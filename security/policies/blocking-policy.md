# Blocking Policy

This policy defines when a security finding must block a pull request from merging and when it is advisory only.

---

## Default Blocking Threshold

A finding is **blocking** (`"blocking": true`) when **all** of the following conditions are met:

| Condition | Requirement |
|---|---|
| Severity | `critical` or `high` |
| Confidence | `high` |

All other findings default to **advisory** (`"blocking": false`).

This is intentionally conservative. Blocking is a high-stakes action that can delay legitimate work. The default policy prioritises high-signal, high-severity findings to avoid alert fatigue.

<!-- CUSTOMISATION POINT: Organisations may tighten blocking thresholds (e.g. block on medium+high confidence) or relax them (e.g. advisory-only mode during initial rollout). See the Rollout section below. -->

---

## Blocking Conditions Summary

| Severity | Confidence: High | Confidence: Medium | Confidence: Low |
|---|---|---|---|
| Critical | 🔴 **Blocking** | 🟡 Advisory | ⬜ Advisory (or omit) |
| High | 🔴 **Blocking** | 🟡 Advisory | ⬜ Advisory (or omit) |
| Medium | 🟡 Advisory | 🟡 Advisory | ⬜ Advisory (or omit) |
| Low | 🟡 Advisory | ⬜ Advisory | ⬜ Omit |
| Info | ℹ️ Advisory | ⬜ Advisory | ⬜ Omit |

---

## Recommended Rollout Phases

Organisations importing these workflows should follow a phased rollout to build trust in the agents before enabling hard blocking.

### Phase 1 — Advisory Only (weeks 1–4)

- All findings are advisory regardless of severity or confidence.
- Engineers and security teams calibrate findings against real PRs.
- Identify false positive patterns and document them in [false-positive-guidance.md](false-positive-guidance.md).
- No PRs are blocked.

**Configuration:** Set `mode: advisory` in your consuming workflow or disable the blocking enforcement step.

### Phase 2 — Blocking Critical/High (High Confidence Only)

- Enable blocking for `critical`/`high` severity with `high` confidence.
- This matches the default policy described above.
- Continue gathering feedback on advisory findings.

**Configuration:** Use the default blocking policy (no override needed).

### Phase 3 — Tighten as Appropriate

- Optionally lower the blocking threshold to include `medium`+`high confidence` findings.
- Optionally introduce organisation-specific controls (e.g. block on any new dependency without internal approval).

<!-- CUSTOMISATION POINT: Define your own phase 3 thresholds based on your organisation's risk appetite. -->

---

## Override Mechanism

Organisations may override the blocking behaviour in their consuming workflow configuration:

```yaml
# Example: advisory-only mode (no blocking)
with:
  mode: advisory

# Example: block on medium severity with high confidence
with:
  blocking_severity_threshold: "medium"
  blocking_confidence_threshold: "high"
```

<!-- CUSTOMISATION POINT: Implement these parameters in your consuming workflow wrapper. -->

---

## Suppressing Individual Findings

If a blocking finding is a confirmed false positive, it must be suppressed using a documented mechanism rather than by overriding the policy wholesale.

Acceptable suppression mechanisms:
1. Add the finding to a `.security-ignore` file with a justification comment.
2. Add an inline code comment referencing the suppression with a tracking issue number.
3. Document in [false-positive-guidance.md](false-positive-guidance.md) as a class-level suppression.

**Agents must not suppress findings silently.** All suppressions must be traceable.

---

## What Blocking Means

When a finding is `"blocking": true`, the consuming workflow should:
1. Post the finding as a PR review comment requesting changes.
2. Exit with a non-zero status code (or equivalent failure signal).
3. Prevent auto-merge from proceeding.

The finding does **not** prevent the PR author from overriding with a manual approval from a security team member, if your organisation's branch protection rules permit it.

<!-- CUSTOMISATION POINT: Configure required reviewers and override paths in your branch protection rules. -->

---

## What Blocking Does Not Mean

- Blocking does not mean the code is certainly vulnerable.
- Blocking does not replace human security review.
- Blocking does not guarantee that non-blocked PRs are safe.

These agents are one layer of a defence-in-depth strategy.
