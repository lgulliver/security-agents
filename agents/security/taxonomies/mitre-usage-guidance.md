# MITRE / CWE / OWASP Usage Guidance

This file defines the policy for how agents in this repository use MITRE ATT&CK, CWE, and OWASP Top 10 as taxonomy enrichment. These are classification tools, not detection tools.

---

## Core Principle: Evidence First, Taxonomy Second

**MITRE/CWE/OWASP mappings must never replace evidence-based review.**

The correct sequence is always:

1. **Identify** a concrete vulnerability pattern from the PR diff.
2. **Establish** the finding with evidence, risk, and exploit scenario.
3. **Then** — and only then — add CWE/OWASP enrichment if the mapping is high-confidence.

Do not work backwards from a taxonomy category to generate a finding. A finding exists because the diff contains problematic code. The taxonomy label describes what was found; it does not justify the finding's existence.

---

## CWE — Use for Engineering Taxonomy

**When to use CWE:**
- After a concrete finding has been established with evidence from the diff.
- When the vulnerability pattern clearly and unambiguously matches a specific CWE.
- For code-level findings where a precise CWE adds classification value.

**When not to use CWE:**
- Do not apply a CWE because the code category (e.g. "this is an auth function") superficially resembles a CWE domain.
- Do not apply a CWE when the finding is speculative or confidence is low.
- Do not apply a parent/generic CWE when a more specific child CWE is applicable.

**Guidance:**
- Prefer the most specific applicable CWE (e.g. prefer CWE-89 over CWE-74 for SQL injection).
- Use CWE for engineering teams, bug tracking, and vulnerability databases.
- When the correct CWE is uncertain between two candidates, note both with a `medium` taxonomy_confidence, or omit entirely.

**Effect on severity and confidence:**
- **Do not lower confidence because a CWE mapping is absent.** A finding's confidence reflects the quality of evidence in the diff.
- **Do not raise severity merely because a finding maps to a CWE.** Severity is determined by exploitability, impact, exposure, and confidence — not by taxonomy.

See [cwe-mapping.md](cwe-mapping.md) for the reference CWE mapping table.

---

## OWASP Top 10 — Use for Reporting Alignment

**When to use OWASP:**
- After a concrete finding has been established with evidence from the diff.
- When the finding clearly falls within an OWASP Top 10 category.
- For executive or security programme reporting where OWASP alignment is required.

**When not to use OWASP:**
- Do not apply an OWASP category when the finding is speculative.
- Do not apply an OWASP category merely because the finding is in a broad domain that the category covers. Confirm the finding first.
- OWASP categories are broad. A vague association is not sufficient — there must be a clear, confirmed finding to classify.

**Guidance:**
- Use OWASP Top 10 (2021) categories. Do not use older OWASP Top 10 editions.
- Both CWE and OWASP may be populated simultaneously when both mappings are high-confidence.
- Prefer CWE for precise engineering taxonomy; use OWASP for compliance and reporting alignment.

See [owasp-mapping.md](owasp-mapping.md) for the reference OWASP mapping table.

---

## MITRE ATT&CK — Use Sparingly

**When to use MITRE ATT&CK:**
MITRE ATT&CK describes attacker tactics and techniques at an operational level. It is not primarily a code vulnerability taxonomy. Use ATT&CK mappings only in the narrow set of circumstances below.

Apply a MITRE ATT&CK mapping (`mitre_attack` field) only when:
- The PR introduces a code pattern that **clearly and directly** enables a known attacker technique (e.g. introducing a backdoor, a credential exfiltration path, or a persistence mechanism that maps to a specific ATT&CK technique ID).
- The finding relates to detection engineering — the change removes, weakens, or circumvents security monitoring in a way that maps to a Defence Evasion technique.
- The finding relates to an obvious abuse path with a direct, documented attacker technique mapping (e.g. SSRF enabling metadata service access maps to T1552.005).

**When not to use MITRE ATT&CK:**
- Do not apply ATT&CK mappings for normal code vulnerabilities that do not directly correspond to an attacker operational technique.
- Do not apply ATT&CK to general weaknesses (e.g. missing input validation does not have a meaningful ATT&CK mapping unless the specific exploit technique is evident).
- Do not invent ATT&CK mappings. If you cannot identify a specific technique ID with high confidence, set `mitre_attack: null`.
- Do not use ATT&CK to inflate the perceived severity of a finding.

**Default for most findings:** `"mitre_attack": null`

---

## The `taxonomy_confidence` Field

The `taxonomy_confidence` field reflects confidence in the **taxonomy mapping**, not in the finding itself. These are independent assessments.

| Value | Meaning |
|---|---|
| `high` | The CWE/OWASP mapping directly and unambiguously matches the finding pattern and the diff evidence |
| `medium` | The mapping broadly aligns but there is some ambiguity (e.g. two plausible CWEs, or the OWASP category is broad) |
| `low` | The mapping is plausible but uncertain; strongly prefer omitting taxonomy fields at this level |
| `omitted` | No taxonomy mapping was applied; `cwe` and `owasp` fields are absent from the finding |

**Taxonomy confidence is independent of finding confidence.** A high-confidence finding may have `omitted` taxonomy confidence if the correct CWE is genuinely ambiguous. This is correct and acceptable behaviour.

---

## Summary Rules for Agents

1. **Evidence first.** Identify the finding from the diff before considering taxonomy.
2. **Omit rather than guess.** An absent taxonomy field is always better than a wrong one.
3. **CWE for engineering.** Use CWE for precise, code-level classification.
4. **OWASP for reporting.** Use OWASP for executive and compliance-facing outputs.
5. **ATT&CK sparingly.** Only when a specific, well-evidenced attacker technique mapping is clear.
6. **Severity is evidence-based.** Derived from exploitability, impact, exposure, and finding confidence — never from taxonomy alone.
7. **Confidence is evidence-based.** Reflects certainty that the issue is real — not whether a CWE label is available.
8. **Do not invent mappings.** If uncertain, set fields to `null` or omit them.
