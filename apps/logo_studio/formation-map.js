(() => {
  "use strict";

  // A small uniform mass keeps the empty paper attached to the image boundary.
  // It also prevents zero-width cells when either artwork has blank rows.
  const PAPER_MASS = 0.03;

  function gaussian(sigma) {
    const radius = Math.ceil(sigma * 3);
    const weights = new Float64Array(radius * 2 + 1);
    let total = 0;
    for (let i = -radius; i <= radius; i += 1) {
      const weight = Math.exp(-0.5 * (i / sigma) ** 2);
      weights[i + radius] = weight;
      total += weight;
    }
    for (let i = 0; i < weights.length; i += 1) weights[i] /= total;
    return { radius, weights };
  }

  function smoothDensities(pixels, width, height) {
    // Geometry follows the body of the ink, not photographic grain or single
    // scanlines. These scales are relative to the sampled image, so increasing
    // sampling resolution does not bring the serrations back.
    const horizontal = gaussian(Math.max(0.75, width * 0.018));
    const vertical = gaussian(Math.max(0.75, height * 0.02));
    const intermediate = new Float64Array(pixels.length);
    const smoothed = new Float64Array(pixels.length);
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        let value = 0;
        for (let i = -horizontal.radius; i <= horizontal.radius; i += 1) {
          const at = Math.max(0, Math.min(width - 1, x + i));
          value += pixels[y * width + at] * horizontal.weights[i + horizontal.radius];
        }
        intermediate[y * width + x] = value;
      }
    }
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        let value = 0;
        for (let i = -vertical.radius; i <= vertical.radius; i += 1) {
          const at = Math.max(0, Math.min(height - 1, y + i));
          value += intermediate[at * width + x] * vertical.weights[i + vertical.radius];
        }
        smoothed[y * width + x] = value;
      }
    }
    return smoothed;
  }

  function smoothHorizontalTravel(points, columns, rows) {
    const kernel = gaussian(Math.max(1, rows * 0.02));
    const original = points.slice();
    for (let row = 0; row <= rows; row += 1) {
      for (let column = 1; column < columns; column += 1) {
        let targetX = 0;
        for (let i = -kernel.radius; i <= kernel.radius; i += 1) {
          const at = Math.max(0, Math.min(rows, row + i));
          targetX += original[(at * (columns + 1) + column) * 4 + 2] * kernel.weights[i + kernel.radius];
        }
        points[(row * (columns + 1) + column) * 4 + 2] = targetX;
      }
    }
    // Every row is averaged with the same positive weights for all x values.
    // A convex average of monotone row maps stays monotone. Since y is unchanged
    // and strictly ordered, triangles also remain unfolded throughout travel.
  }

  function integer(value, name, minimum) {
    if (!Number.isInteger(value) || value < minimum) {
      throw new RangeError(`${name} must be an integer of at least ${minimum}`);
    }
  }

  function distribution(pixels, width, height, name) {
    if (!pixels || pixels.length !== width * height) {
      throw new RangeError(`${name} must contain width * height densities`);
    }
    let total = 0;
    for (const density of pixels) {
      if (!Number.isFinite(density) || density < 0) {
        throw new RangeError(`${name} densities must be finite and non-negative`);
      }
      total += density;
    }
    if (!(total > 0) || !Number.isFinite(total)) {
      throw new RangeError(`${name} must contain some pigment`);
    }

    const pigment = smoothDensities(pixels, width, height);
    total = pigment.reduce((sum, value) => sum + value, 0);

    const rowSize = width + 1;
    const rowCdf = new Float64Array(rowSize * height);
    const yCdf = new Float64Array(height + 1);
    const paper = PAPER_MASS / (width * height);
    for (let y = 0; y < height; y += 1) {
      const offset = y * rowSize;
      for (let x = 0; x < width; x += 1) {
        rowCdf[offset + x + 1] = rowCdf[offset + x] + pigment[y * width + x] / total + paper;
      }
      yCdf[y + 1] = yCdf[y] + rowCdf[offset + width];
    }
    const sum = yCdf[height];
    for (let y = 1; y <= height; y += 1) yCdf[y] /= sum;
    yCdf[height] = 1;
    return { rowCdf, yCdf };
  }

  function cdfAt(cdf, coordinate) {
    if (coordinate <= 0) return 0;
    if (coordinate >= 1) return 1;
    const scaled = coordinate * (cdf.length - 1);
    const index = Math.floor(scaled);
    return cdf[index] + (cdf[index + 1] - cdf[index]) * (scaled - index);
  }

  function quantile(cdf, mass) {
    if (mass <= 0) return 0;
    if (mass >= 1) return 1;
    let left = 0;
    let right = cdf.length - 1;
    while (right - left > 1) {
      const middle = (left + right) >>> 1;
      if (cdf[middle] <= mass) left = middle;
      else right = middle;
    }
    return (left + (mass - cdf[left]) / (cdf[right] - cdf[left])) / (cdf.length - 1);
  }

  function conditional(distribution, y, width, height) {
    // Samples are cell-centred. Interpolating adjacent raw row distributions
    // before normalizing makes the horizontal transport continuous in y.
    const sampleY = Math.max(0, Math.min(height - 1, y * height - 0.5));
    const rowA = Math.floor(sampleY);
    const rowB = Math.min(height - 1, rowA + 1);
    const mix = sampleY - rowA;
    const stride = width + 1;
    const cdf = new Float64Array(stride);
    for (let x = 1; x <= width; x += 1) {
      const a = distribution.rowCdf[rowA * stride + x];
      const b = distribution.rowCdf[rowB * stride + x];
      cdf[x] = a + (b - a) * mix;
    }
    const total = cdf[width];
    for (let x = 1; x <= width; x += 1) cdf[x] /= total;
    cdf[width] = 1;
    return cdf;
  }

  /**
   * Map sampled pigment mass with a monotone triangular transport.
   * Source/target are non-negative row-major densities at cell centres on the
   * same bounds. The mesh stores startX, startY, targetX, targetY per vertex.
   * Its start coordinates are also the unchanged source-texture coordinates.
   *
   * This maps geometry, not pigment opacity: the renderer must handle density
   * dilution and the final empty channel. It is not a fluid simulation.
   */
  function build({ source, target, width, height, bounds = { left: -0.3, top: -0.3, width: 1.6, height: 1.6 }, columns = 100, rows = 132 } = {}) {
    integer(width, "width", 2);
    integer(height, "height", 2);
    integer(columns, "columns", 1);
    integer(rows, "rows", 1);
    if (!bounds || ![bounds.left, bounds.top, bounds.width, bounds.height].every(Number.isFinite) || bounds.width <= 0 || bounds.height <= 0) {
      throw new RangeError("bounds must have finite coordinates and positive dimensions");
    }

    const from = distribution(source, width, height, "source");
    const to = distribution(target, width, height, "target");
    const points = new Float32Array((columns + 1) * (rows + 1) * 4);
    for (let row = 0; row <= rows; row += 1) {
      const startY = row / rows;
      const targetY = quantile(to.yCdf, cdfAt(from.yCdf, startY));
      const sourceCdf = conditional(from, startY, width, height);
      const targetCdf = conditional(to, targetY, width, height);
      for (let column = 0; column <= columns; column += 1) {
        const startX = column / columns;
        const targetX = quantile(targetCdf, cdfAt(sourceCdf, startX));
        const offset = (row * (columns + 1) + column) * 4;
        points[offset] = bounds.left + startX * bounds.width;
        points[offset + 1] = bounds.top + startY * bounds.height;
        points[offset + 2] = bounds.left + targetX * bounds.width;
        points[offset + 3] = bounds.top + targetY * bounds.height;
      }
    }

    smoothHorizontalTravel(points, columns, rows);

    const count = columns * rows * 6;
    const vertices = new Float32Array(count * 4);
    let offset = 0;
    const append = (point) => {
      const at = point * 4;
      for (let component = 0; component < 4; component += 1) vertices[offset++] = points[at + component];
    };
    for (let row = 0; row < rows; row += 1) {
      for (let column = 0; column < columns; column += 1) {
        const topLeft = row * (columns + 1) + column;
        const bottomLeft = topLeft + columns + 1;
        append(topLeft);
        append(bottomLeft);
        append(topLeft + 1);
        append(topLeft + 1);
        append(bottomLeft);
        append(bottomLeft + 1);
      }
    }
    return { vertices, count };
  }

  const api = Object.freeze({ build });
  if (typeof window !== "undefined") window.UtekiFormationMap = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
