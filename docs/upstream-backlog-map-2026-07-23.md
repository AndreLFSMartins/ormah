# Mapa do backlog upstream — local-main vs r-spade/ormah

**Data:** 2026-07-23 · **Base:** `upstream/main` = f8ff9d7 (ativo, commit há 5 dias) · **Beta:** `local-main` = 7cd15cb

## Números

- local-main está **497 commits à frente, 0 atrás** → superset linear limpo (upstream é ancestral estrito; nenhum conflito a reconciliar, só volume).
- **168 arquivos** divergem: **97 novos** (não existem upstream) + **71 modificados**.
- **+21.947 / −3.429 linhas.**
- **Nada de segredos/.env/credenciais** no diff rastreado (verificado).

## Áreas de código (arquivos)

| Área | Modificados | Novos | Nota |
|---|---|---|---|
| `src/ormah` core | 35 | 11 | ingestão, engine, index, config, dedup |
| `ui/src` + `ui/playwright` | 8 | 29 | galaxy/graph UI (auto-contido) |
| `tests/*` | ~20 | ~40 | cobertura das features acima |
| `eval/*` | 0 | 11 | harness de avaliação (maintenance/relevance) |
| `scripts/` | 0 | 2 | cleanup_auto_ingested (dogfooding) |

## Clusters temáticos (por commit scope / issue)

1. **Pipeline de ingestão** (~120 commits): `session-watcher` (68), `ingest` (29), `background` ingest, `parser` (5) — ADR-0003 orphan (#149), ADR-0004 async spool (ADR-0004/#150), byte-cursor (#32/#33). **O mais emaranhado**: a slice-1 senta em cima de ~600 linhas de divergência Beta anterior em session_watcher/parser/main. Só contribuível como STACK ordenada.
2. **Manutenção / sleep-cycle** (~40): `background` maintenance, `dedup` (8), `auto-linker` (4) — #26, #81, #87, #90 (bounding, batching, dedup timestamp).
3. **Galaxy UI** (24 commits, 33 arquivos novos): #22 — **o mais contribuível limpo** (auto-contido, arquivos novos, não toca o core upstream).
4. **Setup/install hardening** (18 fix): instalador — moderadamente isolado.
5. **Engine/index/embeddings** (~40): #28 e outros.
6. **Cross-cutting**: `config` (7), `security` (6), `lifecycle` (6) — mistura de contribuível + tuning Beta.

## Contribuibilidade

- **Limpo / baixa fricção:** Galaxy UI (#22), eval harness, setup hardening. Arquivos majoritariamente novos, pouco overlap com o core upstream.
- **Moderado:** maintenance/dedup, engine/index — tocam `background`/`engine` que o upstream tem, mas em blocos coerentes.
- **Difícil / stack ordenada:** o pipeline de ingestão (session-watcher → parser → spool). 100+ commits interleaved; extração exige re-aplicar por área numa branch cortada de upstream/main, **não** cherry-pick commit-a-commit.
- **Beta-específico (NÃO contribuir cru):** `config.py` defaults de tuning (provider=claude_cli, pares/call), `scripts/cleanup_auto_ingested.py`, ajustes de `.gitignore`.

## Ordem sugerida de fatias (se a decisão for contribuir)

1. **Galaxy UI (#22)** — auto-contido, prova o fluxo fork→PR sem risco no core.
2. **Setup hardening + eval harness** — isolados.
3. **Manutenção/sleep-cycle (#26/#81/#87)** — engine/background.
4. **Pipeline de ingestão (#32 → #149 → ADR-0004)** — a stack grande, por último, como sequência de PRs dependentes.

## CORREÇÃO (2026-07-23) — o backlog JÁ está contribuído

A afirmação inicial deste doc de que "nada foi contribuído" estava **errada**: confundia
*mergeado* com *submetido*. `upstream/main` estar 0-atrás mede o que o **r-spade mergeou**,
não o que o André submeteu.

Estado real (verificado via `gh pr list --repo r-spade/ormah --author AndreLFSMartins`):
- **20 PRs abertas** em `REVIEW_REQUIRED`, cobrindo quase todos os clusters acima:
  #31→#28, #38→#32, #68→#52, #79 (claude_cli), #92→#90, #95→#87, #116, #119, #120, #121,
  #127→#126, #128→#106, #129→#84, #130→#83, #131→#63, #133→#81, #141→#134, #146→#143,
  #147 (setup), **#153→#149 (ADR-0003)**.
- **14 PRs mergeadas** na história.

**Conclusão:** NÃO há merge gigantesco à frente. O trabalho já está decomposto em ~20 PRs
independentes cortadas de `upstream/main`. O gargalo é a **fila de review do r-spade** (lenta),
não a contribuição do André. Cada PR mergeada faz upstream avançar → local-main reconverge
naquela peça. A divergência de 497 commits é o Beta rodando à frente enquanto a fila drena —
"converging downstream" funcionando, não um fork abandonado.

**A slice-1 (ADR-0004) é a única peça deliberadamente Beta-only**, porque empilha sobre ~5 PRs
ainda não-mergeadas (#153, #79, #68, #38). Vira uma PR limpa quando essas dependências
aterrissarem. Regra permanente: OPEN em r-spade/ormah ≠ trabalho a fazer — é a fila de review.
