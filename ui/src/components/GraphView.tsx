import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import cytoscape, { type Core } from "cytoscape";
import cola from "cytoscape-cola";
import {
  GRAPH_DISPLAY_SCALE,
  type GraphAppearance,
  type GraphTheme,
} from "../graphAppearance";
import type { Edge, MemoryNode, Tier } from "../types";

try { cytoscape.use(cola); } catch (_) { /* already registered */ }

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

function nodeSize(accessCount: number): number {
  const baseSize = Math.min(56, Math.max(24, 24 + Math.log2(accessCount + 1) * 6));
  return Math.round(baseSize * GRAPH_DISPLAY_SCALE);
}

function displayNodeSize(accessCount: number, selfRole: string): number {
  const size = nodeSize(accessCount);
  return selfRole === "self" ? Math.max(Math.round(36 * GRAPH_DISPLAY_SCALE), size) : size;
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

const OVERVIEW_PADDING = 150;
const SPACE_FOCUS_PADDING = 110;
const ZOOM_MIN = 0.03;
const ZOOM_MAX = 4;
const ZOOM_SLIDER_MAX = 100;
const ZOOM_SLIDER_STEP = 8;

function clampZoomSliderValue(value: number): number {
  return Math.max(0, Math.min(ZOOM_SLIDER_MAX, value));
}

function zoomToSliderValue(zoom: number): number {
  const normalized =
    Math.log(Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, zoom)) / ZOOM_MIN) /
    Math.log(ZOOM_MAX / ZOOM_MIN);
  return Math.round(normalized * ZOOM_SLIDER_MAX);
}

function sliderValueToZoom(value: number): number {
  return ZOOM_MIN * Math.pow(ZOOM_MAX / ZOOM_MIN, clampZoomSliderValue(value) / ZOOM_SLIDER_MAX);
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
        label: "data(labelText)",
        "font-size": `${Math.round(12 * GRAPH_DISPLAY_SCALE)}px`,
        "min-zoomed-font-size": 8,
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
      selector: "node[tier = 'archival'][selfRole = '']",
      style: {
        "border-style": "dashed" as const,
      } as cytoscape.Css.Node,
    },
    {
      selector: "node:active, node:selected",
      style: {
        "border-color": tokens.accent,
        "border-width": 3,
        "overlay-opacity": 0,
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
      // Cross-space edges are kept subtle so clustered graphs do not turn into
      // a hard lattice.
      selector: "edge.cross-space",
      style: {
        "line-opacity": 0.32,
      } as cytoscape.Css.Edge,
    },
    {
      selector: ".dim",
      style: { opacity: 0.06 } as cytoscape.Css.Node,
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

/**
 * Compute initial positions that place same-space nodes near each other.
 * Each space gets a centroid on a large circle; nodes scatter within.
 */
function computeClusteredPositions(nodes: MemoryNode[]): Map<string, { x: number; y: number }> {
  const spaceGroups = new Map<string, string[]>();
  const ungrouped: string[] = [];
  for (const n of nodes) {
    if (n.space) {
      let g = spaceGroups.get(n.space);
      if (!g) { g = []; spaceGroups.set(n.space, g); }
      g.push(n.id);
    } else {
      ungrouped.push(n.id);
    }
  }

  const spaceList = Array.from(spaceGroups.keys()).sort();
  const hasUngrouped = ungrouped.length > 0;
  const totalGroups = spaceList.length + (hasUngrouped ? 1 : 0);
  const clusterRadius = Math.max(600, Math.sqrt(totalGroups) * 200);
  const positions = new Map<string, { x: number; y: number }>();

  function placeGroup(group: string[], centroidAngle: number) {
    const cx = Math.cos(centroidAngle) * clusterRadius;
    const cy = Math.sin(centroidAngle) * clusterRadius;
    const innerRadius = Math.max(80, Math.sqrt(group.length) * 40);
    group.forEach((id, j) => {
      const a = (2 * Math.PI * j) / group.length;
      positions.set(id, {
        x: cx + Math.cos(a) * innerRadius,
        y: cy + Math.sin(a) * innerRadius,
      });
    });
  }

  spaceList.forEach((space, i) => {
    placeGroup(spaceGroups.get(space)!, (2 * Math.PI * i) / totalGroups);
  });

  if (hasUngrouped) {
    placeGroup(ungrouped, (2 * Math.PI * spaceList.length) / totalGroups);
  }

  return positions;
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

const RIGHT_RAIL_STYLE: CSSProperties = {
  position: "absolute",
  right: 12,
  top: 56,
  bottom: 12,
  zIndex: 10,
  display: "flex",
  alignItems: "flex-end",
  gap: 8,
  minHeight: 0,
  maxWidth: "calc(100% - 24px)",
};

const LEGEND_PANEL_STYLE: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  minHeight: 0,
  maxHeight: "100%",
  overflow: "hidden",
  background: "rgba(12,14,18,0.85)",
  border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 8,
  padding: 10,
  fontFamily: "monospace",
  fontSize: 11,
  color: "#cdd6e0",
  lineHeight: 1.7,
  width: 230,
  maxWidth: "calc(100vw - 78px)",
};

const SPACE_LEGEND_LIST_STYLE: CSSProperties = {
  minHeight: 0,
  overflowY: "auto",
  paddingRight: 3,
};

const ZOOM_CONTROL_STYLE: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: 8,
  width: 34,
  padding: "8px 0",
  background: "rgba(12,14,18,0.82)",
  border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 8,
  boxShadow: "0 12px 30px rgba(0,0,0,0.35)",
};

const ZOOM_BUTTON_STYLE: CSSProperties = {
  width: 22,
  height: 22,
  border: "1px solid rgba(255,255,255,0.14)",
  borderRadius: 6,
  background: "rgba(255,255,255,0.04)",
  color: "#d8dee6",
  fontFamily: "monospace",
  fontSize: 14,
  lineHeight: "18px",
  cursor: "pointer",
};

// Custom vertical zoom slider. Native `<input type=range>` can't be made
// reliably vertical in WebKitGTK (Tauri's webview ignores both `writing-mode`
// and `slider-vertical`), so we draw the track + thumb ourselves and drive it
// with pointer events — identical behavior in every engine. Top = max zoom.
function VerticalZoomSlider({
  value,
  max,
  onChange,
}: {
  value: number;
  max: number;
  onChange: (v: number) => void;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const setFromY = (clientY: number) => {
    const el = trackRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const t = 1 - (clientY - r.top) / r.height; // top = 1 (max), bottom = 0
    onChange(Math.max(0, Math.min(max, Math.round(t * max))));
  };
  const onDown = (e: React.PointerEvent) => {
    dragging.current = true;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setFromY(e.clientY);
  };
  const onMove = (e: React.PointerEvent) => {
    if (dragging.current) setFromY(e.clientY);
  };
  const stop = () => {
    dragging.current = false;
  };

  const filled = max ? value / max : 0; // 0..1 from the bottom
  return (
    <div
      ref={trackRef}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={stop}
      onPointerCancel={stop}
      role="slider"
      aria-label="Graph zoom"
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      style={{ position: "relative", width: 22, height: 122, cursor: "pointer", touchAction: "none" }}
    >
      {/* rail */}
      <div
        style={{
          position: "absolute", left: "50%", top: 0, transform: "translateX(-50%)",
          width: 3, height: "100%", borderRadius: 2, background: "rgba(255,255,255,0.16)",
        }}
      />
      {/* filled portion (from bottom up to the thumb) */}
      <div
        style={{
          position: "absolute", left: "50%", bottom: 0, transform: "translateX(-50%)",
          width: 3, height: `${filled * 100}%`, borderRadius: 2, background: "#d4a574",
        }}
      />
      {/* thumb */}
      <div
        style={{
          position: "absolute", left: "50%", top: `${(1 - filled) * 100}%`,
          transform: "translate(-50%, -50%)", width: 14, height: 14, borderRadius: "50%",
          background: "#d4a574", boxShadow: "0 0 0 2px rgba(10,10,10,0.6), 0 1px 3px rgba(0,0,0,0.6)",
        }}
      />
    </div>
  );
}

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
    const [zoomSliderValue, setZoomSliderValue] = useState(() => zoomToSliderValue(0.18));

    const identityNodeIds = useMemo(() => {
      const ids = new Set<string>();
      if (!userNodeId) return ids;
      for (const e of edges) {
        if (e.edge_type === "defines" && e.source_id === userNodeId) {
          ids.add(e.target_id);
        }
      }
      return ids;
    }, [edges, userNodeId]);


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

    useLayoutEffect(() => {
      if (!containerRef.current) return;
      setLayoutReady(false);

      const nodeIds = new Set(nodes.map((n) => n.id));

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

      const themeTokens = GRAPH_THEME_TOKENS[appearance.theme];
      const nodeElements = nodes.map((n) => {
        const sr = selfRole(n.id);
        const size = displayNodeSize(n.access_count, sr);
        return {
          data: {
            id: n.id,
            labelText: nodeLabel(n),
            space: n.space || "",
            tier: n.tier,
            type: n.type,
            accessCount: n.access_count,
            selfRole: sr,
            bgColor: tierColor(n.tier, sr, appearance),
            borderColor: tierBorderColor(n.tier, sr, appearance),
            borderWidth: sr === "self" ? 3 : n.tier === "archival" ? 1 : 2,
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
              edgeOpacity: Math.max(0.2, e.weight ?? 0.5),
            },
            classes: crossSpace ? "cross-space" : undefined,
          };
        });

      const positions = clusterBySpace
        ? computeClusteredPositions(nodes)
        : null;

      const cy = cytoscape({
        container: containerRef.current,
        elements: [...nodeElements, ...edgeElements],
        style: buildStyles(appearance),
        layout: { name: "preset" },
        minZoom: ZOOM_MIN,
        maxZoom: ZOOM_MAX,
        wheelSensitivity: 0.3,
      });

      const syncZoomSlider = () => {
        setZoomSliderValue(zoomToSliderValue(cy.zoom()));
      };
      cy.on("zoom", syncZoomSlider);

      if (positions) {
        cy.nodes().forEach((node) => {
          const pos = positions.get(node.id());
          if (pos) node.position(pos);
        });
      }
      if (cy.nodes().length) {
        cy.fit(undefined, OVERVIEW_PADDING);
        syncZoomSlider();
      }

      cy.nodes().grabify();

      const maxSimulationTime = Math.min(8000, 1500 + nodes.length);
      const layout = cy.layout({
        name: "cola",
        animate: true,
        infinite: false,
        maxSimulationTime,
        refresh: nodes.length > 2500 ? 8 : 1,
        fit: false,
        ungrabifyWhileSimulating: false,
        nodeSpacing: clusterBySpace ? 60 : 40,
        edgeLength: (edge: cytoscape.EdgeSingular) => {
          const w = edge.data("weight") ?? 0.5;
          const baseLen = 120 + (1 - w) * 100;
          if (clusterBySpace) {
            const srcSpace = nodeSpaceMap.get(edge.source().id());
            const tgtSpace = nodeSpaceMap.get(edge.target().id());
            if (srcSpace !== tgtSpace) return baseLen * 5;
          }
          return baseLen;
        },
        convergenceThreshold: 0.01,
        randomize: !positions,
        avoidOverlap: true,
        handleDisconnected: !clusterBySpace,
      } as never);
      layoutRef.current = layout;

      let layoutSettled = false;
      let layoutWatchdog: ReturnType<typeof setTimeout> | null = null;
      const finishLayout = () => {
        if (layoutSettled) return;
        layoutSettled = true;
        if (layoutWatchdog) {
          clearTimeout(layoutWatchdog);
          layoutWatchdog = null;
        }
        cy.fit(undefined, OVERVIEW_PADDING);
        syncZoomSlider();
        setLayoutReady(true);
      };

      layout.one("layoutstop", finishLayout);
      layoutWatchdog = setTimeout(() => {
        if (layoutSettled) return;
        layout.stop();
        finishLayout();
      }, maxSimulationTime + 1500);
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
        if (layoutWatchdog) {
          clearTimeout(layoutWatchdog);
          layoutWatchdog = null;
        }
        if (layoutRef.current) {
          layoutRef.current.stop();
          layoutRef.current = null;
        }
        cy.destroy();
        cyRef.current = null;
      };
    }, [nodes, edges, userNodeId, clusterBySpace, identityNodeIds]);

    useEffect(() => {
      const cy = cyRef.current;
      if (!cy) return;

      const themeTokens = GRAPH_THEME_TOKENS[appearance.theme];
      cy.style(buildStyles(appearance));
      cy.nodes().forEach((node) => {
        const tier = node.data("tier") as string;
        const selfRole = node.data("selfRole") as string;
        node.data("bgColor", tierColor(tier, selfRole, appearance));
        node.data("borderColor", tierBorderColor(tier, selfRole, appearance));
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
        cy.elements().addClass("dim");
        if (legendFocus.kind === "space") {
          const m = cy.nodes().filter((n) => n.data("space") === legendFocus.val);
          m.removeClass("dim").addClass("hot");
          m.connectedEdges().removeClass("dim");
        } else if (legendFocus.kind === "tier") {
          const m = cy.nodes().filter((n) => n.data("tier") === legendFocus.val);
          m.removeClass("dim").addClass("hot");
          m.connectedEdges().removeClass("dim");
        } else if (legendFocus.kind === "role") {
          const m = cy.nodes().filter((n) => n.data("selfRole") === legendFocus.val);
          m.removeClass("dim").addClass("hot");
          m.connectedEdges().removeClass("dim");
        } else {
          const ed = cy.edges().filter((e) => (e.data("edgeType") || "related_to") === legendFocus.val);
          ed.removeClass("dim").addClass("hot");
          ed.connectedNodes().removeClass("dim");
        }
      });
    }, [legendFocus, layoutReady]);

    const visibleLegendTargets = useMemo(() => {
      const nodeIds = new Set(nodes.map((n) => n.id));
      const edgeTypes = new Set<string>();

      for (const e of edges) {
        if (!nodeIds.has(e.source_id) || !nodeIds.has(e.target_id)) continue;
        edgeTypes.add(e.edge_type || "related_to");
      }

      return { edgeTypes };
    }, [nodes, edges]);

    useEffect(() => {
      if (!legendFocus) return;

      let stillVisible = false;
      if (legendFocus.kind === "space") {
        stillVisible = clusterBySpace && nodes.some((n) => (n.space || "") === legendFocus.val);
      } else if (legendFocus.kind === "tier") {
        stillVisible = clusterBySpace && nodes.some((n) => n.tier === legendFocus.val);
      } else if (legendFocus.kind === "role") {
        if (legendFocus.val === "self") {
          stillVisible = !!userNodeId && nodes.some((n) => n.id === userNodeId);
        } else {
          stillVisible = nodes.some((n) => identityNodeIds.has(n.id));
        }
      } else {
        stillVisible = visibleLegendTargets.edgeTypes.has(legendFocus.val);
      }

      if (!stillVisible) setLegendFocus(null);
    }, [clusterBySpace, identityNodeIds, legendFocus, nodes, userNodeId, visibleLegendTargets]);

    const edgeLegend = useMemo(() => {
      const t = GRAPH_THEME_TOKENS[appearance.theme];
      const rows = [
        { c: t.edgeSupports, t: "Supports", k: "supports" },
        { c: t.edgeContradicts, t: "Contradicts", k: "contradicts" },
        { c: t.edgeDefines, t: "Defines", k: "defines" },
        { c: t.edgeEvolved, t: "Evolved from", k: "evolved_from" },
        { c: t.edgeDefault, t: "Related", k: "related_to" },
      ].filter((row) => visibleLegendTargets.edgeTypes.has(row.k));

      return rows;
    }, [appearance.theme, visibleLegendTargets]);
    const spaceLegend = useMemo(() => {
      const spaceCounts = new Map<string, number>();
      for (const n of nodes) {
        const k = n.space || "";
        spaceCounts.set(k, (spaceCounts.get(k) ?? 0) + 1);
      }
      return Array.from(spaceCounts.entries())
        .sort((a, b) => b[1] - a[1])
        .map(([name, count]) => ({ name: name || "(no space)", count }));
    }, [nodes]);
    const tierLegend = useMemo(() => {
      const counts: Record<string, number> = { core: 0, working: 0, archival: 0 };
      for (const n of nodes) counts[n.tier] = (counts[n.tier] ?? 0) + 1;
      return [
        { val: "core", label: "core", count: counts.core, color: appearance.colors.core, dashed: false },
        { val: "working", label: "working", count: counts.working, color: appearance.colors.working, dashed: false },
        { val: "archival", label: "archival", count: counts.archival, color: appearance.colors.archival, dashed: true },
      ];
    }, [nodes, appearance.colors.archival, appearance.colors.core, appearance.colors.working]);
    const roleLegend = useMemo(() => {
      const selfCount = userNodeId && nodes.some((n) => n.id === userNodeId) ? 1 : 0;
      let identityCount = 0;
      for (const n of nodes) {
        if (identityNodeIds.has(n.id)) identityCount += 1;
      }

      return [
        { val: "self", label: "self", count: selfCount, color: "#74b3a5" },
        { val: "identity", label: "identity", count: identityCount, color: "#4d8a7e" },
      ].filter((row) => row.count > 0);
    }, [identityNodeIds, nodes, userNodeId]);
    const showLegend = clusterBySpace || edgeLegend.length > 0;

    const clearGraphSelection = () => {
      const cy = cyRef.current;
      if (!cy) return;
      cy.nodes().unselect();
      cy.elements().removeClass("glow glow-neighbor");
    };

    const toggleLegendFocus = (kind: string, val: string) => {
      clearGraphSelection();
      setLegendFocus((f) =>
        f && f.kind === kind && f.val === val ? null : { kind, val },
      );
    };

    const focusSpace = (space: string) => {
      clearGraphSelection();
      const nextActive = !(legendFocus && legendFocus.kind === "space" && legendFocus.val === space);
      setLegendFocus(nextActive ? { kind: "space", val: space } : null);

      const cy = cyRef.current;
      if (!cy || !layoutReady) return;

      if (!nextActive) {
        cy.fit(undefined, OVERVIEW_PADDING);
        return;
      }

      const spaceNodes = cy.nodes().filter((node) => node.data("space") === space);
      if (spaceNodes.length) {
        cy.fit(spaceNodes, SPACE_FOCUS_PADDING);
      }
    };

    const focusRole = (role: string) => {
      clearGraphSelection();
      const nextActive = !(legendFocus && legendFocus.kind === "role" && legendFocus.val === role);
      setLegendFocus(nextActive ? { kind: "role", val: role } : null);

      const cy = cyRef.current;
      if (!cy || !layoutReady) return;

      if (!nextActive) {
        cy.fit(undefined, OVERVIEW_PADDING);
        return;
      }

      const roleNodes = cy.nodes().filter((node) => node.data("selfRole") === role);
      if (roleNodes.length) {
        cy.fit(roleNodes, SPACE_FOCUS_PADDING);
        if (cy.zoom() > 1.6) {
          cy.zoom(1.6);
          cy.center(roleNodes);
        }
      }
    };

    const applyZoomSliderValue = (value: number) => {
      const nextValue = clampZoomSliderValue(value);
      setZoomSliderValue(nextValue);

      const cy = cyRef.current;
      if (!cy) return;

      cy.zoom({
        level: sliderValueToZoom(nextValue),
        renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 },
      } as never);
    };

    const nudgeZoom = (delta: number) => {
      const cy = cyRef.current;
      const currentValue = cy ? zoomToSliderValue(cy.zoom()) : zoomSliderValue;
      applyZoomSliderValue(currentValue + delta);
    };

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
          <div style={RIGHT_RAIL_STYLE}>
            <div
              style={ZOOM_CONTROL_STYLE}
              onPointerDown={(e) => e.stopPropagation()}
              onWheel={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                style={ZOOM_BUTTON_STYLE}
                onClick={() => nudgeZoom(ZOOM_SLIDER_STEP)}
                aria-label="Zoom in"
                title="Zoom in"
              >
                +
              </button>
              <VerticalZoomSlider
                value={zoomSliderValue}
                max={ZOOM_SLIDER_MAX}
                onChange={applyZoomSliderValue}
              />
              <button
                type="button"
                style={ZOOM_BUTTON_STYLE}
                onClick={() => nudgeZoom(-ZOOM_SLIDER_STEP)}
                aria-label="Zoom out"
                title="Zoom out"
              >
                -
              </button>
            </div>
            {showLegend && (
              <div
                style={LEGEND_PANEL_STYLE}
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
                    onClick={() => toggleLegendFocus("tier", tl.val)}
                  >
                    <span
                      style={{
                        width: 11,
                        height: 11,
                        borderRadius: "50%",
                        boxSizing: "border-box",
                        background: tl.color,
                        border: tl.dashed ? "1px dashed rgba(255,255,255,0.75)" : "none",
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
            {clusterBySpace && roleLegend.length > 0 && (
              <>
                <div style={{ ...LEGEND_SECTION_TITLE_STYLE, margin: "9px 0 4px" }}>
                  IDENTITY
                </div>
                {roleLegend.map((rl) => (
                  <LegendRow
                    key={rl.val}
                    active={!legendFocus || (legendFocus.kind === "role" && legendFocus.val === rl.val)}
                    onClick={() => focusRole(rl.val)}
                  >
                    <span
                      style={{
                        width: 11,
                        height: 11,
                        borderRadius: "50%",
                        boxSizing: "border-box",
                        background: rl.color,
                        border: "1px solid rgba(255,255,255,0.22)",
                        display: "inline-block",
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ flex: 1 }}>{rl.label}</span>
                    <span style={{ opacity: 0.4 }}>{rl.count}</span>
                  </LegendRow>
                ))}
              </>
            )}
            {edgeLegend.length > 0 && (
              <>
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
                    onClick={() => toggleLegendFocus("edge", e.k)}
                  >
                    <span style={{ width: 16, height: 3, background: e.c, display: "inline-block", borderRadius: 2 }} />
                    <span>{e.t}</span>
                  </LegendRow>
                ))}
              </>
            )}
            {clusterBySpace && (
              <>
                <div style={{ ...LEGEND_SECTION_TITLE_STYLE, margin: "9px 0 4px" }}>
                  SPACES
                </div>
                <div style={SPACE_LEGEND_LIST_STYLE}>
                  {spaceLegend.map((sp) => {
                    const val = sp.name === "(no space)" ? "" : sp.name;
                    return (
                      <LegendRow
                        key={sp.name}
                        active={!legendFocus || (legendFocus.kind === "space" && legendFocus.val === val)}
                        onClick={() => focusSpace(val)}
                      >
                        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                          {sp.name}
                        </span>
                        <span style={{ opacity: 0.4 }}>{sp.count}</span>
                      </LegendRow>
                    );
                  })}
                </div>
              </>
            )}
              </div>
            )}
          </div>
        )}
      </div>
    );
  }
);

GraphView.displayName = "GraphView";
export default GraphView;
