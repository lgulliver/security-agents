"""MCP server exposing lgulliver/agents as prompts and resources.

Works with Claude Desktop, VS Code (via MCP settings), Cursor, and any
other MCP-compatible host.

Prompts: ready-to-use invocations of each security review agent.
Resources: raw agent definition files and policy documents.
"""

from __future__ import annotations

from pathlib import Path

import mcp.types as types
from mcp.server.fastmcp import FastMCP

# ─── Path resolution ──────────────────────────────────────────────────────────
# File is at: distributions/mcp-server/src/agents_mcp/server.py
# Repo root is 4 levels up.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_AGENTS_DIR = _REPO_ROOT / "agents"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _read_agent(relative_path: str) -> str:
    """Read a markdown agent file and return its content."""
    full_path = _AGENTS_DIR / relative_path
    if not full_path.exists():
        raise FileNotFoundError(f"Agent file not found: {full_path}")
    return full_path.read_text(encoding="utf-8")


def _make_review_messages(
    agent_relative_path: str,
    pr_diff: str,
) -> list[types.PromptMessage]:
    """Return prompt messages combining the agent system prompt with the PR diff."""
    system_prompt = _read_agent(agent_relative_path)
    return [
        types.PromptMessage(
            role="user",
            content=types.TextContent(
                type="text",
                text=(
                    f"{system_prompt}\n\n"
                    "---\n\n"
                    "## PR Diff to Review\n\n"
                    f"```diff\n{pr_diff}\n```"
                ),
            ),
        )
    ]


# ─── MCP server ───────────────────────────────────────────────────────────────

mcp = FastMCP(
    "lgulliver-agents",
    instructions=(
        "A collection of AI review agents for pull requests and cloud estate "
        "governance. Use the available prompts to run an agent against your "
        "content, or browse the resources to read the agent definitions and "
        "policy documents directly."
    ),
)


# ─── Resources ────────────────────────────────────────────────────────────────


@mcp.resource("agents://security/{agent_name}")
def get_security_agent(agent_name: str) -> str:
    """Read a security agent definition by name (e.g. pr-security-review)."""
    return _read_agent(f"security/{agent_name}.md")


@mcp.resource("agents://security/policies/{policy_name}")
def get_security_policy(policy_name: str) -> str:
    """Read a security policy document by name (e.g. finding-schema)."""
    return _read_agent(f"security/policies/{policy_name}.md")


@mcp.resource("agents://security/taxonomies/{taxonomy_name}")
def get_security_taxonomy(taxonomy_name: str) -> str:
    """Read a security taxonomy document by name (e.g. cwe-mapping)."""
    return _read_agent(f"security/taxonomies/{taxonomy_name}.md")


# ─── Prompts ──────────────────────────────────────────────────────────────────


@mcp.prompt()
def pr_security_review(pr_diff: str) -> list[types.PromptMessage]:
    """Orchestrating PR security review agent.

    Classifies the PR diff, invokes the relevant specialist review agents,
    consolidates findings, deduplicates, and produces a single actionable
    summary. Always use this prompt as your entry point for security reviews.
    """
    return _make_review_messages("security/pr-security-review.md", pr_diff)


@mcp.prompt()
def authz_review(pr_diff: str) -> list[types.PromptMessage]:
    """Authorization and tenant isolation specialist review.

    Reviews the PR diff for missing auth checks, IDOR vulnerabilities, tenant
    isolation failures, and privilege escalation.
    """
    return _make_review_messages("security/authz-review.md", pr_diff)


@mcp.prompt()
def secrets_config_review(pr_diff: str) -> list[types.PromptMessage]:
    """Secrets and configuration specialist review.

    Reviews the PR diff for hardcoded secrets, unsafe defaults, debug flags,
    and sensitive data in logs.
    """
    return _make_review_messages("security/secrets-config-review.md", pr_diff)


@mcp.prompt()
def iac_kubernetes_review(pr_diff: str) -> list[types.PromptMessage]:
    """IaC and Kubernetes specialist review.

    Reviews the PR diff for privileged containers, broad RBAC, insecure IAM
    policies, and unsafe Terraform patterns.
    """
    return _make_review_messages("security/iac-kubernetes-review.md", pr_diff)


@mcp.prompt()
def dependency_supply_chain_review(pr_diff: str) -> list[types.PromptMessage]:
    """Dependency and supply chain specialist review.

    Reviews the PR diff for risky dependencies, unpinned versions, and
    unsafe build steps.
    """
    return _make_review_messages(
        "security/dependency-supply-chain-review.md", pr_diff
    )


@mcp.prompt()
def data_exposure_review(pr_diff: str) -> list[types.PromptMessage]:
    """Data exposure and privacy specialist review.

    Reviews the PR diff for PII leakage, excessive API responses, and
    unsafe serialisation patterns.
    """
    return _make_review_messages("security/data-exposure-review.md", pr_diff)


@mcp.prompt()
def threat_model_review(pr_diff: str) -> list[types.PromptMessage]:
    """Threat model holistic review.

    Reviews the PR diff for new attack paths, trust boundary changes, and
    blast radius. Always run alongside the other specialist agents.
    """
    return _make_review_messages("security/threat-model-review.md", pr_diff)


# ─── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    """Entry point for the MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
