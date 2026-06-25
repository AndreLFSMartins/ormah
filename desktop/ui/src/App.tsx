import { useEffect, useRef, useState } from "react";
import GraphCanvas from "@/components/GraphCanvas";
import Act1Void from "@/components/Act1Void";
import InstallPanel from "./InstallPanel";
import { invoke, graphUrl, waitForServer, sleep, winMinimize, winClose } from "./lib/bridge";

type Phase = "intro" | "connect" | "graph";

function TitleBar() {
  return (
    <div className="titlebar">
      <div className="titlebar-drag" data-tauri-drag-region />
      <div className="titlebar-controls">
        <button className="tbtn" aria-label="Minimize" onClick={() => winMinimize()}>
          <svg width="11" height="11" viewBox="0 0 11 11"><rect x="1" y="5" width="9" height="1" fill="currentColor" /></svg>
        </button>
        <button className="tbtn close" aria-label="Close" onClick={() => winClose()}>
          <svg width="11" height="11" viewBox="0 0 11 11"><path d="M1 1l9 9M10 1l-9 9" stroke="currentColor" strokeWidth="1.1" /></svg>
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const progressRef = useRef(0);
  const selfNodeReadyRef = useRef<{ x: number; y: number } | null>(null);
  const [phase, setPhase] = useState<Phase>("intro");
  const [graphSrc, setGraphSrc] = useState("");
  const started = useRef(false);

  async function goGraph() {
    const url = await graphUrl();
    // Cache-bust so a fresh UI build is always loaded in the webview.
    setGraphSrc(url + (url.includes("?") ? "&" : "?") + "_=" + Date.now());
    document.getElementById("root")?.classList.add("to-graph");
    await sleep(620);
    setPhase("graph");
  }

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    (async () => {
      const t0 = Date.now();
      let onboarded = false;
      try { onboarded = await invoke<boolean>("is_onboarded"); } catch { /* ignore */ }

      const ready = await waitForServer();
      if (!ready) return;

      if (onboarded) {
        await sleep(Math.max(0, 2200 - (Date.now() - t0)));
        goGraph();
        return;
      }
      await sleep(Math.max(0, 5200 - (Date.now() - t0)));
      setPhase("connect");
    })();
  }, []);

  return (
    <>
      <TitleBar />
      {phase === "graph" ? (
        <iframe className="graph-frame" src={graphSrc} title="Ormah graph" />
      ) : (
        <div className="stage-wrap">
          <GraphCanvas progressRef={progressRef} selfNodeReadyRef={selfNodeReadyRef} />
          <Act1Void progressRef={progressRef} selfNodeReadyRef={selfNodeReadyRef} />
          {phase === "connect" && <InstallPanel onDone={goGraph} />}
        </div>
      )}
    </>
  );
}
