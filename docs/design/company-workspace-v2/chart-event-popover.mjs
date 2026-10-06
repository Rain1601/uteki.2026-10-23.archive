const clamp = (value, lower, upper) => Math.min(upper, Math.max(lower, value));

function finite(value, label, minimum = -Infinity) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum) {
    throw new TypeError(`${label} must be a finite number${minimum === 0 ? ' greater than or equal to zero' : ''}`);
  }
}

function rectangle(rect, label, positive) {
  if (!rect || typeof rect !== 'object') throw new TypeError(`${label} must be a rectangle`);
  for (const edge of ['left', 'right', 'top', 'bottom']) finite(rect[edge], `${label}.${edge}`);
  const width = rect.right - rect.left;
  const height = rect.bottom - rect.top;
  if (!Number.isFinite(width) || !Number.isFinite(height) || width < 0 || height < 0 ||
      (positive && (width === 0 || height === 0))) {
    throw new RangeError(`${label} must have ordered edges${positive ? ' and positive dimensions' : ''}`);
  }
  return { width, height };
}

/**
 * Position an event card without overlapping its marker. Inputs and returned
 * left/top are viewport client coordinates; bounds must already be clipped to
 * the visible chart/reading area. arrowX is relative to the card's left edge.
 * Apply width and maxHeight to the card, with internal overflow scrolling.
 * A zero width or maxHeight means there is no room to display the card.
 */
export function placeChartEventPopover({ anchor, bounds, size, gap = 12, padding = 8 } = {}) {
  const anchorSize = rectangle(anchor, 'anchor', false);
  const boundsSize = rectangle(bounds, 'bounds', true);
  if (!size || typeof size !== 'object') throw new TypeError('size must contain width and height');
  for (const dimension of ['width', 'height']) {
    finite(size[dimension], `size.${dimension}`, 0);
    if (size[dimension] === 0) throw new RangeError(`size.${dimension} must be positive`);
  }
  finite(gap, 'gap', 0);
  finite(padding, 'padding', 0);

  const insetX = Math.min(padding, boundsSize.width / 2);
  const insetY = Math.min(padding, boundsSize.height / 2);
  const leftEdge = bounds.left + insetX;
  const rightEdge = bounds.right - insetX;
  const topEdge = bounds.top + insetY;
  const bottomEdge = bounds.bottom - insetY;
  const width = Math.min(size.width, Math.max(0, rightEdge - leftEdge));
  const anchorX = anchor.left + anchorSize.width / 2;
  const left = clamp(anchorX - width / 2, leftEdge, rightEdge - width);
  const aboveBottom = clamp(anchor.top - gap, topEdge, bottomEdge);
  const belowTop = clamp(anchor.bottom + gap, topEdge, bottomEdge);
  const aboveSpace = Math.max(0, aboveBottom - topEdge);
  const belowSpace = Math.max(0, bottomEdge - belowTop);
  const placement = aboveSpace >= size.height || aboveSpace >= belowSpace ? 'above' : 'below';
  const maxHeight = Math.min(size.height, placement === 'above' ? aboveSpace : belowSpace);
  const top = placement === 'above' ? aboveBottom - maxHeight : belowTop;
  const arrowInset = Math.min(padding, width / 2);
  const arrowX = clamp(anchorX - left, arrowInset, width - arrowInset);
  return { left, top, width, maxHeight, placement, arrowX };
}
