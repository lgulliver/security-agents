# Copilot Extension — `distributions/copilot-extension`

A GitHub Copilot Extension that exposes `lgulliver/agents` as a **Copilot chat participant** (`@lgulliver-agents`). Users can invoke security review agents directly from GitHub Copilot chat in the browser, VS Code, and GitHub Mobile.

---

## How It Works

The extension is a lightweight Node.js/TypeScript server that:

1. Receives a Copilot chat message.
2. Loads the agent system prompt from `agents/security/`.
3. Forwards the conversation to the GitHub Copilot LLM API with the agent system prompt prepended.
4. Streams the response back to the user via SSE.

No LLM credentials are needed — the extension uses the user's own Copilot token.

---

## Prerequisites

- Node.js ≥ 20
- A GitHub App registered in your organisation or personal account
- A publicly accessible deployment URL (for webhook delivery)
- GitHub Copilot license for testing

---

## Quick Start

### 1. Install dependencies

```bash
cd distributions/copilot-extension
npm install
```

### 2. Build

```bash
npm run build
```

### 3. Run in development

```bash
npm run dev
```

The server listens on port `3000` by default. Set the `PORT` environment variable to change this.

### 4. Expose via a tunnel (for local development)

```bash
# Using smee.io
npx smee --url https://smee.io/YOUR-CHANNEL --target http://localhost:3000/agent

# Using ngrok
ngrok http 3000
```

---

## GitHub App Setup

1. Go to **GitHub Developer Settings → GitHub Apps → New GitHub App**.
2. Set **Webhook URL** to `https://your-deployment-url.example.com/agent`.
3. Under **Copilot**, enable **Copilot Extension** and set the agent type to **Agent**.
4. Install the app in your account or organisation.
5. In Copilot chat, type `@lgulliver-agents` to invoke the extension.

See [`copilot-extension.yml`](copilot-extension.yml) for a complete manifest reference.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `PORT` | No | HTTP port (default: `3000`) |
| `COPILOT_INTEGRATION_ID` | No | Identifies this extension to the Copilot API (default: `lgulliver-agents`) |

---

## Selecting a Different Default Agent

The default agent is `pr-security-review` (the orchestrating agent). To change this, edit `DEFAULT_AGENT_ID` in [`src/handler.ts`](src/handler.ts):

```typescript
const DEFAULT_AGENT_ID = "authz-review";  // or any other agent ID
```

---

## Deployment

Deploy as a standard Node.js application. The server requires no persistent storage — all agent definitions are loaded from the filesystem at startup.

Recommended platforms: **Railway**, **Render**, **Fly.io**, **Azure Container Apps**.

Always pin to a specific release tag in production. See the root [CHANGELOG](../../CHANGELOG.md) for release notes.

---

## Security Notes

- All inbound requests are verified using the GitHub public key signature (`github-public-key-signature` header) before processing.
- The extension operates read-only and never writes to the repository.
- The user's GitHub token is used only to call the Copilot LLM API — it is never logged or stored.
