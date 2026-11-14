# V1 runtime and API

The integrated local demo runs the v1 FastAPI transport, a bounded domain service, fixture-backed inventory, SQLite persistence, the existing synthetic travel sandbox, and the separate management service. The legacy agent remains available for comparison; the dashboard defaults to v1 in Docker Compose.

## Run

From PowerShell, create per-session secrets and start the default stack:

```powershell
function New-RouteWatchSecret {
  $bytes = New-Object byte[] 32
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $rng.GetBytes($bytes)
  $rng.Dispose()
  return [Convert]::ToBase64String($bytes)
}
$env:SANDBOX_MANAGEMENT_TOKEN = New-RouteWatchSecret
$env:VOYAGEGUARD_REVIEWER_TOKEN = New-RouteWatchSecret
docker compose up --build -d
```

Open `http://localhost:5173`. The dashboard calls the v1 transport through its Vite `/v1-api` proxy. The v1 API is also published on host port 8012. The management API is not published and is reachable only from the private Compose network. The reviewer token is server-side configuration and must be entered in the dashboard to approve a proposal; it is held in page memory and sent only in the approval request header.

The v1 runner accepts only `target_id=local-sandbox`, the configured sandbox host allowlist, HTTP port 8000, and the two server-side synthetic credential references. It rejects arbitrary internet targets. This is a controlled demo integration, not a general-purpose production DAST deployment.

## Implemented API

All mutation routes require an `Idempotency-Key`. Errors use a sanitized `{code,message}` body.

| Method | Route | Purpose |
|---|---|---|
| POST | `/v1/scans` | Queue and run a bounded synthetic scan |
| GET | `/v1/scans` | List persisted scans |
| GET | `/v1/scans/{id}` | Read scan state |
| GET | `/v1/scans/{id}/events` | Read persisted scan events |
| POST | `/v1/scans/{id}/cancel` | Request cancellation |
| GET | `/v1/findings` | List persisted findings |
| GET | `/v1/findings/{id}` | Read a finding |
| GET | `/v1/inventory?target_id=local-sandbox` | Read latest inventory snapshot or fixture baseline |
| GET | `/v1/changes` | Read persisted snapshot-difference events |
| POST | `/v1/findings/{id}/proposals` | Create a predefined remediation proposal |
| GET | `/v1/proposals` | List proposals |
| POST | `/v1/proposals/{id}/approval` | Record an approval/rejection after reviewer-token validation |
| GET | `/v1/approvals` | List approval records |
| POST | `/v1/proposals/{id}/execute` | Execute an approved predefined sandbox action |
| GET | `/v1/executions` | List execution results |
| POST | `/v1/findings/{id}/retest` | Independently replay supported finding proof and legitimate controls |
| GET | `/v1/retests` | List retest results |
| GET | `/v1/audit` | Read sanitized request audit events |

## Runtime behavior

- Scan requests are persisted before background execution. The runner records events, request audit, findings, an inventory snapshot, and change events.
- The initial supported business-logic checks are cross-agency booking access and persisted fare tampering. Both use synthetic Agency A/B accounts and a legitimate control.
- The scanner permits only GET and POST, caps each scan at 30 requests, caps the configured per-minute rate at 30, caps response bodies at 256 KiB, uses bounded HTTP timeouts/connections, disables redirects and honors a global kill switch.
- Inventory is built from the repository's synthetic journey, reference, historical-traffic and archived-route fixtures. HAR parsing and JavaScript route-literal extraction are reusable library functions; external ingestion and general browser crawling are not wired into this demo.
- Active means observed journey traffic; shadow means observed in traffic but absent from the reference inventory; zombie requires complete zero-traffic history and an explicit reachable result. Incomplete history remains unknown.
- Change events compare persisted inventory snapshots and recommend deterministic travel test families. No deployment webhook or CI/CD event subscription is implemented yet.
- Remediation is limited to predefined sandbox actions. Reviewer-token validation is a local shared-secret demo gate, not enterprise SSO or per-user identity.
- Retests independently replay the supported original scenario and a legitimate workflow. A finding is resolved only when both checks pass; unsupported scenarios remain inconclusive.

## Persistence and failure semantics

The v1 database is separate from the legacy agent database. Migrations are versioned and SQLite foreign keys are enabled. Mutations reserve an idempotency tuple and canonical request fingerprint before invoking domain logic. Identical completed requests replay their result; conflicting or pending requests are rejected. An indeterminate or pending management execution must be reconciled before another attempt. There is no claim of exactly-once behavior across SQLite and the management HTTP service.

The management adapter and its credential are injected server-side only. Browser payloads, v1 contracts, findings and request audit do not contain management credentials. Sandbox actions are limited to predefined control keys; do not add arbitrary command execution.

## Tests and limitations

Run:

```powershell
python -m pytest -q
docker compose config -q
cd dashboard
npm ci
npm test
npm run build
```

The new v1 domain tests use a deterministic in-memory HTTP transport and a temporary SQLite database. CI runs the Python suite, dashboard tests/build, and Compose configuration validation. A successful CI run is the evidence to cite for the current branch; historical results in `docs/INTEGRATION_STATUS.md` describe a prior revision.

Not implemented in this branch: generic browser crawler and gateway-log ingestion, deployment webhook triggers, dynamic LLM planning, broad injection/SSRF/file-upload testing, refund/duplicate-refund/cancellation/payment/coupon/sub-agent/supplier test cases, production-grade identity/SSO, distributed workers, or a production DAST authorization policy. Do not represent these as complete.
