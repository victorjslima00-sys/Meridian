import React, { useState, useEffect } from 'react';
import api from './api';
import ActiveTradeDetails from './ActiveTradeDetails';
import PositionNarrative, { ClosedPositionsNarrative } from './PositionNarrative';
import CapitalVault from './CapitalVault';
import DecisionLog from './DecisionLog';
import {
  Activity, ShieldAlert, Cpu,
  BarChart2, Briefcase, X,
  WifiOff, TrendingUp, TrendingDown,
  Settings,
  DollarSign, BookOpen,
  Key, ToggleLeft, ToggleRight, Users, Menu,
  Wallet, Lock
} from 'lucide-react';
import { RiskMetricsPanel, PositionSizingCalc, FastExecutionWidget } from './EliteCharts';
import { PortfolioChart as SimplePortfolio } from './Charts';
import { timeAgo, FreshnessTag } from './Freshness';
import './index.css';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }
  static getDerivedStateFromError() { return { hasError: true }; }
  componentDidCatch(error, errorInfo) { this.setState({ error, errorInfo }); }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '2rem', background: '#f43f5e', color: 'white', fontFamily: 'monospace' }}>
          <h2>React Crashed!</h2>
          <p>{this.state.error && this.state.error.toString()}</p>
          <details style={{ whiteSpace: 'pre-wrap', marginTop: '1rem' }}>{this.state.errorInfo?.componentStack}</details>
        </div>
      );
    }
    return this.props.children;
  }
}


// ─── Health Badge — 4 estados reais de /api/status (honest-dashboard) ────────
// Nenhum threshold decidido aqui: a cor é só um mapa 1:1 do campo `status`
// que o backend já calculou (worker_state._compute_status). Motivos de
// bloqueio (motivos_bloqueio) vêm prontos também — o front só exibe.
const HEALTH_STATES = {
  online: { color: '#10b981', label: 'OPERACIONAL' },
  degraded: { color: '#f59e0b', label: 'DEGRADADO' },
  unprotected: { color: '#fb923c', label: 'SEM PROTEÇÃO' },
  stopped: { color: '#f43f5e', label: 'PARADO' },
};

const HealthBadge = ({ status, connected }) => {
  if (!connected || !status) {
    return (
      <div className="conn-pill down">
        <WifiOff size={12} />
        SEM CONEXÃO
      </div>
    );
  }
  const s = HEALTH_STATES[status.status] || { color: '#8b9bb4', label: (status.status || 'DESCONHECIDO').toUpperCase() };
  const motivos = status.motivos_bloqueio || [];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
      <div
        className="conn-pill"
        style={{ background: `${s.color}20`, borderColor: `${s.color}50`, color: s.color, border: '1px solid' }}
      >
        <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: s.color, boxShadow: `0 0 6px ${s.color}`, flexShrink: 0 }} />
        {s.label}
      </div>
      {motivos.length > 0 && (
        <div style={{ fontSize: '0.62rem', color: 'var(--text-muted)', lineHeight: 1.4, paddingLeft: '0.2rem' }}>
          {motivos.join(' · ')}
        </div>
      )}
    </div>
  );
};

// ─── System Health Panel — detalhe operacional real de /api/status ──────────
// Todo campo abaixo já vem pronto do worker_state.snapshot() no backend; o
// único cálculo feito aqui é "há quanto tempo" a partir de um timestamp ISO,
// que é formatação de exibição (igual a toLocaleString() já usado em outros
// pontos do arquivo), não lógica de negócio/risco.
const EXECUTION_MODE_LABELS = {
  manual: 'Manual — só ordens iniciadas por você',
  semi_auto: 'Semi-automático — IA sugere, você confirma',
  full_auto: 'Totalmente automático',
};

const HealthRow = ({ label, value, warn }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.4rem 0', borderBottom: '1px solid rgba(255,255,255,0.05)', fontSize: '0.78rem', gap: '1rem' }}>
    <span style={{ color: 'var(--text-muted)' }}>{label}</span>
    <span style={{ color: warn ? '#f59e0b' : '#e2e8f0', fontWeight: 600, fontFamily: 'monospace', textAlign: 'right' }}>{value}</span>
  </div>
);

const SystemHealthPanel = ({ status }) => {
  if (!status) return null;
  const motivos = status.motivos_bloqueio || [];
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <HealthRow label="Modo de execução" value={EXECUTION_MODE_LABELS[status.execution_mode] || status.execution_mode || '—'} />
      <HealthRow label="Laço de entradas" value={status.worker_status || '—'} warn={status.worker_status !== 'running'} />
      <HealthRow label="Última varredura (entradas)" value={timeAgo(status.last_scan_at)} />
      <HealthRow label="Restarts (entradas)" value={status.restart_count ?? 0} warn={(status.restart_count || 0) > 0} />
      <HealthRow label="Laço de saída — atividade" value={timeAgo(status.last_exit_activity_at)} />
      <HealthRow label="Laço de saída — efetivo" value={timeAgo(status.last_effective_exit_scan_at)} />
      <HealthRow label="Restarts (saída)" value={status.exit_restart_count ?? 0} warn={(status.exit_restart_count || 0) > 0} />
      {status.exit_gate_sticky_block && (
        <div style={{ marginTop: '0.5rem', padding: '0.5rem', background: 'rgba(244,63,94,0.1)', border: '1px solid rgba(244,63,94,0.3)', borderRadius: '4px', color: '#f43f5e', fontSize: '0.72rem', fontWeight: 600 }}>
          ⚠️ Bloqueio permanente: laço de saída esgotou os restarts. Só reinício manual do processo libera novas entradas.
        </div>
      )}
      {motivos.length > 0 && (
        <div style={{ marginTop: '0.5rem', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
          <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Entradas bloqueadas — motivos</span>
          {motivos.map((m, i) => (
            <span key={i} style={{ fontSize: '0.75rem', color: '#f59e0b' }}>• {m}</span>
          ))}
        </div>
      )}
    </div>
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

// ─── Curva de Patrimônio (Visão Global) ──────────────────────────────────
// usabilidade 2c: dos 4 gráficos da tela inicial sobrou só este — o único
// com valor real de decisão (histórico verdadeiro de equity, 1 snapshot/dia
// de pregão, direto de /api/equity_snapshots). Removidos: "Alocação de
// Capital" (pizza — repetia os cards e o KPI), "PnL MTM por Ativo" (barras
// — cada card de posição já mostra o mesmo pnl_monetario) e "Evolução MTM
// (Intraday)" (série acumulada client-side que zerava a cada reload,
// janela de 5min, cheia de buracos com a aba oculta, e cujo header
// duplicava o KPI "PnL Flutuante").
const PortfolioOverviewDashboard = () => (
  <div className="glass-panel" style={{ padding: '1.5rem', background: 'rgba(255,255,255,0.01)' }}>
    <h3 style={{ marginBottom: '1rem', color: '#fff', fontSize: '1.1rem' }}>Curva de Patrimônio</h3>
    <SimplePortfolio />
  </div>
);

// ─── APP PRINCIPAL ────────────────────────────────────────────────────────────
export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [tab, setTab] = useState('overview');
  const [status, setStatus] = useState(null);
  const [positions, setPositions] = useState(null);
  const [apiError, setApiError] = useState(null);
  const [connected, setConnected] = useState(true);

  // Elite Features State — risk_metrics é a única rota /elite/* real hoje
  // (as demais nunca existiram no backend, ver honest-dashboard Bloco 4).
  const [riskMetrics, setRiskMetrics] = useState(null);


  // Track B, 3c: frescor real do polling de 5s. lastRiskMetricsAt é
  // separado de lastPolledAt porque /elite/risk_metrics tem um .catch
  // próprio (silencioso) -- pode ficar velho independente do resto.
  const [lastPolledAt, setLastPolledAt] = useState(null);
  const [lastRiskMetricsAt, setLastRiskMetricsAt] = useState(null);
  // 2a: true só durante o catch-up de retorno de aba oculta com dado velho.
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Settings State
  const [brokerSettings, setBrokerSettings] = useState({ mode: 'paper', has_cedro_key: false });

  const [selectedTrade, setSelectedTrade] = useState(null);
  const [showEmergency, setShowEmergency] = useState(false);
  const [password, setPassword] = useState('');

  // usabilidade 2f: o log ao vivo (WebSocket, buffer de mensagens,
  // indicador CONECTADO, reconexão) foi extraído para <DecisionLog />.
  // Ficava aqui e cada mensagem re-renderizava o dashboard INTEIRO — com
  // o bot varrendo ~50 tickers, uma mensagem a cada 1-2s — causando a
  // lentidão e os timeouts de captura sofridos no diagnóstico. Agora a
  // mensagem de log só re-renderiza o próprio painel.

  // Status da chave da corretora — não muda em runtime (é var de ambiente),
  // então só no mount, sem polling (Track B, Commit 1: substitui o
  // has_cedro_key hardcoded em false que nunca era lido de lugar nenhum).
  useEffect(() => {
    api.get('/broker/status')
      .then(res => setBrokerSettings(prev => ({ ...prev, has_cedro_key: !!res.data?.has_cedro_key })))
      .catch(() => {});
  }, []);

  // Main Data fetch — só rotas que existem de verdade no backend.
  //
  // Usabilidade 2a (números congelados): o navegador estrangula
  // setInterval em página oculta/ocluída para ~1 disparo/min — flagrado
  // ao vivo no diagnóstico (tela "há 56s" com 2 posições enquanto a API
  // respondia 4 no mesmo instante, e os polls represados chegando em
  // rajada coalescida ao acordar). Nada disso é consertável do lado do
  // timer; o conserto é reagir ao RETORNO: visibilitychange/focus
  // disparam load() na hora, e se o dado estiver velho (>2 ciclos) o
  // FreshnessTag mostra "atualizando..." até a resposta chegar, para o
  // usuário VER que o sistema percebeu a volta.
  useEffect(() => {
    let lastSuccessAtMs = 0;

    const load = async () => {
      try {
        const [s, p, rm] = await Promise.all([
          api.get(`/status`),
          api.get(`/positions`),
          api.get(`/elite/risk_metrics`).catch(()=>({data:null})),
        ]);
        setStatus(s.data);
        setPositions(p.data);
        lastSuccessAtMs = Date.now();
        setLastPolledAt(new Date().toISOString());
        setSelectedTrade(prev => {
          if (!prev) return prev;
          // Sync with the latest fetched positions
          const updated = p.data.active_positions?.find(t => t.id === prev.id) || p.data.closed_positions?.find(t => t.id === prev.id);
          return updated ? { ...prev, ...updated } : prev;
        });

        if (rm.data) { setRiskMetrics(rm.data); setLastRiskMetricsAt(new Date().toISOString()); }

        setConnected(true); setApiError(null);
      } catch (err) {
        setApiError(err.message); setConnected(false);
      } finally {
        setIsRefreshing(false);
      }
    };

    const onReturn = () => {
      if (document.visibilityState !== 'visible') return;
      // Dado velho = mais de 2 ciclos de poll sem sucesso. O rótulo
      // "atualizando..." só aparece nesse caso — num foco corriqueiro com
      // dado fresco, trocar o rótulo seria ruído.
      if (Date.now() - lastSuccessAtMs > 10000) setIsRefreshing(true);
      load();
    };

    document.addEventListener('visibilitychange', onReturn);
    window.addEventListener('focus', onReturn);
    load();
    const iv = setInterval(load, 5000);
    return () => {
      clearInterval(iv);
      document.removeEventListener('visibilitychange', onReturn);
      window.removeEventListener('focus', onReturn);
    };
  }, []);

  const refreshCapital = async () => {
    const p = await api.get(`/positions`);
    setPositions(p.data);
  };

  const handleCloseTrade = async (tradeId) => {
    try {
      setApiError(null);
      await api.post(`/trades/${tradeId}/close`);

      // Force refresh positions
      const p = await api.get(`/positions`);
      setPositions(p.data);
    } catch (err) {
      const msg = err.response?.data?.detail || err.message;
      setApiError(`Erro ao encerrar trade: ${msg}`);
    }
  };

  const handleExecuteTrade = async (tradeParams) => {
    try {
      setApiError(null);
      await api.post(`/trades/execute`, tradeParams);
      // Force refresh positions
      const p = await api.get(`/positions`);
      setPositions(p.data);
    } catch (err) {
      const msg = err.response?.data?.detail || err.message;
      setApiError(`Erro ao executar trade: ${msg}`);
      throw err;
    }
  };

  const doEmergencyStop = async () => {
    try {
      const r = await api.post(`/system/emergency_stop`, { action: 'emergency_stop', password });
      alert(r.data.error || r.data.msg);
      if (!r.data.error) { setShowEmergency(false); setPassword(''); }
    } catch { alert('Erro de conexão.'); }
  };

  if (!status || !positions) {
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

  const cap = positions.capital || {};
  const patTotal = cap.patrimonio_total || 0;
  const patReservado = cap.patrimonio_reservado || 0;
  const saldoLivre = cap.saldo_livre || 0;
  const saldoDisponivel = cap.saldo_disponivel || 0;
  const emPosicoes = cap.em_posicoes || 0;
  // Soma direta do pnl_monetario que a API entrega por posição (2c:
  // substitui o array livePnlHistory acumulado client-side, que existia
  // só para alimentar o gráfico "Evolução MTM" removido).
  const pnlFlutuante = (positions.active_positions || []).reduce((s, p) => s + (p.pnl_monetario || 0), 0);

  return (
    <div className="shell">
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
            <button key={id} className={`nav-item ${tab === id ? 'active' : ''}`} onClick={() => { setSelectedTrade(null); setTab(id); }}>
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <HealthBadge status={status} connected={connected} />
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

          <button className="emergency-btn" onClick={() => setShowEmergency(true)}>
            <ShieldAlert size={14} /> STOP
          </button>
        </header>

        {/* ── PAGE CONTENT ── */}
        <div className="page-content">

          {/* DETALHE DE TRADE (ativo ou fechado) OU CONTEÚDO DA ABA —
              selectedTrade é setado por qualquer linha clicável (posição
              ativa ou fechada, em qualquer aba), então o dossiê aparece
              independente da aba atual; "VOLTAR" retorna pra aba de onde
              veio (selectedTrade só volta a null, tab não muda). */}
          {selectedTrade ? (
            <ErrorBoundary>
              <ActiveTradeDetails trade={selectedTrade} onBack={() => setSelectedTrade(null)} />
            </ErrorBoundary>
          ) : (
          <>
          {tab === 'overview' && (
            <div className="overview-layout">
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '0.35rem' }}>
                <FreshnessTag ts={lastPolledAt} refreshing={isRefreshing} />
              </div>
              {/* HEADER DE KPIS UNIFICADO */}
              <div className="kpi-row" style={{ marginBottom: '0.75rem' }}>
                <KpiCard title="Patrimônio Total" icon={DollarSign} color="#00f3ff" value={`R$ ${patTotal.toFixed(2)}`} sub="Reservado + gerido pelo bot (ao vivo)" />
                <KpiCard title="Reservado" icon={Lock} color="#8b9bb4" value={`R$ ${patReservado.toFixed(2)}`} sub="Fora do alcance do bot" />
                <KpiCard title="Caixa Disponível" icon={Wallet} color="#3b82f6" value={`R$ ${saldoDisponivel.toFixed(2)}`} sub="Entregue ao bot, antes de posições" />
                <KpiCard title="Em Posições" icon={Lock} color="#f59e0b" value={`R$ ${emPosicoes.toFixed(2)}`} sub="Alocado no preço de entrada" />
                {/* 2e: sub-rótulo corrigido — com margem operável definida,
                    o que o bot pode usar é saldo_operavel (Gestão de
                    Capital), não o livre bruto; "Margem livre p/ operar"
                    viraria mentira. */}
                <KpiCard title="Caixa Livre" icon={Briefcase} color="#10b981" value={`R$ ${saldoLivre.toFixed(2)}`} sub="Não alocado em posições" />
                <KpiCard
                  title="PnL Flutuante (MTM)"
                  icon={Activity}
                  color={pnlFlutuante >= 0 ? '#10b981' : '#f43f5e'}
                  value={`R$ ${pnlFlutuante.toFixed(2)}`}
                  sub={`Resultado não realizado de ${positions?.active_positions?.length || 0} posições`}
                />
              </div>

              <div className="pro-trading-layout">
                {/* COLUNA PRINCIPAL (ESQUERDA - 75%) */}
                <div className="pro-main-col">
                  {/* SUAS POSIÇÕES — primeira coisa vista: narrativa por
                      posição em linguagem natural, mesmo dado real do
                      resto do dashboard (alocado/current_price/pnl_monetario
                      vêm prontos da API), só formatado como texto em vez
                      de tabela. */}
                  <PositionNarrative positions={positions} onSelectTrade={setSelectedTrade} onClosePosition={handleCloseTrade} lastUpdated={lastPolledAt} refreshing={isRefreshing} />

                  {/* ÁREA GRÁFICA / VISÃO GLOBAL */}
                  {/* selectedTrade nunca chega aqui: quando setado, o
                      branch tab==='overview' já redireciona pra
                      ActiveTradeDetails.jsx (ver acima) — era um segundo
                      "modo detalhe" com iframe do TradingView pedindo
                      símbolo BINANCE: (Binance, cripto) pra um ticker B3,
                      inalcançável e errado, removido. */}
                  <PortfolioOverviewDashboard />

                </div>

                {/* COLUNA LATERAL (DIREITA - 25%) */}
                <div className="pro-side-col">
  {/* SAÚDE DO SISTEMA — detalhe real de /api/status */}
                  <div className="glass-panel" style={{ flexShrink: 0 }}>
                    <div className="panel-header" style={{ padding: '0.5rem 0.75rem', background: 'rgba(255,255,255,0.02)' }}>
                      <h3>Saúde do Sistema</h3>
                    </div>
                    <div style={{ padding: '0.5rem 0.75rem' }}>
                      <SystemHealthPanel status={status} />
                    </div>
                  </div>

                  {/* COFRE — depositar/retirar capital do alcance do bot */}
                  <div className="glass-panel" style={{ flexShrink: 0 }}>
                    <div className="panel-header" style={{ padding: '0.5rem 0.75rem', background: 'rgba(255,255,255,0.02)' }}>
                      <h3>Gestão de Capital</h3>
                    </div>
                    <div style={{ padding: '0.75rem' }}>
                      <CapitalVault capital={cap} onChanged={refreshCapital} />
                    </div>
                  </div>

                  {/* BOLETA E DOM */}
                  <div className="glass-panel" style={{ flexShrink: 0 }}>
                    <div className="panel-header" style={{ padding: '0.5rem 0.75rem', background: 'rgba(255,255,255,0.02)' }}>
                      <h3>Boleta Rápida (Scalper)</h3>
                    </div>
                    <div style={{ padding: '0.75rem' }}>
                      <FastExecutionWidget
                        trade={selectedTrade}
                        onExecute={handleExecuteTrade}
                      />
                    </div>
                  </div>

                  {/* usabilidade 2b: "Matriz de Risco" saiu daqui — era o
                      painel de "Métricas de Risco" da aba Risk duplicado
                      na íntegra (mesmo endpoint, mesmos 8 números). Um
                      fato, um lugar: a aba Risk é o lugar. */}
                </div>
              </div>
            </div>
            )}

          {/* AI COMMITTEE — sempre montado (visible controla exibição) para
              o WebSocket e o histórico sobreviverem à troca de aba. 2f:
              extraído para <DecisionLog />, isolando seu re-render. */}
          <DecisionLog visible={tab === 'ai'} />

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
                <div className="glass-panel" style={{ gridColumn: 'span 2' }}>
                  <div className="panel-header"><h3>Métricas de Risco</h3><FreshnessTag ts={lastRiskMetricsAt} /></div>
                  <div style={{ padding: '1rem' }}>
                    <RiskMetricsPanel metrics={riskMetrics} />
                  </div>
                </div>
                <div className="glass-panel" style={{ gridColumn: 'span 2' }}>
                  <div className="panel-header"><h3>Calculadora de Position Sizing</h3></div>
                  <div style={{ padding: '1.25rem' }}>
                    <PositionSizingCalc capital={cap.saldo_livre || 100} />
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
                  <h3 style={{ fontSize: '1.2rem', marginBottom: '0.2rem' }}>Meridian Bot</h3>
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                    {EXECUTION_MODE_LABELS[status?.execution_mode] || status?.execution_mode || 'Modo desconhecido'} • Conta {brokerSettings.mode.toUpperCase()}
                  </p>
                  <div style={{ display: 'flex', gap: '1rem' }}>
                    <span style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem', background: 'rgba(255,255,255,0.05)', borderRadius: '4px' }}>Ambiente: Paper Trading</span>
                    <span style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem', background: 'rgba(255,255,255,0.05)', borderRadius: '4px' }}>Execução: Simulador local</span>
                  </div>
                </div>
              </div>

              {positions?.closed_positions?.length > 0 && (
                <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
                  <div className="kpi-card" style={{ flex: 1, borderTop: '2px solid var(--primary)' }}>
                    <div className="kpi-title">Total de Trades</div>
                    <div className="kpi-value">{positions.closed_positions.length}</div>
                  </div>
                  <div className="kpi-card" style={{ flex: 1, borderTop: '2px solid var(--primary)' }}>
                    <div className="kpi-title">Winning / Losing</div>
                    <div className="kpi-value" style={{ color: 'var(--green)' }}>
                      {positions.closed_positions.filter(t => t.pnl_pct >= 0).length}
                      {' '}<span style={{ color: 'var(--text-muted)', fontSize: '1rem' }}>
                        / {positions.closed_positions.filter(t => t.pnl_pct < 0).length}
                      </span>
                    </div>
                  </div>
                  <div className="kpi-card" style={{ flex: 1, borderTop: '2px solid var(--primary)' }}>
                    <div className="kpi-title">PnL Total (BRL)</div>
                    {(() => {
                      {/* Soma simples de pnl_monetario, que já vem pronto por trade
                          da API — nenhum novo cálculo de risco/negócio aqui. */}
                      const total = positions.closed_positions.reduce(
                        (sum, t) => sum + (t.pnl_monetario || 0), 0
                      );
                      return (
                        <div className="kpi-value" style={{ color: total >= 0 ? 'var(--green)' : 'var(--red)' }}>
                          R$ {total.toFixed(2)}
                        </div>
                      );
                    })()}
                  </div>
                </div>
              )}

              <div className="glass-panel" style={{ padding: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', marginBottom: '1rem' }}>
                  <div>
                    <h3 style={{ margin: 0, fontSize: '1.1rem' }}>Histórico de Operações Fechadas</h3>
                    <span className="muted-tag">Clique numa posição pra ver o dossiê completo (justificativa da IA, alvo/stop no gráfico)</span>
                  </div>
                  <FreshnessTag ts={lastPolledAt} refreshing={isRefreshing} />
                </div>
                <ClosedPositionsNarrative positions={positions} onSelectTrade={setSelectedTrade} />
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
                      <strong>Simulador local (SQLite)</strong>
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
                </div>

                <div className="glass-panel" style={{ padding: '1.5rem' }}>
                  <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1.5rem' }}>
                    <ShieldAlert size={18} color="#f59e0b" /> Ambiente de Execução
                  </h3>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    {[
                      { id: 'paper', label: 'Simulador Local (SQLite)', color: '#10b981' },
                      
                      
                    ].map(mode => (
                      <div 
                        key={mode.id}
                        onClick={() => setBrokerSettings({...brokerSettings, mode: 'paper'})}
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
                    Circuit breaker ativo — limites definidos em <code>config/settings.yaml</code> (risk.circuit_breaker). Se atingidos, o sistema bloqueia novas entradas automaticamente.
                  </p>
                </div>
              </div>
            </div>
          )}
          </>
          )}

        </div>
      </main>

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
