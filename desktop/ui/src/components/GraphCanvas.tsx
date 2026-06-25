"use client";
import { useEffect, useRef, useCallback } from "react";
import { createGraphState, reconcile, setNodeOpacity } from "@/engine/graph";
import { stepPhysics } from "@/engine/physics";
import { render } from "@/engine/renderer";
import { hitTest, startDrag, updateDrag, endDrag } from "@/engine/interaction";
import { getScenarioFrame, getAct4Overrides } from "@/engine/scenario";
import { ACTS_VH, vhToPx, TOTAL_STORY_VH } from "@/lib/constants";
import type { GraphState } from "@/engine/types";

interface Props {
  progressRef: React.RefObject<number>;
  selfNodeReadyRef: React.RefObject<{ x: number; y: number } | null>;
  storyComplete?: boolean;
}

export default function GraphCanvas({ progressRef, selfNodeReadyRef, storyComplete = false }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef<GraphState | null>(null);
  const isMobileRef = useRef(false);

  const getMousePos = useCallback(
    (e: MouseEvent | Touch, canvas: HTMLCanvasElement) => {
      const rect = canvas.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    },
    [],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const isMobile = window.innerWidth < 768;
    isMobileRef.current = isMobile;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    function resize() {
      if (!canvas) return;
      const w = window.innerWidth;
      const h = window.innerHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      if (stateRef.current) {
        stateRef.current.width = w;
        stateRef.current.height = h;
      }
    }

    const state = createGraphState(window.innerWidth, window.innerHeight);
    stateRef.current = state;
    resize();

    let lastTime = performance.now();
    let rafId: number;

    const act5StartVh = ACTS_VH.act5.startVh;
    const act4EndVh = ACTS_VH.act4.endVh;
    const totalStoryPx = () => vhToPx(TOTAL_STORY_VH);

    function loop(now: number) {
      const dt = now - lastTime;
      lastTime = now;
      state.time = now;

      const scrollY = progressRef.current ?? 0;
      const storyEnd = totalStoryPx();

      // Fade out canvas after story ends
      const fadeStart = storyEnd;
      const fadeEnd = storyEnd + window.innerHeight * 0.5;
      let canvasOpacity = 1;
      if (scrollY > fadeStart) {
        canvasOpacity = Math.max(0, 1 - (scrollY - fadeStart) / (fadeEnd - fadeStart));
      }
      if (canvas) {
        canvas.style.opacity = String(canvasOpacity);
      }

      const frame = getScenarioFrame(scrollY, isMobileRef.current);
      reconcile(state, frame.nodes, frame.edges);

      // Act 4 opacity overrides
      const overrides = getAct4Overrides(scrollY);
      for (const [id, opacity] of overrides) {
        setNodeOpacity(state, id, opacity);
      }

      // Self node birth: invisible until the DOM dot hands off coordinates.
      // On the first frame the ref is set, teleport the canvas node to the
      // dot's position, stamp birthTime (for growth animation in renderer),
      // and make it immediately visible. Physics will drift it to center.
      // Exception: return visitors (scrollY already past Act 1) skip the
      // birth animation entirely — the node appears at center immediately.
      const selfNode = state.nodes.get("self");
      if (selfNode) {
        const pastAct1 = scrollY > vhToPx(ACTS_VH.act2.startVh);
        if (pastAct1 && selfNode.birthTime == null) {
          // Return visitor — show at center immediately, no birth animation
          selfNode.opacity = 1;
          selfNode.targetOpacity = 1;
          selfNode.birthTime = now - 10000; // well past growth (4s) + S-curve (4.2s) durations
        } else if (!selfNodeReadyRef.current) {
          // Dot hasn't handed off yet — keep invisible
          selfNode.targetOpacity = 0;
          selfNode.opacity = 0;
        } else if (selfNode.birthTime == null) {
          // First frame after handoff — teleport and birth
          selfNode.x = selfNodeReadyRef.current.x;
          selfNode.y = selfNodeReadyRef.current.y;
          selfNode.vx = 0;
          selfNode.vy = 0;
          selfNode.opacity = 1;
          selfNode.targetOpacity = 1;
          selfNode.birthTime = now;
        }
      }

      // Act 5: enable interaction
      const act5Threshold = vhToPx(act5StartVh + (ACTS_VH.act5.endVh - act5StartVh) * 0.88);
      state.interactive = scrollY > act5Threshold;

      // Act 5: graph background opacity
      const act5FadeStart = vhToPx(act4EndVh);
      const act5FadeEnd = vhToPx(act5StartVh + (ACTS_VH.act5.endVh - act5StartVh) * 0.88);
      if (scrollY > act5FadeStart && scrollY < act5FadeEnd) {
        const t = (scrollY - act5FadeStart) / (act5FadeEnd - act5FadeStart);
        for (const node of state.nodes.values()) {
          if (!overrides.has(node.id)) {
            node.targetOpacity = Math.max(0.4, 1 - t * 0.6);
          }
        }
      } else if (scrollY >= act5FadeEnd) {
        for (const node of state.nodes.values()) {
          if (!overrides.has(node.id)) {
            node.targetOpacity = 1;
          }
        }
      }

      // Act 5: shift graph gravity to the left so text can sit on the right
      const act5Start = vhToPx(ACTS_VH.act5.startVh);
      const act5TransEnd = act5Start + vhToPx(15); // transition over 15vh of scroll
      if (scrollY >= act5Start && scrollY <= storyEnd) {
        const t = Math.min(1, (scrollY - act5Start) / (act5TransEnd - act5Start));
        const eased = 1 - (1 - t) * (1 - t); // ease-out quad
        state.gravityCenterX = state.width / 2 - eased * state.width * 0.22; // shift left ~22%
      } else {
        state.gravityCenterX = null;
      }

      stepPhysics(state, dt);

      // S-curve guided path: ball dips down as ormah lifts away, then floats
      // to center. Fixed viewport-relative control points avoid instability
      // when spawn is close to center. Ease-in-out sine is the smoothest
      // interpolation (zero velocity at both ends, no sudden changes).
      const pathNode = state.nodes.get("self");
      const birthSpawn = selfNodeReadyRef.current;
      if (pathNode?.birthTime != null && birthSpawn) {
        const pathAge = now - pathNode.birthTime;
        const pathDuration = 4200;
        if (pathAge < pathDuration) {
          const rawT = pathAge / pathDuration;
          // Ease-in-out sine: smoothest possible, derivative is 0 at both ends
          const t = -(Math.cos(Math.PI * rawT) - 1) / 2;

          const sx = birthSpawn.x;
          const sy = birthSpawn.y;
          const ex = state.width / 2;
          const ey = state.height / 2;
          const h = state.height;
          const w = state.width;

          // P1: briefly follows ormah's departure direction (up-left) —
          // the ball carries a little of ormah's momentum as it lifts away.
          // Ormah heads toward ~(3%, 2.5%) from (50%, 50%), direction ≈ (-0.71, -0.70).
          const carry = Math.min(w, h) * 0.08;
          const p1x = sx - carry * 0.71;
          const p1y = sy - carry * 0.70;

          // P2: sweeps through below-right of center — the return arc of the S.
          const p2x = ex + w * 0.05;
          const p2y = ey + h * 0.07;

          const inv = 1 - t;
          pathNode.x = inv*inv*inv*sx + 3*inv*inv*t*p1x + 3*inv*t*t*p2x + t*t*t*ex;
          pathNode.y = inv*inv*inv*sy + 3*inv*inv*t*p1y + 3*inv*t*t*p2y + t*t*t*ey;
          pathNode.vx = 0;
          pathNode.vy = 0;
        }
      }

      render(ctx!, state, dpr);

      rafId = requestAnimationFrame(loop);
    }

    rafId = requestAnimationFrame(loop);
    window.addEventListener("resize", resize);

    // Mouse interaction — SELF node is always draggable, others only when interactive
    function onMouseMove(e: MouseEvent) {
      const pos = getMousePos(e, canvas!);
      if (state.draggedNodeId) {
        updateDrag(state, pos.x, pos.y);
        return;
      }
      const hit = hitTest(state, pos.x, pos.y);
      // Allow hovering SELF node always, others only when fully interactive
      if (hit === "self" || (hit && state.interactive)) {
        state.hoveredNodeId = hit;
        canvas!.style.cursor = "grab";
      } else {
        state.hoveredNodeId = null;
        canvas!.style.cursor = "default";
      }
    }

    function onMouseDown(e: MouseEvent) {
      if (isMobileRef.current) return;
      const pos = getMousePos(e, canvas!);
      const hit = hitTest(state, pos.x, pos.y);
      // SELF node is always draggable, others only when interactive
      if (hit === "self" || (hit && state.interactive)) {
        startDrag(state, hit);
        canvas!.style.cursor = "grabbing";
      }
    }

    function onMouseUp() {
      endDrag(state);
      canvas!.style.cursor = "default";
    }

    // Touch: SELF node draggable, others tap-to-highlight
    let touchDragging = false;
    function onTouchStart(e: TouchEvent) {
      if (!e.touches[0]) return;
      const pos = getMousePos(e.touches[0], canvas!);
      const hit = hitTest(state, pos.x, pos.y);
      if (hit === "self") {
        startDrag(state, hit);
        touchDragging = true;
      } else if (hit && state.interactive) {
        state.hoveredNodeId = hit;
      }
    }

    function onTouchMove(e: TouchEvent) {
      if (!touchDragging || !e.touches[0]) return;
      const pos = getMousePos(e.touches[0], canvas!);
      updateDrag(state, pos.x, pos.y);
    }

    function onTouchEnd() {
      if (touchDragging) {
        endDrag(state);
        touchDragging = false;
      } else {
        setTimeout(() => {
          state.hoveredNodeId = null;
        }, 2000);
      }
    }

    canvas.addEventListener("mousemove", onMouseMove);
    canvas.addEventListener("mousedown", onMouseDown);
    window.addEventListener("mouseup", onMouseUp);
    canvas.addEventListener("touchstart", onTouchStart, { passive: true });
    canvas.addEventListener("touchmove", onTouchMove, { passive: true });
    canvas.addEventListener("touchend", onTouchEnd);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", resize);
      canvas.removeEventListener("mousemove", onMouseMove);
      canvas.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("mouseup", onMouseUp);
      canvas.removeEventListener("touchstart", onTouchStart);
      canvas.removeEventListener("touchmove", onTouchMove);
      canvas.removeEventListener("touchend", onTouchEnd);
    };
  }, [progressRef, selfNodeReadyRef, getMousePos]);

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 z-0 h-screen w-full"
      style={{ background: "#0a0a0a", pointerEvents: storyComplete ? "none" : "auto" }}
    />
  );
}
