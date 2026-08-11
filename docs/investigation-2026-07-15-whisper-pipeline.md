# Investigação — pipeline de whisper — 2026-07-15

**Escopo:** o que o whisper é, o que faz, como faz — e o que pode/precisa/deve melhorar.
**Método:** leitura integral do código em `local-main` + agregados somente-leitura do banco vivo
(`~/.local/share/ormah/memory/index.db`, janela de 30 dias) + testes de investigação em
`tests/test_whisper_claims_investigation.py` + experimento com o encoder vivo (bge-m3 @ Ollama,
2026-07-15) — o experimento **revisou a conclusão §1** e revelou o achado §0.
**Fora de escopo:** mudanças de código; medição de latência em produção.

## O que é

O whisper é o mecanismo de *recall involuntário*: injeta memórias relevantes no contexto do agente
antes de cada prompt, sem busca deliberada. Fluxo: hook `UserPromptSubmit` → `ormah whisper inject`
(`src/ormah/adapters/cli_adapter.py:256`) → `POST /agent/whisper` (`src/ormah/api/routes_agent.py:124`)
→ `MemoryEngine.get_whisper_context` (`src/ormah/engine/memory_engine.py:1257`)
→ `ContextBuilder.build_whisper_context` (`src/ormah/engine/context_builder.py:329`) → bloco
"# Ormah whispers" devolvido como `additionalContext`.

## Como funciona (pipeline)

1. **Hook (cliente):** lê JSON do stdin, resolve `space` pelo cwd, POST com timeout de 5 s,
   falha silenciosa em qualquer erro. Conta prompts por sessão para o *nudge* (a cada 10) e para a
   extração periódica em background (`whisper store`).
2. **Endpoint:** ring buffer em memória com os 5 últimos prompts por sessão (gap 10 min) para
   follow-ups; engine roda em threadpool.
3. **Degradação:** sem reranker carregado, roda embedding-only com gate mais conservador
   (0.60 cosseno vs 0.45 CE).
4. **Filtros de entrada:** prompt vazio/curto (≤2 alfanuméricos) → silêncio; classificação de
   intenção por similaridade a arquétipos embeddados (threshold 0.65; categorias `temporal`,
   `identity`, `continuation`, `conversational`); conversacional puro → silêncio; *topic-shift*
   (cos ≥ 0.75 vs centroide dos 3 últimos prompts) → silêncio, mas só se o tópico já foi servido
   nesta sessão (lido de `whisper_log`, sobrevive a restart).
5. **Recuperação e gating:** busca híbrida com pool fundo (6×5 = 30 candidatos; tiers core+working)
   → floor 0.45 (blend OU raw cosine) → rerank cross-encoder (linear-rescale, α = 0.6) →
   *affinity boost* (feedback aprendido por prompt-vec) → floor pós-boost 0.40 → filtro topical
   *fail-closed* (overlap de tokens ou voucher CE/cosseno) → **gate de injeção absoluto**
   (`_gate_score` = `ce_absolute` × fator de confiança × fator de espaço + afinidade, ≥ 0.45).
   Score blendado ordena; sinal absoluto decide injetar.
6. **Extras:** 1 slot de exploração (candidato reprovado no gate, sem sinal de afinidade prévio,
   rotulado `[exploring]`); canal paralelo de **preferências** com rerank de aplicabilidade próprio
   (gate 0.40, máx. 2); queries temporais reordenadas por recência; cap final 6 nós, 2 com conteúdo
   completo (≤600 chars), resto título+id.
7. **Instrumentação e feedback:** 1 linha em `whisper_decisions` por chamada (inclusive silêncios);
   1 linha em `whisper_log` por candidato com o estágio que o eliminou; `session_watcher` minera
   transcripts (heurística + LLM judge) → `signals`/`affinity` → realimenta o boost;
   `whisper_health` calcula coverage/precision; cleanup com retenção de 30 d. No 1º prompt da
   sessão, um bloco de *review* pede julgamento de um candidato retido.

## Números medidos (banco vivo, 30 dias, 2026-07-15)

| Métrica | Valor |
| --- | --- |
| Chamadas (`whisper_decisions`) | 745 — 44% injetou, 45% silêncio por gate, 11% skips |
| Intent do classificador | **93% `general`**; temporal 2×, identity 0×, conversational 10× |
| Prompts sintéticos (subagents, task-notifications, loops) | **≥17,5%** dos eventos com texto (272/1.556, padrões conservadores); **133 receberam injeção** |
| Review de sessão | **185 surfaced, 0 respondidos** (`review_log`) |
| Feedback sobre injeções | 1.293 de 2.847 com feedback (45% coverage) |
| Heurística de uso | 25% das injeções referenciadas (555 vs 1.627) |
| Afinidade acumulada | 861 positivas / 455 negativas |
| Rejeições borderline do gate | 61 a ≤0.05 do limiar de 0.45 |
| Linhas `whisper_log` presas em `candidate` | **193 — 100% co-ocorrem com preferência injetada no mesmo evento** |

## O que está bom (não mexer)

Gate absoluto vs. score relativo, filtro topical fail-closed, degradação sem reranker, topic-shift
persistido em DB, instrumentação por estágio com denominador de silêncio, e feedback loop
efetivamente fechado. O problema do whisper não é arquitetura — é calibração e duas features com
retorno zero.

## Recomendações

### DEVE (defeitos e desperdício verificados)

1. **[0] Filtrar prompts sintéticos antes de sussurrar.** O hook dispara em todo `UserPromptSubmit`,
   inclusive turnos gerados por máquina: `<task-notification>` de subagents, prompts de sistema
   (até os do próprio maintenance do ormah — "You are classifying the relationship between two
   memories…"), checks de loop autônomo. Medido: ≥17,5% dos eventos com texto são sintéticos e
   133 receberam injeção de memórias — latência e tokens gastos onde não há usuário, e
   `whisper_log`/`whisper_decisions`/feedback heurístico poluídos (injeção em subagent nunca é
   "referenciada"). Fix barato: skip por prefixo (`<task-notification>`, `<role>`, "You are",
   `# Autonomous loop`) no hook ou no endpoint. Isso também explica parte dos 45% de
   `silent_gate` e da taxa de 25% de uso referenciado.
2. **[1] Internacionalizar as frases temporais (regex) — o classificador NÃO é o gargalo.**
   Os regexes temporais (`_TIME_KEYWORDS`, `prompt_classifier.py:81`) são 100% inglês: "ontem",
   "semana passada", "últimos 3 dias" não são detectados, então uma query temporal PT-BR que o
   classificador acerta ainda recebe a janela default de 3 dias (em vez de 48h→24h para "ontem")
   e não tem o ruído temporal removido da query de busca.
   *Prova em runtime:* `tests/test_whisper_claims_investigation.py` (§1, unit).
   **Revisão do experimento com o modelo vivo (bge-m3, 2026-07-15):** os arquétipos EN atuais já
   classificam prompts PT-BR cross-língue — 14/16 acertos (temporal 0.78–0.96, identity
   0.79–0.94). Arquétipos PT-BR sobem para 15/16 e ampliam as margens (temporal → 1.00, identity
   "onde eu moro?" 0.56 → 0.95 — o único MISS de identity corrigido). Ou seja: adicionar
   arquétipos PT-BR é um upgrade de margem, não um resgate; o item obrigatório são os regexes.
   Os 93% de `general` na produção se explicam por mix real de prompts (comandos de código são
   `general` corretos) + prompts sintéticos (item [0]), não por falha do classificador.
   *Prova em runtime:* `test_live_bge_m3_classifies_ptbr_against_en_archetypes` (integration).
3. **[2] Desligar ou repensar o review de sessão.** 185 blocos, 0 respostas — custo de tokens em toda
   sessão nova, retorno zero. O cap de exaustão é por nó (3 não-respondidos), mas com 16 k nós há
   sempre outro candidato: o fluxo é infinito por construção. Agravantes encontrados depois
   (2026-07-15, caso real com 2 abas): `_find_review_candidate` não filtra por `space` nem por
   sessão — a seleção é global por score (`context_builder.py:80-111`), então uma sessão de código
   recebe para julgar uma retenção de outra aba/projeto (ex.: prompt de `/council`), sem contexto
   para responder; e o gatilho "primeira mensagem" é na verdade "primeira mensagem após 10 min de
   pausa" (o buffer podado devolve `recent_prompts=None`, `routes_agent.py:160-174`), então o
   bloco dispara mais de 1× por sessão. Sugestão: kill-switch global por rendimento
   (auto-desativar após N surfaced sem resposta) ou mover para o ciclo de maintenance; se mantido,
   escopar por `space` da sessão atual.
4. **[3] Corrigir instrumentação do merge de preferências.** Em
   `src/ormah/engine/context_builder.py:941-950`, resultados topicais deslocados por
   `room_for_main` são cortados **antes** do `_mark_removed` do cap e ficam
   `decision_stage='candidate'` para sempre (193 casos no banco vivo, 100% correlacionados).
   *Prova em runtime:* `tests/test_whisper_claims_investigation.py` (§3).

### PRECISA (confiabilidade/observabilidade)

1. **[4] Medir latência e detectar entregas fantasma.** Não há medição de duração no pipeline; o hook
   tem timeout de 5 s com falha silenciosa, mas o servidor registra `was_injected=1` /
   `outcome=injected` mesmo quando o hook já descartou a resposta. Isso contamina `whisper_health`
   e o judge heurístico (injeção nunca entregue vira "unreferenced"). Mínimo: cronometrar o
   endpoint e logar; ideal: hook confirmar entrega.
2. **[5] Calibração contínua do gate.** 61 rejeições em 30 d a ≤0.05 do gate (0.45, tunado uma vez em
   2026-07). `max_gate_score` já é logado — um sweep periódico cruzado com o feedback de afinidade
   diria se o gate está caro demais. Relacionado (*inferido, não medido*): o reranker
   `ms-marco-MiniLM` é treinado em inglês; para prompts/memórias PT-BR o `ce_absolute` (que decide
   o gate) é de qualidade duvidosa — vale A/B com um reranker multilíngue (ex.:
   `bge-reranker-v2-m3`).

### PODE (custo/manutenção)

1. **[6]** Canal de preferências roda um 2º rerank CE em praticamente todo prompt, com ~6% de
   aproveitamento (115 injetadas vs 1.667 rejeitadas no gate de aplicabilidade). Cache por
   sessão/tópico ou skip em follow-ups cortaria latência.
2. **[7]** `build_whisper_context` tem ~820 linhas num método só; as closures de trace são
   sintoma. Extrair os estágios em funções facilita o item [3] e futuros tunings — refactor puro.

## Verificação por testes

`tests/test_whisper_claims_investigation.py` — artefato de investigação (mesmo padrão de
`test_proposal_claims_investigation.py`): cada teste afirma o **comportamento atual** que sustenta
uma alegação deste doc, com mensagem indicando a promoção a teste de regressão quando o item for
corrigido. Cobertos: item [1] (frases temporais PT-BR invisíveis aos regexes; janela default
errada para "ontem"; e — via `test_live_bge_m3_classifies_ptbr_against_en_archetypes`, marcado
`integration`, requer Ollama vivo — a prova de que o classificador acerta PT-BR cross-língue com
bge-m3) e item [3] (candidato deslocado por preferência fica sem estágio final). Execução
2026-07-15: **6 passed** (5 unit + 1 integration). Itens [0], [2], [4] e [5] são alegações de
dados do banco vivo/design — verificadas por consulta SQL, não unit-testáveis.

O experimento completo (16 prompts PT-BR × arquétipos EN vs PT-BR, encoder vivo) está em
`scratchpad/ptbr_classifier_experiment.py` da sessão; resultado: EN 14/16, PT-BR 15/16, margens
temporal 0.96→1.00 e identity 0.56→0.95 no caso "onde eu moro?".

## Riscos e não-verificados

- Números vêm do banco vivo (30 d) e do código em `local-main`; o pipeline não foi executado
  ponta-a-ponta nem houve medição de latência real — a hipótese de timeout do hook é plausível,
  não confirmada.
- ~~Eficácia de arquétipos PT-BR com bge-m3 não testada~~ — **verificado em 2026-07-15** com o
  encoder vivo: EN já classifica PT-BR cross-língue (14/16); PT-BR amplia margens (15/16).
  André confirmou (2026-07-15) que o servidor Beta usa bge-m3 — a conclusão vale para a produção.
- A cota de prompts sintéticos (17,5%) usa padrões de prefixo conservadores — o número real é um
  piso, não um teto; e `retrieval_events` só existe para chamadas com candidatos, então a fração
  sobre o total de chamadas pode diferir.
- O default de fábrica (`BAAI/bge-base-en-v1.5`, inglês-only) muda o custo/benefício do item [1]
  para o upstream; o ganho depende do encoder de cada instalação.
