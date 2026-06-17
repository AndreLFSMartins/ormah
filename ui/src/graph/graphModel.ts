import Graph from "graphology";
import type { GraphAppearance } from "../graphAppearance";
import type { GraphData } from "../types";
import {
  computeSelfRoles,
  displayNodeSize,
  edgeColor,
  nodeLabel,
  tierColor,
} from "./visual";

// Deterministic small ring seed so FA2 has x/y to start from.
// (FA2 rescales; exact seed positions don't matter, only that they exist and differ.)
function seedPosition(index: number, total: number): { x: number; y: number } {
  const angle = total > 0 ? (2 * Math.PI * index) / total : 0;
  const r = 100 + (index % 7);
  return { x: r * Math.cos(angle), y: r * Math.sin(angle) };
}

export function buildGraph(data: GraphData, appearance: GraphAppearance): Graph {
  const graph = new Graph({ multi: true, type: "directed" });
  const roles = computeSelfRoles(data.nodes, data.edges, data.user_node_id);

  data.nodes.forEach((n, i) => {
    const role = roles.get(n.id) ?? "";
    const { x, y } = seedPosition(i, data.nodes.length);
    graph.addNode(n.id, {
      x,
      y,
      size: displayNodeSize(n.access_count, role),
      color: tierColor(n.tier, role, appearance),
      label: nodeLabel(n),
      space: n.space || "",
      tier: n.tier,
      // NOTE: store the domain node type under `nodeType`, NOT `type` — sigma
      // reserves the node `type` attribute to pick the render program (e.g.
      // "circle"); a domain value like "concept" makes sigma throw
      // "could not find a suitable program for node type". See FilterDrawer type filter.
      nodeType: n.type,
      selfRole: role,
    });
  });

  for (const e of data.edges) {
    if (!graph.hasNode(e.source_id) || !graph.hasNode(e.target_id)) continue;
    graph.addEdge(e.source_id, e.target_id, {
      size: 1,
      color: edgeColor(e.edge_type, appearance.theme),
      edgeType: e.edge_type,
    });
  }

  return graph;
}

// Council M4: re-style an EXISTING graph in place (no add/remove of nodes) when
// the appearance/theme changes — so GraphView can recolor/resize without
// remounting sigma + the worker. Uses the same visual.ts functions as buildGraph.
export function applyAppearance(graph: Graph, data: GraphData, appearance: GraphAppearance): void {
  const roles = computeSelfRoles(data.nodes, data.edges, data.user_node_id);
  for (const n of data.nodes) {
    if (!graph.hasNode(n.id)) continue;
    const role = roles.get(n.id) ?? "";
    graph.setNodeAttribute(n.id, "color", tierColor(n.tier, role, appearance));
    graph.setNodeAttribute(n.id, "size", displayNodeSize(n.access_count, role));
  }
  graph.forEachEdge((edge, attr) => {
    graph.setEdgeAttribute(edge, "color", edgeColor((attr.edgeType as string) ?? "", appearance.theme));
  });
}
