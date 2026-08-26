# Gatehouse — Vendor Lifecycle Fleet

All Things Agentic Hackathon · Fortified Enterprise Fleet track · **Submission: Aug 31, 5:00 pm PDT.**

A vendor's whole lifecycle as one autonomous, evidence-receipted pipeline: documents arrive at
a guarded door, a review fleet grounds findings in temporally-valid evidence, an approval gate
decides, and an enablement agent onboards the vendor with training **conditioned on what the
review actually found** — every consultation and action content-addressed in a cryptographic
ledger, every hop traced content-free to Cloud Trace.

> Firestore finds what's similar; chronofy decides what's still true enough to rely on;
> pollard proves what was consulted.

**Status: the full lifecycle runs autonomously in the cloud.** One `POST /intake` produces —
with zero humans — a Model Armor screen, a Pub/Sub event, a three-agent review on Agent
Engine (validity-gated retrieval, freshness-trap pruning, ledgered evidence nodes), a
risk-threshold approval, a `vendor-approved` event, and an enablement run that recalls the
findings from Memory Bank and executes three registered actions with Firestore receipts.
First full lap completed 8/26 — via Pub/Sub redelivery after two transient faults, i.e. the
pipeline **self-healed**. All **7/7 GEAP components GREEN** and load-bearing
(`GEAP-AUDIT.md`, findings log included). ~50 tests green; CI runs a slim env by design.

## The beats, and how to see them

- **Poisoned doc blocked at the door** — `bash infra/setup_intake.sh` smoke: injection →
  403 `pi_and_jailbreak` with `screen_node` + `intake_run` evidence ids on the verdict.
- **Freshness trap** — the 2025 pen test is *clean but stale*: validity decays below 0.5,
  the gate prunes it, and the reviewer files an EVIDENCE-STALE re-acquisition finding.
  Reproducible arithmetic: `python infra/seed_corpus.py --dry-run`.
- **Registry firewall, live** — the poisoned doc's `approve_vendor(...)` call is not a
  registered action; it becomes a REFUSAL node (`spikes/refusal_spike.py`, and in-agent in
  `tests/test_enablement_agent.py`).
- **Memory-conditioned enablement** (the differentiator): the review stores findings to
  Memory Bank; the enablement agent recalls them and generates
  *"MFA Setup for Acme SaaS Inc. Legacy Tier"* — the training teaches the exact gap the
  review found (`conditioned_on: ["CC6.1", "DPA §7.1"]`), then writes ticket/module/comms
  with ledger receipts.
- **Local two-session demo:**
  `adk run agents/review_fleet` → "Review vendor acme-saas-inc." (watch `[memory] stored N`)
  → then `adk run agents/enablement` → "Vendor acme-saas-inc approved. Run enablement."
- **Cloud lifecycle e2e:** POST a clean doc to the intake URL, then
  `gcloud run services logs read gatehouse-dispatch --region us-central1` — the four-line
  story: `fleet done` → `approval: APPROVED … published` → `enable: …` → `enablement done`.
- **Golden run:** `evidence/golden/review-acme-golden.db` (`golden-acme-v1`, 17 nodes,
  query_time pinned) — inspect with `pollard runs` / `pollard show`; offline replay wiring
  is in progress (below).

## Setup (clean clone)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp agents/review_fleet/.env.example agents/review_fleet/.env   # global endpoint + memory engine pre-set
gcloud auth login && gcloud auth application-default login
gcloud config set project gatehouse-hackathon
ruff check . && pytest -q     # house rule: this gate before every commit
```

## Endpoint topology (read before debugging "permissions" — hard-won D1/D4 findings)

- **Gemini models + embeddings → the `global` endpoint**; regional 404s.
- **Platform services → `us-central1`**: Agent Engine, Memory Bank, Firestore, Model Armor.
- **Model Armor gcloud needs a regional endpoint override** or it fakes a PERMISSION_DENIED
  (baked into `infra/audit/01_model_armor.sh`).
- **Agent Engine's ambient `GOOGLE_CLOUD_PROJECT` is the project NUMBER**; Firestore needs
  the ID — code resolves via `GATEHOUSE_PROJECT` (never trust a numeric project env).
- Firestore vectors: 768 dims pinned (cap 2048; model default 3072); indexes per-collection.

## Live resources

- **Cloud Run:** `gatehouse-intake` (Model Armor inline; evidence ids on responses) ·
  `gatehouse-dispatch` (fleet dispatch, approval gate, `/approved` → enablement)
- **Agent Engine:** `3060061256623849472` gatehouse-review-fleet (also hosts Memory Bank) ·
  `1286768903346716672` gatehouse-enablement · `5146129483631165440` audit engine (D1)
- **Pub/Sub:** `vendor-docs-received` (+`-dispatch` push, `-debug`) · `vendor-approved`
  (+`-enable` push, `-debug`) — 600s acks; redelivery is the retry story
- **Firestore:** `corpus_chunks` (31 chunks, 768-dim COSINE index) · `vendors` ·
  `provisioning_tickets` / `training_modules` / `comms_drafts` (enablement receipts) · `audit_chunks`
- **Agent Registry:** Service records for intake + review fleet (enablement pending)
- **Model Armor:** template `ma-audit` @ us-central1 (filter V1 → LEGACY 9/1; pin if touched)

## Next up

1. **Agent Identity denied-read beat** — the one remaining feature (auth-providers create
   flags captured in the D1 audit); holds a demo-beat slot.
2. Registry Service record for the enablement engine.
3. **Hardening:** dispatcher retry on the fleet path (pattern proven live on `/approved`);
   pollard `redact()` on PII fields; CI replay test against the golden db + verify/seal.
4. Ratify the `take_action` pattern (implemented in `agents/enablement/agent.py` with a live
   refusal test) and wire the second billing-alert channel.
5. **Freeze Thu 12:00**, then: failure-path polish, GCP-proof capture, final architecture
   diagram (SOLID v3 →), demo beat-sheet dry run, clean-clone repro test, ≤4:00 video,
   Devpost + blog (disclosure line) + #AllThingsAgenticHackathon post, teardown, **submit 8/31**.

## Layout

- `agents/review_fleet/` — orchestrator + security + DPA reviewers (SequentialAgent); opens a
  pollard run per review; persists findings to Memory Bank on close
- `agents/enablement/` — ONE agent, THREE registered actions via generic `take_action`;
  recall is a ledgered node; module generation conditioned on recalled findings
- `actions/` — the ActionSpec firewall: `retrieve_evidence@1` (phase 1) + `enablement.py`
  (recall/ticket/module/comms specs); `approve_vendor` forever absent by design
- `ledger/` — pollard Runtime per phase, content-free `[otel]` spans (`tracing.py`), review +
  enablement run lifecycles
- `memorybank/` — the cross-session bridge (store findings / recall findings; per-vendor scope)
- `retrieval/` — chunker + schema (`store.py`), validity gate (`validity.py`), gated retriever
  (`search.py`)
- `services/intake/` · `services/dispatcher/` — the Cloud Run edge and the event spine
- `corpus/` — synthetic Acme docs + manifest (poisoned doc payload is the demo — don't strip)
- `infra/` — audit scripts (01–05) + deploy/wire scripts (intake, runtime, enablement, approved)
- `evidence/` — pollard stores (gitignored except `golden/`) · `docs/assets/` — demo evidence
- `GEAP-AUDIT.md` — 7/7 verdict table + the findings log worth reading first
