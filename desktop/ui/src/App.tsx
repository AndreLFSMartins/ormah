import { useEffect, useRef, useState } from "react";
import GraphCanvas from "@/components/GraphCanvas";
import Act1Void from "@/components/Act1Void";
import InstallPanel from "./InstallPanel";
import { invoke, graphUrl, waitForServer, sleep } from "./lib/bridge";

type Phase = "intro" | "connect";

export default function App() {
  // progress stays at 0 → wordmark centered, the self-node births and arcs to
  // center on its own (time-based, not scroll). This is the real web intro.
  const progressRef = useRef(0);
  const selfNodeReadyRef = useRef<{ x: number; y: number } | null>(null);
  const [phase, setPhase] = useState<Phase>("intro");
  const started = useRef(false);

  async function dissolveToGraph() {
    const url = await graphUrl();
    document.getElementById("root")?.classList.add("dissolve");
    await sleep(720);
    window.location.replace(url);
  }

  useEffect(() => {
    if (started.current) return; // guard StrictMode double-invoke
    started.current = true;

    (async () => {
      const t0 = Date.now();
      let onboarded = false;
      try { onboarded = await invoke<boolean>("is_onboarded"); } catch { /* ignore */ }

      const ready = await waitForServer();
      if (!ready) return;

      if (onboarded) {
        // Return visit: let the orb balloon up, then fade into the graph.
        await sleep(Math.max(0, 2200 - (Date.now() - t0)));
        dissolveToGraph();
        return;
      }

      // First run: let the full intro breathe (birth ~4s + arc ~4.2s), then connect.
      await sleep(Math.max(0, 5200 - (Date.now() - t0)));
      setPhase("connect");
    })();
  }, []);

  return (
    <>
      <GraphCanvas progressRef={progressRef} selfNodeReadyRef={selfNodeReadyRef} />
      <Act1Void progressRef={progressRef} selfNodeReadyRef={selfNodeReadyRef} />
      {phase === "connect" && <InstallPanel onDone={dissolveToGraph} />}
    </>
  );
}
