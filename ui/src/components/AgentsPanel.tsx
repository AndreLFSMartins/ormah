import { useEffect, useState } from "react";
import { fetchAgentClients, runAgentSetup, wireAgent, unwireAgent } from "../api";
import type { AgentInfo } from "../api";

interface Props {
  open: boolean;
  onClose: () => void;
}

function StatusPill({ agent }: { agent: AgentInfo }) {
  if (!agent.available_on_current_os) {
    return <span className="agent-pill agent-pill--unavailable">not available on this OS</span>;
  }
  if (!agent.detected) {
    return <span className="agent-pill agent-pill--undetected">not installed</span>;
  }
  if (agent.wired) {
    return <span className="agent-pill agent-pill--wired">connected</span>;
  }
  return <span className="agent-pill agent-pill--detected">installed, not wired</span>;
}

export default function AgentsPanel({ open, onClose }: Props) {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null); // agent id currently being wired/unwired
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [fetchError, setFetchError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setFetchError(null);
    fetchAgentClients()
      .then(setAgents)
      .catch(() => setFetchError("Could not reach server."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (open) { load(); setErrors({}); }
  }, [open]);

  const handleWire = async (agentId: string) => {
    setBusy(agentId);
    setErrors(e => { const n = { ...e }; delete n[agentId]; return n; });
    try {
      const res = await wireAgent(agentId);
      if (res.errors[agentId]) setErrors(e => ({ ...e, [agentId]: res.errors[agentId] }));
    } catch {
      setErrors(e => ({ ...e, [agentId]: "Request failed." }));
    } finally {
      setBusy(null);
      load();
    }
  };

  const handleUnwire = async (agentId: string) => {
    setBusy(agentId);
    setErrors(e => { const n = { ...e }; delete n[agentId]; return n; });
    try {
      const res = await unwireAgent(agentId);
      if (res.errors[agentId]) setErrors(e => ({ ...e, [agentId]: res.errors[agentId] }));
    } catch {
      setErrors(e => ({ ...e, [agentId]: "Request failed." }));
    } finally {
      setBusy(null);
      load();
    }
  };

  const handleWireAll = async () => {
    setBusy("__all__");
    setErrors({});
    try {
      const res = await runAgentSetup();
      if (Object.keys(res.errors).length) setErrors(res.errors);
    } catch {
      setFetchError("Setup failed — check that ormah is running.");
    } finally {
      setBusy(null);
      load();
    }
  };

  const hasUnwired = agents.some(a => a.available_on_current_os && a.detected && !a.wired);

  return (
    <div className={`side-panel ${open ? "open" : ""}`}>
      <div className="side-panel-header">
        <span className="review-title">Agents</span>
        <button className="panel-close" onClick={onClose}>✕</button>
      </div>

      <div className="agents-panel-body">
        {loading && <p className="agents-loading">Loading…</p>}

        {!loading && agents.length > 0 && (
          <>
            <ul className="agents-list">
              {agents.map(agent => (
                <li key={agent.id} className="agent-row">
                  <div className="agent-row-info">
                    <span className="agent-name">{agent.name}</span>
                    <StatusPill agent={agent} />
                  </div>
                  <div className="agent-row-actions">
                    {agent.available_on_current_os && agent.detected && !agent.wired && (
                      <button
                        className="agent-btn agent-btn--connect"
                        onClick={() => handleWire(agent.id)}
                        disabled={busy !== null}
                      >
                        {busy === agent.id ? "Connecting…" : "Connect"}
                      </button>
                    )}
                    {agent.wired && (
                      <button
                        className="agent-btn agent-btn--disconnect"
                        onClick={() => handleUnwire(agent.id)}
                        disabled={busy !== null}
                      >
                        {busy === agent.id ? "Disconnecting…" : "Disconnect"}
                      </button>
                    )}
                  </div>
                  {errors[agent.id] && (
                    <p className="agent-row-error">{errors[agent.id]}</p>
                  )}
                </li>
              ))}
            </ul>

            {hasUnwired && (
              <button
                className="agents-wire-btn"
                onClick={handleWireAll}
                disabled={busy !== null}
              >
                {busy === "__all__" ? "Wiring…" : "Connect all"}
              </button>
            )}

            {!hasUnwired && !fetchError && (
              <p className="agents-all-wired">All detected agents are connected.</p>
            )}
          </>
        )}

        {fetchError && <p className="agents-error">{fetchError}</p>}
      </div>
    </div>
  );
}
