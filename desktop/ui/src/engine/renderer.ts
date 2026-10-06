import { COLORS } from "@/lib/constants";
import type { GraphState, GraphNode, GraphEdge, Tier, SelfRole, EdgeType } from "./types";

function tierColor(tier: Tier, selfRole: SelfRole): string {
  if (selfRole === "self") return COLORS.nodeSelf;
  if (selfRole === "identity") return COLORS.nodeIdentity;
  switch (tier) {
    case "core": return COLORS.nodeCore;
    case "working": return COLORS.nodeWorking;
    case "archival": return COLORS.nodeArchival;
    default: return COLORS.nodeWorking;
  }
}

function tierBorderColor(tier: Tier, selfRole: SelfRole): string {
  if (selfRole === "self") return COLORS.nodeSelfBorder;
  if (selfRole === "identity") return COLORS.nodeIdentityBorder;
  switch (tier) {
    case "core": return COLORS.nodeCore;
    case "working": return COLORS.nodeWorkingBorder;
    case "archival": return COLORS.nodeArchivalBorder;
    default: return COLORS.nodeWorkingBorder;
  }
}

function edgeColor(type: EdgeType): string {
  switch (type) {
    case "supports": return COLORS.edgeSupports;
    case "contradicts": return COLORS.edgeContradicts;
    case "defines": return COLORS.edgeDefines;
    case "evolved_from": return COLORS.edgeEvolved;
    default: return COLORS.edgeDefault;
  }
}

function edgeGlowColor(type: EdgeType): string {
  switch (type) {
    case "supports": return COLORS.edgeGlowSupports;
    case "contradicts": return COLORS.edgeGlowContradicts;
    case "defines": return COLORS.edgeGlowDefines;
    case "evolved_from": return COLORS.edgeGlowEvolved;
    default: return COLORS.edgeGlowDefault;
  }
}

function nodeSize(accessCount: number): number {
  return Math.min(56, Math.max(24, 24 + Math.log2(accessCount + 1) * 6));
}

export function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

export function render(
  ctx: CanvasRenderingContext2D,
  state: GraphState,
  dpr: number,
): void {
  const w = state.width * dpr;
  const h = state.height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  // Vignette overlay for text readability
  const vignetteGrad = ctx.createRadialGradient(
    state.width / 2,
    state.height / 2,
    state.height * 0.25,
    state.width / 2,
    state.height / 2,
    state.height * 0.85,
  );
  vignetteGrad.addColorStop(0, "rgba(10, 10, 10, 0)");
  vignetteGrad.addColorStop(0.7, "rgba(10, 10, 10, 0.15)");
  vignetteGrad.addColorStop(1, "rgba(10, 10, 10, 0.5)");
  ctx.fillStyle = vignetteGrad;
  ctx.fillRect(0, 0, state.width, state.height);

  // Starfield — fixed speckles scattered like a night sky
  const starCount = 120;
  for (let i = 0; i < starCount; i++) {
    // Hash-based pseudo-random positions (no visible patterns)
    let h = i * 2654435761; // Knuth multiplicative hash
    h = ((h >>> 16) ^ h) * 0x45d9f3b;
    h = ((h >>> 16) ^ h) & 0x7fffffff;
    const rx = (h & 0xffff) / 0xffff;
    const ry = ((h >>> 8) ^ (i * 7919)) & 0xffff;
    const px = rx * state.width;
    const py = (ry / 0xffff) * state.height;

    // Gentle twinkle — each star on its own slow cycle
    const twinkle = Math.sin(state.time * 0.0006 + i * 3.7) * 0.5 + 0.5;
    const size = i % 7 === 0 ? 1.6 : 1.0;
    const alpha = 0.15 + twinkle * 0.2;

    ctx.beginPath();
    ctx.arc(px, py, size, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(212, 165, 116, ${alpha})`;
    ctx.fill();
  }

  const nodes = Array.from(state.nodes.values());
  const edges = Array.from(state.edges.values());

  // Determine connected set for hover dimming
  const connectedIds = new Set<string>();
  const connectedEdgeIds = new Set<string>();
  if (state.hoveredNodeId && state.interactive) {
    connectedIds.add(state.hoveredNodeId);
    for (const edge of edges) {
      if (edge.source === state.hoveredNodeId || edge.target === state.hoveredNodeId) {
        connectedIds.add(edge.source);
        connectedIds.add(edge.target);
        connectedEdgeIds.add(edge.id);
      }
    }
  }
  const dimming = state.hoveredNodeId !== null && state.interactive;

  // Draw edges
  for (const edge of edges) {
    const a = state.nodes.get(edge.source);
    const b = state.nodes.get(edge.target);
    if (!a || !b) continue;

    // Edge pulse synchronized with connected nodes
    const nodeA = a;
    const edgePulse = 1 + Math.sin(state.time * 0.002 + (nodeA.phase || 0)) * 0.08;
    const baseOpacity = Math.max(0.2, edge.weight) * edge.opacity * edgePulse;
    let finalOpacity = baseOpacity;
    if (dimming) {
      finalOpacity = connectedEdgeIds.has(edge.id) ? 1 : baseOpacity * 0.06;
    }
    if (finalOpacity < 0.01) continue;

    // Highlighted edges get glow
    if (dimming && connectedEdgeIds.has(edge.id)) {
      ctx.strokeStyle = hexToRgba(edgeGlowColor(edge.type), finalOpacity);
      ctx.lineWidth = 3;
    } else {
      ctx.strokeStyle = hexToRgba(edgeColor(edge.type), finalOpacity);
      ctx.lineWidth = 1;
    }

    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }

  // Draw nodes
  for (const node of nodes) {
    if (node.opacity < 0.01) continue;
    drawNode(ctx, node, state.time, dimming, connectedIds);
  }
}

function drawNode(
  ctx: CanvasRenderingContext2D,
  node: GraphNode,
  time: number,
  dimming: boolean,
  connectedIds: Set<string>,
): void {
  const isSelf = node.selfRole === "self";
  const fullRadius = isSelf
    ? Math.max(18, nodeSize(node.accessCount) / 2)
    : nodeSize(node.accessCount) / 2;
  // Gentle pulse
  const pulse = Math.sin(time * 0.002 + node.phase) * 1.5;

  // Birth growth: self node emerges slowly from near-nothing over 4s
  let growthScale = 1;
  if (isSelf && node.birthTime != null) {
    const age = time - node.birthTime;
    const growDuration = 4000; // ms
    if (age < growDuration) {
      const t = age / growDuration;
      // Ease-out quint: very gentle start, settles softly
      const eased = 1 - Math.pow(1 - t, 5);
      // Start from a barely-visible speck, expand to full size
      growthScale = 0.04 + eased * 0.96;
    }
  }

  const r = (fullRadius + pulse) * growthScale;

  let opacity = node.opacity;
  if (dimming) {
    opacity = connectedIds.has(node.id) ? node.opacity : node.opacity * 0.25;
  }
  if (opacity < 0.01) return;

  const fill = tierColor(node.tier, node.selfRole);
  const border = tierBorderColor(node.tier, node.selfRole);

  // Glow for core/self nodes
  if ((node.tier === "core" || isSelf) && opacity > 0.3) {
    ctx.beginPath();
    ctx.arc(node.x, node.y, r + 8, 0, Math.PI * 2);
    ctx.fillStyle = hexToRgba(fill, opacity * 0.15);
    ctx.fill();
  }

  // Node fill
  ctx.beginPath();
  ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
  ctx.fillStyle = hexToRgba(fill, opacity);
  ctx.fill();

  // Border
  const borderWidth = isSelf ? 3 : node.tier === "archival" ? 1 : 2;
  ctx.lineWidth = borderWidth;
  ctx.strokeStyle = hexToRgba(border, opacity);
  if (node.tier === "archival" && node.selfRole === "") {
    ctx.setLineDash([4, 4]);
  }
  ctx.beginPath();
  ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);

  // Label
  if (opacity > 0.4) {
    ctx.font = "9px ui-monospace, monospace";
    ctx.fillStyle = hexToRgba("#777777", opacity);
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const maxWidth = 100;
    const label = node.label.length > 30 ? node.label.slice(0, 28) + "..." : node.label;
    ctx.fillText(label, node.x, node.y + r + 6, maxWidth);
  }
}
