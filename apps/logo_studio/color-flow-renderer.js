(() => {
  "use strict";

  const LOOP_SECONDS = 6;
  const vertexSource = `
    attribute vec2 aPosition;
    varying vec2 vUv;
    void main() {
      vUv = aPosition * 0.5 + 0.5;
      gl_Position = vec4(aPosition, 0.0, 1.0);
    }
  `;
  const fragmentSource = `
    precision __PRECISION__ float;
    varying vec2 vUv;
    uniform sampler2D uSource;
    uniform vec4 uCrop;
    uniform float uPhase;
    uniform float uStrength;

    void main() {
      // Only the colour changes. Every frame reads the very same source pixel;
      // no displacement, reconstructed surface, blur, or moving light texture.
      vec2 p = vec2(vUv.x, 1.0 - vUv.y);
      vec3 source = texture2D(uSource, uCrop.xy + p * uCrop.zw).rgb;
      float highest = max(source.r, max(source.g, source.b));
      float lowest = min(source.r, min(source.g, source.b));
      float saturation = (highest - lowest) / max(highest, 0.0001);
      float luminance = dot(source, vec3(0.2126, 0.7152, 0.0722));

      // Smooth colour eligibility, not a silhouette mask. Neutral JPEG paper,
      // the white S opening, and near-white specular pixels stay transparent.
      float blue = smoothstep(0.025, 0.13, source.b - source.r)
                 * smoothstep(-0.02, 0.075, source.b - source.g);
      float mask = blue * smoothstep(0.12, 0.34, saturation);
      mask *= 1.0 - smoothstep(0.64, 0.86, lowest);
      mask *= 1.0 - smoothstep(0.76, 0.93, luminance);

      // A curved colour front travels from tip to base. More than one phase
      // fits inside the drop, so a bright region and its dark wake are visible
      // together instead of the whole mark simply breathing. Both lobes follow
      // the same direction with an offset; the source UV never moves.
      float bend = sin(p.y * 3.14159265) * (p.x - 0.5) * 2.0;
      float path = p.y * 8.8 + (p.x - 0.5) * 2.8 + bend;
      float crest = pow(0.5 + 0.5 * cos(path - uPhase), 2.0);
      float wake = pow(0.5 + 0.5 * cos(path - uPhase + 1.8), 2.0);

      // Screen a blue-cyan tint into the photographic colour, then deepen the
      // trailing blue. Unlike flat replacement colours, these operations keep
      // local differences from the original glass texture at every phase.
      vec3 ice = 1.0 - (1.0 - source) * (1.0 - vec3(0.10, 0.58, 0.76));
      vec3 deep = source * vec3(0.48, 0.57, 0.78);
      vec3 colour = mix(source, deep, wake * 0.85);
      colour = mix(colour, ice, crest * 0.90);
      gl_FragColor = vec4(colour, mask * uStrength * 0.85);
    }
  `;

  class UtekiColorFlowRenderer {
    constructor(canvas) {
      if (!canvas || typeof canvas.getContext !== "function") {
        throw new TypeError("A canvas is required for colour flow");
      }
      this.canvas = canvas;
      this.ready = false;
      this.disposed = false;
      this.gl = canvas.getContext("webgl", {
        alpha: true,
        premultipliedAlpha: false,
        antialias: false,
        depth: false,
        stencil: false,
        powerPreference: "low-power",
      });
      if (!this.gl) throw new Error("WebGL is unavailable for colour flow");
      const gl = this.gl;
      const shaders = [];
      try {
        const highp = gl.getShaderPrecisionFormat(gl.FRAGMENT_SHADER, gl.HIGH_FLOAT);
        const precision = highp && highp.precision > 0 ? "highp" : "mediump";
        for (const [type, source] of [
          [gl.VERTEX_SHADER, vertexSource],
          [gl.FRAGMENT_SHADER, fragmentSource.replace("__PRECISION__", precision)],
        ]) {
          const shader = gl.createShader(type);
          if (!shader) throw new Error("Colour-flow shader allocation failed");
          shaders.push(shader);
          gl.shaderSource(shader, source);
          gl.compileShader(shader);
          if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
            throw new Error(gl.getShaderInfoLog(shader) || "Colour-flow shader compilation failed");
          }
        }
        this.program = gl.createProgram();
        if (!this.program) throw new Error("Colour-flow program allocation failed");
        shaders.forEach((shader) => gl.attachShader(this.program, shader));
        gl.linkProgram(this.program);
        if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) {
          throw new Error(gl.getProgramInfoLog(this.program) || "Colour-flow shader linking failed");
        }
        gl.useProgram(this.program);
        this.buffer = gl.createBuffer();
        if (!this.buffer) throw new Error("Colour-flow buffer allocation failed");
        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
        this.position = gl.getAttribLocation(this.program, "aPosition");
        gl.enableVertexAttribArray(this.position);
        gl.vertexAttribPointer(this.position, 2, gl.FLOAT, false, 0, 0);
        this.texture = gl.createTexture();
        if (!this.texture) throw new Error("Colour-flow texture allocation failed");
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, this.texture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        this.uniforms = Object.fromEntries(["uSource", "uCrop", "uPhase", "uStrength"].map((name) => [name, gl.getUniformLocation(this.program, name)]));
        gl.uniform1i(this.uniforms.uSource, 0);
        this.resize(canvas.width || 1, canvas.height || 1);
        this.checkError("initialisation");
      } catch (error) {
        this.dispose();
        throw error;
      } finally {
        shaders.forEach((shader) => gl.deleteShader(shader));
      }
    }

    checkError(operation) {
      const error = this.gl.getError();
      if (error !== this.gl.NO_ERROR) {
        throw new Error(`Colour-flow ${operation} failed (WebGL ${error})`);
      }
    }

    // crop is [left, top, width, height] in original image pixels. The caller
    // aligns this canvas with that same crop of the always-visible photograph.
    setImage(image, crop) {
      if (this.disposed) throw new Error("Colour-flow renderer has been disposed");
      const width = image && (typeof image.naturalWidth === "number" ? image.naturalWidth : image.width);
      const height = image && (typeof image.naturalHeight === "number" ? image.naturalHeight : image.height);
      if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0 || image.complete === false) {
        throw new TypeError("A loaded source image is required for colour flow");
      }
      const region = crop === undefined ? [0, 0, width, height] : crop;
      if (!Array.isArray(region) || region.length !== 4 || region.some((value) => !Number.isFinite(value)) ||
          region[0] < 0 || region[1] < 0 || region[2] <= 0 || region[3] <= 0 ||
          region[0] + region[2] > width || region[1] + region[3] > height) {
        throw new RangeError("The colour-flow crop must fit inside the source image");
      }
      const gl = this.gl;
      const maxTexture = gl.getParameter(gl.MAX_TEXTURE_SIZE);
      if (width > maxTexture || height > maxTexture) {
        throw new RangeError("The source image exceeds this device's texture size limit");
      }
      this.ready = false;
      gl.useProgram(this.program);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
      gl.uniform4f(this.uniforms.uCrop, region[0] / width, region[1] / height, region[2] / width, region[3] / height);
      this.checkError("image upload");
      this.ready = true;
    }

    // Dimensions are drawing-buffer pixels; the caller includes its DPR.
    resize(width, height) {
      if (this.disposed) return;
      if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
        throw new RangeError("Colour-flow canvas dimensions must be positive");
      }
      const w = Math.max(1, Math.round(width));
      const h = Math.max(1, Math.round(height));
      if (this.canvas.width !== w) this.canvas.width = w;
      if (this.canvas.height !== h) this.canvas.height = h;
      this.gl.viewport(0, 0, w, h);
      this.checkError("resize");
    }

    render({ time = 0, strength = 0.8 } = {}) {
      if (this.disposed || !this.ready || this.gl.isContextLost()) return;
      const gl = this.gl;
      const seconds = Number.isFinite(time) ? time : 0;
      // Bound the phase on the CPU so long sessions retain smooth precision.
      const phase = ((seconds % LOOP_SECONDS) + LOOP_SECONDS) % LOOP_SECONDS / LOOP_SECONDS * Math.PI * 2;
      const amount = Number.isFinite(strength) ? Math.max(0, Math.min(1, strength)) : 0;
      gl.useProgram(this.program);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
      gl.enableVertexAttribArray(this.position);
      gl.vertexAttribPointer(this.position, 2, gl.FLOAT, false, 0, 0);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
      gl.disable(gl.BLEND);
      gl.disable(gl.DEPTH_TEST);
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
      gl.uniform1f(this.uniforms.uPhase, phase);
      gl.uniform1f(this.uniforms.uStrength, amount);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      this.checkError("render");
    }

    dispose() {
      if (this.disposed) return;
      const gl = this.gl;
      if (gl && !gl.isContextLost()) {
        if (this.texture) gl.deleteTexture(this.texture);
        if (this.buffer) gl.deleteBuffer(this.buffer);
        if (this.program) gl.deleteProgram(this.program);
      }
      this.ready = false;
      this.disposed = true;
    }
  }

  window.UtekiColorFlowRenderer = UtekiColorFlowRenderer;
})();
