import type Graph from "graphology";
import type { FocusKind } from "../graph/sigmaReducers";

// Returns node ids whose attribute matches the legend kind/val.
// For "edge" kind, returns endpoints of matching edges.
function idsMatching(graph: Graph, kind: string, val: string): string[] {
  if (kind === "edge") {
    const ids = new Set<string>();
    graph.forEachEdge((_edge, attr, source, target) => {
      if ((attr.edgeType as string ?? "") === val) {
        ids.add(source);
        ids.add(target);
      }
    });
    return Array.from(ids);
  }
  // space / tier / role
  const attrKey = kind === "space" ? "space" : kind === "tier" ? "tier" : "selfRole";
  const ids: string[] = [];
  graph.forEachNode((id, attr) => {
    const nodeVal = (attr[attrKey] as string) ?? "";
    if (nodeVal === val) ids.push(id);
  });
  return ids;
}

// Which node ids should fitToNodes() frame for a given legend focus state?
// - focus active  → the matching nodes (zoom-to-fit on the selection).
// - focus cleared → the WHOLE graph, so re-clicking a legend returns the camera
//   to "everything visible" instead of leaving it parked on the prior focus.
export function focusFitIds(graph: Graph, next: FocusKind): string[] {
  if (!next) return graph.nodes();
  return idsMatching(graph, next.kind, next.val);
}
