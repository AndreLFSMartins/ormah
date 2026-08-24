### Task 2: The prompt budget setting

**Files:**
- Modify: `src/ormah/config.py:287` (settings block) and `:525-537` (validators)
- Test: `tests/test_background/test_consolidator.py` (the existing settings tests live there)

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings.consolidation_max_prompt_chars: int` (default `24000`, validator floor
  `4000`). Task 3's budget arithmetic and Task 5's derived Ollama window both read it.

**Context you need.** `Settings` is a `pydantic-settings` model; every field is overridable via
an `ORMAH_`-prefixed environment variable, so this one is `ORMAH_CONSOLIDATION_MAX_PROMPT_CHARS`.
Validators are `@field_validator` classmethods grouped further down the file. The consolidation
fields sit together under a `# Consolidation` comment, ending at
`consolidation_max_cluster_nodes: int = 5`.

The default is not a guess: it was measured over a 5,923-node store with 301 real consolidation
events. The worst real event builds a 12,961-char prompt and the largest single node in the whole
store is 5,513 chars, so 24000 keeps 1.85x headroom over the worst case ever observed. Do not
change the number.

`tests/test_background/test_consolidator.py` already imports `pytest` and `Settings` — you do not
need to add either.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background/test_consolidator.py`:

```python
def test_consolidation_max_prompt_chars_default(tmp_path):
    s = Settings(memory_dir=tmp_path)
    assert s.consolidation_max_prompt_chars == 24000


def test_consolidation_max_prompt_chars_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ORMAH_CONSOLIDATION_MAX_PROMPT_CHARS", "16000")
    s = Settings(memory_dir=tmp_path)
    assert s.consolidation_max_prompt_chars == 16000


def test_consolidation_max_prompt_chars_rejects_below_floor(tmp_path, monkeypatch):
    monkeypatch.setenv("ORMAH_CONSOLIDATION_MAX_PROMPT_CHARS", "3999")
    with pytest.raises(ValueError, match="consolidation_max_prompt_chars must be >= 4000"):
        Settings(memory_dir=tmp_path)
```

- [ ] **Step 2: Run them and verify they fail**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/test_background/test_consolidator.py -k max_prompt_chars -v > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt; cat out.txt
```

Expected: FAIL — `AttributeError: 'Settings' object has no attribute
'consolidation_max_prompt_chars'` on the first two, and no `ValueError` raised on the third.

- [ ] **Step 3: Add the field**

In `src/ormah/config.py`, directly after the line `consolidation_max_cluster_nodes: int = 5`, add:

```python
    # Budget for the WHOLE consolidation prompt, in characters. It governs two things at once:
    # the cluster split (a cluster that does not fit is split, never truncated -- #192) and the
    # Ollama input window the consolidation route pins on its own adapter. They must be the same
    # number: a budget the provider never promised to honor is fiction, and an oversized prompt
    # is then truncated by the Ollama server instead, silently.
    # Sized from measurement (5,923 nodes / 301 real consolidation events): the worst real event
    # builds a 12,961-char prompt and the largest single node is 5,513 chars, so this keeps 1.85x
    # headroom over the worst case observed. At any value >= 16000 none of those 301 events would
    # have been split -- the split is a tail safety net, not the common path.
    consolidation_max_prompt_chars: int = 24000
```

- [ ] **Step 4: Add the validator**

In `src/ormah/config.py`, immediately after the `_consolidation_max_cluster_nodes_range`
validator (it ends with `        return v` before `@field_validator("activation_decay")`), add:

```python
    @field_validator("consolidation_max_prompt_chars")
    @classmethod
    def _consolidation_max_prompt_chars_floor(cls, v: int) -> int:
        # The prompt template alone costs ~2,440 chars. Below 4000 there is no room left for two
        # sources of any useful size, so no cluster could ever be consolidated -- reject the
        # impossible config up front rather than emitting a silent no-op every run.
        if v < 4000:
            raise ValueError(f"consolidation_max_prompt_chars must be >= 4000, got {v}")
        return v
```

- [ ] **Step 5: Document the key in `.env.example`**

`.env.example` has a `# Memory consolidation (requires LLM)` section. The other per-run limits are
not documented there, but this one is: it is the knob an Ollama operator must raise before raising
their server window. Under that section's existing `# ORMAH_CONSOLIDATION_INTERVAL_MINUTES=360`
line, add:

```
# Prompt budget for one consolidation, in characters. Also sets the Ollama input window the
# consolidation route requests (chars/2 + ORMAH_LLM_NUM_PREDICT). A cluster that does not fit is
# split into smaller consolidations — sources are never truncated.
# ORMAH_CONSOLIDATION_MAX_PROMPT_CHARS=24000
```

- [ ] **Step 6: Run the tests and verify they pass**

Same command as Step 2. Expected: 3 passed, `PYTEST_EXIT=0`.

- [ ] **Step 7: Confirm nothing else broke**

```bash
env -u VIRTUAL_ENV -u PYTHONPATH HOME=$(mktemp -d) .venv/bin/python -m pytest \
  tests/ -q -k "config or consolidat" > out.txt 2>&1
echo "PYTEST_EXIT=$?" >> out.txt; tail -20 out.txt
```

Expected: `PYTEST_EXIT=0`.

- [ ] **Step 8: Commit**

```bash
git add src/ormah/config.py .env.example tests/test_background/test_consolidator.py
git commit -m "feat(config): add consolidation_max_prompt_chars (#192)

One number governs both the cluster split budget and the Ollama input window
the consolidation route pins on its adapter. Default 24000 is 1.85x the worst
real consolidation prompt measured over 301 events."
```
