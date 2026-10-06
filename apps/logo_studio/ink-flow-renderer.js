(() => {
  "use strict";

  const LOOP_SECONDS = 12;
  const TAU = Math.PI * 2;

  // Fitted to the approved ink artwork and its explicit crop. These curves
  // describe pigment travel, never the image geometry or silhouette.
  const PROFILES = {
    ink: {
      left: [[0.50, 0.02], [0.49, 0.27], [0.12, 0.43], [0.19, 0.69], [0.20, 0.86], [0.31, 0.97], [0.47, 0.985]],
      right: [[0.50, 0.02], [0.65, 0.25], [0.84, 0.46], [0.78, 0.72], [0.74, 0.91], [0.57, 0.985], [0.47, 0.985]],
      divide: [[0, 0.50], [0.16, 0.565], [0.32, 0.615], [0.48, 0.58], [0.63, 0.43], [0.79, 0.295], [0.91, 0.345], [0.985, 0.47], [1, 0.48]],
    },
  };

  function ribbonSegments(points, aspect) {
    const samples = [];
    // Two joined cubic Beziers keep the flow direction smooth through the bend.
    for (let curve = 0; curve < 2; curve += 1) {
      const offset = curve * 3;
      for (let step = curve ? 1 : 0; step <= 24; step += 1) {
        const t = step / 24;
        const u = 1 - t;
        const weights = [u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t];
        let x = 0;
        let y = 0;
        for (let point = 0; point < 4; point += 1) {
          x += weights[point] * points[offset + point][0] * aspect;
          y += weights[point] * points[offset + point][1];
        }
        samples.push([x, y]);
      }
    }
    let total = 0;
    const segments = samples.slice(1).map((point, index) => {
      const start = samples[index];
      const dx = point[0] - start[0];
      const dy = point[1] - start[1];
      const length = Math.hypot(dx, dy);
      const segment = { x: start[0], y: start[1], dx, dy, length, inverseLength: 1 / length, inverseLengthSquared: 1 / (length * length), start: total };
      total += length;
      return segment;
    });
    return { segments, inverseTotal: 1 / total };
  }

  function ribbonCoordinate(x, y, ribbon) {
    let bestDistance = Infinity;
    let along = 0;
    let across = 0;
    for (const segment of ribbon.segments) {
      const px = x - segment.x;
      const py = y - segment.y;
      const projection = (px * segment.dx + py * segment.dy) * segment.inverseLengthSquared;
      const t = projection < 0 ? 0 : projection > 1 ? 1 : projection;
      const dx = px - segment.dx * t;
      const dy = py - segment.dy * t;
      const distance = dx * dx + dy * dy;
      if (distance < bestDistance) {
        bestDistance = distance;
        along = (segment.start + segment.length * t) * ribbon.inverseTotal;
        across = (dx * -segment.dy + dy * segment.dx) * segment.inverseLength;
      }
    }
    return [along, across];
  }

  function separatorAt(y, points) {
    for (let i = 1; i < points.length; i += 1) {
      if (y <= points[i][0]) {
        const a = points[i - 1];
        const b = points[i];
        const t = Math.max(0, Math.min(1, (y - a[0]) / (b[0] - a[0])));
        return a[1] + (b[1] - a[1]) * t;
      }
    }
    return points[points.length - 1][1];
  }

  function makeCoordinates(profile, aspect) {
    // Only a broad colour field uses this map. Linear interpolation provides
    // smooth motion without a dense or expensive per-image CPU calculation.
    const width = 128;
    const height = Math.round(width / aspect);
    const pixels = new Uint8Array(width * height * 4);
    const left = ribbonSegments(profile.left, aspect);
    const right = ribbonSegments(profile.right, aspect);
    const byte = (value) => Math.round(Math.max(0, Math.min(1, value)) * 255);
    for (let y = 0; y < height; y += 1) {
      const py = (y + 0.5) / height;
      const divider = separatorAt(py, profile.divide);
      for (let x = 0; x < width; x += 1) {
        const px = (x + 0.5) / width;
        const a = ribbonCoordinate(px * aspect, py, left);
        const b = ribbonCoordinate(px * aspect, py, right);
        const blend = Math.max(0, Math.min(1, (px - divider) / 0.065 + 0.5));
        const side = blend * blend * (3 - 2 * blend);
        const across = a[1] * (1 - side) + b[1] * side;
        const offset = (y * width + x) * 4;
        // R/G carry independent arc lengths; B selects the ribbon across the
        // existing white river; A carries the signed cross-ribbon coordinate.
        pixels[offset] = byte(a[0]);
        pixels[offset + 1] = byte(b[0]);
        pixels[offset + 2] = byte(side);
        pixels[offset + 3] = byte(0.5 + across / 0.72);
      }
    }
    return { width, height, pixels };
  }

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
    uniform sampler2D uCoordinates;
    uniform vec4 uCrop;
    uniform float uPhase;
    uniform float uStrength;
    uniform float uSlide;

    // Bounded, smooth procedural wash. The source photograph is never warped.
    float hash(vec2 p) {
      p = fract(p * vec2(0.1031, 0.1030));
      p += dot(p, p.yx + 19.19);
      return fract((p.x + p.y) * p.x);
    }
    float noise(vec2 p) {
      vec2 i = floor(p);
      vec2 f = fract(p);
      f = f * f * (3.0 - 2.0 * f);
      return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
                 mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
    }
    void main() {
      vec2 p = vec2(vUv.x, 1.0 - vUv.y);
      // Fixed sampling preserves every original grain and the white river.
      vec4 source = texture2D(uSource, uCrop.xy + p * uCrop.zw);
      float luminance = dot(source.rgb, vec3(0.2126, 0.7152, 0.0722));
      float chroma = max(source.r, max(source.g, source.b)) - min(source.r, min(source.g, source.b));
      // Paper and the pale S remain untouched. Protect near-black contours too;
      // only the existing ink's middle values can accept moving pigment.
      float mask = (1.0 - smoothstep(0.77, 0.93, luminance))
                 * smoothstep(0.035, 0.16, luminance)
                 * (1.0 - smoothstep(0.12, 0.28, chroma)) * source.a;
      vec4 coordinate = texture2D(uCoordinates, p);
      float along = mix(coordinate.r, coordinate.g, coordinate.b);
      float across = coordinate.a * 2.0 - 1.0;
      // A circular noise orbit returns exactly after one cycle, without a
      // discontinuity at the 12-second wrap. Only broad, smooth scales move.
      vec2 orbit = vec2(cos(uPhase), sin(uPhase));
      vec2 field = vec2(across * 2.4, along * 3.8);
      float wash = noise(field + orbit * 0.65) * 0.68
                 + noise(field * 2.05 - orbit * 0.38) * 0.32;
      float bend = 0.17 * across + 0.065 * sin(across * 3.14159265 + along * 3.14159265);
      float sidePhase = (coordinate.b - 0.5) * 0.65 * sin(along * 3.14159265);
      float phase = (along * 1.08 + bend) * 6.28318531 + sidePhase - uPhase;
      float edge = (wash - 0.5) * mix(0.90, 0.60, uSlide);
      float diluteBody = pow(0.5 + 0.5 * cos(phase + edge), mix(1.15, 1.8, uSlide));
      float denseBody = pow(0.5 + 0.5 * cos(phase + 2.75 + edge), mix(1.2, 1.55, uSlide));
      // Multiplicative density and restrained dilution preserve source detail.
      // Equal RGB channels guarantee monochrome pigment (no blue tint).
      float dense = luminance * mix(0.48, 0.28, uSlide);
      float dilute = luminance + (1.0 - luminance) * mix(0.19, 0.34, uSlide);
      float pigment = mix(luminance, dense, denseBody * 0.90);
      pigment = mix(pigment, dilute, diluteBody * 0.88);
      gl_FragColor = vec4(vec3(pigment), mask * uStrength * 0.90);
    }
  `;

  class UtekiInkFlowRenderer {
    constructor(canvas) {
      if (!canvas || typeof canvas.getContext !== "function") {
        throw new TypeError("A canvas is required for ink flow");
      }
      this.canvas = canvas;
      this.ready = false;
      this.disposed = false;
      this.coordinateCache = new Map();
      this.gl = canvas.getContext("webgl", {
        alpha: true,
        premultipliedAlpha: false,
        antialias: false,
        depth: false,
        stencil: false,
        powerPreference: "low-power",
      });
      if (!this.gl) throw new Error("WebGL is unavailable for ink flow");
      const gl = this.gl;
      const shaders = [];
      try {
        const highp = gl.getShaderPrecisionFormat(gl.FRAGMENT_SHADER, gl.HIGH_FLOAT);
        const precision = highp && highp.precision > 0 ? "highp" : "mediump";
        for (const [type, source] of [[gl.VERTEX_SHADER, vertexSource], [gl.FRAGMENT_SHADER, fragmentSource.replace("__PRECISION__", precision)]]) {
          const shader = gl.createShader(type);
          if (!shader) throw new Error("Ink-flow shader allocation failed");
          shaders.push(shader);
          gl.shaderSource(shader, source);
          gl.compileShader(shader);
          if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
            throw new Error(gl.getShaderInfoLog(shader) || "Ink-flow shader compilation failed");
          }
        }
        this.program = gl.createProgram();
        if (!this.program) throw new Error("Ink-flow program allocation failed");
        shaders.forEach((shader) => gl.attachShader(this.program, shader));
        gl.linkProgram(this.program);
        if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) {
          throw new Error(gl.getProgramInfoLog(this.program) || "Ink-flow shader linking failed");
        }
        gl.useProgram(this.program);
        this.buffer = gl.createBuffer();
        if (!this.buffer) throw new Error("Ink-flow buffer allocation failed");
        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
        this.position = gl.getAttribLocation(this.program, "aPosition");
        gl.enableVertexAttribArray(this.position);
        gl.vertexAttribPointer(this.position, 2, gl.FLOAT, false, 0, 0);
        this.texture = this.createTexture(gl.TEXTURE0);
        this.coordinateTexture = this.createTexture(gl.TEXTURE1);
        this.uniforms = Object.fromEntries(["uSource", "uCoordinates", "uCrop", "uPhase", "uStrength", "uSlide"].map((name) => [name, gl.getUniformLocation(this.program, name)]));
        gl.uniform1i(this.uniforms.uSource, 0);
        gl.uniform1i(this.uniforms.uCoordinates, 1);
        this.resize(canvas.width || 1, canvas.height || 1);
        this.checkError("initialisation");
      } catch (error) {
        this.dispose();
        throw error;
      } finally {
        shaders.forEach((shader) => gl.deleteShader(shader));
      }
    }

    createTexture(unit) {
      const gl = this.gl;
      const texture = gl.createTexture();
      if (!texture) throw new Error("Ink-flow texture allocation failed");
      gl.activeTexture(unit);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      return texture;
    }

    checkError(operation) {
      const error = this.gl.getError();
      if (error !== this.gl.NO_ERROR) throw new Error(`Ink-flow ${operation} failed (WebGL ${error})`);
    }

    setImage(image, crop) {
      if (this.disposed) throw new Error("Ink-flow renderer has been disposed");
      const width = image && (typeof image.naturalWidth === "number" ? image.naturalWidth : image.width);
      const height = image && (typeof image.naturalHeight === "number" ? image.naturalHeight : image.height);
      if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0 || image.complete === false) {
        throw new TypeError("A loaded source image is required for ink flow");
      }
      const region = crop === undefined ? [0, 0, width, height] : crop;
      if (!Array.isArray(region) || region.length !== 4 || region.some((value) => !Number.isFinite(value)) ||
          region[0] < 0 || region[1] < 0 || region[2] <= 0 || region[3] <= 0 ||
          region[0] + region[2] > width || region[1] + region[3] > height) {
        throw new RangeError("The ink-flow crop must fit inside the source image");
      }
      const gl = this.gl;
      const maxTexture = gl.getParameter(gl.MAX_TEXTURE_SIZE);
      if (width > maxTexture || height > maxTexture) throw new RangeError("The source image exceeds this device's texture size limit");
      // Select only the known source/crop profiles; the caller explicitly owns
      // material selection. An unknown asset must not silently inherit a map.
      const profileName = width === 1024 && height === 1536 && region.join(",") === "244,286,536,716" ? "ink" : null;
      if (!profileName) throw new RangeError("This logo crop has no ink-flow ribbon profile");
      let coordinates = this.coordinateCache.get(profileName);
      if (!coordinates) {
        coordinates = makeCoordinates(PROFILES[profileName], region[2] / region[3]);
        this.coordinateCache.set(profileName, coordinates);
      }
      if (coordinates.width > maxTexture || coordinates.height > maxTexture) throw new RangeError("The flow map exceeds this device's texture size limit");
      this.ready = false;
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.useProgram(this.program);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, this.coordinateTexture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, coordinates.width, coordinates.height, 0, gl.RGBA, gl.UNSIGNED_BYTE, coordinates.pixels);
      gl.uniform4f(this.uniforms.uCrop, region[0] / width, region[1] / height, region[2] / width, region[3] / height);
      this.checkError("image upload");
      this.ready = true;
    }

    resize(width, height) {
      if (this.disposed) return;
      if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) throw new RangeError("Ink-flow canvas dimensions must be positive");
      const w = Math.max(1, Math.round(width));
      const h = Math.max(1, Math.round(height));
      if (this.canvas.width !== w) this.canvas.width = w;
      if (this.canvas.height !== h) this.canvas.height = h;
      this.gl.viewport(0, 0, w, h);
      this.checkError("resize");
    }

    render({ time = 0, strength = 0.8, mode = "flow" } = {}) {
      if (this.disposed || !this.ready || this.gl.isContextLost()) return;
      if (mode !== "flow" && mode !== "slide") throw new RangeError("Ink-flow mode must be flow or slide");
      const gl = this.gl;
      const seconds = Number.isFinite(time) ? time : 0;
      const phase = ((seconds % LOOP_SECONDS) + LOOP_SECONDS) % LOOP_SECONDS / LOOP_SECONDS * TAU;
      const amount = Number.isFinite(strength) ? Math.max(0, Math.min(1, strength)) : 0;
      gl.useProgram(this.program);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
      gl.enableVertexAttribArray(this.position);
      gl.vertexAttribPointer(this.position, 2, gl.FLOAT, false, 0, 0);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, this.coordinateTexture);
      gl.disable(gl.BLEND);
      gl.disable(gl.DEPTH_TEST);
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
      gl.uniform1f(this.uniforms.uPhase, phase);
      gl.uniform1f(this.uniforms.uStrength, amount);
      gl.uniform1f(this.uniforms.uSlide, mode === "slide" ? 1 : 0);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      this.checkError("render");
    }

    dispose() {
      if (this.disposed) return;
      const gl = this.gl;
      if (gl && !gl.isContextLost()) {
        if (this.texture) gl.deleteTexture(this.texture);
        if (this.coordinateTexture) gl.deleteTexture(this.coordinateTexture);
        if (this.buffer) gl.deleteBuffer(this.buffer);
        if (this.program) gl.deleteProgram(this.program);
      }
      this.coordinateCache.clear();
      this.ready = false;
      this.disposed = true;
    }
  }

  window.UtekiInkFlowRenderer = UtekiInkFlowRenderer;
})();
