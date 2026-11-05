import json, os, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from shared.schemas import TargetConfig

DB=Path(os.getenv('AGENT_DB','/data/agent.db')); REF=Path(__file__).with_name('reference_inventory.json')
app=FastAPI(title='RouteWatch agent'); app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'])
def ts(): return datetime.now(timezone.utc).isoformat()
def con():
 DB.parent.mkdir(parents=True,exist_ok=True); c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
@app.on_event('startup')
def init():
 c=con();c.executescript('''CREATE TABLE IF NOT EXISTS scans(id TEXT PRIMARY KEY,config TEXT,status TEXT,started TEXT,completed TEXT,activity TEXT,endpoints TEXT,request_count INTEGER);CREATE TABLE IF NOT EXISTS findings(id TEXT PRIMARY KEY,scan_id TEXT,kind TEXT,severity TEXT,title TEXT,impact TEXT,proof TEXT,fix TEXT,status TEXT,created TEXT);CREATE TABLE IF NOT EXISTS audits(id INTEGER PRIMARY KEY AUTOINCREMENT,scan_id TEXT,method TEXT,path TEXT,status INTEGER,note TEXT,created TEXT);CREATE TABLE IF NOT EXISTS retests(id TEXT PRIMARY KEY,finding_id TEXT,scan_id TEXT,passed INTEGER,detail TEXT,legitimate INTEGER,created TEXT);''');c.commit();c.close()
def row(r): return dict(r) if r else None
def update(i,**v):
 c=con();d=row(c.execute('SELECT * FROM scans WHERE id=?',(i,)).fetchone());c.close()
 for k,x in v.items():d[k]=json.dumps(x) if k in ('activity','endpoints') else x
 c=con();c.execute('UPDATE scans SET status=?,completed=?,activity=?,endpoints=?,request_count=? WHERE id=?',(d['status'],d['completed'],d['activity'],d['endpoints'],d['request_count'],i));c.commit();c.close()
def scan(i):
 c=con();r=c.execute('SELECT * FROM scans WHERE id=?',(i,)).fetchone();c.close()
 if not r:return None
 d=row(r);d['config']=json.loads(d['config']);d['activity']=json.loads(d['activity']);d['endpoints']=json.loads(d['endpoints']);return d
def audit(s,m,p,status,note):
 c=con();c.execute('INSERT INTO audits(scan_id,method,path,status,note,created) VALUES(?,?,?,?,?,?)',(s,m,p,status,note,ts()));c.commit();c.close()
def finding(s,kind,severity,title,impact,proof,fix):
 fid=str(uuid.uuid4());c=con();c.execute('INSERT INTO findings VALUES(?,?,?,?,?,?,?,?,?,?)',(fid,s,kind,severity,title,impact,json.dumps(proof),fix,'open',ts()));c.commit();c.close();return fid
class SafeClient:
 def __init__(self,cfg,s):self.cfg,self.s,self.used=cfg,s,0
 async def req(self,m,path,acct=None,body=None,note='probe'):
  if scan(self.s)['status']=='cancelled':raise RuntimeError('scan cancelled by operator')
  if self.used>=self.cfg.max_requests:raise RuntimeError('request budget reached')
  u=self.cfg.base_url.rstrip('/')+path;p=urlparse(u)
  if f'{p.scheme}://{p.netloc}' not in self.cfg.allowed_origins:raise RuntimeError('target outside configured scope')
  h={}
  if acct:h={'X-Agency':acct.agency_id,'X-User':acct.user_id,'Authorization':'Bearer ***'}
  self.used+=1
  async with httpx.AsyncClient(timeout=self.cfg.timeout_seconds,follow_redirects=False) as x:r=await x.request(m,u,headers=h,json=body)
  if r.is_redirect and urlparse(r.headers.get('location','')).netloc not in [urlparse(x).netloc for x in self.cfg.allowed_origins]:raise RuntimeError('out-of-scope redirect rejected')
  audit(self.s,m,path,r.status_code,note)
  try:b=r.json()
  except Exception:b={'text':r.text[:200]}
  return r.status_code,b
async def run_scan(sid):
 d=scan(sid);cfg=TargetConfig.model_validate(d['config']);act=['Capturing normal journey traffic (synthetic HAR).'];update(sid,activity=act)
 try:
  cl=SafeClient(cfg,sid);code,har=await cl.req('GET','/ui/traffic-recording',note='discovery HAR')
  if code!=200:raise RuntimeError('traffic recording unavailable')
  obs=har.get('requests',[]);refs=json.loads(REF.read_text())[cfg.reference_profile];act.append(f'Discovered {len(obs)} observed request shapes.')
  a,b=cfg.accounts[:2];qp=next(x['path'] for x in obs if x['method']=='POST' and 'quote' in x['path']);bp=next(x['path'] for x in obs if x['method']=='POST' and 'booking' in x['path']);gp=next(x['path'] for x in obs if x['method']=='GET' and 'booking' in x['path'] and 'v2' in x['path']);route=next(x.get('body',{}).get('route') for x in obs if x.get('body',{}).get('route'))
  async def baseline(ac):
   _,q=await cl.req('POST',qp,ac,{'route':route},'legitimate quote baseline');_,bk=await cl.req('POST',bp,ac,{'quote_id':q['quote_id'],'traveler':'Synthetic baseline','fare':q['fare']},'legitimate booking baseline');return q,bk
  qa,ba=await baseline(a);qb,bb=await baseline(b)
  foreign=gp.replace('{id}',bb['booking_id']);status,body=await cl.req('GET',foreign,a,note='cross-agency ownership test');_,legit=await cl.req('GET',gp.replace('{id}',ba['booking_id']),a,note='legitimate ownership control')
  if status==200 and body.get('booking_id')==bb['booking_id'] and body.get('agency_id')==b.agency_id: finding(sid,'cross_agency_access','high','Cross-agency booking access','One travel agency can view another agency’s booking and traveler data.',{'request':{'method':'GET','path':foreign,'account':a.name},'response':body,'control_booking':legit.get('booking_id')},'Enforce agency ownership on every booking lookup, including legacy routes.')
  act.append('Completed ownership boundary test with legitimate control.')
  tampered=max(1,qa['fare']-1);_,tb=await cl.req('POST',bp,a,{'quote_id':qa['quote_id'],'traveler':'Synthetic tamper test','fare':tampered},'fare tampering test')
  if tb.get('fare')==tampered and tb.get('quote_fare')!=tampered:finding(sid,'fare_tampering','high','Client-controlled fare accepted','A booking can be confirmed for a modified synthetic fare.',{'request':{'method':'POST','path':bp,'body':{'quote_id':'[redacted]','fare':tampered}},'response':tb},'Calculate or validate the payable fare server-side from the quote.')
  allx={(x['method'],x['path']) for x in obs}|{(x['method'],x['path']) for x in refs};oset={(x['method'],x['path']) for x in obs};rset={(x['method'],x['path']) for x in refs};ends=[]
  for m,p in sorted(allx):
   reachable=None
   if m=='GET' and ('/v1/' in p or (m,p) not in oset): status,_=await cl.req(m,p.replace('{id}',ba['booking_id']),a,note='inventory reachability probe');reachable=status<400
   traffic=(m,p) in oset;referenced=(m,p) in rset
   if reachable and not traffic and '/v1/' in p:klass='zombie';ev=['reachable during scan','no legitimate synthetic traffic in supplied observation window','older API path']
   elif traffic and not referenced:klass='shadow';ev=['observed in synthetic HAR','absent from supplied reference inventory']
   elif traffic and referenced:klass='active';ev=['observed in synthetic HAR','present in reference inventory']
   else:klass='unknown';ev=['insufficient reachability or traffic evidence']
   ends.append({'method':m,'path':p,'reachable':reachable,'classification':klass,'evidence':ev})
  act.append('Classified inventory using supplied synthetic traffic window and reference inventory.');update(sid,status='completed',completed=ts(),activity=act,endpoints=ends,request_count=cl.used)
 except Exception as e:act.append(f'Scan stopped: {e}');update(sid,status='failed',completed=ts(),activity=act,request_count=cl.used if 'cl' in locals() else 0)
@app.post('/scans')
async def create_scan(cfg:TargetConfig,background:BackgroundTasks):
 if len(cfg.accounts)<2:raise HTTPException(400,'two explicitly owned test accounts required')
 if any(urlparse(x).netloc!=urlparse(cfg.base_url).netloc for x in cfg.allowed_origins):raise HTTPException(400,'allowed origins must be target scope')
 sid=str(uuid.uuid4());c=con();c.execute('INSERT INTO scans VALUES(?,?,?,?,?,?,?,?)',(sid,cfg.model_dump_json(),'running',ts(),None,json.dumps(['Scan queued.']),json.dumps([]),0));c.commit();c.close();background.add_task(run_scan,sid);return {'scan_id':sid}
@app.post('/scans/{sid}/cancel')
def cancel(sid:str):
 r=scan(sid)
 if not r:raise HTTPException(404)
 if r['status']=='running':update(sid,status='cancelled',completed=ts(),activity=r['activity']+['Cancelled by operator.'])
 return scan(sid)
@app.get('/scans')
def scans():
 c=con();ids=[x[0] for x in c.execute('SELECT id FROM scans ORDER BY started DESC').fetchall()];c.close();return [scan(x) for x in ids]
@app.get('/scans/{sid}')
def getscan(sid:str):
 r=scan(sid)
 if not r:raise HTTPException(404)
 return r
@app.get('/findings')
def findings():
 c=con();rs=c.execute('SELECT * FROM findings ORDER BY created DESC').fetchall();c.close();return [{**row(x),'proof':json.loads(x['proof'])} for x in rs]
@app.get('/audit')
def audits():
 c=con();rs=c.execute('SELECT * FROM audits ORDER BY id DESC LIMIT 200').fetchall();c.close();return [row(x) for x in rs]
@app.post('/findings/{fid}/retest')
async def retest(fid:str,background:BackgroundTasks):
 c=con();f=c.execute('SELECT * FROM findings WHERE id=?',(fid,)).fetchone();c.close()
 if not f:raise HTTPException(404)
 cfg=TargetConfig.model_validate(scan(f['scan_id'])['config']);sid=str(uuid.uuid4());c=con();c.execute('INSERT INTO scans VALUES(?,?,?,?,?,?,?,?)',(sid,cfg.model_dump_json(),'running',ts(),None,json.dumps(['Retest queued.']),json.dumps([]),0));c.commit();c.close();background.add_task(run_retest,fid,f['kind'],sid);return {'finding_id':fid,'retest_scan_id':sid,'note':'Fresh live scan is running.'}
async def run_retest(fid,kind,sid):
 await run_scan(sid);result=scan(sid);c=con();exists=c.execute('SELECT 1 FROM findings WHERE scan_id=? AND kind=?',(sid,kind)).fetchone() is not None;passed=result['status']=='completed' and not exists;detail='Original proof no longer reproduced; legitimate baseline workflow completed.' if passed else 'Original proof reproduced or retest did not complete.';c.execute('INSERT INTO retests VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),fid,sid,int(passed),detail,int(result['status']=='completed'),ts()));
 if passed:c.execute("UPDATE findings SET status='retest_passed' WHERE id=?",(fid,))
 c.commit();c.close()
@app.get('/retests')
def retests():
 c=con();rs=c.execute('SELECT * FROM retests ORDER BY created DESC').fetchall();c.close();return [row(x) for x in rs]
@app.post('/deployments/simulate')
async def deploy(cfg:TargetConfig,background:BackgroundTasks):
 cfg.reference_profile='documented';r=await create_scan(cfg,background);return {**r,'event':'simulated deployment; target behavior unchanged'}
