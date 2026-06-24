/**
 * Slash commands — the Pi analogue of integrations/claude-plugin/commands/.
 *
 *   /ormah:setup       Install/repair the Ormah runtime + wire the Pi extension
 *   /ormah:status      Server health + memory stats
 *   /ormah:maintenance Run the maintenance agent prompt in-session
 *   /ormah:upgrade     Upgrade the Ormah runtime
 *   /ormah:reload      Reload Pi extensions/skills/prompts/themes
 */

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { homedir } from "node:os";
import type {
	ExtensionAPI,
	ExtensionCommandContext,
} from "@earendil-works/pi-coding-agent";
import type { OrmahClient } from "./client.js";
import { loadMaintenancePrompt } from "./maintenance.js";

const PI_AGENTS_MD = join(homedir(), ".pi", "agent", "AGENTS.md");
const SENTINEL_START = "<!-- ormah:start -->";
const SENTINEL_END = "<!-- ormah:end -->";

const GUIDANCE = `# Ormah — persistent memory

You have durable, local memory via Ormah. Memory should be involuntary: you do not need to remember to remember.

- **recall**: before answering, relevant memories may already have been whispered to you. Use ormah_recall to search when you need prior context, decisions, or preferences.
- **remember**: use ormah_remember to store decisions, preferences, facts, corrections, and noteworthy observations. Write self-contained content + a one-line title.
- **outdated**: use ormah_mark_outdated when you learn a stored memory no longer holds.
- **feedback**: use ormah_submit_feedback (implicit) to tune which memories whisper surfaces.
- **maintenance**: when a whisper includes a \`maintenance_due\` signal, run the two-step ormah_run_maintenance flow (or /ormah:maintenance). Submit ALL evaluated pairs in \`edges\`, using \`none\` for non-relationships, so they don't reappear.
- Silence beats noise: do not call tools just to call them.`;

async function upsertGuidance(): Promise<void> {
	let existing = "";
	try {
		existing = await readFile(PI_AGENTS_MD, "utf8");
	} catch {
		existing = "";
	}
	const block = `${SENTINEL_START}\n${GUIDANCE}\n${SENTINEL_END}`;
	if (existing.includes(SENTINEL_START)) {
		const next = existing.replace(
			new RegExp(`${SENTINEL_START}[\\s\\S]*?${SENTINEL_END}`, "m"),
			block,
		);
		await writeFile(PI_AGENTS_MD, next, "utf8");
		return;
	}
	await mkdir(dirname(PI_AGENTS_MD), { recursive: true });
	const sep =
		existing && !existing.endsWith("\n") ? "\n\n" : existing ? "\n" : "";
	await writeFile(PI_AGENTS_MD, existing + sep + block + "\n", "utf8");
}

export function registerCommands(pi: ExtensionAPI, client: OrmahClient): void {
	pi.registerCommand("ormah:setup", {
		description: "Install/repair the Ormah runtime and wire this Pi extension",
		handler: async (_args, ctx: ExtensionCommandContext) => {
			if (!ctx.hasUI) return;
			const ok = await ctx.ui.confirm(
				"Ormah setup",
				"Run `ormah setup --skip-client-setup` (starts server + preloads models + autostart) and install the Pi guidance block into ~/.pi/agent/AGENTS.md?",
			);
			if (!ok) return;
			ctx.ui.setStatus("ormah", "running ormah setup…");
			const result = await pi.exec("ormah", ["setup", "--skip-client-setup"], {
				timeout: 300_000,
			});
			await upsertGuidance();
			ctx.ui.setStatus("ormah", undefined);
			const tail = (result.stdout || result.stderr || "")
				.split("\n")
				.filter(Boolean)
				.slice(-3)
				.join(" | ");
			ctx.ui.notify(
				`Ormah setup done (rc=${result.code}). ${tail}`,
				result.code === 0 ? "info" : "warning",
			);
			ctx.ui.notify(
				"Guidance block written to ~/.pi/agent/AGENTS.md. Run /reload to activate.",
				"info",
			);
		},
	});

	pi.registerCommand("ormah:status", {
		description: "Show Ormah server health and memory stats",
		handler: async (_args, ctx: ExtensionCommandContext) => {
			try {
				const stats = await client.health();
				const byTier = Object.entries(stats.by_tier)
					.map(([k, v]) => `${k}:${v}`)
					.join(" ");
				ctx.ui.notify(
					`Ormah: ${stats.total_nodes} memories, ${stats.total_edges} edges (${byTier})`,
					"info",
				);
				ctx.ui.setStatus("ormah", `connected · ${stats.total_nodes} mem`);
			} catch (e) {
				ctx.ui.notify(
					`Ormah: server not reachable — ${(e as Error).message.slice(0, 80)}`,
					"warning",
				);
				ctx.ui.setStatus("ormah", "down");
			}
		},
	});

	pi.registerCommand("ormah:maintenance", {
		description: "Run the Ormah memory maintenance flow in this session",
		handler: async (_args, _ctx: ExtensionCommandContext) => {
			const prompt = await loadMaintenancePrompt();
			// Runs maintenance in-session; an isolated background subagent is the upgrade path.
			pi.sendUserMessage(prompt);
		},
	});

	pi.registerCommand("ormah:upgrade", {
		description:
			"Upgrade the Ormah runtime (uv tool upgrade) and restart the server",
		handler: async (_args, ctx: ExtensionCommandContext) => {
			if (!ctx.hasUI) return;
			const ok = await ctx.ui.confirm(
				"Ormah upgrade",
				"Run `uv tool upgrade ormah` then restart the server?",
			);
			if (!ok) return;
			ctx.ui.setStatus("ormah", "upgrading…");
			const up = await pi.exec("uv", ["tool", "upgrade", "ormah"], {
				timeout: 300_000,
			});
			await pi.exec("ormah", ["server", "stop"], { timeout: 15_000 });
			await pi.exec("ormah", ["server", "start", "-d"], { timeout: 30_000 });
			ctx.ui.setStatus("ormah", undefined);
			ctx.ui.notify(
				`Ormah upgrade done (rc=${up.code}).`,
				up.code === 0 ? "info" : "warning",
			);
		},
	});

	pi.registerCommand("ormah:reload", {
		description: "Reload Pi extensions, skills, prompts, and themes",
		handler: async (_args, ctx: ExtensionCommandContext) => {
			await ctx.reload();
		},
	});
}
