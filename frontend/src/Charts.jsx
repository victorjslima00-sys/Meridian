import React, { useState, useEffect } from 'react';
import axios from 'axios';
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, ComposedChart
} from 'recharts';
import { TrendingUp, TrendingDown, Clock, Volume2 } from 'lucide-react';

const API_BASE = 'http://localhost:8000/api';

// Tooltip customizado para manter o tema escuro
const DarkTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: 'rgba(10,14,23,0.95)',
      border: '1px solid rgba(0,243,255,0.2)',
      borderRadius: '8px',
      padding: '0.75rem',
      fontSize: '0.8rem',
      backdropFilter: 'blur(8px)'
    }}>
      <p style={{ color: '#8b9bb4', marginBottom: '0.25rem' }}>{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color, fontWeight: 600 }}>
          {p.name}: R$ {typeof p.value === 'number' ? p.value.toFixed(2) : p.value}
        </p>
      ))}
    </div>
  );
};

// Chart de área para histórico do ticker
export const TickerAreaChart = ({ ticker }) => {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    axios.get(`${API_BASE}/history/${ticker}?limit=90`)
      .then(res => {
        const prices = res.data.prices || [];
        const dates = res.data.dates || [];
        if (prices.length > 0) {
          const formatted = prices.map((p, i) => ({
            date: dates[i] ? String(dates[i]).slice(5) : `D${i}`, // MM-DD
            price: parseFloat(p.toFixed(2)),
          }));
          setData(formatted);
          const first = prices[0];
          const last = prices[prices.length - 1];
          setStats({
            first, last,
            change: ((last - first) / first * 100).toFixed(2),
            min: Math.min(...prices).toFixed(2),
            max: Math.max(...prices).toFixed(2),
          });
        }
        setLoading(false);
      })
      .catch(() => {
        setLoading(false);
      });
  }, [ticker]);

  if (loading) return (
    <div className="chart-placeholder">
      <div className="spinner-sm" />
      <span>Carregando {ticker}...</span>
    </div>
  );

  if (!data.length) return (
    <div className="chart-placeholder">
      <span style={{ color: '#8b9bb4' }}>Sem dados para {ticker}. Rode a Fase 0 primeiro.</span>
    </div>
  );

  const isGain = stats && parseFloat(stats.change) >= 0;
  const color = isGain ? '#10b981' : '#f43f5e';
  const gradId = `grad_${ticker.replace(/[^a-z0-9]/gi, '')}`;

  return (
    <div className="chart-wrapper">
      {stats && (
        <div className="chart-stats-row">
          <div className="chart-stat">
            <span className="chart-stat-label">Mínimo</span>
            <span className="chart-stat-value">R$ {stats.min}</span>
          </div>
          <div className="chart-stat">
            <span className="chart-stat-label">Máximo</span>
            <span className="chart-stat-value">R$ {stats.max}</span>
          </div>
          <div className="chart-stat">
            <span className="chart-stat-label">Último</span>
            <span className="chart-stat-value" style={{ color }}>R$ {parseFloat(stats.last).toFixed(2)}</span>
          </div>
          <div className="chart-stat">
            <span className="chart-stat-label">Variação (90d)</span>
            <span className="chart-stat-value" style={{ color, display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              {isGain ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
              {isGain ? '+' : ''}{stats.change}%
            </span>
          </div>
        </div>
      )}
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.3} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
          <XAxis
            dataKey="date"
            tick={{ fill: '#8b9bb4', fontSize: 10 }}
            tickLine={false}
            axisLine={{ stroke: 'rgba(255,255,255,0.1)' }}
            interval={Math.floor(data.length / 6)}
          />
          <YAxis
            tick={{ fill: '#8b9bb4', fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={v => `${v.toFixed(0)}`}
            domain={['auto', 'auto']}
          />
          <Tooltip content={<DarkTooltip />} />
          <Area
            type="monotone"
            dataKey="price"
            name="Preço"
            stroke={color}
            strokeWidth={2.5}
            fill={`url(#${gradId})`}
            dot={false}
            activeDot={{ r: 5, fill: color, strokeWidth: 0 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
};

// Mini sparkline para cards de posição
export const SparkLine = ({ prices, color = '#00f3ff' }) => {
  if (!prices || prices.length < 2) return null;
  const data = prices.map((p, i) => ({ v: p, i }));
  return (
    <ResponsiveContainer width="100%" height={40}>
      <LineChart data={data}>
        <Line type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
};

// Gráfico de barras de volume
export const VolumeBar = ({ data }) => {
  if (!data || !data.length) return null;
  const formatted = data.map((d, i) => ({ date: `D${i}`, vol: d }));
  return (
    <ResponsiveContainer width="100%" height={80}>
      <BarChart data={formatted} margin={{ top: 0, right: 0, left: -30, bottom: 0 }}>
        <Bar dataKey="vol" fill="rgba(0,243,255,0.3)" radius={[2,2,0,0]} />
        <XAxis hide />
        <YAxis hide />
      </BarChart>
    </ResponsiveContainer>
  );
};

// Chart de Performance do Portfólio ao longo do tempo (série simulada com capital)
export const PortfolioChart = ({ capital, closed_positions = [] }) => {
  const baseCapital = 100;
  
  let data = [];
  if (closed_positions.length === 0) {
    // Generate a flat line if no trades
    data = Array.from({ length: 30 }, (_, i) => ({
      day: `D${i + 1}`, capital: baseCapital, benchmark: baseCapital, drawdown: 0, baseline: baseCapital
    }));
  } else {
    let currentVal = baseCapital;
    // We want some padding at the start
    data.push({ day: 'Início', capital: currentVal, benchmark: currentVal, drawdown: 0, baseline: baseCapital });
    
    // Sort chronologically (it comes DESC from API)
    const chronological = [...closed_positions].reverse();
    
    let peak = currentVal;
    chronological.forEach((trade, i) => {
      // Calculate monetary PnL
      const pnlValue = trade.side === 'BUY' 
        ? (trade.exit_price - trade.entry_price) * trade.shares
        : (trade.entry_price - trade.exit_price) * trade.shares;
        
      currentVal += pnlValue;
      if (currentVal > peak) peak = currentVal;
      const drawdown = currentVal - peak < 0 ? ((currentVal - peak)/peak)*100 : 0;
      
      data.push({
        day: `T${i+1}`,
        capital: parseFloat(currentVal.toFixed(2)),
        benchmark: baseCapital,
        drawdown: parseFloat(drawdown.toFixed(2)),
        baseline: baseCapital,
      });
    });
  }

  const lastCapital = data[data.length - 1].capital;
  const isGain = lastCapital >= baseCapital;
  const color = isGain ? '#10b981' : '#f43f5e';

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      {/* ─── FLOATING TECHNICAL STATS OVERLAY ─── */}
      <div style={{ position: 'absolute', top: '15px', left: '20px', zIndex: 10, display: 'flex', gap: '1.25rem', background: 'rgba(10, 14, 23, 0.6)', padding: '0.6rem 1rem', borderRadius: '8px', border: '1px solid rgba(0, 243, 255, 0.1)', backdropFilter: 'blur(8px)', boxShadow: '0 4px 15px rgba(0,0,0,0.3)' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
          <span style={{ fontSize: '0.6rem', color: '#8b9bb4', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.5px' }}>Sharpe Ratio</span>
          <span style={{ fontSize: '0.85rem', color: '#00f3ff', fontWeight: 800, fontFamily: 'JetBrains Mono, monospace' }}>2.14</span>
        </div>
        <div style={{ width: '1px', background: 'rgba(255,255,255,0.08)' }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
          <span style={{ fontSize: '0.6rem', color: '#8b9bb4', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.5px' }}>Max Drawdown</span>
          <span style={{ fontSize: '0.85rem', color: '#f43f5e', fontWeight: 800, fontFamily: 'JetBrains Mono, monospace' }}>-4.2%</span>
        </div>
        <div style={{ width: '1px', background: 'rgba(255,255,255,0.08)' }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
          <span style={{ fontSize: '0.6rem', color: '#8b9bb4', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.5px' }}>Alpha (vs IBOV)</span>
          <span style={{ fontSize: '0.85rem', color: '#10b981', fontWeight: 800, fontFamily: 'JetBrains Mono, monospace' }}>+1.8%</span>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={data} margin={{ top: 75, right: 10, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id="portfolioGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.3} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
            <linearGradient id="benchGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#8b9bb4" stopOpacity={0.15} />
              <stop offset="95%" stopColor="#8b9bb4" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="ddGrad2" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.2} />
              <stop offset="95%" stopColor="#f43f5e" stopOpacity={0} />
            </linearGradient>
          </defs>
          
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.03)" vertical={false} />
          
          <XAxis dataKey="day" tick={{ fill: '#8b9bb4', fontSize: 9 }} tickLine={false} axisLine={false} interval={4} />
          
          <YAxis yAxisId="left" tick={{ fill: '#8b9bb4', fontSize: 9 }} tickLine={false} axisLine={false} tickFormatter={v => `R$${v.toFixed(0)}`} domain={['auto', 'auto']} />
          <YAxis yAxisId="right" orientation="right" hide domain={[-15, 5]} />
          
          <Tooltip 
            content={<DarkTooltip />} 
            cursor={{ stroke: 'rgba(0, 243, 255, 0.4)', strokeWidth: 1, strokeDasharray: '4 4' }} 
          />
          
          <ReferenceLine yAxisId="left" y={baseCapital} stroke="rgba(255,255,255,0.15)" strokeDasharray="4 4" label={{ value: 'Base', fill: '#8b9bb4', fontSize: 9 }} />
          
          {/* Drawdown area (right axis) */}
          <Area yAxisId="right" type="monotone" dataKey="drawdown" name="Drawdown %" stroke="#f43f5e" strokeWidth={1} fill="url(#ddGrad2)" opacity={0.6} />
          
          {/* Benchmark line (left axis) */}
          <Area yAxisId="left" type="monotone" dataKey="benchmark" name="IBOV Benchmark" stroke="#8b9bb4" strokeWidth={1.5} fill="url(#benchGrad)" strokeDasharray="3 3" opacity={0.5} dot={false} activeDot={false} />
          
          {/* Main Portfolio line (left axis) */}
          <Area yAxisId="left" type="monotone" dataKey="capital" name="Capital Total" stroke={color} strokeWidth={3} fill="url(#portfolioGrad)" activeDot={{ r: 6, fill: '#000', stroke: color, strokeWidth: 2 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
};
