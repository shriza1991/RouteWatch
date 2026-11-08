"""Record normal journeys over HTTP. Run only after an operator-managed reset."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx


DEFAULT_OUTPUT = Path(__file__).with_name('journey-recording.v1.json')
AGENCIES = ('agency-a', 'agency-b')


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def record(client, base_url: str):
    """Client may be httpx.Client or FastAPI TestClient; all journeys use HTTP."""
    base = base_url.rstrip('/')
    requests = []

    def call(method, path, agency, body=None, normalized_path=None, normalized_body=None, response_body=None):
        headers = {'X-Agency': agency, 'X-User': f'{agency}-recorder'} if agency else {}
        response = client.request(method, base + path, headers=headers, json=body)
        if response.status_code != 200:
            raise RuntimeError(f'Normal journey failed: {method} {normalized_path or path} returned {response.status_code}')
        event = {
            'method': method, 'path': normalized_path or path, 'status': response.status_code,
            'timestamp': utc_now(), 'account_context_id': agency or 'ui',
            'source': 'synthetic journey recording',
            'response': response_body(response.json()) if callable(response_body) else (response_body if response_body is not None else response.json()),
        }
        if normalized_body is not None:
            event['body'] = normalized_body
        requests.append(event)
        return response.json()

    for agency in AGENCIES:
        quoted = call('POST', '/api/v2/quotes', agency, {'route': 'DEL-BOM'},
                      normalized_body={'route': 'DEL-BOM'},
                      response_body=lambda actual: {**actual, 'quote_id': f'{{quote:{agency}}}'})
        confirmed = call('POST', '/api/v2/bookings', agency,
                         {'quote_id': quoted['quote_id'], 'traveler': 'Synthetic traveler', 'fare': quoted['fare']},
                         normalized_body={'quote_id': f'{{quote:{agency}}}', 'traveler': 'Synthetic traveler', 'fare': quoted['fare']},
                         response_body=lambda actual: {**actual, 'booking_id': f'{{booking:{agency}}}'})
        own = call('GET', f"/api/v2/bookings/{confirmed['booking_id']}", agency,
                   normalized_path='/api/v2/bookings/{id}',
                   response_body=lambda actual: {**actual, 'booking_id': f'{{booking:{agency}}}'})
        if own['booking_id'] != confirmed['booking_id'] or own['agency_id'] != agency:
            raise RuntimeError('Own-booking journey returned the wrong booking')

    call('GET', '/api/ui/preferences', None)
    return {
        'schema_version': '1.0', 'synthetic': True,
        'provenance': 'Recorded ordinary sandbox HTTP journey; identifiers normalized after response',
        'format': 'routewatch-journey-recording-v1',
        'label': 'synthetic custom journey recording',
        'observation_window': {'start': requests[0]['timestamp'], 'end': requests[-1]['timestamp']},
        'requests': requests,
    }


def main():
    parser = argparse.ArgumentParser(description='Record normal synthetic journeys; reset via authenticated management first.')
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    with httpx.Client(timeout=5, follow_redirects=False) as client:
        result = record(client, args.base_url)
    from sandbox.fixtures.validate import validate_recording
    validate_recording(result)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f'Recorded {len(result["requests"])} synthetic application requests to {args.output}')


if __name__ == '__main__':
    main()
