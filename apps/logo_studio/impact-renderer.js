(() => {
  "use strict";

  // Texture-driven 2.5D motion based on the approved ink/blue storyboard.
  // This is an art-directed image animation, not a numerical fluid simulation.
  const DURATION = 10;
  const PADDING = 1.6;
  const vertexSource = `
    attribute vec2 aPosition;
    attribute vec2 aTarget;
    attribute vec2 aScale;
    uniform vec2 uMorph;
    varying __PRECISION__ vec2 vUv;
    varying __PRECISION__ vec2 vScreen;
    varying mediump float vDilution;
    void main() {
      vUv = aPosition;
      vScreen = mix(aPosition, aTarget, uMorph);
      vec2 scale = mix(vec2(1.), aScale, uMorph);
      vDilution = min(1., 1. / max(.001, scale.x * scale.y));
      vec2 p = (vScreen - .5) / 1.6 + .5;
      gl_Position = vec4(p.x * 2. - 1., 1. - p.y * 2., 0., 1.);
    }
  `;
  const fragmentSource = `
    precision __PRECISION__ float;
    varying __PRECISION__ vec2 vUv;
    varying __PRECISION__ vec2 vScreen;
    varying mediump float vDilution;
    uniform sampler2D uSource;
    uniform sampler2D uStoryboard;
    uniform vec4 uCrop;
    uniform vec4 uFall;
    uniform vec4 uUnfold;
    uniform vec4 uUnfoldBounds;
    uniform float uTime;
    uniform float uStrength;

    float rectMask(vec2 p, float feather) {
      vec2 lo = smoothstep(vec2(0.), vec2(feather), p);
      vec2 hi = 1. - smoothstep(vec2(1. - feather), vec2(1.), p);
      return lo.x * lo.y * hi.x * hi.y;
    }
    vec3 sourceAt(vec2 q) {
      float inside = step(0., q.x) * step(q.x, 1.) * step(0., q.y) * step(q.y, 1.);
      vec4 colour = texture2D(uSource, uCrop.xy + clamp(q, 0., 1.) * uCrop.zw);
      return mix(vec3(1.), colour.rgb, colour.a * inside);
    }
    vec3 removePaper(vec3 colour, vec3 paper) {
      // Divide out the warm paper lighting before selecting pigment. Pale
      // filaments survive; empty background becomes exactly white.
      vec3 balanced = clamp(colour / max(paper, vec3(.65)), 0., 1.);
      vec3 pigment = 1. - balanced;
      float signal = max(pigment.r, max(pigment.g, pigment.b));
      return 1. - pigment * smoothstep(.008, .045, signal);
    }
    vec3 fallAt(vec2 q) {
      vec2 at = uFall.xy + clamp(q, 0., 1.) * uFall.zw;
      vec3 paper = texture2D(uStoryboard, uFall.xy + uFall.zw * vec2(.04, .96)).rgb;
      vec3 colour = removePaper(texture2D(uStoryboard, at).rgb, paper);
      return mix(vec3(1.), colour, rectMask(q, .045));
    }
    vec3 unfoldAt(vec2 q) {
      vec2 at = uUnfold.xy + q * uUnfold.zw;
      vec2 local = (at - uUnfoldBounds.xy) / uUnfoldBounds.zw;
      vec2 safeAt = uUnfoldBounds.xy + clamp(local, 0., 1.) * uUnfoldBounds.zw;
      // Caller-selected safe bounds exclude captions and panel dividers.
      // Their clear edges also provide the local paper colour for each row.
      vec2 paperLeft = vec2(uUnfoldBounds.x + uUnfoldBounds.z * .012, safeAt.y);
      vec2 paperRight = vec2(uUnfoldBounds.x + uUnfoldBounds.z * .988, safeAt.y);
      vec3 paper = mix(texture2D(uStoryboard, paperLeft).rgb,
        texture2D(uStoryboard, paperRight).rgb, clamp(local.x, 0., 1.));
      vec3 colour = removePaper(texture2D(uStoryboard, safeAt).rgb, paper);
      return mix(vec3(1.), colour, rectMask(local, .04));
    }
    void main() {
      vec2 q = vUv;
      vec2 p = (q - .5) / 1.6 + .5;
      float t = clamp(uTime, 0., 10.);
      vec3 original = sourceAt(vScreen);
      // The final image is the approved source at its exact original UVs.
      if (t >= 9.5 || uStrength <= .001) {
        gl_FragColor = vec4(original, 1.);
        return;
      }
      float amplitude = mix(.45, 1., uStrength);
      float canvasEdge = rectMask(p, .085);

      // A photographed filament enters progressively beneath the waterline.
      // Small lateral advection preserves the bead's detailed photographic form.
      vec2 fallUv = q;
      fallUv.x += .007 * sin(q.y * 13. - t * .85) * amplitude;
      fallUv.y += .026 * (1. - smoothstep(0., 2.2, t));
      float fallFront = mix(-.14, 1.15, smoothstep(0., 2.55, t));
      float fallReveal = 1. - smoothstep(fallFront - .075, fallFront + .075, q.y);
      float fallOpacity = smoothstep(0., .3, t) * (1. - smoothstep(2.05, 3.7, t));
      vec3 fallPigment = (1. - fallAt(fallUv)) * fallReveal * fallOpacity;

      // Let the source artwork unfurl from top to bottom. Two low-frequency
      // offsets move fine folds locally; there is no global spin, zoom or blob.
      float unfolding = smoothstep(1.85, 5., t);
      float motionEnvelope = smoothstep(1.6, 2.8, t) * (1. - smoothstep(5.5, 8.35, t));
      vec2 unfoldUv = q;
      unfoldUv.x += (.016 * sin(q.y * 7.1 - t * .73)
        + .005 * sin(q.y * 15. + t * .55)) * amplitude * motionEnvelope;
      unfoldUv.y += .011 * sin(q.x * 8.2 - q.y * 2. + t * .62) * amplitude * motionEnvelope;
      float unfoldFront = mix(-.43, 1.48, unfolding);
      float unfoldReveal = 1. - smoothstep(unfoldFront - .15, unfoldFront + .13, q.y);
      float unfoldOpacity = smoothstep(1.8, 3.35, t) * unfoldReveal;
      vec3 unfoldPigment = (1. - unfoldAt(unfoldUv)) * unfoldOpacity;

      // Pigment is now carried by the moving mesh into the target lobes.
      // Keep it visible throughout travel; only refine the channel once the
      // strands have arrived, then settle their material into the source logo.
      float sourcePigment = 1. - min(original.r, min(original.g, original.b));
      float silhouette = smoothstep(.025, .14, sourcePigment);
      float channelSettle = smoothstep(7.8, 8.65, t);
      vec3 ink = fallPigment * (1. - unfoldOpacity * .8)
        + unfoldPigment * vDilution * mix(1., silhouette, channelSettle);
      vec3 colour = 1. - clamp(ink, 0., 1.) * canvasEdge;
      colour = mix(colour, original, smoothstep(8.65, 9.5, t));
      gl_FragColor = vec4(colour, 1.);
    }
  `;

  class UtekiImpactRenderer {
    constructor(canvas) {
      if (!canvas || typeof canvas.getContext !== "function") throw new TypeError("An impact canvas is required");
      this.canvas = canvas;
      this.ready = false;
      this.disposed = false;
      this.gl = canvas.getContext("webgl", {
        // All effects share this canvas; preserve alpha for the overlay modes.
        alpha: true, antialias: false, depth: false, stencil: false,
        premultipliedAlpha: false, powerPreference: "low-power",
      });
      if (!this.gl) throw new Error("WebGL is unavailable for ink impact");
      const gl = this.gl;
      const shaders = [];
      try {
        const highp = gl.getShaderPrecisionFormat(gl.FRAGMENT_SHADER, gl.HIGH_FLOAT);
        const precision = highp && highp.precision > 0 ? "highp" : "mediump";
        for (const [type, source] of [[gl.VERTEX_SHADER, vertexSource.replaceAll("__PRECISION__", precision)], [gl.FRAGMENT_SHADER, fragmentSource.replaceAll("__PRECISION__", precision)]]) {
          const shader = gl.createShader(type);
          if (!shader) throw new Error("Impact shader allocation failed");
          shaders.push(shader);
          gl.shaderSource(shader, source);
          gl.compileShader(shader);
          if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader) || "Impact shader compilation failed");
        }
        this.program = gl.createProgram();
        if (!this.program) throw new Error("Impact program allocation failed");
        shaders.forEach(shader => gl.attachShader(this.program, shader));
        gl.linkProgram(this.program);
        if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(this.program) || "Impact shader linking failed");
        this.buffer = gl.createBuffer();
        this.texture = gl.createTexture();
        this.storyboardTexture = gl.createTexture();
        if (!this.buffer || !this.texture || !this.storyboardTexture) throw new Error("Impact resource allocation failed");
        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(36), gl.STATIC_DRAW);
        for (const [unit, texture] of [[gl.TEXTURE0, this.texture], [gl.TEXTURE1, this.storyboardTexture]]) {
          gl.activeTexture(unit);
          gl.bindTexture(gl.TEXTURE_2D, texture);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        }
        this.position = gl.getAttribLocation(this.program, "aPosition");
        this.target = gl.getAttribLocation(this.program, "aTarget");
        this.scale = gl.getAttribLocation(this.program, "aScale");
        this.uniforms = Object.fromEntries(["uSource", "uStoryboard", "uCrop", "uFall", "uUnfold", "uUnfoldBounds", "uTime", "uStrength", "uMorph"].map(name => [name, gl.getUniformLocation(this.program, name)]));
        gl.useProgram(this.program);
        gl.uniform1i(this.uniforms.uSource, 0);
        gl.uniform1i(this.uniforms.uStoryboard, 1);
        this.resize(canvas.width || 1, canvas.height || 1);
        this.checkError("initialisation");
      } catch (error) {
        this.dispose();
        throw error;
      } finally {
        shaders.forEach(shader => gl.deleteShader(shader));
      }
    }

    checkError(operation) {
      const error = this.gl.getError();
      if (error !== this.gl.NO_ERROR) throw new Error(`Impact ${operation} failed (WebGL ${error})`);
    }

    validateImage(image) {
      if (this.disposed) throw new Error("Impact renderer has been disposed");
      const width = image && (typeof image.naturalWidth === "number" ? image.naturalWidth : image.width);
      const height = image && (typeof image.naturalHeight === "number" ? image.naturalHeight : image.height);
      if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0 || image.complete === false) throw new TypeError("A loaded impact image is required");
      const limit = this.gl.getParameter(this.gl.MAX_TEXTURE_SIZE);
      if (width > limit || height > limit) throw new RangeError("Impact image exceeds this device's texture size limit");
      return [width, height];
    }

    validateCrop(crop, width, height) {
      if (!Array.isArray(crop) || crop.length !== 4 || crop.some(v => !Number.isFinite(v)) || crop[0] < 0 || crop[1] < 0 || crop[2] <= 0 || crop[3] <= 0 || crop[0] + crop[2] > width || crop[1] + crop[3] > height) throw new RangeError("An explicit crop inside the image is required");
      return [crop[0] / width, crop[1] / height, crop[2] / width, crop[3] / height];
    }

    upload(image, texture, unit) {
      const gl = this.gl;
      gl.useProgram(this.program);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
      gl.activeTexture(unit);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
    }

    setImage(image, crop) {
      const [width, height] = this.validateImage(image);
      const normalized = this.validateCrop(crop, width, height);
      this.ready = false;
      this.sourceLoaded = false;
      this.upload(image, this.texture, this.gl.TEXTURE0);
      this.sourceCrop = normalized;
      this.sourceImage = image;
      this.sourcePixelCrop = [...crop];
      this.gl.uniform4f(this.uniforms.uCrop, ...normalized);
      this.checkError("source upload");
      this.sourceLoaded = true;
      if (this.storyboardLoaded) this.rebuildFormation();
    }

    setStoryboard(image, { fall, unfold, unfoldBounds = unfold } = {}) {
      const [width, height] = this.validateImage(image);
      const fallCrop = this.validateCrop(fall, width, height);
      const unfoldCrop = this.validateCrop(unfold, width, height);
      const bounds = this.validateCrop(unfoldBounds, width, height);
      if (unfold[0] < unfoldBounds[0] || unfold[1] < unfoldBounds[1]
        || unfold[0] + unfold[2] > unfoldBounds[0] + unfoldBounds[2]
        || unfold[1] + unfold[3] > unfoldBounds[1] + unfoldBounds[3]) throw new RangeError("Unfold crop must lie inside its safe panel bounds");
      this.ready = false;
      this.storyboardLoaded = false;
      this.upload(image, this.storyboardTexture, this.gl.TEXTURE1);
      this.storyboardCrops = { fall: fallCrop, unfold: unfoldCrop, bounds };
      this.storyboardImage = image;
      this.storyboardPixelCrops = { unfold: [...unfold], bounds: [...unfoldBounds] };
      const gl = this.gl;
      gl.uniform4f(this.uniforms.uFall, ...fallCrop);
      gl.uniform4f(this.uniforms.uUnfold, ...unfoldCrop);
      gl.uniform4f(this.uniforms.uUnfoldBounds, ...bounds);
      this.checkError("storyboard upload");
      this.storyboardLoaded = true;
      if (this.sourceLoaded) this.rebuildFormation();
    }

    rebuildFormation() {
      const mapper = window.UtekiFormationMap;
      if (!mapper) throw new Error("Formation mapping is unavailable");
      // Read the caller-selected images once on upload. These density fields
      // define where the existing strands travel, not a new rendered asset.
      const read = (image) => {
        const surface = document.createElement("canvas");
        surface.width = image.naturalWidth || image.width;
        surface.height = image.naturalHeight || image.height;
        const ctx = surface.getContext("2d", { willReadFrequently: true });
        if (!ctx) throw new Error("Cannot read motion artwork");
        ctx.drawImage(image, 0, 0);
        const pixels = ctx.getImageData(0, 0, surface.width, surface.height);
        surface.width = surface.height = 0;
        return pixels;
      };
      const board = read(this.storyboardImage), logo = read(this.sourceImage);
      const sample = (image, x, y) => {
        x = Math.max(0, Math.min(image.width - 1, x));
        y = Math.max(0, Math.min(image.height - 1, y));
        const x0 = Math.floor(x), y0 = Math.floor(y), fx = x - x0, fy = y - y0;
        const x1 = Math.min(x0 + 1, image.width - 1), y1 = Math.min(y0 + 1, image.height - 1);
        const offsets = [(y0 * image.width + x0) * 4, (y0 * image.width + x1) * 4,
          (y1 * image.width + x0) * 4, (y1 * image.width + x1) * 4];
        return [0, 1, 2].map(c => ((image.data[offsets[0] + c] * (1 - fx) + image.data[offsets[1] + c] * fx) * (1 - fy)
          + (image.data[offsets[2] + c] * (1 - fx) + image.data[offsets[3] + c] * fx) * fy) / 255);
      };
      const smooth = (a, b, v) => { const p = Math.max(0, Math.min(1, (v - a) / (b - a))); return p * p * (3 - 2 * p); };
      const mask = (v, feather) => smooth(0, feather, v) * (1 - smooth(1 - feather, 1, v));
      const width = 192, height = 256;
      const source = new Float32Array(width * height), target = new Float32Array(source.length);
      const [ux, uy, uw, uh] = this.storyboardPixelCrops.unfold;
      const [bx, by, bw, bh] = this.storyboardPixelCrops.bounds;
      const [lx, ly, lw, lh] = this.sourcePixelCrop;
      for (let y = 0; y < height; y++) {
        const qy = -.3 + (y + .5) / height * 1.6;
        const py = uy + qy * uh;
        const paperLeft = sample(board, bx + bw * .012, py);
        const paperRight = sample(board, bx + bw * .988, py);
        for (let x = 0; x < width; x++) {
          const qx = -.3 + (x + .5) / width * 1.6, index = y * width + x;
          const px = ux + qx * uw, localX = (px - bx) / bw, localY = (py - by) / bh;
          if (localX > 0 && localX < 1 && localY > 0 && localY < 1) {
            const rgb = sample(board, px, py);
            const pigment = Math.max(...rgb.map((v, c) => 1 - Math.min(1, v / Math.max(.65, paperLeft[c] * (1 - localX) + paperRight[c] * localX))));
            source[index] = Math.pow(pigment * smooth(.008, .045, pigment), .65)
              * mask(localX, .04) * mask(localY, .04) * mask((x + .5) / width, .085) * mask((y + .5) / height, .085);
          }
          if (qx >= 0 && qx <= 1 && qy >= 0 && qy <= 1) {
            const pigment = 1 - Math.min(...sample(logo, lx + qx * lw, ly + qy * lh));
            target[index] = Math.pow(pigment, .65) * smooth(.025, .075, pigment);
          }
        }
      }
      const columns = 112, rows = 144;
      const geometry = mapper.build({ source, target, width, height,
        bounds: { left: -.3, top: -.3, width: 1.6, height: 1.6 }, columns, rows });
      // Average area gradients at shared vertices: expansion dilutes pigment,
      // and adjacent triangles must not produce visibly different opacities.
      const vertices = new Float32Array(geometry.count * 6);
      const scaleSums = new Float64Array((columns + 1) * (rows + 1) * 3);
      const pointIndex = at => (Math.round((geometry.vertices[at + 1] + .3) / 1.6 * rows) * (columns + 1)
        + Math.round((geometry.vertices[at] + .3) / 1.6 * columns)) * 3;
      for (let i = 0; i < geometry.count; i += 3) {
        const a = i * 4, b = a + 4, c = a + 8, v = geometry.vertices;
        const ax = v[b] - v[a], ay = v[b + 1] - v[a + 1];
        const bx = v[c] - v[a], by = v[c + 1] - v[a + 1];
        const det = ax * by - bx * ay;
        const scaleX = ((v[b + 2] - v[a + 2]) * by - (v[c + 2] - v[a + 2]) * ay) / det;
        const scaleY = (ax * (v[c + 3] - v[a + 3]) - bx * (v[b + 3] - v[a + 3])) / det;
        for (let j = 0; j < 3; j++) {
          const at = pointIndex((i + j) * 4);
          scaleSums[at] += Math.max(.001, scaleX);
          scaleSums[at + 1] += Math.max(.001, scaleY);
          scaleSums[at + 2]++;
        }
      }
      for (let i = 0; i < geometry.count; i++) {
        const at = pointIndex(i * 4), offset = i * 6;
        vertices.set(geometry.vertices.subarray(i * 4, i * 4 + 4), offset);
        vertices[offset + 4] = scaleSums[at] / scaleSums[at + 2];
        vertices[offset + 5] = scaleSums[at + 1] / scaleSums[at + 2];
      }
      this.gl.bindBuffer(this.gl.ARRAY_BUFFER, this.buffer);
      this.gl.bufferData(this.gl.ARRAY_BUFFER, vertices, this.gl.STATIC_DRAW);
      this.vertexCount = geometry.count;
      this.checkError("formation upload");
      this.ready = true;
    }

    resize(width, height) {
      if (this.disposed) return;
      if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) throw new RangeError("Impact canvas dimensions must be positive");
      const w = Math.max(1, Math.round(width)), h = Math.max(1, Math.round(height));
      if (this.canvas.width !== w) this.canvas.width = w;
      if (this.canvas.height !== h) this.canvas.height = h;
      this.gl.viewport(0, 0, w, h);
      this.checkError("resize");
    }

    render({ time = 0, strength = .8 } = {}) {
      if (this.disposed || !this.ready || this.gl.isContextLost()) return;
      const gl = this.gl;
      gl.useProgram(this.program);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
      gl.enableVertexAttribArray(this.position);
      gl.vertexAttribPointer(this.position, 2, gl.FLOAT, false, 24, 0);
      gl.enableVertexAttribArray(this.target);
      gl.vertexAttribPointer(this.target, 2, gl.FLOAT, false, 24, 8);
      gl.enableVertexAttribArray(this.scale);
      gl.vertexAttribPointer(this.scale, 2, gl.FLOAT, false, 24, 16);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, this.storyboardTexture);
      gl.disable(gl.BLEND);
      gl.disable(gl.SCISSOR_TEST);
      gl.disable(gl.CULL_FACE);
      gl.colorMask(true, true, true, true);
      gl.disable(gl.DEPTH_TEST);
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
      const seconds = Number.isFinite(time) ? Math.max(0, Math.min(DURATION, time)) : 0;
      gl.uniform1f(this.uniforms.uTime, seconds);
      const ease = (start, end) => { const p = Math.max(0, Math.min(1, (seconds - start) / (end - start))); return p * p * (3 - 2 * p); };
      gl.uniform2f(this.uniforms.uMorph, ease(5.85, 8.65), ease(5.5, 8.35));
      gl.uniform1f(this.uniforms.uStrength, Number.isFinite(strength) ? Math.max(0, Math.min(1, strength)) : 0);
      gl.uniform1i(this.uniforms.uSource, 0);
      gl.uniform1i(this.uniforms.uStoryboard, 1);
      gl.uniform4f(this.uniforms.uCrop, ...this.sourceCrop);
      gl.uniform4f(this.uniforms.uFall, ...this.storyboardCrops.fall);
      gl.uniform4f(this.uniforms.uUnfold, ...this.storyboardCrops.unfold);
      gl.uniform4f(this.uniforms.uUnfoldBounds, ...this.storyboardCrops.bounds);
      gl.clearColor(1, 1, 1, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLES, 0, this.vertexCount);
      this.checkError("render");
    }

    dispose() {
      if (this.disposed) return;
      const gl = this.gl;
      if (gl && !gl.isContextLost()) {
        if (Number.isInteger(this.target) && this.target >= 0) gl.disableVertexAttribArray(this.target);
        if (Number.isInteger(this.scale) && this.scale >= 0) gl.disableVertexAttribArray(this.scale);
        if (this.texture) gl.deleteTexture(this.texture);
        if (this.storyboardTexture) gl.deleteTexture(this.storyboardTexture);
        if (this.buffer) gl.deleteBuffer(this.buffer);
        if (this.program) gl.deleteProgram(this.program);
      }
      this.ready = false;
      this.sourceLoaded = false;
      this.storyboardLoaded = false;
      this.disposed = true;
    }
  }
  UtekiImpactRenderer.DURATION = DURATION;
  UtekiImpactRenderer.PADDING = PADDING;
  window.UtekiImpactRenderer = UtekiImpactRenderer;
})();
