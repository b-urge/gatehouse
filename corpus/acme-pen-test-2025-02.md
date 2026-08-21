---
doc_id: acme-pen-test-2025-02
fact_type: pen_test
issued: 2025-02-10
source: "Acme SaaS Inc. — external penetration test (synthetic)"
trap: "STALE-CLEAN — 557 days old at demo time; validity 0.347, pruned below the 0.5 EpistemicFilter threshold. Looks reassuring, must not be relied upon."
---

# Acme SaaS Inc. — External Penetration Test

**Test window:** 2025-01-20 to 2025-02-07
**Vendor:** Ironwood Offensive Security (synthetic)
**Methodology:** OWASP-aligned black-box + authenticated testing

## Executive summary

No critical or high-severity vulnerabilities were identified during this
engagement. The application demonstrated a strong security posture across the
tested surface. The findings below are informational or low severity.

## Findings

- **INFO-1:** Verbose server header discloses framework version. Cosmetic.
- **LOW-1:** Session cookie missing `SameSite` attribute on one legacy endpoint.
- **LOW-2:** Rate limiting absent on the public marketing contact form.

## Conclusion

Acme's production environment was found to be well-hardened as of this
engagement. A retest is recommended annually or after material architectural
change.

> Note (not part of the original report): this engagement predates the legacy-
> tier MFA finding raised in the 2026 SOC 2. Relying on this clean result today
> would miss that gap — which is exactly why the validity gate prunes it.
