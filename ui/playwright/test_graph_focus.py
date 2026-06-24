"""Manual real-sigma smoke check: focusing a space frames it (no blank canvas).

NOT a CI gate (depends on the live dev server + the user's live graph). The
deterministic gate is ui/src/components/fit.test.ts. Oracle: the focused space's
node bounding box lands inside the viewport (with tolerance). Also exercises the
zoom-OUT path by zooming in first and asserting the camera ratio actually dropped.

Start the dev server first: `make dev` (backend :8787 + Vite :5173, DEV → __ormahSigma).
"""
import os
import pytest
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ORMAH_UI_URL", "http://localhost:5173")
TARGET_SPACE = os.environ.get("ORMAH_FOCUS_SPACE", "council")
TOL = 0.05        # 5% of viewport tolerance for bbox containment
ZOOM_DELTA = 0.6  # require a 40% ratio change to consider zoom direction proven


def _space_bbox_in_viewport(page, space: str):
    # Returns {inside: bool, frac: float, count: int} for the target space after focus.
    return page.evaluate(
        """([space, tol]) => {
            const sig = window.__ormahSigma;
            if (!sig) return { inside: false, frac: -1, count: -1 };
            const g = sig.getGraph();
            const { width, height } = sig.getDimensions();
            const mx = width * tol, my = height * tol;
            let count = 0, inView = 0;
            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            g.forEachNode((id, attr) => {
                if ((attr.space || '') !== space) return;
                count++;
                const p = sig.framedGraphToViewport(sig.getNodeDisplayData(id));
                minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
                minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
                if (p.x >= 0 && p.x <= width && p.y >= 0 && p.y <= height) inView++;
            });
            if (!count) return { inside: false, frac: -1, count: 0 };
            const inside = minX >= -mx && maxX <= width + mx && minY >= -my && maxY <= height + my;
            return { inside, frac: inView / count, count };
        }""",
        [space, TOL],
    )


def _wait_settled(page):
    page.wait_for_function(
        "() => window.__ormahSigma && window.__ormahSigma.getGraph().order > 0", timeout=20000)
    page.wait_for_timeout(4500)  # FA2 settleMs=4000 + margin
    page.wait_for_function("() => !window.__ormahSigma.getCamera().isAnimated()", timeout=10000)


@pytest.mark.integration
def test_space_focus_frames_the_space():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_selector("canvas", timeout=20000)
        _wait_settled(page)

        # State 1: focus at default zoom (scoped click on the exact legend row).
        page.get_by_test_id(f"legend-space-{TARGET_SPACE}").click()
        page.wait_for_function("() => !window.__ormahSigma.getCamera().isAnimated()", timeout=10000)
        s1 = _space_bbox_in_viewport(page, TARGET_SPACE)
        assert s1["count"] > 0, f"DEV handle missing or space '{TARGET_SPACE}' empty (count={s1['count']})"
        assert s1["inside"], f"[default] '{TARGET_SPACE}' bbox not contained (frac={s1['frac']:.0%})"

        # State 2: zoom IN, PROVE we zoomed in, then refocus and assert it zooms OUT to fit.
        ratio_focused = page.evaluate("() => window.__ormahSigma.getCamera().ratio")
        # factor 3 → ratio/3, a decisive zoom-in well below the ZOOM_DELTA threshold
        # (a default animatedFactor ~1.5 only reaches ~0.67×, not enough to prove direction).
        page.evaluate("() => window.__ormahSigma.getCamera().animatedZoom(3)")
        page.wait_for_function(
            f"() => {{ const c = window.__ormahSigma.getCamera(); return !c.isAnimated() && c.ratio < {ratio_focused} * {ZOOM_DELTA}; }}",
            timeout=10000,
        )
        page.get_by_test_id(f"legend-space-{TARGET_SPACE}").click()  # clear
        page.get_by_test_id(f"legend-space-{TARGET_SPACE}").click()  # focus again
        page.wait_for_function("() => !window.__ormahSigma.getCamera().isAnimated()", timeout=10000)
        s2 = _space_bbox_in_viewport(page, TARGET_SPACE)
        ratio_refocused = page.evaluate("() => window.__ormahSigma.getCamera().ratio")
        browser.close()

        assert s2["inside"], f"[after zoom-in] '{TARGET_SPACE}' bbox not contained (frac={s2['frac']:.0%})"
        assert ratio_refocused > ratio_focused * ZOOM_DELTA, "refocus did not zoom back out to fit the space"
