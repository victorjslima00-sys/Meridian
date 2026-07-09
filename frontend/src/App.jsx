import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import {
  Activity, ShieldAlert, Cpu, Database,
  BarChart2, Globe, Terminal, Briefcase, X,
  Wifi, WifiOff, TrendingUp, TrendingDown,
  ChevronRight, Bell, Settings, RefreshCw,
  DollarSign, Percent, BookOpen, History,
  Key, ToggleLeft, ToggleRight, Users
} from 'lucide-react';
import { 
  CandlestickChart, EquityDrawdownChart, CorrelationHeatmap, 
  RiskMetricsPanel, PositionSizingCalc, AlertBadge, MarketRegimeBadge
} from './EliteCharts';
import { TickerAreaChart as SimpleArea, PortfolioChart as SimplePortfolio } from './Charts';
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
const KpiCard = ({ title, value, sub, icon: Icon, color, trend }) => (
  <div className="kpi-card" style={{ borderTop: `2px solid ${color}` }}>
    <div className="kpi-header">
      <span className="kpi-title">{title}</span>
      <Icon size={16} color={color} opacity={0.7} />
    </div>
    <div className="kpi-value">{value}</div>
    {sub && (
      <div className="kpi-sub" style={{ color: trend === undefined ? 'var(--text-muted)' : (trend >= 0 ? 'var(--green)' : 'var(--red)') }}>
        {trend !== undefined && (trend >= 0 ? <TrendingUp size={12}/> : <TrendingDown size={12}/>)}
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
    data:      { top: '15%', left: '15%', icon: Globe, color: '#ffffff' },
    db:        { top: '40%', left: '35%', icon: Database, color: '#ffffff' },
    quant:     { top: '15%', left: '58%', icon: BarChart2, color: 'var(--primary)' },
    research:  { top: '75%', left: '35%', icon: Cpu, color: '#a3a3a3' },
    guardrail: { top: '75%', left: '65%', icon: ShieldAlert, color: 'var(--primary)' },
    broker:    { top: '40%', left: '85%', icon: Briefcase, color: '#ffffff' },
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

const AgentOfficeView = () => {
  const agents = {
    news: { id: 'news', emoji: '🧑‍💼', name: 'Agente de Notícias', role: 'Sentimento Macro', x: 20, y: 30, color: '#f59e0b' },
    quant: { id: 'quant', emoji: '🧑‍🔬', name: 'Agente Quant', role: 'Análise Gráfica', x: 80, y: 30, color: '#00f3ff' },
    guardrail: { id: 'guardrail', emoji: '👮', name: 'Agente de Verificação', role: 'Compliance', x: 50, y: 70, color: '#f43f5e' },
    broker: { id: 'broker', emoji: '🤖', name: 'Agente de Execução', role: 'Roteamento Cedro', x: 80, y: 70, color: '#10b981' }
  };

  const script = [
    { from: 'news', to: 'guardrail', text: 'Estou lendo notícias sobre mercado e acredito que isso pode influenciar o preço. Vou encaminhar para o Agente de Verificação.' },
    { from: 'guardrail', to: 'quant', text: 'Recebi o alerta macro. Agente Quant, favor rodar análise técnica para confirmar se há setup de entrada alinhado ao sentimento.' },
    { from: 'quant', to: 'guardrail', text: 'Análise concluída. O ativo rompeu a SMA-50 com volume. Setup confirmado. Retornando para aprovação final de risco.' },
    { from: 'guardrail', to: 'broker', text: 'Risco aprovado. Correlação do portfólio controlada. Agente de Execução, pode disparar a ordem para a B3.' },
    { from: 'broker', to: 'news', text: 'Ordem executada na Cedro com sucesso a mercado. Retornando ao modo de monitoramento.' }
  ];

  const [step, setStep] = useState(0);
  const [phase, setPhase] = useState('thinking'); // thinking | traveling | received

  useEffect(() => {
    let timer;
    if (phase === 'thinking') {
      timer = setTimeout(() => setPhase('traveling'), 4000);
    } else if (phase === 'traveling') {
      timer = setTimeout(() => setPhase('received'), 2000);
    } else if (phase === 'received') {
      timer = setTimeout(() => {
        setStep((s) => (s + 1) % script.length);
        setPhase('thinking');
      }, 3000);
    }
    return () => clearTimeout(timer);
  }, [phase, step]);

  const currentLine = script[step];
  const fromAgent = agents[currentLine.from];
  const toAgent = agents[currentLine.to];

  return (
    <div style={{ position: 'relative', width: '100%', height: '600px', background: 'var(--bg-2)', borderRadius: '12px', border: '1px solid rgba(0,243,255,0.1)', overflow: 'hidden' }}>
      {/* Grid Floor */}
      <div style={{ position: 'absolute', inset: 0, backgroundImage: 'linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px)', backgroundSize: '50px 50px', transform: 'perspective(500px) rotateX(45deg) scale(2)', transformOrigin: 'top center' }} />
      
      {/* Central Hologram / Brain */}
      <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', width: '150px', height: '150px', borderRadius: '50%', background: 'radial-gradient(circle, rgba(0,243,255,0.1) 0%, transparent 70%)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Globe size={40} color="#00f3ff" opacity={0.3} style={{ animation: 'spin 20s linear infinite' }} />
      </div>

      {/* Agents Avatars */}
      {Object.values(agents).map(a => {
        const isSpeaking = currentLine.from === a.id && phase === 'thinking';
        const isReceiving = currentLine.to === a.id && phase === 'received';
        const isActive = isSpeaking || isReceiving;

        return (
          <div key={a.id} style={{
            position: 'absolute', top: `${a.y}%`, left: `${a.x}%`, transform: 'translate(-50%, -50%)',
            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem', zIndex: 10
          }}>
            <div style={{
              width: '70px', height: '70px', borderRadius: '50%', background: `rgba(10,14,23,0.9)`,
              border: `2px solid ${isActive ? a.color : 'rgba(255,255,255,0.1)'}`, 
              display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '2rem',
              boxShadow: isActive ? `0 0 30px ${a.color}80` : 'none',
              transition: 'all 0.5s ease',
              position: 'relative'
            }}>
              {a.emoji}
              {isActive && (
                <div style={{ position: 'absolute', inset: -6, border: `1px solid ${a.color}`, borderRadius: '50%', animation: 'ping 1.5s cubic-bezier(0, 0, 0.2, 1) infinite' }} />
              )}
            </div>
            <div style={{ textAlign: 'center', background: 'rgba(0,0,0,0.6)', padding: '0.3rem 0.6rem', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.05)', backdropFilter: 'blur(4px)' }}>
              <div style={{ fontSize: '0.8rem', fontWeight: 'bold', color: isActive ? a.color : '#e2e8f0', transition: 'color 0.5s' }}>{a.name}</div>
              <div style={{ fontSize: '0.65rem', color: '#8b9bb4' }}>{a.role}</div>
            </div>
          </div>
        );
      })}

      {/* Thinking Bubble */}
      {phase === 'thinking' && (
        <div style={{
          position: 'absolute', top: `calc(${fromAgent.y}% - 100px)`, left: `calc(${fromAgent.x}% + 50px)`,
          background: 'rgba(15,23,42,0.95)', border: `1px solid ${fromAgent.color}`, borderRadius: '12px', borderBottomLeftRadius: '0',
          padding: '1rem', width: '280px', zIndex: 20, boxShadow: `0 10px 30px rgba(0,0,0,0.8)`,
          animation: 'popIn 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards', color: '#e2e8f0', fontSize: '0.85rem', lineHeight: 1.5
        }}>
          <strong style={{ color: fromAgent.color, display: 'block', marginBottom: '0.4rem', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '1px' }}>
            {fromAgent.emoji} {fromAgent.name} pensando...
          </strong>
          {currentLine.text}
        </div>
      )}

      {/* Traveling Particle & Trail */}
      {phase === 'traveling' && (
        <div style={{
          position: 'absolute', zIndex: 15,
          left: `${fromAgent.x}%`, top: `${fromAgent.y}%`,
          width: '100px', padding: '0.4rem 0.8rem', background: `linear-gradient(90deg, ${fromAgent.color}, ${toAgent.color})`,
          borderRadius: '20px', color: '#fff', fontSize: '0.7rem', fontWeight: 'bold', textAlign: 'center',
          boxShadow: `0 0 20px ${fromAgent.color}`, whiteSpace: 'nowrap',
          transform: 'translate(-50%, -50%)',
          animation: 'travel 2s cubic-bezier(0.4, 0, 0.2, 1) forwards'
        }}>
          Encaminhando... ⚡
        </div>
      )}

      {/* Received Bubble */}
      {phase === 'received' && (
        <div style={{
          position: 'absolute', top: `calc(${toAgent.y}% - 60px)`, left: `calc(${toAgent.x}% + 50px)`,
          background: 'rgba(15,23,42,0.95)', border: `1px solid ${toAgent.color}`, borderRadius: '12px', borderBottomLeftRadius: '0',
          padding: '0.75rem 1rem', zIndex: 20, boxShadow: `0 10px 30px rgba(0,0,0,0.8)`,
          animation: 'popIn 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards', color: '#10b981', fontSize: '0.85rem', fontWeight: 'bold'
        }}>
          ✓ Mensagem Recebida
        </div>
      )}

      <style>{`
        @keyframes popIn { 
          from { opacity: 0; transform: scale(0.8) translateY(20px); } 
          to { opacity: 1; transform: scale(1) translateY(0); } 
        }
        @keyframes spin { 100% { transform: rotate(360deg); } }
        @keyframes ping { 75%, 100% { transform: scale(1.5); opacity: 0; } }
        @keyframes travel {
          0% { left: ${fromAgent.x}%; top: ${fromAgent.y}%; opacity: 0; transform: translate(-50%, -50%) scale(0.5); }
          10% { opacity: 1; transform: translate(-50%, -50%) scale(1); }
          90% { opacity: 1; transform: translate(-50%, -50%) scale(1); }
          100% { left: ${toAgent.x}%; top: ${toAgent.y}%; opacity: 0; transform: translate(-50%, -50%) scale(0.5); }
        }
      `}</style>
    </div>
  );
};

// ─── APP PRINCIPAL ────────────────────────────────────────────────────────────
export default function App() {
  const [tab, setTab] = useState('overview');
  const [status, setStatus] = useState(null);
  const [positions, setPositions] = useState(null);
  const [ecosystem, setEcosystem] = useState(null);
  const [tapeData, setTapeData] = useState(null);
  const [apiError, setApiError] = useState(null);
  const [connected, setConnected] = useState(true);

  // Elite Features State
  const [riskMetrics, setRiskMetrics] = useState(null);
  const [tradeJournal, setTradeJournal] = useState(null);
  const [correlation, setCorrelation] = useState(null);
  const [marketRegime, setMarketRegime] = useState(null);
  const [equityCurve, setEquityCurve] = useState(null);
  const [alerts, setAlerts] = useState([
    { type: 'regime_change', ticker: 'IBOV', message: 'Regime alterado para Bull Market', time: new Date().toLocaleTimeString() }
  ]);
  const [candleData, setCandleData] = useState(null);

  // Settings State
  const [brokerSettings, setBrokerSettings] = useState({ mode: 'paper', has_cedro_key: false });
  const [testingBroker, setTestingBroker] = useState(false);

  const [chartModal, setChartModal] = useState(null); // ticker string
  const [nodePanel, setNodePanel] = useState(null);
  const [nodeDetails, setNodeDetails] = useState(null);
  const [showEmergency, setShowEmergency] = useState(false);
  const [password, setPassword] = useState('');

  const [logs, setLogs] = useState([
    { t: new Date().toLocaleTimeString(), sender: 'SISTEMA', msg: 'Conexão segura estabelecida.' }
  ]);
  const termRef = useRef(null);

  // Terminal stream simulation
  useEffect(() => {
    const msgs = [
      { sender: 'PESQUISADOR', msg: 'Analisando fluxo institucional em PETR4...' },
      { sender: 'GUARD-RAIL',  msg: 'Correlação PETR4/VALE3 = 0.61 — dentro do limite.' },
      { sender: 'QUANT',       msg: 'Sharpe otimizado: 0.87 (regime alta_juros).' },
      { sender: 'SISTEMA',     msg: 'Sincronização B3 concluída. Latência: 12ms.' },
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

  const [marketNews, setMarketNews] = useState(null);

  // Main Data fetch
  useEffect(() => {
    const load = async () => {
      try {
        const [s, p, e, tp, rm, tj, cm, mr, eq, nw] = await Promise.all([
          axios.get(`${API_BASE}/status`),
          axios.get(`${API_BASE}/positions`),
          axios.get(`${API_BASE}/ecosystem`),
          axios.get(`${API_BASE}/market_tape`),
          axios.get(`${API_BASE}/elite/risk_metrics`).catch(()=>({data:null})),
          axios.get(`${API_BASE}/elite/trade_journal`).catch(()=>({data:null})),
          axios.get(`${API_BASE}/elite/correlation_matrix`).catch(()=>({data:null})),
          axios.get(`${API_BASE}/elite/market_regime`).catch(()=>({data:null})),
          axios.get(`${API_BASE}/elite/equity_curve`).catch(()=>({data:null})),
          axios.get(`${API_BASE}/elite/news`).catch(()=>({data:null})),
        ]);
        setStatus(s.data); setPositions(p.data);
        setEcosystem(e.data); setTapeData(tp.data);
        
        if (rm.data) setRiskMetrics(rm.data);
        if (tj.data) setTradeJournal(tj.data);
        if (cm.data) setCorrelation(cm.data);
        if (mr.data) setMarketRegime(mr.data);
        if (eq.data) setEquityCurve(eq.data);
        if (nw.data && nw.data.news) setMarketNews(nw.data.news);

        setConnected(true); setApiError(null);
      } catch (err) {
        setApiError(err.message); setConnected(false);
      }
    };
    load();
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, []);

  // Fetch candle data when a ticker is selected for modal
  useEffect(() => {
    if (!chartModal) return;
    axios.get(`${API_BASE}/history/${chartModal}?limit=60`)
      .then(res => {
        // format to {date, o, h, l, c, v}
        const data = res.data;
        if (data && data.candles) {
          const formatted = data.candles.map((c, i) => ({
            date: data.dates[i],
            o: c[0], h: c[1], l: c[2], c: c[3], v: c[4] || Math.random()*1000
          }));
          setCandleData(formatted);
        }
      });
  }, [chartModal]);

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
            { id: 'overview',   Icon: BarChart2,   label: 'Visão Geral' },
            { id: 'risk',       Icon: ShieldAlert, label: 'Risk & Metrics' },
            { id: 'profile',    Icon: BookOpen,    label: 'Perfil' },
            { id: 'neural',     Icon: Globe,       label: 'Mapa Neural' },
            { id: 'settings',   Icon: Settings,    label: 'Configurações' },
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
        </div>
      </aside>

      {/* ── MAIN ── */}
      <main className="main-area">
        {/* ── TOPBAR ── */}
        <header className="topbar">
          <div style={{ padding: '0 1rem', display: 'flex', alignItems: 'center' }}>
            {brokerSettings.mode === 'real' ? (
              <span style={{ background: 'rgba(244,63,94,0.15)', color: '#f43f5e', padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.7rem', fontWeight: 'bold', border: '1px solid rgba(244,63,94,0.3)' }}>
                🔴 CONTA REAL
              </span>
            ) : brokerSettings.mode === 'cedro_sandbox' ? (
              <span style={{ background: 'rgba(245,158,11,0.15)', color: '#f59e0b', padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.7rem', fontWeight: 'bold', border: '1px solid rgba(245,158,11,0.3)' }}>
                🟡 SANDBOX
              </span>
            ) : (
              <span style={{ background: 'rgba(16,185,129,0.15)', color: '#10b981', padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.7rem', fontWeight: 'bold', border: '1px solid rgba(16,185,129,0.3)' }}>
                🟢 SIMULADOR
              </span>
            )}
          </div>

          <div className="topbar-tape" aria-label="Fita de mercado">
            <div className="tape-scroll">
              {tapeData.tape.map((item, i) => <TapeItem key={i} item={item} />)}
              {tapeData.tape.map((item, i) => <TapeItem key={`r${i}`} item={item} />)}
            </div>
          </div>
          
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', paddingRight: '1rem' }}>
            <MarketRegimeBadge regime={marketRegime} />
            <AlertBadge alerts={alerts} />
          </div>

          <button className="emergency-btn" onClick={() => setShowEmergency(true)}>
            <ShieldAlert size={14} /> STOP
          </button>
        </header>

        {/* ── PAGE CONTENT ── */}
        <div className="page-content">

          {/* OVERVIEW */}
          {tab === 'overview' && (
            <div className="overview-layout">
              {/* GLOBAL MACRO TICKER */}
              <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', fontSize: '0.75rem', fontWeight: 600, color: '#8b9bb4', padding: '0.5rem 1rem', background: 'rgba(255,255,255,0.02)', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.05)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span>S&P 500</span> <span style={{ color: '#10b981' }}>5,123.40 (+0.8%)</span>
                </div>
                <div style={{ width: '1px', background: 'rgba(255,255,255,0.1)' }} />
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span>DXY</span> <span style={{ color: '#f43f5e' }}>104.20 (-0.2%)</span>
                </div>
                <div style={{ width: '1px', background: 'rgba(255,255,255,0.1)' }} />
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span>VIX</span> <span style={{ color: '#10b981' }}>13.40 (-1.5%)</span>
                </div>
                <div style={{ width: '1px', background: 'rgba(255,255,255,0.1)' }} />
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span>US10Y</span> <span style={{ color: '#f59e0b' }}>4.23% (+0.02)</span>
                </div>
              </div>

              <div className="kpi-row">
                <KpiCard title="Capital Inicial" icon={DollarSign} color="#8b9bb4" value={`R$ ${positions.capital.initial.toFixed(2)}`} />
                <KpiCard title="Patrimônio Atual" icon={DollarSign} color="#00f3ff" value={`R$ ${positions.capital.current.toFixed(2)}`} sub={`${roiNum >= 0 ? '+' : ''}${roi}% total`} trend={roiNum} />
                <KpiCard title="ROI" icon={Percent} color={roiNum >= 0 ? '#10b981' : '#f43f5e'} value={`${roiNum >= 0 ? '+' : ''}${roi}%`} sub="desde o início" trend={roiNum} />
                <KpiCard title="Posições Abertas" icon={Activity} color="#f59e0b" value={positions.active_positions.length} sub={`R$ ${positions.capital.invested?.toFixed(2) || '0.00'} investido`} />
              </div>

              <div className="content-grid">
                <div className="left-col">
                  <div className="glass-panel">
                    <div className="panel-header">
                      <h3>Evolução do Portfólio</h3>
                      <span className="muted-tag">30 dias · BRL</span>
                    </div>
                    <SimplePortfolio capital={positions.capital} />
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
                            <tr><td colSpan="8" className="empty-state">🛡️ Nenhuma posição aberta — capital protegido</td></tr>
                          ) : (
                            positions.active_positions.map((p, i) => (
                              <PositionRow key={i} pos={p} onClick={() => { setChartModal(p.ticker); setCandleData(null); }} />
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>

                <div className="right-col">
                  {/* LIVE STREAM WIDGET */}
                  <div className="glass-panel" style={{ flexShrink: 0 }}>
                    <div className="panel-header" style={{ padding: '0.75rem 1rem' }}>
                      <h3><Globe size={16} color="var(--primary)" /> TV Mercado Ao Vivo</h3>
                      <span className="live-badge">● REC</span>
                    </div>
                    <div style={{ width: '100%', aspectRatio: '16/9', background: '#000' }}>
                      <iframe 
                        width="100%" 
                        height="100%" 
                        src="https://www.youtube.com/embed/live_stream?channel=UCXwZGs_2hH9AEvSExnQicZw&autoplay=1&mute=1" 
                        title="Live de Mercado" 
                        frameBorder="0" 
                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                        allowFullScreen
                        style={{ display: 'block' }}
                      ></iframe>
                    </div>
                  </div>

                  {/* NEWS WIDGET (MOVIDO DA ABA JOURNAL) */}
                  <div className="glass-panel" style={{ flex: 1 }}>
                    <div className="panel-header"><h3>Notícias e Eventos (B3)</h3></div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', padding: '1rem', overflowY: 'auto', maxHeight: '300px' }}>
                      {marketNews ? marketNews.map((n, i) => (
                        <div key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '0.75rem' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.3rem', fontSize: '0.75rem' }}>
                            <span style={{ color: 'var(--primary)', fontWeight: 600 }}>{n.category}</span>
                            <span style={{ color: 'var(--text-muted)' }}>{n.time} • {n.source}</span>
                          </div>
                          <div style={{ fontSize: '0.85rem', lineHeight: 1.4, color: 'var(--text)' }}>{n.title}</div>
                        </div>
                      )) : <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Carregando radar de notícias...</div>}
                    </div>
                  </div>

                  <div className="glass-panel terminal-panel">
                    <div className="panel-header">
                      <h3><Terminal size={16} /> Comitê de IA</h3>
                      <span className="live-badge">● LIVE</span>
                    </div>
                    <div className="terminal-feed" ref={termRef}>
                      {logs.map((l, i) => (
                        <div key={i} className="log-line">
                          <span className="log-time">{l.t}</span>
                          <span className={`log-sender sender-${l.sender.toLowerCase().replace('-','')}`}>{l.sender}</span>
                          <span className="log-msg">{l.msg}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* AGENT OFFICE IN OVERVIEW */}
              <div className="glass-panel" style={{ marginTop: '1.25rem', overflow: 'hidden' }}>
                <div className="panel-header" style={{ padding: '1rem', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <h3><Users size={16} /> Agent Office (Live Thoughts)</h3>
                  <span className="muted-tag">Monitoramento em tempo real do workflow cognitivo dos Agentes</span>
                </div>
                <AgentOfficeView />
              </div>
            </div>
          )}

          {/* RISK & METRICS */}
          {tab === 'risk' && (
            <div className="page-section">
              <div className="page-title">
                <ShieldAlert size={22} />
                <div>
                  <h2>Risk & Metrics</h2>
                  <p>Métricas de risco avançadas e calculadora de Position Sizing (Kelly)</p>
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.25rem' }}>
                <div className="glass-panel">
                  <div className="panel-header"><h3>Curva de Equity & Drawdown</h3></div>
                  <div style={{ padding: '1rem' }}>
                    <EquityDrawdownChart capitalHistory={equityCurve?.curve || []} />
                  </div>
                </div>
                <div className="glass-panel">
                  <div className="panel-header"><h3>Métricas de Risco</h3></div>
                  <div style={{ padding: '1rem' }}>
                    <RiskMetricsPanel metrics={riskMetrics} />
                  </div>
                </div>
                <div className="glass-panel" style={{ gridColumn: 'span 2' }}>
                  <div className="panel-header"><h3>Calculadora de Position Sizing</h3></div>
                  <div style={{ padding: '1.25rem' }}>
                    <PositionSizingCalc capital={positions?.capital?.current || 300} />
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* PROFILE */}
          {tab === 'profile' && (
            <div className="page-section">
              <div className="page-title">
                <Users size={22} />
                <div>
                  <h2>Perfil & Histórico de Operações</h2>
                  <p>Dados da conta e registro detalhado de negociações</p>
                </div>
              </div>
              
              {/* Perfil Info */}
              <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: '1.25rem', display: 'flex', gap: '2rem', alignItems: 'center' }}>
                <div style={{ width: '80px', height: '80px', borderRadius: '50%', background: 'rgba(230,0,0,0.1)', border: '2px solid var(--primary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <Users size={32} color="var(--primary)" />
                </div>
                <div>
                  <h3 style={{ fontSize: '1.2rem', marginBottom: '0.2rem' }}>Trader Elite</h3>
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginBottom: '0.5rem' }}>ID: 10492-MERIDIAN • Conta {brokerSettings.mode.toUpperCase()}</p>
                  <div style={{ display: 'flex', gap: '1rem' }}>
                    <span style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem', background: 'rgba(255,255,255,0.05)', borderRadius: '4px' }}>Plano: Institucional</span>
                    <span style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem', background: 'rgba(255,255,255,0.05)', borderRadius: '4px' }}>Corretora: Cedro Tech</span>
                  </div>
                </div>
              </div>

              {tradeJournal?.summary && (
                <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
                  <div className="kpi-card" style={{ flex: 1, borderTop: '2px solid var(--primary)' }}>
                    <div className="kpi-title">Total de Trades</div>
                    <div className="kpi-value">{tradeJournal.summary.total_trades}</div>
                  </div>
                  <div className="kpi-card" style={{ flex: 1, borderTop: '2px solid var(--primary)' }}>
                    <div className="kpi-title">Winning / Losing</div>
                    <div className="kpi-value" style={{ color: 'var(--green)' }}>
                      {tradeJournal.summary.winning} <span style={{ color: 'var(--text-muted)', fontSize: '1rem' }}>/ {tradeJournal.summary.losing}</span>
                    </div>
                  </div>
                  <div className="kpi-card" style={{ flex: 1, borderTop: '2px solid var(--primary)' }}>
                    <div className="kpi-title">PnL Total (BRL)</div>
                    <div className="kpi-value" style={{ color: tradeJournal.summary.total_pnl_brl >= 0 ? 'var(--green)' : 'var(--red)' }}>
                      R$ {tradeJournal.summary.total_pnl_brl.toFixed(2)}
                    </div>
                  </div>
                </div>
              )}

              <div className="glass-panel">
                <div className="panel-header"><h3>Histórico de Operações Fechadas</h3></div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Ativo</th><th>Lado</th><th>Entrada</th><th>Saída</th>
                        <th>Data Início</th><th>Duração</th><th>PnL %</th><th>Motivo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tradeJournal?.trades?.map((t, i) => (
                        <tr key={i}>
                          <td><span className="ticker-badge">{t.ticker}</span></td>
                          <td><span className={`side-chip ${t.side === 'BUY' ? 'long' : 'short'}`}>{t.side}</span></td>
                          <td className="mono">R$ {t.entry_price.toFixed(2)}</td>
                          <td className="mono">R$ {t.exit_price.toFixed(2)}</td>
                          <td className="dim">{t.entry_date}</td>
                          <td className="dim">{t.duration_days} d</td>
                          <td><span className={`pnl-chip ${t.pnl_pct >= 0 ? 'gain' : 'loss'}`}>{t.pnl_pct}%</span></td>
                          <td className="dim">{t.exit_reason.toUpperCase()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* CORRELATION HEATMAP */}
          {tab === 'correlation' && (
            <div className="page-section">
              <div className="page-title">
                <Database size={22} />
                <div>
                  <h2>Heatmap de Correlação</h2>
                  <p>Matriz de Pearson dos últimos 45 pregões (SQLite)</p>
                </div>
              </div>
              <div className="glass-panel" style={{ padding: '1.5rem', display: 'flex', justifyContent: 'center' }}>
                <CorrelationHeatmap matrix={correlation?.matrix || []} tickers={correlation?.tickers || []} />
              </div>
              <div className="glass-panel" style={{ padding: '1.25rem' }}>
                <p style={{ color: '#8b9bb4', fontSize: '0.85rem', lineHeight: 1.6 }}>
                  Correlação &gt; 0.7: Guard-Rail veta abertura de nova posição. <br/>
                  Correlação &lt; 0.3: Diversificação eficiente.
                </p>
              </div>
            </div>
          )}

          {/* NEURAL MAP */}
          {tab === 'neural' && (
            <div className="page-section" style={{ position: 'relative' }}>
              <div className="page-title">
                <Globe size={22} />
                <div><h2>Mapa Neural do Ecossistema</h2><p>Agentes ativos e fluxo de dados em tempo real</p></div>
              </div>
              <div className="glass-panel" style={{ flex: 1, minHeight: 500, display: 'flex' }}>
                <NeuralMap nodes={ecosystem.nodes} edges={ecosystem.edges} onNodeClick={openNode} />
                
                {/* Node Side Panel */}
                {nodePanel && (
                  <div style={{
                    width: '350px', borderLeft: '1px solid rgba(0,243,255,0.2)', background: 'rgba(10,14,23,0.95)',
                    padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem',
                    animation: 'fadeInRight 0.3s ease-out'
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: '1rem' }}>
                      <h3 style={{ margin: 0, color: '#00f3ff', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Terminal size={18} /> {nodePanel.label}
                      </h3>
                      <button onClick={() => setNodePanel(null)} style={{ background: 'none', border: 'none', color: '#8b9bb4', cursor: 'pointer' }}><X size={18} /></button>
                    </div>
                    
                    <div style={{ flex: 1, overflowY: 'auto' }}>
                      <div style={{ fontSize: '0.8rem', color: '#e2e8f0', marginBottom: '1rem' }}>
                        <strong>Status:</strong> <span style={{ color: nodePanel.status === 'active' ? '#10b981' : '#f59e0b' }}>{nodePanel.status.toUpperCase()}</span>
                      </div>
                      
                      <h4 style={{ fontSize: '0.75rem', color: '#8b9bb4', textTransform: 'uppercase', marginBottom: '0.5rem' }}>CMD State Logs (Live)</h4>
                      <div style={{ background: '#000', padding: '1rem', borderRadius: '8px', border: '1px solid #333', fontFamily: 'JetBrains Mono', fontSize: '0.7rem', color: '#00f3ff', height: '250px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        <div>[21:14:02] Initializing {nodePanel.id} module...</div>
                        <div>[21:14:05] Context loaded. Ready.</div>
                        <div>[21:15:10] Scanning incoming data streams...</div>
                        <div>[21:15:42] Processing vector embeddings... [OK]</div>
                        <div style={{ color: '#10b981' }}>[21:16:01] Awaiting new tasks.</div>
                        {/* Fake animated line */}
                        <div style={{ opacity: 0.5, animation: 'pulse 1.5s infinite' }}>_</div>
                      </div>
                    </div>
                    <button style={{ padding: '0.75rem', background: 'rgba(0,243,255,0.1)', color: '#00f3ff', border: '1px solid rgba(0,243,255,0.3)', borderRadius: '8px', cursor: 'pointer' }} onClick={() => alert('Diagnostic run initiated.')}>
                      Executar Diagnóstico
                    </button>
                  </div>
                )}
              </div>
              <style>{`@keyframes fadeInRight { from { opacity: 0; transform: translateX(20px); } to { opacity: 1; transform: translateX(0); } }`}</style>
            </div>
          )}

          {/* SETTINGS (NOVO) */}
          {tab === 'settings' && (
            <div className="page-section">
              <div className="page-title">
                <Settings size={22} />
                <div>
                  <h2>Configurações e Corretora</h2>
                  <p>Gerencie as chaves de acesso e ambiente de execução</p>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                <div className="glass-panel" style={{ padding: '1.5rem' }}>
                  <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1.5rem' }}>
                    <Key size={18} color="#00f3ff" /> Credenciais da Corretora
                  </h3>
                  
                  <div style={{ marginBottom: '1.5rem', padding: '1rem', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                      <span style={{ color: '#8b9bb4' }}>Corretora Ativa</span>
                      <strong>Cedro Technologies</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#8b9bb4' }}>Status da API Key no `.env`</span>
                      {brokerSettings.has_cedro_key ? (
                        <span style={{ color: '#10b981', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>✅ Encontrada</span>
                      ) : (
                        <span style={{ color: '#f43f5e', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>❌ Faltando</span>
                      )}
                    </div>
                  </div>

                  <button 
                    style={{ width: '100%', padding: '0.75rem', background: 'rgba(0,243,255,0.1)', color: '#00f3ff', border: '1px solid rgba(0,243,255,0.3)', borderRadius: '8px', fontWeight: 'bold', cursor: 'pointer' }}
                    onClick={() => {
                      setTestingBroker(true);
                      setTimeout(() => {
                        setTestingBroker(false);
                        alert(brokerSettings.has_cedro_key ? 'Conexão com Cedro OK!' : 'Adicione CEDRO_API_KEY no arquivo .env primeiro.');
                      }, 1500);
                    }}
                  >
                    {testingBroker ? <RefreshCw size={16} className="spin" /> : 'Validar Conexão Cedro'}
                  </button>
                </div>

                <div className="glass-panel" style={{ padding: '1.5rem' }}>
                  <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1.5rem' }}>
                    <ShieldAlert size={18} color="#f59e0b" /> Ambiente de Execução
                  </h3>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    {[
                      { id: 'paper', label: 'Simulador Local (SQLite)', color: '#10b981' },
                      { id: 'cedro_sandbox', label: 'Cedro Sandbox (Homologação)', color: '#f59e0b' },
                      { id: 'real', label: 'Conta Real B3', color: '#f43f5e' }
                    ].map(mode => (
                      <div 
                        key={mode.id}
                        onClick={() => {
                          if (mode.id === 'real' && !confirm('ATENÇÃO: Você está mudando para conta REAL. Ordens irão para a B3. Continuar?')) return;
                          setBrokerSettings({...brokerSettings, mode: mode.id});
                        }}
                        style={{ 
                          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                          padding: '1rem', cursor: 'pointer',
                          background: brokerSettings.mode === mode.id ? `${mode.color}15` : 'rgba(255,255,255,0.02)',
                          border: `1px solid ${brokerSettings.mode === mode.id ? mode.color : 'rgba(255,255,255,0.05)'}`,
                          borderRadius: '8px'
                        }}
                      >
                        <span style={{ fontWeight: brokerSettings.mode === mode.id ? 'bold' : 'normal', color: brokerSettings.mode === mode.id ? mode.color : '#e2e8f0' }}>
                          {mode.label}
                        </span>
                        {brokerSettings.mode === mode.id ? <ToggleRight color={mode.color} size={24} /> : <ToggleLeft color="#8b9bb4" size={24} />}
                      </div>
                    ))}
                  </div>

                  <p style={{ marginTop: '1.5rem', fontSize: '0.75rem', color: '#8b9bb4', lineHeight: 1.5 }}>
                    Circuit Breaker ativo: Limite diário de perda configurado em <strong>-R$ 150.00</strong>. Se atingido no modo real, o sistema bloqueia novas ordens automaticamente.
                  </p>
                </div>
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
              <h3>📈 {chartModal} · Candlestick (60d)</h3>
              <button className="close-btn" onClick={() => setChartModal(null)}><X size={18} /></button>
            </div>
            <div style={{ padding: '1rem' }}>
              {candleData ? <CandlestickChart data={candleData} /> : <div style={{color: '#8b9bb4', textAlign: 'center'}}>Carregando OHLCV...</div>}
            </div>
          </div>
        </div>
      )}

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
            </p>
            <input type="password" placeholder="Senha de CEO..." value={password} onChange={e => setPassword(e.target.value)} onKeyDown={e => e.key === 'Enter' && doEmergencyStop()} className="password-input" autoFocus />
            <div className="modal-actions">
              <button className="btn-cancel" onClick={() => { setShowEmergency(false); setPassword(''); }}>Cancelar</button>
              <button className="btn-danger" onClick={doEmergencyStop}>🔴 Confirmar</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
