"""Operator-only local command. Run inside the management container."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description='Authenticated local sandbox operation')
    operations = parser.add_subparsers(dest='operation', required=True)
    operations.add_parser('reset')
    mode = operations.add_parser('mode')
    mode.add_argument('value', choices=('vulnerable', 'fixed'))
    action = operations.add_parser('action')
    action.add_argument('key', choices=('enforce_booking_ownership', 'validate_quote_fare', 'disable_legacy_booking'))
    action.add_argument('idempotency_key')
    args = parser.parse_args()

    token = os.environ.get('SANDBOX_MANAGEMENT_TOKEN', '')
    if not token.strip():
        print('Management token is not configured', file=sys.stderr)
        return 2
    path = '/management/reset' if args.operation == 'reset' else (
        f'/management/mode/{args.value}' if args.operation == 'mode' else '/management/actions')
    body = {'action_key': args.key, 'idempotency_key': args.idempotency_key} if args.operation == 'action' else None
    request = urllib.request.Request(
        f'http://127.0.0.1:8002{path}', method='POST',
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        data=json.dumps(body).encode() if body is not None else b'',
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            print(response.read().decode())
        return 0
    except urllib.error.HTTPError as error:
        print(f'Management request failed with HTTP {error.code}', file=sys.stderr)
        return 1
    except urllib.error.URLError:
        print('Management service unavailable', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
