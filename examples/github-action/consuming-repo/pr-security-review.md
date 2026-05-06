# PR Security Review — Example Consuming Repository

This file shows how a consuming repository imports and customises the central PR security review workflow from `lgulliver/agents`.

---

<!-- CONSUMING REPO CUSTOMISATION START -->
<!-- Copy this file into your repository at .github/agentic-workflows/pr-security-review.md -->
<!-- Update the import reference to pin to the desired release tag. -->
<!-- CONSUMING REPO CUSTOMISATION END -->

## Import

This workflow imports the central orchestrating agent from `lgulliver/agents`.

**Local CLI invocation** (replace `<PR_NUMBER>` with the actual pull request number):

```bash
gh aw run lgulliver/agents/agents/security/pr-security-review.md@v1.0.0 \
  --with pr=<PR_NUMBER>
```

**GitHub Actions step** (the `${{ github.event.pull_request.number }}` expression is evaluated by the Actions runner):

```yaml
- name: Run Security Review Agent
  uses: github/agentic-workflows-action@v1   # Replace with actual gh-aw action
  with:
    workflow: lgulliver/agents/agents/security/pr-security-review.md@v1.0.0
    pr: ${{ github.event.pull_request.number }}
    mode: advisory
```

Pin to a specific version tag. Do not use `@main` or `@latest` in production.

---

## Local Customisation

The following customisations are applied on top of the central workflow for this organisation:

### Mode

<!-- CUSTOMISATION POINT: Set to 'advisory' during initial rollout, then 'blocking' when ready. -->

```yaml
mode: advisory   # Change to 'blocking' after Phase 1 rollout (see blocking-policy.md)
```

### Blocking Thresholds (when mode = blocking)

<!-- CUSTOMISATION POINT: Adjust to your organisation's risk appetite. -->

```yaml
blocking_severity_threshold: high      # Block on critical and high
blocking_confidence_threshold: high    # Only when confidence is high
```

### Organisation-Specific Context

<!-- CUSTOMISATION POINT: Provide your system architecture context to improve threat model accuracy. -->

The following context helps the `threat-model-reviewer` reason about trust boundaries in this system:

- **Service type:** [e.g. "Multi-tenant SaaS API"]
- **Primary data classification:** [e.g. "PII — GDPR applicable"]
- **Trust zones:** [e.g. "Public internet → API Gateway → Application services → Internal data stores"]
- **Approved external integrations:** [e.g. "Stripe (payments), SendGrid (email), Datadog (monitoring)"]

### Technology Stack

<!-- CUSTOMISATION POINT: List your primary languages and frameworks so agents can use correct patterns. -->

- **Languages:** [e.g. Go, TypeScript, Python]
- **Frameworks:** [e.g. Echo, Express, FastAPI]
- **Cloud provider:** [e.g. AWS, GCP, Azure]
- **Container orchestration:** [e.g. Kubernetes on EKS]
- **Secrets management:** [e.g. AWS Secrets Manager, HashiCorp Vault]

### Approved Dependency Registries

<!-- CUSTOMISATION POINT: List your approved package registries for dependency confusion detection. -->

- [e.g. `https://registry.npmjs.org`]
- [e.g. `https://pypi.org`]
- [e.g. `https://your-internal-registry.example.com`]

### Suppression Configuration

<!-- CUSTOMISATION POINT: Reference your organisation's .security-ignore file. -->

Suppressions are managed in [`.security-ignore`](./.security-ignore).

All suppressions require approval from the security team. See [false-positive-guidance.md](https://github.com/lgulliver/agents/blob/main/agents/security/policies/false-positive-guidance.md).

---

## Full Workflow Example (GitHub Actions)

```yaml
# .github/workflows/pr-security-review.yml
name: PR Security Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read          # Read-only: required to fetch PR diff
  pull-requests: write    # Required to post review comments

jobs:
  security-review:
    name: Agentic Security Review
    runs-on: ubuntu-latest
    steps:
      - name: Run Security Review Agent
        uses: github/agentic-workflows-action@v1   # Replace with actual gh-aw action
        with:
          workflow: lgulliver/agents/agents/security/pr-security-review.md@v1.0.0
          pr: ${{ github.event.pull_request.number }}
          # CUSTOMISATION POINT: Switch to 'blocking' after Phase 1 rollout
          mode: advisory
```

---

## Notes

- This example pins the workflow to `v1.0.0`. Update the tag when new versions are released.
- Review the [CHANGELOG](https://github.com/lgulliver/agents/blob/main/CHANGELOG.md) before upgrading.
- Local customisations in this file take precedence over the central workflow defaults.
- Do not edit the central workflow files in `lgulliver/agents` directly for organisation-specific needs. Add customisations here instead.
