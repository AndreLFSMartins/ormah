# Handoff — ADR-0004 slice 3 (`no_safe_boundary`): plano revisado 5×, nada implementado (2026-07-28)

Chat em **PT-BR**; código/commits/ADRs em **English**.

**Nada foi implementado, commitado, ou branchado.** Esta sessão foi inteira de diagnóstico +
planejamento + revisão adversarial. O repo está intocado em `local-main` @ `bfc34fa`.

## O documento que importa

`/Users/andre/.claude/plans/delightful-pondering-lake.md` (367 linhas) — o plano, já com **cinco
rodadas** de achados incorporados. Cópia sincronizada em
`/Users/andre/.council/state/r-spade-ormah-683b05e/current-plan.md`.
**Não re-derive dele o que já está escrito.** Este handoff cobre só o que o plano não diz.

| artefato | onde |
|---|---|
| Plano (fonte) | `/Users/andre/.claude/plans/delightful-pondering-lake.md` |
| Council result (rodada 2, a última consolidada) | `~/.council/state/r-spade-ormah-683b05e/council-result.md` |
| Outputs brutos dos peers | `~/.council/state/r-spade-ormah-683b05e/runs/*/round-1-{cursor.md,codex.json}` |
| Revisão final do Codex (fora do council) | `codex resume 019fa94f-b759-7463-8d49-99078bfd5e5c` |
| Handoff anterior (content-budget, **track separado**) | `<outro-scratchpad>/handoff-ormah-content-budget-2026-07-27.md` |

⚠️ Este arquivo está em `/tmp` e pode ser auto-deletado. Se o trabalho continuar, mover para o repo
— há memória registrada de que André prefere handoffs repo-tracked.

## O que foi decidido (não re-litigar)

1. **André quer resolução automática.** Ele rejeitou explicitamente a recomendação do council de
   mover a recuperação para fora do hot path: *"tem que ser resolvido automaticamente… é melhor
   perder um pequeno pedaço do que travar tudo e perder o resto."* O plano implementa isso.
2. **Corrigi uma premissa dele e ele manteve a decisão:** nada trava e o "resto" não se perde — o
   safe boundary já ingere 99,5% (mediana). O risco real do force-close ingênuo era **duplicação
   em massa**, não perda. Ele decidiu prosseguir mesmo assim, com as mitigações do plano.
3. **Branch sai de `local-main`, não de `upstream/main`.** Verificado: `upstream/main` não contém
   `ingest_spool.py` nem `no_safe_boundary` (521 commits atrás). Beta-only por impossibilidade.
   André tinha escolhido `upstream/main` antes dessa verificação.

## Diagnóstico — medido, não estimado

O `no_safe_boundary` **não é perda de dados**. 549 transcripts dead-lettered de 609 entradas no
state = **90% de todas as sessões**; é o caminho *normal* de encerramento. Cauda nunca fechada:
**1,02 MB no total, mediana 998 B** — a última linha aberta do JSONL, que
`src/ormah/transcript/parser.py:895-900` declara intencionalmente não-ingerida. Perda com conteúdo:
31 parciais (pior: 15 turnos) + 8 "totais" que são sessões **sem nenhuma resposta do assistente**.
Todos os `.jsonl` intactos no disco. A pergunta UNVERIFIED do handoff anterior está respondida:
**nada reprocessa esses bytes** — `_mark_frozen_prefix_consumed` avança o cursor exatamente para
impedir isso (`cursor == boundary == size` em toda a amostra).

## Bug ATIVO no Beta, descoberto aqui — anterior a esta branch

`~/.local/share/ormah/logs/ormah.log`: **42** ocorrências de
`"recovering legacy mid-response cursor"` entre 10:47:51 e 11:14:41 de 2026-07-28, todas no **mesmo**
transcript (`-Users-andre-Documents-Obsidian-AndreMartins/c13fd7d1-…jsonl`), a cada ~30-60 s. Não é
contaminação de pytest (path real do vault, não `tmp_path`). É o loop que a própria ADR-0003
descreve. Impacto medido: 291 nós criados hoje / 291 fingerprints distintos ⇒ **zero duplicatas
exatas**; o custo confirmado é retrabalho (re-parse + re-extração LLM por tick).
**NÃO VERIFICADO: duplicação semântica** — re-extrações geram textos levemente diferentes, com
fingerprints diferentes, que a contagem não captura. Vale investigar separadamente.

## As 5 rodadas — o que cada uma matou

Cada correção sobreviveu à rodada seguinte apenas para ser derrubada pela outra. Padrão claro:
**o watermark resolve duplicação e cria perda; a ordem errada troca um pelo outro.**

1. Force-close puro no drain ⇒ `leading_orphan` → `should_rewind` → re-ingestão do arquivo inteiro.
2. Watermark só no commit do force-close ⇒ `mark_frozen` e o skip path ainda plantavam cursor
   mid-response sem marca.
3. Plano contradizia a si mesmo sobre `mark_frozen` ⇒ com watermark, viraria **perda silenciosa**.
4. Linha stale completava sem enfileirar sucessor (`reconcile` é gated em `discover`; raiz
   acceptance-only nunca varre) + linha "não idle → TRANSIENT" era falsa e causaria retry storm.
5. **(Codex, o mais valioso)** TOCTOU: job fresco na classificação vira stale entre o retorno de
   `_ingest_session` e a mutação do cursor ⇒ perda **permanente**. Reenquadramento: `mark_frozen`
   nunca deveria ter avançado o cursor — *"não re-selecionar" ≠ "consumido"*. Agora é
   `parked_until`, cursor intacto. Mais: a atomicidade ledger↔`_commit_state` que eu prometia é
   **impossível** (dois arquivos, um só `os.replace`) ⇒ disposição vive dentro do state entry.

**Todos os achados foram verificados por mim no código antes de aceitar** — nenhum foi aceito pela
palavra do peer. As citações `file:line` no plano são todas conferidas.

## Estado da revisão — leia antes de assumir que está aprovado

- **Nenhuma versão do plano tem aprovação.** Todas as rodadas terminaram `needs-attention`.
- Cursor revisou a penúltima versão; Codex revisou a anterior às **três últimas correções**
  (park/`parked_until`, ledger no state, `_commit_state` como choke point). **Essas três são minhas,
  verificadas no código, mas não revisadas por ninguém.**
- O último `/council` terminou com **gate bloqueado** (`codex:BLOCKED`). Não consolidei
  `council-result.md` nem calibrei como aprovado, conforme o protocolo fail-closed.

## Armadilhas que vão te morder

- **`/council` com Codex estoura o timeout** (3× seguidas, ~570 s, plano de ~300 linhas). Solução
  verificada: `codex-companion.mjs task --background --effort high "<prompt>"`, pollar
  `status <job-id> --json` (`.job.status == "completed"`), colher com `result <job-id>`. Levou 7 min.
  No prompt, **liste o que NÃO re-litigar** — rende achados novos em vez de repetição.
- **Nunca edite `current-plan.md` entre a resposta do peer e a consolidação.** O plan-gate compara
  sha256 com o `plan_receipt`; editar invalida a revisão e bloqueia o gate. Aconteceu uma vez aqui.
- **`Tools/ormah` É o Beta vivo** — nunca `git checkout` de branch lá. Use worktree nova.
- **O log de produção recebe escrita do pytest.** Antes de tratar qualquer linha como evidência do
  serviço, confirme que o path é real (vault/projects) e não `tmp_path`.
- **pytest sem `PYTHONPATH` pinado exercita o `src` do clone principal** (pacote editable). Sempre
  cheque `rootdir` na saída antes de confiar em contagem.
- O plano tem **367 linhas** — acima do limite de 200 do `CLAUDE.md` global. Se for dispatchar
  subagentes, divida em overview (≤100) + um arquivo por tarefa antes.

## Pendências — a decisão está com André

Ele foi perguntado e **não respondeu**: dividir o plano em overview + tarefas, mandar o Codex
revisar a versão atual em background, ou partir direto para os testes vermelhos. Nada avança sem
essa escolha.

Depois disso, a sequência do plano: worktree de `local-main` → council-a…k vermelhos → implementar
→ `/council-pr` (comando do André, o controller não invoca) → merge sem squash → backfill (altera o
Beta vivo, exige autorização na hora).

## Suggested skills

- **`superpowers:test-driven-development`** — o plano define council-a…k como gate; todos devem
  nascer vermelhos.
- **`superpowers:using-git-worktrees`** — obrigatório: o clone principal é o Beta vivo.
- **`superpowers:verification-before-completion`** — o modo de falha desta sessão inteira foi
  afirmação à frente da evidência, dos dois lados.
- **`superpowers:writing-plans`** — se dividir o plano em overview + tarefas.
- **`graphify`** — política do repo: `graphify query` antes de grep/leitura de fonte (o hook cobra).
- Comandos, não skills: **`/council`** (plano) e **`/council-pr`** (pré-merge) — ambos do André.
