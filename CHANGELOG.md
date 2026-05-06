# Changelog

All notable changes to this repository are documented in this file.

This project adheres to [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added
- Monorepo restructure: merged `security-agents` and `finops-agents` into a single `agents` repository.
- `agents/finops/` — Azure FinOps multi-agent suite (PR review and weekly estate analysis).
- `.github/workflows/pr-finops-review.yml` — reusable GitHub Actions workflow for FinOps PR review.
- `.github/workflows/weekly-estate-analysis.yml` — reusable GitHub Actions workflow for weekly estate analysis.
- `presets/startup.yml`, `presets/platform-team.yml`, `presets/enterprise.yml`, `presets/kubernetes.yml` — opinionated configuration presets.
- `packages/` — placeholder structure for planned shared packages (core, github, policy-engine, comment-renderer).
- Stub agent directories for planned domains: `agents/reliability/`, `agents/observability/`, `agents/k8s/`, `agents/architecture/`, `agents/change-risk/`.
- `examples/github-app/` and `examples/self-hosted/` stub directories.

### Changed
- Security agent workflows moved from `.github/agentic-workflows/` to `agents/security/`.
- Security policies moved from `security/policies/` to `agents/security/policies/`.
- Security taxonomies moved from `security/taxonomies/` to `agents/security/taxonomies/`.
- `examples/consuming-repo/` moved to `examples/github-action/consuming-repo/`.
- All internal relative links in agent and policy files updated to reflect new paths.
- Repository renamed from `security-agents` to `agents`.

---

## [v1.0.0] — Initial security-agents release

### Added
- `agents/security/pr-security-review.md` — orchestrating agent.
- `agents/security/authz-review.md` — AuthZ and tenant isolation reviewer.
- `agents/security/secrets-config-review.md` — Secrets and configuration reviewer.
- `agents/security/iac-kubernetes-review.md` — IaC and Kubernetes reviewer.
- `agents/security/dependency-supply-chain-review.md` — Dependency and supply chain reviewer.
- `agents/security/data-exposure-review.md` — Data exposure and privacy reviewer.
- `agents/security/threat-model-review.md` — Threat model reviewer.
- `agents/security/policies/finding-schema.md` — Canonical finding schema and output format.
- `agents/security/policies/severity-rubric.md` — Severity level definitions.
- `agents/security/policies/blocking-policy.md` — Blocking thresholds and rollout phases.
- `agents/security/policies/secure-review-principles.md` — Core agent behaviour principles.
- `agents/security/policies/prompt-injection-hardening.md` — Prompt injection threat model and defences.
- `agents/security/policies/false-positive-guidance.md` — False positive evaluation and suppression.
- `examples/github-action/consuming-repo/pr-security-review.md` — Example local workflow overlay.
- `examples/github-action/consuming-repo/README.md` — Step-by-step consuming repository guide.
- `README.md` — Repository overview, usage, and security model.
- `CONTRIBUTING.md` — Contribution guidelines.
- `LICENSE` — MIT License.

---

## Format

Each release entry uses the following sections as applicable:

- **Added** — New agents, features, or policy documents.
- **Changed** — Changes to existing agents or policies (breaking changes noted).
- **Deprecated** — Features or agents that will be removed in a future release.
- **Removed** — Features or agents removed in this release.
- **Fixed** — Bug fixes to agent prompts or policy documents.
- **Security** — Changes that address security issues in the repository itself.

[Unreleased]: https://github.com/lgulliver/agents/compare/HEAD...HEAD
[v1.0.0]: https://github.com/lgulliver/agents/releases/tag/v1.0.0
