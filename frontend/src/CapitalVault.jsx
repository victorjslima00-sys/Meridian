import React, { useState } from 'react';
import api from './api';

// ─── Cofre de capital — depositar/retirar já existiam prontos e testados
// no backend (POST /api/portfolio/depositar, /retirar) sem NENHUMA UI
// que os chamasse. É exatamente o controle que faltava: quanto capital
// fica exposto ao bot vs. reservado fora do alcance dele.
//
// Track B, 3a: os valores de "Reservado" e "Caixa Livre" já aparecem nos
// KPIs do topo do dashboard (mesma fonte, capital.patrimonio_reservado/
// saldo_livre) -- repeti-los aqui era a duplicação que o diagnóstico
// apontou. Este painel passa a mostrar só as ações.
//
// usabilidade 2e: ganhou o controle da margem operável (teto de exposição
// do bot). margem_operavel/saldo_operavel são exibidos SÓ aqui (um fato,
// um lugar) e vêm prontos de capital (calculados em get_portfolio() no
// backend — zero conta no navegador). O enforcement de verdade mora no
// executor/rotas; este controle só edita o valor.
const CapitalVault = ({ capital, onChanged }) => {
  const [valor, setValor] = useState('');
  const [valorMargem, setValorMargem] = useState('');
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState(null);

  const margem = capital?.margem_operavel;
  const saldoOperavel = capital?.saldo_operavel ?? 0;

  const definirMargem = async () => {
    const v = parseFloat(valorMargem);
    if (Number.isNaN(v) || v < 0) {
      setMsg({ tipo: 'erro', texto: 'Margem deve ser zero ou positiva.' });
      return;
    }
    setLoading(true);
    setMsg(null);
    try {
      await api.post('/portfolio/margem_operavel', { valor: v });
      setMsg({
        tipo: 'ok',
        texto: v === 0
          ? 'Margem zerada: novas entradas congeladas (saídas seguem gerenciadas).'
          : `Teto de exposição do bot definido em R$ ${v.toFixed(2)}.`,
      });
      setValorMargem('');
      if (onChanged) onChanged();
    } catch (err) {
      setMsg({ tipo: 'erro', texto: err.response?.data?.detail || err.message });
    } finally {
      setLoading(false);
    }
  };

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

      {/* ── Margem operável (teto de exposição do bot) ── */}
      <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '0.65rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem' }}>
          <span style={{ color: 'var(--text-muted)' }}>Margem operável (teto)</span>
          <strong className="mono">{margem == null ? 'sem teto' : `R$ ${margem.toFixed(2)}`}</strong>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem' }}>
          <span style={{ color: 'var(--text-muted)' }}>Operável p/ novas entradas</span>
          <strong className="mono">R$ {saldoOperavel.toFixed(2)}</strong>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '0.5rem' }}>
          <input
            type="number"
            value={valorMargem}
            onChange={(e) => setValorMargem(e.target.value)}
            placeholder="Novo teto em R$"
            min="0"
            step="0.01"
            style={{ width: '100%', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border)', color: '#fff', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem', fontFamily: 'JetBrains Mono, monospace' }}
          />
          <button
            onClick={definirMargem}
            disabled={loading}
            title="Teto de exposição total do bot: em posições + novas entradas nunca passam deste valor"
            style={{ background: 'rgba(59,130,246,0.1)', border: '1px solid #3b82f6', color: '#3b82f6', padding: '0.6rem 0.8rem', borderRadius: '4px', fontWeight: 800, fontSize: '0.8rem', cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.5 : 1 }}
          >
            {loading ? '...' : 'DEFINIR'}
          </button>
        </div>
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
