# Contributing to security-agents

Thank you for your interest in contributing. This repository provides generic, organisation-agnostic security review agents. Contributions must meet a high quality bar to ensure the agents remain trustworthy, accurate, and useful for all consuming organisations.

---

## Principles for Contributors

1. **Security scope only.** Agent prompts must not include instructions to review style, performance, naming, or refactoring.
2. **Generic and portable.** Do not introduce company-specific assumptions, vendor-specific APIs, or internal tool names.
3. **Evidence-based.** Any new review focus area must require direct evidence from the diff before a finding is raised.
4. **Prefer no finding over speculative findings.** New focus areas should have a clear, demonstrable signal.
5. **Prompt injection hardened.** Any new agent must include the standard behavioural constraints from the existing agents.

---

## Types of Contributions

### ✅ Welcome

- New or improved review focus areas within an existing agent's scope.
- New specialist agents for security domains not yet covered.
- Improvements to the finding schema, severity rubric, or blocking policy.
- New policy documents (e.g. guidance for specific regulatory frameworks).
- Improvements to the example consuming repository.
- Bug fixes where an agent's instructions produce incorrect behaviour.
- Documentation improvements.

### ❌ Not Accepted

- Organisation-specific agents or prompts.
- Vendor-specific integrations (unless documented as a generic placeholder).
- Changes that weaken the prompt injection hardening.
- Changes that lower the evidence requirement for findings.
- Style, formatting, or performance review instructions added to security agents.

---

## Contribution Process

### 1. Open an Issue First

For significant changes (new agents, schema changes, policy changes), open an issue to discuss the proposal before submitting a pull request. This avoids wasted effort if the direction doesn't align with the repository's goals.

For small improvements (typos, clarifications, minor prompt improvements), a PR without a prior issue is fine.

### 2. Fork and Branch

Fork the repository and create a feature branch:

```bash
git checkout -b feature/your-feature-name
```

### 3. Make Your Changes

Follow the structure and conventions in the existing files:
- Use the `<!-- CUSTOMISATION POINT -->` marker where organisations should customise.
- Use the standard output template format in agent files.
- Reference the policy files using relative links.
- Keep agents concise — longer is not better if it reduces clarity.

### 4. Self-Review Checklist

Before submitting, verify:

- [ ] No company-specific assumptions introduced.
- [ ] All new review focus areas require direct evidence from the diff.
- [ ] Standard behavioural constraints are present in any new agent.
- [ ] Finding output format matches the schema in `finding-schema.md`.
- [ ] Severity assignments match the `severity-rubric.md`.
- [ ] Blocking rules match the `blocking-policy.md`.
- [ ] `<!-- CUSTOMISATION POINT -->` markers are present where applicable.
- [ ] Policy file cross-references use relative links.
- [ ] CHANGELOG.md updated with a summary of the change.

### 5. Submit a Pull Request

Open a pull request against the `main` branch. Include:
- A clear description of what the change does and why.
- A reference to any related issue.
- Confirmation that the self-review checklist has been completed.

---

## Versioning

This repository follows [semantic versioning](https://semver.org/):

- **Patch** (`v1.0.x`): Non-breaking changes — prompt improvements, documentation fixes, clarifications.
- **Minor** (`v1.x.0`): New agents or new focus areas within existing agents. Non-breaking for consuming repos.
- **Major** (`vX.0.0`): Breaking changes — schema changes, agent ID changes, removal of agents.

When contributing, note in your PR which version bump your change requires.

---

## Code of Conduct

This project follows the [GitHub Community Code of Conduct](https://docs.github.com/en/site-policy/github-terms/github-community-code-of-conduct). Be respectful, constructive, and collaborative.

---

## Questions

Open an issue with the `question` label if you're unsure about something before contributing.
