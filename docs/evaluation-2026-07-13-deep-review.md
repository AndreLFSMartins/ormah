# Avaliação profunda — ormah Beta (`local-main`) — 2026-07-13

**Escopo acordado:** arquitetura & código · escolhas de tecnologia · qualidade do produto de memória · operacional. Perspectiva: **fork local / uso do André** (Beta como memória do Claude Code). Recomendações em duas camadas (incremental × estrutural). Nada vira issue/código sem sign-off.

**Método:** 4 subagentes em paralelo (auditoria de código, auditoria ops/testes, pesquisa web com ~35 URLs, inspeção read-only do Beta vivo) + verificação direta dos achados load-bearing por leitura de código. Registros: **[V]** verificado (lido/medido, fonte citada) · **[I]** inferido · **[A]** assumido/a confirmar. Snapshot do Beta: 2026-07-13 ~11:26 BRT. Nada foi mutado.

---

## 1. Sumário executivo

1. **O problema nº 1 não é tecnologia — é a economia da memória.** O store tem 12.283 nodes; **82% foram criados em 3 dias** (backfill 07-06→07-08) [V]; **apenas 41 nodes (0,33%) foram efetivamente recuperados alguma vez** (`access_count>0`) [V]; o whisper injeta em média 3 nodes/prompt (~320 tokens) [V]. A manutenção nunca alcança: backlog do auto_linker = **12.254 nodes** (praticamente o store inteiro), dedup/conflict nunca viram 99%/96,5% dos nodes, e há **2.136 merge proposals pendentes** (~89 dias de fila no ritmo atual ~) [V/I]. O sistema produz memória ~6x mais rápido do que consome.
2. **A classe de falha dominante é "falha silenciosa em background".** Todos os grandes incidentes registrados (wipe da vec table, watermark congelado, extração quebrada por TypeError) pertencem a ela. O código tem 125 `except Exception` e ~42 `except: pass` [V]; o pior deles (`db.py:387`) engole exatamente o guard que impediria o wipe.
3. **O plano `.council/current-plan.md` (r2) está 100% não executado** [V: todos os checkboxes abertos; `grep reindex_on_dim_change|allow_drop` vazio] e ataca precisamente os 3 riscos de topo. Executá-lo é a ação nº 1 — ~3 arquivos, TDD já desenhado.
4. **Tecnologia: manter tudo.** sqlite-vec (full-scan a 12k×1024 ≈ 8 ms ~), fastembed+bge-m3 (release mar/2026; re-embed de 12k é minutos), APScheduler 3.x (3.11.3 jun/2026; 4.0 alpha há ~1,5 ano). Nenhuma migração paga o custo nesta escala. O ganho vem de **ideias** dos concorrentes (mem0, Letta, claude-mem), não de troca de stack. Fontes na §5.
5. **Esta avaliação descobriu 3 problemas novos** (fora das memórias/issues conhecidas): contaminação do log de produção por processos de teste (§7.1, mecanismo verificado), classifier de intent do whisper quebrando com o adapter Ollama (§7.2), e escrita de `whisper_decisions` falhando com AttributeError (§7.3).
6. **Upstream tem valor parado:** `local-main` está 400 à frente / **18 atrás** de `origin/main` [V]; entre os 18 estão fixes diretos de whisper (#101 feedback attribution, #103 diagnostics, #104 perf) e a frente Sync v1/cloud. Avaliar merge via processo beta-sync.

---

## 2. Estado vivo do Beta (snapshot)

| Métrica | Valor | Nota |
|---|---|---|
| Serviço | `com.ormah.server.dev` running, pid 42220, up desde 10:28 | restart de hoje (incidente .env) |
| Store | 12.283 nodes · 236 MB DB · 25.870 edges | archival 85,5% · working 1.726 · core 51 |
| Edges | **88,5% `related_to`** genérico | grafo pouco informativo; `contradicts`: 3 |
| Embeddings | 12.283/12.283 (gap 0), dim 1024 | recuperado pós-incidente |
| Criação | 13–27/dia normal; **10.023 em 07-06→08** (backfill [I]) | 07-12: 0 · 07-13: 166 |
| Recall efetivo | **41 nodes (0,33%)** com `access_count>0` | consumo ≪ produção |
| Whisper (7d) | 213 prompts c/ injeção, média 3,0 nodes / ~1.291 chars | hoje: 19 inject / 52 prompts (36,5%) |
| Precisão feedback | all-time 0,748 → **7d 0,670** | em queda |
| Backlog auto_linker | watermark 333.726 vs max seq 647.803 → **12.254 nodes** | congelado (§3, hotspot c) |
| Dedup / conflict | skip-tables paradas desde **07-08**; 99%/96,5% nunca checados | throughput ≪ chegada (#81) |
| Proposals | **2.136 pending** vs ~24 aplicadas/dia → ~89 dias (~) | fila não drena |
| Duplicatas exatas | 20 títulos/41 nodes; **13x "User communicates in Portuguese (Brazil)"** | loop-redundancy do backfill |
| Órfãos | 1.034 nodes (8,4%) com 0 edges, incl. 1 core | |
| Versão | pyproject 0.13.6; metadata do editable diz 0.13.2 | cosmético, confunde diagnóstico |

**Caveat importante:** contagens de WARNING/ERROR tiradas do `ormah.log` estão **contaminadas por processos de teste** (§7.1) — os 4.649 warnings de jsonl sumido e os 15 ERRORs "observable data loss" com fixtures (`-Users-alice-Code-myproject`) são quase certamente de runs de pytest escrevendo no log de produção, não do servidor vivo [V mecanismo / I atribuição].

---

## 3. Arquitetura & código — verdictos dos hotspots

| # | Hotspot | Verdito | Evidência |
|---|---|---|---|
| a | `init_vec_table` DROPa vec table populada em mismatch de dim | **PRESENTE** | `index/db.py:379-386`; DROP dentro de `try/except Exception: pass` (`db.py:387-388`) [V direto] |
| b | Backfill de embeddings não-resumável (buffer-all-then-upsert) | **PRESENTE** | `memory_engine.py:1297-1321`: encode preenche tudo em memória antes do 1º upsert [V agente] |
| c | Nó sem vetor aborta o run do auto_linker → watermark congela | **PRESENTE** | `auto_linker.py:436-443`, `stopped=True; break`; comentário admite "blocks the watermark forever" [V direto]; sem WARNING |
| d | `_extract_json` local truncando JSON com ``` interno | **CORRIGIDO** | todos os call-sites usam `llm_client.extract_json` robusto (raw_decode fallback) [V agente] |
| e | `apply_maintenance_results` sem validação de IDs, falhas engolidas | **PRESENTE (parcial)** | `memory_engine.py:1978-2018`: IDs do LLM usados direto; 3 laços `except → logger.warning`; `counts` sem chave `failed` [V agente] |
| f | claude_cli: fallback structured_output-null + timeout_hint | **OK** | `claude_cli_adapter.py:161-172` e `:112-116` (commit HEAD 490a45f) [V agente] |
| g | Manutenção full-scan sem watermark; caps frouxos | **PRESENTE** | dedup/conflict/consolidator com `ORDER BY RANDOM()` full-scan; `duplicate_check_max_pairs_per_run=0` = **ilimitado** (`config.py:162`) [V agente] |

**Dívida estrutural** (fonte: auditoria A, verificação amostral):
- God modules: `memory_engine.py` 2.923 LOC · `setup.py` 2.246 (um instalador interativo completo dentro do pacote runtime) · `session_watcher.py` 1.405 · `context_builder.py` 946. `build_whisper_context` tem **629 linhas** no caminho quente de todo whisper.
- Ciclos `engine ↔ background` contornados com **115 imports função-level** — o grafo real de dependências está escondido.
- **Dupla fonte-da-verdade** markdown (`file_store`) ↔ SQLite sem atomicidade cruzada; `_apply_edge` grava os dois lados em operações separadas com `except → logger.debug` no lado markdown (`auto_linker.py:304-330`).
- SQLite bem feito (WAL, conexão por-thread, `RLock` global reentrante, finalizers de fd) — o `RLock` global é um teto de throughput aceitável para single-user.
- 6 config knobs de 151 **nunca lidos** fora do config: `fsrs_initial_stability`, `importance_recency_half_life_days`, `llm_api_key_env_var`, `llm_inherit_api_key`, `session_watcher_catchup_concurrency`, `working_decay_days`.

---

## 4. Testes & operações

- **Env-leak dos testes — mecanismo confirmado:** `config.py:11-20` inclui `~/.config/ormah/.env` no `env_file` e `config.py:722` instancia `settings = Settings()` **no import**. A blindagem do conftest (`conftest.py:76-86`) cobre `Settings()` criados em teste, **não o singleton** — que 13 módulos de `src/` importam. Daí os ~7 failures ambientais [V mecanismo / I contagem].
- **O leak tem uma segunda direção (nova, §7.1):** testes → produção, via logging.
- CI existe (`.github/workflows/ci.yml`: pytest + ruff em todo PR). **Eval fica fora do CI** por decisão (corpora local) — regressões de whisper/recall não têm trava automática.
- Plugin Claude Code: whisper por hook `UserPromptSubmit` → `ormah whisper inject` → POST `/agent/whisper`; PreCompact/SessionEnd → whisper store. **Fail-open totalmente silencioso**: servidor caído = zero contexto e zero gravação, sem nenhum sinal na sessão (`cli_adapter.py:287-289` etc.).
- **Sem detecção de manutenção estagnada:** `/admin/health` não sinaliza "manutenção parada há N dias" — exatamente o modo de falha dos incidentes de julho.
- `make release` local contorna o Trusted Publishing do workflow (risco de release não auditada); `install.sh` tem curl|sh duplo sem checksum; `make logs` não taila nada.
- Suíte usa **fastembed real** no fixture `engine` (não mock) — correto para fidelidade, caro em tempo; sem marker `slow` para separar.

---

## 5. Tecnologia — manter × trocar (pesquisa 2025-2026, com fontes)

| Componente | Veredito | Justificativa (fontes no relatório do agente C) |
|---|---|---|
| **sqlite-vec** | **MANTER** | 0.1.9 em mar/2026 (PyPI); brute-force a 100k×1024 ≈ 68 ms medido (Bambini); a 12k ≈ ~8 ms (~). Risco = mantenedor único com hiato em 2025; plano B barato: `sqlite-vector` (SQLite AI) ou fork vlasky — ambos continuam SQLite. LanceDB/Chroma só pagam em 1M+ vetores; Qdrant local tem teto documentado ~20k points; DuckDB VSS experimental. |
| **fastembed + bge-m3** | **MANTER** | fastembed 0.8.0 mar/2026, ativo. bge-m3 segue competitivo. Re-embed de 12k nodes ≈ minutos (~) → lock-in ~zero. Se a RAM (~2,5 GB) incomodar: EmbeddingGemma-300m (768 dims, MRL) é o candidato. Não migrar agora. |
| **APScheduler 3.x** | **MANTER** (pin `<4.0`) | 3.11.3 jun/2026; 4.0 alpha há ~1,5 ano sem migração de store. Alternativas exigem broker (Redis/Postgres) — contra o local-first. |
| **watchdog/FSEvents** | **MANTER como fallback, rebaixar de primário** | Pitfalls documentados (coalescing, thread-safety FSEvents); histórico real de bugs de catch-up no ormah. Hooks de lifecycle (SessionEnd/PreCompact, que o plugin **já usa** para whisper-store) são sinal determinístico — claude-mem prova o padrão em produção. Ver §8-B. |
| **FastAPI/uvicorn/pydantic** | **MANTER** | Sem achados. Ponte async→thread correta. |

**Ideias a roubar (ranqueadas pelo agente C):** 1) update-phase no write (mem0: ADD/UPDATE/DELETE/NOOP na hora do remember); 2) invalidação bi-temporal de edges (Zep/Graphiti); 3) hooks como ingest primário (claude-mem); 4) LongMemEval como gate de regressão; 5) sleep-time agent que **reescreve** um contexto curado por space (Letta), não só linka/deduplica.

---

## 6. Produto de memória — onde o valor vaza

O funil medido [V]:

```
criação 12.283 nodes ──► manutenção (backlog ≈ 100%; 88,5% edges genéricos;
   │                       2.136 merges na fila; dedup parado desde 07-08)
   └──► whisper (máx 6 nodes/prompt, 600 chars/node; 36,5% dos prompts injetam;
           precisão 0,75 → 0,67) ──► uso real: 41 nodes já recuperados (0,33%)
```

- **Qualidade das amostras** (25 nodes aleatórios): core/working são **bons** — atômicos, acionáveis. Os problemas: near-dups semânticos (mesma lição em EN e PT), memórias time-bound sem TTL ("retomar com Rafael…"), status-snapshots de vida curta em tier working, e o cluster 13x da preferência de idioma. A redundância grossa está **concentrada no backfill 07-06/08** — corrobora a tese (memória `ormah-dogfooding-is-valuable`) de que o problema é o loop, não o dogfooding.
- **O grafo quase não discrimina**: 88,5% `related_to`, 3 `contradicts` em 25.870 edges. O auto_linker congelado explica parte; o resto é o custo de linkar por similaridade sem tipo.
- **Classifier de intent possivelmente morto em produção** (§7.2) → whisper degradando para busca default — candidato direto para a queda de precisão 0,75→0,67 [I].
- A telemetria para melhorar isso existe (whisper_log, whisper_decisions, feedback judge, eval harness ativo) — mas decisions está falhando na escrita (§7.3) e o eval não roda em gate.

---

## 7. Bugs novos descobertos nesta avaliação

### 7.1 Log de produção contaminado por processos de teste — **[V mecanismo]**
`main.py:27-31` chama `setup_logging(..., log_file=LOG_DIR/"ormah.log")` **no nível de módulo**. Qualquer processo que importe `ormah.main` (testes de API/rotas, qualquer pytest que toque o app) anexa um RotatingFileHandler ao log **de produção** `~/.local/share/ormah/logs/ormah.log`. Evidência: fixtures (`-Users-alice-Code-myproject`, `/…/pytest-of-andre/…`) aparecem no log vivo; o state file do watcher vivo tem 0 entradas dessas [V]. Consequências: (1) métricas de erro do log são inúteis para diagnóstico do serviço; (2) esta auditoria quase concluiu "servidor ingere fixtures" — falso alarme causado pelo bug; (3) possível poluição do **store** real por testes que usem o singleton `settings` (db_path real) — **[A confirmar]** (sinais suspeitos: 164 nodes `agent:unknown`, space lixo `395`). Fix: mover `setup_logging` para dentro do entrypoint (`lifespan`/`__main__`) e/ou guardar por env; mesma família do env-leak da §4.

### 7.2 Classifier de intent quebra com adapter Ollama — **[V code path / A trigger exato]**
Assinatura no log: `Prompt classification failed, using default search: axis 1 is out of bounds for array of dimension 1` (204x no dia 13). O raise vem de `np.linalg.norm(vecs, axis=1, …)` quando `np.array(all_embeddings)` é 1-D — `ollama_adapter.py:45-47` (e o mesmo padrão em `prompt_classifier.py:260`). Isso acontece quando `/api/embed` devolve lista vazia ou ragged (ex.: input vazio). O Beta roda embeddings via **Ollama** (.env), enquanto o classifier foi calibrado com bge-base local (comentário em `prompt_classifier.py:236`). Efeito: whisper cai para busca default nesses prompts. Atribuição live-vs-teste das 204 ocorrências contaminada por 7.1, mas o code path é real em produção. Fix: guard de shape (`np.atleast_2d`, tratar `[]`) + teste de contrato do adapter.

### 7.3 Escrita de `whisper_decisions` falha com AttributeError — **[V ocorrência / root cause aberto]**
`whisper_decisions write failed: 'sqlite3.Connection' object has no attribute 'transaction'` (30x no dia 13). O call-site óbvio (`context_builder.py:304`) usa `engine.db.transaction()` com `engine.db = Database` — que **tem** `transaction`. Logo o erro vem de um caminho onde `engine.db` é uma conexão crua (eval harness? outro builder? teste via 7.1?). O `except → logger.warning("%s")` sem `exc_info` esconde o stack — o próprio catch-all impede o diagnóstico. Efeito potencial: telemetria de decisão perdida (189 rows vs 2.972 no whisper_log — parcialmente explicável pela tabela ser mais nova). Fix primeiro passo: `logger.warning(..., exc_info=True)` e observar.

### 7.4 Menores
`Forgetting manager failed` 3x hoje **com deleção armada** e error_count 0 no health (falha não sobe ao job state) — investigar antes de confiar no forgetting; metadata de versão 0.13.2 vs 0.13.6; space lixo `395` (12 nodes); 1 node core órfão; plist `com.ormah.server` (prod) presente mas aparentemente não carregado [A].

---

## 8. Recomendações

### Camada 1 — incremental (impacto × esforço; S/M/L)

| # | Ação | Esforço | Mata |
|---|---|---|---|
| 1 | **Executar o plano r2** (Tasks 0-2: guard do DROP c/ raise fora do `except`, backfill resumável, auto_linker skip+WARNING) + destravar watermark (Task 3) | M (~3 arquivos, TDD pronto) | riscos #1-#3, backlog de 12k |
| 2 | **Hermetizar o singleton `settings` + logging** — `env_file` condicionado (ex.: `ORMAH_CONFIG_DIR`), `setup_logging` fora do import; fecha o env-leak nas 2 direções (§4, §7.1) | M | ~7 failures + log contaminado + risco de store poluído |
| 3 | **`apply_maintenance_results`: validar IDs + `counts["failed"]`** | S (1 arquivo) | aplicação silenciosa de alucinação (#91) |
| 4 | **Fix shape do `encode_batch` Ollama** + teste de contrato dos adapters de embedding | S | classifier morto (§7.2) |
| 5 | **Health staleness**: `/admin/health` degrada se última manutenção bem-sucedida > N h (timestamps já existem no job_tracker) | S | classe "parado há dias sem ninguém ver" |
| 6 | **Merge dos 18 commits upstream** (whisper #101/#103/#104 primeiro) via processo beta-sync | M | precisão/diagnóstico do whisper |
| 7 | **Drenar a fila**: cap de dedup 0→finito (`config.py:162`), runs manuais controlados de proposals até zerar as 2.136 | S + operação | fila de 89 dias |
| 8 | **`exc_info=True` nos catch-alls de instrumentação** + auditar os ~42 `except: pass` (começar por `db.py:387`, consolidator, builder, main) | M | invisibilidade da classe inteira |
| 9 | Higiene: remover 6 knobs mortos · `make logs` de verdade · sinal opcional "ormah offline" no whisper-inject · marker `slow` na suíte · TTL/decay para memórias time-bound | S cada | atrito diverso |

### Camada 2 — estrutural (avaliação honesta custo × ganho)

- **A. Write-gate estilo mem0 (update-on-write).** No `remember`/ingest: top-k por similaridade e decidir ADD/UPDATE/NOOP na hora (regra simples primeiro, sim>0,9 → NOOP/UPDATE; LLM depois se o eval justificar). É o ataque **na origem** ao problema nº 1 — a manutenção noturna nunca vai alcançar um ingest sem gate. Custo M-L; ganho alto; gate por eval de recall/whisper. **Recomendo ser a primeira estrutural.**
- **B. Hooks-first ingest.** SessionEnd/PreCompact (o plugin já os usa) passam a ser o sinal primário de ingest com `transcript_path`; watchdog vira catch-up/fallback LLM-agnostic. Mata a classe FSEvents (coalescing, catch-up bugs — 2 incidentes no histórico). Custo M.
- **C. Learned-context por space (Letta sleep-time).** O sleep cycle passa a **curar um bloco condensado** por space que o whisper injeta inteiro, em vez de só top-k de nodes atômicos (teto atual: 6 nodes × 600 chars). Ataca diretamente o recall efetivo de 0,33%. Custo L; ganho potencialmente o maior da lista; exige o eval como gate. Fazer **depois** de A estancar a entrada.
- **D. LongMemEval (subset) como gate de regressão** ao lado do eval caseiro — benchmark padrão, comparável entre mudanças. Custo M.
- **E. Bi-temporalidade (Zep/Graphiti)** — `valid_at`/`invalid_at` + supersession. Elegante, mas com 3 edges `contradicts` no store hoje, a dor real ainda não apareceu. **Adiar.**
- **F. Não fazer:** migrar vector store, embeddings, scheduler ou framework web (§5) e reescrever o session_watcher do zero (B o rebaixa gradualmente).

---

## 9. O que eu faria diferente (a pergunta do André)

Como agente que usa este sistema todo dia: **as memórias que mais me ajudam são as ~30 curadas do MEMORY.md, não os 12k nodes do store.** O que as torna úteis: gancho de uma linha, causa+fix+data, e o custo de estar erradas é visível. O ormah me daria mais valor com 1/10 dos nodes e um gate de entrada mais alto do que com qualquer melhoria de busca — recuperar bem 12k memórias medianas perde para recuperar 1k excelentes. Por isso a ordem: **estancar a entrada (8-A) antes de melhorar a curadoria (8-C), antes de qualquer busca melhor.**

Segundo padrão das minhas memórias operacionais: os incidentes que custaram sessões inteiras (watermark, wipe, TypeError do claude_cli) foram todos **silenciosos por dias**. Fail-loud (camada 1 itens 1, 3, 5, 8) vale mais que qualquer feature nova — inclusive porque restaura a confiança no log/health como instrumento (hoje, §7.1, nem o log é confiável).

Métrica norte que eu adotaria: o **funil da §6** (criados → linkados-com-tipo → injetados → usados/feedback+) publicado no `/stats` — hoje cada estágio existe em separado e ninguém vê que o funil converte 0,33%.

---

## 10. Riscos & não verificado

- **[A]** Poluição do store real por testes (nodes `agent:unknown`, space `395`) — hipótese derivada de 7.1, não confirmada; checar antes de qualquer limpeza.
- **[A]** Root cause exato de 7.3 (whisper_decisions) e o trigger exato de 7.2 — ambos precisam de `exc_info`/repro.
- **[I]** Atribuição do pico 07-06/08 a backfill (padrão temporal + spaces); estimativa de 89 dias de fila assume ritmo constante; ~8 ms/query e minutos de re-embed são aritmética, não medição.
- Contagens de log por dia subcontam tracebacks multilinhas e **incluem ruído de teste** (7.1).
- Scores de benchmark de memória de terceiros (mem0/Letta/Zep) estão em disputa pública — usados como sinal, nunca como fato.
- A suíte de testes **não foi executada** nesta avaliação (regra read-only); contagens de testes são estáticas.
