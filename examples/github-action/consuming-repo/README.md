# Example: Consuming Repository

This directory contains a reference example showing how an organisation imports and customises the PR security review workflows from `lgulliver/agents` into their own repository.

---

## What This Example Shows

| File | Purpose |
|---|---|
| [`pr-security-review.md`](./pr-security-review.md) | Local workflow overlay: imports the central workflow, sets mode, adds org context |

---

## Quick Start

### Step 1: Copy the Workflow File

Copy [`pr-security-review.md`](./pr-security-review.md) to your repository:

```
your-repo/
  .github/
    agentic-workflows/
      pr-security-review.md    ← copy this file here
```

### Step 2: Update the Import Reference

In your copied `pr-security-review.md`, update the version tag to the latest release:

```
lgulliver/agents/agents/security/pr-security-review.md@v1.0.0
```

Check the [releases page](https://github.com/lgulliver/agents/releases) for the latest tag.

### Step 3: Fill in Organisation Context

Complete the `<!-- CUSTOMISATION POINT -->` sections with your organisation's:
- Mode (`advisory` for initial rollout, `blocking` when ready).
- Technology stack and frameworks.
- Approved external integrations.
- Approved package registries.
- Architecture and trust zone description.

### Step 4: Add a GitHub Actions Workflow

Create `.github/workflows/pr-security-review.yml` using the example in [`pr-security-review.md`](./pr-security-review.md).

### Step 5: Run in Advisory Mode

Start in `mode: advisory`. All findings will be posted as comments but will not block merges. Use this period to:
- Calibrate false positives for your codebase.
- Document suppressions in `.security-ignore`.
- Build team familiarity with the findings format.

Recommended advisory period: at least 4 weeks. See the [blocking policy](https://github.com/lgulliver/agents/blob/main/agents/security/policies/blocking-policy.md) for rollout phases.

### Step 6: Enable Blocking Mode

After the advisory period, change `mode: advisory` to `mode: blocking` in your workflow configuration.

By default, blocking applies to `critical` and `high` severity findings with `high` confidence only.

---

## Customisation Options

### Adjust Blocking Thresholds

```yaml
# Block on high severity and above, high confidence only (default)
blocking_severity_threshold: high
blocking_confidence_threshold: high

# More aggressive: block on medium severity with high confidence
blocking_severity_threshold: medium
blocking_confidence_threshold: high
```

### Add Organisation-Specific Context

Add a context block in your local workflow overlay to improve threat model accuracy:

```markdown
### Organisation Context
- Service: Multi-tenant B2B API
- Data classification: GDPR-applicable PII
- Trust zones: Public → API Gateway → Microservices → Postgres + Redis
- Approved third parties: Stripe, Twilio, Datadog
```

### Suppress False Positives

Create a `.security-ignore` file in your repository root:

```yaml
suppressions:
  - id: "SUPP-001"
    agent: "secrets-config-reviewer"
    file: "tests/fixtures/mock_credentials.json"
    reason: "Synthetic test data, not real credentials"
    approved_by: "security-team"
    expires: "2026-12-31"
    issue: "https://github.com/your-org/your-repo/issues/42"
```

See [false-positive-guidance.md](https://github.com/lgulliver/agents/blob/main/agents/security/policies/false-positive-guidance.md) for full suppression guidance.

---

## Keeping Up to Date

This repository follows [semantic versioning](https://semver.org/):

- **Patch releases** (`v1.0.x`): bug fixes and minor improvements to prompts.
- **Minor releases** (`v1.x.0`): new agent capabilities, non-breaking changes.
- **Major releases** (`vX.0.0`): breaking changes to the finding schema or agent IDs.

Subscribe to releases on the [security-agents repository](https://github.com/lgulliver/agents) to be notified of updates.

Review the [CHANGELOG](https://github.com/lgulliver/agents/blob/main/CHANGELOG.md) before upgrading across major versions.
