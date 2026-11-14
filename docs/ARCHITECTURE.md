# Architecture

## Integrated local demo

```text
React dashboard (Vite)
  | same-origin /v1-api proxy
  v
FastAPI v1 transport (8012)
  |-- canonical v1 SQLite store (separate persistent volume)
  |-- fixture-backed discovery/inventory
  |-- bounded domain runner
  |      |-- synthetic travel API (ordinary HTTP, port 8000)
  |      |-- evidence-backed findings and request audit
  |      |-- inventory snapshot diff and deterministic test-family hints
  |      |-- independent supported retests
  |
  +-- reviewer-token gate
  +-- server-side management adapter
          |
          v
      private management API (8002, no host port)
          |
          v
      synthetic sandbox state and predefined controls

Legacy agent (8001) remains separately available for comparison.
```

The v1 runtime is the default dashboard backend in Docker Compose. The v1 and legacy stores remain separate; there is no automatic migration of historical agent rows.

## Runtime boundaries

- The v1 domain service accepts only `target_id=local-sandbox`, configured sandbox hostnames on port 8000, exactly the configured allowed origin, and two synthetic agency contexts.
- The scanner sends only GET/POST, disables redirects, applies a maximum 30-request scan budget, a maximum configured 30 requests/minute, bounded timeouts/connections and a 256 KiB response limit, and honors a global kill switch.
- Browser code never receives the management URL/token. The management service has no published host port and is reachable from the v1 container on an internal Compose network.
- The dashboard reviewer token is a local shared-secret demo gate, not enterprise SSO or individual identity proof.
- The scanner never accepts arbitrary production targets. Use only the bundled synthetic sandbox.

## Discovery and classification

`discovery.inventory` normalizes route identity and consumes four independent synthetic evidence sources: journey recording, reference inventory, historical traffic and archived route candidates. It also exposes HAR parsing and JavaScript route-literal extraction functions. Those parsers are not yet wired to live gateway ingestion or a browser crawler.

- **active:** observed legitimate journey traffic.
- **shadow:** observed in traffic but absent from the reference inventory; may overlap with active.
- **zombie:** no current journey traffic, complete zero-traffic historical evidence and explicit positive reachability.
- **unknown:** evidence is insufficient to support a stronger label.

Missing or incomplete history never means zero traffic. Archived route candidacy alone does not prove reachability.

## Change intelligence

`discovery.changes` compares normalized inventory snapshots, assigns deterministic risk scores and recommends bounded travel test families. The domain persists the changes and the dashboard displays them. The current scanner still runs its fixed supported IDOR/fare test sequence; there is no deployment webhook, frontend-bundle diff trigger or targeted test dispatch yet.

## Business logic and proof

The current v1 scanner covers:
1. Cross-agency booking read access: Agency A's own booking is the legitimate control; a finding requires the response to identify Agency B's booking and agency.
2. Client fare tampering: a modified fare is submitted for a synthetic booking and verified against a subsequent persisted booking read; the original quote and a legitimate booking are controls.

Independent retests replay these supported scenarios and verify a legitimate workflow. A finding resolves only if both exploit and legitimate-flow checks pass. Other finding types remain inconclusive until a dedicated replay routine exists.

## Persistence and remediation

V1 SQLite migrations store scans, scan events, findings, inventory snapshots, change events, proposals, approvals, executions, retests, request audit and scan configuration. Mutations use idempotency keys and request fingerprints. A pending or indeterminate management action must be reconciled before retry.

Only predefined sandbox actions can be executed through the server-side management adapter. Proposal/approval binding is persisted. The browser cannot invoke management endpoints directly.

## Deliberate limitations

Not yet implemented: generic browser crawling, real gateway/CI event ingestion, deployment-triggered scans, dynamic LLM planning, broad injection/SSRF/file-upload test coverage, duplicate refunds, cancellation abuse, payment bypass, coupon reuse, role escalation, supplier isolation, production identity/SSO, distributed workers and production deployment hardening. These must not be represented as complete.
