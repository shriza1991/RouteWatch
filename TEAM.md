# RouteWatch ownership and interfaces

The sole-owner rules are in [docs/OWNERSHIP.md](docs/OWNERSHIP.md). Agree contract changes in [docs/CONTRACTS.md](docs/CONTRACTS.md) before changing consumers. `shared.schemas` serves the legacy runtime; `shared.v1` serves the separate v1 transport and store.

1. **Shriraj — sandbox:** `sandbox/` and sandbox tests. Owns travel HTTP, synthetic data/fixtures, three independent controls and the separate authenticated management app. Travel and management share `SANDBOX_DB`; see [handoff](sandbox/HANDOFF.md).
2. **Akshat — discovery:** journey import, normalization and active/zombie/shadow evidence. Inputs are separate journey, reference, historical and archived-route fixtures. The v1 `InventoryService` is not integrated yet.
3. **Ram — agent:** legacy `agent/app.py` and future domain service. Owns scan planning, safe requests, findings, approval policy, execution eligibility and independent retest decisions. The v1 `DomainService` is not integrated yet.
4. **Vikram — dashboard:** `dashboard/`. Consumes the legacy agent HTTP API today; later migration should use v1 polling models. The browser never receives management credentials or invokes management.
5. **Sujal — integration/QA:** `shared/`, `persistence/`, `transport/`, `tests/integration/`, root Docker/Compose/config and release docs. Owns v1 contracts, durable storage, polling transport, server-only management adapter and deployment. Does not implement another owner's decisions.

Legacy Compose runs travel 8000, agent 8001 and dashboard 5173, with management 8002 inside a private, unpublished container. Opt-in v1 transport uses host 8012 and a separate database. Old travel mutation routes were removed; operator reset/mode/action calls use authenticated management. The v1 service currently returns 503 where domain or discovery implementations are absent. Its `applied` execution state cannot by itself resolve a finding.
