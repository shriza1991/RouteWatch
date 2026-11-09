"""Isolated, real-HTTP Compose smoke check. Preserves its new volumes."""

import json
import os
import socket
import subprocess
import sys
import time
import uuid

import httpx


def unused_port(exclude):
    while True:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        if port not in exclude:
            return port


PORTS = {}
for service in ('sandbox', 'agent', 'dashboard', 'v1'):
    PORTS[service] = unused_port(PORTS.values())
PROJECT = f'routewatch-suj03b-{uuid.uuid4().hex[:8]}'
ENV = dict(os.environ)
ENV.update({
    'ROUTEWATCH_SANDBOX_PORT': str(PORTS['sandbox']),
    'ROUTEWATCH_AGENT_PORT': str(PORTS['agent']),
    'ROUTEWATCH_DASHBOARD_PORT': str(PORTS['dashboard']),
    'ROUTEWATCH_V1_PORT': str(PORTS['v1']),
})
TRAVEL = f"http://127.0.0.1:{PORTS['sandbox']}"
AGENT = f"http://127.0.0.1:{PORTS['agent']}"
V1 = f"http://127.0.0.1:{PORTS['v1']}"
CLIENT = httpx.Client(timeout=5, follow_redirects=False)


def compose(*args):
    process = subprocess.run(['docker', 'compose', '-p', PROJECT, *args], env=ENV,
                             capture_output=True, text=True, timeout=600)
    if process.returncode:
        message = (process.stderr or process.stdout).replace(ENV['SANDBOX_MANAGEMENT_TOKEN'], '[redacted]')
        raise RuntimeError(f'Compose {args[0]} failed: {message[-600:]}')
    return process.stdout


def request(method, url, *, expected=200, **kwargs):
    response = CLIENT.request(method, url, **kwargs)
    assert response.status_code == expected, f'{method} {url} returned {response.status_code}: {response.text[:200]}'
    return response.json()


def wait_http(url, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            response = CLIENT.get(url)
            if response.status_code == 200:
                return response
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise TimeoutError(f'Not ready: {url}')


def wait_scan(scan_id, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        scan = request('GET', f'{AGENT}/scans/{scan_id}')
        if scan['status'] in ('completed', 'failed', 'cancelled'):
            assert scan['status'] == 'completed', f"Scan ended {scan['status']}: {scan['activity']}"
            return scan
        time.sleep(1)
    raise TimeoutError(f'Scan {scan_id} did not finish')


def manage(*args):
    output = compose('exec', '-T', 'management', 'python', 'scripts/management_request.py', *args)
    return json.loads(output)


def booking(agency, quote=None, fare=None):
    headers = {'X-Agency': agency, 'X-User': f'{agency}-smoke'}
    quote = quote or request('POST', f'{TRAVEL}/api/v2/quotes', headers=headers, json={'route': 'DEL-BOM'})
    confirmed = request('POST', f'{TRAVEL}/api/v2/bookings', headers=headers,
                        json={'quote_id': quote['quote_id'], 'traveler': 'Synthetic smoke',
                              'fare': quote['fare'] if fare is None else fare})
    stored = request('GET', f"{TRAVEL}/api/v2/bookings/{confirmed['booking_id']}", headers=headers)
    assert stored['booking_id'] == confirmed['booking_id'] and stored['agency_id'] == agency
    return quote, confirmed, stored


def headers(agency):
    return {'X-Agency': agency, 'X-User': f'{agency}-smoke'}


def scan_and_findings():
    config = {'id': 'isolated-smoke', 'base_url': 'http://sandbox:8000',
              'allowed_origins': ['http://sandbox:8000'], 'accounts': [
                  {'name': 'Agency A smoke', 'agency_id': 'agency-a', 'user_id': 'a-smoke', 'token': 'synthetic-a'},
                  {'name': 'Agency B smoke', 'agency_id': 'agency-b', 'user_id': 'b-smoke', 'token': 'synthetic-b'}],
              'max_requests': 30, 'timeout_seconds': 3, 'reference_profile': 'initial'}
    scan_id = request('POST', f'{AGENT}/scans', json=config)['scan_id']
    scan = wait_scan(scan_id)
    findings = {item['kind']: item for item in request('GET', f'{AGENT}/findings') if item['scan_id'] == scan_id}
    assert {'cross_agency_access', 'fare_tampering'} <= set(findings)
    access = findings['cross_agency_access']['proof']
    assert access['request']['account'] == 'Agency A smoke'
    assert access['response']['agency_id'] == 'agency-b'
    assert access['response']['booking_id'] in access['request']['path']
    assert access['control_booking'] != access['response']['booking_id']
    fare = findings['fare_tampering']['proof']
    assert fare['request']['body']['fare'] == fare['response']['fare']
    assert fare['response']['fare'] != fare['response']['quote_fare']
    saved = request('GET', f"{TRAVEL}/api/v2/bookings/{fare['response']['booking_id']}", headers=headers('agency-a'))
    assert saved['fare'] == fare['response']['fare']
    return scan, findings


def main():
    if not ENV.get('SANDBOX_MANAGEMENT_TOKEN', '').strip():
        raise RuntimeError('Operator-supplied management token required in this process environment')
    print(f'Isolated Compose project: {PROJECT}', flush=True)
    compose('up', '--build', '-d')
    for url in (f'{TRAVEL}/sandbox/status', f'{AGENT}/scans', f"http://127.0.0.1:{PORTS['dashboard']}/"):
        wait_http(url)
    assert manage('reset') == {'ok': True, 'mode': 'vulnerable'}
    print('Default services ready; authenticated reset passed', flush=True)

    initial_scan, findings = scan_and_findings()
    print(f"Legacy scan {initial_scan['id']} completed with both evidence-backed findings", flush=True)
    _, a, _ = booking('agency-a')
    _, b, _ = booking('agency-b')
    foreign = f"{TRAVEL}/api/v2/bookings/{b['booking_id']}"
    assert request('GET', foreign, headers=headers('agency-a'))['agency_id'] == 'agency-b'
    assert request('GET', f"{TRAVEL}/api/v1/bookings/{a['booking_id']}", headers=headers('agency-a'))['booking_id'] == a['booking_id']

    assert manage('action', 'enforce_booking_ownership', 'ownership-1')['state'] == 'applied'
    assert request('GET', foreign, headers=headers('agency-a'), expected=403)['detail']
    assert request('GET', f"{TRAVEL}/api/v2/bookings/{a['booking_id']}", headers=headers('agency-a'))['booking_id'] == a['booking_id']
    assert request('GET', foreign, headers=headers('agency-b'))['booking_id'] == b['booking_id']
    quote, _, saved = booking('agency-a', fare=1.0)
    assert saved['fare'] == 1.0 and quote['fare'] != 1.0
    assert request('GET', f'{TRAVEL}/sandbox/status')['controls'] == {
        'enforce_booking_ownership': True, 'validate_quote_fare': False, 'disable_legacy_booking': False}
    print('Ownership action blocked foreign access; own access and fare vulnerability remained', flush=True)

    assert manage('action', 'validate_quote_fare', 'fare-1')['state'] == 'applied'
    quote, _, saved = booking('agency-a', fare=1.0)
    assert saved['fare'] == quote['fare'] and saved['fare'] != 1.0
    normal_quote, _, normal_saved = booking('agency-b')
    assert normal_saved['fare'] == normal_quote['fare']
    print('Fare action restored server quote price and legitimate booking', flush=True)

    assert manage('action', 'disable_legacy_booking', 'legacy-1')['state'] == 'applied'
    assert request('GET', f"{TRAVEL}/api/v1/bookings/{a['booking_id']}", headers=headers('agency-a'), expected=410)['detail']
    assert request('GET', f"{TRAVEL}/api/v2/bookings/{a['booking_id']}", headers=headers('agency-a'))['booking_id'] == a['booking_id']
    assert request('GET', f'{TRAVEL}/sandbox/status')['mode'] == 'fixed'
    print('Legacy action returned 410; current route remained usable', flush=True)

    for finding in findings.values():
        retest_scan = request('POST', f"{AGENT}/findings/{finding['id']}/retest")['retest_scan_id']
        wait_scan(retest_scan)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            results = [r for r in request('GET', f'{AGENT}/retests') if r['finding_id'] == finding['id'] and r['scan_id'] == retest_scan]
            if results:
                assert results[0]['passed'] == 1 and results[0]['legitimate'] == 1
                break
            time.sleep(1)
        else:
            raise TimeoutError(f'Retest result absent for {finding["kind"]}')
    print('Legacy retest recorded pass for both findings (fresh-scan heuristic)', flush=True)

    compose('restart', 'sandbox', 'management', 'agent', 'dashboard')
    wait_http(f'{TRAVEL}/sandbox/status'); wait_http(f'{AGENT}/scans')
    assert request('GET', f'{TRAVEL}/sandbox/status')['mode'] == 'fixed'
    assert any(s['id'] == initial_scan['id'] for s in request('GET', f'{AGENT}/scans'))
    assert all(any(f['id'] == item['id'] for f in request('GET', f'{AGENT}/findings')) for item in findings.values())
    print('Restart preserved controls, scan and findings', flush=True)

    assert manage('reset')['mode'] == 'vulnerable'
    assert request('GET', f'{TRAVEL}/sandbox/status')['mode'] == 'vulnerable'
    _, a2, _ = booking('agency-a'); _, b2, _ = booking('agency-b')
    assert request('GET', f"{TRAVEL}/api/v2/bookings/{b2['booking_id']}", headers=headers('agency-a'))['agency_id'] == 'agency-b'
    assert request('GET', f"{TRAVEL}/api/v1/bookings/{a2['booking_id']}", headers=headers('agency-a'))['booking_id'] == a2['booking_id']
    quote, _, saved = booking('agency-a', fare=1.0)
    assert saved['fare'] == 1.0 and quote['fare'] != 1.0
    second_scan, _ = scan_and_findings()
    print(f"Reset restored all vulnerabilities; second scan {second_scan['id']} confirmed both findings", flush=True)

    compose('--profile', 'v1', 'up', '--build', '-d', 'v1-transport')
    wait_http(f'{V1}/v1/scans')
    assert request('GET', f'{V1}/v1/scans') == []
    assert request('GET', f'{V1}/v1/inventory?target_id=isolated-smoke', expected=503)['code'] == 'capability_unavailable'
    v1_target = {'target': {'id': 'isolated-smoke', 'base_url': 'http://sandbox:8000',
                  'allowed_origins': ['http://sandbox:8000'], 'accounts': [
                      {'id': 'a', 'agency_id': 'agency-a', 'user_id': 'a', 'credential_ref': 'server:agency-a'},
                      {'id': 'b', 'agency_id': 'agency-b', 'user_id': 'b', 'credential_ref': 'server:agency-b'}],
                  'max_requests': 30, 'timeout_seconds': 3}}
    assert request('POST', f'{V1}/v1/scans', json=v1_target, headers={'Idempotency-Key': 'smoke-v1'}, expected=503)['code'] == 'capability_unavailable'
    print('Opt-in v1 ready; absent domain/inventory returned 503', flush=True)

    config = json.loads(compose('--profile', 'v1', 'config', '--format', 'json'))
    assert not config['services']['management'].get('ports')
    assert 'SANDBOX_MANAGEMENT_TOKEN' not in config['services']['dashboard'].get('environment', {})
    assert 'SANDBOX_MANAGEMENT_TOKEN' not in config['services']['agent'].get('environment', {})
    dashboard_source = CLIENT.get(f"http://127.0.0.1:{PORTS['dashboard']}/src/main.tsx").text
    assert ENV['SANDBOX_MANAGEMENT_TOKEN'] not in dashboard_source
    print('Management unpublished; token absent from agent/dashboard configuration and served source', flush=True)
    compose('stop')
    print(f'SMOKE PASSED; isolated project stopped, volumes retained: {PROJECT}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        token = ENV.get('SANDBOX_MANAGEMENT_TOKEN', '')
        message = str(error).replace(token, '[redacted]') if token else str(error)
        print(f'SMOKE FAILED: {message}', file=sys.stderr)
        raise SystemExit(1)
