"""Validate sandbox-owned handoff data before serving or saving it."""

import json
import re
from datetime import datetime
from pathlib import Path


HERE = Path(__file__).parent
ALLOWED = {('POST', '/api/v2/quotes'), ('POST', '/api/v2/bookings'),
           ('GET', '/api/v2/bookings/{id}'), ('GET', '/api/ui/preferences')}
UUID = re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.I)


def instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError('timestamp must be UTC')
    return parsed


def validate_recording(data):
    if data.get('schema_version') != '1.0' or data.get('synthetic') is not True or data.get('format') != 'routewatch-journey-recording-v1' or not data.get('provenance'):
        raise ValueError('invalid recording metadata')
    serialized = json.dumps(data).lower()
    if any(secret in serialized for secret in ('authorization', 'password', 'cookie', '/management/', '/sandbox/reset', '/sandbox/mode/')) or UUID.search(serialized):
        raise ValueError('recording contains a secret, management route, or runtime identifier')
    events = data.get('requests', [])
    if len(events) != 7:
        raise ValueError('expected two three-step journeys and preferences')
    start = instant(data['observation_window']['start'])
    end = instant(data['observation_window']['end'])
    if start > end:
        raise ValueError('inverted observation window')
    expected = [(agency, method, path) for agency in ('agency-a', 'agency-b')
                for method, path in (('POST', '/api/v2/quotes'), ('POST', '/api/v2/bookings'), ('GET', '/api/v2/bookings/{id}'))]
    expected.append(('ui', 'GET', '/api/ui/preferences'))
    previous = start
    for event, (agency, method, path) in zip(events, expected):
        current = instant(event['timestamp'])
        if not start <= current <= end or current < previous:
            raise ValueError('event outside window or out of order')
        previous = current
        if (event.get('account_context_id'), event.get('method'), event.get('path')) != (agency, method, path) or (method, path) not in ALLOWED or event.get('status') != 200:
            raise ValueError('unexpected normal journey request')
        if event.get('source') != 'synthetic journey recording':
            raise ValueError('invalid event provenance')
        if agency != 'ui':
            response = event['response']
            if method == 'POST' and path.endswith('quotes'):
                if response.get('quote_id') != f'{{quote:{agency}}}' or not isinstance(response.get('fare'), (int, float)):
                    raise ValueError('quote placeholder or fare invalid')
            elif path == '/api/v2/bookings':
                if event['body'].get('quote_id') != f'{{quote:{agency}}}' or response.get('booking_id') != f'{{booking:{agency}}}' or response.get('agency_id') != agency or event['body'].get('fare') != response.get('quote_fare'):
                    raise ValueError('booking relationship invalid')
            elif response.get('booking_id') != f'{{booking:{agency}}}' or response.get('agency_id') != agency:
                raise ValueError('own-booking relationship invalid')
    return data


def validate_history(data):
    if data.get('schema_version') != '1.0' or data.get('synthetic') is not True or data.get('provenance') != 'simulated historical traffic':
        raise ValueError('invalid history metadata')
    start, end = instant(data['observation_window']['start']), instant(data['observation_window']['end'])
    if start >= end:
        raise ValueError('invalid history window')
    for item in data['endpoints']:
        coverage = item.get('coverage')
        count = item.get('legitimate_requests_in_window')
        if coverage == 'complete' and (not isinstance(count, int) or count < 0):
            raise ValueError('complete history requires an explicit count')
        if coverage == 'incomplete' and count is not None:
            raise ValueError('incomplete history cannot assert zero traffic')
        if coverage not in ('complete', 'incomplete'):
            raise ValueError('invalid coverage')
        last = item.get('last_legitimate_at')
        if last and instant(last) > end:
            raise ValueError('last traffic is after window')
    return data


def load_recording():
    return validate_recording(json.loads((HERE / 'journey-recording.v1.json').read_text(encoding='utf-8')))
