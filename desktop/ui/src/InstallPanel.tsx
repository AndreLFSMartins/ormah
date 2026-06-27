import { useEffect, useState } from "react";
import { invoke } from "./lib/bridge";

interface AgentInfo {
  id: string;
  name: string;
  detected: boolean;
  wired: boolean;
  available_on_current_os: boolean;
}

export default function InstallPanel({ onDone }: { onDone: () => void }) {
  const [show, setShow] = useState(false);
  const [agents, setAgents] = useState<AgentInfo[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    requestAnimationFrame(() => setShow(true));
    (async () => {
      try { setAgents(await invoke<AgentInfo[]>("detect_agents")); }
      catch { setAgents([]); }
    })();
  }, []);

  const found = agents ? agents.filter((a) => a.available_on_current_os && a.detected) : [];
  const title = !agents ? "Looking around your machine"
    : found.length ? "Found your AI tools" : "No AI tools found yet";
  const lead = !agents ? "Finding the AI tools Ormah can connect to."
    : found.length ? "One click wires hooks and MCP into each."
    : "Install Claude Code, Claude Desktop, or Codex, then reopen Ormah.";

  async function connect() {
    setBusy(true);
    setStatus("Wiring your tools…");
    let succeeded = false;
    try {
      const res = await invoke<{ wired?: string[]; errors?: Record<string, string> }>("setup_agents");
      const errors = res.errors ?? {};
      const errorEntries = Object.entries(errors);
      const names = (res.wired ?? []).map(
        (id) => agents?.find((a) => a.id === id)?.name ?? id
      );
      if (errorEntries.length > 0) {
        setStatus(`Setup incomplete: ${errorEntries.map(([k, v]) => `${k}: ${v}`).join("; ")}`);
      } else {
        setStatus(names.length ? `Connected ${names.join(", ")}` : "Nothing to connect.");
        succeeded = true;
      }
    } catch (e) {
      setStatus(`Couldn't finish: ${e}`);
    }
    if (succeeded) {
      try { await invoke("mark_onboarded"); } catch { /* ignore */ }
      setTimeout(onDone, 1100);
    } else {
      setBusy(false);
    }
  }

  async function skip() {
    try { await invoke("mark_onboarded"); } catch { /* ignore */ }
    onDone();
  }

  return (
    <>
      <div className={"scrim" + (show ? " show" : "")} />
      <div className={"install" + (show ? " show" : "")}>
        <h2>{title}</h2>
        <p className="lead">{lead}</p>
        <div className="ledger">
          {agents && agents.filter((a) => a.available_on_current_os).map((a, i) => (
            <div key={a.id} className={"tool" + (a.detected ? " found" : "")} style={{ animationDelay: `${i * 0.08}s` }}>
              <span className="tdot" />
              <span className="tname">{a.name}</span>
              <span className="tstate">{a.detected ? "ready to connect" : "not found"}</span>
            </div>
          ))}
        </div>
        <div className="actions">
          {found.length > 0 && (
            <button className="btn primary" disabled={busy} onClick={connect}>Connect them</button>
          )}
          <button className="btn ghost" disabled={busy} onClick={skip}>Skip</button>
        </div>
        <div className="istatus">{status}</div>
      </div>
    </>
  );
}
