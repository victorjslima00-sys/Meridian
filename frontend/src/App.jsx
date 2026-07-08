import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { 
  Activity, ShieldAlert, Cpu, Database, 
  BarChart2, Globe, Terminal, Briefcase, Server 
} from 'lucide-react';
import './index.css';

const API_BASE = 'http://localhost:8000/api';

const NeuralMap = ({ nodes, edges }) => {
  // Coordenadas manuais (percentuais) para posicionar os nós
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
      {/* SVG Background for Edges */}
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

      {/* Nodes */}
      {nodes.map(node => {
        const pos = layout[node.id];
        if (!pos) return null;
        
        const Icon = pos.icon;
        
        return (
          <div 
            key={node.id} 
            className={`node ${node.status === 'active' ? 'active' : ''}`}
            style={{ top: pos.top, left: pos.left, transform: 'translate(-50%, -50%)' }}
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

  // Terminal mock stream
  const [terminalLogs, setTerminalLogs] = useState([
    { time: '14:02:11', sender: 'SYSTEM', msg: 'Market Ingestion (brapi) completed. 47/50 valid.' },
    { time: '14:02:32', sender: 'SIGNALS', msg: 'IBOV (877) < SMA-50. Macro filter triggered. NO BUYS.' },
    { time: '14:03:04', sender: 'QUANT', msg: 'Grid Search optimized parameters: stop_pct=0.05, target_pct=0.08.' },
    { time: '17:02:34', sender: 'COORD', msg: 'Dispatched Research agent and Guard-Rail.' },
    { time: '17:04:36', sender: 'RESEARCH', msg: 'Database scanned. Proposed WAL mode for performance.' },
    { time: '17:04:47', sender: 'GUARD-RAIL', msg: 'VERDICT APPROVED. Risk parameters respected.' },
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

  if (!systemStatus || !positions || !ecosystem) {
    return <div className="loading">Carregando Meridian Core...</div>;
  }

  return (
    <div className="dashboard-container">
      {/* Header */}
      <header className="header">
        <h1><Activity color="#00f0ff" /> Meridian Command Center</h1>
        <div className="system-status">
          <div className="status-badge">
            <div className={`status-dot ${systemStatus.modules.database === 'online' ? '' : 'offline'}`}></div>
            <span>SQLite Database</span>
          </div>
          <div className="status-badge">
            <div className="status-dot"></div>
            <span>AWS EC2 Core</span>
          </div>
          <div className="status-badge">
            <div className="status-dot"></div>
            <span>Guard-Rail AI</span>
          </div>
        </div>
      </header>

      {/* Tabs */}
      <div className="tabs">
        <button 
          className={`tab-btn ${activeTab === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveTab('overview')}
        >
          <BarChart2 size={18} /> Visão Geral
        </button>
        <button 
          className={`tab-btn ${activeTab === 'neural' ? 'active' : ''}`}
          onClick={() => setActiveTab('neural')}
        >
          <Globe size={18} /> Mapa Neural
        </button>
      </div>

      <div className="main-content">
        {/* Left Column (Dynamic Content) */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          
          {activeTab === 'overview' && (
            <div className="glass-card">
              <h2 className="card-title">Carteira de Operações (Simulado)</h2>
              <table>
                <thead>
                  <tr>
                    <th>Ativo</th>
                    <th>Lado</th>
                    <th>Entrada</th>
                    <th>MTM Atual</th>
                    <th>Alvo</th>
                    <th>Stop</th>
                    <th>Resultado</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.active_positions.map((pos, i) => (
                    <tr key={i}>
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
                  {positions.active_positions.length === 0 && (
                    <tr>
                      <td colSpan="7" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                        Nenhuma operação aberta no momento. (Filtro Macro IBOV segurando o capital).
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {activeTab === 'neural' && (
            <NeuralMap nodes={ecosystem.nodes} edges={ecosystem.edges} />
          )}
        </div>

        {/* Right Column (Terminal Feed) */}
        <div className="glass-card" style={{ padding: 0, display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '1.25rem', borderBottom: '1px solid var(--border-light)' }}>
            <h2 className="card-title" style={{ marginBottom: 0 }}>
              <Terminal size={18} /> Comm Feed
            </h2>
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
    </div>
  );
}
