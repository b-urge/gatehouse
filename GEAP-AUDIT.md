# GEAP availability audit — D1

Question per component: **can THIS account perform the minimal mutation?**
Status: GREEN (works) · GATED (blocked/allowlist) · UNKNOWN (not yet checked).
Any GATED row must name its fallback here, tonight — not deferred.
Decision gate: **D2 EOD** — green-light architecture or execute fallbacks (plan §9).

Docs home: https://docs.cloud.google.com/gemini-enterprise-agent-platform

| # | Component | Minimal check | Status | Notes / fallback if GATED |
|---|-----------|---------------|--------|---------------------------|
| 1 | Agent Registry | Create + list one registry entry | UNKNOWN | Fallback: Firestore-backed versioned agent catalog; document the mapping |
| 2 | Agent Runtime | Deploy a trivial agent; see it run async (https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime) | UNKNOWN | Fallback: Cloud Run service/jobs + Pub/Sub triggers |
| 3 | Memory Bank | Create store; write in session A, read in session B (https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank) | UNKNOWN | Fallback: Firestore-backed session state, honestly labeled |
| 4 | Agent Identity | Two service accounts; one denied read via IAM | UNKNOWN | Standard IAM — expected GREEN |
| 5 | Agent Gateway | Route one call through gateway with a policy | UNKNOWN | Fallback: policy check in orchestrator, documented as such |
| 6 | Model Armor | `gcloud services enable modelarmor.googleapis.com`; screen one test string | UNKNOWN | Fallback: Gemini safety settings + explicit screening prompt, honestly labeled |
| 7 | Agent Observability | Hello-world span visible in Cloud Trace | UNKNOWN | Cloud Trace + [otel] from pollard — expected GREEN |

Audit method: open the component quickstart from the docs home, run its first
*mutating* step (not just the read), log the result + timestamp + error text.
Honest fallback mapping beats silent substitution (judges reward the former).
