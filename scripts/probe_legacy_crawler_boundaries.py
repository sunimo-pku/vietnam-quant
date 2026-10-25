"""Replay legacy source requests; keep originals unchanged. Not a full browser run."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import tempfile
from urllib.parse import urlencode
from bs4 import BeautifulSoup
from scripts.probe_status_sources import OUT, probe
from vietnam_quant.http import Client


def cafef_boundary(symbol):
    def page(number):
        label=f'legacy-cafef-{symbol.lower()}-boundary-{number}'
        receipt_path=OUT/label/'receipt.json'
        r=json.loads(receipt_path.read_text()) if receipt_path.exists() else probe(label,'https://cafef.vn/du-lieu/Ajax/Events_RelatedNews_New.aspx?'+urlencode({'symbol':symbol,'floorID':0,'configID':0,'PageIndex':number,'PageSize':30,'Type':2}))
        if r['curl_exit'] or r['http_status']!='200':raise RuntimeError(r)
        soup=BeautifulSoup(Path(r['body_path']).read_text(),'html.parser')
        dates=[datetime.strptime(x.get_text(strip=True),'%d/%m/%Y %H:%M') for x in soup.select('span.timeTitle')]
        if not dates and soup.select('a.docnhanhTitle'):raise RuntimeError('Unrecognized dates')
        if not dates and len(soup.get_text(strip=True))>100:raise RuntimeError('Unrecognized nonempty body')
        return dates
    first=page(1)
    if not first:raise RuntimeError('Missing first page')
    lo,hi=1,2
    while hi<=1000 and page(hi):lo,hi=hi,min(hi*2,1001)
    if hi>1000:return {'symbol':symbol,'boundary':'not established within legacy page cap'}
    while hi-lo>1:
        mid=(lo+hi)//2
        if page(mid):lo=mid
        else:hi=mid
    dates=page(lo)
    result={'source':'CafeF','symbol':symbol,'last_nonempty_page':lo,'next_empty_page':hi,'oldest_on_last_page':min(dates).isoformat(),'rows_on_last_page':len(dates),'latest_page1':max(first).isoformat(),'scope':'boundary probe; intervening pages not all downloaded'}
    print(json.dumps(result),flush=True)
    return result


def vietstock_vnl():
    page_url='https://finance.vietstock.vn/lich-su-kien.htm?page=1&tab=2&code=VNL&languageid=2'
    with tempfile.TemporaryDirectory() as tmp:
        cookies=str(Path(tmp)/'session.cookies')
        c=Client(OUT/'legacy-vietstock-raw',['--compressed','--cookie-jar',cookies])
        body,_=c.fetch(page_url)
        token=BeautifulSoup(body,'html.parser').select_one('input[name=__RequestVerificationToken]')['value']
        c.extra_args=['--compressed','--cookie',cookies,'-H','X-Requested-With: XMLHttpRequest','-H','Referer: '+page_url]
        results=[]
        for tab in [1,2]:
            rows=[];total=None
            for page in range(1,31):
                body,_=c.fetch('https://finance.vietstock.vn/data/eventstypedata',{'eventTypeID':tab,'channelID':0,'code':'VNL','catID':'','fDate':'','tDate':'','page':page,'pageSize':20,'orderBy':'Date1','orderDir':'DESC','__RequestVerificationToken':token})
                value=json.loads(body);part=value[0];total=int(value[1][0]);rows.extend(part)
                if page*20>=total:break
            if len({x['EventID'] for x in rows})!=total:raise RuntimeError('Pagination incomplete')
            result={'source':'Vietstock','symbol':'VNL','tab':tab,'total':total,'pages':page,'records':rows}
            results.append(result)
            print(json.dumps({k:v for k,v in result.items() if k!='records'}),flush=True)
        (OUT/'legacy-vietstock-vnl-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
        return [{k:v for k,v in r.items() if k!='records'} for r in results]

if __name__=='__main__':
    results=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs=[pool.submit(cafef_boundary,s) for s in ['REE','SAM','VNL']]+[pool.submit(vietstock_vnl)]
        for job in jobs:
            try:results.append(job.result())
            except Exception as exc:results.append({'error':str(exc)});print(str(exc),flush=True)
    (OUT/'legacy-crawler-boundaries.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
