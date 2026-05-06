# Finding Schema

All security findings produced by agents in this repository **must** conform to the schema below.
Agents must not emit a finding unless they can populate every required field with direct evidence from the PR diff.

---

## JSON Schema

```json
{
  "agent": "authz-reviewer",
  "severity": "critical|high|medium|low|info",
  "confidence": "high|medium|low",
  "blocking": true,
  "file": "path/to/file",
  "line": 123,
  "finding": "Short finding title",
  "evidence": "Specific evidence from the diff",
  "risk": "Why this matters",
  "exploit_scenario": "How this could be abused",
  "recommendation": "Concrete fix",
  "cwe": "CWE-639",
  "owasp": "A01:2021-Broken Access Control",
  "mitre_attack": null,
  "taxonomy_confidence": "high|medium|low|omitted",
  "false_positive_notes": "What would make this not an issue"
}
```

> **Notes:**
> - `line` is optional. Set it to `null` (or omit it) when the exact line number cannot be determined from the diff.
> - `cwe`, `owasp`, `mitre_attack`, and `taxonomy_confidence` are optional enrichment fields. Omit them when the mapping is uncertain rather than guessing. See [../taxonomies/mitre-usage-guidance.md](../taxonomies/mitre-usage-guidance.md).
> - The legacy `category` field is superseded by the `cwe` and `owasp` fields. Existing findings using `category` remain valid; new findings should use the structured taxonomy fields.

---

## Field Definitions

| Field | Required | Description |
|---|---|---|
| `agent` | ✅ | Identifier of the agent that produced the finding (e.g. `authz-reviewer`). |
| `severity` | ✅ | `critical`, `high`, `medium`, `low`, or `info`. See [severity-rubric.md](severity-rubric.md). |
| `confidence` | ✅ | `high`, `medium`, or `low`. Reflects the agent's certainty that this is a real issue. |
| `blocking` | ✅ | `true` if the finding should block merge. See [blocking-policy.md](blocking-policy.md). |
| `file` | ✅ | Repo-relative path of the affected file. |
| `line` | ⚠️ | Line number if determinable from the diff. Omit (or use `null`) if not available. |
| `finding` | ✅ | One-line summary suitable for a PR comment header. |
| `evidence` | ✅ | Direct quote or paraphrase of the diff change that is the basis of the finding. Must not be generic. |
| `risk` | ✅ | Concrete description of the security impact. |
| `exploit_scenario` | ✅ | Realistic abuse scenario. Must not be speculative without basis in the diff. |
| `recommendation` | ✅ | Specific, actionable guidance. Prefer code-level advice where possible. |
| `false_positive_notes` | ✅ | What context (compensating controls, test scope, etc.) would make this a non-finding. |
| `cwe` | ⚠️ | CWE identifier (e.g. `"CWE-639"`). Optional enrichment. Omit when uncertain. See [../taxonomies/cwe-mapping.md](../taxonomies/cwe-mapping.md). |
| `owasp` | ⚠️ | OWASP Top 10 (2021) category (e.g. `"A01:2021-Broken Access Control"`). Optional enrichment. Omit when uncertain. See [../taxonomies/owasp-mapping.md](../taxonomies/owasp-mapping.md). |
| `mitre_attack` | ⚠️ | MITRE ATT&CK technique ID (e.g. `"T1552.005"`). Set to `null` for most findings. Apply only when a specific attacker technique is clearly evidenced. See [../taxonomies/mitre-usage-guidance.md](../taxonomies/mitre-usage-guidance.md). |
| `taxonomy_confidence` | ⚠️ | `high`, `medium`, `low`, or `omitted`. Reflects confidence in the CWE/OWASP mapping, independent of finding confidence. Omit the field (or set to `omitted`) when no taxonomy mapping is applied. |

---

## Severity Levels

| Level | Meaning |
|---|---|
| `critical` | Immediate exploitation likely; direct data loss, authentication bypass, or RCE. |
| `high` | Significant risk requiring prompt remediation. |
| `medium` | Exploitable under certain conditions; should be addressed. |
| `low` | Minor risk or defense-in-depth improvement. |
| `info` | Informational observation; no direct exploitability. |

---

## Confidence Levels

| Level | Meaning |
|---|---|
| `high` | Clear evidence in diff; no compensating controls visible; high certainty of real issue. |
| `medium` | Likely issue but dependent on context not visible in diff. |
| `low` | Possible issue; requires further investigation by a human reviewer. |

---

## Blocking Rules

See [blocking-policy.md](blocking-policy.md) for the full policy.

**Default:** `blocking: true` only when `severity` is `critical` or `high` **and** `confidence` is `high`.

All other findings default to `blocking: false` and are advisory.

<!-- CUSTOMISATION POINT: Organisations may tighten or relax blocking thresholds in their local policy overlay. -->

---

## Output Format for PR Comments

When surfacing findings in a pull request comment, agents must use the following structure:

```
## Security Review — <Agent Name>

### 🔴 BLOCKING Findings

#### [CRITICAL | HIGH] <finding title>
- **File:** `path/to/file.ext` (line N)
- **Evidence:** <exact evidence from diff>
- **Risk:** <risk description>
- **Exploit Scenario:** <scenario>
- **Recommendation:** <recommendation>
- **CWE:** CWE-XXX *(omit if uncertain)*
- **OWASP:** A0X:2021-Category *(omit if uncertain)*
- **False Positive Notes:** <notes>

---

### 🟡 Advisory Findings

...same structure...

---

### ✅ No Findings

<Agent> found no security issues in the reviewed files.
```

---

## Rules for Agents

1. **Evidence is mandatory.** Do not raise a finding without a direct reference to something in the diff.
2. **Prefer no finding over speculative findings.** If confidence would be `low` and severity `medium` or below, omit the finding.
3. **Do not duplicate.** If the same issue is already raised by another agent, omit or note it as a cross-reference.
4. **Do not surface style, formatting, or general refactoring issues.** Security scope only.
5. **Do not reveal secrets.** If a secret is found, describe its type and location but do not reproduce its value.
6. **Taxonomy is enrichment, not detection.** Apply CWE/OWASP only after a finding is established from diff evidence. Never generate a finding because a CWE or OWASP category exists.
7. **Omit taxonomy fields when uncertain.** An absent `cwe` or `owasp` field is always preferable to a wrong one. See [../taxonomies/mitre-usage-guidance.md](../taxonomies/mitre-usage-guidance.md).
8. **Severity is evidence-based.** Do not raise or lower severity based on the presence or absence of a taxonomy mapping.
9. **MITRE ATT&CK is optional and rare.** Set `mitre_attack: null` for most findings. Apply only when a specific attacker technique is clearly evidenced in the diff.
