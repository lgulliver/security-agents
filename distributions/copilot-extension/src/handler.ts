import type { Request, Response } from "express";
import {
  createAckEvent,
  createDoneEvent,
  createErrorsEvent,
  createTextEvent,
  verifyAndParseRequest,
} from "@copilot-extensions/preview-sdk";
import { agents } from "./agents.js";

/**
 * The Copilot completions endpoint.
 * See: https://docs.github.com/en/copilot/building-copilot-extensions/building-a-copilot-agent-for-your-copilot-extension
 */
const COPILOT_API_URL = "https://api.githubcopilot.com/chat/completions";

/**
 * The agent to use when no explicit selection is provided.
 * Change this to offer a different default experience.
 */
const DEFAULT_AGENT_ID = "pr-security-review";

/**
 * Handle a Copilot Extension agent request.
 *
 * Workflow:
 *  1. Verify the GitHub request signature.
 *  2. Prepend the agent system prompt to the message list.
 *  3. Forward to the Copilot LLM API using the user's token.
 *  4. Stream the response back as SSE.
 */
export async function handleCopilotChat(
  req: Request,
  res: Response
): Promise<void> {
  const rawBody: string =
    typeof req.body === "string" ? req.body : JSON.stringify(req.body);

  const signature = req.headers[
    "github-public-key-signature"
  ] as string | undefined;
  const keyId = req.headers[
    "github-public-key-identifier"
  ] as string | undefined;
  const githubToken = req.headers["x-github-token"] as string | undefined;

  // ── 1. Signature verification ──────────────────────────────────────────────
  if (!signature || !keyId) {
    res.status(401).json({ error: "Missing GitHub signature headers." });
    return;
  }

  const { isValidRequest, payload } = await verifyAndParseRequest(
    rawBody,
    signature,
    keyId
  );

  if (!isValidRequest) {
    res.status(401).json({ error: "Request signature verification failed." });
    return;
  }

  // ── 2. Resolve agent ───────────────────────────────────────────────────────
  const agentId = DEFAULT_AGENT_ID;
  const agent = agents[agentId];

  // Begin SSE stream
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  res.write(createAckEvent());

  if (!agent) {
    res.write(
      createErrorsEvent([
        {
          type: "agent",
          message: `Agent '${agentId}' not found. Ensure the agents directory is accessible.`,
          code: "agent_not_found",
          identifier: agentId,
        },
      ])
    );
    res.write(createDoneEvent());
    res.end();
    return;
  }

  if (!githubToken) {
    res.write(
      createErrorsEvent([
        {
          type: "agent",
          message: "Missing GitHub token. Cannot call the Copilot LLM API.",
          code: "missing_token",
          identifier: "github_token",
        },
      ])
    );
    res.write(createDoneEvent());
    res.end();
    return;
  }

  // ── 3. Build message list with agent system prompt ─────────────────────────
  const messages = [
    { role: "system", content: agent.systemPrompt },
    ...payload.messages,
  ];

  // ── 4. Forward to Copilot LLM and stream response ─────────────────────────
  try {
    const llmResponse = await fetch(COPILOT_API_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${githubToken}`,
        "Content-Type": "application/json",
        "Copilot-Integration-Id":
          process.env["COPILOT_INTEGRATION_ID"] ?? "lgulliver-agents",
      },
      body: JSON.stringify({ model: "gpt-4o", stream: true, messages }),
    });

    if (!llmResponse.ok || !llmResponse.body) {
      const errorText = await llmResponse
        .text()
        .catch(() => llmResponse.statusText);
      throw new Error(
        `Copilot LLM API returned ${llmResponse.status}: ${errorText}`
      );
    }

    const reader = llmResponse.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      for (const line of chunk.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        const data = line.slice(6).trim();
        if (data === "[DONE]") continue;

        try {
          const parsed = JSON.parse(data) as {
            choices?: Array<{ delta?: { content?: string } }>;
          };
          const content = parsed.choices?.[0]?.delta?.content;
          if (content) {
            res.write(createTextEvent(content));
          }
        } catch {
          // Ignore malformed SSE chunks
        }
      }
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    res.write(
      createTextEvent(
        `\n\n⚠️ **Error contacting the Copilot LLM API:** ${message}\n`
      )
    );
  }

  res.write(createDoneEvent());
  res.end();
}
