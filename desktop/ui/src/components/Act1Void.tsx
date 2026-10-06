"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { motion, useAnimationControls } from "framer-motion";
import { vhToPx } from "@/lib/constants";

interface Props {
  progressRef: React.RefObject<number>;
  selfNodeReadyRef: React.MutableRefObject<{ x: number; y: number } | null>;
}

const TITLE_CHARS = "ormah".split("");
const R_INDEX = 1;

export default function Act1Void({ progressRef, selfNodeReadyRef }: Props) {
  const [scroll, setScroll] = useState({ t: 0, titleOpacity: 1 });
  const dotRef = useRef<HTMLSpanElement>(null);
  const dotControls = useAnimationControls();
  const [dotVisible, setDotVisible] = useState(true);

  const compute = useCallback(() => {
    const scrollY = progressRef.current ?? 0;
    const vh = window.innerHeight;
    const transitionEnd = vh * 1.5;
    const t = Math.min(1, Math.max(0, scrollY / transitionEnd));

    // Fade out title as Act5 pitch card appears (avoids two ormah logos)
    const fadeStart = vhToPx(1000);
    const fadeEnd = vhToPx(1120);
    const titleOpacity = scrollY < fadeStart ? 1
      : scrollY > fadeEnd ? 0
      : 1 - (scrollY - fadeStart) / (fadeEnd - fadeStart);

    return { t: 1 - Math.pow(1 - t, 3), titleOpacity };
  }, [progressRef]);

  useEffect(() => {
    let rafId: number;
    function tick() {
      const next = compute();
      setScroll((prev) => {
        if (Math.abs(prev.t - next.t) > 0.002 || Math.abs(prev.titleOpacity - next.titleOpacity) > 0.01) return next;
        return prev;
      });
      rafId = requestAnimationFrame(tick);
    }
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [compute]);

  // Dot appears under "r", holds, then hands off to canvas
  useEffect(() => {
    async function animate() {
      // Wait for "r" to finish its entrance
      const rDelay = 0.3 + R_INDEX * 0.08 + 0.6;
      await new Promise((r) => setTimeout(r, rDelay * 1000));

      // Fade in quickly — must be visible before auto-play starts (~1500ms).
      // rDelay ~980ms + 400ms = ~1380ms, giving 120ms before ormah moves.
      await dotControls.start({
        opacity: 1,
        transition: { duration: 0.4, ease: "easeOut" },
      });

      // Capture position now — ormah is still centered, scroll = 0.
      // Canvas self node spawns here and begins its arc toward center.
      const el = dotRef.current;
      if (el) {
        const rect = el.getBoundingClientRect();
        selfNodeReadyRef.current = {
          x: rect.left + rect.width / 2,
          y: rect.top + rect.height / 2,
        };
      }

      // Dissolve the DOM dot immediately — the canvas node takes over.
      // This fade-out runs as ormah starts lifting away, creating a clean
      // visual handoff: dot dissolves, canvas ball begins its arc.
      await dotControls.start({
        opacity: 0,
        transition: { duration: 1.6, ease: [0.25, 0.46, 0.45, 0.94] },
      });
      setDotVisible(false);
    }

    animate();
  }, [dotControls, selfNodeReadyRef]);

  const t = scroll.t;
  const titleOpacity = scroll.titleOpacity ?? 1;
  const isMobile = typeof window !== "undefined" && window.innerWidth < 640;
  const baseFontSize = isMobile ? 56 : 86;
  const minFontSize = isMobile ? 24 : 32;
  const fontSize = baseFontSize - t * (baseFontSize - minFontSize);
  const dotSize = fontSize * 0.09;

  // Static nav dot: sized proportionally, fades in as title settles
  const navDotSize = fontSize * 0.09;
  const navDotOpacity = Math.min(1, Math.max(0, (t - 0.7) / 0.3));

  return (
    <div className="absolute inset-0">
      <div
        className="fixed z-20 story-text"
        style={{
          top: t === 0 ? "50%" : `${50 - t * 47}%`,
          left: t === 0 ? "50%" : `${50 - t * 47.5}%`,
          transform: t === 0
            ? "translate(-50%, -50%)"
            : `translate(${-50 + t * 50}%, ${-50 + t * 50}%)`,
          opacity: titleOpacity,
          transition: "none",
          willChange: "top, left, transform, opacity",
        }}
      >
        <motion.h1
          className="tracking-tight flex whitespace-nowrap"
          style={{
            fontSize: `${fontSize}px`,
            lineHeight: 1.1,
          }}
          initial="hidden"
          animate="visible"
        >
          {TITLE_CHARS.map((char, i) => (
            <motion.span
              key={i}
              className="inline-block relative"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                duration: 0.6,
                ease: "easeOut",
                delay: 0.3 + i * 0.08,
              }}
            >
              {char}
              {i === R_INDEX && dotVisible && (
                <motion.span
                  ref={dotRef}
                  className="absolute block rounded-full"
                  style={{
                    width: `${dotSize}px`,
                    height: `${dotSize}px`,
                    backgroundColor: "var(--node-self)",
                    left: "25%",
                    bottom: `-${dotSize * 0.25}px`,
                    transform: "translateX(-50%)",
                    boxShadow:
                      "0 0 6px var(--node-self), 0 0 12px rgba(116, 179, 165, 0.2)",
                  }}
                  initial={{ opacity: 0 }}
                  animate={dotControls}
                />
              )}
              {/* Static brand dot — fades in once title reaches top-left */}
              {i === R_INDEX && !dotVisible && (
                <span
                  className="absolute block rounded-full"
                  style={{
                    width: `${navDotSize}px`,
                    height: `${navDotSize}px`,
                    backgroundColor: "var(--node-self)",
                    left: "25%",
                    bottom: `-${navDotSize * 0.25}px`,
                    transform: "translateX(-50%)",
                    boxShadow:
                      "0 0 6px var(--node-self), 0 0 12px rgba(116, 179, 165, 0.2)",
                    opacity: navDotOpacity,
                    transition: "opacity 0.6s ease",
                  }}
                />
              )}
            </motion.span>
          ))}
        </motion.h1>
      </div>
    </div>
  );
}
