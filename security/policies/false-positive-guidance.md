# False Positive Guidance

This document helps consuming organisations distinguish genuine security findings from false positives, and provides guidance on how to suppress false positives in a traceable, auditable way.

---

## Why False Positives Occur

Security review agents work from static analysis of a PR diff. They cannot:
- Execute the code.
- Inspect runtime state.
- Access the full codebase context outside the diff.
- Know about compensating controls in adjacent systems.
- Understand all organisation-specific conventions.

As a result, findings may occasionally be raised for code that is, in context, safe. This is expected. The goal is not zero false positives, but a high enough signal-to-noise ratio that engineers trust the findings.

---

## Evaluating a Finding

Before suppressing a finding, ask:

1. **Is the evidence accurate?** Does the agent correctly describe what the diff changes?
2. **Is the risk real?** Could an attacker realistically exploit this in your environment?
3. **Are there compensating controls?** Is this mitigated elsewhere (framework, middleware, platform)?
4. **Is this test-only?** Is the flagged code only reachable in test or local-dev contexts?
5. **Is the finding based on a pattern rather than a specific vulnerability?** Some patterns (e.g. `eval()`) are flagged as risky even when used safely.

If the answer to questions 2–5 suggests a false positive, document the reasoning before suppressing.

---

## Common False Positive Patterns

### Pattern: Test Fixtures and Mock Data

**Situation:** A test file contains a hardcoded credential or PII-like value that is synthetic mock data.

**Evaluation:** Confirm the value is not a real credential and is only used in tests. Check that the file cannot be loaded in production.

**Suppression:** Add an inline comment referencing a suppression ID. Ensure CI prevents test secrets from reaching production.

---

### Pattern: Framework-Managed Authorization

**Situation:** An authorization check appears missing in application code, but is enforced by the framework's middleware or decorator.

**Evaluation:** Verify the middleware is applied to the route in question. Confirm the framework's enforcement is documented and tested.

**Suppression:** Document the compensating control in the `.security-ignore` entry.

---

### Pattern: Internal-Only Services

**Situation:** A finding flags missing auth on an endpoint that is only accessible within a private network segment.

**Evaluation:** Confirm network-level controls are enforced (security groups, service mesh policy, etc.). Note that network controls alone are not sufficient if the endpoint handles sensitive operations.

**Suppression:** Document the network boundary assumption. Flag for re-review if the service boundary changes.

---

### Pattern: Intentional Privileged Configuration

**Situation:** An IaC or Kubernetes config grants broad permissions that are intentional for a specific workload (e.g. a CI runner, a backup agent).

**Evaluation:** Confirm the workload genuinely requires these permissions. Confirm the role is scoped to the correct service account.

**Suppression:** Document the justification. Add a review trigger if the role or its bindings change.

---

### Pattern: Generated or Vendored Code

**Situation:** A finding is raised in auto-generated or vendored code that the team does not directly maintain.

**Evaluation:** Confirm the code is truly generated/vendored and not hand-edited. Assess whether the vulnerability affects the consuming application.

**Suppression:** Exclude generated/vendored paths using the `.security-ignore` file. Ensure the code generation process is itself reviewed.

<!-- CUSTOMISATION POINT: Add organisation-specific false positive patterns for your technology stack. -->

---

## Suppression Mechanisms

### Option 1: `.security-ignore` File

Create a `.security-ignore` file in the repository root or in `.github/`:

```yaml
# .security-ignore
suppressions:
  - id: "SUPP-001"
    agent: "secrets-config-reviewer"
    file: "tests/fixtures/mock_credentials.json"
    reason: "Synthetic mock data. Not a real credential. Verified against production vault."
    approved_by: "security-team"
    expires: "2026-12-31"
    issue: "https://github.com/org/repo/issues/42"
```

<!-- CUSTOMISATION POINT: Define who in your organisation is authorised to approve suppressions. -->

### Option 2: Inline Code Comment

For a specific line in the code:

```python
api_key = "test_key_123"  # security-ignore: SUPP-002 - synthetic test key, not a real credential (Issue #42)
```

### Option 3: Class-Level Policy Suppression

For a recurring pattern that is consistently a false positive in your codebase, document it in a local policy overlay file:

```markdown
<!-- org-security-overrides.md -->
## Suppressed Finding Classes

### secrets-config-reviewer: Test Fixture Credentials
All files matching `tests/fixtures/**` are excluded from credential scanning.
Rationale: All test fixtures are reviewed during PR merge by the security team.
```

---

## Suppression Governance

Organisations should enforce:
- **Approval requirement:** Suppressions require sign-off from a designated security reviewer.
- **Expiry dates:** Suppressions should be time-bounded and reviewed periodically.
- **Traceability:** Every suppression must link to an issue or decision record.
- **Audit log:** Changes to `.security-ignore` should trigger a security team notification.

<!-- CUSTOMISATION POINT: Define your suppression approval workflow here. -->

---

## Escalating Uncertain Findings

If a finding cannot be definitively classified as real or a false positive, escalate to a human security reviewer rather than suppressing it. Use the label:

```
Status: Needs human review — context insufficient to determine if finding is valid.
```

Do not merge a PR with a blocking finding that cannot be resolved or responsibly suppressed.
