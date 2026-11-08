import os, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

DB = Path(os.getenv("SANDBOX_DB", "/data/sandbox.db"))
app = FastAPI(title="RouteWatch synthetic sandbox", docs_url=None, openapi_url=None)
CONTROLS = ('enforce_booking_ownership', 'validate_quote_fare', 'disable_legacy_booking')

def now(): return datetime.now(timezone.utc).isoformat()
def con():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c
def init():
    c=con(); c.executescript('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE IF NOT EXISTS bookings(id TEXT PRIMARY KEY, agency_id TEXT, traveler TEXT, route TEXT, fare REAL, quote_fare REAL, created_at TEXT);
    CREATE TABLE IF NOT EXISTS quotes(id TEXT PRIMARY KEY, agency_id TEXT, route TEXT, fare REAL);''')
    try:
        c.execute('BEGIN IMMEDIATE')
        legacy = c.execute("SELECT value FROM settings WHERE key='mode'").fetchone()
        initial = '1' if legacy and legacy['value'] == 'fixed' else '0'
        for name in CONTROLS:
            c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)', (name, initial))
        c.execute("DELETE FROM settings WHERE key='mode'")
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
@app.on_event("startup")
def startup(): init()
def controls():
    c=con()
    try:
        values = {r['key']: r['value'] == '1' for r in c.execute(
            'SELECT key,value FROM settings WHERE key IN (?,?,?)', CONTROLS)}
        if len(values) != len(CONTROLS):
            raise RuntimeError('Sandbox controls are not initialized')
        return values
    finally:
        c.close()

def mode():
    values = controls().values()
    if all(values): return 'fixed'
    if not any(values): return 'vulnerable'
    return 'mixed'

def apply_control(name: str, enabled: bool, *, connection=None):
    """Internal, allowlisted control update for a future management adapter."""
    if name not in CONTROLS or type(enabled) is not bool:
        raise ValueError('Invalid sandbox control or boolean value')
    c=connection if connection is not None else con()
    try:
        if connection is None:
            c.execute('BEGIN IMMEDIATE')
        result = c.execute('UPDATE settings SET value=? WHERE key=?', ('1' if enabled else '0', name))
        if result.rowcount != 1:
            raise RuntimeError('Sandbox controls are not initialized')
        if connection is None:
            c.commit()
    except Exception:
        if connection is None:
            c.rollback()
        raise
    finally:
        if connection is None:
            c.close()
def identity(agency: str|None, user: str|None):
    if agency not in {'agency-a','agency-b'} or not user: raise HTTPException(401,"Synthetic account required")
    return agency
def booking_dict(r):
    data=dict(r)
    data['booking_id']=data.pop('id')
    return data
class QuoteIn(BaseModel): route: str
class ConfirmIn(BaseModel): quote_id: str; traveler: str; fare: float

def reset():
    c=con()
    try:
        c.execute('BEGIN IMMEDIATE')
        c.execute('DELETE FROM bookings'); c.execute('DELETE FROM quotes')
        # A reset begins a new demonstration cycle; old keys must not replay.
        if c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='management_executions'").fetchone() is not None:
            c.execute('DELETE FROM management_executions')
        c.executemany('UPDATE settings SET value=? WHERE key=?', [('0', name) for name in CONTROLS])
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    return {'ok':True,'mode':'vulnerable'}
def set_mode(new_mode:str):
    if new_mode not in {'vulnerable','fixed'}: raise HTTPException(400,'mode must be vulnerable or fixed')
    c=con()
    try:
        c.execute('BEGIN IMMEDIATE')
        c.executemany('UPDATE settings SET value=? WHERE key=?', [('1' if new_mode == 'fixed' else '0', name) for name in CONTROLS])
        if c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='management_executions'").fetchone() is not None:
            c.execute('DELETE FROM management_executions')
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    return {'mode':new_mode, 'note':'sandbox-only switch'}
@app.get('/sandbox/status')
def status(): return {'mode':mode(),'synthetic':True,'controls':controls()}

@app.post('/api/v2/quotes')
def quote(payload:QuoteIn, x_agency:str|None=Header(None), x_user:str|None=Header(None)):
    agency=identity(x_agency,x_user); fare=120.0 if payload.route=='DEL-BOM' else 180.0; q=str(uuid.uuid4())
    c=con(); c.execute('INSERT INTO quotes VALUES (?,?,?,?)',(q,agency,payload.route,fare)); c.commit(); c.close()
    return {'quote_id':q,'route':payload.route,'fare':fare}
@app.post('/api/v2/bookings')
def confirm(payload:ConfirmIn,x_agency:str|None=Header(None),x_user:str|None=Header(None)):
    agency=identity(x_agency,x_user); c=con(); q=c.execute('SELECT * FROM quotes WHERE id=?',(payload.quote_id,)).fetchone()
    if not q or q['agency_id']!=agency: c.close(); raise HTTPException(404,'quote not found')
    stored_fare=q['fare'] if controls()['validate_quote_fare'] else payload.fare; bid=str(uuid.uuid4())
    c.execute('INSERT INTO bookings VALUES (?,?,?,?,?,?,?)',(bid,agency,payload.traveler,q['route'],stored_fare,q['fare'],now())); c.commit(); c.close()
    return {'booking_id':bid,'agency_id':agency,'fare':stored_fare,'quote_fare':q['fare']}
def get_booking(bid, agency, legacy=False):
    flags=controls()
    if legacy and flags['disable_legacy_booking']: raise HTTPException(410,'legacy endpoint disabled')
    c=con(); b=c.execute('SELECT * FROM bookings WHERE id=?',(bid,)).fetchone(); c.close()
    if not b: raise HTTPException(404,'booking not found')
    if flags['enforce_booking_ownership'] and b['agency_id']!=agency: raise HTTPException(403,'booking belongs to another agency')
    return booking_dict(b)
@app.get('/api/v2/bookings/{booking_id}')
def booking(booking_id:str,x_agency:str|None=Header(None),x_user:str|None=Header(None)): return get_booking(booking_id,identity(x_agency,x_user))
@app.get('/api/v1/bookings/{booking_id}')
def legacy_booking(booking_id:str,x_agency:str|None=Header(None),x_user:str|None=Header(None)): return get_booking(booking_id,identity(x_agency,x_user),True)
@app.get('/api/ui/preferences')
def preferences(): return {'currency':'INR','synthetic':True}
@app.get('/ui/traffic-recording')
def recording():
    from sandbox.fixtures.validate import load_recording
    return load_recording()
@app.get('/', response_class=HTMLResponse)
def ui(): return '''<h1>RouteWatch Travel Sandbox</h1><p>Synthetic demo UI. Use the dashboard to scan.</p>'''
