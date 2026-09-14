import React, { useState } from 'react';
import api from '../api';
import { formatCurrency, isValidNumber } from '../utils/formatters';
import { ProvenanceTooltip } from './ProvenanceTooltip';

// ─── Cofre de capital — depositar/retirar ──────────────────────────────────
// Track B & Hardening Institucional:
// - Nunca coerces saldo_operavel ou margem_operavel para 0 em caso de null ou desconexão.
// - Botões desabilitados quando connected === false (Fail-Closed ativo).
// - Exibe explicitamente 'Indisponível' ou 'Sem teto definido'.
const CapitalVault = ({ capital, onChanged, connected = true }) => {
  const [valor, setValor] = useState('');
  const [valorMargem, setValorMargem] = useState('');
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState(null);

  const margem = capital?.margem_operavel;
  const saldoOperavel = capital?.saldo_operavel;
  const isUnavailable = !connected || capital?.verification_status === 'unavailable';

  // Renderização honesta da margem
  let margemTexto = 'Indisponível';
  if (!isUnavailable) {
    if (margem == null) {
      margemTexto = 'Sem teto definido';
    } else if (isValidNumber(margem)) {
      margemTexto = formatCurrency(margem);
    }
  }

  // Renderização honesta do saldo operável
  let saldoTexto = 'Indisponível';
  if (!isUnavailable && isValidNumber(saldoOperavel)) {
    saldoTexto = formatCurrency(saldoOperavel);
  }

  const isActionDisabled = loading || isUnavailable;

  const definirMargem = async () => {
    if (isUnavailable) {
      setMsg({ tipo: 'erro', texto: 'Operação bloqueada: dados de capital indisponíveis (Fail-Closed ativo).' });
      return;
    }
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
          : `Teto de exposição do bot definido em ${formatCurrency(v)}.`,
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
    if (isUnavailable) {
      setMsg({ tipo: 'erro', texto: 'Operação bloqueada: dados de capital indisponíveis (Fail-Closed ativo).' });
      return;
    }
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
          ? `${formatCurrency(v)} liberados para o bot operar.`
          : `${formatCurrency(v)} reservados, fora do alcance do bot.`,
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
        disabled={isActionDisabled}
        style={{
          width: '100%',
          background: 'rgba(0,0,0,0.3)',
          border: '1px solid var(--border)',
          color: '#fff',
          padding: '0.5rem',
          borderRadius: '4px',
          fontSize: '0.85rem',
          fontFamily: 'JetBrains Mono, monospace',
          fontVariantNumeric: 'tabular-nums',
          opacity: isActionDisabled ? 0.6 : 1,
        }}
      />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
        <button
          onClick={() => executar('retirar')}
          disabled={isActionDisabled}
          title={!connected ? 'Operações bloqueadas em modo Fail-Closed' : 'Move do saldo livre do bot para o cofre reservado'}
          style={{
            background: 'rgba(244,63,94,0.1)',
            border: '1px solid var(--red)',
            color: 'var(--red)',
            padding: '0.6rem',
            borderRadius: '4px',
            fontWeight: 800,
            fontSize: '0.8rem',
            cursor: isActionDisabled ? 'not-allowed' : 'pointer',
            opacity: isActionDisabled ? 0.5 : 1,
          }}
        >
          {loading ? '...' : 'RETIRAR'}
        </button>
        <button
          onClick={() => executar('depositar')}
          disabled={isActionDisabled}
          title={!connected ? 'Operações bloqueadas em modo Fail-Closed' : 'Move do cofre reservado para o saldo livre do bot'}
          style={{
            background: 'rgba(16,185,129,0.1)',
            border: '1px solid var(--green)',
            color: 'var(--green)',
            padding: '0.6rem',
            borderRadius: '4px',
            fontWeight: 800,
            fontSize: '0.8rem',
            cursor: isActionDisabled ? 'not-allowed' : 'pointer',
            opacity: isActionDisabled ? 0.5 : 1,
          }}
        >
          {loading ? '...' : 'DEPOSITAR'}
        </button>
      </div>

      {/* ── Margem operável (teto de exposição do bot) ── */}
      <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '0.65rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.78rem' }}>
          <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
            Margem operável (teto)
            {capital?.provenance && <ProvenanceTooltip provenance={capital.provenance} label="Margem Operável" />}
          </span>
          <strong className="mono tabular-nums" style={{ color: margemTexto === 'Indisponível' ? '#f59e0b' : '#fff' }}>
            {margemTexto}
          </strong>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.78rem' }}>
          <span style={{ color: 'var(--text-muted)' }}>Operável p/ novas entradas</span>
          <strong className="mono tabular-nums" style={{ color: saldoTexto === 'Indisponível' ? '#f59e0b' : '#fff' }}>
            {saldoTexto}
          </strong>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '0.5rem' }}>
          <input
            type="number"
            value={valorMargem}
            onChange={(e) => setValorMargem(e.target.value)}
            placeholder="Novo teto em R$"
            min="0"
            step="0.01"
            disabled={isActionDisabled}
            style={{
              width: '100%',
              background: 'rgba(0,0,0,0.3)',
              border: '1px solid var(--border)',
              color: '#fff',
              padding: '0.5rem',
              borderRadius: '4px',
              fontSize: '0.85rem',
              fontFamily: 'JetBrains Mono, monospace',
              fontVariantNumeric: 'tabular-nums',
              opacity: isActionDisabled ? 0.6 : 1,
            }}
          />
          <button
            onClick={definirMargem}
            disabled={isActionDisabled}
            title={!connected ? 'Operações bloqueadas em modo Fail-Closed' : 'Teto de exposição total do bot'}
            style={{
              background: 'rgba(197,160,89,0.15)',
              border: '1px solid #C5A059',
              color: '#DFBF7A',
              padding: '0.6rem 0.8rem',
              borderRadius: '4px',
              fontWeight: 800,
              fontSize: '0.8rem',
              cursor: isActionDisabled ? 'not-allowed' : 'pointer',
              opacity: isActionDisabled ? 0.5 : 1,
            }}
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
