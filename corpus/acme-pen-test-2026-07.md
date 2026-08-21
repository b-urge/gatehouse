---
doc_id: acme-pen-test-2026-07
fact_type: pen_test
issued: 2026-07-15
source: "Acme SaaS Inc. — external penetration test (synthetic)"
---

# Acme SaaS Inc. — External Penetration Test

**Test window:** 2026-07-01 to 2026-07-12
**Vendor:** Ironwood Offensive Security (synthetic)
**Methodology:** OWASP-aligned black-box + authenticated testing

## Executive summary

One medium-severity finding was identified, corroborating the access-control
exception noted in the 2026 SOC 2. No critical or high findings.

## Findings

- **MED-1:** Legacy customer tier permits single-factor authentication.
  Accounts on this tier can be accessed without a second factor, consistent with
  the SOC 2 CC6.1 exception. **Recommendation:** enforce MFA on the legacy tier
  or accelerate its decommissioning.
- **LOW-1:** Session cookie missing `SameSite` on one legacy endpoint (carried
  over from the prior engagement; not yet remediated).

## Conclusion

The production platform remains well-hardened; the legacy tier is the material
residual risk and should be prioritized.
