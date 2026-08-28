"""Approval-flow spike (plan §4-§5): the whole phase-2 lifecycle, offline.

Act 1  a stand-in Enablement agent (dry runtime) drafts training + comms for
       real and *intends* the access provision — recorded, not executed.
Act 2  the transcript a human would approve.
Act 3  approve_and_execute: approval note, the provision runs, the run seals.
Act 4  the walls, live: approve_vendor is refused (unknown action), and a
       side effect attempted without an approval above it is refused by policy.

  python spikes/approval_spike.py [--db PATH] [--trace]

Then:  pollard show <db> <root-id> --payloads
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from pollard import PolicyViolation

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))  # `python spikes/...` puts spikes/ first, not the root

import ledger.enablement as enablement  # noqa: E402
from actions.enablement import (  # noqa: E402
    DRAFT_ROLLOUT_COMMS,
    GENERATE_TRAINING,
    PROVISION_ACCESS,
)
from ledger import DEFAULT_DB  # noqa: E402
from ledger.enablement import (  # noqa: E402
    ApprovalGate,
    approval_transcript,
    approve_and_execute,
    open_enablement_run,
)
from ledger.seal import signer_identity  # noqa: E402

VENDOR = "acme-saas-inc"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=DEFAULT_DB, help="ledger sqlite path")
    ap.add_argument(
        "--trace", action="store_true", help="print the spans Cloud Trace would receive"
    )
    args = ap.parse_args()
    if args.trace:
        from ledger.tracing import local_tracing

        local_tracing("console")

    invocation = f"approval-spike-{datetime.now():%Y%m%dT%H%M%S}"
    enablement.reset()
    enablement.dry_runtime(store=args.db)

    print("— Act 1: the agent's dry pass (drafts real, side effects intent-only)")
    run = open_enablement_run(invocation, VENDOR)
    run.take_action(
        GENERATE_TRAINING,
        {"vendor_id": VENDOR, "topics": ["MFA on the legacy tier", "evidence freshness"],
         "audience": "it-admins"},
    )
    run.take_action(
        DRAFT_ROLLOUT_COMMS,
        {"vendor_id": VENDOR, "summary": "Approved with conditions (risk 0.55).",
         "channels": ["#general", "#it"]},
    )
    intent = run.take_action(
        PROVISION_ACCESS,
        {"vendor_id": VENDOR, "systems": ["sso", "billing"],
         "justification": "risk 0.55 accepted; conditions tracked as findings"},
    )
    print(f"  provision_access -> {intent['status']}  node {intent['node'][:12]}…")

    print("\n— Act 2: the approval transcript")
    transcript = approval_transcript(run.root_id)
    for entry in transcript["intended"]:
        print(f"  INTENDED  {entry['tool']}  args={entry['args']}")
    for entry in transcript["drafts"]:
        keys = ", ".join(sorted(entry["result"]))
        print(f"  DRAFT     {entry['tool']}  -> {keys}")

    print(f"\n— Act 3: human approves ({signer_identity()}); execution + seal")
    outcome = approve_and_execute(run.run.label, approved_by=signer_identity(), store=args.db)
    (done,) = outcome["executed"]
    print(f"  executed  {done['tool']}  ticket={done['result']['ticket_id']}")
    sealed = outcome["seal"]
    custody = sealed.get("custody", {})
    print(f"  sealed    {sealed['digest']}  ({sealed['nodes']} nodes; custody "
          f"#{custody.get('sequence', '-')})")

    print("\n— Act 4: the walls")
    blocked = run.take_action("approve_vendor", {"status": "approved"})
    print(f"  approve_vendor        -> {blocked['status']}: {blocked['reason']}")
    gated = enablement._build_runtime(args.db, dry_run=False, policies=None)
    gated.policies = [ApprovalGate(gated.store)]
    fresh = gated.run(f"enablement:{VENDOR}:{invocation}-unapproved")
    try:
        fresh.tool_call(
            PROVISION_ACCESS,
            {"vendor_id": VENDOR, "systems": ["prod-db"], "justification": "no approval above"},
        )
    except PolicyViolation as refused:
        print(f"  unapproved provision  -> refused: {refused}  node {refused.refusal_id[:12]}…")

    print(f"\nInspect: pollard show {args.db} {outcome['root_id']} --payloads")


if __name__ == "__main__":
    main()
