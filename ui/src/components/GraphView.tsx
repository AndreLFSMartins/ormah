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
import Graph from "graphology";
import Sigma from "sigma";
import { buildGraph, applyAppearance } from "../graph/graphModel";
import { createForceLayout, type ForceLayout } from "../graph/forceLayout";
import { makeNodeReducer, makeEdgeReducer, type ViewState } from "../graph/sigmaReducers";
import { focusFitIds } from "./legendFit";
import { fitToNodes } from "./fit";
import { GRAPH_THEME_TOKENS } from "../graph/visual";
import { type GraphAppearance, type GraphTheme } from "../graphAppearance";
import type { Edge, MemoryNode } from "../types";
import { ALL_TIERS, ALL_NODE_TYPES, ALL_EDGE_TYPES } from "../types";
import type { Filters } from "../App";

// ─── Zoom slider helpers (unchanged from cytoscape era) ───────────────────────
const ZOOM_MIN = 0.03;
const ZOOM_MAX = 4;
const ZOOM_SLIDER_MAX = 100;
const ZOOM_SLIDER_STEP = 8;

function clampZoomSliderValue(value: number): number {
  return Math.max(0, Math.min(ZOOM_SLIDER_MAX, value));
}
function zoomToSliderValue(zoom: number): number {
  return Math.round(
    (Math.log(Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, zoom)) / ZOOM_MIN) /
      Math.log(ZOOM_MAX / ZOOM_MIN)) *
      ZOOM_SLIDER_MAX,
  );
}
function sliderValueToZoom(value: number): number {
  return ZOOM_MIN * Math.pow(ZOOM_MAX / ZOOM_MIN, clampZoomSliderValue(value) / ZOOM_SLIDER_MAX);
}

// ─── Sigma ratio ↔ zoom conversion helpers ────────────────────────────────────
// sigma ratio is inverse of zoom: ratio = 1/zoom (approx). Lower ratio = more zoomed in.
// We map the slider (higher value = more zoomed in) to a lower ratio.
function sliderValueToRatio(value: number): number {
  // reuse the same log scale; map zoom→ratio = 1/zoom
  const zoom = sliderValueToZoom(value);
  return 1 / zoom;
}
function ratioToSliderValue(ratio: number): number {
  const zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, 1 / Math.max(ratio, 1e-9)));
  return zoomToSliderValue(zoom);
}

// ─── Styles (unchanged from cytoscape era) ───────────────────────────────────
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

const ZOOM_RANGE_STYLE: CSSProperties = {
  writingMode: "vertical-lr",
  direction: "rtl",
  height: 90,
  accentColor: "#d4a574",
  cursor: "pointer",
};

// ─── LegendRow component ─────────────────────────────────────────────────────
// One clickable legend row: swatch + content as children, dimmed when another
// row is active (focus system A1). Forwards data-testid to the root element.
function LegendRow({
  active,
  onClick,
  children,
  "data-testid": dataTestId,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
  "data-testid"?: string;
}) {
  return (
    <div
      style={{
        ...LEGEND_ROW_STYLE,
        opacity: active ? 1 : 0.3,
        transition: "opacity 0.15s",
      }}
      onClick={onClick}
      data-testid={dataTestId}
    >
      {children}
    </div>
  );
}

// ─── Props ────────────────────────────────────────────────────────────────────
interface Props {
  nodes: MemoryNode[];
  edges: Edge[];
  onNodeSelect: (id: string) => void;
  focusNodeId: string | null;
  userNodeId: string | null;
  clusterBySpace: boolean;
  appearance: GraphAppearance;
  /** Council C2: App.tsx filter state. Drives dimmed.* in the reducer (HIDE); does NOT remount. */
  filters: Filters;
}

// ─── GraphView ────────────────────────────────────────────────────────────────
const GraphView = forwardRef<
  {
    focusNode: (id: string) => void;
    highlightNode: (id: string) => void;
    highlightNodes: (ids: string[]) => void;
    clearHighlight: () => void;
  },
  Props
>(
  (
    { nodes, edges, onNodeSelect, focusNodeId, userNodeId, clusterBySpace, appearance, filters },
    ref,
  ) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const tooltipRef = useRef<HTMLDivElement>(null);
    const sigmaRef = useRef<Sigma | null>(null);
    const graphRef = useRef<Graph | null>(null);
    const layoutRef = useRef<ForceLayout | null>(null);
    const onNodeSelectRef = useRef(onNodeSelect);
    onNodeSelectRef.current = onNodeSelect;

    const [layoutReady, setLayoutReady] = useState(false);
    // A1: legend focus state
    const [legendFocus, setLegendFocus] = useState<{ kind: string; val: string } | null>(null);
    // Zoom slider (visual state only; driven from camera events)
    const [zoomSliderValue, setZoomSliderValue] = useState(() => zoomToSliderValue(0.18));

    // ─── ViewState ref (single source of truth for reducer) ──────────────────
    // Council C1: initialised once; updated imperatively; reducer reads it via ref.
    const viewStateRef = useRef<ViewState>({
      hoveredNode: null,
      neighbors: new Set(),
      highlightSet: new Set(),
      glowOnly: new Set(),
      focusKind: null,
      dimmed: { space: new Set(), tier: new Set(), role: new Set(), type: new Set(), edge: new Set() },
      attrsById: new Map(),
      edgeTypeById: new Map(),
      dimColor: appearance.theme === "dark" ? "#2a2a2a" : "#cfd6de",
    });

    // ─── Legend data memos ────────────────────────────────────────────────────
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

    const visibleLegendTargets = useMemo(() => {
      const nodeIds = new Set(nodes.map((n) => n.id));
      const edgeTypes = new Set<string>();
      for (const e of edges) {
        if (!nodeIds.has(e.source_id) || !nodeIds.has(e.target_id)) continue;
        edgeTypes.add(e.edge_type || "related_to");
      }
      return { edgeTypes };
    }, [nodes, edges]);

    const edgeLegend = useMemo(() => {
      const t = GRAPH_THEME_TOKENS[appearance.theme as GraphTheme];
      const rows = [
        { c: t.edgeSupports,    t: "Supports",     k: "supports" },
        { c: t.edgeContradicts, t: "Contradicts",   k: "contradicts" },
        { c: t.edgeDefines,     t: "Defines",       k: "defines" },
        { c: t.edgeEvolved,     t: "Evolved from",  k: "evolved_from" },
        { c: t.edgeDefault,     t: "Related",       k: "related_to" },
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
        { val: "core",     label: "core",     count: counts.core,     color: appearance.colors.core,     dashed: false },
        { val: "working",  label: "working",  count: counts.working,  color: appearance.colors.working,  dashed: false },
        { val: "archival", label: "archival", count: counts.archival, color: appearance.colors.archival, dashed: true  },
      ];
    }, [nodes, appearance.colors.archival, appearance.colors.core, appearance.colors.working]);

    const roleLegend = useMemo(() => {
      const selfCount = userNodeId && nodes.some((n) => n.id === userNodeId) ? 1 : 0;
      let identityCount = 0;
      for (const n of nodes) {
        if (identityNodeIds.has(n.id)) identityCount += 1;
      }
      return [
        { val: "self",     label: "self",     count: selfCount,     color: "#74b3a5" },
        { val: "identity", label: "identity", count: identityCount, color: "#4d8a7e" },
      ].filter((row) => row.count > 0);
    }, [identityNodeIds, nodes, userNodeId]);

    const showLegend = clusterBySpace || edgeLegend.length > 0;

    // ─── Mount effect: build graph + start sigma + layout ─────────────────────
    // Deps: [nodes, edges, userNodeId] — does NOT include filters or appearance.
    // Council C2: filters applied via dimmed.* without remounting.
    // Council M4: appearance applied via restyle effect without remounting.
    useEffect(() => {
      if (!containerRef.current) return;

      setLayoutReady(false);
      setLegendFocus(null);

      const graph = buildGraph({ nodes, edges, user_node_id: userNodeId ?? null }, appearance);
      graphRef.current = graph;

      // Build lookup maps for the reducer
      const attrsById = new Map<string, { space: string; tier: string; selfRole: string; type: string }>();
      graph.forEachNode((id, a) =>
        attrsById.set(id, {
          space: (a.space as string) ?? "",
          tier: a.tier as string,
          selfRole: a.selfRole as string,
          type: (a.nodeType as string) ?? "",
        }),
      );
      const edgeTypeById = new Map<string, string>();
      graph.forEachEdge((e, a) => edgeTypeById.set(e, (a.edgeType as string) ?? ""));
      viewStateRef.current.attrsById = attrsById;
      viewStateRef.current.edgeTypeById = edgeTypeById;

      // Seed dimmed from current filters (so initial render is consistent)
      viewStateRef.current.dimmed = buildDimmed(filters, graph);
      viewStateRef.current.dimColor = appearance.theme === "dark" ? "#2a2a2a" : "#cfd6de";
      viewStateRef.current.focusKind = null;
      viewStateRef.current.hoveredNode = null;
      viewStateRef.current.neighbors = new Set();
      viewStateRef.current.highlightSet = new Set();
      viewStateRef.current.glowOnly = new Set();

      const renderer = new Sigma(graph, containerRef.current, {
        enableEdgeEvents: true,
        labelRenderedSizeThreshold: 8,
        // Node sizes live in layout-position units and scale 1:1 with zoom, like
        // Obsidian's graph: zoom out -> nodes shrink with the gaps (dots), zoom in
        // -> readable. Default "screen" keeps sizes fixed in px, which overlapped
        // ~1800 nodes into an unreadable blob. See visual.ts nodeSize().
        itemSizesReference: "positions",
        zoomToSizeRatioFunction: (ratio) => ratio,
        nodeReducer: (node, data) => makeNodeReducer(viewStateRef.current)(node, data),
        edgeReducer: (edge, data) =>
          makeEdgeReducer(viewStateRef.current, (e) => [graph.source(e), graph.target(e)])(edge, data),
      });
      sigmaRef.current = renderer;

      // DEV-only debug handles (Council L1 + needed by Task 7 tests)
      if (import.meta.env.DEV) {
        (window as unknown as Record<string, unknown>).__ormahGraph = graph;
        (window as unknown as Record<string, unknown>).__ormahSigma = renderer;
      }

      // ── Force layout ──────────────────────────────────────────────────────
      const layout = createForceLayout(graph);
      layoutRef.current = layout;
      layout.start();

      // Mark layout ready after a brief settle (matches old cytoscape watchdog pattern)
      const layoutWatchdog = setTimeout(() => {
        setLayoutReady(true);
      }, 800);

      // ── Sync zoom slider from camera ──────────────────────────────────────
      const syncZoomSlider = () => {
        setZoomSliderValue(ratioToSliderValue(renderer.getCamera().ratio));
      };
      renderer.getCamera().on("updated", syncZoomSlider);

      // ── Hover highlight (6.2) ─────────────────────────────────────────────
      function neighborsOf(id: string): Set<string> {
        const s = new Set<string>();
        graph.forEachNeighbor(id, (n) => s.add(n));
        return s;
      }
      function setHover(id: string | null) {
        viewStateRef.current.hoveredNode = id;
        viewStateRef.current.neighbors = id ? neighborsOf(id) : new Set();
        renderer.refresh();
      }

      // ── Tooltip helpers (6.5) ─────────────────────────────────────────────
      function showTooltip(label: string, space: string, _gx: number, _gy: number, clientX: number, clientY: number) {
        const t = tooltipRef.current;
        if (!t || !containerRef.current) return;
        const rect = containerRef.current.getBoundingClientRect();
        t.textContent = space ? `${label} · ${space}` : label;
        t.style.left = `${clientX - rect.left + 14}px`;
        t.style.top = `${clientY - rect.top - 10}px`;
        t.style.opacity = "1";
      }
      function hideTooltip() {
        const t = tooltipRef.current;
        if (t) t.style.opacity = "0";
      }

      // enterNode — hover highlight + tooltip
      renderer.on("enterNode", ({ node, event }) => {
        setHover(node);
        const label = graph.getNodeAttribute(node, "label") as string;
        const space = (graph.getNodeAttribute(node, "space") as string) || "(no space)";
        const displayData = renderer.getNodeDisplayData(node);
        const gx = displayData?.x ?? 0;
        const gy = displayData?.y ?? 0;
        // event.original is MouseEvent | TouchEvent; narrow to MouseEvent for clientX/Y.
        const orig = event.original;
        const clientX = "clientX" in orig ? orig.clientX : 0;
        const clientY = "clientY" in orig ? orig.clientY : 0;
        showTooltip(label, space, gx, gy, clientX, clientY);
      });
      renderer.on("leaveNode", () => {
        setHover(null);
        hideTooltip();
      });
      renderer.on("clickNode", ({ node }) => onNodeSelectRef.current(node));
      renderer.on("clickStage", () => setHover(null));

      // ── Drag + reheat (6.5) ───────────────────────────────────────────────
      let dragged: string | null = null;
      renderer.on("downNode", ({ node }) => {
        dragged = node;
        layout.stop();
      });
      renderer.getMouseCaptor().on("mousemovebody", (e) => {
        if (!dragged) return;
        const pos = renderer.viewportToGraph(e);
        graph.setNodeAttribute(dragged, "x", pos.x);
        graph.setNodeAttribute(dragged, "y", pos.y);
        e.preventSigmaDefault();
        e.original.preventDefault();
        e.original.stopPropagation();
      });
      renderer.getMouseCaptor().on("mouseup", () => {
        if (!dragged) return;
        dragged = null;
        layout.reheat();
      });

      return () => {
        clearTimeout(layoutWatchdog);
        layout.kill();
        layoutRef.current = null;
        renderer.kill();
        sigmaRef.current = null;
        graphRef.current = null;
        if (import.meta.env.DEV) {
          delete (window as unknown as Record<string, unknown>).__ormahGraph;
          delete (window as unknown as Record<string, unknown>).__ormahSigma;
        }
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [nodes, edges, userNodeId]);

    // ─── Restyle effect: in-place recolor/resize without remounting (Council M4) ─
    // Deps include appearance, nodes, edges, userNodeId — never recreates sigma.
    useEffect(() => {
      const g = graphRef.current, r = sigmaRef.current;
      if (!g || !r) return;
      applyAppearance(g, { nodes, edges, user_node_id: userNodeId ?? null }, appearance);
      viewStateRef.current.dimColor = appearance.theme === "dark" ? "#2a2a2a" : "#cfd6de";
      r.refresh();
    }, [appearance, nodes, edges, userNodeId]);

    // ─── Filter-dim effect (Council C2): update dimmed.* without remounting ───
    // App.tsx passes the FULL graph.nodes/graph.edges + the filters prop (it no
    // longer shrinks the arrays — that would remount sigma and reset the camera).
    // buildDimmed() converts the active filter sets into the complement dim sets:
    //   filters.tiers     → dimmed.tier  (tiers NOT active)
    //   filters.spaces    → dimmed.space (spaces NOT active, when the set is non-empty)
    //   filters.types     → dimmed.type  (node types NOT active — FilterDrawer type filter)
    //   filters.edgeTypes → dimmed.edge  (edge types NOT active)
    // The reducer then dims/hides anything matching a dim set. A filter toggle costs
    // one refresh(), not a graph rebuild.
    useEffect(() => {
      const r = sigmaRef.current, g = graphRef.current;
      if (!r || !g) return;
      viewStateRef.current.dimmed = buildDimmed(filters, g);
      r.refresh();
    }, [filters]);

    // ─── Legend FOCUS handler (Council A1) ────────────────────────────────────
    // Two distinct dimming systems (do NOT conflate):
    //   Legend click = FOCUS: highlights that item's nodes, dims rest, fits camera.
    //   App.tsx filters = HIDE: drives dimmed.* via the effect above.
    function focusLegend(kind: "space" | "tier" | "role" | "edge", val: string) {
      setLegendFocus((prev) => {
        const next = prev && prev.kind === kind && prev.val === val ? null : { kind, val };
        viewStateRef.current.focusKind = next;
        const r = sigmaRef.current, g = graphRef.current;
        // Fit on focus AND on clear: focusFitIds returns the whole graph when next === null.
        if (r && g) {
          fitToNodes(r, g, focusFitIds(g, next));
        }
        r?.refresh();
        return next;
      });
    }

    // ─── Imperative ref API (6.3) — same signatures as the cytoscape era ─────
    useImperativeHandle(ref, () => ({
      focusNode(id: string) {
        const r = sigmaRef.current, g = graphRef.current;
        if (!r || !g || !g.hasNode(id)) return;
        const displayData = r.getNodeDisplayData(id);
        if (!displayData) return;
        const { x, y } = displayData;
        r.getCamera().animate({ x, y, ratio: 0.4 }, { duration: 400 });
      },
      highlightNode(id: string) {
        // Council A4: search-hover = glow-only (highlight WITHOUT dimming others)
        const r = sigmaRef.current, g = graphRef.current;
        if (!r || !g) return;
        if (!g.hasNode(id)) return;
        viewStateRef.current.glowOnly = new Set([id]);
        viewStateRef.current.highlightSet = new Set();
        viewStateRef.current.hoveredNode = null;
        viewStateRef.current.neighbors = new Set();
        r.refresh();
      },
      highlightNodes(ids: string[]) {
        // Council H1: multi-highlight — members vivid + dims rest + camera fit.
        // Used by Insights/Review panels.
        const r = sigmaRef.current, g = graphRef.current;
        if (!r || !g) return;
        const present = ids.filter((id) => g.hasNode(id));
        viewStateRef.current.glowOnly = new Set();
        viewStateRef.current.hoveredNode = null;
        viewStateRef.current.highlightSet = new Set(present);
        fitToNodes(r, g, present);
        r.refresh();
      },
      clearHighlight() {
        const r = sigmaRef.current;
        if (!r) return;
        viewStateRef.current.hoveredNode = null;
        viewStateRef.current.neighbors = new Set();
        viewStateRef.current.highlightSet = new Set();
        viewStateRef.current.glowOnly = new Set();
        r.refresh();
      },
    }));

    // ─── focusNodeId effect (6.6, Council M1) ────────────────────────────────
    useEffect(() => {
      const r = sigmaRef.current, g = graphRef.current;
      if (!r || !g || !focusNodeId || !g.hasNode(focusNodeId)) return;
      const displayData = r.getNodeDisplayData(focusNodeId);
      if (!displayData) return;
      const { x, y } = displayData;
      r.getCamera().animate({ x, y, ratio: 0.4 }, { duration: 400 });
    }, [focusNodeId]);

    // ─── Zoom helpers (6.6, Council M3) ──────────────────────────────────────
    // sigma camera: animatedZoom/animatedUnzoom/animatedReset confirmed in camera.d.ts.
    function zoomIn() {
      sigmaRef.current?.getCamera().animatedZoom({ duration: 200 });
    }
    function zoomOut() {
      sigmaRef.current?.getCamera().animatedUnzoom({ duration: 200 });
    }
    function applyZoomSliderValue(value: number) {
      const nextValue = clampZoomSliderValue(value);
      setZoomSliderValue(nextValue);
      const ratio = sliderValueToRatio(nextValue);
      sigmaRef.current?.getCamera().animate({ ratio }, { duration: 150 });
    }
    function nudgeZoom(delta: number) {
      applyZoomSliderValue(zoomSliderValue + delta);
    }

    // ─── JSX ─────────────────────────────────────────────────────────────────
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
        {/* Node hover tooltip */}
        <div
          ref={tooltipRef}
          style={{
            position: "absolute",
            pointerEvents: "none",
            background: "rgba(12,14,18,0.88)",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: 6,
            padding: "4px 8px",
            fontFamily: "monospace",
            fontSize: 11,
            color: "#cdd6e0",
            opacity: 0,
            transition: "opacity 0.1s",
            whiteSpace: "nowrap",
            zIndex: 20,
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
                onClick={zoomIn}
                aria-label="Zoom in"
                title="Zoom in"
              >
                +
              </button>
              <input
                type="range"
                min={0}
                max={ZOOM_SLIDER_MAX}
                step={1}
                value={zoomSliderValue}
                onChange={(e) => applyZoomSliderValue(Number(e.target.value))}
                aria-label="Graph zoom"
                style={ZOOM_RANGE_STYLE}
              />
              <button
                type="button"
                style={ZOOM_BUTTON_STYLE}
                onClick={zoomOut}
                aria-label="Zoom out"
                title="Zoom out"
              >
                -
              </button>
            </div>
            {showLegend && (
              <div style={LEGEND_PANEL_STYLE}>
                {clusterBySpace && (
                  <>
                    <div style={{ ...LEGEND_SECTION_TITLE_STYLE, marginBottom: 4 }}>
                      TIERS
                    </div>
                    {tierLegend.map((tl) => (
                      <LegendRow
                        key={tl.val}
                        active={!legendFocus || (legendFocus.kind === "tier" && legendFocus.val === tl.val)}
                        onClick={() => focusLegend("tier", tl.val)}
                      >
                        <span
                          style={{
                            width: 10,
                            height: 10,
                            borderRadius: "50%",
                            background: tl.color,
                            border: tl.dashed ? "1.5px dashed rgba(255,255,255,0.3)" : "none",
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
                        onClick={() => focusLegend("role", rl.val)}
                      >
                        <span
                          style={{
                            width: 10,
                            height: 10,
                            borderRadius: "50%",
                            background: rl.color,
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
                        key={e.k}
                        active={!legendFocus || (legendFocus.kind === "edge" && legendFocus.val === e.k)}
                        onClick={() => focusLegend("edge", e.k)}
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
                            data-testid={`legend-space-${sp.name}`}
                            active={!legendFocus || (legendFocus.kind === "space" && legendFocus.val === val)}
                            onClick={() => focusLegend("space", val)}
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
  },
);

GraphView.displayName = "GraphView";
export default GraphView;

// ─── buildDimmed helper ───────────────────────────────────────────────────────
// Council C2: converts App.tsx Filters into the ViewState dimmed sets.
// Filters contain sets of ACTIVE (visible) items; dimmed = the complement.
//
// Mapping:
//   filters.tiers     → dimmed.tier  = tiers NOT in filters.tiers
//   filters.spaces    → dimmed.space = spaces NOT in filters.spaces
//                       (empty filters.spaces = all spaces shown = no dim)
//   filters.edgeTypes → dimmed.edge  = edge types NOT in filters.edgeTypes
//   filters.types     → dimmed.type  = node types NOT in filters.types
//                       (parity: the FilterDrawer node-type control must still
//                       hide nodes; the reducer dims by node `type` attribute).
function buildDimmed(
  filters: Filters,
  graph: Graph,
): ViewState["dimmed"] {
  // tiers: dim tiers not in the active set
  // Derive the dim sets from the canonical enum lists in types.ts (NOT inline
  // literals) so a new NodeType/EdgeType can't silently escape type/edge dimming.
  const dimmedTier = new Set(ALL_TIERS.filter((t) => !filters.tiers.has(t)));

  // spaces: dim spaces not in the active set (if the active set is non-empty)
  const dimmedSpace = new Set<string>();
  if (filters.spaces.size > 0) {
    graph.forEachNode((_id, attr) => {
      const space = (attr.space as string) ?? "";
      if (!filters.spaces.has(space)) {
        dimmedSpace.add(space);
      }
    });
  }

  // node types: dim types not in the active set (complement, mirrors tiers).
  const dimmedType = new Set<string>(ALL_NODE_TYPES.filter((t) => !filters.types.has(t)));

  // edgeTypes: dim edge types not in the active set
  const dimmedEdge = new Set<string>(ALL_EDGE_TYPES.filter((et) => !filters.edgeTypes.has(et)));

  return {
    space: dimmedSpace,
    tier: dimmedTier,
    role: new Set(), // role (selfRole) has no filter dimension in App.tsx Filters
    type: dimmedType,
    edge: dimmedEdge,
  };
}
