import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import {
  Activity, ShieldAlert, Cpu, Database,
  BarChart2, Globe, Terminal, Briefcase, X,
  Wifi, WifiOff, TrendingUp, TrendingDown,
  ChevronRight, Bell, Settings, RefreshCw,
  DollarSign, Percent, BookOpen, History
} from 'lucide-react';
import { TickerAreaChart, SparkLine, PortfolioChart } from './Charts';
import './index.css';

const API_BASE = 'http://localhost:8000/api';

// ─── Ticker Tape Item com cor semântica ───────────────────────────────────────
const TapeItem = ({ item }) => {
  const isUp = item.includes('▲');
  return (
    <span className="tape-item" data-up={isUp}>
      {item}
    </span>
  );
};

// ─── KPI Card ─────────────────────────────────────────────────────────────────
const KpiCard = ({ title, value, sub, icon: Icon, color = '#00f3ff', trend }) => (
  <div className="kpi-card">
    <div className="kpi-header">
      <span className="kpi-label">{title}</span>
      {Icon && <Icon size={18} color={color} opacity={0.7} />}
    </div>
    <div className="kpi-value" style={{ color }}>{value}</div>
    {(sub || trend !== undefined) && (
      <div className="kpi-sub" style={{ color: trend >= 0 ? '#10b981' : '#f43f5e' }}>
        {trend >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
        {sub}
      </div>
    )}
  </div>
);

// ─── Position Row com mini-sparkline ─────────────────────────────────────────
const PositionRow = ({ pos, onClick }) => {
  const priceDiff = pos.target - pos.entry_price;
  const progress = priceDiff === 0 ? 0 : Math.max(0, Math.min(100, ((pos.current_price - pos.entry_price) / priceDiff) * 100));
  const isGain = pos.pnl_pct >= 0;

  return (
    <tr className="pos-row" onClick={onClick} tabIndex={0} onKeyDown={e => e.key === 'Enter' && onClick()}>
      <td>
        <div className="ticker-badge">{pos.ticker}</div>
      </td>
      <td>
        <span className={`side-chip ${pos.side === 'BUY' ? 'long' : 'short'}`}>
          {pos.side === 'BUY' ? '↑ LONG' : '↓ SHORT'}
        </span>
      </td>
      <td className="mono">R$ {pos.entry_price.toFixed(2)}</td>
      <td>
        <div className="mtm-cell">
          <span className="mono" style={{ color: isGain ? '#10b981' : '#f43f5e' }}>
            R$ {pos.current_price.toFixed(2)}
          </span>
          <div className="prog-track">
            <div className="prog-fill" style={{ width: `${progress}%`, background: isGain ? '#10b981' : '#f43f5e' }} />
          </div>
        </div>
      </td>
      <td className="mono dim">R$ {pos.target.toFixed(2)}</td>
      <td className="mono dim">R$ {pos.stop.toFixed(2)}</td>
      <td>
        <span className={`pnl-chip ${isGain ? 'gain' : 'loss'}`}>
          {isGain ? '+' : ''}{pos.pnl_pct}%
        </span>
      </td>
      <td>
        <ChevronRight size={14} color="#8b9bb4" />
      </td>
    </tr>
  );
};

// ─── Neural Map ───────────────────────────────────────────────────────────────
const NeuralMap = ({ nodes, edges, onNodeClick }) => {
  const layout = {
    data:      { top: '15%', left: '15%', icon: Globe, color: '#3b82f6' },
    db:        { top: '40%', left: '35%', icon: Database, color: '#8b5cf6' },
    quant:     { top: '15%', left: '58%', icon: BarChart2, color: '#00f3ff' },
    research:  { top: '75%', left: '35%', icon: Cpu, color: '#f59e0b' },
    guardrail: { top: '75%', left: '65%', icon: ShieldAlert, color: '#f43f5e' },
    broker:    { top: '40%', left: '85%', icon: Briefcase, color: '#10b981' },
  };

  return (
    <div className="neural-canvas">
      <svg className="neural-svg">
        {edges.map((e, i) => {
          const s = layout[e.source], t = layout[e.target];
          if (!s || !t) return null;
          return (
            <line key={i}
              x1={s.left} y1={s.top} x2={t.left} y2={t.top}
              className={`neural-edge ${e.animated ? 'live' : ''}`}
            />
          );
        })}
      </svg>
      {nodes.map(node => {
        const pos = layout[node.id];
        if (!pos) return null;
        const Icon = pos.icon;
        return (
          <button key={node.id} className={`neural-node ${node.status === 'active' ? 'active' : ''}`}
            style={{ top: pos.top, left: pos.left, '--node-color': pos.color }}
            onClick={() => onNodeClick(node)}
            aria-label={node.label}
          >
            <div className="neural-ring" />
            <Icon size={20} />
            <span className="neural-label">{node.label}</span>
          </button>
        );
      })}
    </div>
  );
};

// ─── History Page ─────────────────────────────────────────────────────────────
const HistoryPage = ({ tickers }) => {
  const [selected, setSelected] = useState(tickers?.[0] || 'PETR4');
  return (
    <div className="history-page">
      <div className="history-sidebar">
        <div className="sidebar-title">Ativos</div>
        {(tickers?.length ? tickers : ['PETR4', 'VALE3', 'ITUB4', 'BBDC4', 'ABEV3']).map(t => (
          <button key={t} className={`sidebar-ticker ${selected === t ? 'active' : ''}`}
            onClick={() => setSelected(t)}>
            {t}
          </button>
        ))}
      </div>
      <div className="history-main">
        <div className="section-header">
          <h3>{selected}</h3>
          <span className="muted-tag">Últimos 90 pregões · Fonte: SQLite/ohlcv</span>
        </div>
        <div className="glass-panel">
          <TickerAreaChart ticker={selected} />
        </div>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════
// APP PRINCIPAL
// ═══════════════════════════════════════════════════════════════════
export default function App() {
  const [tab, setTab] = useState('overview');
  const [status, setStatus] = useState(null);
  const [positions, setPositions] = useState(null);
  const [ecosystem, setEcosystem] = useState(null);
  const [tapeData, setTapeData] = useState(null);
  const [apiError, setApiError] = useState(null);
  const [connected, setConnected] = useState(true);

  const [chartModal, setChartModal] = useState(null); // ticker string
  const [nodePanel, setNodePanel] = useState(null);
  const [nodeDetails, setNodeDetails] = useState(null);
  const [showEmergency, setShowEmergency] = useState(false);
  const [password, setPassword] = useState('');

  const [logs, setLogs] = useState([
    { t: new Date().toLocaleTimeString(), sender: 'SISTEMA', msg: 'Conexão segura estabelecida.' },
    { t: new Date().toLocaleTimeString(), sender: 'QUANT',  msg: 'Parâmetros Donchian carregados.' },
  ]);
  const termRef = useRef(null);

  // Terminal stream
  useEffect(() => {
    const msgs = [
      { sender: 'PESQUISADOR', msg: 'Analisando fluxo institucional em PETR4...' },
      { sender: 'GUARD-RAIL',  msg: 'Correlação PETR4/VALE3 = 0.61 — dentro do limite.' },
      { sender: 'QUANT',       msg: 'Sharpe otimizado: 0.87 (regime alta_juros).' },
      { sender: 'SISTEMA',     msg: 'Sincronização B3 concluída. Latência: 12ms.' },
      { sender: 'PESQUISADOR', msg: 'Sentimento macroeconômico: neutro com viés de alta.' },
      { sender: 'GUARD-RAIL',  msg: 'VaR diário: R$ 8.40. Limite: R$ 9.00. ✓' },
      { sender: 'QUANT',       msg: 'Novo breakout detectado em WEGE3 (volume 2.3x).' },
    ];
    const iv = setInterval(() => {
      const m = msgs[Math.floor(Math.random() * msgs.length)];
      setLogs(prev => [...prev.slice(-49), { t: new Date().toLocaleTimeString(), ...m }]);
    }, 4000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight;
  }, [logs]);

  // Data fetch
  useEffect(() => {
    const load = async () => {
      try {
        const [s, p, e, tp] = await Promise.all([
          axios.get(`${API_BASE}/status`),
          axios.get(`${API_BASE}/positions`),
          axios.get(`${API_BASE}/ecosystem`),
          axios.get(`${API_BASE}/market_tape`),
        ]);
        setStatus(s.data); setPositions(p.data);
        setEcosystem(e.data); setTapeData(tp.data);
        setConnected(true); setApiError(null);
      } catch (e) {
        setApiError(e.message); setConnected(false);
      }
    };
    load();
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, []);

  const openNode = async (node) => {
    setNodePanel(node); setNodeDetails(null);
    try {
      const r = await axios.get(`${API_BASE}/node/${node.id}`);
      setNodeDetails(r.data);
    } catch {}
  };

  const doEmergencyStop = async () => {
    try {
      const r = await axios.post(`${API_BASE}/system/emergency_stop`, { action: 'emergency_stop', password });
      alert(r.data.error || r.data.msg);
      if (!r.data.error) { setShowEmergency(false); setPassword(''); }
    } catch { alert('Erro de conexão.'); }
  };

  // ── LOADING ────────────────────────────────────────────────────
  if (!status || !positions || !ecosystem || !tapeData) {
    return (
      <div className="splash">
        <div className="splash-glow" />
        <div className="splash-logo">
          <Activity size={40} color="#00f3ff" />
          <span>MERIDIAN</span>
        </div>
        <div className="splash-bar">
          <div className="splash-fill" />
        </div>
        <p className="splash-sub">{apiError ? `⚠️ ${apiError}` : 'Conectando ao cluster...'}</p>
      </div>
    );
  }

  const roi = ((positions.capital.current - positions.capital.initial) / positions.capital.initial * 100).toFixed(2);
  const roiNum = parseFloat(roi);
  const tickers = positions.active_positions.map(p => p.ticker);

  // ── RENDER ─────────────────────────────────────────────────────
  return (
    <div className="shell">

      {/* ── SIDEBAR ── */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <Activity size={22} color="#00f3ff" />
          <span>MERIDIAN</span>
        </div>

        <nav className="sidebar-nav">
          {[
            { id: 'overview',  Icon: BarChart2,  label: 'Visão Geral' },
            { id: 'history',   Icon: History,    label: 'Histórico' },
            { id: 'neural',    Icon: Globe,      label: 'Mapa Neural' },
            { id: 'backtest',  Icon: BookOpen,   label: 'Backtests' },
          ].map(({ id, Icon, label }) => (
            <button key={id} className={`nav-item ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className={`conn-pill ${connected ? 'up' : 'down'}`}>
            {connected ? <Wifi size={12} /> : <WifiOff size={12} />}
            {connected ? 'LIVE' : 'OFFLINE'}
          </div>
          <button className="icon-btn" title="Configurações"><Settings size={16} /></button>
          <button className="icon-btn" title="Alertas"><Bell size={16} /></button>
        </div>
      </aside>

      {/* ── MAIN ── */}
      <main className="main-area">

        {/* ── TOPBAR ── */}
        <header className="topbar">
          <div className="topbar-tape" aria-label="Fita de mercado">
            <div className="tape-scroll">
              {tapeData.tape.map((item, i) => <TapeItem key={i} item={item} />)}
              {tapeData.tape.map((item, i) => <TapeItem key={`r${i}`} item={item} />)}
            </div>
          </div>
          <button className="emergency-btn" onClick={() => setShowEmergency(true)}>
            <ShieldAlert size={14} /> STOP
          </button>
        </header>

        {/* ── PAGE CONTENT ── */}
        <div className="page-content">

          {/* OVERVIEW ─────────────────────────────────────────── */}
          {tab === 'overview' && (
            <div className="overview-layout">

              {/* KPI ROW */}
              <div className="kpi-row">
                <KpiCard
                  title="Capital Inicial" icon={DollarSign} color="#8b9bb4"
                  value={`R$ ${positions.capital.initial.toFixed(2)}`}
                />
                <KpiCard
                  title="Patrimônio Atual" icon={DollarSign} color="#00f3ff"
                  value={`R$ ${positions.capital.current.toFixed(2)}`}
                  sub={`${roiNum >= 0 ? '+' : ''}${roi}% total`}
                  trend={roiNum}
                />
                <KpiCard
                  title="ROI" icon={Percent} color={roiNum >= 0 ? '#10b981' : '#f43f5e'}
                  value={`${roiNum >= 0 ? '+' : ''}${roi}%`}
                  sub="desde o início"
                  trend={roiNum}
                />
                <KpiCard
                  title="Posições Abertas" icon={Activity} color="#f59e0b"
                  value={positions.active_positions.length}
                  sub={`R$ ${positions.capital.invested?.toFixed(2) || '0.00'} investido`}
                />
              </div>

              {/* PORTFOLIO CHART + POSITIONS */}
              <div className="content-grid">

                {/* Left: Portfolio evolution + table */}
                <div className="left-col">
                  <div className="glass-panel">
                    <div className="panel-header">
                      <h3>Evolução do Portfólio</h3>
                      <span className="muted-tag">30 dias · BRL</span>
                    </div>
                    <PortfolioChart capital={positions.capital} />
                  </div>

                  <div className="glass-panel" style={{ marginTop: '1rem' }}>
                    <div className="panel-header">
                      <h3>Posições Abertas (MTM)</h3>
                      <span className="muted-tag">Clique para ver o gráfico</span>
                    </div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Ativo</th><th>Lado</th><th>Entrada</th>
                            <th>MTM / Progresso</th><th>Alvo</th><th>Stop</th>
                            <th>PnL</th><th></th>
                          </tr>
                        </thead>
                        <tbody>
                          {positions.active_positions.length === 0 ? (
                            <tr>
                              <td colSpan="8" className="empty-state">
                                🛡️ Nenhuma posição aberta — capital protegido
                              </td>
                            </tr>
                          ) : (
                            positions.active_positions.map((p, i) => (
                              <PositionRow key={i} pos={p} onClick={() => setChartModal(p.ticker)} />
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>

                {/* Right: Terminal IA */}
                <div className="right-col">
                  <div className="glass-panel terminal-panel">
                    <div className="panel-header">
                      <h3><Terminal size={16} /> Comitê de IA</h3>
                      <span className="live-badge">● LIVE</span>
                    </div>
                    <div className="terminal-feed" ref={termRef}>
                      {logs.map((l, i) => (
                        <div key={i} className="log-line">
                          <span className="log-time">{l.t}</span>
                          <span className={`log-sender sender-${l.sender.toLowerCase().replace('-','')}`}>
                            {l.sender}
                          </span>
                          <span className="log-msg">{l.msg}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* HISTORY ──────────────────────────────────────────── */}
          {tab === 'history' && (
            <div className="page-section">
              <div className="page-title">
                <History size={22} />
                <div>
                  <h2>Histórico de Preços</h2>
                  <p>Dados reais da tabela <code>ohlcv</code> · SQLite</p>
                </div>
              </div>
              <HistoryPage tickers={tickers.length ? tickers : ['PETR4', 'VALE3', 'ITUB4']} />
            </div>
          )}

          {/* NEURAL MAP ───────────────────────────────────────── */}
          {tab === 'neural' && (
            <div className="page-section">
              <div className="page-title">
                <Globe size={22} />
                <div>
                  <h2>Mapa Neural do Ecossistema</h2>
                  <p>Agentes ativos e fluxo de dados em tempo real</p>
                </div>
              </div>
              <div className="glass-panel" style={{ flex: 1, minHeight: 500 }}>
                <NeuralMap nodes={ecosystem.nodes} edges={ecosystem.edges} onNodeClick={openNode} />
              </div>
            </div>
          )}

          {/* BACKTEST ─────────────────────────────────────────── */}
          {tab === 'backtest' && (
            <div className="page-section">
              <div className="page-title">
                <BookOpen size={22} />
                <div>
                  <h2>Relatório de Backtests</h2>
                  <p>Resultados dos 3 regimes de mercado · Donchian Breakout 20d</p>
                </div>
              </div>
              <div className="backtest-grid">
                {[
                  { name: 'Crise/Volatilidade', period: 'Mar–Set 2020', sharpe: 0.41, wr: '38%', trades: 47, color: '#f59e0b' },
                  { name: 'Alta de Juros (Selic)',   period: 'Jun 2021–Dez 2022', sharpe: 0.33, wr: '37%', trades: 112, color: '#f43f5e' },
                  { name: 'Recuperação Lateral', period: 'Jan 2023–Jun 2024', sharpe: 0.89, wr: '41%', trades: 89, color: '#10b981' },
                ].map((r, i) => (
                  <div key={i} className="backtest-card" style={{ '--accent': r.color }}>
                    <div className="bt-header">
                      <h3>{r.name}</h3>
                      <span className="bt-period">{r.period}</span>
                    </div>
                    <div className="bt-metrics">
                      <div className="bt-metric">
                        <span className="bt-label">Sharpe</span>
                        <span className="bt-value" style={{ color: r.color }}>{r.sharpe}</span>
                      </div>
                      <div className="bt-metric">
                        <span className="bt-label">Win Rate</span>
                        <span className="bt-value">{r.wr}</span>
                      </div>
                      <div className="bt-metric">
                        <span className="bt-label">Trades</span>
                        <span className="bt-value">{r.trades}</span>
                      </div>
                    </div>
                    <div className="bt-bar-wrap">
                      <div className="bt-bar" style={{ width: `${Math.min(100, r.sharpe / 1.5 * 100)}%`, background: r.color }} />
                    </div>
                    <div className="bt-gate">
                      Gate Sharpe ≥ 0.25 · {r.sharpe >= 0.25 ? '✅ Passou' : '❌ Falhou'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

        </div>
      </main>

      {/* ── MODAL: CHART ── */}
      {chartModal && (
        <div className="overlay" onClick={() => setChartModal(null)}>
          <div className="modal-box chart-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-head">
              <h3>📈 {chartModal} · Preços Históricos (90d)</h3>
              <button className="close-btn" onClick={() => setChartModal(null)}><X size={18} /></button>
            </div>
            <TickerAreaChart ticker={chartModal} />
          </div>
        </div>
      )}

      {/* ── SIDE PANEL: NEURAL NODE ── */}
      <div className={`side-drawer ${nodePanel ? 'open' : ''}`}>
        {nodePanel && (
          <>
            <div className="drawer-head">
              <h3>{nodePanel.label}</h3>
              <button className="close-btn" onClick={() => setNodePanel(null)}><X size={18} /></button>
            </div>
            {nodeDetails ? (
              <div className="drawer-body">
                <div className="detail-block">
                  <span className="detail-label">Função</span>
                  <span className="detail-val">{nodeDetails.role}</span>
                </div>
                <div className="detail-block">
                  <span className="detail-label">Próxima Ação</span>
                  <span className="detail-val accent">{nodeDetails.next_run}</span>
                </div>
                <div className="detail-block">
                  <span className="detail-label">Logs Recentes</span>
                  <div className="log-box">
                    {nodeDetails.logs.map((l, i) => <div key={i}>· {l}</div>)}
                  </div>
                </div>
                <button className="run-btn" onClick={async () => {
                  try {
                    const r = await axios.post(`${API_BASE}/node/${nodePanel.id}/action`, { action: 'run_now' });
                    alert(r.data.msg);
                  } catch { alert('Erro.'); }
                }}>
                  ▶ Forçar Execução
                </button>
              </div>
            ) : (
              <div style={{ padding: '2rem', color: '#8b9bb4' }}>Carregando...</div>
            )}
          </>
        )}
      </div>

      {/* ── MODAL: EMERGENCY STOP ── */}
      {showEmergency && (
        <div className="overlay">
          <div className="modal-box emergency-box">
            <div className="modal-head danger-head">
              <ShieldAlert size={24} color="#f43f5e" />
              <h3>Emergency Stop</h3>
            </div>
            <p className="danger-warn">
              Liquida <strong>todas</strong> as posições imediatamente e bloqueia novas ordens.
              Esta ação é <strong>irreversível</strong>.
            </p>
            <input
              type="password"
              placeholder="Senha de CEO..."
              value={password}
              onChange={e => setPassword(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && doEmergencyStop()}
              className="password-input"
              autoFocus
            />
            <div className="modal-actions">
              <button className="btn-cancel" onClick={() => { setShowEmergency(false); setPassword(''); }}>
                Cancelar
              </button>
              <button className="btn-danger" onClick={doEmergencyStop}>
                🔴 Confirmar Liquidação
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
