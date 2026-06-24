/**
 * Ormah-Pi runtime configuration.
 *
 * Reads ORMAH_* env vars (and ~/.config/ormah/.env by convention) the same way
 * the Ormah server does, so the extension and server stay in sync without a
 * second source of truth. Only the handful of settings the extension actually
 * consumes are modeled here — everything else lives server-side.
 */

function envInt(name: string, fallback: number): number {
	const raw = process.env[name];
	if (!raw) return fallback;
	const n = Number(raw);
	return Number.isFinite(n) ? n : fallback;
}

function envStr(name: string, fallback: string): string {
	const raw = process.env[name];
	return raw && raw.length ? raw : fallback;
}

export interface OrmahConfig {
	/** Base URL of the local Ormah HTTP server. */
	baseUrl: string;
	/** Whisper inject HTTP timeout (ms). */
	whisperTimeoutMs: number;
	/** Per-tool HTTP timeout (ms). run_maintenance uses maintenanceTimeoutMs. */
	toolTimeoutMs: number;
	/** run_maintenance HTTP timeout (ms) — extraction/application can be slow. */
	maintenanceTimeoutMs: number;
	/** Whisper store (/ingest) timeout (ms) — LLM extraction can take 30s+. */
	storeTimeoutMs: number;
	/** Nudge the agent to use `remember` every N user prompts (0 = off). Mirrors ORMAH_WHISPER_NUDGE_INTERVAL. */
	whisperNudgeInterval: number;
	/** Minimum user turns before a session is worth storing. Mirrors ORMAH_WHISPER_OUT_MIN_TURNS. */
	whisperOutMinTurns: number;
	/** Enable agent-driven auto-maintenance (mirrors ORMAH_CLAUDE_MAINTENANCE_ENABLED for Pi). */
	maintenanceEnabled: boolean;
	/** Max once per N hours the whisper inject appends a maintenance_due signal. */
	maintenanceSignalIntervalHours: number;
}

export function loadConfig(): OrmahConfig {
	const host = envStr("ORMAH_HOST", "127.0.0.1");
	const port = envInt("ORMAH_PORT", 8787);
	// ORMAH_BASE_URL wins if explicitly set.
	const baseUrl = envStr("ORMAH_BASE_URL", `http://${host}:${port}`);
	const piMaintenance = process.env.ORMAH_PI_MAINTENANCE_ENABLED;
	const claudeMaintenance = process.env.ORMAH_CLAUDE_MAINTENANCE_ENABLED;
	return {
		baseUrl,
		whisperTimeoutMs: envInt("ORMAH_PI_WHISPER_TIMEOUT_MS", 12_000),
		toolTimeoutMs: envInt("ORMAH_PI_TOOL_TIMEOUT_MS", 30_000),
		maintenanceTimeoutMs: envInt("ORMAH_PI_MAINTENANCE_TIMEOUT_MS", 300_000),
		storeTimeoutMs: envInt("ORMAH_PI_STORE_TIMEOUT_MS", 120_000),
		whisperNudgeInterval: envInt("ORMAH_WHISPER_NUDGE_INTERVAL", 10),
		whisperOutMinTurns: envInt("ORMAH_WHISPER_OUT_MIN_TURNS", 3),
		maintenanceEnabled:
			piMaintenance !== undefined
				? piMaintenance === "true"
				: claudeMaintenance === "true",
		maintenanceSignalIntervalHours: envInt(
			"ORMAH_MAINTENANCE_SIGNAL_INTERVAL_HOURS",
			24,
		),
	};
}
