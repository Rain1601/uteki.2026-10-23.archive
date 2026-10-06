(() => {
  "use strict";

  const LOOP_SECONDS = 7.5;
  const TAU = Math.PI * 2;

  // These two maps are fitted to the explicitly selected logo crops. They
  // describe the two curved blue ribbons, not a reconstructed drop surface.
  // Each ribbon runs from the tip, around its broad face, to the lower join.
  const PROFILES = {
    glass: {
      left: [[0.50, 0.028], [0.51, 0.25], [0.11, 0.42], [0.15, 0.67], [0.17, 0.82], [0.28, 0.91], [0.44, 0.961]],
      right: [[0.505, 0.028], [0.60, 0.24], [0.86, 0.45], [0.77, 0.70], [0.72, 0.86], [0.56, 0.96], [0.44, 0.961]],
      divide: [[0, 0.50], [0.15, 0.55], [0.30, 0.585], [0.44, 0.525], [0.60, 0.385], [0.74, 0.300], [0.86, 0.330], [0.962, 0.44], [1, 0.48]],
    },
    silk: {
      left: [[0.496, 0.027], [0.51, 0.28], [0.09, 0.42], [0.16, 0.68], [0.20, 0.84], [0.33, 0.94], [0.49, 0.973]],
      right: [[0.496, 0.027], [0.65, 0.26], [0.85, 0.47], [0.79, 0.72], [0.72, 0.91], [0.57, 0.985], [0.49, 0.973]],
      divide: [[0, 0.496], [0.16, 0.555], [0.32, 0.607], [0.48, 0.575], [0.63, 0.445], [0.79, 0.310], [0.90, 0.350], [0.973, 0.49], [1, 0.50]],
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
        // existing white S; A carries the signed cross-ribbon coordinate.
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

    void main() {
      vec2 p = vec2(vUv.x, 1.0 - vUv.y);
      // The image never slides or distorts. Only the colour field moves in the
      // curved ribbon coordinates, leaving the photographed texture in place.
      vec3 source = texture2D(uSource, uCrop.xy + p * uCrop.zw).rgb;
      vec4 coordinate = texture2D(uCoordinates, p);
      float highest = max(source.r, max(source.g, source.b));
      float lowest = min(source.r, min(source.g, source.b));
      float saturation = (highest - lowest) / max(highest, 0.0001);
      float luminance = dot(source, vec3(0.2126, 0.7152, 0.0722));
      float blue = smoothstep(0.025, 0.13, source.b - source.r)
                 * smoothstep(-0.02, 0.075, source.b - source.g);
      float mask = blue * smoothstep(0.12, 0.34, saturation);
      mask *= 1.0 - smoothstep(0.64, 0.86, lowest);
      mask *= 1.0 - smoothstep(0.76, 0.93, luminance);

      float along = mix(coordinate.r, coordinate.g, coordinate.b);
      float across = coordinate.a * 2.0 - 1.0;
      float bend = 0.16 * across + 0.075 * sin(across * 3.14159265 + along * 3.14159265);
      // One large ice-blue body and its deep-blue wake occupy each ribbon.
      // Curved fronts rotate with the underlying arc, rather than scanning
      // vertically across both faces. The offset vanishes at their joined ends.
      float sidePhase = (coordinate.b - 0.5) * 0.62 * sin(along * 3.14159265);
      float phase = (along * 1.10 + bend) * 6.28318531 + sidePhase - uPhase;
      float iceBody = pow(0.5 + 0.5 * cos(phase), 1.7);
      float deepBody = pow(0.5 + 0.5 * cos(phase + 2.65), 1.4);

      vec3 ice = 1.0 - (1.0 - source) * (1.0 - vec3(0.12, 0.58, 0.79));
      vec3 deep = source * vec3(0.38, 0.48, 0.73);
      vec3 colour = mix(source, deep, deepBody * 0.94);
      colour = mix(colour, ice, iceBody * 0.96);
      gl_FragColor = vec4(colour, mask * uStrength * 0.92);
    }
  `;

  class UtekiTextureSlideRenderer {
    constructor(canvas) {
      if (!canvas || typeof canvas.getContext !== "function") {
        throw new TypeError("A canvas is required for texture slide");
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
      if (!this.gl) throw new Error("WebGL is unavailable for texture slide");
      const gl = this.gl;
      const shaders = [];
      try {
        const highp = gl.getShaderPrecisionFormat(gl.FRAGMENT_SHADER, gl.HIGH_FLOAT);
        const precision = highp && highp.precision > 0 ? "highp" : "mediump";
        for (const [type, source] of [[gl.VERTEX_SHADER, vertexSource], [gl.FRAGMENT_SHADER, fragmentSource.replace("__PRECISION__", precision)]]) {
          const shader = gl.createShader(type);
          if (!shader) throw new Error("Texture-slide shader allocation failed");
          shaders.push(shader);
          gl.shaderSource(shader, source);
          gl.compileShader(shader);
          if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
            throw new Error(gl.getShaderInfoLog(shader) || "Texture-slide shader compilation failed");
          }
        }
        this.program = gl.createProgram();
        if (!this.program) throw new Error("Texture-slide program allocation failed");
        shaders.forEach((shader) => gl.attachShader(this.program, shader));
        gl.linkProgram(this.program);
        if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) {
          throw new Error(gl.getProgramInfoLog(this.program) || "Texture-slide shader linking failed");
        }
        gl.useProgram(this.program);
        this.buffer = gl.createBuffer();
        if (!this.buffer) throw new Error("Texture-slide buffer allocation failed");
        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
        this.position = gl.getAttribLocation(this.program, "aPosition");
        gl.enableVertexAttribArray(this.position);
        gl.vertexAttribPointer(this.position, 2, gl.FLOAT, false, 0, 0);
        this.texture = this.createTexture(gl.TEXTURE0);
        this.coordinateTexture = this.createTexture(gl.TEXTURE1);
        this.uniforms = Object.fromEntries(["uSource", "uCoordinates", "uCrop", "uPhase", "uStrength"].map((name) => [name, gl.getUniformLocation(this.program, name)]));
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
      if (!texture) throw new Error("Texture-slide texture allocation failed");
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
      if (error !== this.gl.NO_ERROR) throw new Error(`Texture-slide ${operation} failed (WebGL ${error})`);
    }

    setImage(image, crop) {
      if (this.disposed) throw new Error("Texture-slide renderer has been disposed");
      const width = image && (typeof image.naturalWidth === "number" ? image.naturalWidth : image.width);
      const height = image && (typeof image.naturalHeight === "number" ? image.naturalHeight : image.height);
      if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0 || image.complete === false) {
        throw new TypeError("A loaded source image is required for texture slide");
      }
      const region = crop === undefined ? [0, 0, width, height] : crop;
      if (!Array.isArray(region) || region.length !== 4 || region.some((value) => !Number.isFinite(value)) ||
          region[0] < 0 || region[1] < 0 || region[2] <= 0 || region[3] <= 0 ||
          region[0] + region[2] > width || region[1] + region[3] > height) {
        throw new RangeError("The texture-slide crop must fit inside the source image");
      }
      const gl = this.gl;
      const maxTexture = gl.getParameter(gl.MAX_TEXTURE_SIZE);
      if (width > maxTexture || height > maxTexture) throw new RangeError("The source image exceeds this device's texture size limit");
      // Select only the known source/crop profiles; the caller explicitly owns
      // material selection. An unknown asset must not silently inherit a map.
      let profileName;
      if (width === 1376 && height === 768 && region.join(",") === "272,186,258,342") profileName = "glass";
      if (width === 922 && height === 1152 && region.join(",") === "318,255,292,382") profileName = "silk";
      if (!profileName) throw new RangeError("This logo crop has no texture-slide ribbon profile");
      let coordinates = this.coordinateCache.get(profileName);
      if (!coordinates) {
        coordinates = makeCoordinates(PROFILES[profileName], region[2] / region[3]);
        this.coordinateCache.set(profileName, coordinates);
      }
      if (coordinates.width > maxTexture || coordinates.height > maxTexture) throw new RangeError("The flow map exceeds this device's texture size limit");
      this.ready = false;
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
      if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) throw new RangeError("Texture-slide canvas dimensions must be positive");
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

  window.UtekiTextureSlideRenderer = UtekiTextureSlideRenderer;
})();
