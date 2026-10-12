/**
 * submitFeedback whisper_log_id threading.
 *
 * Post-#101 contract: when the surfaced memory carries a whisper_log_id,
 * feedback must attach to that exact event; omitting the key entirely (older
 * outputs) preserves the legacy latest-event fallback. These tests pin both
 * shapes of the POST body to /agent/feedback.
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import type { OrmahConfig } from "../src/config.js";
import { OrmahClient } from "../src/client.js";
import type { WhisperResponse } from "../src/client.js";

const cfg = {
	baseUrl: "http://127.0.0.1:8787",
	toolTimeoutMs: 5000,
} as OrmahConfig;

/** Swap in a fetch stub, run fn, restore. */
async function withFetchStub(
	fn: (calls: Array<{ url: string; init: RequestInit }>) => Promise<void>,
): Promise<void> {
	const calls: Array<{ url: string; init: RequestInit }> = [];
	const original = globalThis.fetch;
	globalThis.fetch = (async (url: unknown, init?: RequestInit) => {
		calls.push({ url: String(url), init: init ?? {} });
		return new Response(JSON.stringify({ text: "ok" }), {
			status: 200,
			headers: { "Content-Type": "application/json" },
		});
	}) as typeof fetch;
	try {
		await fn(calls);
	} finally {
		globalThis.fetch = original;
	}
}

test("includes whisper_log_id in the POST body when present", async () => {
	const client = new OrmahClient(cfg);
	await withFetchStub(async (calls) => {
		const resp = await client.submitFeedback("node-abc", 1, "implicit", 4242);
		assert.equal((resp as WhisperResponse).text, "ok");
		assert.equal(calls.length, 1);
		assert.equal(calls[0].url, "http://127.0.0.1:8787/agent/feedback");
		const body = JSON.parse(String(calls[0].init.body));
		assert.deepEqual(body, {
			node_id: "node-abc",
			signal: 1,
			source: "implicit",
			whisper_log_id: 4242,
		});
	});
});

test("omits the whisper_log_id key entirely when not provided", async () => {
	const client = new OrmahClient(cfg);
	await withFetchStub(async (calls) => {
		await client.submitFeedback("node-xyz", -1, "implicit");
		const body = JSON.parse(String(calls[0].init.body));
		assert.deepEqual(body, {
			node_id: "node-xyz",
			signal: -1,
			source: "implicit",
		});
		assert.ok(
			!("whisper_log_id" in body),
			"whisper_log_id must be absent (not null/undefined) so old-server fallback semantics stay intact",
		);
	});
});

test("omits whisper_log_id when explicitly undefined", async () => {
	const client = new OrmahClient(cfg);
	await withFetchStub(async (calls) => {
		await client.submitFeedback("node-xyz", 1, "explicit", undefined);
		const body = JSON.parse(String(calls[0].init.body));
		assert.ok(!("whisper_log_id" in body));
		assert.equal(body.source, "explicit");
	});
});

test("defaults source to explicit when omitted, still honors whisper_log_id", async () => {
	const client = new OrmahClient(cfg);
	await withFetchStub(async (calls) => {
		// Two-arg + id call shape exercised by older call sites.
		await client.submitFeedback("node-q", 1, undefined, 7);
		const body = JSON.parse(String(calls[0].init.body));
		assert.deepEqual(body, {
			node_id: "node-q",
			signal: 1,
			source: "explicit",
			whisper_log_id: 7,
		});
	});
});
