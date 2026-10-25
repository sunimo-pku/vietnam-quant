"""Read-only search of official early regulatory archive; retain raw receipts."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
import json,re,tempfile
from vietnam_quant.http import Client
from vietnam_quant.sources import hnx_history_year
from vietnam_quant.ssc import parse_search
ROOT=Path('outputs/direct-status-research-20261023/early-regulatory')
ROOT.mkdir(parents=True,exist_ok=True)

def hnx():
 c=Client(ROOT/'raw-hnx',['--compressed'])
 results=[]
 for year in range(2005,2010):
  try:
   rows,receipts=hnx_history_year(c,'HNX',year,f'31/12/{year}')
   selected=[r for r in rows if re.search(r'cảnh báo|kiểm soát',r['title'],re.I)]
   (ROOT/f'hnx-{year}.json').write_text(json.dumps({'all_records':rows,'candidate_records':selected,'receipts':receipts},ensure_ascii=False,indent=2))
   result={'year':year,'total':len(rows),'candidates':len(selected)};results.append(result);print('HNX',json.dumps(result),flush=True)
  except Exception as e:results.append({'year':year,'error':str(e)});print(str(e),flush=True)
 return results

def ssc(query):
 with tempfile.TemporaryDirectory() as t:
  cookie=str(Path(t)/'cookies');c=Client(ROOT/'raw-ssc',['--compressed','--cookie',cookie,'--cookie-jar',cookie])
  body,receipt=c.fetch('https://ssc.gov.vn/webcenter/portal/ubck/pages_otherpages/tmkim?SearchInput='+quote(query))
  links,total=parse_search(body)
  result={'query':query,'total':total,'links':links,'receipt':receipt,'complete':len(links)==total}
  (ROOT/('ssc-'+{'cảnh báo':'warning','kiểm soát':'control','HAP':'hap'}[query]+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
  print('SSC',query,total,'saved',len(links),flush=True)
  return result

if __name__=='__main__':
 with ThreadPoolExecutor(max_workers=3) as pool:
  jobs=[pool.submit(hnx)]+[pool.submit(ssc,q) for q in ['cảnh báo','kiểm soát','HAP']]
  results=[]
  for j in jobs:
   try:results.append(j.result())
   except Exception as e:results.append({'error':str(e)});print(str(e),flush=True)
 (ROOT/'manifest.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
