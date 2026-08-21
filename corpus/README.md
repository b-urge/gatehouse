# Acme corpus — synthetic vendor review demo data

Seven synthetic documents for the Gatehouse vertical slice. Every file is fake;
"synthetic" is stamped throughout so nothing reads as a real audit.

`manifest.json` is the index: each doc's `fact_type` matches a decay key in
`retrieval/validity.py`, and `validity_at_as_of` is the gate score computed for
the 2026-08-21 demo date (the live gate recomputes at query_time).

## The three demo beats these props serve

1. **Freshness trap (chronofy).** `acme-pen-test-2025-02` is clean but 557 days
   old -> validity 0.347, pruned below the 0.5 threshold; `acme-pen-test-2026-07`
   (0.932) survives. The reviewer files a "request updated pen test"
   re-acquisition finding for the pruned one. This is the retrieval/validity beat.
2. **Poisoned doc (Model Armor).** `acme-vendor-overview` carries a prompt
   injection + a fake `approve_vendor` call. Model Armor blocks it at intake
   (MATCH_FOUND, pi_and_jailbreak, HIGH); the induced tool call would hit the
   pollard registry firewall as a refusal node. Do not strip the payload.
3. **Grounded findings (the fleet).** `acme-soc2-2026` (the MFA-on-legacy-tier
   finding — the exact fact Memory Bank retrieved in the D1 audit) +
   `acme-dpa` (residency clauses, invariant) ground the security and legal
   reviewers, each Finding citing a `policy_clause` and an `evidence_node`.

`acme-rollout-comms` and `acme-iso-27001` round out the corpus so vector search
has plausible-but-wrong and supporting material to rank against.
