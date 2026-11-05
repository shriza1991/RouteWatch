# Demo and acceptance

## 3–5 minute script (proposed final flow)

1. Reset Shriraj’s sandbox to known vulnerable synthetic state. Show management interface is separate and not scanner-discoverable.
2. Run normal A/B journeys; import the redacted capture and show synthetic timestamped historical window.
3. Start scan. Show actual discovery, scope/budget audit, active/zombie/shadow evidence, cross-agency returned agency identity, and mismatched quote/booking fare.
4. Create the predefined ownership proposal; reviewer approves it in the dashboard; execute through the server-side management adapter. Show `remediating`, then independent ordinary-API retest.
5. Show foreign access blocked and own booking access successful. Repeat for fare: tamper corrected/rejected and normal booking succeeds. Only then show resolved.
6. Disable/restrict retired endpoint; document shadow endpoint via reference update. Explain the latter is inventory reconciliation, not a fixed security issue. Reset.

## Required acceptance checks

| Check | Required evidence | Current status |
|---|---|---|
| Both vulnerabilities in vulnerable mode | real redacted proof and control | partly implemented; approval flow missing |
| Neither falsely reported fixed | fresh scan/retest with legitimate control | partly implemented; lifecycle missing |
| Inventory labels | traffic/reference/history/reachability evidence | partly implemented; labels cannot coexist |
| Unsupported/failed remediation unresolved | visible terminal state | proposed |
| Cancel/scope/budget | audit and cancelled run | partial current implementation |
| Restart persistence | agent restart retains scan/finding/audit | proposed E2E test |
| No secrets displayed | fixture/audit/dashboard checks | proposed test |
| Independent fixture work | each role’s fixture command | proposed |

Do not claim proposed tests were executed. Existing tests only cover sandbox vulnerable/fixed behavior; current dashboard/agent behavior must be reverified once refactored.
