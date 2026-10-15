"""Render an original editorial motion study; no business data or remote media."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math
import sys

ROOT = Path(__file__).resolve().parent
FRAMES = Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/editorial-motion-frames')
FRAMES.mkdir(parents=True, exist_ok=True)
W, H, SCALE, FPS, SECONDS = 960, 540, 2, 24, 7
FONTS = ROOT.parent / 'fonts'
serif = ImageFont.truetype(str(FONTS / 'LiberationSerif-Regular.ttf'), 56 * SCALE)
sans = ImageFont.truetype(str(FONTS / 'LiberationSans-Regular.ttf'), 14 * SCALE)
small = ImageFont.truetype(str(FONTS / 'LiberationSans-Regular.ttf'), 11 * SCALE)
paper, ink, olive, faint = '#f5f3eb', '#292c25', '#6b7654', '#dcded2'

def line(draw, points, color, width):
    draw.line([(int(x*SCALE), int(y*SCALE)) for x, y in points], fill=color, width=width*SCALE, joint='curve')

def point(t, offset=0):
    x = 86 + 788 * t
    y = 378 - 90 * math.sin(t * math.pi * 1.3) + 32 * math.sin(t * math.pi * 3) + offset
    return x, y

def render(i):
    elapsed = i / FPS
    progress = max(0, min(1, (elapsed - .65) / 4.65))
    progress = progress * progress * (3 - 2 * progress)
    img = Image.new('RGB', (W*SCALE, H*SCALE), paper)
    draw = ImageDraw.Draw(img)
    draw.text((56*SCALE, 35*SCALE), 'MOTION STUDY / 01', fill=olive, font=small)
    draw.text((55*SCALE, 77*SCALE), 'Small changes, seen clearly.', fill=ink, font=serif)
    draw.text((57*SCALE, 155*SCALE), 'An original study of a line, a point, and a little time.', fill='#6d7067', font=sans)
    # Soft contour lines provide depth without card / flowchart geometry.
    for offset in [-34, 0, 34]:
        line(draw, [point(j/400, offset) for j in range(401)], faint, 1)
    count = max(2, int(progress * 500))
    line(draw, [point(j/500) for j in range(count+1)], olive, 3)
    x,y = point(progress)
    ring = 12 + 2 * math.sin(elapsed * math.pi)
    draw.ellipse(((x-ring)*SCALE,(y-ring)*SCALE,(x+ring)*SCALE,(y+ring)*SCALE), outline='#bdc4ab', width=SCALE)
    draw.ellipse(((x-5)*SCALE,(y-5)*SCALE,(x+5)*SCALE,(y+5)*SCALE), fill=ink)
    draw.line((56*SCALE,464*SCALE,904*SCALE,464*SCALE), fill='#d5d7cb', width=SCALE)
    draw.text((56*SCALE,485*SCALE), 'ABSTRACT DESIGN DEMO · NO BUSINESS DATA', fill='#76796f', font=small)
    draw.text((813*SCALE,485*SCALE), '00:07 / SILENT', fill='#76796f', font=small)
    return img.resize((W,H), Image.Resampling.LANCZOS)

for i in range(FPS * SECONDS):
    render(i).save(FRAMES / f'{i:04}.png')
render(112).save(ROOT / 'line-study-poster.png')
print(f'{FPS*SECONDS} frames at {W}x{H}; poster saved')
