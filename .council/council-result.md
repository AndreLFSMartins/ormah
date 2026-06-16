# Council Result — 2026-06-16

## Decisão: ❌ Requires changes — arquitetura aprovada, robustez do schema-bump + independência do scheduler precisam de rework antes de implementar.

## Perfis de Review: architecture, performance | Peers: Cursor | Codex | Rodadas: 1

## Resumo do Debate
Ambos os peers convergiram sem divergência entre si. Cursor: "Requires changes". Codex: "needs-attention / No-ship". Concordam que o plano resolve bem o problema central (re-embed síncrono O(n) no startup → delta O(gap) + job de reconciliação), mas que o **modo schema-bump** e a **garantia de recuperação** têm falhas concretas no vetor adversarial pedido. Como Senior Dev, aceito os dois achados consequentes — são gaps reais que o próprio plano introduz.

## O que foi aceito
- **Pontos positivos confirmados:** separação startup vs. reconciliação (padrão `tracked()`/`JobTracker`/sleep-cycle já existente); delta com anti-join O(gap); bump de versão só após sucesso corrige o bug atual de `memory_engine.py:134-138`; chunking+checkpoint reaproveita mitigação #18/#19; retry em `_index_embedding`; `next_run_time` pós-bind.
- **Findings aceitos:** todos os 7 (2 consequentes + 5 de robustez/observabilidade/doc) — ver abaixo.

## Achados por Severidade

### 🔴 Críticos — bloqueiam implementação
- **C1 — Schema-bump entra em loop O(n) permanente com 1 nó "poison"** (Codex crit 0.94; Cursor #1). Enquanto `stored_version < _EMBEDDING_SCHEMA_VERSION`, cada tick faz `SELECT ... FROM nodes` (todos N) e só bumpa se `failed == 0`. Um único nó que falha deterministicamente (encoder instável, conteúdo problemático) impede o bump para sempre → re-embed de todos os N a cada tick. É exatamente o custo O(n) que a mudança deveria eliminar. *Fix:* quarantine/retry-budget por nó; avançar a versão quando as falhas restantes estão todas em quarentena; ticks seguintes re-embarcam só `missing ∪ failed`, não todos os N. Teste com 1 nó poison provando que a 2ª run não reprocessa N.

### 🟡 Importantes — devem ser endereçados
- **I1 — Recuperação depende de scheduler tratado como opcional** (Codex high 0.9; Cursor #4). `lifespan` (main.py:67-68) engole falha de `start_scheduler`; sem scheduler = sem backfill = degradação indefinida. *Fix:* fallback one-shot independente do scheduler após o bind (thread daemon disparando `backfill_embeddings`), ou marcar health degradado com recuperação manual explícita. Teste de `start_scheduler` falho com vetores faltando.
- **I2 — Critério de sucesso do schema-bump ignora drops silenciosos do sqlite-vec** (Cursor #2). `failed==0` não cobre `vec_count < len(all_items)`; o plano remove a verificação que existia em `_reindex_all_embeddings`. *Fix:* bumpar só se `failed==0 AND vec_count >= embeddable_count`; reintroduzir o check de contagem.
- **I3 — Janela de degradação pós-restart sem SLA nem teste E2E** (Cursor #3). *Fix:* teste de integração (engine + `start_scheduler` + gap → recupera) e expor `embedding_gap`/`embedding_schema_version` em `stats()`/health.
- **I4 — JobTracker reporta sucesso com backfill incompleto** (Cursor #5). *Fix:* `run_embedding_backfill` retorna status não-ok / levanta quando `failed>0` ou `vec_count<embeddable_count`.

### 🟢 Menores — opcionais
- **m1 — Nós com texto vazio ficam no delta para sempre** (Cursor #6). *Fix:* excluir texto-vazio do anti-join (ou marcar `unembeddable` em meta) — necessário para o completeness check de I2.
- **m2 — "startup() não toca o encoder" é falso** (Cursor #7). `_warmup_embedder()` ainda roda no startup. *Fix:* corrigir redação; opcionalmente mover warmup para o thread pós-bind.
- **Sugestão de escala:** trocar `NOT IN (subquery)` por `LEFT JOIN ... WHERE v.id IS NULL` no anti-join.

## O que foi rejeitado e por quê
Nada rejeitado — todos os achados aceitos. Não houve necessidade de Rodada 2: peers concordam entre si e o orquestrador concorda com eles (sem rebuttal).

## Plano Final
Arquitetura mantida (delta + job de reconciliação). Revisões a aplicar antes de implementar:
1. **Task 03 (schema-bump):** quarentena de IDs com falha + retry budget; avanço de versão por completeness verificado (`vec_count >= embeddable_count` e falhas restantes em quarentena); ticks seguintes embarcam só `missing ∪ failed`.
2. **Task 02 (`_embed_node_rows`):** reintroduzir verificação `vec_count`; retornar também o gap; excluir texto-vazio (`embeddable_count`).
3. **Nova Task (main.py):** fallback one-shot pós-bind independente do scheduler (thread daemon) quando `start_scheduler` falhar.
4. **Task 06 (job):** status não-ok em backfill incompleto para o JobTracker/health.
5. **Nova Task (observabilidade):** `embedding_gap` + `embedding_schema_version` em `stats()`/health + teste E2E de recuperação.
6. **Docs:** corrigir redação do warmup; anti-join via LEFT JOIN.

## Próximos passos
Aprovar as revisões → atualizar as task files (03, 02, 06 + 2 novas) → rerun rápido de `/council` opcional sobre o plano revisado, ou seguir direto para implementação via subagent-driven-development.
