import React, { useState, useEffect } from 'react';
import api from './api';
import {
  AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';

// honest-dashboard Bloco 4: removidos TickerAreaChart (chamava
// /history/{ticker}, rota que nunca existiu no backend — 404 silencioso
// sempre), SparkLine e VolumeBar (nunca importados em lugar nenhum).

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
