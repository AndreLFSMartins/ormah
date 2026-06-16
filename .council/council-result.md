# Council Result — 2026-06-16 (R2, plano revisado)

## Decisão: ❌ Requires changes — recomendo trocar a quarentena por um design mais simples (sem exclusão permanente).

## Perfis de Review: architecture, performance | Peers: Cursor | Codex | Rodadas: 1 (2ª invocação)

## Resumo do Debate
Segunda rodada sobre o plano revisado (quarentena + fallback + completeness). Ambos os peers convergiram de novo, sem divergência entre si. Cursor: "Requires changes". Codex: "needs-attention / No-ship". Concordam que o R1 matou o loop O(n) (C1), mas que **a quarentena introduziu um problema pior**: exclusão permanente de nós recuperáveis, mascarada como "store completo". Como Senior Dev concordo — o fix do R1 trocou um problema por outro.

## O que foi aceito
Todos os achados. O ponto central: **quarentena ≠ completo**, e ela não tem path de recuperação.

## Achados por Severidade

### 🔴 Críticos — bloqueiam implementação
- **C2 — Quarentena é exclusão permanente disfarçada de completude** (Codex crit; Cursor #1). Nós em `embedding_quarantine` saem do delta **e** do alvo de completude. Sem un-quarantine (em sucesso, mudança de conteúdo/`file_hash`, fingerprint de encoder/schema, TTL ou retry admin), uma falha transitória (Ollama instável por N ticks) some o nó da busca para sempre. Pior: uma queda sustentada do encoder faz **todos** os nós falharem por `max_attempts` ticks → store inteiro quarentenado → `embedding_gap==0`, job "ok", schema "atual" — degradação silenciosa total. O teste `test_schema_bump_quarantines_poison_node_without_looping` codifica exatamente o comportamento que o foco adversarial proíbe.

### 🟡 Importantes — devem ser endereçados
- **I5 — "Verificado contra `vec_count`" não está implementado** (Cursor #2). O overview afirma I2, mas o bump usa só `missing == 0` do anti-join; `_embed_node_rows` apenas loga drop silencioso do vec0. Ou implementa `vec_count >= embeddable_count` no critério, ou para de afirmar.
- **I6 — JobTracker verde com quarentenados sem vetor** (Cursor #3). `missing` exclui quarentenados → health "ok" com vetores ausentes.
- **I1b — Fallback é one-shot, não recuperação contínua** (Codex high; Cursor #4). Se a única thread de fallback falha (encoder down no startup), não há retry até restart/sleep-cycle. Precisa loop com backoff até `embedding_gap==0` ou estado degradado explícito.
- **I7 — Schema mode reprocessa todos os não-quarentenados a cada tick** até completar (~75 min se o encoder oscila com 9k nós). Após a 1ª passagem, schema mode deve usar o mesmo anti-join do delta.

### 🟢 Menores — opcionais
- Caminho feliz híbrido (delta síncrono curto no startup quando schema == atual) — sugestão de redução de janela; não adotado para manter bind não-bloqueante.

## O que foi rejeitado e por quê
Nada rejeitado. Sobre o fix do Codex (fingerprint completo + TTL + admin retry): aceito a **essência** (recuperabilidade), mas evito a complexidade — ver Plano Final.

## Plano Final (recomendação do Senior Dev — trocar abordagem na Task 03)
Abandonar a quarentena-como-completude. Design mais simples que fecha C2 + C1 + I5 + I6 + I7 de uma vez:
1. **Schema bump:** re-embarca todos numa **única** passagem; para cada nó que falha no encode, **deleta o vetor stale** (vira genuinamente `missing`); avança a versão **incondicionalmente após a passagem**. Sem loop O(n): ticks seguintes são delta.
2. **Delta (recorrente):** anti-join embarca só os `missing` — barato, O(gap), **a cada tick para sempre**. Um nó genuinamente poison continua `missing` e é re-tentado O(1)/tick, **nunca descartado, nunca mascarado**.
3. **`embedding_gap` é a verdade** (anti-join). Um silent drop do vec0 vira `missing` → re-tentado (I5 resolvido sem check separado). Sem quarentena, sem `embeddable_count` redefinido.
4. **Health (I6):** job reporta non-ok enquanto `embedding_gap > 0` após sua run — um poison node aparece como degradado honesto (operador corrige conteúdo/modelo).
5. **Fallback (I1b):** loop com backoff (ex.: até `embedding_gap==0` ou N tentativas) na thread daemon, em vez de one-shot. Teste: scheduler falha + 1ª backfill falha + 2ª sucede.
6. Remover settings/test de quarentena (`embedding_schema_max_attempts`, teste poison vira "poison fica visível em gap, não some").

Trade-off honesto: um nó permanentemente não-embeddable mantém `embedding_gap > 0` e health degradado — **visível e correto**, em vez de silenciosamente escondido.

## Próximos passos
Decisão do André: adotar o redesign (sem quarentena) e atualizar Tasks 02/03/06/09/10 + overview, depois (opcional) um último `/council` ou seguir para implementação. Evitar mais um ciclo de revisão sem sinal do André — convergência já clara.
