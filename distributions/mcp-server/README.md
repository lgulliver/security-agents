# MCP Server — `distributions/mcp-server`

Exposes all agents from `lgulliver/agents` as **MCP prompts** and **resources** for use in any MCP-compatible host: Claude Desktop, VS Code (with MCP support), Cursor, Continue, and others.

---

## What This Provides

### Prompts

Ready-to-use agent invocations. Each prompt accepts the PR diff as input and returns the agent's system prompt combined with your content.

| Prompt | Agent | Description |
|---|---|---|
| `pr_security_review` | `pr-security-review` | Orchestrating review — classifies diff and consolidates all findings |
| `authz_review` | `authz-review` | Authorization, IDOR, tenant isolation |
| `secrets_config_review` | `secrets-config-review` | Hardcoded secrets, unsafe config |
| `iac_kubernetes_review` | `iac-kubernetes-review` | IaC, Kubernetes, Terraform |
| `dependency_supply_chain_review` | `dependency-supply-chain-review` | Dependencies, supply chain |
| `data_exposure_review` | `data-exposure-review` | PII leakage, unsafe serialisation |
| `threat_model_review` | `threat-model-review` | Threat model, attack surface changes |

### Resources

Browse and read agent definitions and policy documents directly.

| Resource URI | Description |
|---|---|
| `agents://security/{agent_name}` | Security agent markdown (e.g. `agents://security/pr-security-review`) |
| `agents://security/policies/{policy_name}` | Policy doc (e.g. `agents://security/policies/finding-schema`) |
| `agents://security/taxonomies/{taxonomy_name}` | Taxonomy doc (e.g. `agents://security/taxonomies/cwe-mapping`) |

---

## Installation

### 1. Clone or reference the repo

```bash
git clone https://github.com/lgulliver/agents.git
cd agents
```

### 2. Install the MCP server

```bash
pip install -e distributions/mcp-server
```

This installs the `agents-mcp` command globally in your active Python environment.

### 3. Verify the installation

```bash
agents-mcp --help
```

---

## Host Configuration

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "lgulliver-agents": {
      "command": "agents-mcp"
    }
  }
}
```

See [`examples/claude-desktop-config.json`](examples/claude-desktop-config.json) for the full template.

### VS Code

Add to your VS Code `settings.json` (requires an MCP-compatible extension such as the GitHub Copilot extension with MCP support or Continue):

```json
{
  "mcp": {
    "servers": {
      "lgulliver-agents": {
        "command": "agents-mcp"
      }
    }
  }
}
```

See [`examples/vscode-settings.json`](examples/vscode-settings.json) for the full template.

### Cursor

In Cursor → Settings → MCP Servers, add:

```json
{
  "lgulliver-agents": {
    "command": "agents-mcp"
  }
}
```

---

## Usage

### Running a PR security review

In Claude Desktop or any MCP-enabled chat interface:

1. Open the prompts panel.
2. Select `pr_security_review`.
3. Paste your PR diff as the `pr_diff` argument.
4. The agent will classify the diff, invoke specialist sub-agents, and return a consolidated review.

### Reading an agent definition

In your MCP host's resources browser, navigate to:

```
agents://security/pr-security-review
```

This returns the full agent system prompt markdown, useful for inspecting or customising agent behaviour.

---

## Development

```bash
# Install with dev dependencies
pip install -e "distributions/mcp-server[dev]"

# Run the server directly (stdio transport)
agents-mcp
```

The server uses stdio transport by default, which is the standard for MCP servers integrated with desktop clients.

---

## Pinning to a Release

When using in production, pin the MCP server to a specific release tag:

```bash
pip install "git+https://github.com/lgulliver/agents.git@v1.0.0#subdirectory=distributions/mcp-server"
```
