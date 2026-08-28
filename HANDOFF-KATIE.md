# HANDOFF-KATIE.md — evidence plane landed (8/24 night, branch `feature/evidence-plane`)

PR: `jemsbhai/gatehouse:feature/evidence-plane` → `b-urge/gatehouse:main`. Every commit
is `ruff check . && pytest -q` green; **39 tests, all offline** (CI still installs only
requirements-dev; ADK/flask/otel tests `importorskip`). Nothing here touched the cloud —
that is deliberately yours, and the checklist below is exactly what needs doing there.

## Short version

All four items from HANDOFF-MUNTASER.md are built and proven offline:

1. **Every fleet search is a pollard node.** `search_vendor_evidence` now runs as the
   registered action `retrieve_evidence@1`; findings cite `evidence_node` = a real 64-hex
   node id (never "unrecorded"), the final ReviewResult carries `evidence_run` (the root
   id), and the verdict is noted under the run. Option B from the plan: the retrieval is
   the action's *handler*, so `GATEHOUSE_LEDGER_MODE=replay` serves a recorded retrieval
   without Firestore or embeddings.
2. **Intake verdicts are nodes.** Each `/intake` request is one run `intake:<vendor>:<doc>`;
   `screen_document@1` records the Model Armor verdict + decision, `publish_intake@1`
   records the publish. The document text never enters the ledger — pollard's `sensitive`
   schema field stores a content-committing digest. Both node ids ride the 403/202 bodies
   and the Pub/Sub event (`screen_node`, `intake_run`).
3. **Refusal node.** `python spikes/refusal_spike.py` parses `approve_vendor(status="approved")`
   out of the poisoned corpus doc, feeds it to the fleet's registry, and the ledger gets a
   `REFUSAL` node (`policy`, blocked-payload digest, registry digest) plus a provenance
   note naming the source doc. `pollard show` renders it `[REFUSED]`.
4. **[otel] → Cloud Trace.** The ledger emits one content-free span per node (ids and
   digests only), nested under whatever OTel span is current — under ADK that is your
   `execute_tool search_vendor_evidence` span. Library code never installs a provider, so
   on Agent Engine it joins the one `--otel_to_cloud` sets up. Verified locally with an
   in-memory exporter, including the nesting; **Cloud Trace itself is your step (D below).**

## What landed (read in this order if you want the shape in 10 minutes)

| Where | What |
|---|---|
| `actions/__init__.py` | ActionSpec registry: `retrieve_evidence@1` (read-only, strict schema, `additionalProperties: false`), `FORBIDDEN_ACTIONS = ("approve_vendor",)` guarded in `build_registry` |
| `ledger/__init__.py` | Runtime per process, `ReviewRun` per ADK invocation; `consult()`, `open/close_review_run`; env: `GATEHOUSE_EVIDENCE_DB`, `_LEDGER_MODE`, `_QUERY_TIME`, `_RUN_LABEL`, `_LEDGER_TRACE`; falls back to in-memory (with a warning) if the store path can't open |
| `ledger/tracing.py` | `ledger_span_hook()` (default `on_node`), `export_run()`, `local_tracing()` |
| `agents/review_fleet/agent.py` | `build_fleet(model=)` factory (tests inject a scripted LLM); `before/after_agent_callback` open/close the run; tool takes `tool_context`; synthesizer emits `evidence_run` |
| `retrieval/search.py` | additive `RetrievalResult.to_dict()` — nothing else changed |
| `contracts/reviewer.py` | `ReviewResult.evidence_run: str = "unrecorded"` (defaulted) |
| `services/intake/evidence.py` + `main.py` | intake's own registry/runtime (self-contained: Cloud Run builds from `services/intake` alone); your handlers and `decide()` untouched |
| `spikes/refusal_spike.py` | the demo beat; `--trace` prints the spans Cloud Trace would receive |
| `tests/test_{actions,ledger,fleet_ledger,refusal_spike,intake_ledger,tracing}.py` | 21 new tests; `test_fleet_ledger.py` drives the real fleet through ADK's `InMemoryRunner` with a scripted model + fake retriever |
| `agents/review_fleet/requirements.txt`, `services/intake/requirements.txt`, `infra/deploy_runtime.sh`, `.env.example` | deploy config: pollard in both images; `--extra_packages actions ledger` |

## Your cloud checklist (in order)

**A. Merge the PR, then a local sanity run** (this is the demo path; nothing about your
   instructions or model calls changed, only what's underneath the tool):
```bash
pip install -r requirements.txt -r requirements-dev.txt     # root deps unchanged
adk run agents/review_fleet                                  # "Review vendor acme-saas-inc."
```
   Expect: same review as before, but every finding's `evidence_node` is a 64-hex id, the
   final JSON has `"evidence_run": "<root id>"`, and stdout ends with two `[ledger]` lines:
   `spent={'seconds': …, 'steps': N}` (N = number of searches) and the exact
   `pollard show evidence/runs.db <root>` command. Run it: `root → tool_call retrieve_evidence
   × N → note`. `--payloads` shows args (query, pinned `query_time`, `k`) and results.

**B. Deploy the fleet.** `bash infra/deploy_runtime.sh` (now stages `actions/` + `ledger/`;
   pollard is in the fleet requirements). Optional but tidy: uncomment
   `GATEHOUSE_EVIDENCE_DB=/tmp/gatehouse-runs.db` in `agents/review_fleet/.env` first —
   `adk deploy` forwards that file to the engine. Without it the ledger uses `evidence/runs.db`
   under the app dir, and if that's not writable it records in memory and warns; either way
   ids and spans still flow. Then `bash infra/wire_dispatch.sh <FLEET_ENGINE_ID>` as before.

**C. Trigger one review on the deployed fleet** (dispatcher path or a direct query).

**D. Cloud Trace — completes audit row 7.** Trace explorer, last 1h, span name
   `execute_tool retrieve_evidence`. Expected tree (this is the exact shape the offline
   test asserts under ADK's runner):
```
invocation
└─ invoke_agent vendor_review_orchestrator
   ├─ pollard root
   ├─ invoke_agent security_reviewer
   │  └─ call_llm → generate_content gemini-3.5-flash
   │     └─ execute_tool search_vendor_evidence        ← ADK's span
   │        └─ execute_tool retrieve_evidence          ← pollard's span
   ├─ invoke_agent dpa_legal_reviewer   (same shape)
   ├─ invoke_agent review_synthesizer
   └─ pollard note                                     (the verdict)
```
   Attributes on the pollard span: `pollard.node.id`, `pollard.parent.id`,
   `pollard.result.digest`, `pollard.registry.digest`, `pollard.charge.steps`, `.seconds`.
   **No query text, no evidence content, no vendor id** — that's the content-free property.
   If you see it: flip row 7 to GREEN and add the findings line (draft in GEAP-AUDIT.md).
   If Cloud Trace is empty: check the engine logs for the `[ledger]` lines first — if they're
   there the nodes were recorded and only export is off; if not, `ledger` didn't import
   (staging) — `--extra_packages` order doesn't matter, but both packages must be listed.

**E. Redeploy intake.** `bash infra/setup_intake.sh` (pollard added to its requirements).
   Smoke 1 (clean) now returns `{"accepted": true, …, "screen_node": …, "intake_run": …}`;
   smoke 2 (poisoned) returns the 403 with the same two ids. Optional:
   `--set-env-vars …,GATEHOUSE_EVIDENCE_DB=/tmp/intake.db` keeps the intake ledger across
   requests within an instance (otherwise per-process memory; the ids are still valid —
   they're content-addressed).

## Gotchas that will save you time

- The `retrieve_evidence` schema is strict on purpose: empty query, `k > 20`, or any extra
  key (e.g. a smuggled `status: approved`) is refused by the registry. The tool catches
  `PolicyViolation` and hands the model `{"error": …, "refusal_node": …}` instead of raising,
  so a bad query becomes a refusal node, not a crashed review.
- `query_time` is pinned once per review (state `query_time`), so all searches in a review
  share one as-of instant and node ids are reproducible. Set `GATEHOUSE_QUERY_TIME` +
  `GATEHOUSE_RUN_LABEL` to record a golden run replayable by name.
- Payload floats are illegal in pollard identity payloads (results are fine). That's why
  the verdict note stores the ReviewResult as JSON *text* (`risk_score` is a float).
- ADK 2.7.1 warns `SequentialAgent` → `Workflow` deprecation on every import. Your call;
  it's harmless for the hackathon.
- Intake: a Model Armor client exception now becomes a `FAILURE` verdict inside the node,
  so `decide()` fails closed *and* the ledger shows the screen was unavailable.

## Open question for the sync

The live fleet currently has no path for an injected `approve_vendor` to *reach* pollard:
reviewers only have the search tool, so a model that tried it hits ADK's "unknown tool".
The spike proves the firewall; making it bite live means a generic `take_action(name, args)`
tool routed through `run.tool_call`, so any action the model attempts — registered or not —
goes through the registry. That's also the shape phase 2's Enablement agent needs
(`grant_access`, `create_ticket`, `send_comms` as side-effectful specs, with pollard's
`confirm()` as the human-in-the-loop). Worth 15 minutes together before either of us builds it.

## Next in my lane (unless you'd rather redirect)

1. Golden run + `pytest --pollard-mode=replay` fixture under `evidence/golden/` (plan §5's
   "killer move"): needs one live run to record — that's a Gemini + Firestore run, so it's
   either you, or me with your go-ahead on credits.
2. `take_action` + phase-2 action specs per the open question above.
3. Model-call recording via ADK `before/after_model_callback` (the plan's timeboxed stretch).
4. README: replace the D2 checklist with the evidence-plane layout + inspect commands.

---

# Update 2 (8/28, the merge of `feature/replay` × your main drop)

Your enablement + Memory Bank + dispatcher approval landed while this branch was in
flight — we built phase-2 twice in parallel. Resolution, in your favor:

- **Your `actions/enablement.py` and `ledger/enablement.py` are canonical, verbatim.** My
  parallel versions and their spike/tests are deleted. Your agent, schemas, Firestore
  handlers, and recall-as-a-ledgered-node are untouched.
- **One capability ported in: closing an enablement run now seals it** — same rolling
  SHA-256 + append-only custody log as reviews (`evidence/seals.db`), replay re-derives
  without attesting — and your agent's close prints the `sealed …` line. Your
  `test_enablement_agent.py` passes unchanged (the seal rides the report additively).
- **What this branch adds underneath you** (no interface changes): every Gemini call in the
  fleet is a `model_call` node, so a recorded review replays offline end to end with the
  model and retriever provably unreached; every review close seals; tests are isolated from
  `evidence/*.db` via a conftest fixture.

Two sync topics, ten minutes total:

1. **Golden re-record.** `evidence/golden/review-acme-golden.db` predates model-call
   recording, so it can't drive the full offline replay. After this merges, one live run
   with `GATEHOUSE_RUN_LABEL` + `GATEHOUSE_QUERY_TIME` set becomes the real fixture — I'll
   have `spikes/record_golden.py` ready so your part is a single command.
2. **Dry-run approval preview** (plan §5's literal wording: "intended side-effectful actions
   recorded, not executed; human approves; actions execute"). Your dispatcher gate approves
   the *vendor*; the plan also previews the *actions*. My deleted branch ran the enablement
   agent on a `dry_run=True` runtime with an ApprovalGate policy — it's in this branch's git
   history if we decide we want it as an env-flagged mode. Your call; not a merge decision.


