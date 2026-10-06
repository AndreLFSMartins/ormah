// Ormah color palette — ported from ormah/ui/src/styles.css
export const COLORS = {
  bg: "#0a0a0a",
  accent: "#d4a574",
  accentDim: "rgba(212, 165, 116, 0.15)",
  nodeSelf: "#74b3a5",
  nodeSelfBorder: "#8fd4c4",
  nodeIdentity: "#4d8a7e",
  nodeIdentityBorder: "#6ba89a",
  nodeCore: "#d4a574",
  nodeWorking: "#4a4a4a",
  nodeWorkingBorder: "#666",
  nodeArchival: "#2a2a2a",
  nodeArchivalBorder: "#444",
  edgeDefault: "#333",
  edgeSupports: "#4a7a4a",
  edgeContradicts: "#7a4a4a",
  edgeDefines: "#5a9e8f",
  edgeEvolved: "#6a5acd",
  edgeGlowSupports: "#6abf6a",
  edgeGlowContradicts: "#bf6a6a",
  edgeGlowDefines: "#8fd4c4",
  edgeGlowEvolved: "#9a8aef",
  edgeGlowDefault: "#d4a574",
  text: "#999",
  textBright: "#ccc",
  textMuted: "#555",
} as const;

export const PHYSICS = {
  centerGravity: 0.0003,
  repulsionStrength: 500,
  repulsionCutoff: 300,
  springRestBase: 120,
  springWeightFactor: 100,
  springStiffness: 0.004,
  damping: 0.92,
  maxDt: 32,
} as const;

// Story section heights in vh units
// Each section must be >100vh for sticky text to pin in the viewport.
// Pin time = section height - 100vh.
export const STORY_VH = {
  act1: 100,
  act2: 250,
  act3: 480,
  act4: 250,
  act5: 380,
} as const;

export const TOTAL_STORY_VH = 1460; // sum of all acts

// Act ranges in vh (cumulative). Used to compute px thresholds at runtime.
// act1: 0–100, act2: 100–350, act3: 350–830, act4: 830–1080, act5: 1080–1460
export const ACTS_VH = {
  act1: { startVh: 0, endVh: 100 },
  act2: { startVh: 100, endVh: 350 },
  act3: { startVh: 350, endVh: 830 },
  act4: { startVh: 830, endVh: 1080 },
  act5: { startVh: 1080, endVh: 1460 },
} as const;

/** Convert vh thresholds to px at current viewport height */
export function vhToPx(vh: number): number {
  if (typeof window === "undefined") return vh * 8; // SSR fallback (assume 800px)
  return (vh / 100) * window.innerHeight;
}

// Legacy export for backward compat during migration
export const TOTAL_SCROLL_VH = TOTAL_STORY_VH;
