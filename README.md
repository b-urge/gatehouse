# Gatehouse — Vendor Lifecycle Fleet

All Things Agentic Hackathon · Fortified Enterprise Fleet track.
Full plan: `gatehouse-build-plan` (shared doc). Deadline: **Aug 31, 5:00 pm PDT**.

**Status (D1 closed, early AM 8/21):** scaffold live, CI green, and the GEAP availability
audit is fully swept — **6/7 components GREEN** on this account, zero gated, Observability
deferred until the otel exporter exists (wiring it IS that audit). First Gemini call
ledgered in pollard; Firestore vector search proven end to end; two endpoint-topology
discoveries banked. Verdicts + findings: `GEAP-AUDIT.md` — read the findings log before
debugging anything that smells like a permissions error. Muntaser has GitHub + GCP access
(editor, granted 8/21). D2 decision gate is effectively cleared; confirm at the morning
sync and green-light the D3 build.

## Setup (clean clone)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt   # includes google-adk[gcp]
cp agents/hello/.env.example agents/hello/.env            # global endpoint pre-set (see topology)
gcloud auth login && gcloud auth application-default login
gcloud config set project gatehouse-hackathon             # jemsbhai@gmail.com already granted editor
ruff check . && pytest -q                                 # green before you write anything
```

## Muntaser — D2 checklist

1. **Prove your access first** (fresh IAM; catch auth issues before they masquerade as bugs):
```bash
   adk run agents/hello                    # live Gemini 3.5 Flash; 'exit' to quit
   python spikes/pollard_spike.py          # same call, ledgered -> evidence/runs.db
   python infra/audit/04_vector_search.py  # embeddings + find_nearest (index exists)
```
   Any PERMISSION_DENIED here → check `GEAP-AUDIT.md` topology findings before IAM rabbit holes.
2. **pollard ActionSpec registry + `tool_call` refusal-node spike** — the `model_call`
   wrapper is already proven in `spikes/pollard_spike.py`; extend the same pattern.
   A registry-refused call recorded as a refusal node is the demo's second gate beat.
3. **`[otel]` bridge → Cloud Trace** — export pollard's content-free spans (ADK spans too
   if cheap). Spans visible at console → Trace explorer **completes audit row 7**; flip it
   to GREEN in `GEAP-AUDIT.md` + add a findings line.
4. Commit spikes under `spikes/`, findings to `GEAP-AUDIT.md`, push — same
   log-as-you-learn pattern as D1.
5. Optional if time: poke Memory Bank against the live engine (ID below) —
   `infra/audit/03_memory_bank.py` is the working example.

## Katie — D2/D3

- Morning sync: confirm decision gate, divide D3 (orchestrator + security-reviewer +
  dpa-legal-reviewer per plan §4; Acme corpus with timestamps, poisoned doc, stale-pen-test trap).
- Registry note for D3: "publish an agent" = create a **Service** record (`agents` is
  read/search-only); create flags captured in the D1 audit output.
- Tidies: remove redundant `modelarmor.admin` grant; confirm $150 hackathon credits landed.

## Endpoint topology — the D1 discoveries (read before debugging "permissions")

- **Gemini models + embeddings → the `global` endpoint** (`GOOGLE_CLOUD_LOCATION=global`). Regional 404s.
- **Platform services → `us-central1`**: Agent Engine/Runtime, Memory Bank, Firestore, Model Armor.
- **Model Armor's gcloud surface needs a regional endpoint override** or it returns a
  *misleading* `PERMISSION_DENIED` — override baked into `infra/audit/01_model_armor.sh`.
- Firestore vectors: **768 dims pinned** (hard cap 2048; gemini-embedding-001 defaults 3072).
  Vector indexes are per-collection; a failed query prints the exact create command.

## Live resources (created during the audit — build against these)

- Agent Engine (bare; hosts Memory Bank): **`5146129483631165440`** @ us-central1
- Model Armor template: **`ma-audit`** @ us-central1 (pi/jailbreak; filter V1 → LEGACY
  2026-09-01 — pin the version when wiring for real)
- Firestore: `audit_chunks` collection + 768-dim COSINE vector index

## Layout

- `contracts/` — «Reviewer» / «Enablement» protocols + contract tests (the SOLID diagram points here)
- `retrieval/validity.py` — chronofy temporal-validity gate (freshness trap proven in `tests/test_validity.py`)
- `agents/hello/` — ADK smoke agent; real agents land D3
- `spikes/pollard_spike.py` — one Gemini call as a content-addressed pollard node (mock + live)
- `infra/audit/` — the D1 sweep: 01 Model Armor · 02 Runtime · 03 Memory Bank · 04 vector search · 05 registry/identity/gateway probes
- `evidence/` — pollard SQLite stores (gitignored; goldens promoted deliberately on D8)
