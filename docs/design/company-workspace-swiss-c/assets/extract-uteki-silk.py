#!/usr/bin/env python3
"""Reproduce the selected silk-blue Uteki mark cutout; no generation or color enhancement.

The source JPEG is a reviewed, explicitly selected brand asset. Its S-shaped
negative space is explicitly seeded separately from the crop-boundary
background. This script only prepares the selected existing raster asset.
"""
from collections import deque
from pathlib import Path
import hashlib
import json
import math

from PIL import Image

ASSETS = Path(__file__).resolve().parent
SOURCE = ASSETS.parents[3] / 'apps/logo_studio/assets/uteki-silk.jpeg'
OUTPUT = ASSETS / 'uteki-drop-silk.png'
SOURCE_NOTE = ASSETS / 'uteki-drop-silk.source.json'
CROP_XYWH = (316, 253, 296, 382)
NEGATIVE_SPACE_SEEDS = [(148, 221)]
WHITE_MIN = 230
WHITE_SPREAD = 25


def near_white(rgb):
    return min(rgb) >= WHITE_MIN and max(rgb) - min(rgb) <= WHITE_SPREAD


def main():
    x, y, width, height = CROP_XYWH
    source = Image.open(SOURCE).convert('RGB')
    original = source.crop((x, y, x + width, y + height))
    pixels = original.load()
    points = {(x, y) for y in range(height) for x in range(width)}
    seeds = {p for p in points if p[0] in (0, width - 1) or p[1] in (0, height - 1)}
    for seed in NEGATIVE_SPACE_SEEDS:
        assert near_white(pixels[seed]), 'Negative-space seed is not in the white opening'
        seeds.add(seed)
    background = {p for p in seeds if near_white(pixels[p])}
    queue = deque(background)
    while queue:
        px, py = queue.popleft()
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            neighbor = (px + dx, py + dy)
            if neighbor in points and neighbor not in background and near_white(pixels[neighbor]):
                background.add(neighbor)
                queue.append(neighbor)

    foreground = points - background
    neighbors = [(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy]
    edge = {p for p in foreground if any((p[0] + dx, p[1] + dy) in background for dx, dy in neighbors)}
    interior = foreground - edge
    output = Image.new('RGBA', original.size, (0, 0, 0, 0))
    output_pixels = output.load()
    corrected = set()

    for point in foreground:
        rgb = pixels[point]
        output_pixels[point] = (*rgb, 255)
        if point not in edge:
            continue
        # Estimate the nearby opaque edge color, then remove only the white
        # matte contribution from this one-pixel boundary. Interior RGB stays
        # byte-for-byte equal to the original JPEG decode.
        candidates = []
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                neighbor = (point[0] + dx, point[1] + dy)
                if neighbor in interior:
                    candidates.append((dx * dx + dy * dy, neighbor))
        if not candidates:
            continue
        distance = min(item[0] for item in candidates)
        references = [pixels[p] for d, p in candidates if d == distance]
        reference = [sum(color[c] for color in references) / len(references) for c in range(3)]
        white_distance = [255 - value for value in reference]
        denominator = sum(value * value for value in white_distance)
        if denominator == 0:
            continue
        alpha = sum((255 - rgb[c]) * white_distance[c] for c in range(3)) / denominator
        if alpha >= 0.97:
            continue
        # Keep the original contribution reproducible when composited on white.
        # This lower bound prevents channel clipping from a poor edge estimate.
        alpha = max(alpha, max((255 - value) / 255 for value in rgb))
        alpha_byte = max(1, min(254, math.ceil(alpha * 255)))
        alpha = alpha_byte / 255
        unmatte = tuple(max(0, min(255, round((value - 255 * (1 - alpha)) / alpha))) for value in rgb)
        output_pixels[point] = (*unmatte, alpha_byte)
        corrected.add(point)

    output.save(OUTPUT)
    alpha = output.getchannel('A')
    unchanged = sum(output_pixels[p][:3] == pixels[p] and output_pixels[p][3] == 255 for p in foreground)
    assert all(output_pixels[p] == (*pixels[p], 255) for p in interior)
    assert all(alpha.getpixel(p) == 0 for p in NEGATIVE_SPACE_SEEDS)
    assert all(alpha.getpixel(p) == 0 for p in seeds)
    white = Image.new('RGBA', output.size, 'white')
    recomposed = Image.alpha_composite(white, output).convert('RGB')
    edge_error = max(abs(recomposed.getpixel(p)[c] - pixels[p][c]) for p in corrected for c in range(3)) if corrected else 0

    metadata = {
        'status': 'deterministic-silk-original-cutout',
        'selected_for': 'Swiss C sidebar, 2026-10-05; replace dense glass highlights with the existing silk-blue source',
        'previous_asset_preserved': 'uteki-drop.png',
        'source': '../../../../apps/logo_studio/assets/uteki-silk.jpeg',
        'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        'method': 'Pillow deterministic crop, connected near-white background removal, and one-pixel edge white-matte correction. No generation, resizing, recoloring, enhancement or redrawing.',
        'crop_xywh': list(CROP_XYWH),
        'negative_space_seeds_in_crop': NEGATIVE_SPACE_SEEDS,
        'negative_space_note': 'The verified white seed is at source coordinate (464, 474), inside the S-shaped opening. It removes only its connected near-white region; the blue lobes are preserved.',
        'near_white_min_channel': WHITE_MIN,
        'near_white_max_channel_spread': WHITE_SPREAD,
        'dimensions': list(output.size),
        'mode': output.mode,
        'alpha_range': list(alpha.getextrema()),
        'subject_bbox_xyxy': list(alpha.getbbox()),
        'foreground_pixels': len(foreground),
        'interior_pixels_preserved_exactly': len(interior),
        'all_opaque_pixels_preserved_exactly': unchanged,
        'edge_pixels_corrected': len(corrected),
        'fraction_foreground_rgb_unchanged': unchanged / len(foreground),
        'max_corrected_edge_rgb_error_recomposited_on_white': edge_error,
        'reproduction': 'python3 docs/design/company-workspace-swiss-c/assets/extract-uteki-silk.py',
    }
    SOURCE_NOTE.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
