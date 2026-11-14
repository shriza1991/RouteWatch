# RouteWatch v1 demo and acceptance

## 5-minute demonstration

1. Start the default Compose stack with fresh `SANDBOX_MANAGEMENT_TOKEN` and `VOYAGEGUARD_REVIEWER_TOKEN` values. Confirm the management service has no host-published port.
2. Reset the sandbox to vulnerable synthetic mode using the management container's operator command.
3. Open the dashboard at `http://localhost:5173`, enter the reviewer token, and start a scan against the preconfigured local sandbox.
4. Show the scan lifecycle, bounded request audit, inventory labels and persisted findings.
5. Open the cross-agency finding. Show Agency A's request returning Agency B's synthetic booking identity while Agency A's own-booking control succeeds.
6. Open the fare finding. Show the submitted modified fare and the subsequent persisted booking read that confirms the client-controlled value.
7. Create a predefined remediation proposal, approve it with the reviewer token and execute it through the server-only management adapter.
8. Run the independent retest. Show exploit check and legitimate-flow check separately. Only a resolved outcome with both checks passed may be described as fixed.
9. Show the change-intelligence table and explain that it compares inventory snapshots; it is not yet connected to live deployment events.

## Acceptance matrix

| Requirement | Evidence in this branch | Status |
|---|---|---|
| Unified v1 runtime | Compose service, injected domain, persistent SQLite | Implemented; still coexists with legacy |
| Active/shadow/zombie inventory | Four synthetic sources, explicit coverage and reachability rules | Implemented for supplied fixtures |
| HAR and JavaScript extraction | Discovery library and unit tests | Library capability, not live ingestion |
| Change-aware priorities | Snapshot diff, risk score, test-family recommendations | Partial; no automatic targeted dispatch |
| Cross-agency booking IDOR | Synthetic two-agency exploit and legitimate control | Implemented |
| Fare tampering | Tampered booking and persisted fare read | Implemented |
| Duplicate refund/cancellation/payment/role abuse | No corresponding v1 rules yet | Not implemented |
| Scope and execution safety | Sandbox allowlist, method/rate/request/response bounds, timeout, kill switch, no redirects, audit | Implemented for local demo; not a production authorization gateway |
| Approval-gated remediation | Reviewer shared secret and predefined management actions | Implemented for local demo |
| Independent retest | Supported IDOR/fare replay plus legitimate controls | Implemented for supported finding types |
| Dashboard integration | v1 API polling and change/finding/lifecycle surfaces | Implemented; browser E2E pending |
| Production readiness | SSO, multi-tenant policy, generic discovery, broad test catalogue, distributed scaling | Not claimed |

## Safety

Use only the bundled synthetic sandbox and test accounts. Never point this demo at public websites, real TBO systems, production systems, or customer data. No denial-of-service, destructive, bulk extraction or real financial operations are part of the demo.
