import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { 
  Activity, ShieldAlert, Cpu, Database, 
  BarChart2, Globe, Terminal, Briefcase, X
} from 'lucide-react';
import './index.css';

const API_BASE = 'http://localhost:8000/api';

const NeuralMap = ({ nodes, edges, onNodeClick }) => {
  const layout = {
    data: { top: '15%', left: '15%', icon: Globe },
    db: { top: '40%', left: '35%', icon: Database },
    quant: { top: '15%', left: '55%', icon: BarChart2 },
    research: { top: '75%', left: '35%', icon: Cpu },
    guardrail: { top: '75%', left: '65%', icon: ShieldAlert },
    broker: { top: '40%', left: '85%', icon: Briefcase }
  };

  return (
    <div className="glass-card neural-map-container">
      <svg className="edges-svg">
        {edges.map((edge, idx) => {
          const src = layout[edge.source];
          const tgt = layout[edge.target];
          if (!src || !tgt) return null;
          return (
            <line
              key={idx}
              x1={src.left} y1={src.top}
              x2={tgt.left} y2={tgt.top}
              className={`edge-path ${edge.animated ? 'animated' : ''}`}
            />
          );
        })}
      </svg>
      {nodes.map(node => {
        const pos = layout[node.id];
        if (!pos) return null;
        const Icon = pos.icon;
        return (
          <div 
            key={node.id} 
            className={`node ${node.status === 'active' ? 'active' : ''}`}
            style={{ top: pos.top, left: pos.left, transform: 'translate(-50%, -50%)', cursor: 'pointer' }}
            onClick={() => onNodeClick(node)}
          >
            <Icon className="node-icon" />
            <span className="node-label">{node.label}</span>
          </div>
        );
      })}
    </div>
  );
};

export default function App() {
  const [activeTab, setActiveTab] = useState('overview');
  const [systemStatus, setSystemStatus] = useState(null);
  const [positions, setPositions] = useState(null);
  const [ecosystem, setEcosystem] = useState(null);
  
  // Interactive Panel State
  const [selectedNode, setSelectedNode] = useState(null);
  const [nodeDetails, setNodeDetails] = useState(null);
  
  // Global Emergency Stop State
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [passwordInput, setPasswordInput] = useState('');

  // Terminal mock stream
  const [terminalLogs, setTerminalLogs] = useState([
    { time: '14:02:11', sender: 'SYSTEM', msg: 'Market Ingestion completed.' },
    { time: '14:03:04', sender: 'QUANT', msg: 'Optimized parameters applied.' },
    { time: '17:05:31', sender: 'SYSTEM', msg: 'WAL mode injected via AST into storage.py.' }
  ]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statRes, posRes, ecoRes] = await Promise.all([
          axios.get(`${API_BASE}/status`),
          axios.get(`${API_BASE}/positions`),
          axios.get(`${API_BASE}/ecosystem`)
        ]);
        setSystemStatus(statRes.data);
        setPositions(posRes.data);
        setEcosystem(ecoRes.data);
      } catch (err) {
        console.error("API falhou:", err);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleNodeClick = async (node) => {
    setSelectedNode(node);
    try {
      const res = await axios.get(`${API_BASE}/node/${node.id}`);
      setNodeDetails(res.data);
    } catch (e) {
      console.error(e);
    }
  };

  const handleAction = async (actionType) => {
    try {
      const res = await axios.post(`${API_BASE}/node/${selectedNode.id}/action`, { action: actionType });
      alert(res.data.msg);
    } catch (e) {
      alert("Erro ao disparar ação.");
    }
  };

  const handleEmergencyStop = async () => {
    try {
      const res = await axios.post(`${API_BASE}/system/emergency_stop`, { 
        action: 'emergency_stop', 
        password: passwordInput 
      });
      if (res.data.error) {
        alert(res.data.error);
      } else {
        alert(res.data.msg);
        setShowPasswordModal(false);
        setPasswordInput('');
        
        // Refresh positions immediately to show the cleared table
        const posRes = await axios.get(`${API_BASE}/positions`);
        setPositions(posRes.data);
      }
    } catch (e) {
      alert("Erro ao conectar com API.");
    }
  };

  if (!systemStatus || !positions || !ecosystem) {
    return <div className="loading">Carregando Meridian Core...</div>;
  }

  const kpis = {
    roi: ((positions.capital.current - positions.capital.initial) / positions.capital.initial * 100).toFixed(2)
  };

  return (
    <div className="dashboard-container">
      <header className="header">
        <h1><Activity color="#00f0ff" /> Meridian Command Center</h1>
        <div className="system-status">
          <div className="status-badge"><div className="status-dot"></div><span>SQLite DB</span></div>
          <div className="status-badge"><div className="status-dot"></div><span>AWS EC2</span></div>
          <div className="status-badge"><div className="status-dot"></div><span>Guard-Rail</span></div>
          
          {/* Global Emergency Stop Button */}
          <button 
            onClick={() => setShowPasswordModal(true)} 
            style={{ 
              background: 'rgba(239, 68, 68, 0.15)', 
              color: 'var(--danger)', 
              border: '1px solid rgba(239, 68, 68, 0.3)',
              borderRadius: '999px',
              padding: '0.5rem 1rem',
              fontWeight: '600',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem'
            }}
          >
            <ShieldAlert size={16} /> EMERGENCY STOP
          </button>
        </div>
      </header>

      <div className="tabs">
        <button className={`tab-btn ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>
          <BarChart2 size={18} /> Visão Geral (Carteira)
        </button>
        <button className={`tab-btn ${activeTab === 'neural' ? 'active' : ''}`} onClick={() => setActiveTab('neural')}>
          <Globe size={18} /> Mapa Neural Interativo
        </button>
      </div>

      <div className="main-content">
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          
          {activeTab === 'overview' && (
            <>
              {/* KPI CARDS */}
              <div className="kpi-grid">
                <div className="kpi-card">
                  <div className="kpi-title">Capital Inicial</div>
                  <div className="kpi-value">R$ {positions.capital.initial.toFixed(2)}</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-title">Patrimônio Atual</div>
                  <div className="kpi-value">R$ {positions.capital.current.toFixed(2)}</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-title">Retorno (ROI)</div>
                  <div className={`kpi-value ${kpis.roi >= 0 ? 'positive' : 'negative'}`}>
                    {kpis.roi > 0 ? '+' : ''}{kpis.roi}%
                  </div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-title">Posições Abertas</div>
                  <div className="kpi-value">{positions.active_positions.length}</div>
                </div>
              </div>

              <div className="glass-card">
                <h2 className="card-title">Carteira de Operações (MTM)</h2>
                <table>
                  <thead>
                    <tr><th>Ativo</th><th>Lado</th><th>Entrada</th><th>MTM</th><th>Alvo</th><th>Stop</th><th>Resultado</th></tr>
                  </thead>
                  <tbody>
                    {positions.active_positions.map((pos, i) => (
                      <tr key={i} onClick={() => setSelectedTicker(pos.ticker)} style={{ cursor: 'pointer' }}>
                        <td className="ticker-cell">{pos.ticker}</td>
                        <td><span className="side-badge">{pos.side}</span></td>
                        <td>R$ {pos.entry_price.toFixed(2)}</td>
                        <td>R$ {pos.current_price.toFixed(2)}</td>
                        <td>R$ {pos.target.toFixed(2)}</td>
                        <td>R$ {pos.stop.toFixed(2)}</td>
                        <td className={pos.pnl_pct >= 0 ? 'pnl-positive' : 'pnl-negative'}>
                          {pos.pnl_pct >= 0 ? '+' : ''}{pos.pnl_pct}%
                        </td>
                      </tr>
                    ))}
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {activeTab === 'neural' && (
            <NeuralMap nodes={ecosystem.nodes} edges={ecosystem.edges} onNodeClick={handleNodeClick} />
          )}
        </div>

        <div className="glass-card" style={{ padding: 0, display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '1.25rem', borderBottom: '1px solid var(--border-light)' }}>
            <h2 className="card-title" style={{ marginBottom: 0 }}><Terminal size={18} /> Comm Feed</h2>
          </div>
          <div className="terminal">
            {terminalLogs.map((log, i) => (
              <div key={i} className="terminal-line">
                <span className="term-time">[{log.time}]</span>
                <span className="term-sender">&lt;{log.sender}&gt;</span>
                <span className="term-msg">{log.msg}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* SIDE PANEL */}
      <div className={`side-panel ${selectedNode ? 'open' : ''}`}>
        {selectedNode && (
          <>
            <button className="side-panel-close" onClick={() => setSelectedNode(null)}><X size={24} /></button>
            <h2 style={{ fontSize: '1.5rem', color: '#fff', marginTop: '1rem' }}>{selectedNode.label}</h2>
            
            {nodeDetails ? (
              <>
                <div>
                  <div className="panel-section-title">Função no Ecossistema</div>
                  <div className="panel-box">{nodeDetails.role}</div>
                </div>
                <div>
                  <div className="panel-section-title">Agenda / Próxima Ação</div>
                  <div className="panel-box" style={{ color: 'var(--accent-cyan)' }}>{nodeDetails.next_run}</div>
                </div>
                <div>
                  <div className="panel-section-title">Últimos Registros (Logs)</div>
                  <div className="panel-box">
                    {nodeDetails.logs.map((l, idx) => <div key={idx} style={{ marginBottom: '0.5rem' }}>• {l}</div>)}
                  </div>
                </div>

                <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                  <button className="btn btn-primary" onClick={() => handleAction('run_now')}>
                    ▶ Forçar Execução Imediata
                  </button>
                </div>
              </>
            ) : (
              <div style={{ color: 'var(--text-muted)' }}>Carregando ficha médica...</div>
            )}
          </>
        )}
      </div>

      {/* PASSWORD MODAL */}
      {showPasswordModal && (
        <div className="modal-overlay">
          <div className="modal-content">
            <h3 style={{ color: 'var(--danger)', marginBottom: '1rem' }}>Autenticação Necessária</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
              Esta ação travará a corretora e liquidará todas as posições IMEDIATAMENTE. Insira a senha de CEO para confirmar o Circuit Breaker.
            </p>
            <input 
              type="password" 
              placeholder="Digite a senha..." 
              value={passwordInput}
              onChange={(e) => setPasswordInput(e.target.value)}
            />
            <div className="modal-actions">
              <button className="btn btn-primary" style={{ background: '#333', borderColor: '#555', color: '#fff' }} onClick={() => setShowPasswordModal(false)}>Cancelar</button>
              <button className="btn btn-danger" onClick={handleEmergencyStop}>Confirmar Liquidação</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
