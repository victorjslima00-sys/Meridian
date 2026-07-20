import React, { useState, useEffect } from 'react';
import api from './api';
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { TrendingUp, TrendingDown, Clock, Volume2 } from 'lucide-react';


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
    api.get(`/history/${ticker}?limit=90`)
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

// Curva de patrimônio real — plota exatamente o que /api/equity_snapshots
// devolve (honest-dashboard Bloco 3). Nenhum Sharpe/Drawdown/Alpha/
// benchmark aparece aqui: esses números não vêm calculados de forma
// confiável do backend ainda (ver ressalva no PR) — mostrar um valor
// fabricado ao lado do gráfico é exatamente o problema que esta
// iniciativa existe para eliminar.
export const PortfolioChart = () => {
  const [snapshots, setSnapshots] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api.get('/equity_snapshots')
      .then(res => {
        if (!cancelled) setSnapshots(res.data?.snapshots || []);
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="chart-placeholder">
        <div className="spinner-sm" />
        <span>Carregando curva de patrimônio...</span>
      </div>
    );
  }

  if (snapshots.length === 0) {
    return (
      <div className="chart-placeholder">
        <span style={{ color: '#8b9bb4' }}>
          Ainda sem snapshot de patrimônio (1 por dia de pregão — aguarde o primeiro ciclo).
        </span>
      </div>
    );
  }

  const first = snapshots[0].equity;
  const last = snapshots[snapshots.length - 1].equity;
  const isGain = last >= first;
  const color = isGain ? '#10b981' : '#f43f5e';

  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={snapshots} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
        <defs>
          <linearGradient id="portfolioGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.3} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.03)" vertical={false} />
        <XAxis dataKey="date" tick={{ fill: '#8b9bb4', fontSize: 9 }} tickLine={false} axisLine={false} />
        <YAxis tick={{ fill: '#8b9bb4', fontSize: 9 }} tickLine={false} axisLine={false} tickFormatter={v => `R$${v.toFixed(0)}`} domain={['auto', 'auto']} />
        <Tooltip content={<DarkTooltip />} cursor={{ stroke: 'rgba(0, 243, 255, 0.4)', strokeWidth: 1, strokeDasharray: '4 4' }} />
        <Area type="monotone" dataKey="equity" name="Patrimônio" stroke={color} strokeWidth={3} fill="url(#portfolioGrad)" activeDot={{ r: 6, fill: '#000', stroke: color, strokeWidth: 2 }} />
      </AreaChart>
    </ResponsiveContainer>
  );
};
