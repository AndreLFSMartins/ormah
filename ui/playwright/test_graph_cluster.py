"""Cluster layout test: enabling clusterBySpace switches GraphView to the static
cluster path (no FA2 worker) when the largest space is within the size gate.

Runs against the Vite dev server (make ui-dev) — the __ormah* DEV hooks only exist
under import.meta.env.DEV, not in the production build served on :8787.
Run `make ui-dev` first. Then: uv run --with playwright python ui/playwright/test_graph_cluster.py
"""
import sys
from playwright.sync_api import sync_playwright

URL = "http://localhost:5173"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_selector("canvas", timeout=30000)
        # Enable clustering via the DEV hook; the dev store is small, so the gate
        # admits the synchronous cluster path.
        page.evaluate("window.__ormahSetClusterBySpace && window.__ormahSetClusterBySpace(true)")
        page.wait_for_timeout(2000)
        mode = page.evaluate("window.__ormahLayoutMode")
        count = page.evaluate("window.__ormahGraph ? window.__ormahGraph.order : 0")
        browser.close()

    if mode != "cluster":
        print(f"FAIL: expected cluster layout mode, got {mode!r}")
        return 1
    if not count or count < 1:
        print(f"FAIL: graph has no nodes (order={count})")
        return 1
    print(f"PASS: cluster mode active over {count} nodes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
