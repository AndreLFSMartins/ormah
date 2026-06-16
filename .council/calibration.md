# Council Calibration Log

<!-- Peer performance per council run. Auto-generated. -->

| Data | Comando | Cursor | Codex | Rodadas | Concordância | Achados Únicos |
|---|---|---|---|---|---|---|
| 2026-06-15 | /council | ressalvas | rejeitou | 1 | parcial | 2 high convergentes LLM-None e timestamp; mais top-k bounded-recall e gaps teste |
| 2026-06-15 | /council | rejeitou | rejeitou | 1 | alta | full_rebuild nao reseta watermark (convergente+prova); MAX-seq fragil; poison no |
| 2026-06-15 | /council | rejeitou | rejeitou | 1 | concordancia alta nos criticos | cap fura conjuncao, TOCTOU pre-delete, archived_at nao duravel no rebuild e re-e |
| 2026-06-15 | /council | ressalvas | rejeitou | 1 | R1 aceito por ambos, dois criticos novos convergentes | race selecao-delete nao fechada e backfill legacy pode corromper arquivos |
| 2026-06-15 | /council | rejeitou | rejeitou | 1 | convergencia alta, TOCTOU confirmado factualmente | guard le indice obsoleto file-antes-de-DB, soft_delete nao atomico, backfill do  |
| 2026-06-15 | /council | rejeitou | rejeitou | 1 | convergencia raiz: corrida e arquitetural do write-model do engine | guard nao fecha race file-antes-de-lock, fix raiz e reordenar mutadores |
| 2026-06-16 | /council | ressalvas | ressalvas | 1 | concordância plena (peers + orquestrador) | schema-bump loops O(n) on poison node; recovery tied to optional scheduler |
| 2026-06-16 | /council | ressalvas | ressalvas | 1 | concordância plena (peers + orquestrador) | quarantine permanently drops recoverable nodes and masks incomplete store |
