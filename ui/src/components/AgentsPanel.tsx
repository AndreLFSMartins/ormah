import { useEffect, useState } from "react";
import { fetchAgentClients, runAgentSetup } from "../api";
import type { AgentInfo, SetupResult } from "../api";

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
  const [wiring, setWiring] = useState(false);
  const [result, setResult] = useState<SetupResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchAgentClients()
      .then(setAgents)
      .catch(() => setError("Could not reach server"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (open) {
      load();
      setResult(null);
    }
  }, [open]);

  const wireAll = async () => {
    setWiring(true);
    setError(null);
    try {
      const res = await runAgentSetup();
      setResult(res);
      load(); // refresh status
    } catch {
      setError("Setup failed — check that ormah is running.");
    } finally {
      setWiring(false);
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
          <ul className="agents-list">
            {agents.map(agent => (
              <li key={agent.id} className="agent-row">
                <div className="agent-row-info">
                  <span className="agent-name">{agent.name}</span>
                  <StatusPill agent={agent} />
                </div>
              </li>
            ))}
          </ul>
        )}

        {result && (
          <div className="agents-result">
            {result.wired.length > 0 && (
              <p className="agents-result--ok">
                Connected: {result.wired.map(id => agents.find(a => a.id === id)?.name ?? id).join(", ")}
              </p>
            )}
            {Object.entries(result.errors).map(([id, msg]) => (
              <p key={id} className="agents-result--err">
                {agents.find(a => a.id === id)?.name ?? id}: {msg}
              </p>
            ))}
          </div>
        )}

        {error && <p className="agents-error">{error}</p>}

        {!loading && hasUnwired && (
          <button
            className="agents-wire-btn"
            onClick={wireAll}
            disabled={wiring}
          >
            {wiring ? "Wiring…" : "Wire all detected agents"}
          </button>
        )}

        {!loading && !hasUnwired && agents.length > 0 && !error && (
          <p className="agents-all-wired">All detected agents are connected.</p>
        )}
      </div>
    </div>
  );
}
