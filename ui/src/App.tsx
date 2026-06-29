import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchGraph, fetchNodeDetail } from "./api";
import type { Edge, GraphData, MemoryNode, NodeDetail, Tier, NodeType, EdgeType, ViewScope } from "./types";
import { ALL_TIERS, ALL_NODE_TYPES, ALL_EDGE_TYPES } from "./types";
import { createRequestGuard } from "./graph/requestGuard";
import GraphView from "./components/GraphView";
import TopBar from "./components/TopBar";
import NodeDetailPanel from "./components/NodeDetail";
import FilterDrawer from "./components/FilterDrawer";
import InsightsPanel from "./components/InsightsPanel";
import AdminPanel from "./components/AdminPanel";
import AgentsPanel from "./components/AgentsPanel";
import ToastContainer from "./components/Toast";
import type { ToastData } from "./components/Toast";
import {
  DEFAULT_GRAPH_APPEARANCE,
  applyGraphAppearance,
  loadGraphAppearance,
  saveGraphAppearance,
  type GraphAppearance,
  type GraphTheme,
} from "./graphAppearance";
import useKeyboardShortcuts from "./hooks/useKeyboardShortcuts";

export interface Filters {
  tiers: Set<Tier>;
  types: Set<NodeType>;
  spaces: Set<string>;
  edgeTypes: Set<EdgeType>;
  clusterBySpace: boolean;
}

// Canonical enum lists live in types.ts (single source of truth shared with
// GraphView's buildDimmed). ALL_TYPES kept as a local alias for readability.
const ALL_TYPES = ALL_NODE_TYPES;
const DEFAULT_EDGE_TYPES = new Set<EdgeType>(ALL_EDGE_TYPES);

type PanelId = "settings" | "insights" | "admin" | "agents" | null;
type ThemeTransitionState = {
  theme: GraphTheme;
  id: number;
};

const THEME_SWAP_DELAY_MS = 260;
const THEME_TRANSITION_TOTAL_MS = 820;

export default function App() {
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<NodeDetail | null>(null);
  const [activePanel, setActivePanel] = useState<PanelId>(null);
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null);
  const [themeTransition, setThemeTransition] = useState<ThemeTransitionState | null>(null);
  const [filters, setFilters] = useState<Filters>({
    tiers: new Set(ALL_TIERS),
    types: new Set(ALL_TYPES),
    spaces: new Set<string>(),
    edgeTypes: new Set(DEFAULT_EDGE_TYPES),
    clusterBySpace: true,
  });
  const [allSpaces, setAllSpaces] = useState<string[]>([]);
  const [userNodeId, setUserNodeId] = useState<string | null>(null);
  const [viewScope, setViewScope] = useState<ViewScope>({ kind: "active" });
  const [hasNoSpace, setHasNoSpace] = useState(false);
  const reqGuard = useRef(createRequestGuard());
  const [toasts, setToasts] = useState<ToastData[]>([]);
  const [graphAppearance, setGraphAppearance] =
    useState<GraphAppearance>(loadGraphAppearance);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const themeTransitionFrameRef = useRef<number | null>(null);
  const themeTransitionTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const graphViewRef = useRef<{
    focusNode: (id: string) => void;
    highlightNode: (id: string) => void;
    highlightNodes: (ids: string[]) => void;
    clearHighlight: () => void;
  }>(null);

  const addToast = useCallback((message: string, type: ToastData["type"] = "info") => {
    const id = Date.now();
    setToasts(t => [...t, { id, message, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3000);
  }, []);

  const togglePanel = useCallback((id: PanelId) => {
    setActivePanel((p) => (p === id ? null : id));
  }, []);

  useKeyboardShortcuts({
    onTogglePanel: togglePanel as (id: "settings" | "insights" | "admin" | "agents") => void,
    onClosePanel: useCallback(() => setActivePanel(null), []),
    onCloseDetail: useCallback(() => setSelectedDetail(null), []),
    onFocusSearch: useCallback(() => searchInputRef.current?.focus(), []),
    activePanel: activePanel as "settings" | "insights" | "admin" | "agents" | null,
    hasDetail: selectedDetail !== null,
  });

  const loadGraph = useCallback((space?: string) => {
    const token = reqGuard.current.begin();
    fetchGraph(space === undefined ? undefined : { space })
      .then((data) => {
        if (!reqGuard.current.isLatest(token)) return; // drop stale response
        setGraph(data);
        setUserNodeId(data.user_node_id);
        setHasNoSpace(data.has_no_space ?? false);
        setViewScope(space === undefined ? { kind: "active" } : { kind: "space", space });
        if (space === undefined) {
          const spaceList = data.all_spaces ?? [];
          setAllSpaces(spaceList);
          // C1: include "" so no-space nodes are not space-dimmed in the overview.
          setFilters((f) => ({ ...f, spaces: new Set([...spaceList, ""]) }));
        }
      })
      .catch(() => {
        if (!reqGuard.current.isLatest(token)) return;
        addToast("Falha ao carregar o grafo", "error"); // keep current view on error
      });
  }, [addToast]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  useEffect(() => {
    applyGraphAppearance(graphAppearance);
    saveGraphAppearance(graphAppearance);
  }, [graphAppearance]);

  const handleNodeSelect = useCallback(async (nodeId: string) => {
    const detail = await fetchNodeDetail(nodeId);
    setSelectedDetail(detail);
  }, []);

  const handleSearchSelect = useCallback(
    (nodeId: string) => {
      setFocusNodeId(nodeId);
      graphViewRef.current?.focusNode(nodeId);
      handleNodeSelect(nodeId);
    },
    [handleNodeSelect]
  );

  const handleConnectionClick = useCallback(
    (nodeId: string) => {
      setFocusNodeId(nodeId);
      graphViewRef.current?.focusNode(nodeId);
      handleNodeSelect(nodeId);
    },
    [handleNodeSelect]
  );

  const filteredNodes = useMemo(() => {
    if (!graph) return [];
    return graph.nodes.filter(
      (n) =>
        filters.tiers.has(n.tier) &&
        filters.types.has(n.type) &&
        (filters.spaces.size === 0 ||
          !n.space ||
          filters.spaces.has(n.space))
    );
  }, [graph, filters]);

  const filteredEdges = useMemo(() => {
    if (!graph) return [];
    return graph.edges.filter((e) => filters.edgeTypes.has(e.edge_type));
  }, [graph, filters.edgeTypes]);

  const toggleFilter = useCallback(
    <K extends keyof Filters>(key: K, value: string) => {
      setFilters((f) => {
        const next = new Set(f[key] as Set<string>);
        if (next.has(value)) next.delete(value);
        else next.add(value);
        return { ...f, [key]: next };
      });
    },
    []
  );

  const clearThemeTransition = useCallback(() => {
    if (themeTransitionFrameRef.current !== null) {
      cancelAnimationFrame(themeTransitionFrameRef.current);
      themeTransitionFrameRef.current = null;
    }
    for (const timer of themeTransitionTimersRef.current) {
      clearTimeout(timer);
    }
    themeTransitionTimersRef.current = [];
    document.documentElement.removeAttribute("data-theme-transitioning");
  }, []);

  useEffect(() => {
    return clearThemeTransition;
  }, [clearThemeTransition]);

  const applyAppearanceWithTransition = useCallback((nextAppearance: GraphAppearance) => {
    const themeChanged = graphAppearance.theme !== nextAppearance.theme;
    const reduceMotion =
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    clearThemeTransition();

    if (!themeChanged || reduceMotion) {
      setThemeTransition(null);
      setGraphAppearance(nextAppearance);
      return;
    }

    setThemeTransition(null);
    document.documentElement.setAttribute("data-theme-transitioning", "true");
    themeTransitionFrameRef.current = requestAnimationFrame(() => {
      themeTransitionFrameRef.current = null;
      setThemeTransition({ theme: nextAppearance.theme, id: Date.now() });
      themeTransitionTimersRef.current = [
        setTimeout(() => {
          setGraphAppearance(nextAppearance);
        }, THEME_SWAP_DELAY_MS),
        setTimeout(() => {
          document.documentElement.removeAttribute("data-theme-transitioning");
          themeTransitionTimersRef.current = [];
          setThemeTransition(null);
        }, THEME_TRANSITION_TOTAL_MS),
      ];
    });
  }, [clearThemeTransition, graphAppearance.theme]);

  const handleThemeChange = useCallback((theme: GraphTheme) => {
    if (graphAppearance.theme === theme) return;
    applyAppearanceWithTransition({ ...graphAppearance, theme });
  }, [applyAppearanceWithTransition, graphAppearance]);

  const resetGraphAppearance = useCallback(() => {
    applyAppearanceWithTransition(DEFAULT_GRAPH_APPEARANCE);
  }, [applyAppearanceWithTransition]);

  const handleTierColorChange = useCallback((tier: Tier, color: string) => {
    setGraphAppearance((appearance) => ({
      ...appearance,
      colors: { ...appearance.colors, [tier]: color },
    }));
  }, []);

  if (!graph) {
    return <div className="loading">ormahing...</div>;
  }

  return (
    <>
      <TopBar
        nodeCount={filteredNodes.length}
        activePanel={activePanel as "settings" | "insights" | "admin" | "agents" | null}
        onTogglePanel={togglePanel as (id: "settings" | "insights" | "admin" | "agents") => void}
        onSearchSelect={handleSearchSelect}
        onSearchHover={(id) => graphViewRef.current?.highlightNode(id)}
        onSearchHoverEnd={() => graphViewRef.current?.clearHighlight()}
        searchInputRef={searchInputRef}
      />
      <div className="graph-container">
        {graph && (
          // Council C2: pass full graph.nodes/graph.edges + filters prop so filter
          // toggles cost a reducer refresh(), not a graph rebuild + camera reset.
          // filteredNodes is kept above only for the TopBar count badge.
          <GraphView
            ref={graphViewRef}
            nodes={graph.nodes}
            edges={graph.edges}
            onNodeSelect={handleNodeSelect}
            focusNodeId={focusNodeId}
            userNodeId={userNodeId}
            clusterBySpace={filters.clusterBySpace}
            appearance={graphAppearance}
            filters={filters}
            viewScope={viewScope}
            allSpaces={allSpaces}
            hasNoSpace={hasNoSpace}
            onDrillSpace={(s) => loadGraph(s)}
            onExitDrill={() => loadGraph()}
          />
        )}
      </div>
      <NodeDetailPanel
        detail={selectedDetail}
        onClose={() => setSelectedDetail(null)}
        onConnectionClick={handleConnectionClick}
      />
      <FilterDrawer
        open={activePanel === "settings"}
        onClose={() => setActivePanel(null)}
        filters={filters}
        allSpaces={allSpaces}
        nodes={graph.nodes}
        edges={graph.edges}
        onToggle={toggleFilter}
        appearance={graphAppearance}
        onThemeChange={handleThemeChange}
        onTierColorChange={handleTierColorChange}
        onResetAppearance={resetGraphAppearance}
      />
      <InsightsPanel
        open={activePanel === "insights"}
        onClose={() => setActivePanel(null)}
        onNodeClick={handleSearchSelect}
        onPairHover={(ids) => graphViewRef.current?.highlightNodes(ids)}
        onPairHoverEnd={() => graphViewRef.current?.clearHighlight()}
      />
      <AdminPanel
        open={activePanel === "admin"}
        onClose={() => setActivePanel(null)}
        onToast={addToast}
      />
      <AgentsPanel
        open={activePanel === "agents"}
        onClose={() => setActivePanel(null)}
      />
      {themeTransition && (
        <div
          key={themeTransition.id}
          className={`theme-transition theme-transition-${themeTransition.theme}`}
          aria-hidden="true"
        />
      )}
      <ToastContainer toasts={toasts} />
    </>
  );
}
