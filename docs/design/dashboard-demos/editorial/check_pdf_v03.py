"""Checks final PDFs and independently exercises bounded renderer failure contracts."""
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
import pdfplumber
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parent
FORBIDDEN_START=set('，。！？：；）》】”’、')
FORBIDDEN_END=set('（《【“‘')
def inspect(path,language):
    reader=PdfReader(path);assert len(reader.pages)==2
    embedded=set()
    for page in reader.pages:
        for font in page['/Resources']['/Font'].values():
            obj=font.get_object(); descriptor=obj.get('/FontDescriptor')
            if descriptor:
                assert '/FontFile2' in descriptor.get_object();embedded.add(str(obj['/BaseFont']))
    assert len(embedded)>=3,embedded
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            assert all(0<=c['x0']<c['x1']<=page.width and 0<=c['top']<c['bottom']<=page.height for c in page.chars)
            for line in page.extract_text_lines():
                text=line['text'].strip()
                assert text[0] not in FORBIDDEN_START,text
                assert text[-1] not in FORBIDDEN_END,text
            footer=[c for c in page.chars if c['top']>740];assert footer
            body=[c for c in page.chars if c['top']<=740];assert max(c['bottom'] for c in body)<728
        text=pdf.pages[1].extract_text();assert '1,284' in text and '0' in text and ('缺失' if language=='zh' else 'Missing') in text
        if language=='zh': assert '研究摘要' in text and '观察项目甲' in text
for language in ['en','zh']:inspect(ROOT/f'output/pdf/editorial-{language}-v0.3.pdf',language)
with tempfile.TemporaryDirectory() as temp:
    temp=Path(temp);original=json.loads((ROOT/'pdf-inputs/zh-v03.json').read_text());output=temp/'check.pdf'
    def run(source,success,layout=None):
        file=temp/'input.json';file.write_text(json.dumps(source,ensure_ascii=False))
        command=[sys.executable,str(ROOT/'render_pdf_v03.py'),str(file),str(ROOT/'fonts'),'--output',str(output)]
        if layout:
            config=temp/'layout.json';config.write_text(json.dumps(layout,ensure_ascii=False));command+=['--layout',str(config)]
        before=hashlib.sha256(output.read_bytes()).hexdigest() if output.exists() else None
        result=subprocess.run(command,capture_output=True,text=True)
        assert (result.returncode==0)==success,result.stderr
        if not success and before:assert hashlib.sha256(output.read_bytes()).hexdigest()==before
        return result.stderr
    source=json.loads(json.dumps(original));source['model']['rows'][0].update(label='海外企业客户订阅与实施服务收入及其他持续服务收入（含跨期确认及调整）',value=-1284.5)
    source['model']['summary']='“观察变化，保留证据。”（数据仅为排版测试）中英文 AI research 混排，检查边界。'*3
    run(source,True)
    with pdfplumber.open(output) as pdf:
        text=pdf.pages[1].extract_text();assert '-1,284.5' in text and '缺失' in text
        lines=pdf.pages[1].extract_text_lines()
        assert all(l['text'][0] not in FORBIDDEN_START and l['text'][-1] not in FORBIDDEN_END for l in lines)
        label_lines=[l for l in lines if any(c in l['text'] for c in ['海外企业','期确认','调整）'])]
        assert len(label_lines)>=2, [l['text'] for l in lines]
    for field,value,expected in [('title','𠮷','unsupported glyphs'),('summary','长文'*2000,'exceeds bounded page')]:
        source=json.loads(json.dumps(original));source['model'][field]=value;assert expected in run(source,False)
    source=json.loads(json.dumps(original));source['model']['rows'][0]['value']=10**40;assert 'column width' in run(source,False)
    layout=json.loads((ROOT/'pdf-layout-v03.json').read_text());layout['languages']['zh']['labels']['footer']='中文页脚'*80;assert 'Footer collides' in run(original,False,layout)
    source=json.loads(json.dumps(original));source['language']='unknown';assert 'supported language' in run(source,False)
print('PASS: bilingual pages, embedded role fonts, bounds, punctuation, numeric identity; independent wrap and failure preservation')
