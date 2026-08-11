# Recomendações para o Ormah como projeto open source

Data da avaliação: 13 de julho de 2026  
Branch avaliada: `local-main`  
Commit avaliado: `490a45f`  
Status deste documento: recomendação arquitetural e de produto; não é um plano de implementação.

## Contexto e decisões de produto

Esta avaliação parte de três decisões do André:

1. O Ormah deve evoluir como produto open source para outros usuários, não apenas como ferramenta pessoal.
2. Providers remotos são permitidos. Transcripts e prompts podem sair da máquina quando o usuário escolher explicitamente essa configuração.
3. Não existe hoje uma dor pessoal prioritária de recall, ruído, custo, latência ou confiabilidade. As prioridades devem ser definidas pelo risco do produto open source, não por otimizações especulativas da experiência atual do André.

Essas decisões mudam o critério de sucesso. O sistema precisa funcionar em máquinas desconhecidas, com homes, binaries, modelos, versões e históricos diferentes. Instalação, testes, recuperação e diagnóstico não podem depender do ambiente do mantenedor.

## Conclusão executiva

A stack atual deve ser mantida. SQLite, WAL, FTS5, sqlite-vec, Markdown, FastAPI, APScheduler e a arquitetura de modular monolith são adequados para um sistema local-first.

O maior risco não é escala nem escolha de banco vetorial. O maior risco é a ausência de uma fronteira durável única entre:

- arquivos Markdown;
- tabelas SQLite;
- embeddings;
- edges;
- cursores e watermarks;
- estado aprendido por feedback e manutenção.

Hoje, cada fluxo coordena esses elementos de maneira própria. Uma falha entre duas gravações pode criar estados divergentes que só aparecem muito depois, normalmente durante rebuild, restart ou manutenção.

Antes de adicionar novas features ou trocar tecnologias, o Ormah precisa tornar explícitos e verificáveis os contratos de durabilidade, progresso dos jobs, privacidade e compatibilidade ambiental.

## O que deve ser preservado

### Arquitetura local-first

O uso de um único processo, SQLite local e arquivos portáveis reduz operação, dependências externas e superfície de falha. Microservices, Redis, Celery e bancos remotos não melhorariam o produto atual.

### Markdown legível por humanos

Markdown é uma boa projeção durável para o conteúdo das memórias. Permite inspeção, edição, backup e recuperação mesmo sem executar o Ormah.

O problema não é usar Markdown; é tratá-lo como fonte completa da verdade quando parte importante do comportamento aprendido existe apenas no SQLite.

### Busca híbrida

FTS, vetores, filtros, expansão de grafo e reranking formam uma base mais rica do que busca puramente vetorial. A direção deve ser tornar os estágios mensuráveis e reproduzíveis, não substituir o pipeline sem evidência.

### Providers intercambiáveis

FastEmbed, Ollama e providers remotos são uma boa combinação para open source. O usuário deve poder escolher entre privacidade local, conveniência e qualidade/custo de modelos remotos.

## Evidências verificadas

### Estado do Beta vivo

Snapshot read-only realizado em 13 de julho de 2026:

| Métrica | Valor |
|---|---:|
| Nodes | 12.294 |
| Nodes criados entre 06 e 08 de julho | 10.023, aproximadamente 81,5% |
| Nodes com `access_count > 0` | 47, aproximadamente 0,38% |
| Edges | 25.902 |
| Edges `related_to` | 22.929, aproximadamente 88,5% |
| Proposals pendentes | 2.137 |
| Edges `contradicts` | 3 |
| Tamanho do `index.db` | aproximadamente 236 MB |

Esses números não provam, sozinhos, que a memória é ruim. `access_count` pode não representar todo uso útil, e o pico de criação foi influenciado por backfill e incidentes de ingest. Eles devem ser tratados como hipótese de economia desequilibrada, a ser confirmada por eval e telemetria melhores.

### Gates executados

- Python: 1.509 testes passaram, 9 falharam, 7 foram deselected e houve 1 warning.
- Ruff: 4 erros.
- Web UI: 82 testes passaram e o build TypeScript/Vite concluiu.
- Desktop UI: não possui script de teste.
- Rust/Tauri: não verificado porque `cargo` não estava instalado.
- Eval de whisper/recall: não reproduzível no checkout, pois o corpus golden é local e não está no repositório.
- Não existe gate de cobertura que demonstre o DoD de 100%.

As nove falhas locais observadas são host-dependent: configuração global já carregada do `.env` real, descoberta de binaries em paths absolutos e detecção do Claude Desktop no home real. Não há evidência suficiente para classificá-las como regressões do FastEmbed.

## Recomendações Must — blockers para confiança open source

### 1. Executar o plano de durabilidade vetorial já existente

O plano `.council/current-plan.md` cobre três falhas confirmadas:

- mismatch de dimensão pode apagar silenciosamente um vector store populado;
- backfill calcula todos os embeddings antes de persistir o primeiro chunk;
- um nó sem vetor pode bloquear o watermark do auto-linker.

Esse plano deve ser tratado como reliability blocker. O comportamento destrutivo continua presente no código avaliado.

### 2. Fazer o incremental updater falhar de forma segura

No fluxo atual, um ID só é considerado presente em disco depois de leitura e parse bem-sucedidos. Se o parse falha, a exceção é registrada e o ID é posteriormente tratado como arquivo deletado.

Reprodução controlada:

```text
source_file_exists: true
indexed_row_exists: false
```

Um erro transitório não deve remover a última versão boa do índice. Presença física, validade do conteúdo e remoção deliberada precisam ser estados distintos.

### 3. Corrigir a inconsistência do core cap

Os nós demovidos pelo core cap são salvos no Markdown, mas não são reindexados antes da criação do novo nó.

Reprodução com limite 2:

```text
Markdown core: 2
SQLite core:   5
```

Qualquer invariant de tier precisa ser aplicado por uma única operação que atualize todas as projeções relevantes.

### 4. Isolar completamente testes e produção

`ormah.main` configura `~/.local/share/ormah/logs/ormah.log` no import. A suíte importa o módulo e escreve eventos de fixtures no log de produção.

Foram encontrados paths de pytest e transcripts sintéticos nos logs reais. A execução da suíte durante a avaliação provocou rotação desses arquivos. Isso torna o log não confiável e pode deslocar evidência operacional legítima.

Requisitos para o isolamento:

- nenhum import deve configurar logging persistente;
- nenhum singleton global deve capturar o `.env` real durante testes;
- home, config dir, log dir, cache e binaries devem ser dependências substituíveis;
- testes devem falhar imediatamente se tentarem acessar paths reais do usuário;
- fixtures e smoke tests devem rodar em um ambiente limpo e reproduzível.

### 5. Definir a verdade durável e o contrato de backup

Backups atuais incluem `nodes/` e `deleted/`, mas excluem `index.db`. Entretanto, o DB contém estado não reconstruível somente a partir do Markdown:

- affinity;
- signals;
- whisper history e decisions;
- audit log;
- merge history;
- checked pairs;
- cursores e metadata operacional.

Uma restauração em nova máquina recupera o conteúdo das memórias, mas não tudo que o sistema aprendeu.

O projeto deve declarar três classes:

1. **Conteúdo canônico:** memórias e evidências que precisam sobreviver sempre.
2. **Estado aprendido:** feedback, affinity, histórico e decisões que precisam de backup ou export explícito.
3. **Índice derivado:** FTS, vetores e projeções que podem ser reconstruídos.

Uma direção incremental é separar estado durável de índice derivado. Backups SQLite devem usar a API de snapshot/backup do próprio SQLite, não copiar um arquivo vivo diretamente.

### 6. Fazer health medir progresso, não apenas retorno sem exceção

O endpoint de health permaneceu `ok` enquanto o auto-linker reportava backlog acima de 12 mil e zero pares avaliados.

Cada job precisa expor:

- idade do último progresso real;
- tamanho e idade do backlog;
- cursor/watermark atual e máximo conhecido;
- itens processados por execução;
- retries e dead letters;
- motivo explícito para ausência de progresso.

Um job que executa diariamente sem mover o cursor está degradado, ainda que nenhuma exceção escape.

## Recomendações Should — preparação para uma release pública

### 7. Criar uma matriz de compatibilidade real

No mínimo:

- Python 3.11, 3.12 e 3.13;
- macOS Apple Silicon e Intel quando aplicável;
- Linux x86_64 e ARM64 quando suportado;
- instalação limpa por wheel;
- upgrade entre versões;
- uninstall sem apagar memória;
- ausência e presença de Claude, Codex, Ollama e Desktop clients;
- FastEmbed cold cache e warm cache;
- recovery após kill durante ingest, merge, backfill e rebuild.

Windows deve ser declarado como suportado com CI e smoke test ou explicitamente marcado como não suportado.

### 8. Colocar todos os produtos no CI

O CI de PR deve cobrir:

- Python tests e lint;
- coverage com gate acordado;
- Web UI tests e build;
- desktop UI tests e build;
- Rust tests e lint;
- wheel build e fresh-install smoke test;
- validação de schema/migrations;
- corpus público mínimo de recall e whisper.

O DoD de 100% não deve ser apenas uma regra textual. Precisa existir instrumentação que demonstre a cobertura ou uma revisão explícita desse requisito.

### 9. Publicar uma política de egress compreensível

Como providers remotos são permitidos, o objetivo não precisa ser `local-only`. O objetivo deve ser consentimento informado.

Para cada operação, documentar:

| Operação | Dados enviados | Destino possível | Configuração |
|---|---|---|---|
| Embedding | título/conteúdo ou query | local, Ollama ou provider remoto | explícita |
| Extração de transcript | trechos de conversa | local ou provider remoto | explícita |
| Dedup/conflito/consolidação | memórias candidatas | local ou provider remoto | explícita |
| Feedback judge | prompt, resposta e memória | local ou provider remoto | explícita |

O setup deve mostrar essa matriz antes de habilitar um provider remoto. Logs não devem incluir conteúdo sensível por padrão.

### 10. Tornar documentação operacional confiável

Os documentos de arquitetura, flows e objectives estão vazios ou incompletos. A documentação da Web UI ainda menciona Cytoscape, enquanto o código usa Graphology e Sigma.

Antes de uma release pública:

- preencher o snapshot de arquitetura;
- documentar startup, ingest, recall, feedback, maintenance, backup e restore;
- documentar invariants e recovery behavior;
- automatizar ou validar links entre docs e código;
- remover exemplos e defaults que não correspondem mais à configuração atual.

### 11. Tornar eval reproduzível

O corpus real pode continuar privado, mas o repositório precisa de um corpus público ou sintético que cubra:

- recuperação factual;
- atualização de conhecimento;
- raciocínio temporal;
- multi-session;
- abstention;
- suppressão de conversa casual;
- duplicatas e near-duplicates;
- cross-space isolation;
- feedback positivo e negativo.

Mudanças em ranking, thresholds ou modelos não devem ser aceitas apenas porque os testes unitários passaram.

### 12. Revisar os 18 commits upstream antes de novas features locais

A branch avaliada está 400 commits à frente e 18 atrás de `origin/main`. Entre os commits upstream existem correções de feedback, diagnostics e performance de whisper, além de mutation stamping e snapshot criptografado.

O merge não deve ser automático, pois a divergência é grande. O valor deve ser selecionado e integrado pelo processo de beta-sync, com Council e eval.

## Recomendações Later — aprofundamento arquitetural

### 13. Durable Mutation Coordinator

Criar um módulo profundo responsável por mutações de memória. Ele registra uma intenção durável, aplica as projeções e marca a operação como concluída.

No startup, operações incompletas são repetidas ou reconciliadas. `remember`, `update`, `connect`, `delete`, `merge` e manutenção passam a compartilhar uma única semântica de escrita.

Benefícios:

- edges não desaparecem em rebuild;
- merges podem ser retomados;
- audit reflete operações realmente concluídas;
- adapters deixam de conhecer detalhes de filesystem e índice.

### 14. Embedding Index Generations

Modelo, dimensão, preprocessing e coverage devem identificar uma geração do índice.

Uma nova geração é construída ao lado da atual. Depois de validar cobertura e consistência, um ponteiro ativo é trocado atomicamente. A geração anterior pode ser mantida temporariamente para rollback.

Isso elimina a necessidade de destruir o índice ativo durante mudança de modelo ou dimensão.

### 15. Durable Work Ledger

Session watcher, auto-linker, dedup, conflict, consolidator e backfill usam conceitos parecidos, mas implementam cursores, checked pairs e retries separadamente.

Uma ledger comum deve possuir:

- idempotency key;
- unidade de trabalho;
- status pending/running/succeeded/retry/quarantined;
- tentativa e próximo retry;
- erro classificado;
- dead letter;
- timestamps de criação e progresso.

Isso resolve a classe de poison cursor sem exigir Redis ou outro broker.

### 16. Memórias com evidência e validade por afirmação

Separar:

- **episódio/evidência imutável:** transcript, evento ou observação original;
- **claim consolidada:** fato, decisão, preferência ou procedimento que pode evoluir.

Claims devem poder referenciar source range, event time, ingestion time e versão/hash da evidência. Atualizações devem criar supersession ou evolution em vez de sobrescrever silenciosamente o passado.

Essa estrutura permite expirar uma afirmação obsoleta sem invalidar outras afirmações presentes no mesmo contexto original.

### 17. Retrieval Policy traceável

O pipeline atual mistura candidate retrieval, filtros, boosts, graph expansion, rerank e injection gate em funções grandes e altamente configuráveis.

Cada estágio deveria produzir um trace reproduzível com:

- candidatos de entrada;
- motivo de inclusão/exclusão;
- score antes e depois;
- configuração e modelo utilizados;
- resultado final de injeção ou silêncio.

Isso permite ablation tests e reduz o risco de thresholds correlacionados produzirem efeitos inesperados.

### 18. Write-time Memory Gate, somente após medição

Os números do Beta sugerem que criação pode superar consumo e manutenção, mas André não relata dor atual. Portanto, não se deve alterar agressivamente a ingestão sem estabelecer uma baseline.

Depois de um eval reproduzível, o caminho pode classificar cada candidata como:

- ADD;
- UPDATE;
- SUPERSEDE;
- NOOP;
- TEMPORARY/TTL;
- QUARANTINE.

Começar com regras determinísticas e similaridade alta. Usar LLM apenas nos casos ambíguos e somente se o ganho justificar custo e variância.

## Decisões de tecnologia

### Manter SQLite + sqlite-vec

O volume atual não justifica migração. O principal cuidado é que sqlite-vec permanece pre-v1; breaking changes e migrations precisam ser tratadas como operações explícitas e reversíveis.

### Quando avaliar LanceDB

Somente se houver necessidade concreta de multimodalidade, versionamento columnar ou escala muito maior de vetores. Adotá-lo hoje criaria um segundo banco e mais uma fronteira de consistência.

### Quando avaliar Qdrant

Quando o produto deixar de ser primariamente local e passar a exigir servidor, filtros intensos, múltiplos usuários ou operação remota. Para o produto atual, o daemon e a migração de dados não se pagam.

### Quando avaliar PostgreSQL/pgvector

Somente para uma direção cloud ou multi-tenant com autenticação, quotas, concorrência e sync colaborativo.

### Não adotar agora

- Neo4j ou outro graph database;
- Redis/Celery;
- microservices;
- reescrita em Rust;
- troca do framework web;
- troca de embedding sem benchmark.

Essas mudanças não atacam as falhas verificadas.

## Métricas de produto recomendadas

Publicar no `/stats` um funil por janela temporal e por space:

```text
candidatas extraídas
  → adicionadas / atualizadas / descartadas
  → sobreviventes após consolidação
  → elegíveis para recall
  → injetadas
  → usadas ou confirmadas
  → feedback positivo / negativo
```

Complementar com:

- idade do backlog de manutenção;
- tempo até primeira recuperação de uma memória;
- diversidade de nodes injetados;
- taxa de atualização versus criação;
- taxa de abstention correta;
- custo e latência por provider;
- recovery time após restart ou falha injetada.

## Não objetivos imediatos

- transformar o Ormah em SaaS;
- suportar multi-tenancy;
- otimizar milhões de vetores;
- substituir Markdown como formato portável;
- criar novos tipos de manutenção antes de estabilizar os atuais;
- mudar ranking porque uma métrica isolada parece baixa;
- implementar sync antes de fechar o contrato de mutação e conflito.

## Critério para uma primeira release open source confiável

Uma release pública deve ser considerada pronta quando:

1. Nenhuma mudança de configuração pode apagar dados ou índices ativos silenciosamente.
2. Todos os testes rodam sem acessar configuração, store, cache ou logs reais do mantenedor.
3. Backup e restore declaram e verificam exatamente o que é preservado.
4. Jobs estagnados aparecem como degradados.
5. Instalação, upgrade e uninstall são testados em ambientes limpos.
6. Python, UI e desktop passam nos gates suportados.
7. Existe pelo menos um corpus público de regressão de memória.
8. Providers remotos possuem consentimento e política de egress explícitos.
9. Documentação e defaults correspondem ao código distribuído.
10. O usuário consegue recuperar suas memórias sem depender do serviço original ou de conhecimento interno do mantenedor.

## Priorização recomendada

Esta ordem é uma recomendação, não um plano de implementação:

1. Durabilidade vetorial e watermark.
2. Incremental updater, core cap e isolamento de testes/logging.
3. Health baseado em progresso.
4. Contrato de backup e separação entre estado durável e índice derivado.
5. Matriz de CI, fresh-install e compatibilidade.
6. Política de egress e documentação operacional.
7. Corpus público de eval.
8. Durable Mutation Coordinator e Work Ledger.
9. Proveniência temporal e Retrieval Policy.
10. Write-time Memory Gate, se o eval demonstrar necessidade e ganho.

## Referências locais

- Avaliação detalhada complementar: `docs/evaluation-2026-07-13-deep-review.md`
- Plano atual de durabilidade: `.council/current-plan.md`
- Arquitetura conceitual: `docs/00 - Ormah Overview.md`
- Modelo de dados: `docs/01 - Data Model.md`
- Storage: `docs/02 - Storage Layer.md`
- Search e ranking: `docs/03 - Search and Ranking.md`
- Background jobs: `docs/05 - Background Jobs.md`
- Embeddings: `docs/06 - Embeddings System.md`
- Eval: `docs/13 - Eval Framework.md`
- Incidente de julho: `docs/investigation-2026-07-05-node-growth-and-nodes-empty.md`

## Referências externas selecionadas

- SQLite Online Backup API: <https://www.sqlite.org/backup.html>
- sqlite-vec: <https://github.com/asg017/sqlite-vec>
- LanceDB: <https://github.com/lancedb/lancedb>
- Qdrant Local Quickstart: <https://qdrant.tech/documentation/quick-start/>
- LongMemEval: <https://arxiv.org/abs/2410.10813>
- Mem0: <https://arxiv.org/abs/2504.19413>
- Zep / Graphiti temporal memory: <https://arxiv.org/abs/2501.13956>
- HippoRAG 2: <https://arxiv.org/abs/2502.14802>

## Questões que permanecem abertas

1. Qual conjunto mínimo de plataformas o projeto deseja declarar oficialmente suportado?
2. O estado aprendido por feedback deve acompanhar backups por padrão ou exigir uma opção separada por conter prompts?
3. A longo prazo, Markdown continuará canônico ou será uma projeção exportável de um journal de mutações?
4. Qual é a política de compatibilidade para modelos de embedding e mudanças de dimensão?
5. Quais métricas de memória devem bloquear uma release e quais servem apenas como diagnóstico?

