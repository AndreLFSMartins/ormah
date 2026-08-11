# Problemas de ingestão

> **Revisado em 2026-07-17 após verificação independente por 7 agentes** — ver
> `docs/verificacao-2026-07-17-problemas-de-ingestao.md` para o veredito consolidado e os
> relatórios brutos dos agentes. Convenção adotada neste doc: onde um agente re-mediu um número,
> o valor re-medido substitui o original e o texto diz "remedido"; onde não houve remedição, o
> número original da manhã é mantido, marcado sem alteração. **Os números de store/backlog são
> snapshots** — o store é vivo e cresce durante a própria leitura deste documento.

Investigação de 2026-07-17. Store: **21.303 nós** (remedido ~12:30-12:35 UTC/−03 pela verificação;
a contagem original da manhã era 21.118). Todos os números vêm de query no
`~/.local/share/ormah/memory/index.db` ou dos stats logados pelo `auto_linker`, exceto onde
marcado como inferido.

**Fonte de log confiável:** `/tmp/ormah-dev.err` (log vivo do plist `com.ormah.server.dev`,
`StandardErrorPath`, 39 MB, 07-10→hoje). **Não usar** `~/.local/share/ormah/logs/ormah.log` (nem
`.1`/`.2`/`.3`) como métrica do serviço vivo: está contaminado por execuções de pytest (41 linhas
"Session watcher started on …pytest…", 53/65 "scheduler started", requests
`POST http://test/ingest/conversation`) — a contaminação foi confirmada, o DB em si está limpo.

---

## Resumo

Quatro achados independentes, em ordem de gravidade (revisado — o Problema 3 caiu de posição
depois de ser refutado como causa do backlog):

1. **Não existe julgamento de relevância na ingestão.** Existe um prompt e um filtro de
   duplicata quase-idêntica, mas nenhum gate de saliência. O que o LLM devolver e não for uma
   quase-cópia é armazenado. 16,5% dos nós de hoje violam explicitamente uma regra do próprio
   prompt.
2. **A ingestão por chunks duplica memórias**, porque cada chunk é extraído sem enxergar os
   outros.
3. **O loop `recovering legacy mid-response cursor` do `session_watcher` é o maior motor de
   duplicação observado** — re-extraiu o mesmo payload 36 vezes em 14 horas (achado novo desta
   verificação, [Problema 2b](#problema-2b--o-loop-de-recovery-do-session_watcher-maior-motor-de-duplicação-observado)).
4. **O backlog do `auto_linker` (70% do store) não é causado por churn de `seq`.** É investigado a
   fundo em [Problema 3](#problema-3--o-churn-de-seq-refutado-como-causa-do-backlog) e refutado
   como causa: a causa real é chegada (~2.000 nós/dia) maior que dreno (cap de 1.200 nós/dia). O
   `auto_cluster`, suspeito original, toca só 1–3 nós/hora.

---

## Problema 0 — existem DUAS vias de ingestão, com cursores independentes

Descoberto em 2026-07-17 depois de o André apontar que "o watcher acontece de qualquer forma em
outra parte do código". Ele estava certo.

| via | gatilho | cursor | tag |
| --- | --- | --- | --- |
| **hook do plugin** | `PreCompact` + `SessionEnd` → `ormah whisper store` → `POST /ingest/conversation` | `~/.cache/ormah/whisper-cursors.json` | `whisper-out` |
| **session_watcher** | watchdog + reconcile a cada 5 min | `~/.claude/projects/.session_watcher_state` | — |

**As duas são independentes.** Não se conhecem, não coordenam cursor, e leem os mesmos arquivos.
O `cmd_whisper_store` (`adapters/cli_adapter.py:423`) tem o seu próprio
`_load_cursors()`/`_save_cursors()` apontando para `~/.cache/ormah/`, e checa
`if start_offset >= path.stat().st_size: sys.exit(0)` contra **esse** cursor — que nada sabe do
cursor do watcher.

Medido em 17/07: **560 dos 2.683 nós (21%) carregam `whisper-out`** (via hook); os outros ~79%
vieram do watcher. **27 sessões aparecem nos dois cursores.** Em `ef8d70a3-…`, os dois estão no
offset **537.567 — idêntico**: as duas vias consumiram os mesmos bytes.

**Correção de ênfase (Agente 6): essa proporção vale só para o dia 17/07.** Contabilidade por
`source` na semana mostra outra distribuição — em 14/07 o hook fez **1.258 posts contra 636 do
watcher**. **Na semana, o hook é ~45% do volume**, não um resíduo de 21%. O 21%/79% do dia 17 é um
snapshot de um dia específico, não a proporção estrutural das duas vias (ver
[Contabilidade de volume](#contabilidade-de-volume--de-onde-vêm-os-nós-7-dias)).

**Consequência agora medida (Agente 3).** Título exato só achava 8 pares — teste ruim, porque o
LLM reformula a cada extração. O teste certo, feito na verificação: similaridade de embedding
(cosine, modelo bge-m3 assumido — **[não confirmado]** qual modelo gerou os vetores em produção)
entre os 4.220 nós `whisper-out` e os 4.737 nós do watcher nas 27 sessões sobrepostas (8.957
embeddings, ~3,7 milhões de pares candidatos). Resultado: **312 nós `whisper-out` (7,4% da janela)
têm um gêmeo ≥0,85** no watcher (14 ≥0,90, dos quais 10 já arquivados). Um controle contra 10.269
nós do watcher **fora** da janela sobreposta (onde dupla ingestão por byte é impossível) achou 78
matches ≥0,85 — ou seja, **~25% dos matches ≥0,85 são recorrência temática normal, não dupla
ingestão**. Estimativa honesta: **~250–500 nós (2,5–5% dos 9.244 nós da janela)** são produto de
dupla ingestão.

**Achado contraintuitivo:** mesmo com 100% de sobreposição de bytes, as duas vias produzem
memórias majoritariamente *diferentes* do mesmo transcript — só ~7% dos nós do hook acham gêmeo.
O custo dominante da dupla via **não é** duplicata em massa — é **pagar a extração em LLM duas
vezes**. Confiança do Agente 3 nesta estimativa: média nos pares individuais, baixa-média no total
(sem atribuição de sessão real no schema; threshold escolhido; merges já feitos ficam invisíveis
ao teste).

### Como cada via fatia (são diferentes)

| | **hook** | **session_watcher** |
| --- | --- | --- |
| o que envia | **tudo de uma vez** — todo o delta desde o cursor, num único POST | **fatias de 60 KB** (`flush_bytes`), um POST por fatia |
| onde fatia | **no servidor**, dentro de `_extract_memories_llm` | **no cliente**, antes de enviar |
| tamanho do chunk | 40 K (`ingest_chunk_chars`) | 40 K (mesmo extrator) |

**O hook NÃO fatia — ele despeja.** `cmd_whisper_store` monta
`body = {"content": result.safe_conversation}` e faz **um** `POST /ingest/conversation`
(`cli_adapter.py:480-487`). Se a sessão cresceu 1,4 MB desde o último `SessionEnd`, ele posta 1,4 MB
inteiros. O fatiamento acontece só depois, no servidor.

As duas vias convergem no **mesmo** `_extract_memories_llm`, logo **as duas sofrem a duplicação por
chunk isolado** (Problema 2).

**Ponto positivo do fork:** `_split_for_extraction` (`memory_engine.py:82`) **não trunca** — divide
em fronteira de linha e, para um turno gigante, quebra em pedaços de `hard_cap` "instead of
truncating, so every character is still extracted". Upstream faz
`content[:ingest_max_content_chars]` — **trunca em 100 K e perde o resto em silêncio**. Numa sessão
grande, o upstream descarta a maior parte e o cursor avança como se tivesse extraído tudo.

### O que é `whisper store` e `POST /ingest/conversation`

**`ormah whisper store`** (`cmd_whisper_store`, `cli_adapter.py:423`) é o handler dos hooks
`PreCompact`/`SessionEnd`. Sequência:

1. lê o JSON do hook no stdin → `transcript_path`, `cwd`, `session_id`
2. carrega o cursor de `~/.cache/ormah/whisper-cursors.json`; sai se `start_offset >= st_size`
3. `parse_transcript(path, start_offset)` → separa o payload **"safe"** (conteúdo provado completo
   por um `stop_reason` terminal ou por um turno de usuário seguinte) do que ainda está em voo
4. sai se `safe_user_turn_count < whisper_out_min_turns` (**= 3**)
5. `POST /ingest/conversation` com `extra_tags=whisper-out` e `default_space` derivado do `cwd`
6. **só avança o cursor se a resposta for `{"status": "processed"}`**

**`POST /ingest/conversation`** (`api/routes_ingest.py:19`) é a rota de extração server-side:
`engine.ingest_conversation(content=…)` → `_extract_memories_llm` → chunking → N chamadas ao LLM →
dedup → grava nós. Retorna `{"status": "processed", "extracted": N}` ou `{"status": "error"}`.

### FINDING — timeout do `SessionEnd`, corrigido após verificação

O `SessionEnd` do plugin declara `timeout: 300, async: false`. A doc oficial do Claude Code
(<https://code.claude.com/docs/en/hooks.md>), citada verbatim pelo Agente 1:

> "SessionEnd hooks have a default timeout of 1.5 seconds. This applies to session exit, `/clear`,
> and switching sessions via interactive `/resume`. If a hook needs more time, set a per-hook
> `timeout` in the hook configuration. The overall budget is automatically raised to the highest
> per-hook timeout configured in settings files, up to 60 seconds. **Timeouts set on
> plugin-provided hooks don't raise the budget.** To override the budget explicitly, set the
> `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS` environment variable in milliseconds."

**O `timeout: 300` do manifest do plugin é inócuo.** Ele não é um "settings file timeout" — é
timeout declarado por um plugin, e a doc é explícita que esses não sobem o budget. O budget real do
`SessionEnd` é **1,5 s por padrão**, subindo até **60 s** só via `timeout` num arquivo de settings
do usuário, ou via a env var acima. Para comparação, outros hooks têm budgets bem maiores: 600 s
para `command`/`http`/`mcp_tool`, 30 s para `prompt`, 60 s para `agent`, 10 s para
`MessageDisplay` — **`SessionEnd` é o menor de todos por padrão** (Agente 1). Mecanismo de kill
(SIGTERM/SIGKILL) segue **[não verificado]** — a doc diz apenas que os hooks são "canceled" e que
"`SessionEnd` hooks have no decision control. They can't block session termination." Comportamento
em crash/`kill -9` também **[não verificado]** — os valores de `reason` documentados
(`clear`/`resume`/`logout`/`prompt_input_exit`/`bypass_permissions_disabled`/`other`) não incluem
encerramento abrupto.

**Mas o mecanismo provado do motor de duplicação não é o harness — é o cliente httpx do próprio
hook** (Agente 2). O timeout do cliente é `max(60, claude_cli_timeout + 15)` = **135 s**
(`cli_adapter.py:387-396`; 120 s confirmado no log como o `claude_cli_timeout` vigente). Contra
isso, a duração real de `/ingest/conversation` (203 conclusões logadas, 07-13→07-17): **p50
118,8 s · p90 905,6 s · max 2.019,4 s (33,6 min)**. **128/203 (63%) passam de 60 s; 56/203 (28%)
passam de 300 s.** No pior caso registrado (29 chunks a ~120 s cada ≈ 58 min), o cliente já desistiu
há ~56 minutos quando o servidor termina. **O httpx sozinho já dispara o motor de duplicação — não
é preciso o harness matar nada.** Sinal de disconnect: zero `ClientDisconnect`/`CancelledError`/
`Broken pipe` em 408.470 linhas de log — mas isso é ausência de sinal, não sinal negativo: o
servidor não loga chegada de request nem disconnect, só conclusão (middleware).

**Evidência direta do motor rodando no hook**, observada por Agente 2: o mesmo payload de
**1.140.586 chars foi postado 5 vezes** entre 15 e 16/07:

```
2026-07-15 12:50:31,512 split 1140586-char payload into 29 chunks
2026-07-15 21:16:25,925 split 1140586-char payload into 29 chunks
2026-07-15 21:50:01,860 split 1140586-char payload into 29 chunks
2026-07-15 22:34:15,150 split 1140586-char payload into 29 chunks
2026-07-16 08:50:16,541 split 1140586-char payload into 29 chunks
```

Duas completaram server-side, com aritmética exata contra o log de split:

```
COMPLETE 2026-07-15 22:11:34  1293s   (22:11:34 − 1293s = 21:50:01 ✓)
COMPLETE 2026-07-15 22:54:14  1199s   (22:54:14 − 1199s = 22:34:15 ✓)
```

Atribuição de sessão por mtime ao segundo (**inferida**, sem `session_id` persistido no log):
transcript `6206db7d` (`-Users-andre-Documents-Obsidian-AndreMartins`), mtime 2026-07-15
21:16:25,304 vs split 21:16:25,925. O cursor dessa sessão está **congelado em 2.913.087 (77,7% de
3.748.653 bytes) até hoje**, apesar de pelo menos duas extrações completas — exatamente o padrão
previsto: o servidor grava, o cliente já desistiu, o cursor não avança. **6 cursores no total estão
travados** (arquivo parado há 1–3 dias, Agente 2):

| sessão | % consumido | tamanho do transcript |
| --- | --- | --- |
| `e73982aa` | 21,6% | 5,4 MB |
| `c2203765` | 44,3% | 2,5 MB |
| `6206db7d` | 77,7% | 3,7 MB |
| `b3f65087` | 88,4% | — |
| `44a38635` | 90,7% | — |
| `6e71e3f8` | 93,6% | — |

**Isso é um motor de duplicação, confirmado, e está no upstream** — qualquer usuário do plugin
upstream com sessões grandes o suficiente para estourar 60–135 s de extração o tem.

**Segue não observado diretamente:** o harness matando o processo do hook em ato — na prática isso
já é secundário, porque o httpx do próprio hook mata antes na maioria dos casos (63% das ingestões
passam de 60 s). Um `SessionEnd` cronometrado ao vivo, comparando `whisper-cursors.json` antes/
depois com a contagem de nós criados, seria o único teste que decidiria se o harness *também* mata
— não muda a conclusão de que o motor existe.

---

## Problema 1 — o julgamento de relevância é um prompt, não um gate

### Como funciona hoje

O único filtro de conteúdo é o `_INGEST_LLM_PROMPT` + `_INGEST_LLM_RULES`
(`src/ormah/engine/memory_engine.py:3081` e `:3174`). Ele diz ao modelo:

- uma **quality bar** ("específico, self-contained, searchable") com exemplos BAD/GOOD;
- uma **lista de prioridade** do que extrair (decisões com raciocínio > correções do usuário >
  preferências > arquitetura > procedimentos > goals > achados surpreendentes > identidade);
- uma lista de **"What NOT to extract"** que inclui, literalmente:
  - *"Generic technical knowledge the AI already has"*
  - *"Routine code changes with no decision or learning behind them"*
  - *"Code read-throughs where the user is just tracing existing logic"*
  - *"Intermediate debugging steps that led nowhere"*
- uma regra de **dedup dentro do próprio output**.

Depois disso, `_extract_memories_llm` (`memory_engine.py:2775`) coleta o JSON e
`all_memories.extend(memories)`. **Existe um filtro pós-LLM, mas não é de relevância** (Agente 4,
Agente 6): (1) skip de conteúdo vazio; (2) dedup semântico — `_is_duplicate_memory`
(`memory_engine.py:3061`, chamado em `:2717`) descarta se o vizinho vetorial top-1 tiver
similaridade ≥ `auto_merge_threshold` (**0,85**); (3) `ingest_min_confidence`
(`config.py:348`), que existe mas está em **0.0 por padrão = desligado**, sem override no `.env`.
**O que não existe é um gate de relevância/saliência:** nenhum score que julgue "isso vale a pena
guardar", nenhum threshold de confiança ativo, nenhum orçamento de quantidade por sessão. O prompt
continua sendo um pedido, não uma restrição — o filtro que existe pega quase-duplicatas, não lixo
genérico não-repetido.

### A evidência de que não funciona

O prompt proíbe conhecimento genérico. Mesmo assim, dos **2.792 nós criados hoje** (remedido
~12:30 UTC de 17/07 pelo Agente 4 — a contagem original da manhã era 2.539, o store cresceu entre
as duas leituras), **461 (16,5%)** têm `Claude`/`API`/`SDK` no título:

```
Claude API: Refusal fallbacks (Fable 5 server-side retry)
Claude Fable 5 breaks thinking configuration — omit the thinking parameter
Claude prompt caching prefix matching and silent invalidators
Anthropic Managed Agents API — session and agent lifecycle
Claude API SDK examples — Go and Java bindings
Claude API: Stop reason enum and refusal structured details
```

Isso é documentação da Anthropic. Não é decisão do André, não é preferência dele, não é surpresa
dele. É exatamente a categoria que a regra bane — e entrou mesmo assim, 461 vezes em um dia.

### De onde isso veio: o extrator memoriza o que passa pela tela

O André não reconheceu esse conteúdo ("não estou usando Go/Java, não sei de onde veio"). O nó
`9272c6e0` explica, e a primeira palavra entrega tudo:

> **"The conversation shows** Go and Java SDK code examples for the Claude API and managed agents.
> Key libraries include anthropic-sdk-go and anthropic-java (Maven dependency
> com.anthropic:anthropic-java:2.34.0)…"

O extrator está **narrando o transcript**, não extraindo conhecimento. A sessão rich-doc estava
*processando documentação da Anthropic* — e o extrator memorizou **o material que passou pela
sessão**, não o trabalho feito nela. **395 dos 461 nós estão no space `rich-doc`.**

A frase "31 nós começam literalmente com 'The conversation shows'" **superestima o literal**
(remedido, Agente 4): o prefixo estrito **"The conversation shows"** aparece em **1** nó. A família
mais ampla — `The conversation%` (26) + `The session%` (3) + `This conversation/session%` (3) —
soma **≈29–32**, confirmando a magnitude do fenômeno, mas não o texto literal citado no doc
original.

**A falha estrutural: o extrator não distingue "o que o André decidiu" de "o que estava na tela".**
Qualquer sessão que *processe* um documento acaba com o documento memorizado. Como o André usa o
Claude para trabalhar com documentação, ferramentas e código dos outros o dia inteiro, essa
confusão converte trabalho em lixo numa taxa industrial.

Isso é o argumento mais forte a favor do **filtro de tipo por fonte**: uma sessão de geração de
doc não deveria poder produzir `fact`. Só `decision` e `preference` — as coisas que são do André,
não do material.

### Onde a hipótese "é a mesma coisa N vezes" vale e onde não vale

**Vale** para o Problema 2 abaixo — `"Claude Code quota is shared across all models"` está no
store **16 vezes** (remedido, Agente 4 — o doc original contava 5), em reformulações diferentes,
geradas por chunks diferentes da mesma sessão. Fingerprints distintos, dedup por hash não pega.
Isso é exatamente o que a hipótese descreve.

**Não vale** para os 461. Eles são fatos *diferentes* — refusal fallbacks, prompt caching, Managed
Agents lifecycle, Go/Java bindings, stop-reason enum. Não são variações do mesmo nó: é um **dump de
documentação**, distinto item a item. São duas doenças com o mesmo sintoma (volume), e o fix é
diferente para cada: a duplicação pede contexto compartilhado entre chunks; o dump pede um gate de
fonte/tipo.

O rastro das fatias aparece no timestamp — rajadas de 5-8 nós no mesmo minuto (00:22 ×5, 00:23 ×7),
cada rajada sendo o retorno de uma chamada LLM. **Um chunk produz 5-8 memórias.**

Amostra do que entrou às 03h, misturando o legítimo com o descartável:

| nó | veredito |
| --- | --- |
| `preference \| Verify peer findings empirically before accepting or rejecting` | **legítimo** — preferência real, é o tipo nº 3 da lista |
| `decision \| rich-doc skill gate deliberately kept failing pending wrap.sh` | **lixo** — estado transitório, sem valor em 3 dias |
| `fact \| TOC labels in rich-doc are editorial, not derived — no h1 anchor` | **lixo** — trivia de implementação, já está no código |
| `fact \| Claude Opus 4.8 — most capable Opus tier, state-of-the-art…` | **lixo** — conhecimento genérico, banido pela regra |
| `fact \| C# Files API (beta) requires BetaRequestDocumentBlock…` | **lixo** — doc de API, não é conhecimento do usuário |

**Taxa medida: 2,56 nós por turno de usuário** (calculado sobre `user_turns` e `node_ids` do
`.session_watcher_state`, 413 transcripts; **re-verificado exato pelo Agente 4**: 6.510 node_ids ÷
2.541 user_turns em 418 entries = 2,56). Trabalhar 8 horas com o Claude gera algumas centenas de
memórias. Não há nada no sistema que diga "esta sessão merece 5 memórias, não 200".

### Por que isso é estrutural, não um bug de prompt

Melhorar o prompt ajuda na margem, mas o modelo recebe uma instrução ("extraia memórias valiosas")
sem custo por errar para mais. Extrair demais não tem penalidade; extrair de menos parece falha.
O incentivo do extrator é sempre produzir. **Falta o outro lado: um gate que rejeite.**

Opções (nenhuma implementada, nenhuma validada):

- **Orçamento por sessão** — no máximo N memórias por slice, forçando o modelo a ranquear em vez
  de listar. É o menor diff e ataca o incentivo direto.
- **Score de salience pós-LLM** — pedir ao extrator um score 0-1 por memória e descartar abaixo de
  um threshold. Move o julgamento para um número auditável, mas confia no mesmo modelo.
- **Filtro de tipo por fonte** — sessões de subagente/geração de doc só podem produzir `decision` e
  `preference`, nunca `fact`. Cortaria os 461 nós genéricos de hoje sem tocar no prompt.

---

## Problema 1b — o throttle: por que 3,8 MB não são consumidos em 14 horas

O cursor parado em 44% depois de uma madrugada inteira **não é uma falha — é o design**. Quatro
constantes, todas em `config.py`:

| constante | valor | efeito |
| --- | --- | --- |
| `session_watcher_reconcile_interval_minutes` | **5** | o reconcile roda a cada 5 min |
| `session_watcher_reconcile_max_seconds` | **30.0** | o loop **quebra após 30 segundos** |
| `session_watcher_reconcile_max_per_tick` | 50 | no máximo 50 arquivos por tick |
| `session_watcher_catchup_concurrency` | **1** | catch-up é **serial** |

**30 segundos de trabalho a cada 5 minutos = duty cycle de 10%.** O watcher trabalha meio minuto
e dorme quatro minutos e meio. O código quebra o loop explicitamente
(`session_watcher.py:1218-1221`):

```python
budget = self.engine.settings.session_watcher_reconcile_max_seconds
for _dep, _mtime, jsonl_file in candidates[:cap]:
    if time.time() - start >= budget:
        break  # yield scheduler thread; remaining picked up next tick
```

### A conta do arquivo de 3,8 MB — corrigida após medição

O modelo original desta seção (~12 fatias/hora, derivado do orçamento de 30 s ÷ ~1 fatia por tick)
estava **errado em ~3×** (Agente 4). Medição direta do log: **231 fatias processadas entre 00h e
06h de 17/07 = ~38,5 fatias/hora** (por hora: 50, 39, 34, 40, 33, 35), com gap mediano entre fatias
sucessivas de **63,5 s** (p25 45 s, p75 85 s). O gargalo do duty cycle de 10% é real — só a conta
de dimensionamento original estava errada.

Com `session_watcher_flush_bytes = 60000`:

- 3.824.790 ÷ 60.000 = **~64 fatias**
- 64 fatias ÷ ~38,5 fatias/hora ≈ **1,7 hora para UM arquivo** — se tivesse a pista só para si

Ele não tem: existem **112 transcripts com cursor >500 KB** disputando a mesma pista serial. Daí
as horas reais observadas para avançar (ver [A pergunta da madrugada](#a-pergunta-da-madrugada--respondida)).
Seis timeouts de 120 s aconteceram durante a madrugada — cada um derruba a fatia inteira
(retryable, nada é gravado antes do sucesso completo).

**"20-40 s por fatia" segue [não confirmado]** nas duas direções: a duração de processamento de
uma chamada individual do `claude -p` não é logada — só o gap entre fatias sucessivas é
observável, e gap não é o mesmo que duração de processamento (pode incluir espera na fila serial
disputada pelos 112 transcripts). O comentário do `ingest_chunk_chars` diz que 40 K ≈ 10 K tokens
foi escolhido como "timeout-safe", mas a medição que sustenta esse número não foi encontrada.

**Atacar o gargalo de outra forma:** blocos maiores por chamada reduziriam spawns *e* dariam
contexto compartilhado ao extrator — atacando latência e duplicação de uma vez. Ainda não medido:
qual o tamanho de bloco que o `claude -p` aguenta sem timeout.

---

## Problema 2 — a ingestão por chunks duplica memórias

`_extract_memories_llm` faz:

```python
chunks = _split_for_extraction(content, chunk_chars, hard_cap)
for i, chunk in enumerate(chunks):
    prompt = _INGEST_LLM_PROMPT.format(conversation=chunk)
```

Com `ingest_chunk_chars = 40000` e `ingest_max_content_chars = 100000`, uma sessão longa vira
vários chunks — e **cada chunk recebe o prompt completo, isolado dos outros**. A regra
"Deduplication within your output" só enxerga o output daquele chunk. Um fato recorrente na
conversa é re-extraído a cada chunk que o menciona. Loop confirmado em código:
`memory_engine.py` ~linha 2791 (Agente 4).

Provado nos últimos 3 dias (remedido pelo Agente 4 — os números originais eram subestimados):

```
Claude Code quota is shared across all models          →  16 nós (≥8 reformulações claras)
rich-doc fragment contract: nav.toc + main on…         →  3 nós
Subagent-driven development with implementer-…         →  3 nós
Defer rich-doc HTML generation until wrap.sh…          →  3 nós
```

Dezesseis cópias do mesmo fato, não cinco. Não são fingerprints idênticos (por isso o dedup por
hash não pega) — são reformulações do mesmo conteúdo, geradas por chunks diferentes da mesma
sessão. **O fenômeno é maior do que o doc original media**: por shingle de 3 palavras nos últimos
3 dias aparecem mais 13 clusters temáticos (`ormah auto linker` 81×, `claude fable 5` 49×,
`opus 4 8` 48×, `subagent driven development` 47×, `timeout hint seconds` 32×,
`vector store durability` 27×) — nem todos são o mesmo fato repetido palavra por palavra (alguns
são o mesmo *tema* revisitado legitimamente em sessões diferentes), mas a cauda é claramente mais
longa que os 4 exemplos originais.

O `duplicate_merger` existiria para limpar isso. A afirmação de que ele "processou 0 pares nas
últimas 24h" está **refutada** (Agente 4): ele **rodou 4 vezes** nas últimas ~24h (pares avaliados
426+463+472+556, 11 proposals, **46 merges gravados em `merge_history`**), disparado pelo
sleep-cycle (`POST /admin/tasks/run-all` às 01:30) **apesar do `=99999` no `.env`** — esse valor
desliga outro gatilho, não o `run-all`. O "0" original veio de consultar a tabela
`duplicate_checked`, que está **estagnada desde 2026-07-08T21:02** (108 linhas, sem crescer desde
então) enquanto o merger continua rodando por outra via — **achado novo, provável bug de
bookkeeping, não investigado** (ver [Registro de confiança](#registro-de-confiança)). Mesmo
funcionando, ele paga LLM para consertar algo que a ingestão não deveria ter criado — esse
argumento segue de pé. Merges também acontecem por uma terceira via não citada antes neste doc:
`run_maintenance` via MCP (**16 merges em 17/07**, todos às 15:19 UTC, Agente 6).

---

## Problema 2b — o loop de recovery do `session_watcher` (maior motor de duplicação observado)

**Não estava no doc original — achado novo do Agente 2, confirmado pelo Agente 6 e pela
verificação consolidada.** Em volume de duplicação observado, é maior que o motor do `SessionEnd`
descrito no Problema 0.

O `session_watcher` **rebobinou e re-extraiu o mesmo payload de 788.113 chars 36 vezes em 14
horas** — transcript `rich-doc/05640182`, de 16/07 20:55 a 17/07 10:44, em ciclo de **~27
minutos**. 28 tentativas completaram (gravando entre 2 e 82 memórias cada, **~773 memórias
somadas** — atribuição aproximada por interleaving no log; é a maior fatia dos nós descritos em
["A pergunta da madrugada"](#a-pergunta-da-madrugada--respondida)); 8 falharam. O gatilho aparece
**26 vezes** no log, sempre precedendo uma nova tentativa completa:

```
2026-07-16 21:39:21,312 [session_watcher] INFO: Session watcher recovering legacy mid-response cursor for ...rich-doc/05640182...
2026-07-16 21:41:08,904 [memory_engine] INFO: ingest extraction: split 788113-char payload into 20 chunks
2026-07-16 21:48:53,102 [memory_engine] INFO: Ingested 52 memories from conversation
   (…27 min depois, rebobina e repete…)
```

Nas falhas, um único chunk que estoura derruba a fatia inteira (retryable — Agente 6 confirma que
nada é gravado antes do sucesso completo do slice inteiro):

```
2026-07-17 04:10:18,018 [claude_cli_adapter] WARNING: claude -p timed out after 120s
2026-07-17 04:10:18,019 [memory_engine] WARNING: ingest extraction: chunk 10/20 (39937 chars) returned no result — whole slice retryable (partial result discarded)
```

**Duplicatas com timestamps casando com runs distintos do loop estão no DB**: 5× "claude code
quota is shared" às 00:25 / 03:41 / 06:55 / 11:43 / 13:35 UTC — um por rebobinada, quase
cronometrado.

**Causa raiz — DIAGNOSTICADA (2026-07-17, replay determinístico + verificação independente dos
bytes e do código).** O parser commita uma boundary segura após um `assistant` com
`stop_reason=end_turn` (`parser.py:333-342`). No transcript `05640182`, o registro imediatamente
seguinte à boundary **3.294.105** é **outro `assistant`** (`stop_sequence`, texto
*"API Error: Connection closed mid-response. The response above may be incomplete."*) que chega
**antes** de qualquer registro de user (o `user "continue"` vem 3 registros depois). O check de
leading-orphan (`parser.py:326-327`: `if text and not _saw_user_record and start_offset > 0`)
classifica isso como cursor legado quebrado — **falso positivo**: o parse a partir de 3.294.105
retorna payload utilizável (`safe_end=3.635.931`), descartado a cada ciclo. O recovery
(`session_watcher.py:777-783`) então rebobina para o offset 0 e re-ingere o arquivo inteiro; o
comentário diz *"a one-time re-ingest"*, mas **nenhum marker é persistido** — e como o gatilho é
propriedade permanente dos bytes do arquivo, o ciclo é eterno: re-drena as 16 fatias (~27 min,
autodirigido pela duração das chamadas LLM — não é o intervalo do reconcile), chega à mesma
boundary, dispara de novo. Efeito colateral: os **~530 KB finais do transcript nunca são
ingeridos**. Alternativas descartadas com evidência: falha de slice (28 ciclos completaram e
avançaram o cursor até a boundary), corrida de workers (replay serial reproduz o loop integral),
state revertido por outro processo, exceção pós-ingest. Blast radius atual: 26 recoveries, todos
deste transcript — mas a classe é geral: qualquer transcript com o padrão
`assistant(end_turn) → assistant("API Error…") → user` loopa igual. **Procedência: UPSTREAM** —
`leading_orphan` e o recovery existem em `upstream/main` (`parser.py:290`,
`session_watcher.py:741-745`) e também no caminho do hook (`cli_adapter.py:447`), que tem o mesmo
padrão de recovery. Direção de fix (não implementada): não rebobinar quando o parse com orphan
ainda produz `safe_end > start_offset` (avançar descartando o fragmento) e/ou marker one-shot
`legacy_recovered` no state; teste de reprodução: fixture
`user → assistant(end_turn) → assistant(stop_sequence "API Error…") → user("continue")`, assert
cursor monotônico + recovery no máximo 1× + nenhuma fatia ingerida 2×. Ver
[Issues a abrir](#issues-a-abrir).

---

## Problema 3 — o churn de `seq` (refutado como causa do backlog)

Investigado a fundo por um agente dedicado (Agente 5), com observação ao vivo do sistema rodando,
não só leitura de código. **A cadeia de código está confirmada elo a elo — mas ela não é a causa
do backlog do `auto_linker`.** Este é o item mais reescrito desta revisão: o doc original tratava
o churn como a causa nº 2 do problema; a verificação refuta essa causalidade.

### Estado atual (12:35 -03, Agente 5)

| medida | valor |
| --- | --- |
| backlog do `auto_linker` | **14.904 de 21.303 nós (70,0%)** |
| `node_seq_next` | **784.903** |
| watermark | **769.690** |
| nós >5 dias acima do watermark | 6.667 *(número original da manhã, não remedido)* |
| nós com `space_locked = 0` | **18.642 (≈88%)** |
| nós com `updated` = hoje | **17.343** (≈11,7 mil do burst do Importance scorer + ~2,7 mil de um burst às 11:11 UTC) |
| pool elegível do `auto_cluster` hoje | **103 nós** |

### A cadeia de código (confirmada, elo a elo)

**Elo 1** — `auto_cluster` faz `UPDATE nodes SET space = ? WHERE id = ? AND space_locked = 0`
(`auto_cluster.py:86`) sobre nós elegíveis. **Nuance importante:** o requeue real vem do
dual-write no markdown (`auto_cluster.py:68-74`: `node.space=…; touch_updated(); file_store.save`),
reindexado pelo Index updater (1 min) — não do `UPDATE` SQL isolado. Seleção é `WHERE (space IS
NULL OR space='') AND space_locked=0` (linha 20) — **one-shot por nó, não recorrente**. Escala
observada: 33 linhas "Auto-cluster assigned" no log, todas de **1–3 nós por run** (job de 1h).

**Elo 2** — `space` está no `content_fingerprint` (`fingerprint.py:22`, confirmado; é
`sha256(title, content, type, space)`).

**Elo 3** — bump condicional de `seq` quando o fingerprint muda (`builder.py:238-247`,
confirmado).

**Elo 4** — a fila do `auto_linker` é por `seq > watermark` (`auto_linker.py:39-41`, confirmado).

**Elo 5** — o fix `#126` (edge-write não bumpa mais `seq`) está no `local-main` **e foi observado
funcionando em escala**: às 13:11 UTC de hoje, o Importance scorer reescreveu **11.697 arquivos de
nó em ~6 s** (`importance_scorer.py:109`, `touch_updated`+`save`); os seqs desses nós vão de
460.847 a 784.593, com 2.687 **abaixo** do watermark e **preservados** — `node_seq_next` não
avançou em massa por causa disso. Varredura dos 21.303 nós: **zero** fingerprints recomputados
divergentes do persistido. `_apply_edge` (`auto_linker.py:349-362`) só escreve
`connections`+`updated`, fora do fingerprint.

### Por que a cadeia não explica o backlog

**Elo 6 — "backlog nunca drena por causa do churn": REFUTADO.** Dos 3.000 `seq` mais recentes,
**2.980 (99,3%) são nós NOVOS** (criados ≥07-16); só 20 são requeue por edição (14
`agent:claude_code`, 4 `consolidator`). O `auto_cluster` contribui **≤3 nós/hora** contra um cap
de dreno de 100 nós/run. A aritmética real: chegada 1.983 (07-14) · 891 (07-15) · 1.945 (07-16) ·
2.792 (07-17 parcial) nós/dia, contra dreno `ORMAH_AUTO_LINK_MAX_NODES_PER_RUN=100` × 12 runs/dia
(trigger vivo a cada 2h) = **1.200/dia**. **Chegada > dreno, ponto final** — não é preciso invocar
churn. Série do log de `backlog_nodes`: 13.308 (07-15 21:07) → 13.938 → 13.450 → **14.904 agora**.
Runs de 260–510 s a 0,8 pares/s, `cap_hit: False` **sempre** — o job usa ~5 minutos de cada janela
de 2 horas disponível. **O gargalo é o cap de 100 nós/run, não o churn.**

**Elo 7 — "37 re-enfileiramentos por nó": refutado como leitura do número.** `node_seq_next` é um
contador **cumulativo** desde a criação do índice — inclui nós deletados/merged e full rebuilds
passados (~21 mil seqs cada rebuild; `min(seq)=168.998` prova reindexações em massa históricas) e
um período **pré-`#126`**, quando edge-writes ainda bumpavam `seq`. Dividir `node_seq_next` pela
contagem atual de nós não mede "requeues por nó vivo hoje" — mede história acumulada.
**[inferido — o histórico anterior não é reconstruível a partir do estado atual.]**

### Conclusão

O backlog de 70% é **estrutural de vazão** (chegada ~2.000/dia vs. cap de dreno 1.200/dia), não um
efeito colateral do `auto_cluster`. Tirar `space` do fingerprint continua sendo tentador e errado
pelo mesmo motivo do doc original (o comentário do código diz que `space` é mostrado ao juiz do
link e alimenta o `cross_space_penalty`, então uma mudança de space genuinamente muda a decisão) —
mas agora sabemos que **não vale a pena mexer nisso para resolver o backlog**, porque o
`auto_cluster` não é o gargalo. Se o objetivo é drenar mais rápido, o knob é **o cap de 100
nós/run** (o job usa ~5 min de cada 2h disponíveis — há folga óbvia), não o churn de `seq`.

**Não verificado / a fazer** (Agente 5): observação ao vivo do próximo run do `auto_cluster` no
ato; se o trigger do `auto_linker` está mesmo em 2h (o `.env` diz 240 min, o processo vivo pode ter
carregado outro valor); 3× "Auto-linker failed: watermark read failed" em 07-15 20:41, não
investigado; atribuição do burst `updated=hoje` ao Importance scorer é por coincidência de tick,
não prova direta.

---

## A pergunta da madrugada — respondida

**O que o ormah ingeriu entre 00h e 06h de 2026-07-17, sem o André estar trabalhando:**

| space | nós |
| --- | --- |
| `rich-doc` | **990** |
| `(null)` | 269 |
| `AndreMartins` | 39 |
| `ormah` | 9 |

*(Nota: reconsultando essa janela agora, na revisão, os números aparecem menores — 885/233/29/9 —
diferença provavelmente explicada pelas ~50 remoções/dia sem trilha completa em `audit_log`/
`merge_history` que o Agente 6 notou como achado à parte, mas pode também ser diferença de query.
**[não confirmado]**, não investigado a fundo.)*

**Resposta: catch-up, não ingestão ao vivo.** O conteúdo é da sessão rich-doc da noite de 16/07 —
e, como o Problema 2b mostra, boa parte dele é o mesmo conteúdo **re-extraído 36 vezes pelo loop de
recovery**, não 36 sessões distintas.

Prova — o cursor persistido em `~/.claude/projects/.session_watcher_state`:

```json
"…/rich-doc/05640182-….jsonl": {
  "end_offset": 1671876,
  "last_ingested": "2026-07-17T13:33:39",
  "user_turns": 12
}
```

O arquivo tem **3.824.790 bytes**. O cursor está em **1.671.876 = 44%**, e o `last_ingested` era
*agora* (13:33). O transcript parou de crescer às 09:11. **O watcher levou a madrugada inteira
mastigando um transcript de 3,8 MB, e às 13:33 ainda estava na metade** — em parte porque estava
gastando ciclo re-processando o mesmo trecho repetidamente (Problema 2b), não só por causa do
throttle (Problema 1b).

Existem **112 transcripts com cursor acima de 500 KB** — todos em digestão. A ingestão não
acompanha a escrita: ela fica devendo, e paga a dívida enquanto o André dorme.

**Descartado — transcripts de subagente NÃO são a fonte dos 990/269 de hoje.** O
`session_watcher.py:749` os pula explicitamente (`_is_subagent_transcript`, linha 560) desde
~08/07. Os 20 arquivos em `05640182-…/subagents/` (~3,4 MB) não entraram. Os 990 nós da madrugada
vieram só dos transcripts pai.

**Os 269 nós `space=(null)` da madrugada: RESOLVIDO** (Agente 6). Mesma origem que os 990 de
`rich-doc` — todos `agent:claude_code` (233/233 checados hoje), tags `session-transcript` +
`auto-ingested`, com `about_self` em 192 deles: é o watcher em catch-up gravando memórias
pessoais/globais que **não recebem `space`** — regra provável **[inferida, não lida diretamente
no código]**: conteúdo `about_self` fica global por padrão. Nenhum mecanismo novo — mesma
madrugada, mesma causa dos 990.

**Achado à parte sobre subagentes:** embora o skip de `*/subagents/*` funcione desde ~08/07, o
store carrega **288 nós legados** de quando o watcher ainda os ingeria — 56 entries `subagent` no
`.session_watcher_state`, todas com `last_ingested ≤ 2026-07-08T18:50`. Do lado do hook,
subagentes nunca contribuíram nada: **0 dos 182 cursores** do hook estão sob `*/subagents/*`
(Agente 6).

---

## Contabilidade de volume — de onde vêm os nós (7 dias)

Pergunta que o doc original deixava implícita: existe alguma via de criação de nós fora das duas
descritas no Problema 0? **Não** — a contabilidade fecha em zero resíduo (Agente 6).

Inventário completo por `source` (única atribuição existente no schema — não há `session_id` em
`nodes`, `node_tags`, nem no frontmatter dos arquivos de nó):

| `source` | nós (07-06→17/07) | via |
| --- | --- | --- |
| `agent:claude_code` | 14.972 | `session_watcher` (tag `session-transcript`) — `session_watcher.py:902` |
| `agent:ingester` | 5.744 | hook `PreCompact`/`SessionEnd` (tag `whisper-out`) — o hook não manda `agent_id`, cai em "ingester" (`memory_engine.py:2763`) |
| `agent:consolidator` | 303 | **consolidator cria nós** (`consolidator.py:159`, `remember` com `agent_id=consolidator`) — via ausente do doc original |
| `agent:unknown` | 247 | `remember` explícito via MCP (`memory_engine.py:584`) |
| `agent:codex` | 36 | watcher sobre `~/.codex/sessions` **[inferido do log, não confirmado no código]** |
| `system:self` | 1 | seed |

**Janela de 7 dias fecha em zero resíduo:** watcher 5.677 + hook 4.919 + consolidator 234 + MCP 103 + codex 25 = **10.958**, sem via oculta. `routes_ingest.py:64` (`ingest_file`) existe no código mas tem **0 nós atribuíveis** — nunca usada na prática.

**Merges também têm uma terceira via não citada antes neste doc:** além do `duplicate_merger` (ver
Problema 2), `run_maintenance` via MCP fez **16 merges em 17/07**, todos às 15:19 UTC (Agente 6).

**Não-patológicos, descartados como causa** (Agente 6): 12 starts do servidor em 7 dias (sem
crash-loop); ~2.488 linhas "Cannot read" = scan de transcripts já apagados (0 nós criados);
reranker ausente (4.648×), classifier axis (912×), `whisper_decisions` (182×) — afetam
whisper-inject/busca, não a ingestão.

---

## O que o André está perdendo

`recall` roda com `spread_activation=True` (`memory_engine.py:855`): acha nós por similaridade e
depois puxa vizinhos por edge. **Os 14.904 nós sem link não participam disso** — só aparecem se o
embedding bater em cheio, nunca por associação. É a promessa central do ormah quebrada em **70,0%
do store** (21.303 nós; `node_seq_next` 784.903, watermark 769.690 — remedido pelo Agente 5,
~12:35 -03 de 17/07).

**Correção sobre a causa:** não é uma fila que "se reembaralha" por churn — é chegada (~2.000
nós/dia) maior que dreno (cap de 1.200 nós/dia), ver
[Problema 3](#problema-3--o-churn-de-seq-refutado-como-causa-do-backlog). O custo de manter isso
quebrado: **~480 spawns de `claude -p` por dia** (derivado de ~5.900 pares/dia ÷
`MAINTENANCE_PAIRS_PER_CALL=10`; **não verificado** — o log não registra invocação de processo, e
este número específico não foi re-checado pelos 7 agentes desta verificação) queimando a
assinatura para linkar uma fila que hoje está **16,5% cheia de documentação da Anthropic**
(remedido; era 17% na contagem original da manhã).

---

## Ordem recomendada

Revisado após verificação (ver `docs/verificacao-2026-07-17-problemas-de-ingestao.md`) — a ordem
original tinha o churn de `seq` como prioridade nº 2; isso caiu, porque o churn foi refutado como
causa do backlog.

1. **Problema 1** — o gate de ingestão. Continua a raiz: menos lixo entrando resolve chegada,
   custo e qualidade do recall ao mesmo tempo. Se a chegada cair de ~2.800 para ~300/dia, o cap de
   dreno atual (1.200/dia) fecha o gap sozinho — **sem precisar tocar no `auto_linker`**.
2. **NOVO — o loop de recovery do `session_watcher`**
   ([Problema 2b](#problema-2b--o-loop-de-recovery-do-session_watcher-maior-motor-de-duplicação-observado)).
   É o maior motor de duplicação observado nesta verificação (36 re-extrações do mesmo payload em
   14h). Investigar a causa do rebobinar antes de qualquer outro trabalho em duplicação.
3. **Ingestão assíncrona.** O motor de duplicação do `SessionEnd` (Problema 0) não se resolve só
   com `async: true` — isso evita segurar a sessão do usuário, mas não conserta o cursor, que só
   avança com resposta síncrona recebida. O fix estrutural é responder rápido (enfileirar o job) e
   avançar o cursor por **confirmação de job concluído**, não por resposta de request. p50 de
   `/ingest/conversation` é 118,8 s; pior caso, 29 chunks × 120 s ≈ 58 min — nenhum timeout de
   cliente razoável cobre isso.
4. **Problema 3 (churn de `seq`) sai da lista de causas do backlog** — refutado. Se a prioridade
   for drenar mais rápido, o knob é o cap de 100 nós/run (o job usa ~5 min de cada janela de 2h
   disponível — há folga óbvia). Não abrir issue de churn.
5. **Problema 2** — os chunks isolados. Mantém posição, agora com evidência maior (16 cópias do
   fato "quota is shared", não 5). A extração holística proposta pelo André (ver seção abaixo)
   segue válida como direção, **depois** do gate de relevância.

Trocar `ORMAH_LLM_PROVIDER` para `ollama` corta o custo imediatamente, mas **não é o fix** — é
parar de pagar caro pelo sintoma. Vale como medida paralela, não como solução.

---

## O que define o `SessionEnd`

Fonte: doc oficial do Claude Code, <https://code.claude.com/docs/en/hooks.md>.

O `SessionEnd` dispara quando a sessão termina, e o payload traz um campo **`reason`** com o
gatilho:

| `reason` | quando |
| --- | --- |
| `clear` | `/clear` |
| `resume` | sessão retomada/trocada via `/resume` |
| `logout` | usuário deslogou |
| `prompt_input_exit` | saiu com o prompt visível |
| `bypass_permissions_disabled` | modo bypass desabilitado |
| `other` | qualquer outra causa |

Payload: `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `reason` — os três primeiros
são os que o `cmd_whisper_store` consome.

**Não documentado (`[não verificado]`):** se o `SessionEnd` dispara em crash, SIGSEGV ou `kill -9`.
A doc oficial não dá garantia de disparo em encerramento abrupto; os valores de `reason`
documentados acima não incluem encerramento abrupto (Agente 1). Nesse caso, a via do hook
simplesmente não roda.

**Correção de procedência (Agente 7):** este doc afirmava que, nesse cenário, "no upstream, que
não tem `session_watcher`, o conteúdo fica órfão até aquele transcript ser tocado de novo".
**Errado.** `upstream/main` **tem** `session_watcher.py` (1.009 linhas, com catch-up e watcher em
tempo real — `:967`/`:986`). O que é exclusivo do fork é a maquinaria de **reconcile**
(`reconcile` em `:1147`, `_run_startup_reconcile` em `:1273`, `run_session_reconcile` em `:1384`;
zero `def reconcile` no upstream, contra 1.411 linhas no `session_watcher.py` do fork). Ou seja:
mesmo no upstream, o watcher básico com catch-up já funciona como rede de segurança para conteúdo
perdido pelo hook — o que falta lá é o reconcile mais robusto, não a rede de segurança em si.

**`PreCompact`** dispara antes de uma compactação, com matcher `manual` (`/compact` explícito) ou
`auto` (o Claude Code decidiu compactar). Diferente do `SessionEnd`, ele **pode bloquear** a
compactação (exit 2 ou `{"decision":"block"}`) — o ormah não usa isso, e o declara com
`async: true`, então não bloqueia nem espera.

**Nota sobre a assimetria:** `PreCompact` é `async: true` (dispara e esquece — não sofre o problema
do timeout acima), mas `SessionEnd` é `async: false` (síncrono, espera o retorno). **Só o
`SessionEnd` está exposto ao motor de duplicação.** Se isso foi deliberado, não achei o registro.

---

## Procedência — upstream ou fork?

Comparação contra `upstream/main` (2026-07-17, commit `4f66abc`, fetch do dia — Agente 7).

| problema | procedência | prova |
| --- | --- | --- |
| **0 — duas vias** | a **via do hook é UPSTREAM**; a via do watcher tem **NUANCE** — upstream já tem `session_watcher` básico, o fork acrescenta o reconcile | `upstream/main:integrations/claude-plugin/hooks/hooks.json` já tem `PreCompact` e `SessionEnd` chamando `ormah-whisper-store`, e `upstream/main:cli_adapter.py:411` já tem `cmd_whisper_store`. **Correção desta revisão:** `upstream/main` já tem `session_watcher.py` (1.009 linhas, catch-up + watcher real-time). O que é **exclusivo do fork** é o **reconcile** (`reconcile`/`_run_startup_reconcile`/`run_session_reconcile`; zero `def reconcile` no upstream; fork tem 1.411 linhas contra 1.009 no upstream). Manifests de hooks (repo × plugin instalado 0.13.3 × upstream) são byte-idênticos — `git diff upstream/main local-main -- .../hooks.json` vazio. |
| **1 — sem gate de relevância** | **UPSTREAM** | `_INGEST_LLM_PROMPT` e `## What NOT to extract` estão em `upstream/main:memory_engine.py:2609/2648`. O `_extract_memories_llm` upstream também não filtra por relevância (o loop usa `created.append`, não `extend`, mas isso é irrelevante para o gate — o pós-LLM upstream também é só `_is_duplicate_memory` + `remember`). |
| **1b — throttle / duty cycle 10%** | **FORK** | `reconcile_*`, `flush_bytes`, `catchup_concurrency`, `chunk_chars`: **zero matches** em `upstream/main:config.py`; 28 matches no fork. |
| **2 — duplicação por chunk** | **FORK** | Upstream faz `content[:max_chars]` (`memory_engine.py:2318-2319`, `ingest_max_content_chars=100000` em `config.py:267`) — **uma chamada, truncando em 100 K**. O chunking (`_split_for_extraction`, `:82`, usado em `:2786`) é do fork. |
| **3 — churn de `seq`** | **FORK, mas é melhoria** | `index/fingerprint.py` não existe no upstream. Upstream (`builder.py:149-155`) bumpa `seq` em **todo** reindex, incondicionalmente — churn pior. O fork adicionou o check de fingerprint que consertou o `#126`, mas incluiu `space`; o gatilho do `auto_cluster` existe dos dois lados (upstream `:50` save + `:60` UPDATE space). Cadeia inferida dos dois lados — mas, no fork, agora confirmada como não-causal para o backlog (ver Problema 3). |

### O erro que essa comparação corrigiu

`session_watcher_enabled: bool = False` — **idêntico no upstream e no fork** (`config.py:92`). Eu
havia lido isso e concluído que "o upstream entrega o auto-ingest desligado, logo o volume é um
problema só do André". **Errado.** A flag governa apenas uma das duas vias. **Qualquer usuário que
instale o plugin upstream auto-ingere toda sessão no `SessionEnd` e a cada `PreCompact`**, com
`session_watcher_enabled=False` o tempo todo.

**O que isso muda:** o Problema 1 não é "um bug upstream que só o uso do André revela". É um bug
que **todo usuário do plugin upstream tem**, em qualquer escala de uso. Isso o torna uma issue
upstream muito mais forte — e a evidência medida aqui (461 nós de documentação em um dia, ~29-32
começando com "The conversation/session shows") serve como reprodução.

**Lição de método:** eu tratei uma flag de config como se fosse o gate do comportamento, sem
rastrear os call-sites. A flag era um proxy; o comportamento real tinha outra porta. É o mesmo erro
que o `#145` cometeu quatro vezes seguidas — provar um proxy em vez da coisa. **Esta revisão repete
a lição uma vez, num ponto diferente:** eu também tinha concluído que "upstream não tem
`session_watcher`" a partir do fato de que a maquinaria de reconcile é do fork — sem checar se o
watcher básico (sem reconcile) já existia lá. Mesmo erro, alvo diferente.

---

## Registro de confiança

Atualizado após verificação independente por 7 agentes (2026-07-17), todos read-only (DB via
`mode=ro`, nenhum estado alterado).

**Verificado** (query/log/código lido/doc oficial, incluindo os re-medidos pelos agentes): todos os
números de nós, backlog, `seq`, cursores, spaces, duplicação de títulos, os 461 nós genéricos
(remedido; eram 442), o skip de subagentes e os 288 nós legados de subagente, a existência (não
ausência) de filtro pós-LLM por dedup semântico, o texto do prompt, as constantes do throttle e a
vazão real de ~38,5 fatias/h, a existência das duas vias e sua proporção semanal (~45%/55%, não
21%/79%), a procedência upstream×fork de cada item (incluindo a correção sobre o
`session_watcher` básico existir no upstream), os gatilhos do `SessionEnd`/`PreCompact`, o texto da
doc oficial sobre o budget do `SessionEnd` (1,5 s / 60 s / timeouts de plugin inócuos), os 5
re-posts do payload de 1,14 MB com 2 extrações completas (aritmética exata contra o log), o
timeout do httpx (135 s) contra p50/p90/max de `/ingest/conversation` (118,8 s / 905,6 s / 33,6
min — 63% e 28% acima de 60 s e 300 s), as 36 re-extrações do loop `recovering legacy mid-response
cursor`, o fix `#126` funcionando ao vivo (11.697 reescritas do Importance scorer sem bump de
`seq`), a refutação do churn como causa do backlog (99,3% dos seqs recentes são nós novos), a
contabilidade de volume por `source` fechando em zero resíduo, as 312 duplicatas hook×watcher por
embedding (com controle contra falso positivo temático), o `duplicate_merger` tendo rodado 4× em
24h (não 0), a estagnação da tabela `duplicate_checked` desde 08/07, a ausência de issues upstream
cobrindo gate de relevância ou duplicação do `SessionEnd`.

**Inferido** (segue do verificado, cadeia mostrada):

- `auto_cluster` → fingerprint → `seq` → re-enfileiramento — cadeia de código confirmada, mas
  agora sabemos que **não é a causa do backlog** (chegada > dreno é).
- Atribuição de sessão a payloads (`6206db7d`, o cálculo de ~773 memórias do loop de recovery, a
  identidade sessão→transcript nos testes de embedding) — por mtime/interleaving no log, sem
  `session_id` persistido em `nodes`/`node_tags`/frontmatter.
- O harness matar o hook do `SessionEnd` antes do POST retornar — **secundário na prática**: o
  httpx do próprio hook (135 s) já mata antes na maioria dos casos observados (63% das ingestões
  passam de 60 s).
- Regra de que conteúdo `about_self` fica sem `space`; atribuição `agent:codex` → watcher sobre
  `~/.codex/sessions`.

**Não verificado / a fazer:**

- Se o harness também mata o hook em algum caso (não decide mais nada na prática, mas seria a
  confirmação direta). Teste que decide: `SessionEnd` cronometrado ao vivo, comparando
  `whisper-cursors.json` antes/depois com a contagem de nós criados.
- Se o `SessionEnd` dispara em crash/SIGKILL — a doc oficial não documenta.
- ~~Causa raiz do loop `recovering legacy mid-response cursor` rebobinar~~ — **RESOLVIDO
  (2026-07-17, mesmo dia):** falso positivo do `leading_orphan` no padrão
  `assistant(end_turn) → assistant("API Error…") → user`, sem marker de recovery persistido;
  ver Problema 2b. Segue em aberto apenas o fix.
- Causa da estagnação de `duplicate_checked` desde 08/07 — bug de bookkeeping provável, não
  confirmado.
- Qual bloco o `claude -p` aguenta sem timeout — duração de processamento por chamada individual
  não é logada.
- O resíduo de ~50 remoções/dia sem trilha completa em `audit_log`/`merge_history` — pode ser
  diferença de query, não confirmado (Agente 6).
- Se o `synthetic_pattern_monitor` já detecta algo disso.
- Se as ~50 remoções/dia entre a manhã e a revisão (nota na seção "A pergunta da madrugada")
  explicam a diferença 990/269/39/9 → 885/233/29/9, ou se é artefato de query.

---

## Direção de fix proposta — extração holística por bloco (André, 2026-07-17)

Proposta do André: em vez de fatiar em 60 KB e mandar pedaço a pedaço, pegar a janela inteira da
conversa (ela já é JSON → vira MD/texto), mandar **o bloco completo numa única chamada** e deixar o
LLM resumir + extrair com visão do arco inteiro.

**O que acerta — o gargalo não é o tamanho do chunk, é o isolamento.** Cada chunk hoje é uma chamada
cega: extrai, esquece, vê o próximo. Daí saem os dois defeitos juntos — duplicação (mesmo fato em
fatias vizinhas) e perda de visão (nenhuma chamada vê "decisão X tomada e depois revertida"). Uma
passada única = contexto compartilhado = dedup natural + coerência. É melhoria arquitetural real. O
"virar MD" é o detalhe menor; `parse_transcript` já entrega texto limpo — o ganho é o **bloco único**.

**Onde esbarra — o teto de contexto é real, "independente do tamanho" não existe:**

| modelo | janela (aprox., não medida aqui) | cabe? |
| --- | --- | --- |
| `haiku-4-5` (default `llm_model` **e** o do André) | ~200K tok ≈ 800K chars | janela de 10 min: folgado. `SessionEnd` de 1,4 MB (~350K tok): **estoura** |
| `gemma3` local (o que o André tinha) | 128K nominal, degrada antes | conversas médias sim; deltas grandes não |
| default puro (`llm_provider="none"`) | — | **não extrai** — sem LLM server-side |

**O plano B decide o design — map-reduce:**

1. cabe na janela → **uma chamada, extração holística** (caminho feliz, quase sempre)
2. não cabe → resumir os pedaços, extrair **do resumo consolidado**

Tensão a nomear no passo 2: **resumo perde detalhe, e memória boa é feita de detalhe** (path,
versão, número, o nome do que foi rejeitado). O resumo do fallback tem de ser *preservador de
fatos*, não executivo — mais difícil do que parece.

**O que NÃO resolve — e por isso a ordem importa.** Holístico conserta duplicação e coerência, não
volume nem relevância. A sessão rich-doc inteira numa chamada ainda memoriza as centenas de linhas
de documentação da Anthropic — organizadas e sem repetir, mas ainda lixo. **Lixo coerente ainda é
lixo.** Logo: o **gate de relevância (Problema 1) vem antes** da extração holística. Fazer o
holístico primeiro é polir a coisa errada. Isso vale ainda mais agora que sabemos que o **maior**
motor de duplicação observado (Problema 2b) nem é o isolamento por chunk — é um loop de recovery
que rebobina; holístico não toca nisso.

**Forma recomendada** (quando virar plano formal, puxar `brainstorming` antes de codar):

- uma chamada por **janela** (temporal ou por sessão), não por 60 KB fixos
- **map-reduce como fallback** só quando o delta estoura a janela do modelo, com resumo preservador
  de fatos
- **depois** do gate de relevância, não antes

**A verificar antes de dimensionar:** janela real do `haiku-4-5` e o ponto de degradação do
`gemma3` (o nominal engana); a razão ~4 chars/token é aproximação padrão, não medição do corpus.

---

## Issues a abrir

Ajustado após verificação. **Nenhuma issue upstream existente cobre gate de relevância nem
duplicação via `SessionEnd`** (busca por relevance/gate/ingest/duplicate/extraction/SessionEnd/
timeout, Agente 7 — busca cobriu só esses 7 termos, pode haver falso negativo). Issues vizinhas
encontradas: `#61` about_self, `#33` re-ingestão full (fechada, resolvida por byte-cursor), `#59`
live path dropa, `#134` prompts sintéticos, `#145` setup re-wira hooks, `#137` timeout de 5s do
inject, `#73` ingest-only provider. Campo livre para as issues 1 e 2 abaixo.

**Upstream** (`r-spade/ormah`) — afetam todo usuário do plugin, não só este fork:

1. **Sem gate de relevância na ingestão** (Problema 1). Evidência: 461 nós de documentação da
   Anthropic em um dia, ~29-32 começando com "The conversation/session shows". O `SessionEnd`
   auto-ingere toda sessão para qualquer um que instale o plugin.
2. **`SessionEnd` síncrono com extração de minutos** (Problema 0) — **reformulado após
   verificação**. Não é só "se o harness mata o hook": o `timeout: 300` do manifest do plugin é
   **inócuo por design documentado** (a doc oficial diz que timeouts de plugin não sobem o budget
   do `SessionEnd`, que fica em 1,5 s / 60 s). E o cliente httpx do próprio hook (135 s) já dispara
   o motor sozinho contra uma extração de p50 118,8 s / p90 905,6 s / max 33,6 min. **`async: true`
   como o `PreCompact` já faz é paliativo** — evita segurar a sessão, mas não resolve o cursor, que
   só avança com resposta síncrona recebida. **Fix real: ingestão assíncrona** — enfileirar o job
   e avançar o cursor por confirmação de conclusão do job, não por resposta de request.
3. **Truncate silencioso em 100 K** — `content[:ingest_max_content_chars]` descarta o resto da
   sessão e o cursor avança como se tivesse extraído tudo. O fork já resolveu isso
   (`_split_for_extraction`); é um candidato natural a PR. *(Confirmado byte a byte contra o
   upstream por Agente 7 — sem mudança nesta revisão.)*
4. **Loop infinito de `recovering legacy mid-response cursor`** (Problema 2b) — **novo, prioridade
   alta, procedência corrigida para UPSTREAM** (2026-07-17: `leading_orphan` + recovery existem em
   `upstream/main:parser.py:290`, `session_watcher.py:741-745` e no caminho do hook,
   `cli_adapter.py:447`). Causa raiz diagnosticada: falso positivo do orphan no padrão
   `assistant(end_turn) → assistant("API Error…") → user`, sem marker de recovery persistido —
   loop eterno + ~530 KB de cauda nunca ingeridos. **Issue aberta:
   <https://github.com/r-spade/ormah/issues/149>** (2026-07-17).

**Fork** — não dependem de ninguém:

1. **Estagnação de `duplicate_checked` desde 08/07** — novo, achado do Agente 4. O merger continua
   rodando (4× em 24h via sleep-cycle) mas essa tabela específica de bookkeeping parou de crescer;
   causa não investigada.
2. **Throttle do watcher** (Problema 1b) — duty cycle de 10% com `claude -p` serial. Vazão real
   medida é ~38,5 fatias/h (não ~12/h como o modelo original calculava), mas o duty cycle continua
   sendo o teto.
3. **Duas vias sem coordenação de cursor** (Problema 0) — decidir se o `session_watcher` deve
   pular sessões que a via do hook já cobre. Dupla ingestão agora quantificada: ~250–500 nós
   (2,5–5% da janela sobreposta) são produto disso; custo dominante é extração paga 2×, não
   duplicata em massa.

**Removido desta lista** (era item 1 fork no doc original): **churn de `seq` via `auto_cluster`**.
Investigado a fundo (Agente 5) e **refutado como causa do backlog** — o `auto_cluster` toca 1-3
nós/hora, one-shot por nó; 99,3% dos seqs recentes são nós novos, não requeues. O backlog é
chegada > dreno (cap de 100 nós/run). Não abrir issue de churn.
