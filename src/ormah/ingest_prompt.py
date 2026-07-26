"""The ingest extraction prompt contract: rules, response schema, rendered template.

A LEAF module by design. ``config.py`` constructs a module-level ``Settings()`` at import time, and
its ollama capacity validator needs the size of the rendered prompt. Reaching that number through
``engine/memory_engine.py`` (which imports ``ormah.config``) made validation time part of import
time and produced a genuine circular import: whether the process survived depended on which module
was imported first. Keeping the template here gives the validator and the extractor ONE source of
truth with no cycle.

Its ONLY ormah import is ``ormah.models.node`` (stdlib + pydantic; ``ormah/models/__init__.py`` is
empty). Do not add an import here that transitively reaches ``ormah.config`` -- that restores the
cycle, and ``test_computing_the_prompt_overhead_never_loads_the_engine_or_config`` will say so.
"""

from __future__ import annotations

from ormah.models.node import NodeType


_INGEST_LLM_RULES = """\
## Quality bar

A good memory is **specific, self-contained, and searchable**. It must:
1. Be understood in complete isolation — no "this", "the above", "as discussed"
2. Include concrete details — names, versions, paths, specific choices, numbers
3. Have a title that distinguishes it from related memories (titles are weighted 10x in search)

BAD: "The project uses SQLite for storage"
GOOD: "Chose SQLite over PostgreSQL for ormah's index because the system is local-first and single-user. The DB stores FTS5 indexes, vector embeddings (via sqlite-vec), and node metadata. File-based markdown is the source of truth; SQLite is a derived index."

BAD: "User prefers dark mode"
GOOD: "User prefers dark mode in all editors and terminals. Specifically mentioned VS Code, iTerm2, and Obsidian."

BAD: "Discussed authentication approach"
GOOD: "Decided to use JWT tokens over session cookies for the API because the client is a CLI tool, not a browser. Tokens are stored in ~/.config/app/auth.json with 7-day expiry."

## What to extract (priority order)

1. **Decisions with reasoning** (type: "decision") — The most valuable memory type. What was chosen, what was rejected, and WHY. The reasoning prevents re-litigating the same decision in future sessions. Always name the alternatives.

2. **User corrections and "no" moments** (type: "preference" or "decision") — When the user pushed back, said "no", or corrected the AI. These reveal unstated preferences. Set about_self=true.

3. **Preferences and opinions** (type: "preference") — Must be specific. "Prefers map/filter over for loops, avoids classes unless modeling state" not "prefers functional style". Set about_self=true — this marks the memory as user-related for recall and whisper.

4. **Architecture and design patterns** (type: "fact" or "concept") — HOW the system works, not just what it does. Include the constraints that shaped the design. Name specific files, modules, patterns.

5. **Procedures discovered through effort** (type: "procedure") — Steps that weren't obvious. Include the exact commands, flags, paths. These save future sessions from re-discovering the same process.

6. **Goals and strategic direction** (type: "goal") — What the user is trying to achieve long-term. Include context on why this goal matters to them.

7. **Surprising findings** (type: "observation") — Bugs with non-obvious causes, unexpected library behavior, performance discoveries. These are high-value because they prevent repeat mistakes.

8. **Personal identity facts** (type: "person" or "fact") — Name, role, email, location, team. Set about_self=true — person nodes get promoted to core tier.

## What NOT to extract

- Vague summaries that could apply to any project
- Generic technical knowledge the AI already has
- Intermediate debugging steps that led nowhere
- Routine code changes with no decision or learning behind them
- Information already captured more specifically by another memory in your output
- The same fact restated at different granularities — pick the most specific version
- **Code read-throughs where the user is just tracing existing logic** — if the user reads code and the AI confirms what it says, this information is already in the codebase. Only extract things that go BEYOND what's already in the code: decisions, preferences, surprises, corrections. "I traced through the pipeline and it works as expected" is NOT worth storing.

## Deduplication within your output

Before adding a memory to your list, check if you've already extracted something that covers the same ground. Prefer fewer, richer memories over many thin ones. If a decision memory already explains the architecture, you don't need a separate architecture fact.

## Provenance (required)

Label every memory on ONE axis: did the session PRODUCE it, or did it merely PASS THROUGH?

- **material** — restates input that passed *through* the session: third-party API/SDK facts, a version string, generic technical knowledge, a read-through of someone else's code — content that would be true and findable in docs/code regardless of this conversation.
- **product** — something the session itself *produced*: a decision, a user correction, a discovered bug, a complaint, an outcome — even when it is *about* an external tool.

When uncertain, label **product**. A dropped Material re-extracts later (it recurs); a dropped Product often happens once and is lost.

## Output format

For each memory:
- "content": 2-5 sentences. Be specific — include names, versions, paths, flags. For decisions, always state what was rejected and why. Write as if explaining to a knowledgeable colleague who has no context about this conversation.
- "type": One of: fact, decision, preference, event, person, project, concept, procedure, goal, observation. Choose carefully — type affects how the memory is weighted, stored, and retrieved.
- "title": 5-12 words. Must be specific enough to distinguish this memory from related ones. The title is heavily weighted in search — make it count. BAD: "Database choice". GOOD: "Chose SQLite over Postgres for local-first single-user index".
- "tags": 2-5 tags. Include the project name if mentioned, technology names, and domain terms. Tags are indexed for search.
- "about_self": true if about the user's identity, preferences, or personal information. This triggers special handling: person types get promoted to core memory; user-related memories are marked for recall and whisper.
- "confidence": 0.0-1.0. Use 1.0 for explicit statements by the user. Use 0.7-0.9 for clear but unstated implications. Use 0.4-0.6 for inferences you're less sure about. Low confidence memories are penalized in search ranking, so be honest.
- "provenance": "material" or "product" — see the Provenance rule above. This is required.

Return: {{"memories": [...]}}
Return {{"memories": []}} if nothing worth remembering was discussed.
"""

_INGEST_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": [t.value for t in NodeType],
                    },
                    "title": {"type": ["string", "null"]},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "about_self": {"type": "boolean"},
                    "confidence": {"type": "number"},
                    "provenance": {"type": "string", "enum": ["material", "product"]},
                },
                "required": [
                    "content", "type", "title", "tags", "about_self", "confidence",
                    "provenance",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["memories"],
    "additionalProperties": False,
}


_INGEST_LLM_PROMPT = """\
You are a memory curator for a persistent knowledge graph. Read the conversation below and extract memories valuable in future sessions.

<conversation>
{conversation}
</conversation>

Now extract the memories, following these rules:
""" + _INGEST_LLM_RULES
