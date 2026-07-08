import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { 
  Activity, ShieldAlert, Cpu, Database, 
  BarChart2, Globe, Terminal, Briefcase, X, Wifi, WifiOff
} from 'lucide-react';
import './index.css';

const API_BASE = 'http://localhost:8000/api';

/* ───────────────────────────────────────────────
   Ticker Tape Item — cores semânticas por variação
   Verde Esmeralda (#10b981) ▲  |  Vermelho Soft (#f43f5e) ▼
─────────────────────────────────────────────── */
const TickerTapeItem = ({ item }) => {
  const isPositive = item.includes('▲');
  const color = isPositive ? '#10b981' : '#f43f5e';
  return (
    <span className="ticker-item" style={{ color }} role="listitem" aria-label={item}>
      {item}
    </span>
  );
};

/* ───────────────────────────────────────────────
   Gráfico SVG Dinâmico — consome /api/history/{ticker}
   Resolve o bug de dados falsos (não duplica IBOV)
─────────────────────────────────────────────── */
const DynamicTickerChart = ({ ticker }) => {
  const [chartData, setChartData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    axios.get(`${API_BASE}/history/${ticker}`)
      .then(res => {
        setChartData(res.data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [ticker]);

  if (loading) return <div className="chart-loading"><div className="spinner" />Carregando dados de {ticker}...</div>;
  if (!chartData || !chartData.prices || chartData.prices.length < 2)
    return <p className="text-muted" style={{ textAlign: 'center', padding: '2rem' }}>Dados insuficientes para {ticker}</p>;

  const prices = chartData.prices;
  const dates = chartData.dates || [];
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min === 0 ? 1 : max - min;
  const W = 600, H = 200, PAD = 30;

  const points = prices.map((p, i) => {
    const x = PAD + (i / (prices.length - 1)) * (W - PAD * 2);
    const y = PAD + (1 - (p - min) / range) * (H - PAD * 2);
    return { x, y, price: p, date: dates[i] || '' };
  });

  const polyline = points.map(p => `${p.x},${p.y}`).join(' ');
  const gradientPath = `M ${points[0].x},${points[0].y} ${points.map(p => `L ${p.x},${p.y}`).join(' ')} L ${points[points.length - 1].x},${H} L ${points[0].x},${H} Z`;

  const isGain = prices[prices.length - 1] >= prices[0];
  const strokeColor = isGain ? '#10b981' : '#f43f5e';
  const gradId = `grad-${ticker}`;

  return (
    <div className="chart-container" role="img" aria-label={`Gráfico de preços de ${ticker} — últimos ${prices.length} pregões`}>
      <div className="chart-header">
        <div className="chart-ticker-label">{ticker}</div>
        <div className="chart-stats">
          <span>Mín: R$ {min.toFixed(2)}</span>
          <span>Máx: R$ {max.toFixed(2)}</span>
          <span style={{ color: strokeColor, fontWeight: 700 }}>
            Último: R$ {prices[prices.length - 1].toFixed(2)}
          </span>
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="price-chart-svg" preserveAspectRatio="none">
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={strokeColor} stopOpacity="0.3" />
            <stop offset="100%" stopColor={strokeColor} stopOpacity="0" />
          </linearGradient>
        </defs>
        {/* Grid horizontal */}
        {[0.25, 0.5, 0.75].map(f => (
          <line key={f} x1={PAD} y1={PAD + f * (H - PAD * 2)} x2={W - PAD} y2={PAD + f * (H - PAD * 2)}
            stroke="rgba(255,255,255,0.06)" strokeWidth="1" />
        ))}
        {/* Área preenchida */}
        <path d={gradientPath} fill={`url(#${gradId})`} />
        {/* Linha principal */}
        <polyline points={polyline} fill="none" stroke={strokeColor} strokeWidth="2.5"
          strokeLinecap="round" strokeLinejoin="round" className="chart-line-animate" />
        {/* Ponto final pulsante */}
        <circle cx={points[points.length - 1].x} cy={points[points.length - 1].y}
          r="4" fill={strokeColor} className="pulse-dot-chart" />
      </svg>
    </div>
  );
};

/* ───────────────────────────────────────────────
   Neural Map — Mapa de Agentes Interativos
─────────────────────────────────────────────── */
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
    <div className="glass-card neural-map-container" role="region" aria-label="Mapa Neural de Agentes">
      <svg className="edges-svg" aria-hidden="true">
        {edges.map((edge, idx) => {
          const src = layout[edge.source];
          const tgt = layout[edge.target];
          if (!src || !tgt) return null;
          return (
            <line key={idx}
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
          <div key={node.id}
            className={`node ${node.status === 'active' ? 'active' : ''}`}
            style={{ top: pos.top, left: pos.left, transform: 'translate(-50%, -50%)', cursor: 'pointer' }}
            onClick={() => onNodeClick(node)}
            role="button" tabIndex={0} aria-label={`Agente: ${node.label}`}
            onKeyDown={e => e.key === 'Enter' && onNodeClick(node)}
          >
            <Icon className="node-icon" />
            <span className="node-label">{node.label}</span>
          </div>
        );
      })}
    </div>
  );
};

/* ───────────────────────────────────────────────
   Onboarding Overlay (didático, primeira visita)
─────────────────────────────────────────────── */
const OnboardingOverlay = ({ onDismiss }) => (
  <div className="onboarding-overlay" role="dialog" aria-label="Guia de Introdução">
    <div className="onboarding-card">
      <div className="onboarding-icon">🛡️</div>
      <h2>Bem-vindo ao Meridian Command Center</h2>
      <p>Este é o painel de controle do seu robô de trading quantitativo na B3.</p>
      <ul className="onboarding-list">
        <li><strong>Visão Geral</strong> — Monitore capital, posições e resultados em tempo real</li>
        <li><strong>Mapa Neural</strong> — Visualize e controle cada agente do ecossistema</li>
        <li><strong>Terminal IA</strong> — Acompanhe as decisões do comitê de inteligência</li>
        <li><strong>Emergency Stop</strong> — Liquide tudo com autenticação de segurança</li>
      </ul>
      <button className="btn btn-primary onboarding-btn" onClick={onDismiss}>Entendido, vamos lá →</button>
    </div>
  </div>
);

/* ═══════════════════════════════════════════════
   APP PRINCIPAL
═══════════════════════════════════════════════ */
export default function App() {
  const [activeTab, setActiveTab] = useState('overview');
  const [systemStatus, setSystemStatus] = useState(null);
  const [positions, setPositions] = useState(null);
  const [ecosystem, setEcosystem] = useState(null);
  
  const [selectedNode, setSelectedNode] = useState(null);
  const [nodeDetails, setNodeDetails] = useState(null);
  const [selectedTicker, setSelectedTicker] = useState(null);
  
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [passwordInput, setPasswordInput] = useState('');

  const [tapeData, setTapeData] = useState(null);
  const [apiError, setApiError] = useState(null);
  const [isConnected, setIsConnected] = useState(true);

  // Onboarding: mostrar somente na primeira visita
  const [showOnboarding, setShowOnboarding] = useState(() => {
    return !localStorage.getItem('meridian_onboarded');
  });

  const dismissOnboarding = () => {
    localStorage.setItem('meridian_onboarded', 'true');
    setShowOnboarding(false);
  };

  // Terminal mock stream
  const [terminalLogs, setTerminalLogs] = useState([
    { time: new Date().toLocaleTimeString(), sender: 'SISTEMA', msg: 'Conexão segura estabelecida com o cluster.' },
    { time: new Date().toLocaleTimeString(), sender: 'QUANT', msg: 'Modelos estocásticos carregados na memória.' }
  ]);
  const terminalRef = useRef(null);

  useEffect(() => {
    const thoughts = [
      { sender: 'PESQUISADOR', msg: 'Analisando fluxo institucional em PETR4...' },
      { sender: 'GUARD-RAIL', msg: 'Auditoria térmica do motor de risco: OK. Exposição controlada.' },
      { sender: 'QUANT', msg: 'Calculando bandas de volatilidade implícita (IV) para opções.' },
      { sender: 'SISTEMA', msg: 'Sincronização de relógio atômico com B3 concluída.' },
      { sender: 'PESQUISADOR', msg: 'Lendo balanço trimestral. Sentimento geral: Bullish.' },
      { sender: 'QUANT', msg: 'Ajuste fino de pesos no modelo XGBoost.' },
      { sender: 'GUARD-RAIL', msg: 'VaR (Value at Risk) atualizado. Nível de alerta verde.' }
    ];

    const interval = setInterval(() => {
      const randomThought = thoughts[Math.floor(Math.random() * thoughts.length)];
      setTerminalLogs(prev => {
        const newLogs = [...prev, { time: new Date().toLocaleTimeString(), ...randomThought }];
        return newLogs.length > 50 ? newLogs.slice(-50) : newLogs;
      });
    }, 4500);

    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (terminalRef.current) terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
  }, [terminalLogs]);

  // Data polling
  useEffect(() => {
    const fetchData = async () => {
      try {
        setApiError(null);
        const [statRes, posRes, ecoRes, tapeRes] = await Promise.all([
          axios.get(`${API_BASE}/status`),
          axios.get(`${API_BASE}/positions`),
          axios.get(`${API_BASE}/ecosystem`),
          axios.get(`${API_BASE}/market_tape`)
        ]);
        if (posRes.data.error_msg) console.warn("Aviso do servidor:", posRes.data.error_msg);
        setSystemStatus(statRes.data);
        setPositions(posRes.data);
        setEcosystem(ecoRes.data);
        setTapeData(tapeRes.data);
        setIsConnected(true);
      } catch (err) {
        console.error("API falhou:", err);
        setApiError(err.message || "Erro de conexão com o servidor API.");
        setIsConnected(false);
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
    } catch (e) { console.error(e); }
  };

  const handleAction = async (actionType) => {
    try {
      const res = await axios.post(`${API_BASE}/node/${selectedNode.id}/action`, { action: actionType });
      alert(res.data.msg);
    } catch (e) { alert("Erro ao disparar ação."); }
  };

  const handleEmergencyStop = async () => {
    try {
      const res = await axios.post(`${API_BASE}/system/emergency_stop`, { 
        action: 'emergency_stop', password: passwordInput 
      });
      if (res.data.error) {
        alert(res.data.error);
      } else {
        alert(res.data.msg);
        setShowPasswordModal(false);
        setPasswordInput('');
        const posRes = await axios.get(`${API_BASE}/positions`);
        setPositions(posRes.data);
      }
    } catch (e) { alert("Erro ao conectar com API."); }
  };

  /* ─── TELA DE ERRO DE CONEXÃO ─── */
  if (apiError) {
    return (
      <div className="error-screen" role="alert">
        <WifiOff size={48} className="error-icon" />
        <h2>Conexão Perdida</h2>
        <p>{apiError}</p>
        <p className="error-hint">Verifique se o backend FastAPI está rodando na porta 8000.</p>
        <button className="btn btn-danger" onClick={() => window.location.reload()}>
          Reconectar
        </button>
      </div>
    );
  }

  /* ─── LOADING ─── */
  if (!systemStatus || !positions || !ecosystem || !tapeData) {
    return (
      <div className="loading-screen" role="status" aria-live="polite">
        <div className="loading-spinner" />
        <span>Inicializando Meridian Command Center...</span>
      </div>
    );
  }

  const kpis = {
    roi: ((positions.capital.current - positions.capital.initial) / positions.capital.initial * 100).toFixed(2)
  };

  return (
    <div className="dashboard-container">
      {showOnboarding && <OnboardingOverlay onDismiss={dismissOnboarding} />}
      
      {/* ═══ HEADER ═══ */}
      <header className="header" role="banner">
        <h1><Activity color="#00f0ff" aria-hidden="true" /> Meridian Command Center</h1>
        <div className="system-status">
          <div className="status-badge" aria-label="Status do banco de dados: online">
            <div className="status-dot" /><span>SQLite DB</span>
          </div>
          <div className="status-badge" aria-label="Status do servidor: online">
            <div className="status-dot" /><span>AWS EC2</span>
          </div>
          <div className="status-badge" aria-label="Guard-Rail: ativo">
            <div className="status-dot" /><span>Guard-Rail</span>
          </div>

          {/* Indicador de conexão */}
          <div className={`conn-indicator ${isConnected ? 'online' : 'offline'}`} aria-live="polite">
            {isConnected ? <Wifi size={14} /> : <WifiOff size={14} />}
            <span>{isConnected ? 'LIVE' : 'OFFLINE'}</span>
          </div>
          
          {/* Emergency Stop */}
          <button 
            className="emergency-btn"
            onClick={() => setShowPasswordModal(true)}
            aria-label="Acionar parada de emergência"
          >
            <ShieldAlert size={16} /> EMERGENCY STOP
          </button>
        </div>
      </header>

      {/* ═══ TICKER TAPE LIVE FEED ═══ */}
      <div className="ticker-wrap" role="marquee" aria-label="Fita de mercado em tempo real">
        <div className="ticker-move">
          {tapeData.tape.map((item, idx) => <TickerTapeItem key={idx} item={item} />)}
          {tapeData.tape.map((item, idx) => <TickerTapeItem key={`loop-${idx}`} item={item} />)}
        </div>
      </div>

      {/* ═══ TABS ═══ */}
      <div className="tabs" role="tablist">
        <button className={`tab-btn ${activeTab === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveTab('overview')} role="tab" aria-selected={activeTab === 'overview'}>
          <BarChart2 size={18} aria-hidden="true" /> Visão Geral (Carteira)
        </button>
        <button className={`tab-btn ${activeTab === 'neural' ? 'active' : ''}`}
          onClick={() => setActiveTab('neural')} role="tab" aria-selected={activeTab === 'neural'}>
          <Globe size={18} aria-hidden="true" /> Mapa Neural Interativo
        </button>
      </div>

      {/* ═══ MAIN CONTENT ═══ */}
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
                <div className="kpi-card highlight">
                  <div className="kpi-title">Patrimônio Atual</div>
                  <div className="kpi-value" style={{color: '#00f0ff'}}>R$ {positions.capital.current.toFixed(2)}</div>
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

              {/* TABELA DE POSIÇÕES */}
              <div className="glass-card">
                <h2 className="card-title" style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                  Carteira de Operações (MTM)
                  <span style={{fontSize: '0.8rem', color: '#8b9bb4', fontWeight: 'normal'}}>Clique em uma linha para abrir o Gráfico Dinâmico</span>
                </h2>
                <table role="grid" aria-label="Posições abertas da carteira">
                  <thead>
                    <tr><th>Ativo</th><th>Lado</th><th>Entrada</th><th>MTM</th><th>Alvo</th><th>Stop</th><th>Resultado</th></tr>
                  </thead>
                  <tbody>
                    {positions.active_positions.length === 0 ? (
                      <tr>
                        <td colSpan="7" style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                          Nenhuma posição aberta. Capital protegido. 🛡️
                        </td>
                      </tr>
                    ) : (
                      positions.active_positions.map((pos, i) => {
                        const priceDiff = pos.target - pos.entry_price;
                        const progress = priceDiff === 0 ? 0 : Math.max(0, Math.min(100, ((pos.current_price - pos.entry_price) / priceDiff) * 100));
                        return (
                          <tr key={i} onClick={() => setSelectedTicker(pos.ticker)}
                            className="table-row-hover" style={{ cursor: 'pointer' }}
                            role="row" tabIndex={0}
                            onKeyDown={e => e.key === 'Enter' && setSelectedTicker(pos.ticker)}
                            aria-label={`${pos.ticker}: ${pos.pnl_pct >= 0 ? 'lucro' : 'prejuízo'} de ${pos.pnl_pct}%`}
                          >
                            <td className="ticker-cell">{pos.ticker}</td>
                            <td><span className={`side-badge ${pos.side === 'BUY' ? 'buy' : 'sell'}`}>{pos.side}</span></td>
                            <td>R$ {pos.entry_price.toFixed(2)}</td>
                            <td>
                              R$ {pos.current_price.toFixed(2)}
                              <div className="progress-container"><div className="progress-fill" style={{width: `${progress}%`}} /></div>
                            </td>
                            <td>R$ {pos.target.toFixed(2)}</td>
                            <td>R$ {pos.stop.toFixed(2)}</td>
                            <td className={pos.pnl_pct >= 0 ? 'pnl-positive' : 'pnl-negative'}>
                              {pos.pnl_pct >= 0 ? '+' : ''}{pos.pnl_pct}%
                            </td>
                          </tr>
                        );
                      })
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

        {/* ═══ TERMINAL IA ═══ */}
        <div className="glass-card" style={{ padding: 0, display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '1.25rem', borderBottom: '1px solid var(--border-light)' }}>
            <h2 className="card-title" style={{ marginBottom: 0 }}>
              <Terminal size={18} aria-hidden="true" /> O que a IA está pensando?
            </h2>
          </div>
          <div className="terminal" ref={terminalRef} role="log" aria-live="polite" aria-label="Feed de pensamentos da IA">
            {terminalLogs.map((log, i) => (
              <div key={i} className="terminal-line">
                <span className="term-time">[{log.time}]</span>
                <span className="term-sender" style={{
                  color: log.sender === 'QUANT' ? '#00f3ff' 
                       : log.sender === 'GUARD-RAIL' ? '#f43f5e' 
                       : log.sender === 'PESQUISADOR' ? '#a3ff00' 
                       : '#8b9bb4'
                }}>&lt;{log.sender}&gt;</span>
                <span className="term-msg">{log.msg}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ═══ MODAL: GRÁFICO DINÂMICO POR TICKER ═══ */}
      {selectedTicker && (
        <div className="modal-overlay" onClick={() => setSelectedTicker(null)}
          role="dialog" aria-modal="true" aria-label={`Gráfico de ${selectedTicker}`}>
          <div className="modal-content chart-modal" onClick={e => e.stopPropagation()}>
            <h3 className="chart-modal-header">
              <span>📈 Evolução em Tempo Real: <strong>{selectedTicker}</strong></span>
              <button className="btn-close-x" onClick={() => setSelectedTicker(null)} aria-label="Fechar gráfico">
                <X size={20} />
              </button>
            </h3>
            <DynamicTickerChart ticker={selectedTicker} />
          </div>
        </div>
      )}

      {/* ═══ SIDE PANEL ═══ */}
      <div className={`side-panel ${selectedNode ? 'open' : ''}`} role="complementary" aria-label="Detalhes do agente">
        {selectedNode && (
          <>
            <button className="side-panel-close" onClick={() => setSelectedNode(null)} aria-label="Fechar painel">
              <X size={24} />
            </button>
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

      {/* ═══ MODAL: EMERGENCY STOP (AUTENTICAÇÃO) ═══ */}
      {showPasswordModal && (
        <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="Autenticação de emergência">
          <div className="modal-content emergency-modal">
            <div className="emergency-header">
              <ShieldAlert size={32} color="#f43f5e" />
              <h3>Autenticação Necessária</h3>
            </div>
            <p className="emergency-warning">
              Esta ação travará a corretora e liquidará todas as posições <strong>IMEDIATAMENTE</strong>. 
              Insira a senha de CEO para confirmar o Circuit Breaker.
            </p>
            <input 
              type="password" 
              placeholder="Digite a senha..." 
              value={passwordInput}
              onChange={(e) => setPasswordInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleEmergencyStop()}
              autoFocus
              aria-label="Senha de emergência"
            />
            <div className="modal-actions">
              <button className="btn btn-cancel" onClick={() => setShowPasswordModal(false)}>Cancelar</button>
              <button className="btn btn-danger" onClick={handleEmergencyStop}>🔴 Confirmar Liquidação</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
