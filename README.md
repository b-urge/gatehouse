# Gatehouse — Vendor Lifecycle Fleet

All Things Agentic Hackathon · Fortified Enterprise Fleet track.
Full plan: `gatehouse-build-plan` (shared doc). Deadline: **Aug 31, 5:00 pm PDT**.

**Status (end of D1):** scaffold live, CI green, GEAP availability audit fully swept —
**6/7 components GREEN** on this account, Observability deferred until the otel exporter
exists (D2 work; wiring it IS the audit). First Gemini call ledgered in pollard; Firestore
vector search proven end to end. Discoveries + verdicts: `GEAP-AUDIT.md` — read the
findings log before touching anything endpoint-shaped.

## Setup (clean clone)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt   # includes google-adk[gcp]
cp agents/hello/.env.example agents/hello/.env            # global endpoint pre-set (see topology)
gcloud auth login && gcloud auth application-default login
gcloud config set project gatehouse-hackathon             # teammates: ask Katie for project IAM first
ruff check . && pytest -q                                 # green before you write anything
```

Smoke tests (optional — prove your credentials end to end):

```bash
adk run agents/hello                    # live Gemini 3.5 Flash via ADK; 'exit' to quit
python spikes/pollard_spike.py          # same call, ledgered: pollard runs evidence/runs.db
python infra/audit/04_vector_search.py  # embeddings + find_nearest (index already exists)
```

## Endpoint topology — the D1 discoveries (read before debugging "permissions")

- **Gemini models + embeddings → the `global` endpoint** (`GOOGLE_CLOUD_LOCATION=global`). Regional 404s.
- **Platform services → `us-central1`**: Agent Engine/Runtime, Memory Bank, Firestore, Model Armor.
- **Model Armor's gcloud surface needs a regional endpoint override** or it returns a
  *misleading* `PERMISSION_DENIED` — the override is baked into `infra/audit/01_model_armor.sh`.
- Firestore vectors: **768 dims pinned** (hard cap 2048; gemini-embedding-001 defaults to 3072).
  Vector indexes are per-collection; the failed query prints the exact create command.

## Live resources (created during the audit — build against these)

- Agent Engine (bare; hosts Memory Bank): **`5146129483631165440`** @ us-central1
- Model Armor template: **`ma-audit`** @ us-central1 (pi/jailbreak filter; V1 → LEGACY 2026-09-01 — pin the filter version when wiring for real)
- Firestore: `audit_chunks` collection + 768-dim COSINE vector index

## Next up

- **D2 — Muntaser:** pollard ActionSpec registry + `tool_call` refusal-node spike; `[otel]`
  bridge into Cloud Trace (completes the 7th audit row). The `model_call` wrapper is already
  proven in `spikes/`.
- **D3:** core agents (orchestrator + 2 reviewers) per plan §4. Registry note: "publish an
  agent" = create a **Service** record — `agents` is read/search-only; create flags are in
  the audit output.
- Tidies: drop the redundant `modelarmor.admin` IAM grant; confirm the $150 hackathon credits landed.

## Layout

- `contracts/` — «Reviewer» / «Enablement» protocols + contract tests (the SOLID diagram points here)
- `retrieval/validity.py` — chronofy temporal-validity gate (freshness trap proven in `tests/test_validity.py`)
- `agents/hello/` — ADK smoke agent; real agents land D3
- `spikes/pollard_spike.py` — one Gemini call as a content-addressed pollard node (mock + live)
- `infra/audit/` — the D1 sweep: 01 Model Armor · 02 Runtime · 03 Memory Bank · 04 vector search · 05 registry/identity/gateway probes
- `evidence/` — pollard SQLite stores (gitignored; goldens promoted deliberately on D8)
