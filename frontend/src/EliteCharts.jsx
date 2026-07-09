import React, { useState, useRef, useEffect } from 'react';
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, AreaChart, Area, ReferenceLine
} from 'recharts';

// ─── Shared dark theme constants ───────────────────────────────────────────────
const DARK_BG   = '#07090f';
const ACCENT    = '#00f3ff';
const TEXT      = '#e2e8f0';
const MUTED     = '#8b9bb4';
const PANEL_BG  = 'rgba(255,255,255,0.03)';
const BORDER    = 'rgba(255,255,255,0.07)';
const GREEN     = '#10b981';
const RED       = '#f43f5e';
const MONO_FONT = "'JetBrains Mono', 'Fira Code', monospace";

// ─── A) CandlestickChart ───────────────────────────────────────────────────────
// Simulates OHLC candles using a ComposedChart with stacked invisible/visible bars.
// Strategy: bar[low→open] invisible, bar[body] colored, bar[open→high] as lines.
const CandleTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  return (
    <div style={{
      background: 'rgba(7,9,15,0.97)',
      border: `1px solid rgba(0,243,255,0.25)`,
      borderRadius: 8,
      padding: '0.75rem 1rem',
      fontFamily: MONO_FONT,
      fontSize: '0.75rem',
      lineHeight: 1.8,
    }}>
      <div style={{ color: ACCENT, fontWeight: 700, marginBottom: 4 }}>{d.date}</div>
      <div style={{ color: TEXT }}>O: <span style={{ color: '#f59e0b' }}>{d.o?.toFixed(2)}</span></div>
      <div style={{ color: TEXT }}>H: <span style={{ color: GREEN }}>{d.h?.toFixed(2)}</span></div>
      <div style={{ color: TEXT }}>L: <span style={{ color: RED }}>{d.l?.toFixed(2)}</span></div>
      <div style={{ color: TEXT }}>C: <span style={{ color: d.c >= d.o ? GREEN : RED, fontWeight: 700 }}>{d.c?.toFixed(2)}</span></div>
      <div style={{ color: MUTED, borderTop: `1px solid ${BORDER}`, marginTop: 4, paddingTop: 4 }}>
        Vol: {d.v != null ? (d.v / 1000).toFixed(0) + 'K' : '—'}
      </div>
    </div>
  );
};

export const CandlestickChart = ({ data = [] }) => {
  if (!data.length) return (
    <div style={{ textAlign: 'center', color: MUTED, padding: '2rem', fontFamily: MONO_FONT, fontSize: '0.85rem' }}>
      Sem dados de candle disponíveis
    </div>
  );

  // Transform data: each candle needs low, body, high segments for stacked bars
  const transformed = data.map(d => {
    const isGreen = d.c >= d.o;
    const bodyLow  = Math.min(d.o, d.c);
    const bodyHigh = Math.max(d.o, d.c);
    return {
      ...d,
      wickLow:    d.l,                          // invisible base
      lowerWick:  bodyLow - d.l,                // lower wick
      body:       bodyHigh - bodyLow || 0.01,   // candle body (min 0.01 to show doji)
      upperWick:  d.h - bodyHigh,               // upper wick
      isGreen,
      // Volume normalized to 20% of price range for display below
      volNorm: d.v,
    };
  });

  const allPrices = data.flatMap(d => [d.l, d.h]);
  const priceMin = Math.min(...allPrices);
  const priceMax = Math.max(...allPrices);
  const pricePad = (priceMax - priceMin) * 0.05;

  return (
    <div style={{ width: '100%' }}>
      {/* Main OHLC chart */}
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={transformed} margin={{ top: 10, right: 10, left: -15, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fill: MUTED, fontSize: 9, fontFamily: MONO_FONT }}
            tickLine={false}
            axisLine={{ stroke: BORDER }}
            interval={Math.floor(data.length / 7)}
          />
          <YAxis
            domain={[priceMin - pricePad, priceMax + pricePad]}
            tick={{ fill: MUTED, fontSize: 9, fontFamily: MONO_FONT }}
            tickLine={false}
            axisLine={false}
            tickFormatter={v => v.toFixed(1)}
          />
          <Tooltip content={<CandleTooltip />} cursor={{ stroke: 'rgba(0,243,255,0.1)', strokeWidth: 1 }} />

          {/* Invisible base (from 0 to low) */}
          <Bar dataKey="wickLow" stackId="candle" fill="transparent" stroke="none" />

          {/* Lower wick */}
          <Bar dataKey="lowerWick" stackId="candle" stroke="none" radius={0}>
            {transformed.map((d, i) => (
              <Cell key={i} fill={d.isGreen ? 'rgba(16,185,129,0.6)' : 'rgba(244,63,94,0.6)'} />
            ))}
          </Bar>

          {/* Candle body */}
          <Bar dataKey="body" stackId="candle" stroke="none" radius={[1, 1, 0, 0]}>
            {transformed.map((d, i) => (
              <Cell key={i} fill={d.isGreen ? GREEN : RED} opacity={0.9} />
            ))}
          </Bar>

          {/* Upper wick */}
          <Bar dataKey="upperWick" stackId="candle" stroke="none" radius={0}>
            {transformed.map((d, i) => (
              <Cell key={i} fill={d.isGreen ? 'rgba(16,185,129,0.6)' : 'rgba(244,63,94,0.6)'} />
            ))}
          </Bar>
        </ComposedChart>
      </ResponsiveContainer>

      {/* Volume bars */}
      <ResponsiveContainer width="100%" height={50}>
        <ComposedChart data={transformed} margin={{ top: 0, right: 10, left: -15, bottom: 0 }}>
          <XAxis dataKey="date" hide />
          <YAxis hide />
          <Bar dataKey="volNorm" radius={[2, 2, 0, 0]} maxBarSize={12}>
            {transformed.map((d, i) => (
              <Cell key={i} fill={d.isGreen ? 'rgba(16,185,129,0.4)' : 'rgba(244,63,94,0.4)'} />
            ))}
          </Bar>
        </ComposedChart>
      </ResponsiveContainer>
      <div style={{ textAlign: 'center', color: MUTED, fontSize: '0.7rem', fontFamily: MONO_FONT, marginTop: -4 }}>
        Volume
      </div>
    </div>
  );
};

// ─── B) EquityDrawdownChart ────────────────────────────────────────────────────
const EquityTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: 'rgba(7,9,15,0.97)',
      border: `1px solid rgba(0,243,255,0.2)`,
      borderRadius: 8,
      padding: '0.65rem 0.9rem',
      fontFamily: MONO_FONT,
      fontSize: '0.75rem',
      lineHeight: 1.8,
    }}>
      <div style={{ color: MUTED, marginBottom: 2 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(2) : p.value}
        </div>
      ))}
    </div>
  );
};

export const EquityDrawdownChart = ({ capitalHistory = [] }) => {
  if (!capitalHistory.length) return (
    <div style={{ textAlign: 'center', color: MUTED, padding: '2rem', fontFamily: MONO_FONT, fontSize: '0.85rem' }}>
      Sem dados de equity disponíveis
    </div>
  );

  const initialVal = capitalHistory[0]?.value || 300;

  return (
    <div style={{ width: '100%' }}>
      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={capitalHistory} margin={{ top: 10, right: 10, left: -15, bottom: 0 }}>
          <defs>
            <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={ACCENT} stopOpacity={0.3} />
              <stop offset="95%" stopColor={ACCENT} stopOpacity={0} />
            </linearGradient>
            <linearGradient id="drawdownGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={RED} stopOpacity={0.5} />
              <stop offset="95%" stopColor={RED} stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
          <XAxis
            dataKey="day"
            tick={{ fill: MUTED, fontSize: 9, fontFamily: MONO_FONT }}
            tickLine={false}
            axisLine={{ stroke: BORDER }}
            interval={Math.floor(capitalHistory.length / 8)}
          />
          <YAxis
            tick={{ fill: MUTED, fontSize: 9, fontFamily: MONO_FONT }}
            tickLine={false}
            axisLine={false}
            tickFormatter={v => `R$${v.toFixed(0)}`}
            domain={['auto', 'auto']}
          />
          <Tooltip content={<EquityTooltip />} cursor={{ stroke: 'rgba(0,243,255,0.15)', strokeWidth: 1 }} />
          <ReferenceLine
            y={initialVal}
            stroke="rgba(255,255,255,0.2)"
            strokeDasharray="5 5"
            label={{ value: 'Break-even', fill: MUTED, fontSize: 9, position: 'left' }}
          />
          {/* Drawdown shaded area */}
          <Area
            type="monotone"
            dataKey="drawdown"
            name="Drawdown"
            stroke={RED}
            strokeWidth={1}
            fill="url(#drawdownGrad)"
            dot={false}
            activeDot={{ r: 4, fill: RED, strokeWidth: 0 }}
          />
          {/* Equity curve */}
          <Area
            type="monotone"
            dataKey="value"
            name="Capital"
            stroke={ACCENT}
            strokeWidth={2}
            fill="url(#equityGrad)"
            dot={false}
            activeDot={{ r: 4, fill: ACCENT, strokeWidth: 0 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
};

// ─── C) CorrelationHeatmap ────────────────────────────────────────────────────
// Color from red (-1) through gray (0) to green (+1), diagonal in blue
function corrColor(val) {
  if (Math.abs(val - 1.0) < 0.001) return '#3b82f6'; // diagonal
  if (val >= 0) {
    const g = Math.round(16 + val * (185 - 16));
    return `rgba(16,${g},130,${0.3 + val * 0.7})`;
  } else {
    const r = Math.round(100 + Math.abs(val) * (244 - 100));
    return `rgba(${r},63,94,${0.2 + Math.abs(val) * 0.8})`;
  }
}

export const CorrelationHeatmap = ({ matrix = [], tickers = [] }) => {
  if (!matrix.length || !tickers.length) return (
    <div style={{ textAlign: 'center', color: MUTED, padding: '2rem', fontFamily: MONO_FONT, fontSize: '0.85rem' }}>
      Sem dados de correlação disponíveis
    </div>
  );

  const n = tickers.length;
  const cellSize = Math.min(72, Math.floor(480 / n));
  const labelW = 60;
  const totalW = labelW + n * cellSize;
  const totalH = labelW + n * cellSize;

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg width={totalW} height={totalH} style={{ display: 'block', margin: '0 auto' }}>
        {/* Column labels (top) */}
        {tickers.map((t, j) => (
          <text
            key={`col-${j}`}
            x={labelW + j * cellSize + cellSize / 2}
            y={labelW - 6}
            textAnchor="middle"
            fill={MUTED}
            fontSize={Math.max(9, cellSize * 0.18)}
            fontFamily={MONO_FONT}
          >
            {t}
          </text>
        ))}
        {/* Row labels (left) */}
        {tickers.map((t, i) => (
          <text
            key={`row-${i}`}
            x={labelW - 6}
            y={labelW + i * cellSize + cellSize / 2 + 4}
            textAnchor="end"
            fill={MUTED}
            fontSize={Math.max(9, cellSize * 0.18)}
            fontFamily={MONO_FONT}
          >
            {t}
          </text>
        ))}
        {/* Cells */}
        {matrix.map((row, i) =>
          row.map((val, j) => {
            const x = labelW + j * cellSize;
            const y = labelW + i * cellSize;
            const bg = corrColor(val);
            const textColor = Math.abs(val) > 0.5 ? TEXT : MUTED;
            return (
              <g key={`${i}-${j}`}>
                <rect
                  x={x + 1}
                  y={y + 1}
                  width={cellSize - 2}
                  height={cellSize - 2}
                  fill={bg}
                  rx={3}
                  stroke="rgba(255,255,255,0.05)"
                  strokeWidth={0.5}
                />
                <title>{tickers[i]} / {tickers[j]}: {val.toFixed(3)}</title>
                <text
                  x={x + cellSize / 2}
                  y={y + cellSize / 2 + 4}
                  textAnchor="middle"
                  fill={textColor}
                  fontSize={Math.max(8, cellSize * 0.22)}
                  fontFamily={MONO_FONT}
                  fontWeight={600}
                >
                  {val.toFixed(2)}
                </text>
              </g>
            );
          })
        )}
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', justifyContent: 'center', marginTop: '1rem' }}>
        <span style={{ color: MUTED, fontSize: '0.75rem', fontFamily: MONO_FONT }}>-1.0</span>
        <div style={{
          width: 160,
          height: 12,
          borderRadius: 6,
          background: 'linear-gradient(to right, rgba(244,63,94,0.9), rgba(139,155,180,0.4), rgba(16,185,130,0.9))',
          border: `1px solid ${BORDER}`
        }} />
        <span style={{ color: MUTED, fontSize: '0.75rem', fontFamily: MONO_FONT }}>+1.0</span>
        <span style={{ color: '#3b82f6', fontSize: '0.75rem', fontFamily: MONO_FONT, marginLeft: 8 }}>■ Diagonal (1.0)</span>
      </div>
    </div>
  );
};

// ─── D) RiskMetricsPanel ──────────────────────────────────────────────────────
const METRIC_CONFIG = [
  { key: 'sharpe',         label: 'Sharpe Ratio',    good: v => v >= 0.5,  bad: v => v < 0.25, fmt: v => v.toFixed(2) },
  { key: 'sortino',        label: 'Sortino Ratio',   good: v => v >= 1.0,  bad: v => v < 0.5,  fmt: v => v.toFixed(2) },
  { key: 'calmar',         label: 'Calmar Ratio',    good: v => v >= 0.5,  bad: v => v < 0.2,  fmt: v => v.toFixed(2) },
  { key: 'max_drawdown_pct',label: 'Max Drawdown',   good: v => v > -5,    bad: v => v < -15,  fmt: v => `${v.toFixed(1)}%` },
  { key: 'var_95_daily',   label: 'VaR 95% (diário)',good: v => v > -5,    bad: v => v < -12,  fmt: v => `R$ ${v.toFixed(2)}` },
  { key: 'win_rate',       label: 'Win Rate',        good: v => v >= 0.4,  bad: v => v < 0.3,  fmt: v => `${(v*100).toFixed(1)}%` },
  { key: 'avg_win',        label: 'Avg Win',         good: v => v >= 2.5,  bad: v => v < 1.0,  fmt: v => `+${v.toFixed(1)}%` },
  { key: 'avg_loss',       label: 'Avg Loss',        good: v => v > -2.5,  bad: v => v < -4.0, fmt: v => `${v.toFixed(1)}%` },
];

export const RiskMetricsPanel = ({ metrics }) => {
  if (!metrics) return (
    <div style={{ textAlign: 'center', color: MUTED, padding: '2rem', fontFamily: MONO_FONT, fontSize: '0.85rem' }}>
      Carregando métricas...
    </div>
  );

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: '0.75rem',
    }}>
      {METRIC_CONFIG.map(({ key, label, good, bad, fmt }) => {
        const val = metrics[key];
        const isGood = val !== undefined && good(val);
        const isBad  = val !== undefined && bad(val);
        const color  = isGood ? GREEN : isBad ? RED : '#f59e0b';

        return (
          <div key={key} style={{
            background: `rgba(${isGood ? '16,185,129' : isBad ? '244,63,94' : '245,158,11'},0.06)`,
            border: `1px solid rgba(${isGood ? '16,185,129' : isBad ? '244,63,94' : '245,158,11'},0.2)`,
            borderRadius: 8,
            padding: '0.65rem 0.85rem',
          }}>
            <div style={{ color: MUTED, fontSize: '0.7rem', fontFamily: MONO_FONT, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              {label}
            </div>
            <div style={{ color, fontSize: '1.15rem', fontFamily: MONO_FONT, fontWeight: 700 }}>
              {val !== undefined ? fmt(val) : '—'}
            </div>
            <div style={{ marginTop: 4, height: 3, borderRadius: 2, background: 'rgba(255,255,255,0.07)' }}>
              <div style={{
                height: '100%',
                width: isGood ? '85%' : isBad ? '20%' : '55%',
                background: color,
                borderRadius: 2,
                transition: 'width 0.6s ease',
              }} />
            </div>
          </div>
        );
      })}
    </div>
  );
};

// ─── E) PositionSizingCalc ────────────────────────────────────────────────────
export const PositionSizingCalc = ({ capital = 300 }) => {
  const [riskPct,     setRiskPct]     = useState(2);
  const [stopDistPct, setStopDistPct] = useState(4);
  const [ticker,      setTicker]      = useState('');
  const [price,       setPrice]       = useState('');

  const riskAmount    = capital * riskPct / 100;
  const positionSize  = riskAmount / (stopDistPct / 100);
  const shares        = price && parseFloat(price) > 0 ? positionSize / parseFloat(price) : null;
  const kellyCriteria = (riskPct / stopDistPct).toFixed(3); // simplified

  const sliderStyle = {
    width: '100%',
    accentColor: ACCENT,
    cursor: 'pointer',
    background: 'transparent',
  };

  return (
    <div style={{ fontFamily: MONO_FONT, color: TEXT }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
        {/* Inputs */}
        <div>
          {/* Risk % slider */}
          <div style={{ marginBottom: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
              <label style={{ color: MUTED, fontSize: '0.8rem' }}>Risco por Trade</label>
              <span style={{ color: ACCENT, fontWeight: 700, fontSize: '0.9rem' }}>{riskPct.toFixed(1)}%</span>
            </div>
            <input
              type="range" min={0.5} max={5} step={0.1}
              value={riskPct}
              onChange={e => setRiskPct(parseFloat(e.target.value))}
              style={sliderStyle}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', color: MUTED, fontSize: '0.68rem', marginTop: 2 }}>
              <span>0.5%</span><span>2.5%</span><span>5.0%</span>
            </div>
          </div>

          {/* Stop distance slider */}
          <div style={{ marginBottom: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
              <label style={{ color: MUTED, fontSize: '0.8rem' }}>Distância do Stop</label>
              <span style={{ color: '#f59e0b', fontWeight: 700, fontSize: '0.9rem' }}>{stopDistPct.toFixed(1)}%</span>
            </div>
            <input
              type="range" min={1} max={10} step={0.5}
              value={stopDistPct}
              onChange={e => setStopDistPct(parseFloat(e.target.value))}
              style={{ ...sliderStyle, accentColor: '#f59e0b' }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', color: MUTED, fontSize: '0.68rem', marginTop: 2 }}>
              <span>1%</span><span>5%</span><span>10%</span>
            </div>
          </div>

          {/* Ticker + Price */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div>
              <label style={{ color: MUTED, fontSize: '0.8rem', display: 'block', marginBottom: 4 }}>Ticker</label>
              <input
                type="text" placeholder="PETR4"
                value={ticker}
                onChange={e => setTicker(e.target.value.toUpperCase())}
                style={{
                  width: '100%', background: 'rgba(255,255,255,0.05)', border: `1px solid ${BORDER}`,
                  borderRadius: 6, padding: '0.4rem 0.6rem', color: TEXT, fontFamily: MONO_FONT,
                  fontSize: '0.85rem', boxSizing: 'border-box',
                }}
              />
            </div>
            <div>
              <label style={{ color: MUTED, fontSize: '0.8rem', display: 'block', marginBottom: 4 }}>Preço (R$)</label>
              <input
                type="number" placeholder="38.20" step="0.01"
                value={price}
                onChange={e => setPrice(e.target.value)}
                style={{
                  width: '100%', background: 'rgba(255,255,255,0.05)', border: `1px solid ${BORDER}`,
                  borderRadius: 6, padding: '0.4rem 0.6rem', color: TEXT, fontFamily: MONO_FONT,
                  fontSize: '0.85rem', boxSizing: 'border-box',
                }}
              />
            </div>
          </div>
        </div>

        {/* Results */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
          {[
            { label: 'Capital Total', value: `R$ ${capital.toFixed(2)}`, color: MUTED },
            { label: 'Risco em R$',   value: `R$ ${riskAmount.toFixed(2)}`, color: RED },
            { label: 'Tamanho da Posição', value: `R$ ${positionSize.toFixed(2)}`, color: ACCENT },
            { label: 'Exposição / Capital', value: `${((positionSize / capital) * 100).toFixed(1)}%`, color: '#f59e0b' },
            shares !== null
              ? { label: `Qtd ${ticker || 'Ações'}`, value: `${Math.floor(shares)} ações`, color: GREEN }
              : { label: 'Qtd de Ações', value: 'Informe o preço', color: MUTED },
            { label: 'Kelly Simplificado', value: kellyCriteria, color: '#8b5cf6' },
          ].map(({ label, value, color }) => (
            <div key={label} style={{
              background: PANEL_BG,
              border: `1px solid ${BORDER}`,
              borderRadius: 8,
              padding: '0.55rem 0.85rem',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}>
              <span style={{ color: MUTED, fontSize: '0.75rem' }}>{label}</span>
              <span style={{ color, fontWeight: 700, fontSize: '0.9rem' }}>{value}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Warning bar */}
      {riskPct > 3 && (
        <div style={{
          marginTop: '1rem',
          background: 'rgba(244,63,94,0.1)',
          border: `1px solid rgba(244,63,94,0.3)`,
          borderRadius: 8,
          padding: '0.6rem 1rem',
          color: RED,
          fontSize: '0.8rem',
          display: 'flex',
          gap: '0.5rem',
          alignItems: 'center',
        }}>
          ⚠️ Risco acima de 3% por trade — verifique as regras do Guard-Rail antes de operar.
        </div>
      )}
    </div>
  );
};

// ─── F) AlertBadge ────────────────────────────────────────────────────────────
const ALERT_COLORS = {
  stop_hit:      { color: RED,     icon: '🔴', label: 'Stop Hit' },
  target_hit:    { color: GREEN,   icon: '🟢', label: 'Target Hit' },
  regime_change: { color: '#f59e0b', icon: '🟡', label: 'Regime' },
};

export const AlertBadge = ({ alerts = [] }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handler = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const count = alerts.length;

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <button
        onClick={() => setOpen(o => !o)}
        title="Alertas"
        style={{
          background: count > 0 ? 'rgba(244,63,94,0.1)' : 'rgba(255,255,255,0.05)',
          border: `1px solid ${count > 0 ? 'rgba(244,63,94,0.3)' : BORDER}`,
          borderRadius: 8,
          padding: '0.35rem 0.6rem',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: '0.4rem',
          position: 'relative',
          color: TEXT,
          fontFamily: MONO_FONT,
          fontSize: '0.8rem',
          transition: 'all 0.2s',
        }}
      >
        <span style={{ fontSize: '1rem' }}>🔔</span>
        {count > 0 && (
          <span style={{
            background: RED,
            color: '#fff',
            borderRadius: '50%',
            width: 18,
            height: 18,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '0.65rem',
            fontWeight: 700,
            animation: 'pulse 2s infinite',
          }}>
            {Math.min(count, 9)}
          </span>
        )}
      </button>

      {open && (
        <div style={{
          position: 'absolute',
          top: 'calc(100% + 8px)',
          right: 0,
          width: 280,
          background: 'rgba(10,14,23,0.98)',
          border: `1px solid ${BORDER}`,
          borderRadius: 12,
          boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
          backdropFilter: 'blur(16px)',
          zIndex: 9999,
          overflow: 'hidden',
        }}>
          <div style={{
            padding: '0.65rem 1rem',
            borderBottom: `1px solid ${BORDER}`,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}>
            <span style={{ color: TEXT, fontFamily: MONO_FONT, fontSize: '0.8rem', fontWeight: 700 }}>
              Alertas Recentes
            </span>
            <span style={{ color: MUTED, fontSize: '0.7rem', fontFamily: MONO_FONT }}>
              {count} alerta{count !== 1 ? 's' : ''}
            </span>
          </div>

          {alerts.length === 0 ? (
            <div style={{ padding: '1rem', color: MUTED, fontSize: '0.8rem', fontFamily: MONO_FONT, textAlign: 'center' }}>
              Nenhum alerta
            </div>
          ) : (
            <div style={{ maxHeight: 260, overflowY: 'auto' }}>
              {alerts.slice().reverse().map((a, i) => {
                const cfg = ALERT_COLORS[a.type] || { color: MUTED, icon: '⚪', label: a.type };
                return (
                  <div key={i} style={{
                    padding: '0.65rem 1rem',
                    borderBottom: `1px solid ${BORDER}`,
                    display: 'flex',
                    gap: '0.65rem',
                    alignItems: 'flex-start',
                  }}>
                    <span style={{ fontSize: '0.85rem', flexShrink: 0, marginTop: 2 }}>{cfg.icon}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 4 }}>
                        <span style={{ color: cfg.color, fontSize: '0.72rem', fontFamily: MONO_FONT, fontWeight: 700 }}>
                          {a.ticker}
                        </span>
                        <span style={{ color: MUTED, fontSize: '0.65rem', fontFamily: MONO_FONT, flexShrink: 0 }}>{a.time}</span>
                      </div>
                      <div style={{ color: TEXT, fontSize: '0.75rem', fontFamily: MONO_FONT, marginTop: 2, lineHeight: 1.4 }}>
                        {a.message}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.7; transform: scale(1.15); }
        }
      `}</style>
    </div>
  );
};

// ─── G) MarketRegimeBadge ─────────────────────────────────────────────────────
const REGIME_CONFIG = {
  bull:     { color: GREEN,     bg: 'rgba(16,185,129,0.12)', border: 'rgba(16,185,129,0.3)', icon: '🐂', label: 'Bull Market',  tip: 'IBOV acima da SMA-50. Estratégia: favorecer posições LONG com stops ampliados.' },
  bear:     { color: RED,       bg: 'rgba(244,63,94,0.12)',  border: 'rgba(244,63,94,0.3)',  icon: '🐻', label: 'Bear Market',  tip: 'IBOV abaixo da SMA-200. Estratégia: reduzir exposição, stops curtos, evitar compras.' },
  volatile: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.3)', icon: '⚡', label: 'Volátil',     tip: 'VIX elevado / gaps recorrentes. Guard-Rail restringe tamanho máximo de posição.' },
  lateral:  { color: MUTED,     bg: 'rgba(139,155,180,0.1)', border: 'rgba(139,155,180,0.2)', icon: '↔️', label: 'Lateral',    tip: 'Mercado sem tendência definida. Donchian Breakout tem menor assertividade — aguardar.' },
};

export const MarketRegimeBadge = ({ regime }) => {
  const [showTip, setShowTip] = useState(false);
  const cfg = REGIME_CONFIG[regime] || {
    color: MUTED, bg: PANEL_BG, border: BORDER, icon: '❓', label: regime || 'Indefinido',
    tip: 'Regime de mercado não identificado.'
  };

  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <button
        onMouseEnter={() => setShowTip(true)}
        onMouseLeave={() => setShowTip(false)}
        style={{
          background: cfg.bg,
          border: `1px solid ${cfg.border}`,
          borderRadius: 8,
          padding: '0.3rem 0.75rem',
          cursor: 'default',
          display: 'flex',
          alignItems: 'center',
          gap: '0.45rem',
          color: cfg.color,
          fontFamily: MONO_FONT,
          fontSize: '0.78rem',
          fontWeight: 700,
          letterSpacing: '0.03em',
          transition: 'all 0.2s',
        }}
      >
        <span style={{ fontSize: '0.9rem' }}>{cfg.icon}</span>
        <span>{cfg.label}</span>
      </button>

      {showTip && (
        <div style={{
          position: 'absolute',
          top: 'calc(100% + 8px)',
          right: 0,
          width: 240,
          background: 'rgba(10,14,23,0.98)',
          border: `1px solid ${cfg.border}`,
          borderRadius: 10,
          padding: '0.75rem',
          boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
          backdropFilter: 'blur(12px)',
          zIndex: 9999,
          fontSize: '0.75rem',
          fontFamily: MONO_FONT,
          color: TEXT,
          lineHeight: 1.6,
          pointerEvents: 'none',
        }}>
          <div style={{ color: cfg.color, fontWeight: 700, marginBottom: 6 }}>{cfg.icon} {cfg.label}</div>
          {cfg.tip}
        </div>
      )}
    </div>
  );
};
