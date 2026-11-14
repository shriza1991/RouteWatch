# RouteWatch — local VoyageGuard prototype

The **working legacy demo** runs a synthetic travel sandbox, a rule-driven security agent and a React dashboard. A separate authenticated management service lets an operator reset the sandbox or enable three predefined controls. The opt-in **v1 transport** has durable polling contracts but no live domain or inventory implementation yet.

## Docker startup

Set your own private management token in PowerShell (or an untracked `.env`). The following works in Windows PowerShell as well as PowerShell 7. Compose refuses a missing or blank value. Do not put it in `VITE_*` configuration.

```powershell
$bytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$rng.Dispose()
$env:SANDBOX_MANAGEMENT_TOKEN = [BitConverter]::ToString($bytes).Replace('-', '')
docker compose up --build -d
docker compose ps
```

Open <http://localhost:5173>. Travel status is at <http://localhost:8000/sandbox/status>; the legacy agent is at <http://localhost:8001/scans>. Compose sets the dashboard's target origin to `http://sandbox:8000`, which the agent container can reach. The browser sends this origin to the agent; it does not make direct travel API calls. Management listens on port 8002 **inside its own container only**, with no published host port.

Management shares `/data/sandbox.db` with travel. It binds `0.0.0.0` inside its container so `docker compose exec` can use its local loopback socket; native startup binds `127.0.0.1`. Its private Compose network has no dashboard or agent membership. This is not complete isolation from privileged containers or host administrators.

Run authenticated operator commands without putting the token in a command argument:

```powershell
docker compose exec -T management python scripts/management_request.py reset
docker compose exec -T management python scripts/management_request.py action enforce_booking_ownership demo-ownership-1
docker compose exec -T management python scripts/management_request.py action validate_quote_fare demo-fare-1
docker compose exec -T management python scripts/management_request.py action disable_legacy_booking demo-legacy-1
# Optional whole-mode convenience:
docker compose exec -T management python scripts/management_request.py mode fixed
```

Start the incomplete v1 polling API only when needed:

```powershell
docker compose --profile v1 up --build -d
Invoke-RestMethod http://localhost:8012/v1/scans
```

It uses its own `/data/voyageguard-v1.db` volume. The v1 inventory endpoint is now backed by the repository's four independent synthetic discovery fixtures for `target_id=local-sandbox`; it does not probe the network and leaves zombie candidates unclassified until reachability is established. Scan and remediation lifecycle commands still require domain services and return an honest 503 until those services are wired. The default dashboard and legacy agent are unchanged. See [v1 transport](docs/TRANSPORT.md) and the [transformation roadmap](docs/IMPLEMENTATION_ROADMAP.md).

## Demo and reset

After authenticated reset, click **Start scan**. Wait for a completed run and inspect the real findings, inventory evidence and request audit. To remediate manually, run the relevant `action` commands above. Then click **Retest after fix** on each finding. The legacy retest starts a fresh scan and marks pass if it completes without a finding of the same kind; it does not implement v1 approval, execution, independent proof replay or resolution. **Simulate deployment + scan** records a local simulated event and changes the reference profile; it does not change sandbox controls.

The sandbox acceptance tests independently exercise vulnerable behavior, authenticated actions and post-action HTTP behavior. They are stronger evidence for the predefined target controls than the current legacy agent retest. Historical inventory logs are labelled synthetic and were not measured over real days. Travel identity uses synthetic headers, not production authentication.

Reset clears sandbox quotes, bookings, controls and management action/idempotency records; it does **not** erase agent scan history. Restarting Compose without deleting volumes preserves both SQLite stores. Reusing an action key after an ordinary restart returns its prior result; reset or manual mode change invalidates those records. To regenerate the custom journey recording, reset first, then run from the repository root:

```powershell
python -m sandbox.fixtures.record --base-url http://127.0.0.1:8000 --output sandbox/fixtures/journey-recording.v1.json
docker compose up --build -d sandbox management
```

The recorder makes ordinary travel HTTP requests and never resets the target. Rebuild the sandbox image to serve the regenerated host fixture. The reference inventory, simulated history and archived candidate are described in [fixture handoff](sandbox/fixtures/README.md).

## Native PowerShell alternative

Install `requirements.txt` in a local Python environment. In separate shells from the repository root, use the **same absolute** `SANDBOX_DB` for travel and management:

```powershell
$env:SANDBOX_DB = 'C:\Users\dyara\RouteWatch\data\sandbox.db'
python -m uvicorn sandbox.app:app --host 127.0.0.1 --port 8000
```

```powershell
$env:SANDBOX_DB = 'C:\Users\dyara\RouteWatch\data\sandbox.db'
# Set SANDBOX_MANAGEMENT_TOKEN to the same private value used by the operator shell.
python -m uvicorn sandbox.management.api:app --host 127.0.0.1 --port 8002
```

```powershell
$env:AGENT_DB = 'C:\Users\dyara\RouteWatch\data\agent.db'
python -m uvicorn agent.app:app --host 127.0.0.1 --port 8001
```

For native operator calls, set the same token privately in the operator shell and use `Authorization: Bearer` as in [sandbox handoff](sandbox/HANDOFF.md). In `dashboard/`, run `npm install` and `npm run dev`; its existing defaults point to local ports 8000 and 8001. Native optional v1 startup is in [v1 transport](docs/TRANSPORT.md).

## Verification and limits

```powershell
python -m pytest -q
docker compose config -q
```

The legacy agent has its own SQLite schema and rule-driven scan. V1 persistence, approval policy, eligibility and retest outcomes are separate and not wired into it. See [DEMO.md](DEMO.md), [TEAM.md](TEAM.md) and [ownership](docs/OWNERSHIP.md).

For a repeatable real-container check, run `python scripts/container_smoke.py` from a PowerShell session with an operator-supplied management token. It creates an isolated Compose project on unused host ports, performs authenticated reset and HTTP assertions, then stops its containers while retaining its new volumes. See the [verified integration status](docs/INTEGRATION_STATUS.md) for results and remaining owner handoffs.
