# Exclusive ownership and repository map

Another contributor consumes and reviews an owner’s artefact but requests changes from that owner; they do not edit it. There is no `AGENTS.md` in the repository, so no repository-specific instruction conflicts were found.

| Path/deliverable | Sole owner | Consumers | Allowed changes | Acceptance evidence |
|---|---|---|---|---|
| `sandbox/`, `tests/test_sandbox.py` | Shriraj | Ram, Akshat, Sujal | synthetic app/management behavior and sandbox tests | HTTP behavior and sandbox tests |
| `agent/reference_inventory.json` | Akshat | Ram, Vikram | reference fixtures only | classification fixture test |
| **Proposed** `discovery/`, `tests/discovery/` | Akshat | Ram, Sujal | capture/import/normalisation/classification | redaction and label tests |
| `agent/app.py` | Ram | Sujal, Vikram | domain orchestration only; proposed split below | agent tests and structured domain results |
| **Proposed** `agent/domain/`, `tests/agent/` | Ram | Sujal | rules, executor, state decisions | rule/retest/cancel tests |
| `dashboard/` | Vikram | Sujal, Ram | frontend only | browser/component tests against contracts |
| `shared/`, **proposed** `transport/`, `persistence/`, `tests/integration/` | Sujal | all | schemas, routes, SQLite migrations, integration | restart/E2E tests |
| `docker-compose.yml`, Dockerfiles, `.env.example`, `requirements.txt` | Sujal | all | root operations | reproducible startup |
| `README.md`, `DEMO.md`, this `docs/` tree, `TEAM.md` | Sujal | all | integration/documentation; role content reviewed by named owner | link/acceptance review |
| `dashboard/index.html`, `package*.json`, TS config, Vite config | Vikram | Sujal | dashboard build dependencies/config | `npm run build` |
| `.gitignore` | Sujal | all | repository hygiene | clean generated files |

## Existing mixed-responsibility files

`agent/app.py` presently mixes FastAPI transport, SQLite persistence, discovery, execution, classification, lifecycle, and retest orchestration. It must be split **in a future implementation**, without moving files in this documentation task: `agent/domain/` (Ram), `discovery/` (Akshat), and `transport/`/`persistence/` (Sujal). `shared/schemas.py` is currently both schema source and undeclared integration boundary; Sujal will version it. `TEAM.md` has obsolete generic ownership labels and should be reconciled by Sujal after team agreement.
