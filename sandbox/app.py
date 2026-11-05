import os, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

DB = Path(os.getenv("SANDBOX_DB", "/data/sandbox.db"))
app = FastAPI(title="RouteWatch synthetic sandbox", docs_url=None, openapi_url=None)

def now(): return datetime.now(timezone.utc).isoformat()
def con():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c
def init():
    c=con(); c.executescript('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE IF NOT EXISTS bookings(id TEXT PRIMARY KEY, agency_id TEXT, traveler TEXT, route TEXT, fare REAL, quote_fare REAL, created_at TEXT);
    CREATE TABLE IF NOT EXISTS quotes(id TEXT PRIMARY KEY, agency_id TEXT, route TEXT, fare REAL);''')
    if not c.execute("SELECT 1 FROM settings WHERE key='mode'").fetchone(): c.execute("INSERT INTO settings VALUES ('mode','vulnerable')")
    c.commit(); c.close()
@app.on_event("startup")
def startup(): init()
def mode():
    c=con(); r=c.execute("SELECT value FROM settings WHERE key='mode'").fetchone()[0]; c.close(); return r
def identity(agency: str|None, user: str|None):
    if agency not in {'agency-a','agency-b'} or not user: raise HTTPException(401,"Synthetic account required")
    return agency
def booking_dict(r):
    data=dict(r)
    data['booking_id']=data.pop('id')
    return data
class QuoteIn(BaseModel): route: str
class ConfirmIn(BaseModel): quote_id: str; traveler: str; fare: float

@app.post('/sandbox/reset')
def reset():
    c=con(); c.execute('DELETE FROM bookings'); c.execute('DELETE FROM quotes'); c.execute("UPDATE settings SET value='vulnerable' WHERE key='mode'"); c.commit(); c.close(); return {'ok':True,'mode':'vulnerable'}
@app.post('/sandbox/mode/{new_mode}')
def set_mode(new_mode:str):
    if new_mode not in {'vulnerable','fixed'}: raise HTTPException(400,'mode must be vulnerable or fixed')
    c=con(); c.execute("UPDATE settings SET value=? WHERE key='mode'",(new_mode,)); c.commit(); c.close(); return {'mode':new_mode, 'note':'sandbox-only switch'}
@app.get('/sandbox/status')
def status(): return {'mode':mode(),'synthetic':True}

@app.post('/api/v2/quotes')
def quote(payload:QuoteIn, x_agency:str|None=Header(None), x_user:str|None=Header(None)):
    agency=identity(x_agency,x_user); fare=120.0 if payload.route=='DEL-BOM' else 180.0; q=str(uuid.uuid4())
    c=con(); c.execute('INSERT INTO quotes VALUES (?,?,?,?)',(q,agency,payload.route,fare)); c.commit(); c.close()
    return {'quote_id':q,'route':payload.route,'fare':fare}
@app.post('/api/v2/bookings')
def confirm(payload:ConfirmIn,x_agency:str|None=Header(None),x_user:str|None=Header(None)):
    agency=identity(x_agency,x_user); c=con(); q=c.execute('SELECT * FROM quotes WHERE id=?',(payload.quote_id,)).fetchone()
    if not q or q['agency_id']!=agency: c.close(); raise HTTPException(404,'quote not found')
    stored_fare=payload.fare if mode()=='vulnerable' else q['fare']; bid=str(uuid.uuid4())
    c.execute('INSERT INTO bookings VALUES (?,?,?,?,?,?,?)',(bid,agency,payload.traveler,q['route'],stored_fare,q['fare'],now())); c.commit(); c.close()
    return {'booking_id':bid,'agency_id':agency,'fare':stored_fare,'quote_fare':q['fare']}
def get_booking(bid, agency, legacy=False):
    if legacy and mode()=='fixed': raise HTTPException(410,'legacy endpoint disabled')
    c=con(); b=c.execute('SELECT * FROM bookings WHERE id=?',(bid,)).fetchone(); c.close()
    if not b: raise HTTPException(404,'booking not found')
    if mode()=='fixed' and b['agency_id']!=agency: raise HTTPException(403,'booking belongs to another agency')
    return booking_dict(b)
@app.get('/api/v2/bookings/{booking_id}')
def booking(booking_id:str,x_agency:str|None=Header(None),x_user:str|None=Header(None)): return get_booking(booking_id,identity(x_agency,x_user))
@app.get('/api/v1/bookings/{booking_id}')
def legacy_booking(booking_id:str,x_agency:str|None=Header(None),x_user:str|None=Header(None)): return get_booking(booking_id,identity(x_agency,x_user),True)
@app.get('/api/ui/preferences')
def preferences(): return {'currency':'INR','synthetic':True}
@app.get('/ui/traffic-recording')
def recording():
    # Equivalent to an exported HAR: normal UI requests only; credentials excluded.
    return {'label':'synthetic HAR; captured normal journey', 'observation_window':'2026-01-01T00:00:00Z/2026-01-02T00:00:00Z','requests':[
      {'method':'POST','path':'/api/v2/quotes','body':{'route':'DEL-BOM'},'status':200,'source':'synthetic HAR'},
      {'method':'POST','path':'/api/v2/bookings','body':{'quote_id':'{quote_id}','traveler':'Demo traveler','fare':120},'status':200,'source':'synthetic HAR'},
      {'method':'GET','path':'/api/v2/bookings/{id}','status':200,'source':'synthetic HAR'},
      {'method':'GET','path':'/api/ui/preferences','status':200,'source':'synthetic HAR'}]}
@app.get('/', response_class=HTMLResponse)
def ui(): return '''<h1>RouteWatch Travel Sandbox</h1><p>Synthetic demo UI. Use the dashboard to scan.</p><p>Mode is controlled through <code>POST /sandbox/mode/fixed</code>.</p>'''
