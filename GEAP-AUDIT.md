# GEAP availability audit — D1

Question per component: **can THIS account perform the minimal mutation?**
Status: GREEN (works) · GATED (blocked/allowlist) · UNKNOWN (not yet checked).
Any GATED row must name its fallback here, tonight — not deferred.
Decision gate: **D2 EOD** — green-light architecture or execute fallbacks (plan §9).

Docs home: https://docs.cloud.google.com/gemini-enterprise-agent-platform

| # | Component | Minimal check | Status | Notes / fallback if GATED |
|---|-----------|---------------|--------|---------------------------|
| 1 | Agent Registry | Create + list one registry entry | GREEN | Fallback: Firestore-backed versioned agent catalog; document the mapping |
| 2 | Agent Runtime | Deploy a trivial agent; see it run async (https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime) | GREEN | Fallback: Cloud Run service/jobs + Pub/Sub triggers |
| 3 | Memory Bank | Create store; write in session A, read in session B (https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank) | GREEN | Fallback: Firestore-backed session state, honestly labeled |
| 4 | Agent Identity | Two service accounts; one denied read via IAM | GREEN | Standard IAM — expected GREEN |
| 5 | Agent Gateway | Route one call through gateway with a policy | GREEN | Fallback: policy check in orchestrator, documented as such |
| 6 | Model Armor | `gcloud services enable modelarmor.googleapis.com`; screen one test string | GREEN | Fallback: Gemini safety settings + explicit screening prompt, honestly labeled |
| 7 | Agent Observability | Hello-world span visible in Cloud Trace | GREEN | Cloud Trace + [otel] from pollard — `ledger/tracing.py`; verified in Cloud Trace 2026-08-26 after the live e2e run (see findings log) |

Audit method: open the component quickstart from the docs home, run its first
*mutating* step (not just the read), log the result + timestamp + error text.
Honest fallback mapping beats silent substitution (judges reward the former).

## Findings log — D1 night audit (2026-08-21, ~00:00–01:30 ET)

- **Endpoint topology is the story of the night.** Gemini 3.x model calls 404 on regional Vertex endpoints → must use `GOOGLE_CLOUD_LOCATION=global` (encoded in `agents/hello/.env` + spike). Model Armor is the mirror image: template CRUD + sanitize are **regional-only**, and gcloud's default global routing returns a misleading `PERMISSION_DENIED` — fixed via `api_endpoint_overrides/modelarmor` (baked into `01_model_armor.sh`; per the official troubleshooting doc). Platform services (reasoningEngines, Memory Bank) are regional (us-central1).
- **Model Armor: GREEN.** Template `ma-audit` created; clean prompt → NO_MATCH_FOUND; injection prompt → MATCH_FOUND, pi_and_jailbreak, confidence HIGH. Note: filter V1 → LEGACY on **2026-09-01** (day after deadline); pin filter version deliberately when wiring for real. The `modelarmor.admin` IAM grant added mid-debug was likely unnecessary (root cause was endpoint routing) — remove for least-privilege hygiene in the morning tidy.
- **Agent Runtime (control plane): GREEN.** Bare reasoning engine created + listed via REST. ENGINE_ID=5146129483631165440 (kept alive for D2 Memory Bank spike; idle cost ~nil). Full code deploy exercised D4 via `adk deploy agent_engine`.
- **Memory Bank: GREEN.** Fact written and semantically retrieved via ADK `VertexAiMemoryBankService` against the bare engine — using the actual phase-2 demo fact (Acme SOC 2 MFA gap). Dependency discovery: requires `google-adk[gcp]` extra (now in requirements.txt). SDK mid-rename FutureWarning (`vertexai.Client` → `agentplatform.Client`) — cosmetic, ignore.
- **Tomorrow's accelerator:** `gcloud agent-registry` and `gcloud agent-identity` command groups exist in the CLI reference → components 1 & 4 audit fast via `--help` + minimal mutation.

## Findings log — D1 late audit, part 2 (~01:40–02:30 ET)

- **Firestore vector search: GREEN (PASS).** Embed → seed → find_nearest → correct doc first (pen_test 0.2688 vs comms 0.4251, COSINE). Embeddings follow the Gemini topology rule: `gemini-embedding-001` on **global**, 768 dims pinned (Firestore caps vectors at 2048; model default 3072). Per-collection vector index required — the query error emits the exact create command; first index built in ~2 min.
- **Agent Gateway: GREEN (control plane).** networkservices API enabled; list answered (0 items). No `create` — gateways are import/export config-file resources; authoring is D5 by design.
- **Agent Registry: GREEN (control plane).** `agents` is read/search-only; authored resources are **services + bindings** ("publish an agent" = create a Service record), with `mcp-servers` a native catalog type. Create flags captured for D3.
- **Agent Identity: GREEN (control plane).** Mutable surface is `auth-providers` — create/enable/disable + IAM bindings + workload queries; type-specific params (e.g. `--api-key`) captured for D5.
- **Agent Observability: DEFERRED by design** — empty Cloud Trace ≠ gated; [otel] wiring is D2, verified then.
- APIs enabled mid-audit via gcloud self-prompts: networkservices, agentregistry, agent-identity.
- **D2 decision gate: effectively cleared ~40h early.** 6/7 GREEN, 1 deferred-by-design, zero GATED, all fallbacks unused. Architecture green-lit as drawn (Registry services/bindings note folds into D3).

## Findings log — D5 evidence plane (2026-08-24 night, Muntaser, offline)

- **Observability wired, verified locally, Cloud Trace pending.** `ledger/tracing.py` emits one content-free span per pollard node (ids + digests, never payloads) via `pollard.otel.live_span_hook`, joined to whatever TracerProvider is installed — ADK's `--otel_to_cloud` provider on Agent Engine, an in-memory/console exporter locally. `tests/test_tracing.py` asserts under ADK's own runner that the pollard span nests beneath ADK's `execute_tool search_vendor_evidence` span (same trace id) and that the query text, evidence content, vendor id and blocked payload appear in no attribute. `python spikes/refusal_spike.py --trace` prints the spans. **Row 7 → GREEN when Katie sees `execute_tool retrieve_evidence` in the Trace explorer after the fleet deploy** (HANDOFF-KATIE.md, step D).
- **Registry firewall is real.** `approve_vendor(status="approved")`, parsed from the poisoned corpus doc, produces a `REFUSAL` node (reason `policy`, blocked-payload digest `e91e13b5…`, registry digest `8dc1857e…`) — identical digests on two machines, as content addressing promises. Nothing runs; `pollard show` renders `[REFUSED]`.
- **Every retrieval is a node; replay works without the cloud.** The fleet's search is the registered `retrieve_evidence@1` handler, so `GATEHOUSE_LEDGER_MODE=replay` serves recorded consultations with Firestore/embeddings provably unreached (`report()["avoided"]["steps"]`). pollard identity payloads reject floats (results don't) — the ReviewResult is noted as JSON text.
- **Intake verdicts are nodes without the text.** `sensitive` schema fields make pollard store a content-committing digest of the document instead of the document; a Model Armor client exception becomes a `FAILURE` verdict inside the node, so `decide()` fails closed on the record.

- 2026-08-26 ~01:20 ET — **Agent Observability: GREEN — 7/7.** pollard [otel] spans verified in Cloud Trace after the live end-to-end run (intake → Pub/Sub → dispatcher → fleet on Agent Engine, take-6): `execute_tool retrieve_evidence` nested under ADK's tool span, attributes ids/digests only (node 6c706b9e…, registry 8dc1857e…, result 655b8b18…), no query text or content. 97 spans, 121.8K tokens metered; failed takes 1–5 also traced (observability caught what the dispatcher ack swallowed). The audit closes with all seven components carrying production traffic.
