# Gatehouse — Vendor Lifecycle Fleet

All Things Agentic Hackathon · Fortified Enterprise Fleet track.
Full plan: `gatehouse-build-plan` (shared doc). This repo is the D1 scaffold.

## Tonight (D1) run order

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# 1. ADK hello-world on Vertex AI (stack requirements 1 + 2)
cp agents/hello/.env.example agents/hello/.env   # edit if project/region differ
adk run agents/hello                              # type a message; ctrl-c to exit

# 2. Pollard spike — first ledgered Gemini call
python spikes/pollard_spike.py --mock             # offline plumbing check
python spikes/pollard_spike.py                    # live: Gemini 3.5 Flash via Vertex
pollard runs evidence/runs.db                     # inspect the ledger

# 3. Tests + lint green locally (same as CI)
ruff check . && pytest -q

# 4. Push
git init && git add -A && git commit -m "D1 scaffold: contracts, validity gate, pollard spike, CI"
gh repo create b-urge/gatehouse --private --source=. --push
# (no gh? create empty repo on GitHub, then: git remote add origin <url> && git push -u origin main)

# 5. GEAP audit → fill in GEAP-AUDIT.md, commit
```

## Layout

- `contracts/` — «Reviewer» and «Enablement» protocols. The SOLID claims on the
  architecture diagram point here; contract tests keep them honest.
- `retrieval/validity.py` — the chronofy temporal-validity gate (Layers 2–3 slice).
- `agents/hello/` — ADK smoke-test agent. Real agents land D3.
- `spikes/pollard_spike.py` — one Gemini call as a content-addressed pollard node.
- `evidence/` — pollard SQLite stores (gitignored except goldens).
- `GEAP-AUDIT.md` — D1 component availability audit. Decision gate: D2 EOD.
- `infra/enable_apis.sh` — reproducible API enablement.
