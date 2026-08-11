# Investigação consolidada — ingestão (2026-07-30, tarde)

Doc em **PT-BR** (segue os docs anteriores); código/commits em **English**.

Consolida e **fecha os itens em aberto** de:
`investigation-2026-07-30-cursor-rewind-loop.md` (§9), `handoff-2026-07-28-no-safe-boundary.md`,
`problemas-de-ingestao.md` (+ `verificacao-2026-07-17`), `evaluation-2026-07-13-deep-review.md`.

**Método:** 4 subagents (2× forense/store em Sonnet, 1× auditoria de código em Opus, 1× dedup em
Sonnet), todos READ-ONLY; verificações inline. **Mudança de estado nesta sessão: UMA linha
autorizada** — `ORMAH_LLM_MODEL=gemma3:12b-it-qat` adicionada a `~/.config/ormah/.env` (§3).
Nenhum commit, nenhuma branch, servidor continua **parado**, store intocado.

## TL;DR — o quadro completo

| # | problema | status | seção |
|---|---|---|---|
| 1 | Loop de rewind do cursor (#154) — **5.342 ingests** de F2 no histórico completo, **+3 loopers secundários** | causa raiz confirmada + repro sintético; fix planejado (invariante **+ gate no drain** — só a invariante não basta) | §1 |
| 2 | Manutenção LLM **morta há semanas** (claude -p exited 1 → 404 Ollama) | causa confirmada; **fix de config aplicado** | §3 |
| 3 | Dedup/conflict estagnados desde 08/07; 3.410 proposals pendentes | investigado (§4) | §4 |
| 4 | Dano do loop no store: ~489 nós, 42–85% duplicação semântica | medido; André decidiu **não mexer** | §5 |
| 5 | `min_turns` bypassado no caminho idle (99,5% fatias de 1 turno) | confirmado `session_watcher.py:923` + `:940` | §6 |
| 6 | Fila do Ollama (`-np 1`) = 20–27 s de GAP por chamada | `OLLAMA_NUM_PARALLEL` **suportado** na 0.32.5 (verificado) | §7 |
| 7 | Backlog do watcher: 11 entries, 17,4 MiB pendentes | medido; inclui 1 caso de design (subagent 9,4 MB) | §2 |

## 1. O loop de rewind — números finais e auditoria completa

### Histórico completo (4 logs, 28/07 19:25 → 30/07 08:34; fixtures de pytest excluídos)

- **F2 (`c13fd7d1-….jsonl`): 5.342 ingests, 2.701 recoveries** — os 1.671 do doc da manhã eram só
  o `ormah.log` atual (~31% do total). Distribuição: log.3=2.944, log.1=727, log=1.671.
- **F2 NÃO é o único.** Três loopers secundários, todos no vault Obsidian, janela 29/07 12:37–16:54:
  `96e2a4cd` (97 recoveries), `b2d00516` (74), `8f103f6e` (45). A classe atinge múltiplos arquivos.
- O cursor de F2 está **congelado em 86732** (o offset baixo do ciclo) no state — o server foi
  parado no meio do loop; ao religar sem fix, o loop retoma.
- O caso `rich-doc/05640182` (36 rewinds, 16-17/07) já saiu da janela retida pelos logs.

### Auditoria dos 4 call-sites de `_commit_state` (item aberto da §9 — fechado)

Único escritor do cursor: `session_watcher.py` (verificado; hippocampus tem state separado).

| site | linha (commit) | condição | pode retroceder? |
|---|---|---|---|
| A | `:980`/`:989` | quarentena (`MAX_EXTRACT_FAILURES=3`) | **SIM** — no rewind, `prev_offset` foi zerado em `:879`, o guard `:929` compara contra 0 |
| B | `:1005`/`:1009` | falha de extração não capada | **SIM — pior caso**: no rewind grava `end_offset=0` |
| C | `:1073`/`:1084` | ingest OK (caminho feliz) | **SIM — é o loop do #154** |
| D | `:1340`/`:1341` | `_mark_frozen_prefix_consumed` | NÃO — já tem guard monotônico próprio (`:1336`) |

Mutadores de `prev_offset` que alimentam A/B/C: `:858-859` (arquivo encolheu — retrocesso
**legítimo**) e `:879` (`prev_offset = 0` no rewind — **é o que neutraliza o guard**).

**Achado colateral novo:** `carry = existing and prev_offset > 0` (`:1061`) → no rewind a entry é
reconstruída do zero (`:1070`), **apagando `skipped_slices`** — o rastro durável de quarentena do
council-pr C1 é destruído a cada volta do loop.

### O achado que muda o fix: a invariante sozinha NÃO resolve o custo

Medido por execução (repro no scratchpad): monotonicidade pura em `_commit_state` converte o loop
de período 7 em **loop de período 1 com 1 chamada LLM por tick** — porque `ingest_conversation`
(`:1012`) roda **antes** do commit (`:1084`). A rejeição do commit é paga depois do custo. Os 98%
de custo do #154 permaneceriam. O fix precisa de **duas peças**:

1. **Gate de progresso no drain** (`:871-895`): recusar o rewind quando o drain capado não
   ultrapassa o cursor original (`drain.safe_end <= original_offset`) — hoje o gate de progresso
   (`:886`) olha só o probe não-capado. Mata o custo na origem.
2. **Invariante monotônica em `_commit_state`** como backstop estrutural, com ressalvas
   obrigatórias (auditadas, não teóricas):
   - escape para **arquivo encolhido** (`:858-859`) — senão o cursor fica acima do EOF e o
     `reconcile` (`:1390`) descarta o arquivo **para sempre**;
   - escape para **backfill** (item 5 do plano do slice 3);
   - em B (`:1009`), rejeitar **só o campo `end_offset`**, nunca a entry inteira — senão
     `extract_fail_count` não persiste e uma fatia tóxica pina o cursor (reabre o bug do
     council-pr I1).

### Repro sintético (candidato a teste de regressão)

`scratchpad/fixture_rewind_loop.jsonl` (10.073 B) + `repro_rewind_loop.py`: com
`flush_bytes=2000`, cursor cíclico de período 7, retrocesso de 8.034 B nos ticks 8/15/22, nunca
alcança EOF. Estrutura idêntica ao F2 real (probe=EOF autoriza, drain capado grava menor).

### Mistério da `feat/relevance-gate` (item aberto da §9 — fechado)

A branch **é um ancestral de `local-main`** (64 commits atrás, diff três-pontos vazio) — pré
ADR-0003: rewind incondicional (`e17818c:…:777-783`, sem `should_rewind`, sem probe). Cada tick
reprocessa `0..86732` e regrava 86732. Não é bug do relevance gate; é o watcher de 21/07.

## 2. Backlog real do watcher (state sweep — item aberto da §9 fechado)

`~/.claude/projects/.session_watcher_state`: 652 entries, **0 órfãs** (todos os arquivos existem),
**0 anômalas** (cursor > tamanho). **11 entries com cursor < tamanho, 17,4 MiB pendentes** — os 4
loopers estão entre elas. Caso de design: o maior pendente (9,4 MB) é um transcript de
`subagents/` que o skip pós-08/07 **nunca mais vai drenar** (fica "pendente" para sempre no
state). O state **não tem campos de disposição** (dead_letter/parked/frozen não existem lá — schema
real: `hash, end_offset, last_ingested, node_ids, session_id, source, space, user_turns,
signals_recorded`); os conceitos do ADR-0004 vivem no spool/job, não aqui.

## 3. Os 404 do Ollama — confirmado e corrigido (item aberto da §9 fechado)

**Causa (reproduzida byte-a-byte):** `ORMAH_LLM_PROVIDER=ollama` **sem** `ORMAH_LLM_MODEL` no
`.env` → default `config.py:56` = `claude-haiku-4-5-20251001` → Ollama responde
`{"error":"model 'claude-haiku-4-5-20251001' not found"}`. Caller: `pair_batch` (feedback judge,
K=10) — mas atinge **todos** os consumidores de `llm_generate`: auto_linker, duplicate_merger,
conflict_detector, consolidator, feedback judge (`session_watcher.py:272`). Ingest não era afetado
(`ingest_llm_model` correto; `llm_client.py:102-103`). No `serve-headless.log`, mesma janela:
487× 200 OK (ingest, 17–30 s) + 143× 404 (pair_batch, ~200 µs).

**Fix aplicado (autorizado):** `ORMAH_LLM_MODEL=gemma3:12b-it-qat` no `~/.config/ormah/.env:11`.
Vale no próximo start do server.

**Gap estrutural (para o plano):** `config.py:416-419` valida `ingest_llm_model` obrigatório
quando `ingest_llm_provider` é sobrescrito; **não existe validador equivalente** para
`llm_model`×`llm_provider` — a combinação inválida passa em silêncio.

**O restart das 05:22:** disputa de porta entre o app GUI do cask (subiu 05:07, SIGTERM 05:21:42)
e o LaunchAgent manual `com.user.ollama-serve.plist`. Não houve troca formula↔cask (formula nunca
instalada; `/opt/homebrew/bin/ollama` é symlink do app). `gemma3:4b` foi removido em decisão
antiga, não hoje.

**Contexto:** a manutenção já estava morta ANTES, via `claude -p exited 1` (1.973 falhas só em
29/07 12:57→18:51). Ou seja: **o pipeline de manutenção não julga um par há semanas.**

## 4. Dedup/conflict "estagnados" — investigado: SEM perda permanente

Fatos medidos no DB (ro): `duplicate_checked` (103 linhas) e `conflict_checked` (693) sem escrita
desde **2026-07-08 ~21:00**, watermarks quase em dia (`duplicate=775768`, `conflict=792049` vs
`node_seq_next=793324`); **3.410 proposals, todas `merge`+`pending`, zero resolvidas**;
`merge_history` 509 aplicados (último 29/07 15:05); nenhuma proposal/merge toca os 489 nós do
loop; auto_linker ativo (465/489 nós do loop com `related_to`, zero `duplicate`/`contradicts`).

**Veredito (código auditado com file:line):**

1. **Falha de LLM NÃO fura o watermark.** Par não julgado → `failed_seed_seqs`
   (`duplicate_merger.py:388-390`); o watermark avança por **prefixo contíguo** e para no primeiro
   seed falho (`duplicate_merger.py:525-532`; idêntico em `conflict_detector.py:436-443`). Com o
   LLM 100% morto, ele simplesmente **para de avançar** — os ~17,5k seqs de gap são exatamente o
   backlog acumulado desde a quebra, e serão **re-selecionados** (`seq > watermark`). Há teste de
   regressão dedicado (`test_conflict_detector.py:616`).
2. **A estagnação das tabelas `*_checked` é intencional**, não bug: o PR #81 (merge `d357892`,
   15/07) trocou o bookkeeping por-par pelo seq-watermark; no HEAD atual o único
   `INSERT INTO duplicate_checked` é a **rejeição humana** de proposal (`routes_agent.py:409`), e
   não existe INSERT em `conflict_checked`. Residual não explicado: as últimas linhas são de
   08/07, uma semana ANTES do merge — [não verificado], exigiria o log daquela semana.
3. **Proposals são human-in-the-loop por design**: `GET /proposals` + `POST /proposals/{id}`
   (`routes_agent.py:329/:369`, MCP `resolve_proposal`). Nenhum job auto-resolve `merge`.
   Duplicatas de alta confiança (≥ `auto_merge_threshold`) fazem auto-merge ANTES de virar
   proposal (`duplicate_merger.py:414-421`) — o que está na fila é, por construção, o caso
   ambíguo aguardando decisão que nunca veio.
4. **Com o LLM consertado (§3), o dedup retoma do ponto certo — veredito (a), nada perdido.**
   Risco residual é **vazão**, não corretude: 500 seeds/run × 1 run/dia (sleep-cycle) ⇒ ~35 dias
   para drenar 17,5k, e só se a chegada parar — a mesma aritmética chegada>dreno do #81.

## 5. Dano do loop no store (item aberto da §9 fechado — duplicação semântica medida)

- **Sem proveniência nó→transcript**: a tabela `nodes` não tem coluna de sessão. Atribuição só por
  proxy (space + janela + tags `auto-ingested`+`session-transcript`) → **489 nós** na janela
  (29/07 12:57 → 30/07 08:34 BRT), todos `tier=working`, `source=agent:claude_code`.
- **Duplicação semântica: 42%** (clustering Jaccard conservador por título) **a 85%** (por tópico
  drive-watch/stubs/curation). Amostra manual n=20: ~55% lixo (trivia/estado transitório), e dos
  "legítimos" 8/9 são a MESMA decisão parafraseada — **~5% de sinal não-redundante**.
- Top cluster: 53 nós sobre "Drive Watch"; outro com 24 ("Prioritized stubs for curation")…
- **Não existe critério SQL de limpeza sem falso positivo**: o melhor critério pega os 489 mas
  inclui **~71 nós (14,5%) de sessões legítimas concorrentes** (deck Davos, Grupo SC, atas).
  **Decisão do André: não mexer no store.** Fica registrado como motivação para uma coluna de
  proveniência (nó→transcript/sessão) no schema.

## 6. `min_turns` bypassado no idle — confirmado

`session_watcher.py:923`: `if not is_idle and not force_flush and payload_users < min_turns:` —
arquivo ocioso (age > 600 s, `:917`) ignora o gate. Reforço em `:940` (`_should_flush = is_idle
or capped`, `:798`). Juntos explicam os 99,5% de fatias de 1 turno (aproveitamento 22,8% vs 100%
em fatias de 3-4 turnos).

## 7. Fila do Ollama

`OLLAMA_NUM_PARALLEL` **existe na 0.32.5** (verificado via `ollama serve --help`). Setar no
LaunchAgent `com.user.ollama-serve.plist` (EnvironmentVariables) elimina a fila do `-np 1` que
causava o GAP de 20–27 s/chamada. Recomendação, não aplicada.

## Não verificado / residual

- Nenhuma suíte pytest foi executada nesta sessão (fora de escopo por decisão; o repro exercita
  `parse_transcript`/`should_rewind` reais mas **replica** `_ingest_session` em vez de chamá-lo —
  os call-sites A/B/D não foram validados por execução, só por leitura Opus).
- A consequência de `skipped_slices` apagado no rewind foi derivada por leitura, não medida no
  state real.
- Duplicação semântica dos loopers secundários (96e2a4cd etc.) não foi amostrada — só F2.
- `serve-headless.log` (903 MB) só foi processado na janela dos 404; outros dias não contados.
