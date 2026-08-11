# Task 5 — Verificação fim-a-fim

Confirma que a fatia 1 (active-graph-first + drill) funciona e não regrediu nada.

- [ ] **Step 1: Backend — testes do endpoint**

Run: `.venv/bin/python -m pytest tests/test_api/ -v`
Expected: PASS, incluindo os 6 testes de `test_routes_graph.py`.

- [ ] **Step 2: Backend — suite relevante + lint**

Run: `.venv/bin/python -m pytest tests/test_api tests/test_index -q`
Run: `ruff check src/ormah/api/routes_ui.py`
Expected: PASS / sem erros de lint.

> Nota: ~7 falhas pré-existentes na suite completa são ambientais (leak de `~/.config/ormah/.env`), não regressões — não tratar aqui.

- [ ] **Step 2.5: Backend — verificação manual do contrato (curl)**

Com o servidor rodando (`.venv/bin/ormah server start`), confirme o shape e o gating reais:

Run: `curl -s localhost:8787/ui/graph | python3 -c "import sys,json; d=json.load(sys.stdin); print('all_spaces' in d, len(d['nodes']), len({n['id'] for n in d['nodes'] if n['tier']=='archival'}))"`
Expected: `True <N> 0` — campo `all_spaces` presente e **zero** nós archival no default.

- [ ] **Step 3: Frontend — testes + build**

Run: `cd ui && npm run test`
Expected: toda a suite verde (api, spaceLegend, scopeLabel novos; graphModel/sigmaReducers/visual/fit/legendFit intactos).

Run: `cd ui && npm run build`
Expected: tsc + vite build sem erros.

- [ ] **Step 4: Smoke manual (`make dev`)**

Suba `make dev` e, com um store que tenha archival e ≥2 espaços, confirme:

1. **Default = active graph**: o overview NÃO mostra nós archival; o banner exibe *"Active graph · archival oculto"*.
2. **Legenda completa**: todo espaço aparece como chip (inclusive um espaço só-archival, com count 0). **F1:** se houver memória archival sem espaço, o chip "(no space)" aparece (count 0) e é drillável.
2b. **F2 (race)**: clicar drill de um espaço e logo o "voltar" em sequência rápida não deixa a UI travada no escopo errado (a última ação vence).
3. **Focus do PR#17 intacto**: clicar na *linha* do espaço ainda faz focus-fit (não recarrega).
4. **Drill**: clicar no botão `↳` de um espaço recarrega só aquele espaço **com** seus archival; banner vira *"Espaço: S · com archival"*.
5. **Voltar**: o botão *"← voltar ao active graph"* retorna ao default.
6. **Sem regressão**: zoom, legend/focus, identity rows, space legend scrollável, label haze e zoom control continuam funcionando.

- [ ] **Step 5: Cobertura de AC (checagem final)**

Confirme contra o spec (§7): default mostra self/core/working sem archival ✅; archival alcançável via drill ✅; UI comunica o modo ✅; PR#17 intacto ✅. Itens de coesão de espaço e LOD ficam para as fatias B/C (fora de escopo).

- [ ] **Step 6: Finalizar a branch**

Use `superpowers:finishing-a-development-branch` para decidir merge/PR. Lembre: feature branch a partir de `local-main`; `docs/superpowers/` é gitignored (não versionar spec/plano).
