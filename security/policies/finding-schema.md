# Finding Schema

All security findings produced by agents in this repository **must** conform to the schema below.
Agents must not emit a finding unless they can populate every required field with direct evidence from the PR diff.

---

## JSON Schema

```json
{
  "agent": "<agent-id>",
  "severity": "critical | high | medium | low | info",
  "confidence": "high | medium | low",
  "blocking": true | false,
  "file": "path/to/file.ext",
  "line": 123,
  "category": "<CWE-ID | OWASP-category | internal-control-id>",
  "finding": "Short, descriptive finding title",
  "evidence": "Exact excerpt or description of the specific code/config change in the diff that triggered this finding",
  "risk": "Why this matters — concrete security impact",
  "exploit_scenario": "Step-by-step description of how an attacker could abuse this",
  "recommendation": "Concrete, actionable fix the author can apply",
  "false_positive_notes": "Conditions that would make this finding invalid (e.g. compensating controls, test-only context)"
}
```

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
| `category` | ✅ | CWE ID, OWASP Top 10 category, or an internal control label. Use the most specific applicable identifier. |
| `finding` | ✅ | One-line summary suitable for a PR comment header. |
| `evidence` | ✅ | Direct quote or paraphrase of the diff change that is the basis of the finding. Must not be generic. |
| `risk` | ✅ | Concrete description of the security impact. |
| `exploit_scenario` | ✅ | Realistic abuse scenario. Must not be speculative without basis in the diff. |
| `recommendation` | ✅ | Specific, actionable guidance. Prefer code-level advice where possible. |
| `false_positive_notes` | ✅ | What context (compensating controls, test scope, etc.) would make this a non-finding. |

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
- **Category:** CWE-XXX / OWASP ASVS X.X
- **Evidence:** <exact evidence from diff>
- **Risk:** <risk description>
- **Exploit Scenario:** <scenario>
- **Recommendation:** <recommendation>
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
