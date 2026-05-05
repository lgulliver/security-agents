# security-agents

A central repository of reusable, organisation-agnostic security review agents and workflows for pull request review, built for [GitHub Agentic Workflows (gh-aw)](https://docs.github.com/en/copilot/using-github-copilot/using-github-copilot-in-your-ide/github-copilot-agentic-workflows).

---

## What Is This?

This repository provides a set of **security-focused agentic workflows** that any organisation can import into their own repositories. The agents review pull request diffs for security issues across a range of categories — authorization, secrets, infrastructure, supply chain, data exposure, and threat modelling.

Key properties:
- **Reusable:** Import into any repository via a version-pinned reference.
- **Generic:** No company-specific assumptions. Customise via local overlays.
- **Security-focused:** Agents review only security concerns — not style, performance, or refactoring.
- **Evidence-based:** Every finding requires direct evidence from the PR diff.
- **Prompt-injection hardened:** Agents treat repository content as untrusted data.

---

## Repository Structure

```
.github/
  agentic-workflows/
    pr-security-review.md              # Orchestrating agent — start here
    authz-review.md                    # Authorization and tenant isolation
    secrets-config-review.md           # Secrets and configuration
    iac-kubernetes-review.md           # IaC and Kubernetes
    dependency-supply-chain-review.md  # Dependencies and supply chain
    data-exposure-review.md            # Data exposure and privacy
    threat-model-review.md             # Threat model review

security/
  policies/
    finding-schema.md                  # Finding data structure and rules
    severity-rubric.md                 # How severity is assigned
    blocking-policy.md                 # When findings block merge
    secure-review-principles.md        # Core agent behaviour principles
    prompt-injection-hardening.md      # Prompt injection threat model and defences
    false-positive-guidance.md         # How to handle and suppress false positives

examples/
  consuming-repo/
    pr-security-review.md              # Example local workflow overlay
    README.md                          # Step-by-step consuming repo guide
```

---

## Available Agents

| Agent | File | Focus |
|---|---|---|
| PR Security Review (orchestrator) | `pr-security-review.md` | Classifies diff, invokes specialists, consolidates findings |
| AuthZ / Tenant Isolation | `authz-review.md` | Missing auth checks, IDOR, tenant isolation, privilege escalation |
| Secrets and Config | `secrets-config-review.md` | Hardcoded secrets, unsafe defaults, debug flags, sensitive logging |
| IaC / Kubernetes | `iac-kubernetes-review.md` | Privileged containers, broad RBAC, IAM, insecure Terraform |
| Dependency / Supply Chain | `dependency-supply-chain-review.md` | Risky dependencies, unpinned versions, unsafe build steps |
| Data Exposure | `data-exposure-review.md` | PII leakage, excessive API responses, unsafe serialisation |
| Threat Model | `threat-model-review.md` | New attack paths, trust boundary changes, blast radius |

---

## How to Import Workflows

### Using gh-aw

Reference the workflow by its path in this repository, pinned to a release tag:

```bash
gh aw run lgulliver/security-agents/.github/agentic-workflows/pr-security-review.md@v1.0.0 \
  --with pr=<PR_NUMBER>
```

### GitHub Actions Integration

```yaml
# .github/workflows/pr-security-review.yml
name: PR Security Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  security-review:
    name: Agentic Security Review
    runs-on: ubuntu-latest
    steps:
      - name: Run Security Review Agent
        uses: github/agentic-workflows-action@v1   # Replace with actual gh-aw action
        with:
          workflow: lgulliver/security-agents/.github/agentic-workflows/pr-security-review.md@v1.0.0
          pr: ${{ github.event.pull_request.number }}
          mode: advisory   # Start in advisory mode; switch to 'blocking' after Phase 1
```

**Always pin to a version tag.** Do not reference `@main` or `@latest` in production.

---

## Recommended Rollout

### Phase 1 — Advisory Only (weeks 1–4)

Set `mode: advisory`. All findings are posted as comments but do not block merges.

Use this period to:
- Calibrate false positives for your codebase.
- Document suppressions in `.security-ignore`.
- Build team familiarity with the finding format.

### Phase 2 — Blocking on Critical/High (High Confidence)

Enable `mode: blocking` with the default thresholds:
- Blocks only on `critical` or `high` severity with `high` confidence.
- All other findings remain advisory.

### Phase 3 — Tighten as Appropriate

Optionally lower the blocking threshold based on your organisation's risk appetite. See [`security/policies/blocking-policy.md`](security/policies/blocking-policy.md) for the full policy.

---

## How to Customise

### Approach: Local Overlay Files

**Do not modify the generic agents in this repository** for organisation-specific customisation. Instead, create a local overlay in your consuming repository's `.github/agentic-workflows/pr-security-review.md`.

The overlay can:
- Set the mode (`advisory` / `blocking`).
- Provide organisation context (tech stack, trust zones, approved integrations).
- Reference your internal suppression file.
- Add organisation-specific review instructions as an addendum.

See [`examples/consuming-repo/pr-security-review.md`](examples/consuming-repo/pr-security-review.md) for a complete example.

### Adding Organisation-Specific Standards

Add organisation context to your local overlay file using the `<!-- CUSTOMISATION POINT -->` markers as a guide. You can add:
- Approved technology list (frameworks, cloud providers, secrets managers).
- Internal control identifiers alongside CWE/OWASP references.
- Organisation-specific PII definitions or data classification.
- Internal architecture context for threat modelling.

### Adjusting Severity and Blocking Thresholds

```yaml
# In your consuming workflow
blocking_severity_threshold: high      # default: high (blocks critical + high)
blocking_confidence_threshold: high    # default: high
```

---

## Finding Schema

All findings follow a consistent schema:

```json
{
  "agent": "authz-reviewer",
  "severity": "critical|high|medium|low|info",
  "confidence": "high|medium|low",
  "blocking": true,
  "file": "path/to/file",
  "line": 123,
  "category": "CWE-XXX / OWASP ASVS X.X",
  "finding": "Short finding title",
  "evidence": "Specific evidence from the PR diff",
  "risk": "Why this matters",
  "exploit_scenario": "How this could be abused",
  "recommendation": "Concrete fix",
  "false_positive_notes": "What would make this not an issue"
}
```

See [`security/policies/finding-schema.md`](security/policies/finding-schema.md) for the full schema definition.

---

## Security Model and Limitations

### What These Agents Do

- Perform **static analysis of PR diffs** using an AI agent.
- Apply security expertise across a range of categories.
- Surface findings with structured evidence and recommendations.
- Block or flag PRs according to configured thresholds.

### What These Agents Do Not Do

- **Execute code.** Agents cannot run the code or tests.
- **Access runtime state.** Agents cannot observe production behaviour.
- **Guarantee safety.** A PR with no findings is not certified as secure.
- **Replace human review.** Agents are one layer of a defence-in-depth strategy.

### Agent Permissions

Agents operate with **read-only access** to the repository and PR diff by default. They do not:
- Write to the repository, branches, or settings.
- Access secrets beyond what the workflow requires to run.
- Make network calls to external systems (beyond the LLM provider configured by the platform).

### Prompt Injection

Repository content — source code, comments, fixtures, markdown — may contain adversarial instructions designed to manipulate the agent's output. These agents apply prompt injection hardening as described in [`security/policies/prompt-injection-hardening.md`](security/policies/prompt-injection-hardening.md).

**Note:** Prompt injection hardening is defence-in-depth, not a guarantee. Human review remains important, especially for high-risk PRs.

### Known Limitations

- **Context window:** Very large diffs may exceed the agent's context window, causing incomplete reviews. Split large PRs where possible.
- **Indirect vulnerabilities:** Agents review the diff in isolation and may miss vulnerabilities that only become apparent with full codebase context.
- **Generated and vendored code:** Agents may raise findings in generated or vendored code that the team does not directly maintain.
- **Novel patterns:** Agents may miss novel attack patterns not represented in their training or prompts.

---

## Policies

| Policy | Description |
|---|---|
| [`finding-schema.md`](security/policies/finding-schema.md) | Finding data structure, field definitions, and output format |
| [`severity-rubric.md`](security/policies/severity-rubric.md) | How severity levels are defined and assigned |
| [`blocking-policy.md`](security/policies/blocking-policy.md) | When findings block merge; recommended rollout phases |
| [`secure-review-principles.md`](security/policies/secure-review-principles.md) | Core agent behaviour and scope principles |
| [`prompt-injection-hardening.md`](security/policies/prompt-injection-hardening.md) | Prompt injection threat model and defences |
| [`false-positive-guidance.md`](security/policies/false-positive-guidance.md) | How to evaluate and suppress false positives |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

---

## License

[MIT License](LICENSE)
