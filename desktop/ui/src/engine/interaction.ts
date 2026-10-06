import type { GraphState } from "./types";

function nodeSize(accessCount: number): number {
  return Math.min(56, Math.max(24, 24 + Math.log2(accessCount + 1) * 6));
}

export function hitTest(
  state: GraphState,
  mx: number,
  my: number,
): string | null {
  // Iterate in reverse to pick topmost
  const nodes = Array.from(state.nodes.values()).reverse();
  for (const node of nodes) {
    if (node.opacity < 0.3) continue;
    const isSelf = node.selfRole === "self";
    const r = isSelf
      ? Math.max(18, nodeSize(node.accessCount) / 2)
      : nodeSize(node.accessCount) / 2;
    const dx = mx - node.x;
    const dy = my - node.y;
    if (dx * dx + dy * dy <= (r + 4) * (r + 4)) {
      return node.id;
    }
  }
  return null;
}

export function startDrag(state: GraphState, nodeId: string): void {
  const node = state.nodes.get(nodeId);
  if (node) {
    node.pinned = true;
    state.draggedNodeId = nodeId;
  }
}

export function updateDrag(state: GraphState, mx: number, my: number): void {
  if (!state.draggedNodeId) return;
  const node = state.nodes.get(state.draggedNodeId);
  if (node) {
    node.x = mx;
    node.y = my;
    node.vx = 0;
    node.vy = 0;
  }
}

export function endDrag(state: GraphState): void {
  if (!state.draggedNodeId) return;
  const node = state.nodes.get(state.draggedNodeId);
  if (node) {
    node.pinned = false;
  }
  state.draggedNodeId = null;
}
