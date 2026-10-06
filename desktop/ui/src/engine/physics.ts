import { PHYSICS } from "@/lib/constants";
import type { GraphState } from "./types";

export function stepPhysics(state: GraphState, dt: number): void {
  const clampedDt = Math.min(dt, PHYSICS.maxDt);
  const factor = clampedDt / 16; // normalize to ~60fps
  const nodes = Array.from(state.nodes.values());
  const edges = Array.from(state.edges.values());
  const cx = state.gravityCenterX ?? state.width / 2;
  const cy = state.height / 2;

  // Center gravity
  const isSingleSelf = nodes.length === 1 && nodes[0].selfRole === "self";
  for (const node of nodes) {
    if (node.pinned) continue;

    if (node.selfRole === "self" && isSingleSelf) {
      // Stronger home gravity for the lone SELF node — pulls it back to center
      // gracefully after being released from a drag
      const dx = cx - node.x;
      const dy = cy - node.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      // Gravity increases with distance for a smooth rubber-band feel
      const strength = 0.002 + (dist / state.width) * 0.003;
      node.vx += dx * strength * factor;
      node.vy += dy * strength * factor;

      // Add gentle ambient drift so it floats around center
      const driftX = Math.sin(state.time * 0.0004 + node.phase) * 0.15;
      const driftY = Math.cos(state.time * 0.0003 + node.phase * 1.5) * 0.12;
      node.vx += driftX * factor;
      node.vy += driftY * factor;
    } else {
      node.vx += (cx - node.x) * PHYSICS.centerGravity * factor;
      node.vy += (cy - node.y) * PHYSICS.centerGravity * factor;
    }
  }

  // Node repulsion (Coulomb)
  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i];
    if (a.pinned) continue;
    for (let j = i + 1; j < nodes.length; j++) {
      const b = nodes[j];
      const dx = a.x - b.x;
      const dy = a.y - b.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      if (dist > PHYSICS.repulsionCutoff) continue;
      const force = (PHYSICS.repulsionStrength / (dist * dist)) * factor;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx;
      a.vy += fy;
      if (!b.pinned) {
        b.vx -= fx;
        b.vy -= fy;
      }
    }
  }

  // Edge springs (Hooke)
  for (const edge of edges) {
    const a = state.nodes.get(edge.source);
    const b = state.nodes.get(edge.target);
    if (!a || !b) continue;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const restLength =
      PHYSICS.springRestBase + (1 - edge.weight) * PHYSICS.springWeightFactor;
    const displacement = dist - restLength;
    const force = displacement * PHYSICS.springStiffness * factor;
    const fx = (dx / dist) * force;
    const fy = (dy / dist) * force;
    if (!a.pinned) {
      a.vx += fx;
      a.vy += fy;
    }
    if (!b.pinned) {
      b.vx -= fx;
      b.vy -= fy;
    }
  }

  // Integrate + damp
  for (const node of nodes) {
    if (node.pinned) continue;
    node.vx *= PHYSICS.damping;
    node.vy *= PHYSICS.damping;
    node.x += node.vx * factor;
    node.y += node.vy * factor;
  }

  // Animate opacity toward target
  for (const node of nodes) {
    const diff = node.targetOpacity - node.opacity;
    if (Math.abs(diff) > 0.01) {
      node.opacity += diff * 0.05 * factor;
    } else {
      node.opacity = node.targetOpacity;
    }
  }
  for (const edge of edges) {
    const diff = edge.targetOpacity - edge.opacity;
    if (Math.abs(diff) > 0.01) {
      edge.opacity += diff * 0.05 * factor;
    } else {
      edge.opacity = edge.targetOpacity;
    }
  }
}
