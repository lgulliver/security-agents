# CWE Mapping — Security Finding Taxonomy

This file provides high-confidence CWE mappings for common security finding patterns encountered during PR code review.

**Important constraints:**

- CWE mappings are **enrichment only**. Agents must identify a concrete vulnerability from PR evidence before applying a CWE label.
- Do not generate a finding because a CWE exists. Generate a finding because evidence in the diff supports it.
- If the appropriate CWE is uncertain, omit the `cwe` field rather than guessing.
- Do not raise or lower severity solely because a CWE mapping is present or absent.
- Prefer the most specific applicable CWE. Use parent CWEs only when no specific child applies.

See [mitre-usage-guidance.md](mitre-usage-guidance.md) for the full taxonomy usage policy.

---

## Authorization / Access Boundary

| Finding Pattern | CWE | Notes |
|---|---|---|
| Missing ownership check — object retrieved by ID without confirming the caller owns it | CWE-639 | Authorisation Bypass Through User-Controlled Key |
| Improper access control — function or endpoint with no access control check | CWE-284 | Improper Access Control |
| Privilege escalation — user-controlled input used to grant elevated role or permission | CWE-266 or CWE-269 | CWE-266: Incorrect Privilege Assignment; CWE-269: Improper Privilege Management. Use CWE-266 when a specific privilege is incorrectly assigned; use CWE-269 for general privilege lifecycle failures |
| Incorrect authorization — authorization check present but applied to wrong resource or condition | CWE-863 | Incorrect Authorisation |

---

## Secrets / Credentials

| Finding Pattern | CWE | Notes |
|---|---|---|
| Hardcoded credentials — password, key, or token literal in source | CWE-798 | Use of Hard-coded Credentials |
| Insufficiently protected credentials — credentials transmitted or stored without adequate protection | CWE-522 | Insufficiently Protected Credentials |
| Sensitive information in logs — credential or token value written to a log | CWE-532 | Insertion of Sensitive Information into Log File |

---

## Data Exposure

| Finding Pattern | CWE | Notes |
|---|---|---|
| Information exposure — sensitive data returned to a caller who should not receive it | CWE-200 | Exposure of Sensitive Information to an Unauthorised Actor |
| Exposure of sensitive information to an unauthorised actor — direct or indirect disclosure | CWE-200 | Same root CWE; use when exposure path is clearly unintended |
| Insertion of sensitive information into logs — PII or credentials written to log output | CWE-532 | Insertion of Sensitive Information into Log File |

---

## Injection / Input Handling

| Finding Pattern | CWE | Notes |
|---|---|---|
| SQL injection — user input unsafely concatenated into a SQL query | CWE-89 | Improper Neutralisation of Special Elements used in an SQL Command |
| OS command injection — user input passed to shell execution without sanitisation | CWE-78 | Improper Neutralisation of Special Elements used in an OS Command |
| Code injection — user input evaluated as code (eval, exec, etc.) | CWE-94 | Improper Control of Generation of Code |
| Path traversal — user-controlled path used to access files without canonicalisation | CWE-22 | Improper Limitation of a Pathname to a Restricted Directory |
| SSRF — user-controlled URL used in a server-side request without validation | CWE-918 | Server-Side Request Forgery |
| XSS — user input rendered into HTML or JavaScript without encoding | CWE-79 | Improper Neutralisation of Input During Web Page Generation |

---

## Cryptography

| Finding Pattern | CWE | Notes |
|---|---|---|
| Use of weak cryptography — deprecated or broken algorithm (MD5, SHA-1, DES, RC4) | CWE-327 | Use of a Broken or Risky Cryptographic Algorithm |
| Hardcoded cryptographic key — encryption or signing key embedded in source | CWE-321 | Use of Hard-coded Cryptographic Key |
| Insufficient entropy — random number generation inadequate for security purposes | CWE-331 | Insufficient Entropy |

---

## Deserialization

| Finding Pattern | CWE | Notes |
|---|---|---|
| Deserialization of untrusted data — unsafe deserialization of externally supplied data | CWE-502 | Deserialization of Untrusted Data |

---

## Configuration / Infrastructure

| Finding Pattern | CWE | Notes |
|---|---|---|
| Incorrect permission assignment — file, resource, or IAM permission set too broadly | CWE-732 | Incorrect Permission Assignment for Critical Resource |
| Exposure of resource to wrong sphere — resource accessible to a broader audience than intended | CWE-668 | Exposure of Resource to Wrong Sphere |
| Missing authentication for critical function — sensitive operation reachable without authentication | CWE-306 | Missing Authentication for Critical Function |
| Use of default credentials — default username/password not required to be changed | CWE-1392 | Use of Default Credentials |

---

## Dependency / Supply Chain

| Finding Pattern | CWE | Notes |
|---|---|---|
| Use of vulnerable component — dependency with a known security advisory | CWE-1395 | Dependency on Vulnerable Third-Party Component |
| Improper control of generation of code — build or install script generating or executing unverified code | CWE-94 | Apply only when the diff shows code-generation execution, not merely dependency pinning issues |
| Untrusted search path or package source risk — registry, path, or package source not verified | Map only when evidence is strong | Apply CWE-427 (Uncontrolled Search Path Element) only when the diff clearly shows a vulnerable path-resolution mechanism |

---

## Mapping Confidence Guidance

When populating `taxonomy_confidence` in a finding:

| Value | Meaning |
|---|---|
| `high` | The finding pattern directly and unambiguously matches the CWE definition, and the evidence from the diff is clear |
| `medium` | The finding pattern broadly aligns with the CWE but there is some ambiguity about which CWE variant applies, or the diff evidence requires inference |
| `low` | The CWE is a plausible fit but the mapping is uncertain; strongly prefer omitting the field at this level |
| `omitted` | No confident CWE mapping was possible; the `cwe` field should be absent from the finding |

**When in doubt, omit.** An absent CWE field is always preferable to an incorrect one.
