import type { Tier } from "./types";

export type GraphTheme = "dark" | "light";

export interface GraphAppearance {
  theme: GraphTheme;
  colors: Record<Tier, string>;
}

export const GRAPH_DISPLAY_SCALE = 1.2;

export const DEFAULT_GRAPH_APPEARANCE: GraphAppearance = {
  theme: "dark",
  colors: {
    core: "#d4a574",
    working: "#6f7883",
    archival: "#4d5662",
  },
};

const STORAGE_KEY = "ormah.graphAppearance.v1";
const HEX_COLOR = /^#[0-9a-f]{6}$/i;

function normalizeColor(value: unknown, fallback: string): string {
  return typeof value === "string" && HEX_COLOR.test(value) ? value : fallback;
}

export function loadGraphAppearance(): GraphAppearance {
  if (typeof window === "undefined") return DEFAULT_GRAPH_APPEARANCE;

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_GRAPH_APPEARANCE;

    const parsed = JSON.parse(raw) as Partial<GraphAppearance> | null;
    if (!parsed || typeof parsed !== "object") return DEFAULT_GRAPH_APPEARANCE;

    return {
      theme: parsed.theme === "light" ? "light" : "dark",
      colors: {
        core: normalizeColor(parsed.colors?.core, DEFAULT_GRAPH_APPEARANCE.colors.core),
        working: normalizeColor(
          parsed.colors?.working,
          DEFAULT_GRAPH_APPEARANCE.colors.working
        ),
        archival: normalizeColor(
          parsed.colors?.archival,
          DEFAULT_GRAPH_APPEARANCE.colors.archival
        ),
      },
    };
  } catch {
    return DEFAULT_GRAPH_APPEARANCE;
  }
}

export function saveGraphAppearance(appearance: GraphAppearance): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(appearance));
  } catch {
    // Ignore storage failures; settings still apply for the current session.
  }
}

export function applyGraphAppearance(appearance: GraphAppearance): void {
  if (typeof document === "undefined") return;

  const root = document.documentElement;
  root.dataset.theme = appearance.theme;
  root.style.setProperty("--node-core", appearance.colors.core);
  root.style.setProperty("--node-working", appearance.colors.working);
  root.style.setProperty("--node-working-border", appearance.colors.working);
  root.style.setProperty("--node-archival", appearance.colors.archival);
  root.style.setProperty("--node-archival-border", appearance.colors.archival);
}
