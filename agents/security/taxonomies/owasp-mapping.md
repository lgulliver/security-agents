# OWASP Top 10 Mapping — Security Finding Taxonomy

This file provides alignment between common PR security finding patterns and the OWASP Top 10 (2021 edition).

**Important constraints:**

- OWASP mappings are **enrichment only**. Agents must identify a concrete vulnerability from PR evidence before applying an OWASP label.
- OWASP Top 10 categories are intentionally broad. Prefer CWE for precise, code-level classification. Use OWASP for executive and security-programme reporting.
- If the OWASP category is uncertain, omit the `owasp` field rather than guessing.
- Do not raise or lower severity solely because an OWASP category is present or absent.

See [mitre-usage-guidance.md](mitre-usage-guidance.md) for the full taxonomy usage policy.

---

## A01:2021 — Broken Access Control

**Use when findings relate to:**
- Missing or bypassed authorization checks on endpoints or resources
- Insecure Direct Object Reference (IDOR) / missing ownership validation
- Tenant isolation failures — cross-tenant data access
- Privilege escalation through user-controlled input
- Scope creep — an operation executing beyond the caller's permitted scope
- Confused deputy vulnerabilities

**Preferred alongside CWE:** CWE-639, CWE-284, CWE-266, CWE-269, CWE-863

---

## A02:2021 — Cryptographic Failures

**Use when findings relate to:**
- Use of weak or broken cryptographic algorithms (MD5, SHA-1, DES, RC4)
- Hardcoded or inadequately protected cryptographic keys
- Insufficient entropy in random value generation
- Sensitive data transmitted without encryption (plain HTTP for sensitive operations)
- Sensitive data stored without encryption or with inadequate encryption
- Key management failures (keys in source, keys not rotated, keys with excessive lifetimes)

**Preferred alongside CWE:** CWE-327, CWE-321, CWE-331, CWE-522

---

## A03:2021 — Injection

**Use when findings relate to:**
- SQL injection — user input unsafely incorporated into SQL queries
- OS command injection — user input passed to shell or system calls
- Template injection — user input rendered through a template engine without sanitisation
- LDAP injection — user input incorporated into LDAP queries
- NoSQL injection — user input used in NoSQL query construction
- XSS (reflected, stored, DOM-based) — user input rendered into HTML/JavaScript without encoding
- Code injection — user input evaluated as executable code

**Note:** XSS maps to both A03 (Injection) in OWASP and CWE-79. Use the OWASP category that best supports the reporting context.

**Preferred alongside CWE:** CWE-89, CWE-78, CWE-94, CWE-79, CWE-918

---

## A04:2021 — Insecure Design

**Use when findings relate to:**
- Missing security controls that should exist by design (e.g. no rate limiting, no account lockout)
- Unsafe trust boundaries — a component trusts another without verification
- Security decisions deferred to runtime without a safe default
- Architectural changes that introduce systemic weaknesses (use alongside threat model findings)
- Missing input validation at trust boundaries

**Note:** A04 is appropriate for design-level issues, not implementation bugs. Use sparingly and only when the diff clearly demonstrates a design-level gap rather than a coding mistake.

---

## A05:2021 — Security Misconfiguration

**Use when findings relate to:**
- Unsafe default settings (default credentials, debug mode enabled, permissive CORS)
- Overly permissive infrastructure permissions (IAM wildcards, public storage, open security groups)
- Insecure HTTP headers (missing HSTS, CSP, X-Frame-Options)
- Exposed sensitive services (admin interfaces, diagnostic endpoints, database ports)
- Verbose error messages revealing internal implementation details
- TLS verification disabled or deprecated cipher suites configured

**Preferred alongside CWE:** CWE-732, CWE-668, CWE-306, CWE-1392

---

## A06:2021 — Vulnerable and Outdated Components

**Use when findings relate to:**
- New dependencies with known security advisories
- Dependencies pinned to versions with known CVEs
- Unpinned or floating dependency versions that may resolve to a vulnerable release
- Abandoned or unmaintained dependencies unlikely to receive security patches
- Third-party components with a history of supply chain compromise

**Preferred alongside CWE:** CWE-1395

---

## A07:2021 — Identification and Authentication Failures

**Use when findings relate to:**
- Missing or weakened authentication on sensitive functions
- Insecure session management (long-lived tokens, no invalidation on logout)
- Weak or default passwords accepted
- Missing multi-factor authentication on privileged operations
- Insecure password reset flows
- Token or session fixation
- Authentication bypass conditions introduced by code changes

**Preferred alongside CWE:** CWE-306, CWE-798, CWE-522

---

## A08:2021 — Software and Data Integrity Failures

**Use when findings relate to:**
- CI/CD pipeline changes that introduce unverified third-party steps
- Unsigned or unverified build artefacts
- Unpinned GitHub Actions or pipeline steps (without SHA pinning)
- Removal of SLSA provenance or SBOM generation from build pipelines
- Dependencies downloaded from unverified sources at build or runtime
- Auto-update mechanisms that do not verify integrity before applying

**Note:** This category overlaps with A06 for dependency issues. Prefer A08 when the concern is about the integrity of the build or update pipeline rather than a specific known-vulnerable version.

**Preferred alongside CWE:** CWE-494 (Download of Code Without Integrity Check), CWE-1395

---

## A09:2021 — Security Logging and Monitoring Failures

**Use when findings relate to:**
- Missing audit logging for sensitive operations (authentication, privilege changes, data access)
- Audit log tampering risks (logs writable by the application)
- Sensitive data (credentials, PII, tokens) written to log output
- Log injection — user-controlled data written to logs without sanitisation
- Log aggregation changes that reduce security visibility
- Missing alerting or monitoring for security-relevant events

**Preferred alongside CWE:** CWE-532, CWE-200, CWE-117 (Improper Output Neutralisation for Logs)

---

## A10:2021 — Server-Side Request Forgery (SSRF)

**Use when findings relate to:**
- Server-side HTTP requests constructed from user-controlled URLs without validation
- Webhook or callback URL handling without allowlist validation
- Internal metadata service endpoints reachable via SSRF (e.g. AWS IMDS, cloud provider metadata)
- DNS rebinding risk in URL-fetching functionality
- SSRF via redirect following without destination validation

**Preferred alongside CWE:** CWE-918

---

## Choosing Between CWE and OWASP

| Use Case | Preferred Taxonomy |
|---|---|
| Code-level vulnerability classification for engineering teams | CWE |
| Executive or security programme reporting | OWASP Top 10 |
| Bug tracking and vulnerability databases | CWE |
| Compliance reporting aligned to OWASP standards | OWASP Top 10 |
| Internal control mapping | Both, plus internal control identifiers |

Both fields may be present in a finding when confidence is high for both mappings. If only one is confidently known, populate only that field.
