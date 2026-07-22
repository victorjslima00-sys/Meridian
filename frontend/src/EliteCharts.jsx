import React, { useState } from 'react';

// honest-dashboard Bloco 4: removidos CandlestickChart, EquityDrawdownChart,
// CorrelationHeatmap, MarketRegimeBadge, AlertBadge, MarketHeatmap,
// EconomicCalendar, DepthOfMarket, AcademyWidget, MonteCarloChart — todos
// decorativos/estáticos ou alimentados por rotas que nunca existiram no
// backend (ver CLAUDE.md: "no frontend, tudo que parece dado É dado vindo
// da API, ou não existe"). RiskMetricsPanel, PositionSizingCalc e
// FastExecutionWidget seguem — o primeiro lê /api/elite/risk_metrics
// (real), os outros dois não dependem de dado fabricado.

export const RiskMetricsPanel = React.memo(({ metrics }) => {
  if (!metrics) return <div style={{ color: '#8b9bb4' }}>Carregando métricas...</div>;

  const getMetricColor = (key, val) => {
    if (key === 'sharpe' || key === 'sortino' || key === 'calmar') return val >= 1 ? '#10b981' : (val >= 0.5 ? '#f59e0b' : '#f43f5e');
    if (key === 'max_drawdown_pct') return val > -10 ? '#10b981' : (val > -20 ? '#f59e0b' : '#f43f5e');
    if (key === 'win_rate') return val >= 0.5 ? '#10b981' : '#f43f5e';
    if (key === 'var_95_daily') return val > -50 ? '#10b981' : '#f43f5e';
    return '#e2e8f0';
  };

  const formatters = {
    sharpe: v => v.toFixed(2),
    sortino: v => v.toFixed(2),
    calmar: v => v.toFixed(2),
    max_drawdown_pct: v => `${v.toFixed(2)}%`,
    var_95_daily: v => `R$ ${v.toFixed(2)}`,
    win_rate: v => `${(v * 100).toFixed(2)}%`,
    avg_win: v => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`,
    avg_loss: v => `${v.toFixed(2)}%`
  };

  const labels = {
    sharpe: 'Sharpe Ratio', sortino: 'Sortino Ratio', calmar: 'Calmar Ratio',
    max_drawdown_pct: 'Max Drawdown', var_95_daily: 'VaR 95% (Diário)',
    win_rate: 'Win Rate', avg_win: 'Média de Ganhos', avg_loss: 'Média de Perdas'
  };

  const getProgressVal = (key, val) => {
    if (key === 'win_rate') return val * 100;
    if (key === 'sharpe' || key === 'sortino' || key === 'calmar') return Math.min(100, Math.max(0, (val / 3) * 100));
    if (key === 'max_drawdown_pct') return Math.min(100, Math.max(0, (Math.abs(val) / 30) * 100)); // assumes max 30% bad
    return 50; // default middle
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.5rem' }}>
      {Object.entries(metrics).map(([k, v]) => {
        const color = getMetricColor(k, v);
        const progress = getProgressVal(k, v);
        return (
          <div key={k} style={{ background: 'rgba(0,0,0,0.2)', padding: '0.75rem', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.05)', position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={{ position: 'absolute', bottom: 0, left: 0, height: '3px', width: '100%', background: 'rgba(255,255,255,0.05)' }}>
              <div style={{ height: '100%', width: `${progress}%`, background: color, opacity: 0.6, transition: 'width 1s ease' }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div style={{ fontSize: '0.65rem', color: '#8b9bb4', textTransform: 'uppercase', letterSpacing: '0.5px', lineHeight: 1.2 }}>{labels[k]}</div>
              <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: color, boxShadow: `0 0 6px ${color}`, flexShrink: 0, marginTop: '2px' }} />
            </div>
            <div style={{ fontSize: '1.1rem', fontWeight: 800, color: color, fontFamily: 'JetBrains Mono, monospace' }}>
              {formatters[k] ? formatters[k](v) : v}
            </div>
          </div>
        );
      })}
    </div>
  );
});

export const PositionSizingCalc = ({ capital }) => {
  const [riskPct, setRiskPct] = useState(2.0);
  const [stopDist, setStopDist] = useState(5.0);

  const riskAmount = capital * (riskPct / 100);
  const positionSize = riskAmount / (stopDist / 100);
  const leverage = positionSize / capital;

  return (
    <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap' }}>
      <div style={{ flex: 1, minWidth: '200px', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <div>
          <label style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#8b9bb4', marginBottom: '0.5rem' }}>
            <span>Risco por Trade (%)</span>
            <span style={{ color: '#00f3ff', fontWeight: 'bold' }}>{riskPct.toFixed(1)}%</span>
          </label>
          <input type="range" min="0.5" max="5.0" step="0.1" value={riskPct} onChange={e => setRiskPct(parseFloat(e.target.value))} style={{ width: '100%', accentColor: '#00f3ff' }} />
        </div>
        <div>
          <label style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#8b9bb4', marginBottom: '0.5rem' }}>
            <span>Distância do Stop Loss (%)</span>
            <span style={{ color: '#f43f5e', fontWeight: 'bold' }}>{stopDist.toFixed(1)}%</span>
          </label>
          <input type="range" min="1.0" max="15.0" step="0.5" value={stopDist} onChange={e => setStopDist(parseFloat(e.target.value))} style={{ width: '100%', accentColor: '#f43f5e' }} />
        </div>
      </div>

      <div style={{ flex: 1, minWidth: '250px', background: 'rgba(0,0,0,0.3)', borderRadius: '8px', padding: '1.25rem', border: '1px solid rgba(0,243,255,0.1)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
          <span style={{ color: '#8b9bb4', fontSize: '0.85rem' }}>Capital Base</span>
          <span style={{ fontFamily: 'JetBrains Mono', fontWeight: 600 }}>R$ {capital.toFixed(2)}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
          <span style={{ color: '#8b9bb4', fontSize: '0.85rem' }}>Valor em Risco</span>
          <span style={{ fontFamily: 'JetBrains Mono', fontWeight: 600, color: '#f43f5e' }}>R$ {riskAmount.toFixed(2)}</span>
        </div>
        <div style={{ height: '1px', background: 'rgba(255,255,255,0.1)', margin: '1rem 0' }} />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ color: '#e2e8f0', fontSize: '1rem', fontWeight: 600 }}>Tamanho da Posição</span>
          <span style={{ fontFamily: 'JetBrains Mono', fontWeight: 800, fontSize: '1.5rem', color: '#00f3ff' }}>R$ {positionSize.toFixed(2)}</span>
        </div>
        <div style={{ marginTop: '0.5rem', fontSize: '0.75rem', color: leverage > 1 ? '#f59e0b' : '#10b981', textAlign: 'right' }}>
          Alavancagem: {leverage.toFixed(2)}x {leverage > 1 && '(Cuidado)'}
        </div>
      </div>
    </div>
  );
};

export const FastExecutionWidget = React.memo(({ trade, saldoLivre = 0, onExecute }) => {
  const [qty, setQty] = useState(100);
  const [loading, setLoading] = useState(false);
  const [localTicker, setLocalTicker] = useState('');

  // Sincroniza se o usuário clicar na tabela
  React.useEffect(() => {
    if (trade?.ticker) setLocalTicker(trade.ticker);
  }, [trade]);

  const handleExec = async (side) => {
    if (!localTicker) {
      alert("Digite um ativo para operar.");
      return;
    }
    if (qty <= 0) return;

    setLoading(true);
    try {
      if (onExecute) {
        await onExecute({
          ticker: localTicker.toUpperCase(),
          side: side,
          quantity: qty
        });
      }
    } catch (err) {
      console.error(err);
      alert("Falha na execução: " + (err.response?.data?.detail || err.message));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', width: '100%' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>Ativo (Ticker)</div>
        <input
          type="text"
          value={localTicker}
          onChange={e => setLocalTicker(e.target.value.toUpperCase())}
          placeholder="Ex: PETR4.SA"
          style={{ width: '100%', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border)', color: '#fff', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem', fontFamily: 'JetBrains Mono, monospace', textAlign: 'center', fontWeight: 800, letterSpacing: '1px' }}
        />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
        <button
          onClick={() => handleExec('SELL')}
          disabled={loading || !localTicker}
          style={{ background: 'rgba(244,63,94,0.1)', border: '1px solid var(--red)', color: 'var(--red)', padding: '0.75rem', borderRadius: '4px', fontWeight: 800, fontSize: '0.9rem', cursor: loading || !localTicker ? 'not-allowed' : 'pointer', transition: 'all 0.2s', opacity: loading || !localTicker ? 0.5 : 1 }}
          onMouseEnter={e => { if(!loading && localTicker) { e.currentTarget.style.background='var(--red)'; e.currentTarget.style.color='#fff'; } }}
          onMouseLeave={e => { if(!loading && localTicker) { e.currentTarget.style.background='rgba(244,63,94,0.1)'; e.currentTarget.style.color='var(--red)'; } }}
        >
          {loading ? '...' : 'VENDER'}
        </button>
        <button
          onClick={() => handleExec('BUY')}
          disabled={loading || !localTicker}
          style={{ background: 'rgba(16,185,129,0.1)', border: '1px solid var(--green)', color: 'var(--green)', padding: '0.75rem', borderRadius: '4px', fontWeight: 800, fontSize: '0.9rem', cursor: loading || !localTicker ? 'not-allowed' : 'pointer', transition: 'all 0.2s', opacity: loading || !localTicker ? 0.5 : 1 }}
          onMouseEnter={e => { if(!loading && localTicker) { e.currentTarget.style.background='var(--green)'; e.currentTarget.style.color='#fff'; } }}
          onMouseLeave={e => { if(!loading && localTicker) { e.currentTarget.style.background='rgba(16,185,129,0.1)'; e.currentTarget.style.color='var(--green)'; } }}
        >
          {loading ? '...' : 'COMPRAR'}
        </button>
      </div>
      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginBottom: '0.2rem', textTransform: 'uppercase', fontWeight: 700 }}>Quantidade</div>
          <input type="number" value={qty} onChange={e => setQty(Number(e.target.value))} step={100} style={{ width: '100%', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border)', color: '#fff', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem', fontFamily: 'JetBrains Mono, monospace' }} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginBottom: '0.2rem', textTransform: 'uppercase', fontWeight: 700 }}>Preço</div>
          <input type="text" defaultValue="Mercado" style={{ width: '100%', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border)', color: '#10b981', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem', fontFamily: 'JetBrains Mono, monospace', textAlign: 'center', fontWeight: 700 }} readOnly />
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.65rem', color: 'var(--text-muted)', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '0.75rem' }}>
        <span>Poder de Compra: <strong style={{ color: '#fff', fontFamily: 'JetBrains Mono, monospace' }}>R$ {saldoLivre.toFixed(2)}</strong></span>
        <span>Margem req: <strong style={{ color: '#fff', fontFamily: 'JetBrains Mono, monospace' }}>R$ 0,00</strong></span>
      </div>
    </div>
  );
});
