"""Local OCR grounds model transcriptions to original pixels, without editing facts.

Explicit adapter: Tesseract English, sparse text, bounded multi-angle deskew.
Deskew images are analysis intermediates only; the original bytes are unchanged.
A missing or ambiguous text match is a gap, never a model-coordinate fallback.
"""
import csv
import hashlib
from io import StringIO
import json
import math
from pathlib import Path
import shutil
import subprocess
from PIL import Image

ANGLES = (0, -45, 45, -40, 40, -50, 50, -90, 90)

def norm(text):
    return ' '.join(text.split())

def original_box(box, angle, rotated_size, original_size):
    a = math.radians(angle); c, s = math.cos(a), math.sin(a)
    rw,rh=rotated_size; w,h=original_size
    points=[]
    for x in (box[0],box[2]):
        for y in (box[1],box[3]):
            xx,yy=x-rw/2,y-rh/2
            points.append((c*xx-s*yy+w/2,s*xx+c*yy+h/2))
    return dict(x0=max(0,math.floor(min(x for x,y in points)*1000/w)),
                y0=max(0,math.floor(min(y for x,y in points)*1000/h)),
                x1=min(1000,math.ceil(max(x for x,y in points)*1000/w)),
                y1=min(1000,math.ceil(max(y for x,y in points)*1000/h)))

def _overlapping_location(a, b):
    """Nearby repeated short labels are distinct unless their pixel regions overlap."""
    areas = [(box['x1'] - box['x0']) * (box['y1'] - box['y0']) for box in (a, b)]
    if min(areas) <= 0:
        return False
    intersection = max(0, min(a['x1'], b['x1']) - max(a['x0'], b['x0'])) * max(0, min(a['y1'], b['y1']) - max(a['y0'], b['y0']))
    return intersection >= .5 * min(areas)


def replay_text_grounding(texts, runs, tsvs, original_size):
    """Apply the same deterministic location contract to every frozen OCR run.

    No OCR process or image conversion runs here. Both generation and consumption
    use these exact candidates, location clusters and physical-occurrence checks.
    """
    candidates = {text['id']: [] for text in texts}
    targets = {text['id']: norm(text['text']) for text in texts}
    for run in runs:
        lines = {}
        for row in csv.DictReader(StringIO(tsvs[run['tsv']]), delimiter='\t'):
            if row['level'] == '5' and row.get('text', '').strip():
                key = tuple(row[key] for key in ('page_num', 'block_num', 'par_num', 'line_num'))
                lines.setdefault(key, []).append(row)
        for words in lines.values():
            for start in range(len(words)):
                for end in range(start + 1, min(len(words), start + 20) + 1):
                    part = words[start:end]
                    text = norm(' '.join(word['text'] for word in part))
                    confidences = [float(word['conf']) for word in part]
                    if any(not math.isfinite(value) or not 80 <= value <= 100 for value in confidences):
                        continue
                    confidence = min(confidences)
                    for identity, target in targets.items():
                        if text != target:
                            continue
                        pixel_box = (min(int(word['left']) for word in part),
                            min(int(word['top']) for word in part),
                            max(int(word['left']) + int(word['width']) for word in part),
                            max(int(word['top']) + int(word['height']) for word in part))
                        candidates[identity].append({
                            'box': original_box(pixel_box, run['angle'], run['size'], original_size),
                            'angle': run['angle'], 'confidence': confidence,
                            'ocr_file': run['tsv'], 'text': text})
    matches={}; gaps=[]
    for text in texts:
        hits=candidates[text['id']]
        clusters=[]
        for hit in hits:
            b=hit['box']; center=((b['x0']+b['x1'])/2,(b['y0']+b['y1'])/2)
            found=next((group for group in clusters if abs(group[0][0]-center[0])<25 and abs(group[0][1]-center[1])<25 and _overlapping_location(group[1][0]['box'], b)),None)
            if found is None:
                clusters.append([center,[hit]])
            else:
                found[1].append(hit)
        if len(clusters)!=1:
            gaps.append({'text_id':text['id'],'code':'ocr_missing' if not clusters else 'ocr_ambiguous','locations':len(clusters)})
            continue
        selected=max(clusters[0][1],key=lambda h:h['confidence'])
        matches[text['id']]=selected
    # One physical text occurrence cannot authorize duplicate model identities.
    reused = {}
    for identity, hit in matches.items():
        key = (hit['text'], tuple(hit['box'][k] for k in ('x0','y0','x1','y1')))
        reused.setdefault(key, []).append(identity)
    for identities in reused.values():
        if len(identities) > 1:
            for identity in identities:
                matches.pop(identity)
                gaps.append({'text_id':identity,'code':'ocr_location_reused','text_ids':identities})
    return matches, gaps


def locate_texts(image_path, texts, output):
    output=Path(output); output.mkdir(exist_ok=False)
    executable=shutil.which('tesseract')
    if not executable:
        raise ValueError('Explicit OCR adapter requires tesseract with eng data')
    version=subprocess.run([executable,'--version'],capture_output=True,text=True,check=True,timeout=15).stdout.splitlines()[0]
    with Image.open(image_path) as opened:
        image=opened.convert('RGB')
    runs=[]
    tsvs={}
    for number,angle in enumerate(ANGLES):
        raster=image.rotate(angle,expand=True,fillcolor='white')
        # Use a real resolved path: Leptonica does not reliably resolve macOS /tmp.
        path=(output/f'deskew-{number}.png').resolve(); raster.save(path)
        call=subprocess.run([executable,str(path),'stdout','-l','eng','--psm','11','tsv'],capture_output=True,text=True,check=True,timeout=45)
        name=f'ocr-{number}.tsv'
        (output/name).write_text(call.stdout)
        tsvs[name]=call.stdout
        path.unlink()  # reversible derived pixels; retained TSV + transform reproduces them
        runs.append({'angle':angle,'size':raster.size,'tsv':name})
    matches, gaps = replay_text_grounding(texts, runs, tsvs, image.size)
    report={'image_sha256':hashlib.sha256(Path(image_path).read_bytes()).hexdigest(),'adapter':'tesseract-multiangle-v1','version':version,'language':'eng','angles':list(ANGLES),
            'image_size':image.size,'coordinate_space':'normalized_original_0_1000','runs':runs,
            'matches':matches,'gaps':gaps,'status':'grounded' if not gaps else 'with_gaps'}
    (output/'grounding.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
    return report
