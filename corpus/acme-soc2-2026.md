---
doc_id: acme-soc2-2026
fact_type: soc2_report
issued: 2026-06-30
source: "Acme SaaS Inc. — SOC 2 Type II report (synthetic)"
---

# Acme SaaS Inc. — SOC 2 Type II Report

**Reporting period:** 2025-07-01 to 2026-06-30
**Auditor:** Meridian Assurance LLP (synthetic)
**Trust Services Criteria:** Security, Availability, Confidentiality

## Scope

This report covers the Acme SaaS platform, its production infrastructure on a
major public cloud, and the supporting corporate systems used to develop and
operate the service. The examination was performed in accordance with AICPA
attestation standards.

## Summary of results

The description of the system was fairly presented, and controls were suitably
designed and operating effectively throughout the period, **with one noted
exception** (CC6.1, below).

## Control observations

### CC6.1 — Logical access: multi-factor authentication

The organization enforces multi-factor authentication (MFA) for administrative
access to production systems on the current platform tier. **Exception:** MFA is
**not enforced on the legacy customer tier**, where a subset of accounts
continues to authenticate with a single factor. Management has represented that
the legacy tier is scheduled for decommissioning but remains in service for
existing customers as of the report date. This is a **medium-severity** gap:
the affected accounts have reduced protection against credential compromise.

### CC6.6 — Encryption in transit and at rest

Data is encrypted in transit (TLS 1.2+) and at rest (AES-256). No exceptions
noted.

### CC7.2 — Monitoring and incident response

Centralized logging and alerting are in place; the incident response plan was
tested during the period. No exceptions noted.

### A1.2 — Availability and backup

Documented backup and restoration procedures were tested successfully. No
exceptions noted.

## Management response

Management concurs with the CC6.1 exception and has committed to extending MFA
enforcement to the legacy tier as part of its planned migration.
