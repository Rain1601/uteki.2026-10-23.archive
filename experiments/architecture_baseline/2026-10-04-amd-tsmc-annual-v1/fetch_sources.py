"""Fetch only the explicitly selected official annual sources; preserve raw bytes and receipts."""
import argparse, concurrent.futures, hashlib, json, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def main():
    cli=argparse.ArgumentParser(); cli.add_argument('--selection',type=Path,required=True); cli.add_argument('--output',type=Path,required=True)
    args=cli.parse_args(); cfg=json.loads(args.selection.read_text()); out=args.output
    out.mkdir(parents=True,exist_ok=False)
    (out/'selection.json').write_text(json.dumps(cfg,indent=2,ensure_ascii=False)+'\n')
    def one(spec):
        url=spec['source_url']
        if urlparse(url).hostname not in {'ir.amd.com','www.sec.gov','investor.tsmc.com'}: raise ValueError('unapproved host in selected experiment source')
        result={**spec,'retrieved_at':datetime.now(timezone.utc).isoformat(),'status':'fetch_failed'}
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Uteki Financial Research source archive (noncommercial research)','Accept':'text/html,application/pdf'}),timeout=90) as reply:
                content=reply.read(30000000)
                if len(content)>=30000000: raise ValueError('source exceeds declared archive limit')
                if reply.status != 200: raise ValueError('HTTP status '+str(reply.status))
                mime='application/pdf' if content.startswith(b'%PDF') else 'text/html'
                if mime=='text/html' and b'<html' not in content.lower(): raise ValueError('not an HTML document')
                folder=out/spec['source_id']; folder.mkdir()
                target=folder/('source.pdf' if mime=='application/pdf' else 'source.html'); target.write_bytes(content)
                result.update(status='frozen',path=str(target.relative_to(out)),content_sha256=hashlib.sha256(content).hexdigest(),bytes=len(content),mime_type=mime,final_url=reply.url,as_of_eligible=spec['filed_at']<=cfg['as_of'])
        except Exception as error: result.update(error_type=type(error).__name__,error=str(error)[:240])
        (out/(spec['source_id']+'-receipt.json')).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
        print(json.dumps({k:result[k] for k in ('source_id','status','bytes','error') if k in result}),flush=True)
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor: results=list(executor.map(one,cfg['sources']))
    (out/'receipts.json').write_text(json.dumps(results,indent=2,ensure_ascii=False)+'\n')
    (out/'manifest.json').write_text(json.dumps({'as_of':cfg['as_of'],'files':{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}},indent=2)+'\n')
if __name__=='__main__': main()
