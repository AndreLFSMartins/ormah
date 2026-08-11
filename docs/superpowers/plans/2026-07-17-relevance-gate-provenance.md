# Relevance Gate (Provenance) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. **Council-reviewed 2026-07-20** (Cursor + Codex) — the safety net below (in-context eval as ship gate + quarantine ledger) is a council requirement, not optional.

**Goal:** Make the Extractor label every candidate memory `provenance=material|product` inside the same extraction call, and have deterministic code drop `material` before write — killing the ~16.5% doc/SDK-echo noise, with a durable safety net so a false Product drop is recoverable.

**Architecture:** No new LLM call. Add a `provenance` field to the extraction JSON schema + a rules section to the prompt; the model labels each candidate. A guard in `ingest_conversation`'s write loop drops candidates labeled exactly `material` when the kill-switch is on, **appending every drop to a durable quarantine ledger** (full content + source + provider/model + prompt version) so a false drop is recoverable. Trust the label unconditionally (no per-model calibration, no safe-list — see [ADR-0002](/Users/andre/Documents/GitHub/Tools/ormah/docs/adr/0002-relevance-gate-provenance.md)); errs toward keeping Product. The drop is validated **pre-ship by an in-context eval** that runs the real extraction prompt+schema end-to-end (the ship gate), and its false-drop rate is confirmed on a Beta canary before the default is trusted.

**Tech Stack:** Python ≥3.11, pydantic-settings, pytest (`asyncio_mode=auto`), `claude_cli` extractor via `--json-schema`.

## Global Constraints

- **Worktree (base = local-main, already created):** work in `/Users/andre/Documents/GitHub/ormah-wt-relevance-gate` (branch `feat/relevance-gate`). Base is **local-main, NOT upstream/main** — the schema/chunk extraction this modifies is Beta-only (local-main is 468 commits ahead; `_INGEST_RESPONSE_SCHEMA` and `ingest_chunk_chars` do not exist in upstream/main). Upstream PR is **deferred** until that extraction base lands in `r-spade/main`. Never `git checkout` in the main `Tools/ormah` tree (it runs the live Beta server off its working tree — a checkout crashes the whisper hooks).
- **⚠️ venv landmine:** the session exports `VIRTUAL_ENV=…/Tools/ormah/.venv` (the Beta venv). The worktree has its own venv at `…/ormah-wt-relevance-gate/.venv` (deps already installed). **Never run `uv pip install`** (it would install into the Beta venv and redirect its ormah editable to the worktree, crashing live hooks). Run every command with the worktree python: `env -u VIRTUAL_ENV HOME=$(mktemp -d) /Users/andre/Documents/GitHub/ormah-wt-relevance-gate/.venv/bin/python -m pytest ...`.
- **Reference docs are outside the worktree** (gitignored/untracked on local-main): read ADR-0002, CONTEXT.md, and this plan at their absolute `Tools/ormah/...` paths — they are absent from the worktree checkout.
- **Ship gate (council):** the **in-context eval (Task 5) PASS is a documented merge prerequisite** — code does not ship without it. Re-run it on any provider/model change. It needs a live provider, so it is NOT in `make test`.
- **Pytest needs HOME isolation** (issue #106): `HOME=$(mktemp -d)` or the live `.env` breaks collection.
- **Lint:** ruff, `target-version = py311`, `line-length = 100`.
- **Kill-switch default = drop ON** (`ORMAH_INGEST_RELEVANCE_GATE=true`). The drop is only *trusted* after the canary (Verification) confirms the false-drop rate; until then the quarantine ledger is the recovery net.
- **Errs toward keeping Product:** drop ONLY when the label is exactly `"material"`. Absent / null / `"product"` / any unrecognized value → keep.
- **Gate runs before dedup**, first thing in the write loop.
- Material/Product definitions are canonical in [CONTEXT.md](/Users/andre/Documents/GitHub/Tools/ormah/CONTEXT.md) (`## Relevance gate`, `## Material`, `## Product`) — copy verbatim into the prompt, do not paraphrase.
- **graphify first:** before reading/grepping source in the worktree, orient with `graphify query "<question>"` (rule applies to every task).

---

### Task 1: Kill-switch setting

**Files:** Modify `src/ormah/config.py` (field next to `ingest_min_confidence`, ~line 348) · Test `tests/test_config.py`

**Interfaces — Produces:** `Settings.ingest_relevance_gate: bool` (env `ORMAH_INGEST_RELEVANCE_GATE`, default `True`).

- [ ] **Step 1 — failing test** (`tests/test_config.py`):

```python
def test_relevance_gate_defaults_on(monkeypatch):
    monkeypatch.delenv("ORMAH_INGEST_RELEVANCE_GATE", raising=False)
    from ormah.config import Settings
    assert Settings().ingest_relevance_gate is True

def test_relevance_gate_env_off(monkeypatch):
    monkeypatch.setenv("ORMAH_INGEST_RELEVANCE_GATE", "false")
    from ormah.config import Settings
    assert Settings().ingest_relevance_gate is False
```

- [ ] **Step 2 — run, expect FAIL** (`AttributeError`): `env -u VIRTUAL_ENV HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_config.py -k relevance_gate -v`
- [ ] **Step 3 — add the field** in `src/ormah/config.py` after `ingest_min_confidence`:

```python
    ingest_relevance_gate: bool = True  # drop memories the Extractor labels provenance=material
```

- [ ] **Step 4 — run, expect PASS** (same command).
- [ ] **Step 5 — commit:** `git commit -am "feat(ingest): add ORMAH_INGEST_RELEVANCE_GATE kill-switch (default on)"`

---

### Task 2: Emit the provenance label (schema + prompt)

**Files:** Modify `src/ormah/engine/memory_engine.py` (`_INGEST_RESPONSE_SCHEMA` ~3144, `_INGEST_LLM_RULES` ~3081) · Test `tests/test_engine/test_ingest.py`

**Interfaces — Produces:** extraction dicts carry `"provenance": "material"|"product"` (schema-required, so `claude_cli` emits it; other providers may omit — Task 4 tolerates that).

- [ ] **Step 1 — failing wiring test** (`tests/test_engine/test_ingest.py`):

```python
def test_extraction_schema_and_prompt_wire_provenance():
    from ormah.engine import memory_engine as me
    item = me._INGEST_RESPONSE_SCHEMA["properties"]["memories"]["items"]
    assert item["properties"]["provenance"]["enum"] == ["material", "product"]
    assert "provenance" in item["required"]
    rules = me._INGEST_LLM_RULES
    assert "material" in rules and "product" in rules
    assert '"provenance"' in rules  # appears in the output-format section
```

- [ ] **Step 2 — run, expect FAIL** (`KeyError: 'provenance'`).
- [ ] **Step 3 — add `provenance` to `_INGEST_RESPONSE_SCHEMA`** properties (after `"confidence"`) and to `required`:

```python
                    "provenance": {"type": "string", "enum": ["material", "product"]},
```
```python
                "required": [
                    "content", "type", "title", "tags", "about_self", "confidence",
                    "provenance",
                ],
```

- [ ] **Step 4 — add the Provenance rules to `_INGEST_LLM_RULES`**, immediately **before** `## Output format`:

```
## Provenance (required)

Label every memory on ONE axis: did the session PRODUCE it, or did it merely PASS THROUGH?

- **material** — restates input that passed *through* the session: third-party API/SDK facts, a version string, generic technical knowledge, a read-through of someone else's code — content that would be true and findable in docs/code regardless of this conversation.
- **product** — something the session itself *produced*: a decision, a user correction, a discovered bug, a complaint, an outcome — even when it is *about* an external tool.

When uncertain, label **product**. A dropped Material re-extracts later (it recurs); a dropped Product often happens once and is lost.
```

Then in the `## Output format` "For each memory:" list, after the `"confidence"` bullet:

```
- "provenance": "material" or "product" — see the Provenance rule above. This is required.
```

- [ ] **Step 5 — run, expect PASS.**
- [ ] **Step 6 — commit:** `git commit -am "feat(ingest): extractor labels each memory provenance=material|product"`

---

### Task 3: Durable quarantine ledger (council safety net)

**Files:** Create `src/ormah/engine/relevance_quarantine.py` · Test `tests/test_engine/test_relevance_quarantine.py`

**Rationale (council, HIGH):** ADR-0002 promises the drop is "recoverable/measurable", but logging a title is not recovery. A durable append-only ledger of every dropped candidate (full content + source + provider/model + prompt version) makes a false Product drop recoverable and lets the canary measure the false-drop rate. **JSONL, not a DB table** (append-only audit log; no migration needed; inspectable with `jq`).

**Interfaces — Produces:**
- `quarantine_path(settings) -> pathlib.Path` — `<ormah data dir>/relevance_gate_quarantine.jsonl`, deriving the data dir the SAME way the store DB path is derived (find it via `graphify query "where is the sqlite db path configured"`; put the file beside it).
- `prompt_version() -> str` — first 12 hex of `sha256(_INGEST_LLM_RULES.encode())` (import the constant from `ormah.engine.memory_engine`).
- `record_dropped(settings, *, content, title, node_type, space, provider, model, dropped_at) -> None` — append one JSON object `{dropped_at, title, content, node_type, space, provider, model, prompt_version, label: "material"}` (one line, `json.dumps` + `"\n"`, `mkdir(parents=True, exist_ok=True)` on first write).
- `iter_dropped(settings) -> Iterator[dict]` — yield each record (inspection/replay; returns empty if the file is absent).

- [ ] **Step 1 — failing test** (`tests/test_engine/test_relevance_quarantine.py`):

```python
import json
from ormah.engine import relevance_quarantine as q

def test_record_and_iter_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "quarantine_path", lambda s: tmp_path / "quarantine.jsonl")
    q.record_dropped(None, content="the requests lib raises Timeout", title="requests Timeout",
                     node_type="fact", space="proj", provider="claude_cli", model="haiku",
                     dropped_at="2026-07-20T00:00:00+00:00")
    rows = list(q.iter_dropped(None))
    assert len(rows) == 1
    r = rows[0]
    assert r["content"] == "the requests lib raises Timeout"
    assert r["label"] == "material"
    assert r["provider"] == "claude_cli"
    assert len(r["prompt_version"]) == 12

def test_iter_empty_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "quarantine_path", lambda s: tmp_path / "missing.jsonl")
    assert list(q.iter_dropped(None)) == []
```

- [ ] **Step 2 — run, expect FAIL** (module missing): `env -u VIRTUAL_ENV HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_engine/test_relevance_quarantine.py -v`
- [ ] **Step 3 — implement `src/ormah/engine/relevance_quarantine.py`** per the Interfaces above. `prompt_version` imports `_INGEST_LLM_RULES` lazily inside the function (avoid a heavy import at module load). `record_dropped` computes `prompt_version()` and writes one JSON line.
- [ ] **Step 4 — run, expect PASS (2 passed).**
- [ ] **Step 5 — commit:** `git commit -am "feat(ingest): durable quarantine ledger for dropped Material (JSONL)"`

---

### Task 4: Deterministic drop → ledger + counters

**Files:** Modify `src/ormah/engine/memory_engine.py` (`ingest_conversation` loop, ~2708-2773) · Test `tests/test_engine/test_ingest.py`

**Interfaces:**
- Consumes: `Settings.ingest_relevance_gate` (T1); `mem["provenance"]` (T2); `relevance_quarantine.record_dropped` / `.prompt_version` (T3).
- Produces: memories labeled `material` are absent from returned `created` when the gate is on (identical in `dry_run`), **each recorded to the quarantine ledger**; per-ingest counts of dropped-Material and missing-label are logged (the missing-label count is the no-op signal for providers that don't enforce the schema).

- [ ] **Step 1 — failing tests** (`tests/test_engine/test_ingest.py`; monkeypatch `_extract_memories_llm` to return canned dicts, the existing pattern):

```python
def _canned(provenance):
    m = {"content": "x" * 60, "type": "fact", "title": "t",
         "tags": [], "about_self": False, "confidence": 0.9, "provenance": provenance}
    if provenance is None:
        m.pop("provenance")
    return [m]

@pytest.mark.parametrize("gate,prov,kept", [
    (True,  "material", False),   # dropped
    (True,  "product",  True),
    (True,  None,       True),    # missing label -> keep (errs toward Product)
    (True,  "garbage",  True),    # unknown label -> keep
    (False, "material", True),    # kill-switch off -> keep
])
def test_relevance_gate_drop(engine, monkeypatch, gate, prov, kept):
    engine.settings.ingest_relevance_gate = gate
    monkeypatch.setattr(type(engine), "_extract_memories_llm", lambda self, c: _canned(prov))
    out = engine.ingest_conversation("hello world " * 20, dry_run=True)
    assert (len(out) == 1) is kept

def test_dropped_material_is_recorded(engine, monkeypatch, tmp_path):
    from ormah.engine import relevance_quarantine as q
    monkeypatch.setattr(q, "quarantine_path", lambda s: tmp_path / "q.jsonl")
    engine.settings.ingest_relevance_gate = True
    monkeypatch.setattr(type(engine), "_extract_memories_llm", lambda self, c: _canned("material"))
    engine.ingest_conversation("hello world " * 20, dry_run=False, space="proj")
    assert len(list(q.iter_dropped(engine.settings))) == 1
```

- [ ] **Step 2 — run, expect FAIL** (material kept; nothing recorded).
- [ ] **Step 3 — implement** in `ingest_conversation`: init `dropped_material = 0` and `missing_label = 0` beside `skipped = 0`; as the FIRST check after `mem_content` is resolved (before the dedup block):

```python
            # Relevance gate (ADR-0002): drop input echoed back as knowledge. Trust the
            # label; drop ONLY exact "material" so an absent/unknown label errs toward Product.
            prov = mem.get("provenance")
            if self.settings.ingest_relevance_gate:
                if prov not in ("material", "product"):
                    missing_label += 1
                if prov == "material":
                    from ormah.engine import relevance_quarantine as _q
                    _q.record_dropped(
                        self.settings, content=mem_content,
                        title=mem.get("title") or mem_content[:60],
                        node_type=mem.get("type", "fact"), space=space,
                        provider=getattr(self.settings, "ingest_llm_provider", None),
                        model=getattr(self.settings, "ingest_llm_model", None),
                        dropped_at=datetime.now(timezone.utc).isoformat(),
                    )
                    logger.info("Relevance gate: dropped Material: %s",
                                mem.get("title") or mem_content[:40])
                    dropped_material += 1
                    continue
```

(Use the real settings field names for provider/model — find them via `graphify query "ingest llm provider and model settings"`. Ensure `datetime`/`timezone` are imported.) At the end, beside the skipped log:

```python
        if dropped_material or missing_label:
            logger.info("Relevance gate: dropped %d Material, %d candidates had no usable label",
                        dropped_material, missing_label)
```

- [ ] **Step 4 — run gate + record tests, expect PASS.**
- [ ] **Step 5 — full ingest suite, no regressions:** `env -u VIRTUAL_ENV HOME=$(mktemp -d) .venv/bin/python -m pytest tests/test_engine/test_ingest.py tests/test_engine/test_ingest_extraction.py -v`
- [ ] **Step 6 — commit:** `git commit -am "feat(ingest): drop provenance=material, record to quarantine ledger, log counts"`

---

### Task 5: In-context pre-ship eval (the ship gate)

**Files:** Create `eval/relevance/corpus/cases.json`, `eval/relevance/runner.py`, `eval/relevance/__init__.py`

**Rationale (council, HIGH — both peers, 0.9–0.99):** a standalone classify prompt over isolated node content does NOT test the production decision — production labels *inside* `_INGEST_LLM_PROMPT` with competing extraction rules, so a systematic Product→material bias can pass a standalone eval and cause irreversible loss. This eval runs the **real** `_INGEST_LLM_PROMPT` + `_INGEST_RESPONSE_SCHEMA` end-to-end via `_extract_memories_llm` and reads the emitted `provenance` labels. It is the **ship gate** (see Global Constraints). The standalone-classify smoke is dropped (YAGNI) in favor of this.

**Interfaces — Produces:** two asymmetric rates measured on the real extraction path — `product_preserved` (of product cases, fraction whose salient memory the extractor emits AND labels `product`) **≥ 0.98**; `material_dropped` (of material cases, fraction whose material candidate is labeled `material`) **≥ 0.80**. Exit non-zero (`FAIL`) if either misses or the corpus is below the minimum.

- [ ] **Step 1 — build the corpus** `eval/relevance/corpus/cases.json`: a list of cases, each a short **conversation snippet** crafted to yield one salient memory of known provenance, plus its ground truth. Seed material cases from the 461 doc/SDK `fact` nodes in [problemas-de-ingestao.md](/Users/andre/Documents/GitHub/Tools/ormah/docs/problemas-de-ingestao.md); product cases from real `decision`/`preference`/correction nodes. **Include ≥3 ambiguous pairs** — near-identical text that is Material in one snippet's context and Product in another (this is what the standalone eval could not test). Aim ≥20 product + ≥20 material cases. Format:

```json
[
  {"id": "mat-requests-timeout", "label": "material",
   "snippet": "user: what does requests raise on timeout?\nassistant: requests.exceptions.Timeout after the configured limit."},
  {"id": "prod-gate-decision", "label": "product",
   "snippet": "user: should we calibrate per model?\nassistant: no — decided to trust the label with a kill-switch; calibration lands off for the median user."}
]
```

- [ ] **Step 2 — write `eval/relevance/runner.py`:**

```python
"""In-context relevance-gate eval (the ship gate). Run pre-merge with a live provider:
   env -u VIRTUAL_ENV HOME=$(mktemp -d) .venv/bin/python -m eval.relevance.runner
Runs the REAL extraction prompt+schema end-to-end and scores provenance labels.
Exits non-zero if either asymmetric threshold is missed or the corpus is too small."""
import json, sys
from pathlib import Path
from ormah.config import Settings
from ormah.engine.memory_engine import MemoryEngine

MIN_PER_CLASS = 20

def _labels_for(engine, snippet):
    """Return the list of provenance labels the real extractor emits for a snippet."""
    mems = engine._extract_memories_llm(snippet)
    if isinstance(mems, str):  # extractor error string
        return []
    return [m.get("provenance") for m in mems if isinstance(m, dict)]

def main() -> int:
    cases = json.loads((Path(__file__).parent / "corpus/cases.json").read_text())
    prod = [c for c in cases if c["label"] == "product"]
    mat = [c for c in cases if c["label"] == "material"]
    if len(prod) < MIN_PER_CLASS or len(mat) < MIN_PER_CLASS:
        print(f"FAIL: corpus too small (product={len(prod)}, material={len(mat)}, "
              f"need >={MIN_PER_CLASS} each)")
        return 2
    engine = MemoryEngine(Settings())
    # product preserved: extractor emits at least one candidate labeled "product"
    prod_ok = sum("product" in _labels_for(engine, c["snippet"]) for c in prod) / len(prod)
    # material dropped: extractor labels a candidate "material" (the gate would drop it)
    mat_ok = sum("material" in _labels_for(engine, c["snippet"]) for c in mat) / len(mat)
    print(f"product_preserved={prod_ok:.3f} (>=0.98)  material_dropped={mat_ok:.3f} (>=0.80)")
    ok = prod_ok >= 0.98 and mat_ok >= 0.80
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
```

(Construct `MemoryEngine` the way the codebase does — check an existing entrypoint via `graphify query "how is MemoryEngine constructed"`; adapt the constructor call if it needs a store/index.)

- [ ] **Step 3 — run against the live provider** (ship gate): `env -u VIRTUAL_ENV HOME=$(mktemp -d) .venv/bin/python -m eval.relevance.runner`. Expected: both rates + `PASS`. **FAIL on `product_preserved` → do NOT merge** (systematic bias — revisit the prompt). FAIL on `material_dropped` → gate under-drops (cheap error), may merge with a note.
- [ ] **Step 4 — commit:** `git commit -am "test(ingest): in-context relevance-gate eval (ship gate, asymmetric thresholds)"`

---

## Verification (post-ship canary — not a unit test)

The kill-switch defaults ON, but the drop is **trusted only after this canary.** Run the Beta with the gate on for a few dogfood days, then:
1. **False-drop check (the safety net in action):** sample the quarantine ledger (`jq . <data-dir>/relevance_gate_quarantine.jsonl`); any entry that is actually Product is a false drop → recover it (re-`remember` from the ledger content) and, if the rate is non-trivial, revisit the prompt or flip `ORMAH_INGEST_RELEVANCE_GATE=false`.
2. **Effect check:** re-run the doc queries ([evaluation-2026-07-13-deep-review.md](/Users/andre/Documents/GitHub/Tools/ormah/docs/evaluation-2026-07-13-deep-review.md) / problemas-de-ingestao.md): the 461 Material `fact` nodes trend to ~0 while `decision`/`preference` stay flat.
3. Grep the server log for `Relevance gate: dropped` for the live drop + no-op-label rate.

## Self-review notes

- **Council coverage:** in-context eval as ship gate (T5) · quarantine ledger for recovery (T3, wired in T4) · eval PASS = merge prereq + re-run on provider change (Global Constraints) · no-op-label count logged (T4) · corpus guard (T5 Step 2) · canary before trusting default (Verification). Rejected: default-off-per-provider (contradicts ADR-0002; addressed via ship-gate-on-real-provider instead).
- **ADR-0002 coverage:** in-prompt label (T2) · code drops Material (T4) · trust-the-label + kill-switch, no calibration/safe-list (T1 + T4 guard) · auditable+recoverable drop (T3 ledger) · pre-ship validation (T5) · post-ship Beta re-query (Verification).
- **Sequencing unchanged:** P1 gate → ADR-0004 → track 1 (this plan is the P1 gate).

## Amendment 2026-07-20 (council-pr — both peers NO-SHIP)

Cursor + Codex blocked the merge with 4 HIGH findings. Adopted (see [ADR-0002 amendment](/Users/andre/Documents/GitHub/Tools/ormah/docs/adr/0002-relevance-gate-provenance.md)):

- **SHADOW mode is the new default** (`ingest_relevance_gate_enforce=False`): the gate records would-drops to the ledger but keeps the memory. No irreversible risk on merge; shadow ledger = real-store eval data. Supersedes the "Kill-switch default = drop ON" line above (the gate is on, but observing, not dropping).
- **Fail-open when enforcing:** drop only if the recovery record was written; on quarantine-write failure, KEEP (this reverses the earlier "guard" that dropped anyway).

**Enforce-gate — ALL required before flipping `ingest_relevance_gate_enforce=True`:**
1. In-context eval passes on a **real-store** corpus for the active provider/model (seed corpus is insufficient).
2. Quarantine ledger included in Ormah **backup/restore** + an idempotent re-ingestion command (Codex HIGH: the ledger currently sits outside the backup set → drops irrecoverable on restore).
3. Ship-gate scorer fixed so mixed material+product labels cannot false-pass (Codex HIGH: verified false-pass at 1.000/1.000).
4. (MEDIUM) ledger records source context (session/agent id); eval adds an end-to-end `ingest_conversation` case; ship-gate wired as a documented merge prerequisite.

Items 2–4 are dormant-path work gating the enforce flip; shadow mode makes the branch safe to merge before they land.
