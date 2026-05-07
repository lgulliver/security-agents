import express from "express";
import rateLimit from "express-rate-limit";
import { loadAgents } from "./agents.js";
import { handleCopilotChat } from "./handler.js";

const PORT = parseInt(process.env["PORT"] ?? "3000", 10);

const app = express();

// Parse raw body as text so we can pass it to verifyAndParseRequest
app.use(express.text({ type: "*/*" }));

// Rate-limit the agent endpoint to protect against abuse.
// GitHub Copilot Extensions receive one request per user turn; 60 rpm
// per IP is generous for normal usage but provides a safety ceiling.
const agentLimiter = rateLimit({
  windowMs: 60 * 1000, // 1 minute
  max: 60,
  standardHeaders: true,
  legacyHeaders: false,
});

// ── Routes ─────────────────────────────────────────────────────────────────

/** Copilot Extension agent endpoint */
app.post("/agent", agentLimiter, handleCopilotChat);

/** Health check */
app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

// ── Startup ────────────────────────────────────────────────────────────────

await loadAgents();

app.listen(PORT, () => {
  console.log(`[server] Copilot Extension listening on port ${PORT}`);
});
