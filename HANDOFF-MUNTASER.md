# Muntaser — handoff (evening 8/23, post-D4 build)

**State:** review fleet runs end-to-end locally (`adk run agents/review_fleet` →
"Review vendor acme-saas-inc.") and is deployed/deploying to Agent Engine; intake
(Cloud Run + Model Armor inline) and the Pub/Sub dispatcher are live. Your lane is
the **evidence plane** — everything below is local-first; please don't redeploy the
Cloud Run services or the fleet engine tonight (Katie's loop).

## 1. Pollard wiring (the "prove what was consulted" leg of the triad)
- `retrieval/search.py` → `ValidityGatedRetriever(on_consultation=...)` is your
  socket: the callback receives {query, query_time, valid[], pruned[], stl_robustness}
  and returns an evidence-node id. Wire it to a pollard tool_call node; thread the
  returned id so findings stop saying "unrecorded". `spikes/pollard_spike.py` has
  the proven model_call pattern; extend to tool_call.
- `services/intake/main.py` returns/logs Model Armor verdict dicts already shaped
  for the ledger — a MATCH_FOUND verdict recorded as a node is the intake evidence beat.
- **Refusal-node spike:** ActionSpec registry that does NOT include `approve_vendor`;
  feed it the payload from `corpus/acme-vendor-overview.md` (do not strip it — it IS
  the demo prop). Acceptance: `pollard runs` / `pollard show` display the refusal node.

## 2. [otel] bridge → Cloud Trace (GEAP audit row 7)
- Fleet deploys with `--otel_to_cloud` (see `infra/deploy_runtime.sh`) — check
  https://console.cloud.google.com/traces/list?project=gatehouse-hackathon first;
  Agent Engine spans may already be flowing. Your part: pollard `[otel]`
  content-free spans joining them. Acceptance: spans visible → flip row 7 in
  `GEAP-AUDIT.md` to GREEN + add a findings-log line, commit.

## 3. House rules (learned the hard way; details in GEAP-AUDIT findings)
- `ruff check . && pytest -q` before every commit. CI installs ONLY
  requirements-dev (chronofy/pollard/pytest/ruff): heavy imports stay lazy; tests
  needing flask/adk use the `pytest.importorskip` pattern already in `tests/`.
- Endpoint topology: Gemini + embeddings → `global`; platform services →
  `us-central1`; Model Armor CLI needs the regional override (scripted).
- Setup from clean clone: README top section; you have GCP editor already.

## Live resources (current as of 8/23 evening — build against these, clobber nothing)
- Cloud Run `gatehouse-intake` @ us-central1 — Model Armor inline; smoke-proven (202 clean / 403 pi_and_jailbreak)
- Cloud Run `gatehouse-dispatch` @ us-central1 — Pub/Sub push -> fleet streamQuery
- Pub/Sub: topic `vendor-docs-received`; subs `-debug` (disposable) and `-dispatch` (push, 600s ack)
- **Engines — two exist, don't mix them:** D1 bare audit engine `5146129483631165440`
  (hosts the Memory Bank audit fact; leave alone) and the fleet engine
  `gatehouse-review-fleet` (id via `infra/deploy_runtime.sh`'s closing list — the
  labeled one). Never `--agent_engine_id` against the bare one.
- **Runtime deploy status:** [Katie: one honest line — e.g. "deployed, e2e log showed
  'fleet done'" / "deployed, wire_dispatch not yet run" / "deploy not yet run — my
  first item tomorrow; your otel check waits on it"]
- Firestore: `corpus_chunks` (31 chunks + 768-dim COSINE index), `audit_chunks`, `vendors`
- Model Armor template `ma-audit` @ us-central1 (V1 -> LEGACY 9/1 — pin when touching)

## Also fair game (small, unowned, yours if you want them)
- Remove the redundant IAM grant: `gcloud projects remove-iam-policy-binding
  gatehouse-hackathon --member=user:k@burge.world --role=roles/modelarmor.admin`
- Confirm the $150 hackathon credits landed (Billing -> Credits)
- Billing alerts: send Katie the email you want on the notification channel
