import { readFile, readdir } from "fs/promises";
import { join, resolve, dirname, basename } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

// distributions/copilot-extension/src/agents.ts
// When compiled → distributions/copilot-extension/dist/agents.js
// Repo root is 3 levels up from dist/
const REPO_ROOT = resolve(__dirname, "../../..");
const AGENTS_DIR = join(REPO_ROOT, "agents");

export interface AgentDefinition {
  /** Identifier derived from the filename (e.g. "pr-security-review"). */
  id: string;
  /** Human-readable name extracted from the H1 heading. */
  name: string;
  /** Short description extracted from the Purpose section. */
  description: string;
  /** Full markdown content used as the system prompt. */
  systemPrompt: string;
}

/** All loaded agent definitions, keyed by their file-stem ID. */
export const agents: Record<string, AgentDefinition> = {};

/**
 * Scan `agents/security/*.md` and populate the {@link agents} map.
 * Called once at startup.
 */
export async function loadAgents(): Promise<void> {
  const securityDir = join(AGENTS_DIR, "security");

  let files: string[];
  try {
    files = await readdir(securityDir);
  } catch (err) {
    console.error(`[agents] Failed to read security agents dir: ${err}`);
    return;
  }

  for (const file of files) {
    if (!file.endsWith(".md")) continue;

    const filePath = join(securityDir, file);
    let content: string;
    try {
      content = await readFile(filePath, "utf-8");
    } catch (err) {
      console.warn(`[agents] Could not read ${filePath}: ${err}`);
      continue;
    }

    const agentId = basename(file, ".md");

    // Extract H1 heading as the display name
    const nameMatch = content.match(/^#\s+(.+)$/m);
    // Extract first paragraph of the Purpose section as description
    const purposeMatch = content.match(/## Purpose\n\n(.+?)(?:\n\n|$)/s);

    agents[agentId] = {
      id: agentId,
      name: nameMatch?.[1]?.trim() ?? agentId,
      description:
        purposeMatch?.[1]?.trim().replace(/\n/g, " ") ??
        `Security review agent: ${agentId}`,
      systemPrompt: content,
    };
  }

  console.log(
    `[agents] Loaded ${Object.keys(agents).length} agents:`,
    Object.keys(agents).join(", ")
  );
}
