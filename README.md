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
  taxonomies/
    cwe-mapping.md                     # CWE mappings for common finding patterns
    owasp-mapping.md                   # OWASP Top 10 alignment guide
    mitre-usage-guidance.md            # Policy for CWE/OWASP/MITRE ATT&CK usage

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

## MITRE / CWE / OWASP Taxonomy Support

This repository supports CWE and OWASP Top 10 mappings as an **enrichment layer** for security findings. These taxonomies are for classification and reporting — they are not the basis for generating findings.

### Design Principles

- **Detection is evidence-first.** Agents reason from concrete PR diff evidence. A finding exists because the diff contains problematic code, not because a CWE or OWASP category exists.
- **Taxonomy is optional enrichment.** The `cwe`, `owasp`, `mitre_attack`, and `taxonomy_confidence` fields are populated only when the mapping is high-confidence.
- **Omit rather than guess.** If the correct CWE or OWASP category is uncertain, agents leave the field absent. An absent field is always better than a wrong one.
- **CWE for engineering.** Use CWE for precise, code-level vulnerability classification and in bug tracking.
- **OWASP for reporting.** Use OWASP Top 10 for executive and security-programme reporting.
- **MITRE ATT&CK sparingly.** Apply only when the PR clearly introduces a specific attacker technique or detection-relevant behaviour. Most findings set `mitre_attack: null`.
- **Severity is evidence-based.** Severity reflects exploitability, impact, exposure, and confidence — not the presence or absence of a taxonomy label.

### Taxonomy Files

| File | Description |
|---|---|
| [`security/taxonomies/cwe-mapping.md`](security/taxonomies/cwe-mapping.md) | High-confidence CWE mappings for common PR finding patterns |
| [`security/taxonomies/owasp-mapping.md`](security/taxonomies/owasp-mapping.md) | OWASP Top 10 (2021) alignment guide |
| [`security/taxonomies/mitre-usage-guidance.md`](security/taxonomies/mitre-usage-guidance.md) | Policy for when and how to apply each taxonomy |

### Example: Correctly Mapped Finding

The finding is established from evidence in the diff. Taxonomy is applied as enrichment only after the finding is confirmed.

```json
{
  "agent": "authz-reviewer",
  "severity": "high",
  "confidence": "high",
  "blocking": true,
  "file": "src/api/documents.js",
  "line": 47,
  "finding": "Missing ownership check on document retrieval",
  "evidence": "Document is fetched by `req.params.id` with no check that `document.owner_id === req.user.id`",
  "risk": "Any authenticated user can read any other user's documents by guessing or enumerating document IDs",
  "exploit_scenario": "Attacker authenticates, then iterates document IDs in the URL to access documents belonging to other users",
  "recommendation": "Add an ownership check: after fetching the document, verify `document.owner_id === req.user.id` and return 403 if the check fails",
  "cwe": "CWE-639",
  "owasp": "A01:2021-Broken Access Control",
  "mitre_attack": null,
  "taxonomy_confidence": "high",
  "false_positive_notes": "Would not be an issue if documents are intentionally public or if authorization is enforced at the database query level via row-level security"
}
```

### Example: Taxonomy Correctly Omitted

When the finding does not confidently map to a CWE, taxonomy fields are omitted. The finding is still valid and the severity is unaffected.

```json
{
  "agent": "threat-model-reviewer",
  "severity": "medium",
  "confidence": "medium",
  "blocking": false,
  "file": "src/webhooks/handler.js",
  "line": null,
  "finding": "New webhook receiver processes external data without documented trust boundary",
  "evidence": "PR adds a new `/webhooks/inbound` route that parses and stores payloads from an external partner without signature validation",
  "risk": "Untrusted external data enters the system without verification; if the partner is compromised, malicious data could be injected",
  "exploit_scenario": "An attacker who controls or spoofs the partner's webhook endpoint sends a crafted payload that exploits downstream processing logic",
  "recommendation": "Add HMAC signature validation for incoming webhook payloads using a shared secret stored in the secrets manager",
  "false_positive_notes": "Not an issue if the partner's webhook source IPs are strictly allowlisted at the network layer and the payloads are fully sanitised before processing"
}
```

### Extending Mappings with Internal Controls

Organisations can extend findings with internal control identifiers by adding them alongside CWE/OWASP in their local overlay or suppression configurations:

```json
{
  "cwe": "CWE-798",
  "owasp": "A02:2021-Cryptographic Failures",
  "internal_control": "SEC-CRED-003"
}
```

Add your organisation's control catalogue mappings in your consuming repository's overlay file using the `<!-- CUSTOMISATION POINT -->` markers as a guide.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

---

## License

[MIT License](LICENSE)
