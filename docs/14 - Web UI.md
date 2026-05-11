# Web UI

Verified against the current repository state on 2026-05-08.

Ormah includes a small React + TypeScript graph explorer served by FastAPI.

## Stack

- React
- TypeScript
- Vite
- Cytoscape.js
- cytoscape-cola

## Main Components

```mermaid
flowchart TB
    APP[App.tsx] --> TOP[TopBar]
    APP --> GRAPH[GraphView]
    APP --> DETAIL[NodeDetail]
    APP --> FILTER[FilterDrawer]
    APP --> SEARCH[SearchResults]
    APP --> INSIGHTS[InsightsPanel]
    APP --> ADMIN[AdminPanel]
```

## Data Flow

1. `App.tsx` loads `/ui/graph`
2. graph data is filtered client-side
3. node selection triggers `/ui/graph/node/{id}`
4. search uses `/ui/search`
5. admin actions use `/admin/*`
6. graph appearance settings are loaded from browser `localStorage`

## Implemented Visual Rules

### Appearance settings

The settings drawer includes graph appearance controls:

- dark / light theme
- core node color
- working node color
- archival node color
- reset to defaults

Settings are browser-local and persist in `localStorage` under `ormah.graphAppearance.v1`.
They are not written to Ormah server config.

### Node colors

Implemented:

- self node: teal
- identity node: darker teal
- core: configurable, default gold
- working: configurable, default light gray
- archival: configurable, default slate gray

### Edge colors

Currently special-cased:

- `supports`
- `contradicts`
- `defines`
- `evolved_from`

All other edge types currently fall back to a theme-aware generic line color.

So docs should not claim dedicated colors for `part_of` and `depends_on` unless the UI is updated to match.

### Node sizing

Node size is based on access count:

```text
24 + log2(access_count + 1) * 6
```

bounded to a minimum / maximum size, scaled by `120%`, with the self node forced a bit larger.
Labels use the same fixed `120%` display scale.

### Edge opacity

Edge opacity is derived from:

```text
max(0.2, weight or 0.5)
```

## Panels

### Settings drawer

Implemented controls:

- dark / light theme
- core / working / archival colors
- tier
- type
- space
- edge type

The drawer shows per-filter counts, but there is no separate statistics overview panel rendered there today.

### Node detail

Currently shown:

- title
- short id
- tier badge
- type
- optional space
- tags
- access count
- last accessed time-ago text
- full content
- clickable connection list

Not currently shown in the rendered panel:

- created timestamp
- updated timestamp
- importance
- confidence
- stability

### Admin panel

Currently implemented:

- fetch background tasks from `/admin/tasks`
- run one task
- run sleep cycle
- pause / resume one task
- pause / resume all

Not currently rendered:

- rebuild-index button
- stats panel, even though `fetchStats()` exists in the API layer

## API Shapes Used By The UI

The graph UI expects edge objects shaped like:

```json
{
  "source_id": "...",
  "target_id": "...",
  "edge_type": "supports",
  "weight": 1.0
}
```

`GraphView.tsx` then maps those into Cytoscape edge `source` / `target` fields on the frontend.

## Walkthrough Example

If you click a node in the graph:

1. `GraphView` reports the selected node id
2. `App` fetches `/ui/graph/node/{id}`
3. `NodeDetail` renders the node metadata, access info, and connected neighbors
4. clicking a connection loads the connected node into the same detail view

## Code Anchors

- `ui/src/components/GraphView.tsx`
- `ui/src/components/NodeDetail.tsx`
- `ui/src/components/FilterDrawer.tsx`
- `ui/src/components/AdminPanel.tsx`
- `ui/src/api.ts`
