# Plan delta — r-spade alignment (issue #73)

Registro das mudanças acordadas na thread https://github.com/r-spade/ormah/issues/73
(comentário do owner + resposta postada 2026-07-02). **Este arquivo é a base pra revisar o
plano** — não reescreve as tasks, lista o que ajustar em cada uma.

## Duas decisões que mudam a premissa

1. **LLM local NÃO sai.** `claude_cli` vira *mais uma opção* ao lado de local (`ollama`) e API
   (`litellm`), opt-in, "custando menos" em resource churn. Isso derruba o design original
   ("gemma cortado de vez, sem fallback"). Nenhum caminho existente é removido — só se acrescenta
   um provider e um override de ingestão.

2. **Recursão de transcript resolve-se na ORIGEM, por-adapter — não com guards no watcher.**
   Spike (2026-07-02) confirmou: `claude -p --no-session-persistence` produz ZERO `.jsonl` novo
   sob `~/.claude` (mtime na árvore toda), envelope JSON idêntico. Sem a flag escreve
   `~/.claude/projects/<encoded-cwd>/<session_id>.jsonl` (macOS: realpath, `/tmp` → `/private/tmp`).

## Achado que reenquadra a Task 04

O session-watcher vigia **DOIS** stores de CLI, não um:
- `~/.claude/projects` (default) — `session_watcher.py:30`
- `~/.codex/sessions` — `session_watcher.py:31` (`_CODEX_SESSION_WATCHER_DIR`, adicionado em `:669`)

Logo a recursão **não é Claude-específica**: qualquer extractor cujo store é ingerido recorre.
- Claude → `--no-session-persistence`
- Codex → `--ephemeral` ("run without persisting session files to disk")
- Cursor → não é vigiado hoje; a mesma regra por-adapter aplica no dia que um cursor-watch existir.

Regra de arquitetura (ponto 7 do r-spade): **watcher permanece alheio ao provider**; cada adapter
suprime a própria persistência com a própria flag.

## Seam genérico exigido pelo owner

- `ingest_llm_provider` + **`ingest_llm_model`** (este ainda não existe — ADICIONAR).
- Ambos vazios → cai em `llm_provider`/`llm_model` (comportamento atual preservado).
- Provider de ingest sobrescrito → **exigir o model explicitamente** (não herdar nome de model
  entre providers incompatíveis).
- `claude_cli` inteiro atrás de `LLMAdapter`; subprocess/auth/env/parsing só dentro do adapter.
- Código compartilhado de ingest só resolve provider/model e chama `generate()`.

## Mudanças por task

- **02-claude-cli-adapter** — adicionar `--no-session-persistence` ao `argv`. **REMOVER**
  `_purge_worker_transcripts` e o param `workdir` (ficam desnecessários). O `cwd` pode ser um
  tempdir efêmero qualquer, sem encoding-de-path pra prever transcript.
- **03-provider-wiring-config** — adicionar `ingest_llm_model`; validar "model obrigatório quando
  provider sobrescrito"; remover os campos que só existiam pra sustentar os guards
  (`claude_cli_workdir` sob temp). Manter `ingest_llm_provider` como o ÚNICO feature-override.
- **04-recursion-guard-exclusion** — **em grande parte DELETADA**. Some a maquinaria
  `_is_extractor_transcript` em `session_watcher.py`, `cli_adapter.py`, `setup.py`. Substituída por:
  "cada adapter suprime persistência via sua flag". Reduzir esta task a um teste que prova que o
  extractor não gera transcript ingerível.
- **05-cursor-unification** — reavaliar à luz de "cursor não é vigiado hoje". Não há recursão de
  cursor a resolver agora; só documentar a regra por-adapter pro futuro cursor-watch.

## Respostas de design postadas (contexto, não exigem código agora)

- **Q1 — `LLMAdapter` suficiente pros 3 shapes?** Sim, já provado: `generate(prompt)->str|None`
  implementado por Ollama (local), LiteLLM (API), ClaudeCli (subprocess). Ressalvas:
  (a) `response_format` honrado desigual — `claude_cli` ignora, Codex tem `--output-schema`;
  (b) acoplamento de config vive na factory `get_adapter`, não na interface — cada provider CLI
  adiciona um cluster `<provider>_*` + um branch. É aí que pressiona, não no `generate()`.
- **Q2 — overrides escalam ou provider profiles?** Ship overrides agora (1 workload, 1 provider).
  Migrar pra "provider profiles" (`{kind, model, timeout, …}` selecionados por nome) no **2º
  workload que sobrescreve** OU **3º cluster de campos provider-específico**, o que vier primeiro.

## Pendências antes do PR

- [ ] Revisar o plano contra este delta (você).
- [ ] Branch `feat/ingest-claude-cli-extraction`: adotar a flag, remover a maquinaria de exclusão,
      adicionar `ingest_llm_model`, alinhar ao seam genérico.
- [ ] Diff local-main vs origin/main antes de qualquer dev (regra core).
