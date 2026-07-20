import React, { useState } from 'react';
import api from './api';

// ─── Cofre de capital — depositar/retirar já existiam prontos e testados
// no backend (POST /api/portfolio/depositar, /retirar) sem NENHUMA UI
// que os chamasse. É exatamente o controle que faltava: quanto capital
// fica exposto ao bot vs. reservado fora do alcance dele.
const formatMoeda = (v) => `R$ ${(v ?? 0).toFixed(2)}`;

const CapitalVault = ({ capital, onChanged }) => {
  const [valor, setValor] = useState('');
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState(null);

  const reservado = capital?.patrimonio_reservado ?? 0;
  const livreNoBot = capital?.saldo_livre ?? 0;

  const executar = async (acao) => {
    const v = parseFloat(valor);
    if (!v || v <= 0) {
      setMsg({ tipo: 'erro', texto: 'Digite um valor positivo.' });
      return;
    }
    setLoading(true);
    setMsg(null);
    try {
      const rota = acao === 'depositar' ? '/portfolio/depositar' : '/portfolio/retirar';
      await api.post(rota, { valor: v });
      setMsg({
        tipo: 'ok',
        texto: acao === 'depositar'
          ? `R$ ${v.toFixed(2)} liberados para o bot operar.`
          : `R$ ${v.toFixed(2)} reservados, fora do alcance do bot.`,
      });
      setValor('');
      if (onChanged) onChanged();
    } catch (err) {
      setMsg({ tipo: 'erro', texto: err.response?.data?.detail || err.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem' }}>
        <span style={{ color: 'var(--text-muted)' }}>Reservado (fora do bot)</span>
        <strong className="mono">{formatMoeda(reservado)}</strong>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem' }}>
        <span style={{ color: 'var(--text-muted)' }}>Livre no bot</span>
        <strong className="mono">{formatMoeda(livreNoBot)}</strong>
      </div>

      <input
        type="number"
        value={valor}
        onChange={(e) => setValor(e.target.value)}
        placeholder="Valor em R$"
        min="0"
        step="0.01"
        style={{ width: '100%', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border)', color: '#fff', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem', fontFamily: 'JetBrains Mono, monospace' }}
      />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
        <button
          onClick={() => executar('retirar')}
          disabled={loading}
          title="Move do saldo livre do bot para o cofre reservado"
          style={{ background: 'rgba(244,63,94,0.1)', border: '1px solid var(--red)', color: 'var(--red)', padding: '0.6rem', borderRadius: '4px', fontWeight: 800, fontSize: '0.8rem', cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.5 : 1 }}
        >
          {loading ? '...' : 'RETIRAR'}
        </button>
        <button
          onClick={() => executar('depositar')}
          disabled={loading}
          title="Move do cofre reservado para o saldo livre do bot"
          style={{ background: 'rgba(16,185,129,0.1)', border: '1px solid var(--green)', color: 'var(--green)', padding: '0.6rem', borderRadius: '4px', fontWeight: 800, fontSize: '0.8rem', cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.5 : 1 }}
        >
          {loading ? '...' : 'DEPOSITAR'}
        </button>
      </div>

      {msg && (
        <div style={{ fontSize: '0.72rem', color: msg.tipo === 'erro' ? '#f43f5e' : '#10b981', lineHeight: 1.4 }}>
          {msg.texto}
        </div>
      )}
    </div>
  );
};

export default CapitalVault;
