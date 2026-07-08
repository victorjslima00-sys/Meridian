import React, { useState, useEffect } from 'react';
import axios from 'axios';
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine
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
export const PortfolioChart = ({ capital }) => {
  // Gera dados históricos simulados baseados no capital atual
  const baseCapital = capital?.initial || 300;
  const currentCapital = capital?.current || 300;

  // Simula 30 dias de evolução usando os valores reais como âncoras
  const data = Array.from({ length: 30 }, (_, i) => {
    const progress = i / 29;
    const noise = (Math.sin(i * 0.8) * 0.02 + Math.cos(i * 1.3) * 0.01);
    const value = baseCapital + (currentCapital - baseCapital) * progress + baseCapital * noise;
    return {
      day: `D${i + 1}`,
      capital: parseFloat(value.toFixed(2)),
      baseline: baseCapital,
    };
  });

  const isGain = currentCapital >= baseCapital;
  const color = isGain ? '#10b981' : '#f43f5e';

  return (
    <ResponsiveContainer width="100%" height={180}>
      <AreaChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
        <defs>
          <linearGradient id="portfolioGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.25} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
        <XAxis dataKey="day" tick={{ fill: '#8b9bb4', fontSize: 9 }} tickLine={false} axisLine={false} interval={4} />
        <YAxis tick={{ fill: '#8b9bb4', fontSize: 9 }} tickLine={false} axisLine={false} tickFormatter={v => `R$${v.toFixed(0)}`} domain={['auto', 'auto']} />
        <Tooltip content={<DarkTooltip />} />
        <ReferenceLine y={baseCapital} stroke="rgba(255,255,255,0.15)" strokeDasharray="4 4" label={{ value: 'Base', fill: '#8b9bb4', fontSize: 9 }} />
        <Area type="monotone" dataKey="capital" name="Capital" stroke={color} strokeWidth={2} fill="url(#portfolioGrad)" dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
};
