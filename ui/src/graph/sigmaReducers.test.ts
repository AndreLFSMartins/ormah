import { describe, it, expect } from "vitest";
import { makeNodeReducer, makeEdgeReducer, type ViewState } from "./sigmaReducers";

const DIM = "#2a2a2a";

function state(over: Partial<ViewState>): ViewState {
  return {
    hoveredNode: null,
    neighbors: new Set<string>(),
    highlightSet: new Set<string>(),
    glowOnly: new Set<string>(),
    focusKind: null,
    dimmed: { space: new Set(), tier: new Set(), role: new Set(), type: new Set(), edge: new Set() },
    attrsById: new Map(),
    edgeTypeById: new Map(),
    dimColor: DIM,
    ...over,
  };
}

describe("makeNodeReducer", () => {
  it("passes attributes through when nothing is active", () => {
    const r = makeNodeReducer(state({}));
    const out = r("a", { color: "#abc", label: "A" });
    expect(out.color).toBe("#abc");
    expect(out.label).toBeUndefined(); // labels hidden when nothing is hovered
  });

  it("dims non-hovered, non-neighbor nodes and highlights the hovered one", () => {
    const r = makeNodeReducer(state({ hoveredNode: "a", neighbors: new Set(["b"]) }));
    expect(r("a", { color: "#abc" }).highlighted).toBe(true);
    expect(r("b", { color: "#abc" }).color).toBe("#abc"); // neighbor stays vivid
    const other = r("c", { color: "#abc" });
    expect(other.color).toBe(DIM);
    expect(other.label).toBeUndefined(); // dimmed nodes drop their label
  });

  it("keeps every highlightSet member vivid and dims the rest (multi-highlight)", () => {
    const r = makeNodeReducer(state({ highlightSet: new Set(["a", "b"]) }));
    expect(r("a", { color: "#abc" }).color).toBe("#abc");
    expect(r("b", { color: "#abc" }).color).toBe("#abc");
    expect(r("c", { color: "#abc" }).color).toBe(DIM);
  });

  it("glowOnly highlights the member and dims NOBODY (Council A4, search-hover)", () => {
    const r = makeNodeReducer(state({ glowOnly: new Set(["a"]) }));
    expect(r("a", { color: "#abc" }).highlighted).toBe(true);
    const other = r("b", { color: "#abc" });
    expect(other.color).toBe("#abc");        // NOT dimmed
    expect(other.label).toBeUndefined();     // (no label set in input; just confirm color preserved)
  });

  it("legend focus keeps matching nodes vivid and dims non-matching (Council A1)", () => {
    const attrs = new Map([
      ["a", { space: "work", tier: "core", selfRole: "", type: "fact" }],
      ["b", { space: "home", tier: "working", selfRole: "", type: "fact" }],
    ]);
    const r = makeNodeReducer(state({ attrsById: attrs, focusKind: { kind: "space", val: "work" } }));
    expect(r("a", { color: "#abc" }).highlighted).toBe(true);
    expect(r("b", { color: "#abc" }).color).toBe(DIM);
  });

  it("dims a node when its space, tier, or role is toggled off", () => {
    const attrs = new Map([
      ["a", { space: "work", tier: "core", selfRole: "", type: "fact" }],
      ["b", { space: "home", tier: "working", selfRole: "identity", type: "person" }],
    ]);
    expect(makeNodeReducer(state({ attrsById: attrs, dimmed: { space: new Set(["work"]), tier: new Set(), role: new Set(), type: new Set(), edge: new Set() } }))("a", { color: "#abc" }).color).toBe(DIM);
    expect(makeNodeReducer(state({ attrsById: attrs, dimmed: { space: new Set(), tier: new Set(["working"]), role: new Set(), type: new Set(), edge: new Set() } }))("b", { color: "#abc" }).color).toBe(DIM);
    expect(makeNodeReducer(state({ attrsById: attrs, dimmed: { space: new Set(), tier: new Set(), role: new Set(["identity"]), type: new Set(), edge: new Set() } }))("b", { color: "#abc" }).color).toBe(DIM);
  });

  it("dims a node when its node type is toggled off (Council C2 — FilterDrawer type filter)", () => {
    const attrs = new Map([["a", { space: "", tier: "working", selfRole: "", type: "person" }]]);
    const r = makeNodeReducer(state({ attrsById: attrs, dimmed: { space: new Set(), tier: new Set(), role: new Set(), type: new Set(["person"]), edge: new Set() } }));
    expect(r("a", { color: "#abc" }).color).toBe(DIM);
  });

  it("hovered node does NOT force native label (HTML tooltip covers hover; all nodes label=undefined)", () => {
    const r = makeNodeReducer(state({ hoveredNode: "a" }));
    const hovered = r("a", { label: "A", color: "#abc" });
    expect(hovered.label).toBeUndefined();        // no native label — HTML tooltip handles it
    expect(hovered.forceLabel).toBeUndefined();   // forceLabel must not be set

    const notHovered = r("b", { label: "B", color: "#abc" });
    expect(notHovered.label).toBeUndefined();
    expect(notHovered.forceLabel).toBeUndefined();
  });

  it("hides all labels when nothing is hovered", () => {
    const r = makeNodeReducer(state({ hoveredNode: null }));
    const node1 = r("a", { label: "A", color: "#abc" });
    expect(node1.label).toBeUndefined();

    const node2 = r("b", { label: "B", color: "#abc" });
    expect(node2.label).toBeUndefined();
  });

  it("hovered node has no native label and neighbor also has none (HTML tooltip handles hover display)", () => {
    const r = makeNodeReducer(state({ hoveredNode: "a", neighbors: new Set(["b"]) }));
    const hovered = r("a", { label: "A", color: "#abc" });
    expect(hovered.label).toBeUndefined();        // no native label on hovered node
    expect(hovered.forceLabel).toBeUndefined();   // forceLabel must not be set

    const neighbor = r("b", { label: "B", color: "#abc" });
    expect(neighbor.label).toBeUndefined();
  });
});

describe("makeEdgeReducer", () => {
  it("dims an edge when its type is toggled off", () => {
    const st = state({ edgeTypeById: new Map([["e1", "supports"]]) });
    st.dimmed.edge.add("supports");
    const r = makeEdgeReducer(st, () => ["a", "b"]);
    expect(r("e1", { color: "#0f0" }).color).toBe(DIM);
  });
});
