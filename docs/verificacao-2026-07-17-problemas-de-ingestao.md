# Verificação independente — problemas-de-ingestao.md

Data: 2026-07-17. Método: 7 agentes paralelos, todos read-only (DB via `mode=ro`, nenhum estado
alterado), cada um re-derivando os números por rota independente do doc original. Evidência bruta
nos transcripts dos agentes; aqui, o veredito consolidado.

Fontes primárias usadas: `~/.local/share/ormah/memory/index.db` (ro), `/tmp/ormah-dev.err`
(log vivo do launchd, 39 MB — **não** o `ormah.log`, que está contaminado por pytest),
`~/.cache/ormah/whisper-cursors.json`, `~/.claude/projects/.session_watcher_state`,
código local (`local-main`) + `upstream/main` @ `4f66abc` (fetch de hoje), doc oficial de hooks
do Claude Code, issues do `r-spade/ormah` via `gh`.

---

## Veredito por afirmação do doc

| Afirmação do doc | Veredito | O que a verificação achou |
| --- | --- | --- |
| **P0 — duas vias independentes de ingestão** | **CONFIRMA** | Contabilidade por `source` fecha em zero resíduo: watcher 5.677 + hook 4.919 + consolidator 234 + MCP 103 + codex 25 = 10.958 nós/7d. Correção: o hook é **45% do volume semanal**, não os ~21% do dia 17. |
| **P0 — dupla ingestão hook×watcher (aberto no doc)** | **RESPONDIDO: real, mas modesto** | Teste de embedding nas 27 sessões sobrepostas: 312 nós `whisper-out` com gêmeo ≥0,85; estimativa honesta **~250–500 nós (2,5–5% da janela)** descontada a recorrência natural. O custo dominante da via dupla é **extração paga 2×**, não duplicata em massa — as duas extrações dos mesmos bytes produzem memórias majoritariamente diferentes. |
| **P0 — motor de duplicação do `SessionEnd`** | **CONFIRMA o motor, corrige o mecanismo** | Observado no log: o mesmo payload de 1.140.586 chars foi **postado 5×** (15–16/07), 2 extrações completaram server-side (1.199 s e 1.293 s), e o cursor da sessão (`6206db7d`) está **congelado em 77,7% até hoje**. Mas o assassino provado é o **timeout do httpx do próprio hook: 135 s** (`max(60, 120+15)`) contra extrações de p50 118 s / p90 906 s / max 33,6 min — **63% das ingestões estouram 60 s; 28% estouram 300 s**. O harness nem precisa matar o hook: o cliente desiste sozinho ~18 min antes da resposta. |
| **P0 — o `timeout: 300` do manifest é honrado?** | **RESPONDIDO: NÃO, e é pior** | Doc oficial: *"Timeouts set on plugin-provided hooks don't raise the budget"* — o budget do `SessionEnd` fica em **1,5 s default** (sobe até 60 s só via settings do usuário, ou via `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS`). O `timeout: 300` do plugin é inócuo. A doc também não garante `SessionEnd` em crash. Morte pelo harness segue não observada diretamente (o hook não loga nada — `stdout/stderr=DEVNULL`); irrelevante na prática, o httpx mata antes. |
| **P1 — sem gate de relevância** | **CONFIRMA (com nuance)** | Não há score de saliência, budget por sessão, nem filtro de relevância. Nuance: **existe** um filtro pós-LLM — dedup semântico top-1 ≥0,85 (`_is_duplicate_memory`) — e um `ingest_min_confidence` que existe mas está em **0.0 = desligado**. Números re-derivados: 2.792 nós hoje (UTC), 461 (16,5%) com Claude/API/SDK no título, 395 no space `rich-doc`; ~29 nós de meta-narração ("The conversation…"); **2,56 nós/turno exato**. Upstream idêntico (prompt + ausência de gate confirmados em `upstream/main`). |
| **P1b — throttle: modelo de ~12 fatias/hora** | **REFUTA o modelo, confirma as constantes** | As 4 constantes e o budget-break existem como descrito (fork-only, zero matches upstream). Mas a vazão real medida na madrugada foi **~38,5 fatias/hora** (231 fatias em 00h–06h), ~3× o modelo do doc. O gargalo existe, mas a conta de dimensionamento precisa ser refeita sobre o número medido. Duração por chamada LLM não é logada (segue não confirmada). |
| **P2 — duplicação por chunk isolado** | **CONFIRMA — e é maior** | Loop com prompt isolado por chunk confirmado no código. Cluster "quota is shared": **16 nós** (doc dizia 5). Mais 13 clusters por shingle nos últimos 3 dias (até 81 títulos no mesmo tema). |
| **P2 — "duplicate_merger processou 0 pares/24h"** | **REFUTA (artefato de medição)** | O merger **rodou 4×** nas últimas ~24h (~1.900 pares avaliados, 46 merges em `merge_history`), disparado pelo sleep-cycle (`run-all`) apesar do `=99999` no `.env`. O "0" veio da tabela `duplicate_checked`, **estagnada desde 08/07** — possível bug de bookkeeping separado, não investigado. |
| **P3 — churn de `seq` via `auto_cluster` impede o dreno** | **REFUTA a causa (código confirmado)** | A cadeia código existe elo a elo (space no fingerprint, bump condicional, fila por seq), **mas** o `auto_cluster` toca **1–3 nós/hora** e é one-shot por nó (pool atual: 103 nós). Dos 3.000 seqs mais recentes, **99,3% são nós novos**. O backlog de 70% (14.904 nós) é **chegada (~2.000/dia) > dreno (cap 100 nós/run × 12 runs = 1.200/dia)**, com `cap_hit: False` — o job usa ~5 min de cada janela de 2h. O "37 requeues/nó" é artefato de contador cumulativo (full rebuilds + era pré-#126). Fix do **#126 observado funcionando ao vivo**: 11.697 reescritas do importance scorer sem bump de seq; 0 fingerprints divergentes nos 21.303 nós. |
| **Madrugada: 990 nós rich-doc = catch-up** | **CONFIRMA + resolve os 269 null** | Os 269 nós `space=(null)` são a mesma origem: `agent:claude_code` (watcher catch-up), memórias pessoais/globais gravadas sem space. Nenhum mecanismo novo. |
| **Procedência upstream×fork** | **CONFIRMA 4/5, corrige 1** | Linhas 1, 1b, 2, 3 confirmadas contra `upstream/main` real. **Erro do doc:** "upstream não tem session_watcher" — tem (1.009 linhas, catch-up + watcher); fork-only é a maquinaria de **reconcile**. Manifests de hooks byte-idênticos nas 3 cópias (fork, instalada 0.13.3, upstream). **Nenhuma issue upstream existente** cobre o gate de relevância nem a duplicação do SessionEnd — campo livre. |

---

## Achados NOVOS (não estavam no doc)

### N1 — o maior motor de duplicação é outro: o loop `recovering legacy mid-response cursor`

O `session_watcher` **rebobinou e re-extraiu o mesmo payload de 788.113 chars 36 vezes em 14 h**
(rich-doc `05640182`, 16/07 20:55 → 17/07 10:44, ~a cada 27 min). 28 tentativas completaram,
gravando **~773 memórias** (atribuição aproximada pelo log). O gatilho aparece 26× no log:
`Session watcher recovering legacy mid-response cursor` → rebobina → re-extrai tudo. As duplicatas
com timestamps casando com runs distintos do loop estão no DB (5× "claude code quota is shared"
às 00:25/03:41/06:55/11:43/13:35 UTC). **Isso, e não o SessionEnd, produziu o grosso da rajada
noturna** — e explica boa parte dos clusters do P2. Causa raiz do recovery rebobinar: não
investigada (próximo passo natural).

### N2 — o design síncrono é insustentável por aritmética, não por azar

p50 de `/ingest/conversation` = 118,8 s; pior caso = 29 chunks × 120 s ≈ 58 min. Nenhum timeout
de cliente razoável cobre isso. Enquanto a rota for síncrona e o cursor só avançar com resposta
recebida, **todo delta grande vira re-extração** — por httpx (135 s), por harness (1,5–60 s), ou
por crash. A direção de fix é estrutural: responder rápido (enfileirar) e avançar cursor por
confirmação de job, não de request.

### N3 — menores

- **Consolidator cria nós** (~234/7d, ~2%) — via de criação ausente do doc.
- **288 nós legados de subagente** (watcher ingeriu subagents até ~08/07; skip funciona desde então; hook nunca disparou para subagente — 0/182 cursores).
- **`duplicate_checked` estagnada desde 08/07** enquanto o merger roda — bug de bookkeeping provável.
- **Resíduo de ~50 remoções/dia sem trilha completa** no `audit_log`/`merge_history` [não confirmado — pode ser diferença de query].
- **Logs derivados são arriscados**: `ormah.log` contaminado por pytest (o log confiável é `/tmp/ormah-dev.err`).

---

## O que isso muda na ordem recomendada do doc

1. **P1 (gate de relevância) segue sendo o nº 1** — confirmado, upstream, e a chegada de ~2k/dia é o que afoga o dreno de 1,2k/dia. Cortar chegada resolve backlog sem tocar no auto_linker.
2. **NOVO nº 2: o loop de recovery do watcher (N1)** — é o maior motor de duplicação observado e é um bug concreto, provavelmente com fix pequeno. Investigar a causa do rebobinar antes de qualquer outra coisa em duplicação.
3. **Ingestão assíncrona (N2)** — resolve o motor do hook pela raiz (o item "async: true como o PreCompact" do doc é paliativo: evita segurar a sessão, mas não conserta o cursor que só avança com resposta síncrona).
4. **P3 (churn de seq) cai da lista de causas** — não abrir issue de churn; se quiser drenar mais rápido, o knob é o cap de 100 nós/run (o job usa 5 min de cada 2 h). Reavaliar só depois do gate.
5. **P2 (chunks)** — mantém posição; a extração holística proposta pelo André segue válida como direção, depois do gate.

### Issues a abrir — ajustes sobre a lista do doc

- Upstream #1 (gate de relevância): **manter**, nenhuma issue existente cobre; evidência re-verificada.
- Upstream #2 (SessionEnd): **reformular** — o problema não é só "harness mata o hook": o `timeout: 300` do plugin é inócuo por design documentado, e o httpx do próprio hook (135 s) já dispara o motor. Fix real = ingestão assíncrona/job, não só `async: true`.
- Upstream #3 (truncate 100 K): **manter** (confirmado byte a byte no upstream).
- Fork #1 (churn de seq): **derrubar** — refutado como causa.
- Fork novo: **loop `recovering legacy mid-response cursor`** (N1) + **`duplicate_checked` estagnada** (N3).

---

## Registro de confiança desta verificação

**Verificado (evidência bruta nos relatórios dos agentes):** todos os números das tabelas acima,
os 5 re-posts do payload de 1,1 MB, as 36 re-extrações do loop, as durações de ingest (203
conclusões logadas), o guard do #126 ao vivo, a contabilidade de volume por `source`, os manifests
idênticos, o texto da doc oficial de hooks, a ausência de issues upstream.

**Inferido:** identidade sessão↔payload do caso `6206db7d` (mtime casando ao segundo, sem
session_id no log); a soma ~773 memórias do loop (interleaving pode desviar unidades); atribuição
dos runs do merger ao sleep-cycle.

**Segue não verificado:** morte do hook pelo harness em ato (irrelevante na prática — httpx mata
antes; só um SessionEnd cronometrado decidiria); causa raiz do recovery rebobinar (N1); causa da
`duplicate_checked` estagnada; duração real por chamada `claude -p` (não logada); o resíduo de
~50 remoções/dia.
