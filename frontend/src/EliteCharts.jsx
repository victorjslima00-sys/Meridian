import React, { useState } from 'react';
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, AreaChart, Area, ReferenceLine, ReferenceArea,
  ScatterChart, Scatter, ZAxis
} from 'recharts';
import { Bell, ChevronDown } from 'lucide-react';

const DarkTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: 'rgba(10,14,23,0.95)',
      border: '1px solid rgba(0,243,255,0.2)',
      borderRadius: '8px',
      padding: '0.75rem',
      fontSize: '0.8rem',
      backdropFilter: 'blur(8px)',
      color: '#e2e8f0',
      fontFamily: 'JetBrains Mono, monospace'
    }}>
      <p style={{ color: '#8b9bb4', marginBottom: '0.25rem' }}>{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color || p.fill, fontWeight: 600 }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(2) : p.value}
        </p>
      ))}
    </div>
  );
};

// Custom Candlestick implementation using ComposedChart
export const CandlestickChart = ({ data }) => {
  if (!data || !data.length) return <div style={{ color: '#8b9bb4', padding: '2rem' }}>Sem dados OHLCV</div>;

  // Process data for stacked bars to simulate candles
  const processedData = data.map((d, i) => {
    const isUp = d.c >= d.o;
    const max = Math.max(d.o, d.c);
    const min = Math.min(d.o, d.c);
    
    return {
      ...d,
      dateFormatted: d.date ? String(d.date).slice(5) : `D${i}`,
      isUp,
      // For the shadow (wick)
      wickTop: d.h - max,
      wickBottom: min - d.l,
      // For the body
      bodyBottom: min,
      bodyHeight: max - min,
      color: isUp ? '#10b981' : '#f43f5e',
    };
  });

  // Calculate min/max for domain
  const minL = Math.min(...data.map(d => d.l));
  const maxH = Math.max(...data.map(d => d.h));
  const padding = (maxH - minL) * 0.1;

  return (
    <ResponsiveContainer width="100%" height={300}>
      <ComposedChart data={processedData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
        <XAxis dataKey="dateFormatted" tick={{ fill: '#8b9bb4', fontSize: 10 }} tickLine={false} />
        <YAxis yAxisId="price" domain={[minL - padding, maxH + padding]} tick={{ fill: '#8b9bb4', fontSize: 10 }} tickLine={false} orientation="right" />
        <YAxis yAxisId="volume" domain={[0, 'dataMax * 4']} hide />
        <Tooltip content={<DarkTooltip />} />
        
        <Bar yAxisId="price" dataKey="bodyBottom" stackId="a" fill="transparent" />
        <Bar yAxisId="price" dataKey="bodyHeight" stackId="a" isAnimationActive={false}>
          {processedData.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={entry.color} />
          ))}
        </Bar>
        
        {/* Volume */}
        <Bar yAxisId="volume" dataKey="v" name="Volume" isAnimationActive={false}>
          {processedData.map((entry, index) => (
            <Cell key={`vol-${index}`} fill={entry.color} fillOpacity={0.3} />
          ))}
        </Bar>
      </ComposedChart>
    </ResponsiveContainer>
  );
};

export const EquityDrawdownChart = ({ capitalHistory }) => {
  if (!capitalHistory || !capitalHistory.length) return <div style={{ color: '#8b9bb4' }}>Sem dados de equity</div>;

  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={capitalHistory} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
        <defs>
          <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#00f3ff" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#00f3ff" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#f43f5e" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
        <XAxis dataKey="day" tick={{ fill: '#8b9bb4', fontSize: 10 }} tickLine={false} />
        <YAxis yAxisId="left" tick={{ fill: '#8b9bb4', fontSize: 10 }} domain={['auto', 'auto']} tickFormatter={v => `R$${v}`} />
        <YAxis yAxisId="right" orientation="right" hide domain={[-20, 5]} />
        <Tooltip content={<DarkTooltip />} />
        
        {/* Drawdown area (negative values) */}
        <Area yAxisId="right" type="monotone" dataKey="drawdown" name="Drawdown %" stroke="#f43f5e" fill="url(#ddGrad)" />
        
        {/* Equity area */}
        <Area yAxisId="left" type="monotone" dataKey="value" name="Capital" stroke="#00f3ff" strokeWidth={2} fill="url(#eqGrad)" />
      </ComposedChart>
    </ResponsiveContainer>
  );
};

export const CorrelationHeatmap = ({ matrix, tickers }) => {
  if (!matrix || !matrix.length || !tickers || !tickers.length) return <div style={{ color: '#8b9bb4' }}>Sem dados de correlação</div>;

  const getColor = (val) => {
    if (val === 1) return '#3b82f6'; // Perfect correlation (self)
    if (val > 0.7) return '#f43f5e'; // High correlation (red/warning)
    if (val > 0.3) return '#f59e0b'; // Medium (yellow)
    if (val > -0.3) return '#10b981'; // Low (green/good for diversification)
    return '#00f3ff'; // Negative (cyan/excellent)
  };

  const size = 40;
  const padding = 60;
  const width = tickers.length * size + padding;
  const height = tickers.length * size + padding;

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg width={width} height={height} style={{ fontSize: '0.75rem', fontFamily: 'JetBrains Mono, monospace' }}>
        <g transform={`translate(${padding}, ${padding})`}>
          {/* Column labels */}
          {tickers.map((t, i) => (
            <text key={`col-${i}`} x={i * size + size/2} y={-10} textAnchor="middle" fill="#8b9bb4">{t}</text>
          ))}
          {/* Row labels */}
          {tickers.map((t, i) => (
            <text key={`row-${i}`} x={-10} y={i * size + size/2 + 4} textAnchor="end" fill="#8b9bb4">{t}</text>
          ))}
          
          {/* Cells */}
          {matrix.map((row, i) => (
            row.map((val, j) => {
              const color = getColor(val);
              return (
                <g key={`${i}-${j}`} transform={`translate(${j * size}, ${i * size})`}>
                  <rect width={size - 2} height={size - 2} fill={color} fillOpacity={0.8} rx={4} />
                  <text x={size/2} y={size/2 + 4} textAnchor="middle" fill="#fff" fontSize="0.65rem">
                    {val.toFixed(2)}
                  </text>
                </g>
              );
            })
          ))}
        </g>
      </svg>
    </div>
  );
};

export const RiskMetricsPanel = ({ metrics }) => {
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
    win_rate: v => `${(v * 100).toFixed(1)}%`,
    avg_win: v => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`,
    avg_loss: v => `${v.toFixed(2)}%`
  };

  const labels = {
    sharpe: 'Sharpe Ratio', sortino: 'Sortino Ratio', calmar: 'Calmar Ratio',
    max_drawdown_pct: 'Max Drawdown', var_95_daily: 'VaR 95% (Diário)',
    win_rate: 'Win Rate', avg_win: 'Média de Ganhos', avg_loss: 'Média de Perdas'
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '1rem' }}>
      {Object.entries(metrics).map(([k, v]) => (
        <div key={k} style={{ background: 'rgba(0,0,0,0.2)', padding: '1rem', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)' }}>
          <div style={{ fontSize: '0.7rem', color: '#8b9bb4', textTransform: 'uppercase', marginBottom: '0.5rem' }}>{labels[k]}</div>
          <div style={{ fontSize: '1.25rem', fontWeight: 700, color: getMetricColor(k, v), fontFamily: 'JetBrains Mono, monospace' }}>
            {formatters[k] ? formatters[k](v) : v}
          </div>
        </div>
      ))}
    </div>
  );
};

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

export const AlertBadge = ({ alerts }) => {
  const [open, setOpen] = useState(false);
  const count = alerts?.length || 0;

  return (
    <div style={{ position: 'relative' }}>
      <button 
        onClick={() => setOpen(!open)}
        style={{ 
          background: 'none', border: 'none', color: '#8b9bb4', cursor: 'pointer',
          padding: '0.5rem', display: 'flex', alignItems: 'center', justifyContent: 'center'
        }}
      >
        <Bell size={20} />
        {count > 0 && (
          <span style={{
            position: 'absolute', top: '2px', right: '2px', background: '#f43f5e', color: '#fff',
            fontSize: '0.6rem', fontWeight: 'bold', width: '16px', height: '16px',
            borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center'
          }}>
            {count}
          </span>
        )}
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: '100%', right: '0', width: '300px',
          background: 'rgba(15,23,42,0.95)', border: '1px solid rgba(255,255,255,0.1)',
          borderRadius: '12px', padding: '1rem', backdropFilter: 'blur(16px)',
          boxShadow: '0 10px 40px rgba(0,0,0,0.5)', zIndex: 100
        }}>
          <h4 style={{ margin: '0 0 1rem 0', fontSize: '0.9rem', borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: '0.5rem' }}>Alertas Recentes</h4>
          {!count ? <div style={{ color: '#8b9bb4', fontSize: '0.85rem' }}>Sem alertas no momento.</div> : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {alerts.map((a, i) => (
                <div key={i} style={{ display: 'flex', gap: '0.75rem', fontSize: '0.8rem' }}>
                  <div style={{
                    width: '8px', height: '8px', borderRadius: '50%', marginTop: '4px', flexShrink: 0,
                    background: a.type === 'target_hit' ? '#10b981' : (a.type === 'stop_hit' ? '#f43f5e' : '#f59e0b')
                  }} />
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.2rem' }}>
                      <span style={{ fontWeight: 600 }}>{a.ticker}</span>
                      <span style={{ color: '#8b9bb4', fontSize: '0.7rem' }}>{a.time}</span>
                    </div>
                    <div style={{ color: '#d1d5db' }}>{a.message}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export const MarketRegimeBadge = ({ regime }) => {
  if (!regime) return null;
  
  const styles = {
    bull: { bg: 'rgba(16,185,129,0.15)', color: '#10b981', label: 'BULL MARKET' },
    bear: { bg: 'rgba(244,63,94,0.15)', color: '#f43f5e', label: 'BEAR MARKET' },
    volatile: { bg: 'rgba(245,158,11,0.15)', color: '#f59e0b', label: 'HIGH VOLATILITY' },
    lateral: { bg: 'rgba(139,92,246,0.15)', color: '#8b5cf6', label: 'LATERAL / RANGING' }
  };
  
  const s = styles[regime.regime] || styles.lateral;

  return (
    <div 
      title={regime.description}
      style={{
        display: 'flex', alignItems: 'center', gap: '0.5rem',
        background: s.bg, border: `1px solid ${s.color}40`,
        padding: '0.35rem 0.75rem', borderRadius: '999px',
        fontSize: '0.7rem', fontWeight: 800, color: s.color, letterSpacing: '1px',
        cursor: 'help'
      }}
    >
      <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: s.color }} />
      {s.label}
      <span style={{ opacity: 0.7, marginLeft: '0.25rem', borderLeft: `1px solid ${s.color}40`, paddingLeft: '0.5rem' }}>
        {(regime.confidence * 100).toFixed(0)}%
      </span>
    </div>
  );
};
