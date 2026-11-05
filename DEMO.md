# 2–3 minute demo

1. Run `docker compose up --build`, open `http://localhost:5173`, and say: “This is a synthetic, local target; the rule-driven agent only has target configuration and a normal-journey traffic capture.” Click **Start scan**.
2. Open **Live activity** and **Findings**. Show the cross-agency response contains Agency B’s booking identity while testing as Agency A; show the legitimate control. Show the fare proof where the confirmation fare differs from the quote fare. Both are synthetic.
3. Open **Inventory evidence**: current journey routes are active, `/api/v1/bookings/{id}` is zombie because it is reachable but absent from the supplied synthetic observation window, and `/api/ui/preferences` is shadow because traffic observed it but the supplied inventory did not.
4. In PowerShell run `Invoke-RestMethod -Method Post http://localhost:8000/sandbox/mode/fixed`. Emphasize this is an operator action, never a scanner action. Click each **Retest after fix**; wait for real results. Legitimate baseline booking access still succeeds.
5. Click **Simulate deployment + scan**. It only emits a local event and switches to the separate documented reference profile. The disabled old endpoint is no longer confirmed zombie and the now-documented preference endpoint is active.
