# Architecture

## Current implementation

`dashboard/` polls `agent/app.py`; the agent calls `sandbox/app.py` over HTTP. Both persist SQLite state. `agent/reference_inventory.json` is a separate reference inventory. The sandbox exposes `/ui/traffic-recording`, an HAR-equivalent fixture; this is discovery input, not OpenAPI. The sandbox currently exposes management-like `/sandbox/mode/{mode}` directly, which must be split before the approval/remediation demo is claimed complete.

```text
Normal synthetic journeys -> Akshat discovery module -> observed inventory --+
Reference inventory + synthetic history ----------------------------------+--> Ram planner/executor
                                                                            |        |
Vikram dashboard <---- Sujal transport/persistence <--- structured results |        v
                                                                approval -> sandbox management adapter -> Shriraj sandbox
                                                                                                  ordinary app HTTP -> retest
```

## Proposed module boundaries

| Module | Owner | Input | Output |
|---|---|---|---|
| `sandbox/` application API and `sandbox/management/` | Shriraj | synthetic requests; approved command | application responses; execution result |
| `discovery/` | Akshat | HAR/equivalent, reference, history | `ObservedRequest`, `Endpoint`, evidence |
| `agent/domain/` | Ram | observations, config, inventory | plans, findings, remediation/retest decisions |
| `dashboard/` | Vikram | Sujal API | user intent and rendered state |
| `shared/`, `transport/`, `persistence/`, root ops | Sujal | domain objects | durable API/event state |

The scanner must receive only ordinary application URLs plus discovered observations, explicitly configured account contexts, and approved management adapter capability. Management URL/credentials stay in Sujal/Ram server-side configuration and are never in `TestPlan`, discovery records, browser payloads, audit output, or attack executor inputs.

## Classification definitions

- **active:** observed legitimate traffic within the stated synthetic observation window and/or documented current use; evidence must state which.
- **zombie:** reachable in the authorised target **and** absent from legitimate traffic for the supplied timestamped observation window; an old-looking path alone is insufficient.
- **shadow:** observed or otherwise narrowly discovered but absent from the supplied reference inventory. It can also be active; classification therefore has `labels: set`, not a mutually exclusive field in the proposed contract.
- **unknown:** evidence cannot establish reachability, traffic status, or reference status.

Security status and inventory status are independent: disabling a retired route is remediation; documenting a shadow route is reconciliation.
