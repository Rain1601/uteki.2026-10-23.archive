(() => {
  "use strict";

  // A silhouette-derived volume. The source JPEG supplies only the outline;
  // all surface depth, normals, absorption and reflections are rendered live.
  const FIELD_SIZE = 384;
  const vertexSource = `
    attribute vec2 aPosition;
    varying vec2 vUv;
    void main() {
      vUv = aPosition * 0.5 + 0.5;
      gl_Position = vec4(aPosition, 0.0, 1.0);
    }
  `;
  const fragmentSource = `
    precision highp float;
    varying vec2 vUv;
    uniform sampler2D uField;
    uniform float uTime;
    uniform float uMode;
    uniform float uGlass;
    uniform float uAspect;
    uniform float uPixel;
    uniform vec2 uPointer;

    mat2 turn(float a) { return mat2(cos(a), -sin(a), sin(a), cos(a)); }
    float outline(vec2 p) {
      vec2 uv = vec2(p.x, -p.y) * 0.5 + 0.5;
      vec2 bounded = clamp(uv, 0.0014, 0.9986);
      vec2 rg = texture2D(uField, bounded).rg;
      float d = (rg.r * 65280.0 + rg.g * 255.0) / 65535.0 * 2.0 - 1.0;
      return d + length(uv - bounded) * 2.0;
    }
    vec3 local(vec3 p) {
      float isBreath = step(1.5, uMode);
      float yaw = sin(uTime * 0.35) * 0.075 + uPointer.x * 0.045;
      float pitch = sin(uTime * 0.23 + 0.7) * 0.021 - uPointer.y * 0.035;
      p.xz = turn(yaw) * p.xz;
      p.yz = turn(pitch) * p.yz;
      p.xy /= 1.0 + isBreath * sin(uTime * 0.72) * 0.012;
      return p;
    }
    float volume(vec3 p) {
      p = local(p);
      float d = outline(p.xy);
      float isBreath = step(1.5, uMode);
      float isWave = step(0.5, uMode) * (1.0 - isBreath);
      // A rounded cross-section, anchored at the original silhouette. Motion
      // changes the real depth of that section, so its normals move with it.
      float swell = 1.0 + isBreath * sin(uTime * 0.72) * 0.13;
      swell += isWave * sin(p.y * 3.1 - uTime * 0.76) * 0.085;
      swell += (1.0 - isBreath - isWave) * sin(p.y * 2.3 - uTime * 0.48) * 0.038;
      float radius = 0.29;
      float depth = 0.74 * swell;
      return (length(vec2(max(d + radius, 0.0), p.z / depth)) - radius) * 0.68;
    }
    vec3 normalAt(vec3 p) {
      const float e = 0.0065;
      return normalize(vec3(
        volume(p + vec3(e, 0.0, 0.0)) - volume(p - vec3(e, 0.0, 0.0)),
        volume(p + vec3(0.0, e, 0.0)) - volume(p - vec3(0.0, e, 0.0)),
        volume(p + vec3(0.0, 0.0, e)) - volume(p - vec3(0.0, 0.0, e))
      ));
    }
    float boxLight(vec2 p, vec2 center, vec2 halfSize, float softness) {
      vec2 q = abs(p - center) - halfSize;
      float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0);
      return 1.0 - smoothstep(-softness, softness, d);
    }
    vec3 environment(vec3 r) {
      // An intentionally sparse photographic studio: two large softboxes,
      // a pale ceiling and a deep blue side wall. No procedural light stripes.
      r.xz = turn(sin(uTime * 0.24) * 0.21 + uPointer.x * 0.16) * r.xz;
      vec3 sky = mix(vec3(0.18, 0.31, 0.50), vec3(0.86, 0.93, 1.0), smoothstep(-0.7, 0.9, r.y));
      sky *= 0.62 + 0.38 * smoothstep(-0.65, 0.65, r.z);
      vec2 projected = r.xy / max(r.z, 0.08);
      float front = smoothstep(0.03, 0.28, r.z);
      float lightTravel = sin(uTime * 0.42) * 0.38;
      float key = boxLight(projected, vec2(-0.58 + lightTravel, 0.65), vec2(0.32, 1.35), 0.16) * front;
      float fill = boxLight(projected, vec2(1.65, 0.15), vec2(0.52, 1.75), 0.46) * front;
      float overhead = pow(max(dot(r, normalize(vec3(-0.15, 1.0, 0.45))), 0.0), 10.0);
      return sky + vec3(6.6, 6.96, 7.2) * key + vec3(2.46, 3.36, 4.2) * fill + vec3(0.45, 0.52, 0.6) * overhead;
    }
    void main() {
      vec2 screen = (vUv - 0.5) * vec2(uAspect, 1.0) * 2.035;
      // Most of the transparent canvas never enters the marching loop.
      if (outline(screen) > 0.07) { gl_FragColor = vec4(0.0); return; }
      vec3 ro = vec3(screen, 0.42);
      vec3 rd = vec3(0.0, 0.0, -1.0);
      float travel = 0.0;
      float nearest = 2.0;
      vec3 best = ro;
      bool hit = false;
      for (int i = 0; i < 74; i++) {
        vec3 p = ro + rd * travel;
        float d = volume(p);
        if (d < nearest) { nearest = d; best = p; }
        if (d < 0.00065) { hit = true; break; }
        travel += max(d, 0.00045);
        if (travel > 0.86) break;
      }
      float alpha = hit ? 1.0 : 1.0 - smoothstep(0.00065, max(0.0014, uPixel * 0.53), nearest);
      if (alpha < 0.01) { gl_FragColor = vec4(0.0); return; }
      vec3 p = best;
      vec3 n = normalAt(p);
      vec3 v = -rd;
      float facing = clamp(dot(n, v), 0.0, 1.0);
      float fresnel = 0.045 + 0.955 * pow(1.0 - facing, 4.5);
      vec3 lp = local(p);
      float thickness = max(0.015, abs(lp.z) * 2.0);
      // Beer-Lambert absorption makes the thin edge icy and the thicker
      // centre cobalt. Refraction samples a broad studio environment.
      vec3 transmittedRay = refract(rd, n, 1.0 / 1.46);
      vec3 transmittedEnvironment = environment(normalize(vec3(-transmittedRay.xy * 1.55, 0.9)));
      vec3 absorption = exp(-vec3(6.2, 1.8, 0.95) * thickness * 1.65);
      vec3 transmission = absorption * (vec3(0.69, 0.84, 1.0) + transmittedEnvironment * 0.20);
      vec3 reflected = environment(reflect(rd, n));
      float diffuse = max(dot(n, normalize(vec3(-0.6, 0.8, 1.1))), 0.0);
      vec3 body = transmission * (0.73 + 0.27 * diffuse);
      // A little multiple-scattering colour keeps the thickest folds blue.
      body += vec3(0.005, 0.035, 0.10) * (1.0 - absorption);
      vec3 glass = mix(body, reflected, fresnel * 0.76);
      // The second original silhouette uses a softly polished finish.
      vec3 satin = body * 0.92 + reflected * (0.055 + 0.15 * pow(1.0 - facing, 2.0));
      vec3 color = mix(satin, glass, uGlass);
      color = color / (vec3(1.0) + max(color - 1.0, 0.0) * 0.65);
      color = pow(clamp(color, 0.0, 1.0), vec3(0.87));
      gl_FragColor = vec4(color, alpha);
    }
  `;

  // Exact squared Euclidean distance transform, separable in x and y.
  function distanceTransform(binary, target, size) {
    const grid = new Float64Array(size * size);
    const f = new Float64Array(size);
    const out = new Float64Array(size);
    const vertices = new Int32Array(size);
    const edges = new Float64Array(size + 1);
    const far = 1e8;
    function line() {
      let k = 0;
      vertices[0] = 0;
      edges[0] = -Infinity;
      edges[1] = Infinity;
      for (let q = 1; q < size; q++) {
        let s;
        do {
          const v = vertices[k];
          s = ((f[q] + q * q) - (f[v] + v * v)) / (2 * q - 2 * v);
          if (s <= edges[k]) k--;
          else break;
        } while (k >= 0);
        k++;
        vertices[k] = q;
        edges[k] = s;
        edges[k + 1] = Infinity;
      }
      k = 0;
      for (let q = 0; q < size; q++) {
        while (edges[k + 1] < q) k++;
        const delta = q - vertices[k];
        out[q] = delta * delta + f[vertices[k]];
      }
    }
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) f[x] = binary[y * size + x] === target ? 0 : far;
      line();
      for (let x = 0; x < size; x++) grid[y * size + x] = out[x];
    }
    for (let x = 0; x < size; x++) {
      for (let y = 0; y < size; y++) f[y] = grid[y * size + x];
      line();
      for (let y = 0; y < size; y++) grid[y * size + x] = out[y];
    }
    return grid;
  }

  function silhouetteField(image, crop) {
    const size = FIELD_SIZE;
    const helper = document.createElement("canvas");
    helper.width = helper.height = size;
    const ctx = helper.getContext("2d", { willReadFrequently: true });
    if (!ctx) throw new Error("Canvas image decoding unavailable");
    ctx.fillStyle = "white";
    ctx.fillRect(0, 0, size, size);
    const ratio = crop[2] / crop[3];
    const height = size * 0.97 / Math.max(1, ratio);
    const width = height * ratio;
    ctx.drawImage(image, ...crop, (size - width) / 2, (size - height) / 2, width, height);
    const pixels = ctx.getImageData(0, 0, size, size).data;
    const inside = new Uint8Array(size * size);
    let count = 0;
    for (let i = 0; i < inside.length; i++) {
      const r = pixels[i * 4];
      const g = pixels[i * 4 + 1];
      const b = pixels[i * 4 + 2];
      const min = Math.min(r, g, b);
      const chroma = Math.max(r, g, b) - min;
      inside[i] = min < 234 || (min < 247 && chroma > 12) ? 1 : 0;
      count += inside[i];
    }
    if (count < 60 || count > inside.length * 0.9) throw new Error("The crop does not contain a usable white-background silhouette");
    // Classify white components: the central S may be enclosed at its tip.
    // Keep all substantial white regions; only fill tiny specular flecks.
    const outside = new Uint8Array(size * size);
    const queue = new Int32Array(size * size);
    let head = 0;
    let tail = 0;
    function push(i) {
      if (!inside[i] && !outside[i]) { outside[i] = 1; queue[tail++] = i; }
    }
    for (let x = 0; x < size; x++) { push(x); push((size - 1) * size + x); }
    for (let y = 0; y < size; y++) { push(y * size); push(y * size + size - 1); }
    while (head < tail) {
      const i = queue[head++];
      const x = i % size;
      const y = Math.floor(i / size);
      if (x > 0) push(i - 1);
      if (x < size - 1) push(i + 1);
      if (y > 0) push(i - size);
      if (y < size - 1) push(i + size);
    }
    for (let start = 0; start < inside.length; start++) {
      if (inside[start] || outside[start]) continue;
      head = 0;
      tail = 0;
      push(start);
      while (head < tail) {
        const i = queue[head++];
        const x = i % size;
        const y = Math.floor(i / size);
        if (x > 0) push(i - 1);
        if (x < size - 1) push(i + 1);
        if (y > 0) push(i - size);
        if (y < size - 1) push(i + size);
      }
      if (tail <= 12) for (let j = 0; j < tail; j++) inside[queue[j]] = 1;
    }
    const toInside = distanceTransform(inside, 1, size);
    const toOutside = distanceTransform(inside, 0, size);
    let distances = new Float32Array(size * size);
    for (let i = 0; i < inside.length; i++) {
      distances[i] = (inside[i] ? -(Math.sqrt(toOutside[i]) - 0.5) : Math.sqrt(toInside[i]) - 0.5) * 2 / size;
    }
    // Smooth the distance values, not the source mask. Two small Gaussian
    // passes remove pixel-step normals while retaining the generous S opening.
    const horizontal = new Float32Array(size * size);
    let vertical = new Float32Array(size * size);
    for (let pass = 0; pass < 2; pass++) {
      for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
          const i = y * size + x;
          horizontal[i] = (distances[y * size + Math.max(0, x - 1)] + 2 * distances[i] + distances[y * size + Math.min(size - 1, x + 1)]) * 0.25;
        }
      }
      for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
          const i = y * size + x;
          vertical[i] = (horizontal[Math.max(0, y - 1) * size + x] + 2 * horizontal[i] + horizontal[Math.min(size - 1, y + 1) * size + x]) * 0.25;
        }
      }
      const previous = distances;
      distances = vertical;
      vertical = previous;
    }
    const rgba = new Uint8Array(size * size * 4);
    for (let i = 0; i < inside.length; i++) {
      const encoded = Math.round(Math.min(1, Math.max(0, distances[i] * 0.5 + 0.5)) * 65535);
      rgba[i * 4] = encoded >> 8;
      rgba[i * 4 + 1] = encoded & 255;
      rgba[i * 4 + 2] = inside[i] * 255;
      rgba[i * 4 + 3] = 255;
    }
    return rgba;
  }

  class UtekiVolumeRenderer {
    constructor(canvas) {
      this.canvas = canvas;
      this.ready = false;
      this.disposed = false;
      this.gl = canvas.getContext("webgl", { alpha: true, premultipliedAlpha: false, antialias: false, depth: false, powerPreference: "high-performance" });
      if (!this.gl) throw new Error("WebGL unavailable");
      const gl = this.gl;
      const shaders = [];
      try {
        for (const [type, source] of [[gl.VERTEX_SHADER, vertexSource], [gl.FRAGMENT_SHADER, fragmentSource]]) {
          const shader = gl.createShader(type);
          if (!shader) throw new Error("Shader allocation failed");
          shaders.push(shader);
          gl.shaderSource(shader, source);
          gl.compileShader(shader);
          if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader) || "Volume shader compilation failed");
        }
        this.program = gl.createProgram();
        if (!this.program) throw new Error("Program allocation failed");
        shaders.forEach((shader) => gl.attachShader(this.program, shader));
        gl.linkProgram(this.program);
        if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(this.program) || "Volume shader linking failed");
        gl.useProgram(this.program);
        this.buffer = gl.createBuffer();
        if (!this.buffer) throw new Error("Buffer allocation failed");
        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
        this.position = gl.getAttribLocation(this.program, "aPosition");
        gl.enableVertexAttribArray(this.position);
        gl.vertexAttribPointer(this.position, 2, gl.FLOAT, false, 0, 0);
        this.texture = gl.createTexture();
        if (!this.texture) throw new Error("Texture allocation failed");
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, this.texture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        this.uniforms = Object.fromEntries(["uField", "uTime", "uMode", "uGlass", "uAspect", "uPixel", "uPointer"].map((name) => [name, gl.getUniformLocation(this.program, name)]));
        gl.uniform1i(this.uniforms.uField, 0);
        this.resize(canvas.width || 1, canvas.height || 1);
      } catch (error) {
        this.dispose();
        throw error;
      } finally {
        shaders.forEach((shader) => gl.deleteShader(shader));
      }
    }

    setImage(image, crop, materialName) {
      if (this.disposed) throw new Error("Renderer has been disposed");
      if (!image || !Array.isArray(crop) || crop.length !== 4 || crop.some((v) => !Number.isFinite(v)) || crop[0] < 0 || crop[1] < 0 || crop[2] <= 0 || crop[3] <= 0) throw new Error("A loaded image and a valid crop are required");
      const width = image.naturalWidth || image.width;
      const height = image.naturalHeight || image.height;
      if (!width || !height || crop[0] + crop[2] > width || crop[1] + crop[3] > height) throw new Error("The crop exceeds the loaded source image");
      const field = silhouetteField(image, crop);
      const gl = this.gl;
      gl.useProgram(this.program);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, FIELD_SIZE, FIELD_SIZE, 0, gl.RGBA, gl.UNSIGNED_BYTE, field);
      if (gl.getError() !== gl.NO_ERROR) throw new Error("Volume distance texture upload failed");
      gl.uniform1f(this.uniforms.uGlass, materialName === "silk" ? 0 : 1);
      this.ready = true;
    }

    // width and height are drawing-buffer pixels, including the caller's DPR.
    resize(width, height) {
      if (this.disposed) return;
      this.canvas.width = Math.max(1, Math.round(Number(width) || 1));
      this.canvas.height = Math.max(1, Math.round(Number(height) || 1));
      this.gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    }

    render({ time = 0, mode = "drift", pointer = { x: 0, y: 0 } } = {}) {
      if (this.disposed || !this.ready || this.gl.isContextLost()) return;
      const gl = this.gl;
      const u = this.uniforms;
      gl.useProgram(this.program);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
      gl.enableVertexAttribArray(this.position);
      gl.vertexAttribPointer(this.position, 2, gl.FLOAT, false, 0, 0);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
      gl.disable(gl.BLEND);
      gl.disable(gl.DEPTH_TEST);
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
      gl.uniform1f(u.uTime, Number.isFinite(time) ? time : 0);
      gl.uniform1f(u.uMode, mode === "ripple" ? 1 : mode === "breathe" ? 2 : 0);
      gl.uniform1f(u.uAspect, this.canvas.width / this.canvas.height);
      gl.uniform1f(u.uPixel, 2.035 / this.canvas.height);
      gl.uniform2f(u.uPointer, Math.max(-1, Math.min(1, Number(pointer.x) || 0)), Math.max(-1, Math.min(1, Number(pointer.y) || 0)));
      gl.drawArrays(gl.TRIANGLES, 0, 6);
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

  window.UtekiVolumeRenderer = UtekiVolumeRenderer;
})();
