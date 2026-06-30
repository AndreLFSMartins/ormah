"""Drag test: dragging a node moves it; releasing re-heats FA2 so the graph keeps settling.

Run `make dev` first. Then: uv run --with playwright python ui/playwright/test_graph_drag.py
"""
import sys
from playwright.sync_api import sync_playwright

URL = "http://localhost:5173"


def first_node_screen_pos(page):
    # graphToViewport returns coords relative to sigma's canvas; the canvas is
    # offset within the page (a TopBar sits above it), so add the container's
    # bounding-rect origin to land the mouse exactly on the node.
    return page.evaluate(
        """() => {
          const g = window.__ormahGraph;
          const s = window.__ormahSigma;          // exposed alongside the graph (DEV only)
          if (!g || !s) return null;
          const id = g.nodes()[0];
          // Use the RAW graph attributes (not getNodeDisplayData, which returns
          // sigma's internally rescaled/framed coords) — graphToViewport expects
          // graph coordinates, so framed coords land the mouse off the node.
          const p = s.graphToViewport({ x: g.getNodeAttribute(id, "x"), y: g.getNodeAttribute(id, "y") });
          const r = s.getContainer().getBoundingClientRect();
          return { id, x: r.x + p.x, y: r.y + p.y };
        }"""
    )


def graph_pos(page, node_id):
    return page.evaluate(
        "(id) => { const g = window.__ormahGraph; return { x: g.getNodeAttribute(id,'x'), y: g.getNodeAttribute(id,'y') }; }",
        node_id,
    )


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_selector("canvas", timeout=30000)
        # Slice B: drag-reheat only happens on the global-FA2 path; cluster mode is
        # static. Force cluster off (DEV hook from App.tsx) so this asserts the worker.
        page.evaluate("window.__ormahSetClusterBySpace && window.__ormahSetClusterBySpace(false)")
        page.wait_for_timeout(6000)

        start = first_node_screen_pos(page)
        if not start:
            print("FAIL: no graph/sigma handle (run the DEV server)"); browser.close(); return 1
        before = graph_pos(page, start["id"])

        page.mouse.move(start["x"], start["y"])
        page.mouse.down()
        page.mouse.move(start["x"] + 180, start["y"] + 120, steps=10)
        page.mouse.up()
        page.wait_for_timeout(500)
        after_release = graph_pos(page, start["id"])
        page.wait_for_timeout(2500)          # reheat settle window
        settled = graph_pos(page, start["id"])
        browser.close()

    moved = abs(after_release["x"] - before["x"]) + abs(after_release["y"] - before["y"])
    if moved < 1.0:
        print(f"FAIL: node did not move under drag (delta={moved:.2f})"); return 1
    # Council A6: re-heat means the sim resumes after release, so positions keep
    # changing. If the post-settle position is identical to the immediate
    # post-release position, reheat did NOT fire - that is a FAILURE, not a warning.
    reheated = abs(settled["x"] - after_release["x"]) + abs(settled["y"] - after_release["y"])
    print(f"moved={moved:.1f} reheated_delta={reheated:.3f}")
    if reheated <= 0.001:
        print("FAIL: layout did not re-heat after release (reheat() did not resume the sim)")
        return 1
    print("PASS: node dragged and layout re-heated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
