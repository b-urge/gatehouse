"""Refusal-node spike (plan §5; handoff item 1c): the second wall.

The poisoned corpus doc smuggles `approve_vendor(status="approved")` into its
text. Model Armor stops it at intake (the first wall). This spike shows what
happens if such an instruction ever reached an agent that tried to act on it:
the action registry has no `approve_vendor`, so pollard refuses the call *into
the ledger* — a REFUSAL node carrying the reason, the digest of the blocked
payload, and the digest of the registry that blocked it. No handler runs.

  python spikes/refusal_spike.py                 # records to evidence/runs.db
  python spikes/refusal_spike.py --db other.db
  python spikes/refusal_spike.py --trace         # + the content-free OTel spans, on stdout

Then inspect the ledger:
  pollard runs evidence/runs.db
  pollard show evidence/runs.db <root-id>
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pollard import PolicyViolation

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))  # `python spikes/refusal_spike.py` puts spikes/ first, not the root

import ledger  # noqa: E402
from actions import FORBIDDEN_ACTIONS  # noqa: E402

POISONED_DOC = REPO / "corpus" / "acme-vendor-overview.md"
VENDOR = "acme-saas-inc"

_CALL = re.compile(r"\b([a-z_][a-z0-9_]*)\(([^()]*)\)")
_KWARG = re.compile(r"([a-z_][a-z0-9_]*)\s*=\s*\"([^\"]*)\"")


def extract_injected_call(text: str) -> tuple[str, dict[str, Any]]:
    """The tool call the injection asks for, as (name, kwargs).

    Only the block-quoted lines count: that is where the payload lives, and it
    keeps prose like "SOC 2 (Type II)" from looking like a call."""
    lines = (line for line in text.splitlines() if line.startswith(">"))
    quoted = " ".join(line.lstrip("> ").strip() for line in lines)
    match = _CALL.search(quoted)
    if match is None:
        raise ValueError(f"no injected tool call found in the block-quoted text of {POISONED_DOC}")
    name, raw_args = match.groups()
    return name, {k: v for k, v in _KWARG.findall(raw_args)}


def run_spike(db: str | Path, doc: Path = POISONED_DOC) -> dict[str, Any]:
    """Feed the poisoned doc's injected call to the registry; return what the ledger recorded."""
    name, args = extract_injected_call(doc.read_text(encoding="utf-8"))

    ledger.configure(store=db)  # the fleet's own registry: retrieve_evidence@1 and nothing else
    invocation_id = f"refusal-spike-{datetime.now():%Y%m%dT%H%M%S}"
    review = ledger.open_review_run(invocation_id, VENDOR)
    registry = ledger.runtime().registry

    try:
        review.run.tool_call(name, args)
    except PolicyViolation as refused:
        refusal = review.run.store.get(refused.refusal_id)
    else:  # pragma: no cover - the registry guard in actions/ makes this unreachable
        raise AssertionError(f"{name} ran: the registry firewall is open")

    # Provenance the refusal node cannot know on its own: which document carried it.
    review.run.note(
        {
            "kind": "injection_attempt",
            "source_doc": doc.stem,
            "requested_action": name,
            "refusal": refusal.id,
        }
    )
    report = ledger.close_review_run(invocation_id)
    return {
        "injected": {"name": name, "args": args},
        "registered": [f"{spec.name}@{spec.version}" for spec in registry],
        "refusal": refusal,
        "report": report,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=ledger.DEFAULT_DB, help="ledger sqlite path")
    ap.add_argument(
        "--trace", action="store_true", help="print the spans Cloud Trace would receive"
    )
    args = ap.parse_args()

    if args.trace:
        from ledger.tracing import local_tracing

        local_tracing("console")
    out = run_spike(args.db)
    refusal, report = out["refusal"], out["report"]
    print(f"poisoned doc : {POISONED_DOC.relative_to(REPO)}")
    print(f"injected call: {out['injected']['name']}({out['injected']['args']})")
    print(f"registry     : {out['registered']}   (forbidden: {list(FORBIDDEN_ACTIONS)})")
    print(f"refusal node : {refusal.id}")
    for key, value in refusal.payload.items():
        print(f"  {key:<24}{value}")
    print(f"run          : {report['label']}  spent={report['spent']}")
    print(f"\nInspect: pollard show {args.db} {report['root_id']}")


if __name__ == "__main__":
    main()
