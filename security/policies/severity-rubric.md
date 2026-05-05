# Severity Rubric

This rubric defines how agents must assign `severity` to security findings. Agents must use this rubric consistently to ensure findings are actionable and comparable across reviews.

---

## Severity Levels

### 🔴 Critical

**Definition:** Direct, high-likelihood exploitation that can result in significant and immediate harm.

**Characteristics:**
- Exploitable without authentication or with easily obtainable credentials.
- Results in: remote code execution, authentication bypass, full data exfiltration, account takeover, or privilege escalation to admin/root.
- No additional preconditions required beyond the vulnerability itself.

**Examples:**
- Hardcoded admin credentials committed to source.
- SQL injection with no parameterisation in a user-facing endpoint.
- Missing authorization check on a privileged action (e.g. delete-all-data endpoint accessible to any authenticated user).
- Kubernetes Pod with `privileged: true` and `hostPID: true`.

---

### 🟠 High

**Definition:** Significant risk with a plausible exploitation path. Requires prompt remediation.

**Characteristics:**
- Exploitable with low effort or common tooling.
- Results in: data exposure, partial privilege escalation, tenant data leakage, or critical service disruption.
- May require an attacker to be authenticated, but exploitation path is clear.

**Examples:**
- Insecure direct object reference (IDOR) allowing access to another user's records.
- AWS IAM policy with `*` actions on production resources.
- Secret or token exposed in environment variable without a secrets manager.
- Dependency with a published CVE at CVSS ≥ 7.0.

---

### 🟡 Medium

**Definition:** Exploitable under certain conditions. Should be addressed in a timely manner.

**Characteristics:**
- Requires additional preconditions (e.g. specific user role, network position, or chained vulnerability).
- Results in: partial data exposure, degraded security posture, or potential escalation if combined with other issues.

**Examples:**
- Verbose error messages leaking stack traces to end users.
- Overly permissive CORS policy.
- Dependency with CVSS 4.0–6.9.
- Missing `httpOnly` / `Secure` flags on non-sensitive cookies.
- Log entries containing PII without a documented retention policy.

---

### 🔵 Low

**Definition:** Minor risk or defense-in-depth improvement. No immediate exploitation path.

**Characteristics:**
- Low exploitability on its own.
- Represents a missed security control that improves posture if remediated.

**Examples:**
- Missing security headers (e.g. `X-Content-Type-Options`).
- Overly verbose logging in non-production code paths.
- Outdated but unexploited dependency.
- Debug flag that is conditional on an environment variable.

---

### ℹ️ Info

**Definition:** Informational observation. No direct exploitability identified.

**Characteristics:**
- Not a vulnerability in isolation.
- May indicate technical debt, a changed trust boundary, or a pattern worth tracking.
- Useful context for human reviewers.

**Examples:**
- New external integration added (threat model context).
- Increased blast radius of a component.
- Commented-out security check (may have been intentional).

---

## Confidence and Severity Interaction

Confidence must be considered alongside severity when determining actionability:

| Severity | High Confidence | Medium Confidence | Low Confidence |
|---|---|---|---|
| Critical | 🔴 Blocking | 🟡 Advisory | ⬜ Omit or note |
| High | 🔴 Blocking | 🟡 Advisory | ⬜ Omit or note |
| Medium | 🟡 Advisory | 🟡 Advisory | ⬜ Omit or note |
| Low | 🔵 Advisory | ⬜ Omit or note | ⬜ Omit |
| Info | ℹ️ Advisory | ⬜ Omit or note | ⬜ Omit |

**Agents must omit findings where confidence is `low` and severity is `medium` or below.**

<!-- CUSTOMISATION POINT: Organisations may add domain-specific severity examples relevant to their technology stack. -->

---

## Notes for Agents

- Assign severity based on the **worst-case realistic impact** given the diff context.
- Do not inflate severity to draw attention to a finding.
- Do not deflate severity to avoid blocking a PR.
- If the diff lacks sufficient context to assess severity accurately, assign `confidence: low` and elevate to a human reviewer via the `info` or `low` tier.
