# Example: FinOps GitHub Actions Integration

This directory shows how to call the reusable FinOps workflows from `lgulliver/agents` in your own repository.

Two reusable workflows are available:

| Workflow | File | Trigger |
|---|---|---|
| PR Review | `.github/workflows/pr-finops-review.yml` | Pull requests with Terraform changes |
| Weekly Estate Analysis | `.github/workflows/weekly-estate-analysis.yml` | Scheduled (Monday 06:00 UTC) or manual |

---

## Prerequisites

### Azure Service Principal

The weekly estate analysis (and optionally PR review cost estimates) requires an Azure service principal with the following roles, assigned at Management Group or Subscription scope:

| Role | Scope | Purpose |
|---|---|---|
| `Reader` | Management Group / Subscription | Estate inventory and resource discovery |
| `Cost Management Reader` | Management Group / Subscription | Cost data and anomaly detection |
| `Monitoring Reader` | Subscription | VM and resource metrics for rightsizing |

```bash
# Create service principal
az ad sp create-for-rbac --name "finops-agents" --role Reader \
  --scopes /providers/Microsoft.Management/managementGroups/<mg-id> \
  --sdk-auth
```

### GitHub Secrets

Add the following secrets to your repository (`Settings → Secrets and variables → Actions`):

| Secret | Description |
|---|---|
| `AZURE_CLIENT_ID` | Service principal application (client) ID |
| `AZURE_CLIENT_SECRET` | Service principal client secret |
| `AZURE_TENANT_ID` | Azure tenant ID |
| `COST_EXPORT_STORAGE_ACCOUNT` | Storage account name for Cost Management exports (optional) |
| `INFRACOST_API_KEY` | Infracost API key for richer cost estimates (optional) |

`GITHUB_TOKEN` is provided automatically by GitHub Actions — no setup required.

---

## PR Review Setup

### Step 1: Generate a Terraform plan JSON in your CI

Before calling the FinOps review, your workflow must produce a `tfplan.json`:

```yaml
- name: Terraform Init
  run: terraform init

- name: Terraform Plan
  run: |
    terraform plan -out=tfplan
    terraform show -json tfplan > tfplan.json
```

### Step 2: Call the reusable workflow

Copy [`pr-review.yml`](./pr-review.yml) to your repository at `.github/workflows/finops-pr-review.yml` and adjust the inputs.

```yaml
# .github/workflows/finops-pr-review.yml
jobs:
  finops:
    uses: lgulliver/agents/.github/workflows/pr-finops-review.yml@v1.0.0
    with:
      plan_json_path: tfplan.json
      mode: advisory              # Start in advisory; switch to blocking when calibrated
      blocking_on_tagging: false  # Set true to fail PRs with missing required tags
    secrets: inherit
```

**Always pin to a version tag.** Do not reference `@main` or `@latest` in production.

### PR Review Agents

The workflow runs four agents against the Terraform plan JSON:

| Agent | What It Checks |
|---|---|
| `PRCostDiffAgent` | Estimates monthly cost delta using Azure Retail Prices API |
| `PRSKUSanityAgent` | Flags oversized VMs, premium disks, AKS over-provisioning in non-prod |
| `PRTaggingAgent` | Checks required tags (`owner`, `service`, `environment`, `cost_center`, etc.) |
| `PRLifecycleWasteAgent` | Detects missing shutdown schedules, orphaned resources, excessive retention |

### Blocking vs Advisory Mode

| Mode | Behaviour |
|---|---|
| `advisory` | Findings posted as PR comments; PR is not blocked. Recommended for first 4 weeks. |
| `blocking` | PR check fails when findings exceed configured thresholds. |

To block on tagging issues, set `blocking_on_tagging: true` in addition to `mode: blocking`.

---

## Weekly Estate Analysis Setup

### Step 1: Copy the workflow file

Copy [`weekly-analysis.yml`](./weekly-analysis.yml) to your repository at `.github/workflows/finops-weekly-analysis.yml` and fill in your management group or subscription IDs.

### Step 2: What the workflow does

Each Monday at 06:00 UTC (or on manual trigger), the workflow:

1. Discovers subscriptions across your Management Groups.
2. Collects full estate inventory via Azure Resource Graph.
3. Pulls cost data from Cost Management (last 30 days by default).
4. Collects Azure Advisor recommendations.
5. Gathers VM, database, and AKS metrics from Azure Monitor.
6. Runs the full analysis suite (rightsizing, reservations, waste, anomalies).
7. Scores and prioritises all recommendations.
8. Generates a comprehensive markdown report.
9. Posts a summary comment to the triggering issue or PR (if applicable).
10. Creates GitHub issues for high-priority recommendations (when `create_issues: true`).
11. Commits the full report to a `reports` branch.

### Step 3: Trigger manually first

Run the workflow manually from `Actions → FinOps Weekly Estate Analysis → Run workflow` before relying on the schedule. This lets you verify credentials and adjust scope before Monday's run.

```yaml
# In your workflow — adjust management_groups or subscription_ids as needed
on:
  workflow_dispatch:
    inputs:
      management_groups:
        description: "Space-separated Management Group IDs"
        default: "mg-prod"
```

### Recommendation Actions

The analysis produces recommendations with an `action.category` that determines what happens next:

| Category | Criteria | Result |
|---|---|---|
| `finance_approval_required` | Saving ≥ £2,000/month | Issue created, flagged for finance review |
| `auto_fix_candidate` | ≥ £500/mo + low risk + low effort | PR created if `create_remediation_prs: true` |
| `create_pr` | ≥ £100/mo + low/medium risk | PR or issue created |
| `needs_owner_review` | Low confidence or high risk | Issue created, assigned to resource owner |
| `create_issue` | Everything else | Issue created |

---

## Configuration

For self-hosted or advanced setups, copy [`agents/finops/config/config.yaml.example`](../../../agents/finops/config/config.yaml.example) to `config/config.yaml` in your checkout and adjust:

```yaml
finops:
  currency: GBP                    # Cost currency
  cost_lookback_days: 30           # How far back to pull cost data
  tagging:
    mode: advisory                 # advisory | blocking
    required_tags:                 # Tags that must be present on all resources
      - owner
      - service
      - environment
      - cost_center
  rightsizing:
    cpu_avg_threshold: 10.0        # Flag VMs averaging below 10% CPU
    cpu_p95_threshold: 40.0        # Flag VMs with p95 below 40% CPU
  anomaly:
    wow_spike_threshold: 0.20      # Flag week-over-week cost increases above 20%
```

---

## Rollout Recommendation

| Phase | When | Configuration |
|---|---|---|
| 1 — Baseline | Week 1 | Run weekly analysis with `create_issues: false`. Review the report manually. |
| 2 — Issues | Week 2–4 | Enable `create_issues: true`. Triage the backlog with your team. |
| 3 — PR review advisory | Week 3+ | Add PR review workflow in `mode: advisory`. Calibrate tagging false positives. |
| 4 — PR review blocking | Week 6+ | Switch to `mode: blocking` once tagging and SKU signals are well-calibrated. |
| 5 — Remediation PRs | Optional | Enable `create_remediation_prs: true` for fully automated low-risk fixes. |

---

## Keeping Up to Date

This repository follows [semantic versioning](https://semver.org/):

- **Patch releases** (`v1.0.x`): bug fixes and analysis improvements.
- **Minor releases** (`v1.x.0`): new agents or analysis capabilities, non-breaking.
- **Major releases** (`vX.0.0`): breaking changes to the recommendation schema or workflow inputs.

Subscribe to releases on the [agents repository](https://github.com/lgulliver/agents) and review the [CHANGELOG](../../../CHANGELOG.md) before upgrading across major versions.
