# agents

A monorepo of reusable, organisation-agnostic AI review agents for pull requests and cloud estate governance. Agents cover security, FinOps, and more — all designed to be imported into any repository via version-pinned references.

---

## What Is This?

This repository provides a growing suite of **agentic review workflows** that any organisation can use. Each agent focuses on a specific review domain — reviewing PR diffs for risks, enforcing cloud cost governance, or analysing your infrastructure estate.

Key properties:
- **Reusable:** Import into any repository via a version-pinned reference.
- **Generic:** No company-specific assumptions. Customise via local overlays.
- **Evidence-based:** Every finding requires direct evidence from the PR diff or cloud data.
- **Prompt-injection hardened:** Security agents treat repository content as untrusted data.

---

## Repository Structure

```
agents/
  security/                            # Security review agents (GitHub Agentic Workflows)
    pr-security-review.md              # Orchestrating agent — start here
    authz-review.md                    # Authorization and tenant isolation
    secrets-config-review.md           # Secrets and configuration
    iac-kubernetes-review.md           # IaC and Kubernetes
    dependency-supply-chain-review.md  # Dependencies and supply chain
    data-exposure-review.md            # Data exposure and privacy
    threat-model-review.md             # Threat model review
    policies/
      finding-schema.md                # Finding data structure and rules
      severity-rubric.md               # How severity is assigned
      blocking-policy.md               # When findings block merge
      secure-review-principles.md      # Core agent behaviour principles
      prompt-injection-hardening.md    # Prompt injection threat model and defences
      false-positive-guidance.md       # How to handle and suppress false positives
    taxonomies/
      cwe-mapping.md                   # CWE mappings for common finding patterns
      owasp-mapping.md                 # OWASP Top 10 alignment guide
      mitre-usage-guidance.md          # Policy for CWE/OWASP/MITRE ATT&CK usage
  finops/                              # Azure FinOps agents (Python)
    pr/                                # PR-time Terraform plan review agents
    weekly/                            # Weekly estate analysis agents
    entrypoints/                       # CLI entrypoints
    models/                            # Shared recommendation model
    config/                            # Configuration example
    tests/                             # Test suite
  reliability/                         # Coming soon
  observability/                       # Coming soon
  k8s/                                 # Coming soon
  architecture/                        # Coming soon
  change-risk/                         # Coming soon

packages/
  core/                                # Shared primitives (planned)
  github/                              # GitHub integration utilities (planned)
  policy-engine/                       # Policy evaluation runtime (planned)
  comment-renderer/                    # Finding/recommendation renderer (planned)

presets/
  startup.yml                          # Advisory-only, lightweight
  platform-team.yml                    # Balanced blocking for platform/SRE teams
  enterprise.yml                       # Full suite, all agents enabled
  kubernetes.yml                       # Focused on Kubernetes workloads

examples/
  github-action/
    consuming-repo/                    # Example overlay for security review
  github-app/                          # Coming soon
  self-hosted/                         # Coming soon
```

---

## Available Agents

### Security (`agents/security/`)

Built for [GitHub Agentic Workflows (gh-aw)](https://docs.github.com/en/copilot/using-github-copilot/using-github-copilot-in-your-ide/github-copilot-agentic-workflows).

| Agent | File | Focus |
|---|---|---|
| PR Security Review (orchestrator) | `pr-security-review.md` | Classifies diff, invokes specialists, consolidates findings |
| AuthZ / Tenant Isolation | `authz-review.md` | Missing auth checks, IDOR, tenant isolation, privilege escalation |
| Secrets and Config | `secrets-config-review.md` | Hardcoded secrets, unsafe defaults, debug flags, sensitive logging |
| IaC / Kubernetes | `iac-kubernetes-review.md` | Privileged containers, broad RBAC, IAM, insecure Terraform |
| Dependency / Supply Chain | `dependency-supply-chain-review.md` | Risky dependencies, unpinned versions, unsafe build steps |
| Data Exposure | `data-exposure-review.md` | PII leakage, excessive API responses, unsafe serialisation |
| Threat Model | `threat-model-review.md` | New attack paths, trust boundary changes, blast radius |

### FinOps (`agents/finops/`)

Python-based Azure cost governance agents. See [`agents/finops/README.md`](agents/finops/README.md) for full documentation.

| Agent | Type | Focus |
|---|---|---|
| `PRCostDiffAgent` | PR review | Estimates monthly cost delta from Terraform plan |
| `PRSKUSanityAgent` | PR review | Flags oversized VMs, premium disks, AKS over-provisioning |
| `PRTaggingAgent` | PR review | Enforces required Azure tag compliance |
| `PRLifecycleWasteAgent` | PR review | Detects missing shutdown schedules, orphaned resources |
| `RightsizingAgent` | Weekly | Identifies over-provisioned VMs, databases, App Service Plans |
| `ReservationAgent` | Weekly | Recommends Reserved Instances and Savings Plans |
| `WasteOrphanAgent` | Weekly | Finds unattached disks, idle load balancers, old snapshots |
| `AnomalyTrendAgent` | Weekly | Detects WoW cost spikes, new services, budget burn rate |

---

## Presets

Presets are opinionated YAML configurations for common team profiles. Use them as a starting point for your consuming workflow.

| Preset | Description |
|---|---|
| [`startup.yml`](presets/startup.yml) | Advisory-only across all agents. Safe for teams in Phase 1 rollout. |
| [`platform-team.yml`](presets/platform-team.yml) | Blocking on high severity. Weekly estate analysis enabled. |
| [`enterprise.yml`](presets/enterprise.yml) | Full suite. All agents enabled, blocking on high+ with medium confidence. |
| [`kubernetes.yml`](presets/kubernetes.yml) | IaC/Kubernetes security focus with AKS FinOps cost governance. |

---

## How to Import Security Workflows

### Using gh-aw

Reference the workflow by its path in this repository, pinned to a release tag:

```bash
gh aw run lgulliver/agents/agents/security/pr-security-review.md@v1.0.0 \
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
          workflow: lgulliver/agents/agents/security/pr-security-review.md@v1.0.0
          pr: ${{ github.event.pull_request.number }}
          mode: advisory   # Start in advisory mode; switch to 'blocking' after Phase 1
```

**Always pin to a version tag.** Do not reference `@main` or `@latest` in production.

---

## How to Run FinOps Agents

See [`agents/finops/README.md`](agents/finops/README.md) for full setup, configuration, and usage.

### PR Review (Reusable GitHub Actions Workflow)

```yaml
jobs:
  finops:
    uses: lgulliver/agents/.github/workflows/pr-finops-review.yml@v1.0.0
    with:
      plan_json_path: tfplan.json
      mode: advisory
      blocking_on_tagging: false
    secrets: inherit
```

### Weekly Estate Analysis

```yaml
jobs:
  finops-weekly:
    uses: lgulliver/agents/.github/workflows/weekly-estate-analysis.yml@v1.0.0
    with:
      management_groups: "mg-prod mg-nonprod"
      create_issues: true
    secrets: inherit
```

---

## Recommended Rollout (Security)

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

Optionally lower the blocking threshold based on your organisation's risk appetite. See [`agents/security/policies/blocking-policy.md`](agents/security/policies/blocking-policy.md) for the full policy.

---

## How to Customise Security Agents

### Approach: Local Overlay Files

**Do not modify the generic agents in this repository** for organisation-specific customisation. Instead, create a local overlay in your consuming repository's `.github/agentic-workflows/pr-security-review.md`.

The overlay can:
- Set the mode (`advisory` / `blocking`).
- Provide organisation context (tech stack, trust zones, approved integrations).
- Reference your internal suppression file.
- Add organisation-specific review instructions as an addendum.

See [`examples/github-action/consuming-repo/pr-security-review.md`](examples/github-action/consuming-repo/pr-security-review.md) for a complete example.

### Adjusting Severity and Blocking Thresholds

```yaml
# In your consuming workflow
blocking_severity_threshold: high      # default: high (blocks critical + high)
blocking_confidence_threshold: high    # default: high
```

---

## Security Finding Schema

All security findings follow a consistent schema:

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

See [`agents/security/policies/finding-schema.md`](agents/security/policies/finding-schema.md) for the full schema definition.

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

### Prompt Injection

Repository content — source code, comments, fixtures, markdown — may contain adversarial instructions designed to manipulate the agent's output. These agents apply prompt injection hardening as described in [`agents/security/policies/prompt-injection-hardening.md`](agents/security/policies/prompt-injection-hardening.md).

---

## Security Policies

| Policy | Description |
|---|---|
| [`finding-schema.md`](agents/security/policies/finding-schema.md) | Finding data structure, field definitions, and output format |
| [`severity-rubric.md`](agents/security/policies/severity-rubric.md) | How severity levels are defined and assigned |
| [`blocking-policy.md`](agents/security/policies/blocking-policy.md) | When findings block merge; recommended rollout phases |
| [`secure-review-principles.md`](agents/security/policies/secure-review-principles.md) | Core agent behaviour and scope principles |
| [`prompt-injection-hardening.md`](agents/security/policies/prompt-injection-hardening.md) | Prompt injection threat model and defences |
| [`false-positive-guidance.md`](agents/security/policies/false-positive-guidance.md) | How to evaluate and suppress false positives |

---

## MITRE / CWE / OWASP Taxonomy Support

Security findings support CWE and OWASP Top 10 mappings as an **enrichment layer**. These taxonomies are for classification and reporting — they are not the basis for generating findings.

| File | Description |
|---|---|
| [`agents/security/taxonomies/cwe-mapping.md`](agents/security/taxonomies/cwe-mapping.md) | High-confidence CWE mappings for common PR finding patterns |
| [`agents/security/taxonomies/owasp-mapping.md`](agents/security/taxonomies/owasp-mapping.md) | OWASP Top 10 (2021) alignment guide |
| [`agents/security/taxonomies/mitre-usage-guidance.md`](agents/security/taxonomies/mitre-usage-guidance.md) | Policy for when and how to apply each taxonomy |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

---

## License

[MIT License](LICENSE)
