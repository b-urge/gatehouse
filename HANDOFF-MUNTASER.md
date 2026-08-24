# Muntaser — handoff (evening 8/23, post-D4 build)

**State:** the review fleet runs end-to-end locally (`adk run agents/review_fleet` →
"Review vendor acme-saas-inc." → grounded findings, live 0.347 freshness prune,
synthesized risk score). Intake is live on Cloud Run with Model Armor inline
(202 clean / 403 pi_and_jailbreak, smoke-proven). The Agent Engine deploy and the
Pub/Sub→fleet dispatcher are **scripted but not yet run** — Katie runs
`infra/deploy_runtime.sh` + `infra/wire_dispatch.sh` first thing tomorrow. Your
lane is the **evidence plane**; everything below is local-first. Please don't
deploy or redeploy any cloud services tonight (Katie's loop).

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

## 2. [otel] → Cloud Trace (GEAP audit row 7) — prep tonight, verify after the deploy
- The fleet deploy script carries `--otel_to_cloud`, but it has NOT run yet, so
  Cloud Trace is expected to be empty tonight — an empty explorer is not a failure.
- Tonight: build the pollard `[otel]` content-free span export locally.
- After Katie's morning deploy: check
  https://console.cloud.google.com/traces/list?project=gatehouse-hackathon —
  engine spans + your pollard spans visible → flip row 7 in `GEAP-AUDIT.md` to
  GREEN + add a findings-log line, commit.

## 3. House rules (learned the hard way; details in GEAP-AUDIT findings)
- `ruff check . && pytest -q` before every commit. CI installs ONLY
  requirements-dev (chronofy/pollard/pytest/ruff): heavy imports stay lazy; tests
  needing flask/adk use the `pytest.importorskip` pattern already in `tests/`.
- Endpoint topology: Gemini + embeddings → `global`; platform services →
  `us-central1`; Model Armor CLI needs the regional override (scripted).
- Setup from clean clone: README top section; you have GCP editor already.

## Live resources (verified 8/23 late — build against these, clobber nothing)
- Cloud Run `gatehouse-intake` @ us-central1 — Model Armor inline; smoke-proven
- Pub/Sub: topic `vendor-docs-received`; sub `-debug` (disposable). The `-dispatch`
  push subscription arrives with tomorrow's wire step.
- **Engine:** D1 bare audit engine `5146129483631165440` (hosts the Memory Bank
  audit fact — leave alone). The fleet engine does not exist yet; after tomorrow's
  deploy there will be two — never `--agent_engine_id` against the bare one.
- Firestore: `corpus_chunks` (31 chunks + 768-dim COSINE index), `audit_chunks`, `vendors`
- Model Armor template `ma-audit` @ us-central1 (V1 -> LEGACY 9/1 — pin when touching)

## Also fair game (small, unowned, yours if you want them)
- Remove the redundant IAM grant: `gcloud projects remove-iam-policy-binding
  gatehouse-hackathon --member=user:k@burge.world --role=roles/modelarmor.admin`
- Confirm the $150 hackathon credits landed (Billing -> Credits)
- Billing alerts: send Katie the email you want on the notification channel
