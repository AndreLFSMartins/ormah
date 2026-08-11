# Investigação — o loop de rewind de cursor do #154 (2026-07-30)

Doc em **PT-BR** (segue `docs/handoff-2026-07-28-no-safe-boundary.md`); código/commits/ADRs em **English**.

**Nada foi implementado, commitado ou branchado nesta sessão.** Repo intocado em `local-main` @
`fa5d044`, `src/` limpo, nenhum worktree modificado. O servidor foi pausado e religado duas vezes
(para medição, com autorização) e está **parado** ao fim da sessão, a pedido.

## TL;DR

O ingest não é lento por causa do modelo, do Ollama ou do JSON. **Um único transcript estático foi
reprocessado 1.671 vezes** porque o cursor do `session_watcher` **retrocede** — ciclo determinístico
de período 2. É a issue [#154](https://github.com/r-spade/ormah/issues/154), **mal caracterizada**
como "one-shot". Nenhuma branch local fecha o loop, incluindo `feat/adr-0004-slice3-force-close`
com suas 7 rodadas de council.

---

## 1. Fontes consultadas (inventário exato)

| # | arquivo | o que forneceu |
|---|---|---|
| F1 | `~/.local/share/ormah/logs/ormah.log` — 3.135 KB, 19.873 linhas | todas as métricas de produção da §2 |
| F2 | `~/.claude/projects/-Users-andre-Documents-Obsidian-AndreMartins/c13fd7d1-9005-4cf9-bf29-f6520d4eabd6.jsonl` — 175.919 B, 70 linhas, mtime **2026-07-28 10:34** | o transcript em loop; entrada de toda reprodução |
| F3 | `~/.config/ormah/.env` — 43 linhas | config efetiva (o `.env` do repo **não existe**; o launchd aponta para `~/.config/ormah/ormah-server-dev`) |
| F4 | `~/Library/LaunchAgents/com.ormah.server.dev.plist` | `StandardOutPath=/tmp/ormah-dev.out`, que levou a F1 |
| F5 | `src/ormah/background/session_watcher.py`, `src/ormah/transcript/parser.py` | o call-site do rewind e `should_rewind` |
| F6 | `docs/adr/0003-recovery-drops-orphan-fragment.md` | a decisão que este bug atravessa |
| F7 | `docs/handoff-2026-07-28-no-safe-boundary.md` | contexto; contém uma afirmação hoje desatualizada (§6) |
| F8 | `~/.claude/plans/delightful-pondering-lake.md` — 367 linhas | o plano do slice 3, incl. a linha 154 do gate |
| F9 | issue #154 via `gh issue view 154 --repo r-spade/ormah` | a caracterização "not a loop" |
| F10 | 5 worktrees (§5) | as branches testadas por execução |

Rotacionados presentes e **não** analisados: `ormah.log.1`, `.2`, `.3` — a janela abaixo cobre só
`ormah.log`.

**Aviso de metodologia:** o log de produção **também recebe escrita do pytest**
(`setup_logging` no import de `main.py`). Toda linha usada como evidência aqui tem path real de
vault/projects, nunca `tmp_path`. Além disso, os números cresceram durante a própria sessão — o
servidor rodou entre a primeira e a última leitura. **Todos os valores abaixo são de uma releitura
única e final**, janela `2026-07-29 12:57:30 → 2026-07-30 08:34:24`.

---

## 2. O que o log de produção mostra

Extração (roda contra F1, imprime só agregados):

```python
import pathlib, re, collections, statistics, datetime
p = pathlib.Path.home() / ".local/share/ormah/logs/ormah.log"
lines = p.read_text(errors="replace").splitlines()

pat = re.compile(r"ingested (\S+) \((\d+) new turns?, (\d+) memories extracted")
files, mem, turns = collections.Counter(), collections.Counter(), collections.Counter()
for l in lines:
    m = pat.search(l)
    if m:
        files[m.group(1)] += 1; mem[m.group(1)] += int(m.group(3)); turns[int(m.group(2))] += 1
print(files.most_common(3), turns.most_common(4))

g = [l[:23] for l in lines if "POST http://localhost:11434/api/generate" in l]
ts = [datetime.datetime.strptime(x, "%Y-%m-%d %H:%M:%S,%f") for x in g]
d = [(b - a).total_seconds() for a, b in zip(ts, ts[1:]) if 0 < (b - a).total_seconds() < 600]
print(len(g), statistics.median(d), sorted(d)[int(len(d) * .9)], max(d))
```

### Resultado

| métrica | valor |
|---|---|
| ingests logados | 1.703 |
| arquivos distintos ingeridos | **11** |
| **do mesmo arquivo (F2)** | **1.671 (98,1%)** |
| memórias criadas a partir de F2 | **529** |
| fatias com `1 new turns` | 1.694 (**99,5%**) |
| `recovering legacy mid-response cursor` | **986** |
| `0 memories extracted` | 1.287 |
| `chunk … returned no result` | 3.568 |
| `extraction deferred (provider-wide)` | 1.785 |
| `claude -p exited 1` | 1.973 (29/07 12:57 → 18:51) |
| `Ollama call failed` 404 | 143 (30/07 05:30 → 08:31) |
| mediana entre `/api/generate` (n=595) | **21,7 s** (p90 28,9 s; máx 159,8 s) |

**Custo:** 1.671 × 21,7 s ≈ **10,1 h de GPU** num arquivo parado desde 28/07.

O outro lado da conta: F2 destilado é uma conversa de **3.949 chars ≈ 987 tokens e 2 turnos de
usuário** — o resto dos 175.919 B é anexo, tool call e metadado. As 529 memórias saíram dessa
conversa de dois turnos.

### Linhas verbatim que sustentam cada número

```
2026-07-29 14:08:45,392 [ormah.background.session_watcher] INFO: Session watcher ingested -Users-andre-Documents-Obsidian-AndreMartins/c13fd7d1-9005-4cf9-bf29-f6520d4eabd6.jsonl (1 new turns, 0 memories extracted, 0 signals recorded)

2026-07-29 12:59:33,541 [ormah.background.session_watcher] INFO: Session watcher recovering legacy mid-response cursor for -Users-andre-Documents-Obsidian-AndreMartins/96e2a4cd-8ae8-413a-8c47-faa3cf246ecb.jsonl

2026-07-29 12:57:32,321 [ormah.engine.memory_engine] WARNING: ingest extraction: chunk 1/1 (233 chars) returned no result — whole slice retryable (partial result discarded)

2026-07-29 12:57:32,321 [ormah.background.session_watcher] WARNING: Session watcher extraction deferred (provider-wide) for /Users/andre/.claude/projects/-Users-andre-Documents-Obsidian-AndreMartins/b2d00516-550a-42d8-b919-a6bf5fa8a503.jsonl: Server-side extraction call returned no result (provider configured — likely a timeout or error; see the adapter log). Will retry.

2026-07-30 05:30:39,647 [ormah.background.llm.ollama_adapter] WARNING: Ollama call failed: Client error '404 Not Found' for url 'http://localhost:11434/api/generate'

2026-07-29 12:57:30,450 [ormah.background.llm.claude_cli_adapter] WARNING: claude -p exited 1:
```

**O ciclo, contíguo no log** — ingest, rewind, ingest de novo, ~20 s de intervalo:

```
2026-07-29 17:58:49,595 [ormah.background.session_watcher] INFO: Session watcher ingested …/c13fd7d1-….jsonl (1 new turns, …)
2026-07-29 17:59:09,707 [ormah.background.session_watcher] INFO: Session watcher ingested …/c13fd7d1-….jsonl (1 new turns, …)
2026-07-29 17:59:09,713 [ormah.background.session_watcher] INFO: Session watcher recovering legacy mid-response cursor for …/c13fd7d1-….jsonl
2026-07-29 17:59:27,184 [ormah.background.session_watcher] INFO: Session watcher ingested …/c13fd7d1-….jsonl (1 new turns, …)
```

### Como o arquivo culpado foi identificado

Não por suspeita — por agregação. O `Counter` por path (código acima) devolveu 11 arquivos
distintos, e o primeiro sozinho responde por 98,1% das chamadas. Os outros 10 tiveram ≤ 8 chamadas
cada.

### Por que `min_turns=5` não segura

`session_watcher_min_turns` é 5 por padrão, mas o gate é ignorado quando a sessão está ociosa
([session_watcher.py:923](../src/ormah/background/session_watcher.py#L923)) — e um arquivo parado há
dois dias está sempre ocioso. Daí os 99,5% de fatias com um único turno. O aproveitamento acompanha
o tamanho do lote:

| turnos na fatia | fatias | produziram memória |
|---|---|---|
| 1 | 1.694 | 22,8% |
| 2 | 6 | 66,7% |
| 3 | 2 | 100% |
| 4 | 1 | 100% |

---

## 3. Causa raiz

Em [session_watcher.py:871-895](../src/ormah/background/session_watcher.py#L871-L895) o rewind de
recuperação é **autorizado por um parse e executado por outro**:

- o **probe** decide *se* há algo a recuperar e é deliberadamente **não-capado** (comentário nas
  linhas 880-885: um parse capado "mis-parkearia" um arquivo grande);
- o **drain** que efetivamente grava o cursor é **capado** em `flush_bytes`.

Nada verifica que o drain ultrapassa o cursor original. Com F2:

```
cursor anterior ................................. 174707
parse(174707, cap 60k) → orphan=True, safe_end=174707  → should_rewind = True
probe  parse(0)         → safe_end = 175795  > 174707  → autoriza
drain  parse(0, cap 60k)→ safe_end =  86732            → GRAVADO
                                    RETROCESSO = 87.975 bytes
```

No tick seguinte o cursor sobe de 86732 para 174707 e o ciclo recomeça. O gatilho é permanente nos
bytes: um `assistant(stop_reason=end_turn)` seguido de outro `assistant` com texto, sem `user` entre
eles ([parser.py:351-353](../src/ormah/transcript/parser.py#L351-L353)).

### Por que #154 subestima o problema

A issue afirma:

> "It is **not a loop** — one re-ingest per affected transcript, cursor monotonic afterwards; the
> background dedup jobs absorb the duplicates."

Isso vale **só para transcript menor que `flush_bytes`**. O fixture da issue tem 363 B: o re-parse
completo cabe no cap, alcança EOF, o cursor fica monotônico e parka. Acima de `flush_bytes` (60.000)
o drain não alcança EOF, o cursor retrocede, e a mesma causa vira loop permanente. A segunda
afirmação também não se sustentou — o dedup não absorveu as 529 memórias (tem backlog próprio, #81).

---

## 4. Como os testes foram feitos

Três métodos independentes, do mais barato ao mais caro.

### 4.1 Separar fila de inferência — refuta "trocar para llama.cpp"

O Ollama devolve `total_duration`, `load_duration`, `prompt_eval_duration` e `eval_duration` em
`/api/generate`. Define-se **GAP = total − load − prefill − decode**: o tempo que não é inferência.
Rodar a mesma bateria com o serviço no ar e com ele parado isola contenção.

```python
import urllib.request, json
def gen(model, prompt, npred=64, fmt=None):
    p = {"model": model, "prompt": prompt, "stream": False, "think": False,
         "options": {"num_predict": npred}, "keep_alive": "20m"}
    if fmt: p["format"] = fmt
    req = urllib.request.Request("http://localhost:11434/api/generate",
        data=json.dumps(p).encode(), headers={"Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=900))
    ns = lambda k: d.get(k, 0) / 1e9
    tot, load, pe, ev = ns("total_duration"), ns("load_duration"), ns("prompt_eval_duration"), ns("eval_duration")
    return tot, pe, ev, tot - load - pe - ev      # o último é o GAP
```

Parar / religar o serviço (é launchd `KeepAlive`; matar o PID não basta):

```bash
launchctl bootout gui/501/com.ormah.server.dev
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.ormah.server.dev.plist
```

| cenário | prefill | decode | GAP | total |
|---|---|---|---|---|
| serviço NO AR, prompt curto + `format:json` | 0,18 s | 0,21 s | **17,43 s** | 17,94 s |
| serviço NO AR, 6k tok, cache quente | 0,13 s | 2,66 s | **24,92 s** | 27,85 s |
| **serviço PARADO**, prompt curto + `format:json` | 0,18 s | 0,20 s | **0,00 s** | **0,49 s** |
| **serviço PARADO**, prompt curto sem json | 0,18 s | 0,12 s | **0,00 s** | **0,41 s** |
| **serviço PARADO**, 3.777 tok in / 36 out | 0,20 s | 1,47 s | **0,01 s** | **1,6 s** |

- **O overhead de 20–27 s era 100% fila.** O runner do gemma3 roda com `-np 1` (slot único) e o ormah
  fazia 54 `/api/generate` + 304 `/api/embed` a cada 25 min.
- **`format:"json"` custa ~0,1 s** (0,41 → 0,53 s). "Grammar cara" refutada.
- Throughput do `gemma3:12b-it-qat` no M5 Pro: **prefill 640–706 tok/s, decode 21–27 tok/s**.
- **O Ollama 0.32.5 já executa o `llama-server` do llama.cpp** — do `ps`:
  `/Applications/Ollama.app/Contents/Resources/llama-server … -c 32768 -np 1 -b 1024 -ub 1024
  --cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on --mmproj … --context-shift --keep 4`.

### 4.2 Reproduzir o loop no nível do parser (sem LLM, sem engine)

Chamar `parse_transcript`/`should_rewind` direto, replicando o fluxo das linhas 850-935. Reproduziu
o ciclo de período 2 em 12 ticks contra F2:

```
tick   prev_off  safe_end  rewind  -> novo cursor
1             0     86732   False          86732
2         86732    174707   False         174707
3        174707     86732    SIM           86732  [REWIND p/ 0]
4         86732    174707   False         174707
…ciclo
```

**Fixture sintético equivalente** (não depende de dado pessoal): 6 pares
`user`/`assistant(end_turn)` + `user` + `assistant(end_turn)` + `assistant(end_turn)`, com
`flush_bytes=2000` → 10.073 B. Resultado: `tick 6: 8045 → 9878` / `tick 7: REWIND, probe=10073,
drain=1609` **(retrocesso)** / `tick 8: 1609 → 3218`. É o candidato natural a teste de regressão.

Condição necessária que o fixture revelou: o registro órfão precisa **fechar** quando lido a partir
de 0 (`stop_reason=end_turn`). Com um órfão que nunca fecha, o guard pós-rewind parka corretamente —
caso já coberto pela ADR-0003. Foi por isso que a primeira versão do fixture (órfão com
`stop_reason=None`) **não** reproduziu.

### 4.3 Reproduzir end-to-end e testar cada branch — `tick_sim.py`

Dirige o `_ingest_session` **real** por N ticks, com `ingest_llm_generate` mockado (sem GPU) e
`PYTHONPATH` pinado na árvore sob teste. Pinar é obrigatório: sem isso o pacote editable exercita o
`src` do clone principal, e todas as branches "passariam" idênticas.

```bash
PYTHONPATH=<worktree>/src \
  /Users/andre/Documents/GitHub/Tools/ormah/.venv/bin/python tick_sim.py <label> <transcript>
```

```python
"""tick_sim.py — dirige _ingest_session por N ticks e reporta o movimento do cursor."""
import os, sys, shutil, tempfile, json
from pathlib import Path

label = sys.argv[1]
src_transcript = Path(sys.argv[2])

tmp = Path(tempfile.mkdtemp(prefix="ticksim-"))
os.environ["ORMAH_HOME"] = str(tmp / "home")
os.environ["ORMAH_LLM_PROVIDER"] = "ollama"          # configurado, mas a chamada é mockada
os.environ["ORMAH_INGEST_LLM_PROVIDER"] = "ollama"
os.environ["ORMAH_INGEST_LLM_MODEL"] = "stub"
os.environ["ORMAH_EMBEDDING_PROVIDER"] = "local"
os.environ["ORMAH_SESSION_WATCHER_ENABLED"] = "false"

from ormah.background.session_watcher import _ingest_session
from ormah.engine.memory_engine import MemoryEngine
from ormah.config import Settings
from unittest.mock import patch

watch = tmp / "projects" / "-test-space"
watch.mkdir(parents=True)
target = watch / src_transcript.name
shutil.copy2(src_transcript, target)          # copy2: preserva o mtime -> is_idle=True
rel = f"{watch.name}/{target.name}"

engine = MemoryEngine(Settings())
state: dict = {}
_LLM_RESPONSE = json.dumps({"memories": [
    {"content": "stub memory", "type": "decision", "title": "stub", "tags": ["t"]}]})
llm_calls = {"n": 0}

def _fake_llm(*a, **k):
    llm_calls["n"] += 1
    return _LLM_RESPONSE

prev = None
for tick in range(1, 15):
    with patch("ormah.background.llm_client.ingest_llm_generate", _fake_llm):
        res = _ingest_session(engine, target, state, watch.parent, min_turns=5,
                              idle_threshold=600.0, flush_bytes=60000)
    entry = state.get(rel, {})
    cur = entry.get("end_offset")
    extra = {k: entry[k] for k in ("force_closed_until", "parked_until") if k in entry}
    back = " <<< RETROCESSO" if prev is not None and cur is not None and cur < prev else ""
    print(f"tick {tick:2d}  result={res.name:<12} cursor={cur}  llm={llm_calls['n']} {extra}{back}")
    prev = cur
shutil.rmtree(tmp, ignore_errors=True)
```

**Duas armadilhas, uma iteração perdida cada:**

1. Com `ORMAH_LLM_PROVIDER=none` o watcher **defere** (`extraction deferred (provider-wide)`) e o
   caminho do cursor nunca é exercitado — precisa de provider configurado **e** chamada mockada.
2. `shutil.copy2` (não `copy`) para preservar o mtime. Sem isso o arquivo parece recém-escrito,
   `is_idle` vira False, e o gate de `min_turns` muda o fluxo inteiro.

Saída em `local-main` (o que roda no Beta hoje) — 14 ticks, 14 chamadas LLM:

```
tick  6  result=OK  cursor=174707  llm=6  {}
tick  7  result=OK  cursor=86732   llm=7  {} <<< RETROCESSO
tick  8  result=OK  cursor=174707  llm=8  {}
tick  9  result=OK  cursor=86732   llm=9  {} <<< RETROCESSO
```

---

## 5. Matriz de branches locais (executadas, não lidas)

Inventário via `git branch -vv` + `git worktree list`; conteúdo inspecionado com `git grep <termo>
<branch>` e `git show <branch>:<path>` — **sem `git checkout`**, porque `Tools/ormah` é o Beta vivo.

| árvore | comportamento em 14 ticks | LLM |
|---|---|---|
| `local-main` @ `fa5d044` (Beta vivo) | loop período 2: **174707 ↔ 86732** | 14 |
| `feat/adr-0004-slice3-force-close` @ `8f4ed84` | **loop idêntico**; `force_closed_until` fica `{}` | 14 |
| `feat/relevance-gate` @ `e17818c` | cursor **travado em 86732** desde o tick 1, re-extrai sempre | 14 |
| `feat/ingest-content-budget` @ `c773cb3` | não testável: `_ingest_session` sem `flush_bytes` (API antiga) | — |
| `fix/leading-orphan-progress-guard` @ `4b6a9ac` | não testável: sem `ingest_llm_generate` (é a ADR-0003 já mergeada) | — |

### Por que o slice 3 não pega

O gate que ele adiciona (linha 1253 na branch):

```python
if should_rewind(result, prev_offset) and prev_offset > (existing or {}).get("force_closed_until", 0):
```

O orphan do #154 é **natural**, não produto de um force-close — logo `force_closed_until` nunca é
plantado (`{}` em todos os 14 ticks, verificado na saída) e o gate passa. O bloco interno (probe
não-capado + drain capado) é **byte-a-byte idêntico** ao de `local-main`, confirmado por
`git show feat/adr-0004-slice3-force-close:src/ormah/background/session_watcher.py`. O watermark
protege contra o rewind que o *próprio force-close* provocaria; o loop pré-existente é ortogonal.

---

## 6. Correção de registro

`docs/handoff-2026-07-28-no-safe-boundary.md` afirma: *"Nada foi implementado, commitado, ou
branchado."* **Desatualizado.** O slice 3 tem **9 commits** (feature + council R1→R7) em
`feat/adr-0004-slice3-force-close`, worktree em `~/Documents/GitHub/Tools/ormah-wt-adr4-s3`, com
`force_closed_until` (14 ocorrências), `parked_until` (13) e `crosses_unsafe` (6) em `src/`.

Em `local-main` esses três termos têm **0 ocorrências** — o slice 3 não foi mergeado.

---

## 7. Hipóteses refutadas

| hipótese | veredito | evidência |
|---|---|---|
| llama.cpp seria mais rápido que o Ollama | **refutada** | o Ollama 0.32.5 *é* o `llama-server` (`ps`) |
| o modelo (`gemma3:12b-it-qat`) é o gargalo | **refutada** | 3.777 tok in + 36 out em 1,6 s sem contenção |
| `format:"json"` / grammar é caro | **refutada** | 0,41 s → 0,53 s |
| o custo é prompt grande / prefill | **refutada** | GAP fixo ~25 s, independente do tamanho do prompt |
| trocar de modelo resolveria | **não testada, e irrelevante** | o custo dominante não é inferência |
| o slice 3 fecha o loop | **refutada** | executado: comportamento idêntico ao `local-main` |
| o `404` em `/api/generate` era o bug | **refutada** | `/api/generate` responde 200 hoje; foram janelas |

---

## 8. Recomendação

Quatro commits já atacaram essa família (`3790324`, `705be38`, `4b6a9ac`, `fb5569d`) e o bug
reapareceu em forma nova a cada um. O handoff de 28/07 nomeia o padrão: *"cada correção sobreviveu à
rodada seguinte apenas para ser derrubada pela outra"*. Isso é sinal de arquitetura, não de hipótese
errada — um quinto gate pontual tende ao mesmo destino.

Raiz comum: **o cursor pode retroceder, e a decisão de rewind é derivada dos bytes em vez de estado.**

O plano do slice 3 já tem a peça certa e a condicionou estreitamente: as linhas 90-102 colocam a
regra dentro de `_commit_state` como invariante estrutural, *"não uma convenção que a próxima pessoa
precisa lembrar"*. A sugestão é **desacoplar essa invariante do `crosses_unsafe`**: `_commit_state`
rejeita qualquer `end_offset` menor que o atual, salvo `allow_rewind=True` explícito — que o backfill
(item 5 do plano) já precisaria, pois rebobina de propósito. Uma regra fecha os três modos de falha
da matriz da §5.

O argumento da ADR-0003 contra estado persistido ("adiciona um novo campo de state para persistir e
migrar") caducou: a ADR-0004 já introduziu `skipped_slices`, `extract_fail_offset` e
`extract_fail_count` na mesma entrada.

Ordem de prioridade por custo real:

1. **O loop (#154).** 98% do custo. Sozinho transforma horas em minutos.
2. **`min_turns` no caminho idle** — 99,5% das fatias com 1 turno, aproveitamento de 22,8%.
3. **`-np` > 1** (via `OLLAMA_NUM_PARALLEL`, **não verificado** na 0.32.5) — elimina a fila.
4. **Tirar o `claude_cli` do caminho** — 1.973 falhas puras.

Flags de llama.cpp (`-ub 2048`, KV em f16 com 64 GB, sem `--mmproj`) vêm depois, e o ganho é
controle de configuração, não velocidade de motor.

---

## 9. Não verificado / em aberto

- Se F2 é o **único** transcript em loop. Os outros 10 do log tiveram ≤ 8 chamadas, mas a janela
  cobre ~20 h e os `ormah.log.{1,2,3}` não foram analisados. Um sweep pelo state completo do watcher
  responderia.
- **Os 143 `404` em `/api/generate` vão até 2026-07-30 08:31**, e `/api/generate` responde 200
  quando testado manualmente. Não expliquei o padrão — pode ser um segundo problema.
- A causa do comportamento de `feat/relevance-gate` (cursor travado, re-extração infinita).
  Reprodutível 13/13 ticks, mas a branch pode estar em desenvolvimento.
- Se a monotonicidade pura quebra algum caminho legítimo além do backfill — os quatro call-sites de
  `_commit_state` não foram auditados sob essa ótica.
- Se as 529 memórias são duplicatas semânticas ou variações — não amostradas. O handoff de 28/07
  registrou 291 nós / 291 fingerprints distintos (zero duplicatas **exatas**) e deixou a duplicação
  semântica explicitamente em aberto.
- **Nenhuma suíte de testes foi executada em nenhuma branch**: testou-se comportamento, não regressão.
- `OLLAMA_NUM_PARALLEL` não foi verificada na versão instalada.

---

## 10. Reprodução mínima

```bash
# 1. o loop, no código que roda no Beta hoje
PYTHONPATH=/Users/andre/Documents/GitHub/Tools/ormah/src \
  .venv/bin/python tick_sim.py local-main \
  ~/.claude/projects/-Users-andre-Documents-Obsidian-AndreMartins/c13fd7d1-9005-4cf9-bf29-f6520d4eabd6.jsonl

# 2. o mesmo loop na branch do slice 3
PYTHONPATH=/Users/andre/Documents/GitHub/Tools/ormah-wt-adr4-s3/src \
  .venv/bin/python tick_sim.py slice3 <mesmo arquivo>

# 3. baseline limpo de inferência (exige o servidor parado)
launchctl bootout gui/501/com.ormah.server.dev
#   … medir GAP via /api/generate (§4.1) …
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.ormah.server.dev.plist
```

Health é `GET /admin/health` — **não** `/health`, que cai no catch-all da SPA e devolve HTML com 200.
