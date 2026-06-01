import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import cytoscape, { type Core } from "cytoscape";
import cola from "cytoscape-cola";
import fcose from "cytoscape-fcose";
import {
  GRAPH_DISPLAY_SCALE,
  type GraphAppearance,
  type GraphTheme,
} from "../graphAppearance";
import type { Edge, MemoryNode, Tier } from "../types";

try { cytoscape.use(cola); } catch (_) { /* already registered */ }
try { cytoscape.use(fcose); } catch (_) { /* already registered */ }

interface Props {
  nodes: MemoryNode[];
  edges: Edge[];
  onNodeSelect: (id: string) => void;
  focusNodeId: string | null;
  userNodeId: string | null;
  clusterBySpace: boolean;
  appearance: GraphAppearance;
}

const GRAPH_THEME_TOKENS: Record<GraphTheme, {
  background: string;
  label: string;
  labelGlow: string;
  accent: string;
  edgeDefault: string;
  edgeSupports: string;
  edgeContradicts: string;
  edgeDefines: string;
  edgeEvolved: string;
  glowDefault: string;
}> = {
  dark: {
    background: "#0a0a0a",
    label: "#d8dee6",
    labelGlow: "#f3f4f6",
    accent: "#d4a574",
    edgeDefault: "#333",
    edgeSupports: "#4a7a4a",
    edgeContradicts: "#7a4a4a",
    edgeDefines: "#5a9e8f",
    edgeEvolved: "#6a5acd",
    glowDefault: "#d4a574",
  },
  light: {
    background: "#f6f8fb",
    label: "#24303c",
    labelGlow: "#111827",
    accent: "#8a5f2d",
    edgeDefault: "#aeb8c4",
    edgeSupports: "#3f7d52",
    edgeContradicts: "#a65353",
    edgeDefines: "#3e8f82",
    edgeEvolved: "#7265bd",
    glowDefault: "#8a5f2d",
  },
};

function tierColor(tier: string, selfRole: string, appearance: GraphAppearance) {
  if (selfRole === "self") return "#74b3a5";
  if (selfRole === "identity") return "#4d8a7e";
  return appearance.colors[tier as Tier] ?? appearance.colors.working;
}

function tierBorderColor(tier: string, selfRole: string, appearance: GraphAppearance) {
  if (selfRole === "self") return "#8fd4c4";
  if (selfRole === "identity") return "#6ba89a";
  return appearance.colors[tier as Tier] ?? appearance.colors.working;
}

function degreeNodeSize(degree: number, selfRole: string): number {
  const base = Math.min(70, Math.max(18, 18 + Math.sqrt(degree) * 7));
  const s = Math.round(base * GRAPH_DISPLAY_SCALE);
  if (selfRole === "self") return Math.max(Math.round(44 * GRAPH_DISPLAY_SCALE), s);
  return s;
}

function edgeColor(edgeType: string, theme: GraphTheme): string {
  const tokens = GRAPH_THEME_TOKENS[theme];
  switch (edgeType) {
    case "supports":
      return tokens.edgeSupports;
    case "contradicts":
      return tokens.edgeContradicts;
    case "defines":
      return tokens.edgeDefines;
    case "evolved_from":
      return tokens.edgeEvolved;
    default:
      return tokens.edgeDefault;
  }
}

function edgeGlowColor(edgeType: string, theme: GraphTheme): string {
  const tokens = GRAPH_THEME_TOKENS[theme];
  switch (edgeType) {
    case "supports":
      return "#6abf6a";
    case "contradicts":
      return "#bf6a6a";
    case "defines":
      return "#8fd4c4";
    case "evolved_from":
      return "#9a8aef";
    default:
      return tokens.glowDefault;
  }
}

function nodeLabel(n: MemoryNode): string {
  if (n.title) return n.title;
  if (n.content) return n.content.slice(0, 40);
  return n.id.split("-")[0];
}

// Deterministic hue per space so each galaxy reads as a distinct colour.
// Cached: it's called once per node on build and again on every appearance
// change (~2 × node count), but the hue only depends on the space name.
const spaceColorCache = new Map<string, string>();
function spaceColor(space: string | null): string {
  const key = space ?? "__none__";
  const cached = spaceColorCache.get(key);
  if (cached) return cached;
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) % 360;
  const color = `hsl(${h}, 62%, 60%)`;
  spaceColorCache.set(key, color);
  return color;
}

// Galaxy mode encodes two independent channels on a node:
//   fill   = space colour (the project a memory belongs to)
//   shape  = tier (archived = hollow ring, core = solid + white rim, working = solid)
// Tier is shape-only (never a hue) so it never collides with the space colour,
// regardless of how a user customises their tier palette.
// self / identity keep the space fill (so the project still reads) but take a
// teal ring that overrides the tier rim — it marks "this is who I am".
const TIER_RIM = "#ffffff";
const IDENTITY_RIM = "#6ba89a";
const SELF_RIM = "#8fd4c4";
function galaxyNodeStyle(
  space: string | null,
  tier: string,
  background: string,
  selfRole: string,
): { bg: string; border: string; borderWidth: number } {
  const sc = spaceColor(space);
  const bg = tier === "archival" ? background : sc;
  // self / identity ring wins over the tier rim.
  if (selfRole === "self") return { bg, border: SELF_RIM, borderWidth: 3 };
  if (selfRole === "identity") return { bg, border: IDENTITY_RIM, borderWidth: 2.5 };
  if (tier === "archival") return { bg, border: sc, borderWidth: 2 };
  if (tier === "core") return { bg, border: TIER_RIM, borderWidth: 2 };
  return { bg, border: sc, borderWidth: 0 }; // working: solid, no rim
}

function buildStyles(appearance: GraphAppearance) {
  const tokens = GRAPH_THEME_TOKENS[appearance.theme];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const styles: any[] = [
    {
      selector: "node",
      style: {
        "background-color": "data(bgColor)",
        "border-color": "data(borderColor)",
        "border-width": "data(borderWidth)",
        "border-style": "solid",
        width: "data(nodeSize)",
        height: "data(nodeSize)",
        label: "",
        "font-size": `${Math.round(12 * GRAPH_DISPLAY_SCALE)}px`,
        color: "data(labelColor)",
        "text-outline-color": "data(labelOutlineColor)",
        "text-outline-opacity": 0.9,
        "text-outline-width": 2,
        "text-valign": "bottom" as const,
        "text-halign": "center" as const,
        "text-margin-y": Math.round(6 * GRAPH_DISPLAY_SCALE),
        "font-family": "ui-monospace, monospace",
        "text-wrap": "wrap" as const,
        "text-max-width": `${Math.round(120 * GRAPH_DISPLAY_SCALE)}px`,
        "text-overflow-wrap": "anywhere" as const,
        "overlay-opacity": 0,
      } as cytoscape.Css.Node,
    },
    {
      selector: "node:active, node:selected",
      style: {
        "border-color": tokens.accent,
        "border-width": 3,
        "overlay-opacity": 0,
        label: "data(labelText)",
        "min-zoomed-font-size": 0,
      } as cytoscape.Css.Node,
    },
    {
      selector: "edge",
      style: {
        "line-color": "data(lineColor)",
        width: 1.8,
        opacity: "data(edgeOpacity)" as unknown as number,
        "curve-style": "bezier",
      } as cytoscape.Css.Edge,
    },
    {
      selector: "edge[edgeType = 'related_to']",
      style: {
        "curve-style": "haystack",
      } as cytoscape.Css.Edge,
    },
    {
      // Cross-space edges = links between galaxies. Kept thin but a touch
      // brighter than intra edges; the *density* of many thin links reads as
      // a bridge between galaxies without becoming spaghetti.
      selector: "edge.cross-space",
      style: {
        // Individual cross-space edges are hidden; the aggregate galaxy-link
        // line represents the whole bundle between two galaxies.
        "line-opacity": 0,
        events: "no",
      } as cytoscape.Css.Edge,
    },
    {
      // Aggregate galaxy-to-galaxy link: one line per connected space pair,
      // width/brightness scaled by how many real edges connect them.
      selector: "edge.galaxy-link",
      style: {
        width: "data(linkW)",
        "line-color": tokens.accent,
        "line-opacity": "data(linkO)" as unknown as number,
        "curve-style": "straight",
        "z-index": 4,
        events: "no",
      } as cytoscape.Css.Edge,
    },
    {
      selector: ".dim",
      style: { opacity: 0.06 } as cytoscape.Css.Node,
    },
    {
      // Galaxy links carry a data-mapped line-opacity that survives the
      // generic .dim opacity, so a dimmed gold line still reads as a strong
      // stroke. Force it down explicitly when dimmed.
      selector: "edge.galaxy-link.dim",
      style: { "line-opacity": 0.04, opacity: 0.04 } as cytoscape.Css.Edge,
    },
    {
      selector: "edge.hot",
      style: { width: 4, opacity: 1, "z-index": 30 } as cytoscape.Css.Edge,
    },
    {
      selector: "node.hot",
      style: { "border-color": tokens.accent, "border-width": 4, "z-index": 30 } as cytoscape.Css.Node,
    },
    {
      selector: "node.glow",
      style: {
        "border-color": tokens.accent,
        "border-width": 3,
        color: tokens.labelGlow,
        label: "data(labelText)",
        "min-zoomed-font-size": 0,
        "z-index": 20,
        "transition-property": "border-color, border-width" as any,
        "transition-duration": "100ms" as unknown as number,
      } as cytoscape.Css.Node,
    },
    {
      selector: "node.glow-neighbor",
      style: {
        "border-color": tokens.accent,
        "border-width": 2,
        "transition-property": "border-color, border-width" as any,
        "transition-duration": "100ms" as unknown as number,
      } as cytoscape.Css.Node,
    },
    {
      selector: "edge.glow",
      style: {
        "line-color": "data(glowColor)",
        width: 3,
        opacity: 1,
        "z-index": 10,
        "transition-property": "line-color, width, opacity" as any,
        "transition-duration": "100ms" as unknown as number,
      } as cytoscape.Css.Edge,
    },
  ];
  return styles;
}

const LEGEND_ROW_STYLE: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 7,
  cursor: "pointer",
  userSelect: "none",
};

const LEGEND_SECTION_TITLE_STYLE: CSSProperties = {
  opacity: 0.5,
  fontSize: 9,
  letterSpacing: 1,
};

// One clickable legend row: swatch + content as children, dimmed when another
// row holds the focus. Shared by both the link-type and space sections.
function LegendRow({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <div onClick={onClick} style={{ ...LEGEND_ROW_STYLE, opacity: active ? 1 : 0.3 }}>
      {children}
    </div>
  );
}

const GraphView = forwardRef<{ focusNode: (id: string) => void }, Props>(
  (
    { nodes, edges, onNodeSelect, focusNodeId, userNodeId, clusterBySpace, appearance },
    ref
  ) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const cyRef = useRef<Core | null>(null);
    const layoutRef = useRef<cytoscape.Layouts | null>(null);
    const onNodeSelectRef = useRef(onNodeSelect);
    onNodeSelectRef.current = onNodeSelect;
    const [layoutReady, setLayoutReady] = useState(false);
    const [legendFocus, setLegendFocus] = useState<{ kind: string; val: string } | null>(null);


    useImperativeHandle(ref, () => ({
      focusNode(id: string) {
        const cy = cyRef.current;
        if (!cy) return;
        const node = cy.getElementById(id);
        if (node.length) {
          cy.animate({
            center: { eles: node },
            zoom: 1.5,
          } as never, { duration: 400 });
        }
      },
      highlightNode(id: string) {
        const cy = cyRef.current;
        if (!cy) return;
        // Clear previous glow
        cy.elements().removeClass("glow glow-neighbor");

        const node = cy.getElementById(id);
        if (!node.length) return;

        node.addClass("glow");
        node.connectedEdges().addClass("glow");
        node.neighborhood("node").addClass("glow-neighbor");
      },
      highlightNodes(ids: string[]) {
        const cy = cyRef.current;
        if (!cy) return;
        cy.elements().removeClass("glow glow-neighbor");

        const matched = ids.map((id) => cy.getElementById(id)).filter((n) => n.length);
        if (!matched.length) return;

        for (const node of matched) {
          node.addClass("glow");
        }

        const idSet = new Set(ids);
        cy.edges().forEach((edge) => {
          if (idSet.has(edge.source().id()) && idSet.has(edge.target().id())) {
            edge.addClass("glow");
          }
        });

        // Fit viewport to show matched nodes (used by Insights/Review panels)
        const collection = matched.reduce((acc, n) => acc.union(n), cy.collection());
        const currentZoom = cy.zoom();
        cy.fit(collection, 120);
        if (cy.zoom() > Math.max(currentZoom, 1.2)) {
          cy.zoom(Math.max(currentZoom, 1.2));
          cy.center(collection);
        }
      },
      clearHighlight() {
        const cy = cyRef.current;
        if (!cy) return;
        cy.elements().removeClass("glow glow-neighbor");
      },
    }));

    useEffect(() => {
      if (!containerRef.current) return;
      setLayoutReady(false);

      const nodeIds = new Set(nodes.map((n) => n.id));

      const identityNodeIds = new Set<string>();
      if (userNodeId) {
        for (const e of edges) {
          if (e.edge_type === "defines" && e.source_id === userNodeId) {
            identityNodeIds.add(e.target_id);
          }
        }
      }

      function selfRole(nodeId: string): string {
        if (nodeId === userNodeId) return "self";
        if (identityNodeIds.has(nodeId)) return "identity";
        return "";
      }

      // Build space lookup for edge length calculation
      const nodeSpaceMap = new Map<string, string | null>();
      for (const n of nodes) {
        nodeSpaceMap.set(n.id, n.space || null);
      }

      const degreeMap = new Map<string, number>();
      for (const e of edges) {
        if (!nodeIds.has(e.source_id) || !nodeIds.has(e.target_id)) continue;
        degreeMap.set(e.source_id, (degreeMap.get(e.source_id) ?? 0) + 1);
        degreeMap.set(e.target_id, (degreeMap.get(e.target_id) ?? 0) + 1);
      }

      const themeTokens = GRAPH_THEME_TOKENS[appearance.theme];
      const nodeElements = nodes.map((n) => {
        const sr = selfRole(n.id);
        const size = degreeNodeSize(degreeMap.get(n.id) ?? 0, sr);
        const gs = clusterBySpace
          ? galaxyNodeStyle(n.space || null, n.tier, themeTokens.background, sr)
          : null;
        return {
          data: {
            id: n.id,
            labelText: nodeLabel(n),
            space: n.space || "",
            tier: n.tier,
            type: n.type,
            accessCount: n.access_count,
            selfRole: sr,
            bgColor: gs ? gs.bg : tierColor(n.tier, sr, appearance),
            borderColor: gs ? gs.border : tierBorderColor(n.tier, sr, appearance),
            borderWidth: gs ? gs.borderWidth : sr === "self" ? 3 : n.tier === "archival" ? 1 : 2,
            nodeSize: size,
            labelColor: themeTokens.label,
            labelOutlineColor: themeTokens.background,
          },
        };
      });

      const edgeElements = edges
        .filter((e) => nodeIds.has(e.source_id) && nodeIds.has(e.target_id))
        .map((e) => {
          const crossSpace =
            (nodeSpaceMap.get(e.source_id) ?? null) !==
            (nodeSpaceMap.get(e.target_id) ?? null);
          return {
            data: {
              id: `${e.source_id}-${e.edge_type}-${e.target_id}`,
              source: e.source_id,
              target: e.target_id,
              edgeType: e.edge_type,
              weight: e.weight,
              lineColor: edgeColor(e.edge_type, appearance.theme),
              glowColor: edgeGlowColor(e.edge_type, appearance.theme),
              edgeOpacity: Math.max(crossSpace ? 0.5 : 0.7, e.weight ?? 0.5),
            },
            classes: crossSpace ? "cross-space" : undefined,
          };
        });

      // --- Galaxy layout: one invisible hub node per space ---
      // Every member connects to its space hub so the space coheres into a
      // dense "galaxy". Orphans get a longer hub edge → they settle on the
      // galaxy's outer rim. Hubs repel each other (+gravity) to arrange the
      // galaxies in a bounded circle; cross-space edges pull connected
      // galaxies nearer (hybrid positioning). Hubs/edges are invisible but
      // still participate in the force simulation.
      const HUB = "__hub__";
      const skey = (s: string | null) => s ?? "__none__";
      const useGalaxy = clusterBySpace;

      const hubElements: cytoscape.ElementDefinition[] = [];
      const hubEdges: cytoscape.ElementDefinition[] = [];
      const galaxyLinks: cytoscape.ElementDefinition[] = [];
      const hubPos = new Map<string, { x: number; y: number }>();

      if (useGalaxy) {
        const sizeBySpace = new Map();
        for (const n of nodes) {
          const k = skey(n.space || null);
          sizeBySpace.set(k, (sizeBySpace.get(k) ?? 0) + 1);
        }
        // Single pass over cross-space edges feeds two aggregates: crossDeg
        // (per-space connectivity, for hub ordering) and pairCount (per
        // space-pair edge count, for the aggregate galaxy links below).
        const crossDeg = new Map();
        const pairCount = new Map<string, number>();
        for (const e of edgeElements) {
          if (!e.classes) continue; // only cross-space edges carry a class
          const sa = skey(nodeSpaceMap.get(e.data.source) ?? null);
          const sb = skey(nodeSpaceMap.get(e.data.target) ?? null);
          if (sa === sb) continue;
          crossDeg.set(sa, (crossDeg.get(sa) ?? 0) + 1);
          crossDeg.set(sb, (crossDeg.get(sb) ?? 0) + 1);
          const key = sa < sb ? `${sa}|${sb}` : `${sb}|${sa}`;
          pairCount.set(key, (pairCount.get(key) ?? 0) + 1);
        }
        // Order galaxies by cross-space connectivity: the most-connected hub
        // spaces sit at the centre (short links between them), isolated ones
        // drift to the rim. Tiebreak by size.
        const keys = Array.from(sizeBySpace.keys()).sort((x, y) => {
          const d = (crossDeg.get(y) ?? 0) - (crossDeg.get(x) ?? 0);
          return d !== 0 ? d : sizeBySpace.get(y) - sizeBySpace.get(x);
        });
        const GOLDEN = 2.399963229728653;
        const SPACING = 340;
        keys.forEach((k, i) => {
          const ang = i * GOLDEN;
          const r = SPACING * Math.sqrt(i);
          hubPos.set(HUB + k, { x: Math.cos(ang) * r, y: Math.sin(ang) * r });
          hubElements.push({ data: { id: HUB + k }, classes: "hub" });
        });
        for (const n of nodes) {
          hubEdges.push({
            data: {
              id: `${HUB}e_${n.id}`,
              source: HUB + skey(n.space || null),
              target: n.id,
              orphan: (degreeMap.get(n.id) ?? 0) === 0,
            },
            classes: "hub-edge",
          });
        }

        // Aggregate cross-space edges into one "galaxy link" per space pair
        // (counted above), weighted by how many real edges connect them. A
        // handful of clean hub-to-hub lines instead of hundreds of crossings.
        for (const [key, count] of pairCount) {
          const [a, b] = key.split("|");
          if (count < 6) continue;
          galaxyLinks.push({
            data: {
              id: `${HUB}link_${a}_${b}`,
              source: HUB + a,
              target: HUB + b,
              linkCount: count,
              linkW: Math.min(7, 1.5 + Math.log2(count) * 1.0),
              linkO: Math.min(0.5, 0.22 + Math.log2(count) * 0.06),
            },
            classes: "galaxy-link",
          });
        }
      }

      const intraEdges = useGalaxy ? edgeElements.filter((e) => !e.classes) : edgeElements;

      const cy = cytoscape({
        container: containerRef.current,
        elements: [...nodeElements, ...intraEdges, ...hubElements, ...hubEdges, ...galaxyLinks],
        style: [
          ...buildStyles(appearance),
          { selector: ".hub", style: { width: 1, height: 1, opacity: 0, events: "no" } },
          { selector: ".hub-edge", style: { width: 1, "line-opacity": 0, events: "no" } },
        ] as never,
        layout: { name: "preset" },
        minZoom: 0.01,
        maxZoom: 4,
        wheelSensitivity: 0.3,
      });

      // Seed hubs + members so fcose starts with galaxies already grouped.
      if (useGalaxy) {
        cy.nodes(".hub").forEach((node) => {
          const p = hubPos.get(node.id());
          if (p) node.position(p);
        });
        cy.nodes().not(".hub").forEach((node, idx) => {
          const p = hubPos.get(HUB + skey(nodeSpaceMap.get(node.id()) ?? null));
          if (p) {
            const a = (idx % 12) * (Math.PI / 6);
            node.position({ x: p.x + Math.cos(a) * 40, y: p.y + Math.sin(a) * 40 });
          }
        });
      }

      cy.nodes().not(".hub").grabify();
      cy.nodes(".hub").ungrabify();

      const layout = cy.layout(
        useGalaxy
          ? ({
              name: "fcose",
              quality: "default",
              animate: true,
              randomize: false, // start from the galaxy seeds
              fit: false,
              numIter: 2500,
              nodeSeparation: 150,
              // Pin each space hub at its phyllotaxis slot so galaxies stay
              // distinct and cannot collapse into one another.
              gravity: 0.7,
              gravityRange: 5,
              // Hubs are pinned; low real-node repulsion → dense, tight galaxies.
              nodeRepulsion: (node: cytoscape.NodeSingular) =>
                node.hasClass("hub") ? 55000 : 2800,
              idealEdgeLength: (edge: cytoscape.EdgeSingular) => {
                // Hub edges set galaxy radius: tight core, modest rim for orphans.
                if (edge.hasClass("hub-edge")) {
                  return edge.data("orphan") ? 150 : 60;
                }
                if (edge.hasClass("galaxy-link")) {
                  return 520 - 160 * (edge.data("linkO") ?? 0.4);
                }
                const w = edge.data("weight") ?? 0.5;
                const base = 120 + (1 - w) * 100;
                const ss = nodeSpaceMap.get(edge.source().id());
                const ts = nodeSpaceMap.get(edge.target().id());
                // Long cross-space links so they draw galaxy-to-galaxy
                // connections without yanking members out of their galaxy.
                return ss !== ts ? base * 2.5 : base * 0.6;
              },
              packComponents: true,
            } as never)
          : ({
              name: "fcose",
              quality: "default",
              animate: true,
              randomize: true,
              fit: false,
              gravity: 0.25,
              packComponents: true,
            } as never),
      );
      layoutRef.current = layout;

      if (useGalaxy) {
        // fcose builds the galaxy structure (gravity + clustering) but lets
        // nodes pile up on the same coordinates, so the dense core reads like
        // a flat PNG on zoom-in. Chase it with a cola pass whose only job is
        // collision: avoidOverlap pushes every dot apart by its own radius
        // (Obsidian-style), seeded from fcose's positions so the galaxies keep
        // their shape. Result: the core spreads into distinct, non-touching
        // dots that separate cleanly as you zoom in.
        layout.one("layoutstop", () => {
          const separate = cy.layout({
            name: "cola",
            animate: true,
            randomize: false, // honour fcose's galaxy positions
            fit: false,
            avoidOverlap: true,
            handleDisconnected: false, // don't relocate isolated galaxies
            nodeSpacing: () => 12, // minimum gap between dot bounding boxes
            edgeLength: (edge: cytoscape.EdgeSingular) => {
              if (edge.hasClass("hub-edge")) {
                return edge.data("orphan") ? 160 : 70;
              }
              if (edge.hasClass("galaxy-link")) return 480;
              const ss = nodeSpaceMap.get(edge.source().id());
              const ts = nodeSpaceMap.get(edge.target().id());
              return ss !== ts ? 260 : 90;
            },
            maxSimulationTime: 2500,
            convergenceThreshold: 0.01,
            ungrabifyWhileSimulating: false,
          } as never);
          layoutRef.current = separate;
          separate.one("layoutstop", () => {
            cy.fit(cy.nodes().not(".hub"), 40);
            setLayoutReady(true);
          });
          separate.run();
        });
      } else {
        layout.one("layoutstop", () => {
          cy.fit(cy.nodes().not(".hub"), 40);
          setLayoutReady(true);
        });
      }
      layout.run();

      cy.on("tap", "node", (e) => {
        onNodeSelectRef.current(e.target.id());
      });

      // Hover: glow, don't dim
      let hoverTimer: ReturnType<typeof setTimeout> | null = null;

      cy.on("mouseover", "node", (e) => {
        document.body.style.cursor = "pointer";

        if (hoverTimer) clearTimeout(hoverTimer);
        hoverTimer = setTimeout(() => {
          // Clear any previous glow
          cy.elements().removeClass("glow glow-neighbor");

          const node = e.target;
          node.addClass("glow");
          node.connectedEdges().addClass("glow");
          node.neighborhood("node").addClass("glow-neighbor");
        }, 50);
      });

      cy.on("mouseout", "node", (e) => {
        document.body.style.cursor = "default";
        if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null; }

        const node = e.target;
        node.removeClass("glow");
        node.connectedEdges().removeClass("glow");
        node.neighborhood("node").removeClass("glow-neighbor");
      });

      // Drag physics: lightweight rAF spring simulation during drag
      let dragRaf: number | null = null;
      const restPos = new Map<string, { x: number; y: number }>();

      cy.on("grab", "node", (e) => {
        if (dragRaf) { cancelAnimationFrame(dragRaf); dragRaf = null; }

        // Snapshot rest positions for all nodes
        restPos.clear();
        cy.nodes().forEach((n) => {
          const p = n.position();
          restPos.set(n.id(), { x: p.x, y: p.y });
        });

        // Collect the 2-hop neighborhood (edges + nodes) once
        const grabbed = e.target;
        const hop1Nodes = grabbed.neighborhood("node");
        const hop1Ids = new Set<string>([grabbed.id()]);
        hop1Nodes.forEach((n: cytoscape.NodeSingular) => { hop1Ids.add(n.id()); });

        const hop2Nodes = cy.collection();
        hop1Nodes.forEach((n: cytoscape.NodeSingular) => {
          n.neighborhood("node").forEach((n2: cytoscape.NodeSingular) => {
            if (!hop1Ids.has(n2.id())) hop2Nodes.merge(n2);
          });
        });
        const allIds = new Set(hop1Ids);
        hop2Nodes.forEach((n: cytoscape.NodeSingular) => { allIds.add(n.id()); });

        // Collect edges within the affected neighborhood
        const affectedEdges: cytoscape.EdgeSingular[] = [];
        cy.edges().forEach((edge) => {
          const sId = edge.source().id();
          const tId = edge.target().id();
          if (allIds.has(sId) && allIds.has(tId)) affectedEdges.push(edge);
        });

        const step = () => {
          const gNode = cy.nodes(":grabbed");
          if (!gNode.length) {
            // Released — animate back to rest
            allIds.forEach((id) => {
              if (id === grabbed.id()) return;
              const rest = restPos.get(id);
              const node = cy.getElementById(id);
              if (rest && node.length) {
                node.animate({ position: { x: rest.x, y: rest.y } }, { duration: 250 });
              }
            });
            dragRaf = null;
            return;
          }

          // Spring forces along neighborhood edges
          for (const edge of affectedEdges) {
            const src = edge.source();
            const tgt = edge.target();
            if (src.grabbed() && tgt.grabbed()) continue;

            const sp = src.position();
            const tp = tgt.position();
            const dx = tp.x - sp.x;
            const dy = tp.y - sp.y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < 1) continue;

            const w = edge.data("weight") ?? 0.5;
            const ideal = 120 + (1 - w) * 100;
            const displacement = dist - ideal;
            const strength = displacement * 0.006;
            const fx = (dx / dist) * strength;
            const fy = (dy / dist) * strength;

            if (!src.grabbed()) {
              const rest = restPos.get(src.id())!;
              const p = src.position();
              const rx = (rest.x - p.x) * 0.025;
              const ry = (rest.y - p.y) * 0.025;
              src.position({ x: p.x + fx + rx, y: p.y + fy + ry });
            }
            if (!tgt.grabbed()) {
              const rest = restPos.get(tgt.id())!;
              const p = tgt.position();
              const rx = (rest.x - p.x) * 0.025;
              const ry = (rest.y - p.y) * 0.025;
              tgt.position({ x: p.x - fx + rx, y: p.y - fy + ry });
            }
          }

          dragRaf = requestAnimationFrame(step);
        };

        dragRaf = requestAnimationFrame(step);
      });

      // Edge tooltip — follows cursor
      const tooltip = document.createElement("div");
      tooltip.className = "edge-tooltip";
      containerRef.current.appendChild(tooltip);

      cy.on("mouseover", "edge", (e) => {
        const edge = e.target;
        const type = edge.data("edgeType") ?? "related";
        const weight = edge.data("weight");
        tooltip.textContent = weight != null
          ? `${type} · ${Math.round(weight * 100)}%`
          : type;
        tooltip.style.opacity = "1";
        document.body.style.cursor = "pointer";
      });

      cy.on("mousemove", "edge", (e) => {
        const { originalEvent } = e as unknown as { originalEvent: MouseEvent };
        const rect = containerRef.current!.getBoundingClientRect();
        tooltip.style.left = `${originalEvent.clientX - rect.left + 12}px`;
        tooltip.style.top = `${originalEvent.clientY - rect.top - 8}px`;
      });

      cy.on("mouseout", "edge", () => {
        tooltip.style.opacity = "0";
        document.body.style.cursor = "default";
      });

      cyRef.current = cy;

      return () => {
        if (dragRaf) { cancelAnimationFrame(dragRaf); dragRaf = null; }
        if (layoutRef.current) {
          layoutRef.current.stop();
          layoutRef.current = null;
        }
        cy.destroy();
        cyRef.current = null;
      };
    }, [nodes, edges, userNodeId, clusterBySpace]);

    useEffect(() => {
      const cy = cyRef.current;
      if (!cy) return;

      const themeTokens = GRAPH_THEME_TOKENS[appearance.theme];
      cy.style(buildStyles(appearance));
      cy.nodes().not(".hub").forEach((node) => {
        const tier = node.data("tier") as string;
        const selfRole = node.data("selfRole") as string;
        // In galaxy mode the fill is the space colour and the tier is encoded
        // by shape (hollow / rim), so re-derive it here too — otherwise a theme
        // or tier-palette change would clobber the space colours with tier hues.
        if (clusterBySpace) {
          const gs = galaxyNodeStyle(
            node.data("space") || null,
            tier,
            themeTokens.background,
            selfRole,
          );
          node.data("bgColor", gs.bg);
          node.data("borderColor", gs.border);
          node.data("borderWidth", gs.borderWidth);
        } else {
          node.data("bgColor", tierColor(tier, selfRole, appearance));
          node.data("borderColor", tierBorderColor(tier, selfRole, appearance));
        }
        node.data("labelColor", themeTokens.label);
        node.data("labelOutlineColor", themeTokens.background);
      });
      cy.edges().forEach((edge) => {
        const edgeType = edge.data("edgeType") as string;
        edge.data("lineColor", edgeColor(edgeType, appearance.theme));
        edge.data("glowColor", edgeGlowColor(edgeType, appearance.theme));
      });
    }, [appearance]);

    useEffect(() => {
      if (focusNodeId && cyRef.current) {
        const node = cyRef.current.getElementById(focusNodeId);
        if (node.length) {
          cyRef.current.nodes().unselect();
          node.select();
        }
      }
    }, [focusNodeId]);

    useEffect(() => {
      const cy = cyRef.current;
      if (!cy) return;
      cy.batch(() => {
        cy.elements().removeClass("dim hot");
        if (!legendFocus) return;
        cy.elements().not(".hub").not(".hub-edge").addClass("dim");
        if (legendFocus.kind === "space") {
          const m = cy.nodes().filter((n) => n.data("space") === legendFocus.val);
          m.removeClass("dim").addClass("hot");
          m.connectedEdges().removeClass("dim");
        } else if (legendFocus.kind === "tier") {
          const m = cy.nodes().not(".hub").filter((n) => n.data("tier") === legendFocus.val);
          m.removeClass("dim").addClass("hot");
          m.connectedEdges().removeClass("dim");
        } else {
          const ed =
            legendFocus.val === "__galaxy__"
              ? cy.edges(".galaxy-link")
              : cy.edges().filter((e) => (e.data("edgeType") || "related_to") === legendFocus.val);
          ed.removeClass("dim").addClass("hot");
          ed.connectedNodes().removeClass("dim");
        }
      });
    }, [legendFocus, layoutReady]);

    const edgeLegend = useMemo(() => {
      const t = GRAPH_THEME_TOKENS[appearance.theme];
      return [
        { c: t.accent, t: "Entre spaces", k: "__galaxy__" },
        { c: t.edgeSupports, t: "Apoia", k: "supports" },
        { c: t.edgeContradicts, t: "Contradiz", k: "contradicts" },
        { c: t.edgeDefines, t: "Define", k: "defines" },
        { c: t.edgeEvolved, t: "Evoluiu de", k: "evolved_from" },
        { c: t.edgeDefault, t: "Relacionado", k: "related_to" },
      ];
    }, [appearance.theme]);
    const spaceLegend = useMemo(() => {
      const spaceCounts = new Map<string, number>();
      for (const n of nodes) {
        const k = n.space || "";
        spaceCounts.set(k, (spaceCounts.get(k) ?? 0) + 1);
      }
      return Array.from(spaceCounts.entries())
        .sort((a, b) => b[1] - a[1])
        .map(([name, count]) => ({ name: name || "(sem space)", count, c: spaceColor(name || null) }));
    }, [nodes]);
    // Tier is shown as a shape, not a colour: the swatch mirrors the node it
    // describes — hollow for archived, solid with a rim for core, plain solid
    // for working. A neutral grey fill keeps the swatch space-agnostic.
    const tierLegend = useMemo(() => {
      const counts: Record<string, number> = { core: 0, working: 0, archival: 0 };
      for (const n of nodes) counts[n.tier] = (counts[n.tier] ?? 0) + 1;
      return [
        { val: "core", label: "core", count: counts.core, hollow: false, rim: true },
        { val: "working", label: "working", count: counts.working, hollow: false, rim: false },
        { val: "archival", label: "archival", count: counts.archival, hollow: true, rim: false },
      ];
    }, [nodes]);

    return (
      <div style={{ width: "100%", height: "100%", position: "relative" }}>
        {!layoutReady && (
          <div className="loading">ormahing...</div>
        )}
        <div
          ref={containerRef}
          style={{
            width: "100%",
            height: "100%",
            opacity: layoutReady ? 1 : 0,
            transition: "opacity 0.4s ease-in",
          }}
        />
        {layoutReady && (
          <div
            style={{
              position: "absolute",
              right: 12,
              bottom: 12,
              // Above the cytoscape canvas — without this the canvas swallows
              // legend clicks (elementFromPoint hits the canvas, not the row).
              zIndex: 10,
              maxHeight: "48%",
              overflowY: "auto",
              background: "rgba(12,14,18,0.85)",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 8,
              padding: 10,
              fontFamily: "monospace",
              fontSize: 11,
              color: "#cdd6e0",
              lineHeight: 1.7,
              maxWidth: 230,
            }}
          >
            {clusterBySpace && (
              <>
                <div style={{ ...LEGEND_SECTION_TITLE_STYLE, marginBottom: 4 }}>
                  TIERS
                </div>
                {tierLegend.map((tl) => (
                  <LegendRow
                    key={tl.val}
                    active={!legendFocus || (legendFocus.kind === "tier" && legendFocus.val === tl.val)}
                    onClick={() =>
                      setLegendFocus((f) =>
                        f && f.kind === "tier" && f.val === tl.val ? null : { kind: "tier", val: tl.val },
                      )
                    }
                  >
                    <span
                      style={{
                        width: 11,
                        height: 11,
                        borderRadius: "50%",
                        boxSizing: "border-box",
                        background: tl.hollow ? "transparent" : "#9aa4b2",
                        border: tl.hollow
                          ? "2px solid #9aa4b2"
                          : tl.rim
                            ? `2px solid ${TIER_RIM}`
                            : "none",
                        display: "inline-block",
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ flex: 1 }}>{tl.label}</span>
                    <span style={{ opacity: 0.4 }}>{tl.count}</span>
                  </LegendRow>
                ))}
              </>
            )}
            <div
              style={{
                ...LEGEND_SECTION_TITLE_STYLE,
                margin: clusterBySpace ? "9px 0 4px" : "0 0 4px",
              }}
            >
              LINKS
            </div>
            {edgeLegend.map((e) => (
              <LegendRow
                key={e.t}
                active={!legendFocus || (legendFocus.kind === "edge" && legendFocus.val === e.k)}
                onClick={() =>
                  setLegendFocus((f) =>
                    f && f.kind === "edge" && f.val === e.k ? null : { kind: "edge", val: e.k },
                  )
                }
              >
                <span style={{ width: 16, height: 3, background: e.c, display: "inline-block", borderRadius: 2 }} />
                <span>{e.t}</span>
              </LegendRow>
            ))}
            {clusterBySpace && (
              <>
                <div style={{ ...LEGEND_SECTION_TITLE_STYLE, margin: "9px 0 4px" }}>
                  SPACES
                </div>
                {spaceLegend.map((sp) => {
                  const val = sp.name === "(sem space)" ? "" : sp.name;
                  return (
                    <LegendRow
                      key={sp.name}
                      active={!legendFocus || (legendFocus.kind === "space" && legendFocus.val === val)}
                      onClick={() =>
                        setLegendFocus((f) =>
                          f && f.kind === "space" && f.val === val ? null : { kind: "space", val },
                        )
                      }
                    >
                      <span style={{ width: 9, height: 9, borderRadius: "50%", background: sp.c, display: "inline-block", flexShrink: 0 }} />
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                        {sp.name}
                      </span>
                      <span style={{ opacity: 0.4 }}>{sp.count}</span>
                    </LegendRow>
                  );
                })}
              </>
            )}
          </div>
        )}
      </div>
    );
  }
);

GraphView.displayName = "GraphView";
export default GraphView;
