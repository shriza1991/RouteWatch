from fastapi.testclient import TestClient
from sandbox.app import app

def headers(agency): return {'X-Agency':agency,'X-User':'tester'}
def book(client,agency):
 q=client.post('/api/v2/quotes',json={'route':'DEL-BOM'},headers=headers(agency)).json()
 return client.post('/api/v2/bookings',json={'quote_id':q['quote_id'],'traveler':'Synthetic','fare':q['fare']},headers=headers(agency)).json()
def test_vulnerable_and_fixed_security_controls(tmp_path,monkeypatch):
 monkeypatch.setattr('sandbox.app.DB',tmp_path/'sandbox.db')
 with TestClient(app) as c:
  c.post('/sandbox/reset');a=book(c,'agency-a');b=book(c,'agency-b')
  foreign=c.get('/api/v2/bookings/'+b['booking_id'],headers=headers('agency-a'))
  assert foreign.status_code==200 and foreign.json()['agency_id']=='agency-b'
  q=c.post('/api/v2/quotes',json={'route':'DEL-BOM'},headers=headers('agency-a')).json();tampered=c.post('/api/v2/bookings',json={'quote_id':q['quote_id'],'traveler':'Synthetic','fare':1},headers=headers('agency-a')).json();assert tampered['fare']==1
  c.post('/sandbox/mode/fixed')
  assert c.get('/api/v2/bookings/'+b['booking_id'],headers=headers('agency-a')).status_code==403
  assert c.get('/api/v2/bookings/'+a['booking_id'],headers=headers('agency-a')).status_code==200
  q=c.post('/api/v2/quotes',json={'route':'DEL-BOM'},headers=headers('agency-a')).json();fixed=c.post('/api/v2/bookings',json={'quote_id':q['quote_id'],'traveler':'Synthetic','fare':1},headers=headers('agency-a')).json();assert fixed['fare']==q['fare']
