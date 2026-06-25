import { useEffect, useState } from "react";
import { invoke } from "./lib/bridge";

const TOOLS = [
  { key: "claude_code", name: "Claude Code" },
  { key: "claude_desktop", name: "Claude Desktop" },
  { key: "codex", name: "Codex" },
];

type Detected = Record<string, boolean>;

export default function InstallPanel({ onDone }: { onDone: () => void }) {
  const [show, setShow] = useState(false);
  const [detected, setDetected] = useState<Detected | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    requestAnimationFrame(() => setShow(true));
    (async () => {
      try { setDetected(await invoke<Detected>("detect_agents")); }
      catch { setDetected({}); }
    })();
  }, []);

  const found = detected ? TOOLS.filter((t) => detected[t.key]) : [];
  const title = !detected ? "Looking around your machine"
    : found.length ? "Found your AI tools" : "No AI tools found yet";
  const lead = !detected ? "Finding the AI tools Ormah can connect to."
    : found.length ? "One click wires hooks and MCP into each."
    : "Install Claude Code, Claude Desktop, or Codex, then reopen Ormah.";

  async function connect() {
    setBusy(true);
    setStatus("Wiring your tools…");
    let succeeded = false;
    try {
      const res = await invoke<{ wired?: string[]; errors?: string[] }>("setup_agents");
      const errors = res.errors ?? [];
      const names = (res.wired ?? []).map((k) => TOOLS.find((t) => t.key === k)?.name ?? k);
      if (errors.length) {
        setStatus(`Setup incomplete: ${errors.join("; ")}`);
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
          {detected && TOOLS.map((t, i) => {
            const ok = !!detected[t.key];
            return (
              <div key={t.key} className={"tool" + (ok ? " found" : "")} style={{ animationDelay: `${i * 0.08}s` }}>
                <span className="tdot" />
                <span className="tname">{t.name}</span>
                <span className="tstate">{ok ? "ready to connect" : "not found"}</span>
              </div>
            );
          })}
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
