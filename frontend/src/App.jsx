import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import {
  Activity, ShieldAlert, Cpu, Database,
  BarChart2, Globe, Terminal, Briefcase, X,
  Wifi, WifiOff, TrendingUp, TrendingDown,
  ChevronRight, Bell, Settings, RefreshCw,
  DollarSign, Percent, BookOpen, History,
  Key, ToggleLeft, ToggleRight, Users, Menu, Bot, Send, BrainCircuit
} from 'lucide-react';
import { 
  CandlestickChart, EquityDrawdownChart, CorrelationHeatmap, 
  RiskMetricsPanel, PositionSizingCalc, AlertBadge, MarketRegimeBadge,
  MarketHeatmap, EconomicCalendar, DepthOfMarket, AcademyWidget, FastExecutionWidget,
  MonteCarloChart
} from './EliteCharts';
import AIFlow from './AIFlow';
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
  <div className="kpi-card" style={{ '--kpi-color': color, '--kpi-color-alpha': `${color}15`, '--kpi-border-alpha': `${color}30` }}>
    <div className="kpi-header">
      <span className="kpi-title">{title}</span>
      <div className="kpi-icon-wrap">
        <Icon size={16} color={color} />
      </div>
    </div>
    <div className="kpi-value">{value}</div>
    {sub && (
      <div className="kpi-sub" style={{ color: trend === undefined ? 'var(--text-muted)' : (trend >= 0 ? '#10b981' : '#f43f5e') }}>
        {trend !== undefined && (trend >= 0 ? <TrendingUp size={14}/> : <TrendingDown size={14}/>)}
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

// ─── AUDIO SYSTEM ─────────────────────────────────────────────────────────────
const playTone = (freq, type, duration, vol) => {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, ctx.currentTime);
    gain.gain.setValueAtTime(vol, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + duration);
  } catch (e) {}
};

const playDing = () => {
  playTone(800, 'sine', 0.1, 0.1);
  setTimeout(() => playTone(1200, 'sine', 0.4, 0.15), 100);
};

const playBeep = () => {
  playTone(300, 'square', 0.1, 0.1);
  setTimeout(() => playTone(300, 'square', 0.2, 0.1), 150);
};

// ─── AI ECOSYSTEM DASHBOARD ───────────────────────────────────────────────────
const AIEcosystemDashboard = () => {
  const departments = [
    {
      name: "Alocação & Wealth (24/7)",
      icon: "🌍",
      agents: [
        { name: "O Criador", role: "Alpha Seeker", status: "ONLINE 24/7", cpu: 85, ram: 92, task: "Analisando liquidez em Crypto (BTC/ETH) e FIIs para balanceamento de carteira de longo prazo." },
        { name: "Guardião", role: "Risk Manager", status: "ONLINE 24/7", cpu: 30, ram: 45, task: "Calculando Drawdown e ajustando Position Sizing via Kelly Criterion." }
      ]
    },
    {
      name: "Engenharia de Software & MLOps",
      icon: "⚙️",
      agents: [
        { name: "Arquiteto", role: "Code Generator", status: "IDLE", cpu: 5, ram: 10, task: "Aguardando novas instruções de modelagem em Python." },
        { name: "Operário", role: "DevOps & Latency", status: "ONLINE", cpu: 40, ram: 55, task: "Otimizando websockets e reduzindo ping com a API da B3." }
      ]
    },
    {
      name: "Criação & Modelagem Quant",
      icon: "🔬",
      agents: [
        { name: "Minerador", role: "Alternative Data", status: "ONLINE", cpu: 65, ram: 80, task: "Raspando sentimento do Twitter e Reddit para correlação de ativos." },
        { name: "Simulador", role: "Backtest Engine", status: "PROCESSING", cpu: 98, ram: 100, task: "Rodando 10.000 simulações de Monte Carlo no IBOV histórico." }
      ]
    },
    {
      name: "Notícias & Macroeconomia",
      icon: "📰",
      agents: [
        { name: "Radar Global", role: "News Aggregator", status: "ONLINE", cpu: 22, ram: 30, task: "Acompanhando discursos do Fed e dados do IPCA-15 em tempo real." },
        { name: "Analista", role: "NLP Sentiment", status: "PROCESSING", cpu: 75, ram: 60, task: "Classificando impacto das notícias corporativas da VALE3 e PETR4." }
      ]
    },
    {
      name: "Supervisão & Compliance",
      icon: "👁️",
      agents: [
        { name: "Overlord", role: "Supervisor Principal", status: "ONLINE 24/7", cpu: 15, ram: 25, task: "Auditando as saídas de todos os agentes. Nenhuma anomalia detectada." },
        { name: "X-Ray", role: "Auditor de Execução", status: "SLEEP", cpu: 0, ram: 5, task: "Aguardando próxima janela de execução de ordens." }
      ]
    }
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div style={{ background: 'linear-gradient(90deg, rgba(16,185,129,0.1) 0%, rgba(0,0,0,0) 100%)', borderLeft: '4px solid #10b981', padding: '1.25rem', borderRadius: '4px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.3rem', fontWeight: 800, color: '#fff', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Activity size={20} color="#10b981" /> Ecossistema Neural Meridian
          </h2>
          <p style={{ margin: '0.25rem 0 0 0', color: 'var(--text-muted)', fontSize: '0.85rem' }}>Arquitetura multi-agente autônoma. Setores operando 24/7 de forma assíncrona.</p>
        </div>
        <div style={{ background: 'rgba(16,185,129,0.1)', border: '1px solid #10b981', color: '#10b981', padding: '0.5rem 1rem', borderRadius: '4px', fontWeight: 700, fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#10b981', boxShadow: '0 0 8px #10b981', animation: 'pulsePill 1.5s infinite' }}></div>
          CORE ONLINE
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: '1rem' }}>
        {departments.map((dept, i) => (
          <div key={i} className="glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="panel-header" style={{ padding: '0.75rem 1rem', borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(255,255,255,0.02)' }}>
              <span style={{ fontSize: '1.1rem' }}>{dept.icon}</span>
              <h3 style={{ margin: 0, fontSize: '0.9rem', color: '#fff' }}>{dept.name}</h3>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1px', background: 'rgba(255,255,255,0.05)', flex: 1 }}>
              {dept.agents.map((agent, j) => (
                <div key={j} style={{ padding: '1rem', background: 'var(--bg-2)', display: 'flex', flexDirection: 'column', gap: '0.75rem', flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.3rem' }}>
                        <span style={{ fontSize: '1rem', fontWeight: 800, color: '#fff' }}>{agent.name}</span>
                        <span style={{ fontSize: '0.65rem', background: 'rgba(0,243,255,0.1)', color: '#00f3ff', border: '1px solid rgba(0,243,255,0.2)', padding: '0.1rem 0.4rem', borderRadius: '2px', fontWeight: 700, textTransform: 'uppercase' }}>{agent.role}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.65rem', color: agent.status.includes('ONLINE') || agent.status === 'PROCESSING' ? '#10b981' : 'var(--text-muted)', fontWeight: 800 }}>
                        <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: agent.status.includes('ONLINE') || agent.status === 'PROCESSING' ? '#10b981' : '#64748b', boxShadow: agent.status.includes('ONLINE') ? '0 0 6px #10b981' : 'none' }}></div>
                        {agent.status}
                      </div>
                    </div>
                    
                    <div style={{ display: 'flex', gap: '0.75rem' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.2rem' }}>
                        <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)', fontWeight: 600 }}>CPU</span>
                        <div style={{ width: '30px', height: '4px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px', overflow: 'hidden' }}>
                          <div style={{ width: `${agent.cpu}%`, height: '100%', background: agent.cpu > 80 ? '#f43f5e' : (agent.cpu > 50 ? '#f59e0b' : '#10b981') }}></div>
                        </div>
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.2rem' }}>
                        <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)', fontWeight: 600 }}>RAM</span>
                        <div style={{ width: '30px', height: '4px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px', overflow: 'hidden' }}>
                          <div style={{ width: `${agent.ram}%`, height: '100%', background: agent.ram > 80 ? '#f43f5e' : (agent.ram > 50 ? '#f59e0b' : '#10b981') }}></div>
                        </div>
                      </div>
                    </div>
                  </div>
                  
                  <div style={{ background: '#000', padding: '0.6rem 0.75rem', borderRadius: '4px', border: '1px solid var(--border)', fontSize: '0.7rem', fontFamily: 'JetBrains Mono, monospace', color: 'var(--text-muted)', display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <span style={{ color: '#00f3ff', animation: 'pulsePill 1.5s infinite' }}>❯</span>
                    <span style={{ lineHeight: 1.4 }}>{agent.task}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// ─── APP PRINCIPAL ────────────────────────────────────────────────────────────
export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [tab, setTab] = useState('overview');
  const [homeTab, setHomeTab] = useState('portfolio');
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
  
  // GOD MODE / OMNIBAR STATE
  const [omnibarOpen, setOmnibarOpen] = useState(false);
  const [omniInput, setOmniInput] = useState('');
  const [omniResult, setOmniResult] = useState(null);
  
  // Listeners for Cmd+K / Ctrl+K
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOmnibarOpen(prev => !prev);
      }
      if (e.key === 'Escape') setOmnibarOpen(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleOmniSubmit = (e) => {
    e.preventDefault();
    if (!omniInput.trim()) return;
    
    const cmd = omniInput.toLowerCase();
    if (cmd.startsWith('/buy') || cmd.startsWith('/sell')) {
      setOmniResult({ type: 'success', text: `Ordem enviada para o Motor FIX de Alta Frequência: ${cmd.toUpperCase()}` });
    } else if (cmd.includes('clima') || cmd.includes('macro')) {
      setOmniResult({ type: 'ai', text: `Análise do Comitê: Volatilidade (VIX) em queda. Apetite a risco favorável. Sugestão: Aumentar exposição em Beta Alto.` });
    } else if (cmd === '/matrix') {
      document.body.classList.toggle('matrix-mode');
      setOmniResult({ type: 'success', text: `Matrix Mode toggled.` });
    } else {
      setOmniResult({ type: 'error', text: `Comando desconhecido. Digite /help para listar as habilidades do Agente.` });
    }
    setOmniInput('');
  };

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
      {/* ── OMNIBAR / GOD MODE OVERLAY ── */}
      <div className={`omnibar-overlay ${omnibarOpen ? 'open' : ''}`} onClick={() => setOmnibarOpen(false)}>
        <div className="omnibar-modal" onClick={e => e.stopPropagation()}>
          <div className="omnibar-header">
            <Bot size={18} color="#00f3ff" />
            <span>Meridian AI Core // God Mode</span>
            <div className="omnibar-hint">ESC to close</div>
          </div>
          <form onSubmit={handleOmniSubmit} className="omnibar-form">
            <span className="omnibar-prompt">❯</span>
            <input 
              autoFocus={omnibarOpen}
              type="text" 
              value={omniInput}
              onChange={e => setOmniInput(e.target.value)}
              placeholder="Digite um comando (ex: /buy 100 PETR4, /matrix, ou 'como está o clima macro?')" 
              className="omnibar-input"
            />
          </form>
          {omniResult && (
            <div className={`omnibar-result type-${omniResult.type}`}>
              {omniResult.type === 'ai' ? <BrainCircuit size={16} /> : <Terminal size={16} />}
              <span>{omniResult.text}</span>
            </div>
          )}
        </div>
      </div>

      {/* ── SIDEBAR OVERLAY ── */}
      <div className={`sidebar-overlay ${sidebarOpen ? 'open' : ''}`} onClick={() => setSidebarOpen(false)} />
      
      {/* ── SIDEBAR ── */}
      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <div className="sidebar-brand">
          <Activity size={22} color="#00f3ff" />
          <span>MERIDIAN</span>
        </div>

        <nav className="sidebar-nav">
          {[
            { id: 'overview',   Icon: BarChart2,   label: 'Visão Geral' },
            { id: 'ai',         Icon: Cpu,         label: 'Comitê de IA' },
            { id: 'risk',       Icon: ShieldAlert, label: 'Risk & Metrics' },
            { id: 'profile',    Icon: BookOpen,    label: 'Perfil' },
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
          <div style={{ padding: '0 1rem', display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <button 
              onClick={() => setSidebarOpen(true)} 
              style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center' }}
            >
              <Menu size={20} />
            </button>
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
              {/* GLOBAL MACRO & NEWS TICKER */}
              <div style={{ overflow: 'hidden', display: 'flex', alignItems: 'center', marginBottom: '1rem', fontSize: '0.75rem', fontWeight: 600, color: '#8b9bb4', padding: '0.6rem 1rem', background: 'rgba(255,255,255,0.02)', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.05)', maskImage: 'linear-gradient(to right, transparent 0%, black 5%, black 95%, transparent 100%)', WebkitMaskImage: 'linear-gradient(to right, transparent 0%, black 5%, black 95%, transparent 100%)' }}>
                <div className="tape-scroll" style={{ gap: '3rem', animationDuration: '60s' }}>
                  {[...Array(2)].map((_, idx) => (
                    <React.Fragment key={idx}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span>S&P 500</span> <span style={{ color: '#10b981' }}>5,123.40 (+0.8%)</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span>DXY</span> <span style={{ color: '#e60000' }}>104.20 (-0.2%)</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span>VIX</span> <span style={{ color: '#10b981' }}>13.40 (-1.5%)</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span>US10Y</span> <span style={{ color: '#f59e0b' }}>4.23% (+0.02)</span>
                      </div>
                      {marketNews && marketNews.map((n, i) => (
                        <div key={`news-${i}`} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          <span style={{ color: 'var(--primary)' }}>[{n.source}]</span>
                          <span style={{ color: '#fff' }}>{n.title}</span>
                        </div>
                      ))}
                    </React.Fragment>
                  ))}
                </div>
              </div>

              <div className="kpi-row">
                <KpiCard title="Patrimônio Total" icon={DollarSign} color="#00f3ff" value={`R$ ${positions.capital.current.toFixed(2)}`} sub={`Inicial: R$ ${positions.capital.initial.toFixed(2)}`} />
                <KpiCard title="Saldo Disponível" icon={Briefcase} color="#10b981" value={`R$ ${(positions.capital.current * 0.65).toFixed(2)}`} sub="Livre para novas operações" />
                <KpiCard title="ROI" icon={Percent} color={roiNum >= 0 ? '#10b981' : '#f43f5e'} value={`${roiNum >= 0 ? '+' : ''}${roi}%`} sub="desde o início" trend={roiNum} />
                <KpiCard title="Posições Abertas" icon={Activity} color="#f59e0b" value={positions.active_positions.length} sub={`R$ ${positions.capital.invested?.toFixed(2) || '105.00'} alocado`} />
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

                    <div className="glass-panel">
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

                    {/* BOTTOM LEFT GRID */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '0.5rem' }}>
                      {/* DOM WIDGET */}
                      <div className="glass-panel">
                        <div className="panel-header">
                          <h3>Livro Visual de Ofertas (DOM)</h3>
                          <button onClick={playDing} title="Testar Som de Gain" style={{ background: 'var(--primary)', color: '#fff', border: 'none', borderRadius: '2px', width: '20px', height: '20px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}>
                            <Activity size={12} />
                          </button>
                        </div>
                        <div style={{ padding: '0.5rem' }}>
                          <DepthOfMarket />
                        </div>
                      </div>

                      {/* FAST EXECUTION WIDGET */}
                      <div className="glass-panel">
                        <div className="panel-header">
                          <h3>Boleta Scalper Turbo</h3>
                        </div>
                        <div style={{ padding: '0.75rem' }}>
                          <FastExecutionWidget />
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="right-col">
                    {/* LIVE STREAM WIDGET */}
                    <div className="glass-panel" style={{ flexShrink: 0 }}>
                      <div className="panel-header" style={{ padding: '0.5rem 0.75rem' }}>
                        <h3><Globe size={14} color="var(--primary)" /> TV Mercado Ao Vivo</h3>
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

                    {/* NEWS WIDGET */}
                    <div className="glass-panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: '200px' }}>
                      <div className="panel-header"><h3>Notícias e Eventos (B3)</h3></div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', padding: '0.75rem', overflowY: 'auto', flex: 1 }}>
                        {marketNews ? marketNews.map((n, i) => (
                          <div key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '0.5rem' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.2rem', fontSize: '0.7rem' }}>
                              <span style={{ color: 'var(--primary)', fontWeight: 600 }}>{n.category}</span>
                              <span style={{ color: 'var(--text-muted)' }}>{n.time} • {n.source}</span>
                            </div>
                            <div style={{ fontSize: '0.8rem', lineHeight: 1.4, color: 'var(--text)' }}>{n.title}</div>
                          </div>
                        )) : <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>Carregando radar de notícias...</div>}
                      </div>
                    </div>

                    {/* BOTTOM RIGHT GRID */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                      {/* ECONOMIC CALENDAR WIDGET */}
                      <div className="glass-panel">
                        <div className="panel-header">
                          <h3>Calendário Econômico</h3>
                          <button onClick={playBeep} title="Testar Alerta" style={{ background: 'var(--primary)', color: '#fff', border: 'none', borderRadius: '2px', width: '20px', height: '20px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}>
                            <Bell size={12} />
                          </button>
                        </div>
                        <div style={{ padding: '0.5rem' }}>
                          <EconomicCalendar />
                        </div>
                      </div>

                      {/* HEATMAP WIDGET */}
                      <div className="glass-panel">
                        <div className="panel-header">
                          <h3>Mapa de Calor (IBOV)</h3>
                        </div>
                        <div style={{ padding: '0.25rem' }}>
                          <MarketHeatmap />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                
                {/* ACADEMY WIDGET ROW */}
                <div style={{ marginTop: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0 0.5rem' }}>
                    <h3 style={{ fontSize: '1.1rem', fontWeight: 800, margin: 0, color: '#fff' }}>Meridian Academy</h3>
                    <span style={{ fontSize: '0.7rem', background: 'rgba(16,185,129,0.15)', color: '#10b981', padding: '0.2rem 0.5rem', borderRadius: '4px', fontWeight: 700 }}>CURSOS GRATUITOS</span>
                  </div>
                  <AcademyWidget />
                </div>
              </div>
            )}

          {/* AI COMMITTEE */}
          {tab === 'ai' && (
            <div className="page-section">
              <div className="page-title">
                <Cpu size={22} />
                <div>
                  <h2>Comitê de IA Operacional</h2>
                  <p>Gestão e supervisão do ecossistema de agentes</p>
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                <div className="glass-panel">
                  <div className="panel-header" style={{ padding: '1rem', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                    <h3><BrainCircuit size={16} /> Workflow Lógico do Agente</h3>
                    <span className="muted-tag">Estrutura Node-Based do Raciocínio (Langflow)</span>
                  </div>
                  <div style={{ padding: '1rem' }}>
                    <AIFlow />
                  </div>
                </div>
                <AIEcosystemDashboard />
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
                  <div className="panel-header">
                    <h3>Simulação de Monte Carlo (1000 caminhos)</h3>
                    <span className="muted-tag">Projeção 60 dias · Sharpe Base 2.1</span>
                  </div>
                  <div style={{ padding: '1rem' }}>
                    <MonteCarloChart initialCapital={positions?.capital?.current || 300} days={60} paths={25} />
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

      {/* ── COPILOT WIDGET ── */}
      <button 
        className="copilot-fab"
        onClick={() => setCopilotOpen(!copilotOpen)}
      >
        {copilotOpen ? <X size={24} color="#fff" /> : <Bot size={24} color="#fff" />}
      </button>

      {copilotOpen && (
        <div className="copilot-window">
          <div className="copilot-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Bot size={18} color="var(--primary)" />
              <span style={{ fontWeight: 'bold' }}>Meridian Copilot</span>
            </div>
            <button onClick={() => setCopilotOpen(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
              <X size={16} />
            </button>
          </div>
          <div className="copilot-body">
            <div className="copilot-msg ai">Olá! Sou o Assistente da Meridian. Posso ajudar a analisar seu portfólio, explicar métricas de risco ou consultar o comitê de agentes por você. Como posso ajudar?</div>
          </div>
          <div className="copilot-footer">
            <input type="text" placeholder="Pergunte ao Copilot..." className="copilot-input" />
            <button className="copilot-send"><Send size={16} color="#fff" /></button>
          </div>
        </div>
      )}
    </div>
  );
}
