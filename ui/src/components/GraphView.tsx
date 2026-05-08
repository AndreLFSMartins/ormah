import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
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
        width: 1,
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
      selector: "node.glow",
      style: {
        "border-color": tokens.accent,
        "border-width": 3,
        color: tokens.labelGlow,
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
  // Large radius so clusters start far apart
  const clusterRadius = Math.max(600, totalGroups * 200);
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

      const nodeElements = nodes.map((n) => {
        const themeTokens = GRAPH_THEME_TOKENS[appearance.theme];
        const sr = selfRole(n.id);
        const size = displayNodeSize(n.access_count, sr);
        return {
          data: {
            id: n.id,
            labelText: nodeLabel(n),
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
        .map((e) => ({
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
        }));

      // Pre-compute clustered positions if needed
      const positions = clusterBySpace
        ? computeClusteredPositions(nodes)
        : null;

      const cy = cytoscape({
        container: containerRef.current,
        elements: [...nodeElements, ...edgeElements],
        style: buildStyles(appearance),
        layout: { name: "preset" },
        minZoom: 0.15,
        maxZoom: 4,
        wheelSensitivity: 0.3,
      });

      // Apply pre-computed positions
      if (positions) {
        cy.nodes().forEach((node) => {
          const pos = positions.get(node.id());
          if (pos) node.position(pos);
        });
      }

      cy.nodes().grabify();

      const layout = cy.layout({
        name: "cola",
        animate: true,
        infinite: false,
        maxSimulationTime: 3000,
        fit: false,
        ungrabifyWhileSimulating: false,
        nodeSpacing: clusterBySpace ? 60 : 40,
        edgeLength: (edge: cytoscape.EdgeSingular) => {
          const w = edge.data("weight") ?? 0.5;
          const baseLen = 120 + (1 - w) * 100;
          if (clusterBySpace) {
            const srcSpace = nodeSpaceMap.get(edge.source().id());
            const tgtSpace = nodeSpaceMap.get(edge.target().id());
            // Cross-cluster edges: very long ideal length pushes clusters apart
            if (srcSpace !== tgtSpace) return baseLen * 5;
          }
          return baseLen;
        },
        convergenceThreshold: 0.01,
        randomize: !positions,
        avoidOverlap: true,
        handleDisconnected: true,
      } as never);
      layout.run();
      layoutRef.current = layout;

      layout.on("layoutstop", () => {
        cy.fit(undefined, 40);
        setLayoutReady(true);
      });

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
      cy.nodes().forEach((node) => {
        const tier = node.data("tier") as string;
        const selfRole = node.data("selfRole") as string;
        const accessCount = node.data("accessCount") as number;
        node.data("bgColor", tierColor(tier, selfRole, appearance));
        node.data("borderColor", tierBorderColor(tier, selfRole, appearance));
        node.data("labelColor", themeTokens.label);
        node.data("labelOutlineColor", themeTokens.background);
        node.data("nodeSize", displayNodeSize(accessCount, selfRole));
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
      </div>
    );
  }
);

GraphView.displayName = "GraphView";
export default GraphView;
