# Changelog

All notable changes to this repository are documented in this file.

This project adheres to [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added
- Initial repository structure and all core agent and policy files.
- `.github/agentic-workflows/pr-security-review.md` — orchestrating agent.
- `.github/agentic-workflows/authz-review.md` — AuthZ and tenant isolation reviewer.
- `.github/agentic-workflows/secrets-config-review.md` — Secrets and configuration reviewer.
- `.github/agentic-workflows/iac-kubernetes-review.md` — IaC and Kubernetes reviewer.
- `.github/agentic-workflows/dependency-supply-chain-review.md` — Dependency and supply chain reviewer.
- `.github/agentic-workflows/data-exposure-review.md` — Data exposure and privacy reviewer.
- `.github/agentic-workflows/threat-model-review.md` — Threat model reviewer.
- `security/policies/finding-schema.md` — Canonical finding schema and output format.
- `security/policies/severity-rubric.md` — Severity level definitions.
- `security/policies/blocking-policy.md` — Blocking thresholds and rollout phases.
- `security/policies/secure-review-principles.md` — Core agent behaviour principles.
- `security/policies/prompt-injection-hardening.md` — Prompt injection threat model and defences.
- `security/policies/false-positive-guidance.md` — False positive evaluation and suppression.
- `examples/consuming-repo/pr-security-review.md` — Example local workflow overlay.
- `examples/consuming-repo/README.md` — Step-by-step consuming repository guide.
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

[Unreleased]: https://github.com/lgulliver/security-agents/compare/HEAD...HEAD
