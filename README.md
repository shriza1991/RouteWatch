# RouteWatch — VoyageHack 4.0 prototype

RouteWatch is a local, synthetic demonstration of: discover APIs → select safe tests → execute → verify → report → retest. It has two services: an intentionally vulnerable travel sandbox and a separate HTTP security agent, plus a React dashboard.

## Run

```powershell
docker compose up --build
# open http://localhost:5173
```

Click **Start scan** while the sandbox is vulnerable. The dashboard shows real scan activity, evidence-backed cross-agency and fare findings, inventory evidence, persisted history, and audit entries.

To apply the sandbox-only fix (the scanner never changes it):

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/sandbox/mode/fixed
```

Then click **Retest after fix** on each finding. The fresh scan records a pass only if the original proof is absent and the legitimate baseline workflow completed. Click **Simulate deployment + scan** after the fix to emit a local-only deployment event and use the documented reference profile; it does not modify target behavior. Reset a demo with:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/sandbox/reset
```

## What is implemented

- Synthetic Agency A/B accounts, quotes and bookings in SQLite.
- Vulnerable/fixed ownership and server-side fare behavior.
- Discovery from a synthetic HAR-equivalent normal-journey recording, not OpenAPI, source, database or seeded IDs.
- Rule-driven planner creates fresh baseline bookings per scan, swaps IDs for the access-control test, and checks returned booking/agency identity rather than status alone.
- Fare proof confirms the stored confirmation amount differs from quote price.
- Inventory combines observed traffic, separate reference inventory and live reachability: active, zombie, shadow and unknown evidence. Historical traffic is visibly labelled synthetic; old APIs are zombie only if reachable and absent during the observation window.
- Strict configured-origin scope, redirects rejected outside scope, timeouts, maximum request budget, redacted audit data, cancel control, and durable scan/finding SQLite storage.

## Tests

```powershell
pip install -r requirements.txt
pytest -q
```

`tests/test_sandbox.py` verifies both required vulnerabilities, the fixed behavior, and legitimate retained access. Use Compose for the live agent/dashboard loop.

## Deliberate MVP limits

The HAR is a deterministic sandbox-export endpoint rather than a browser proxy; the minimal UI is informational rather than a full booking SPA. Authentication is synthetic header identity and must never be treated as production security. The agent supports the two reusable rules only and has no LLM planner. The reference inventory is a local JSON demonstration artifact; a production implementation would import a governed inventory and secure configuration/secrets.
