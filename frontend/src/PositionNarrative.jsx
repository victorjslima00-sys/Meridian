import React from 'react';
import { TrendingUp, TrendingDown, ChevronRight, X } from 'lucide-react';

// ─── Narrativa por posição — mesmo dado real de sempre (alocado,
// current_price, pnl_monetario vêm prontos da API, honest-dashboard
// Bloco 2), só reescrito em linguagem natural em vez de tabela. Nenhum
// número novo é calculado aqui — é formatação de exibição, igual ao
// toLocaleString() já usado em ActiveTradeDetails.jsx.

const formatMoeda = (v) => `R$ ${(v ?? 0).toFixed(2)}`;
const formatData = (iso) => {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' });
};

// ai_rationale vem como "tese do analista | parecer do risk manager"
// (mesmo padrão já usado em ActiveTradeDetails.jsx).
const extrairTese = (rationale) => {
  if (!rationale) return null;
  const tese = rationale.split('|')[0]?.trim();
  return tese || null;
};

// exit_reason é um dos 4 valores literais que o backend grava (ver
// backend/app/main.py: "Take Profit hit at X" / "Stop Loss hit at X" /
// "Encerrado manualmente pelo usuário" / "EMERGENCY STOP") — mapeado
// pra português natural. Fallback mostra o texto cru, nunca inventa.
const descreverMotivoSaida = (reason) => {
  if (!reason) return 'motivo não registrado';
  if (reason.startsWith('Take Profit hit')) return 'o alvo (take profit) foi atingido';
  if (reason.startsWith('Stop Loss hit')) return 'o stop loss foi acionado';
  if (reason === 'Encerrado manualmente pelo usuário') return 'você encerrou manualmente';
  if (reason === 'EMERGENCY STOP') return 'a parada de emergência foi acionada';
  return reason;
};

const PositionNarrativeCard = ({ pos, onClick, onClose }) => {
  const isLong = pos.side === 'BUY';
  const isClosed = pos.status === 'closed';
  const isGain = (pos.pnl_pct || 0) >= 0;
  const cor = isGain ? '#10b981' : '#f43f5e';
  const tese = extrairTese(pos.ai_rationale);

  const acaoEntrada = isLong ? 'comprada' : 'vendida (a descoberto)';
  const alvoDesc = isLong ? 'valorizar até' : 'recuar até';
  const stopDesc = isLong ? 'cair até' : 'subir até';

  return (
    <div
      onClick={onClick}
      style={{
        padding: '1.25rem',
        borderRadius: '10px',
        background: 'rgba(255,255,255,0.02)',
        borderTop: `1px solid ${cor}30`,
        borderRight: `1px solid ${cor}30`,
        borderBottom: `1px solid ${cor}30`,
        borderLeft: `3px solid ${cor}`,
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.6rem',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <span className="ticker-badge" style={{ fontSize: '0.95rem' }}>{pos.ticker}</span>
          <span
            style={{
              fontSize: '0.68rem', fontWeight: 700, padding: '0.15rem 0.5rem', borderRadius: '4px',
              background: isLong ? 'rgba(16,185,129,0.12)' : 'rgba(244,63,94,0.12)',
              color: isLong ? '#10b981' : '#f43f5e',
              border: `1px solid ${isLong ? 'rgba(16,185,129,0.3)' : 'rgba(244,63,94,0.3)'}`,
            }}
          >
            {isLong ? 'COMPRA' : 'VENDA'}
          </span>
          <span style={{ fontSize: '0.68rem', fontWeight: 700, padding: '0.15rem 0.5rem', borderRadius: '4px', background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)' }}>
            SWING TRADE
          </span>
          {isClosed && (
            <span style={{ fontSize: '0.68rem', fontWeight: 700, padding: '0.15rem 0.5rem', borderRadius: '4px', background: 'rgba(139,155,180,0.12)', color: '#8b9bb4' }}>
              FECHADA
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontWeight: 800, fontSize: '1.1rem', color: cor, display: 'flex', alignItems: 'center', gap: '0.3rem', justifyContent: 'flex-end' }}>
              {isGain ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
              {isGain ? '+' : ''}{formatMoeda(pos.pnl_monetario)}
            </div>
            <div style={{ fontSize: '0.72rem', color: cor }}>
              ({isGain ? '+' : ''}{(pos.pnl_pct || 0).toFixed(2)}%)
            </div>
          </div>
          {!isClosed && onClose && (
            <button
              onClick={(e) => { e.stopPropagation(); onClose(pos.id); }}
              title="Encerrar manualmente"
              style={{ background: 'transparent', border: 'none', cursor: 'pointer', opacity: 0.7, padding: '0.2rem' }}
            >
              <X size={16} color="#f43f5e" />
            </button>
          )}
          <ChevronRight size={16} color="#8b9bb4" />
        </div>
      </div>

      {isClosed ? (
        <p style={{ margin: 0, fontSize: '0.85rem', lineHeight: 1.6, color: '#cbd5e1' }}>
          Posição {acaoEntrada} em <strong>{pos.ticker}</strong>, aberta em {formatData(pos.entry_date)} a{' '}
          <strong>{formatMoeda(pos.entry_price)}</strong> e fechada em {formatData(pos.exit_date)} a{' '}
          <strong>{formatMoeda(pos.exit_price)}</strong>, porque {descreverMotivoSaida(pos.exit_reason)}. Resultado:{' '}
          {isGain ? 'ganho' : 'perda'} de{' '}
          <strong style={{ color: cor }}>{formatMoeda(Math.abs(pos.pnl_monetario || 0))}</strong> sobre os{' '}
          {formatMoeda((pos.shares || 0) * (pos.entry_price || 0))} alocados.
        </p>
      ) : (
        <p style={{ margin: 0, fontSize: '0.85rem', lineHeight: 1.6, color: '#cbd5e1' }}>
          Posição {acaoEntrada} em <strong>{pos.ticker}</strong>, aberta em {formatData(pos.entry_date)} a{' '}
          <strong>{formatMoeda(pos.entry_price)}</strong>, com <strong>{formatMoeda(pos.alocado)}</strong> alocados
          ({(pos.shares || 0).toFixed(5)} ações). A meta é o preço {alvoDesc} <strong>{formatMoeda(pos.target_price)}</strong>;
          o stop protege caso o preço {stopDesc} <strong>{formatMoeda(pos.stop_loss)}</strong>. Cotação atual:{' '}
          <strong>{formatMoeda(pos.current_price)}</strong> — {isGain ? 'ganho' : 'perda'} de{' '}
          <strong style={{ color: cor }}>{formatMoeda(Math.abs(pos.pnl_monetario || 0))}</strong> até aqui.
        </p>
      )}

      {tese && (
        <p style={{ margin: 0, fontSize: '0.8rem', lineHeight: 1.5, color: 'var(--text-muted)', fontStyle: 'italic', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '0.5rem' }}>
          Tese da IA: {tese}
        </p>
      )}
    </div>
  );
};

const PositionNarrative = ({ positions, onSelectTrade, onClosePosition, lastUpdatedLabel }) => {
  const ativas = positions?.active_positions || [];

  return (
    <div className="glass-panel" style={{ padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem' }}>
        <div>
          <h3 style={{ margin: 0, fontSize: '1.1rem' }}>Suas Posições</h3>
          <span className="muted-tag">O que está aberto agora, explicado — clique numa posição pra ver o dossiê completo</span>
        </div>
        {lastUpdatedLabel && (
          <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
            atualizado {lastUpdatedLabel}
          </span>
        )}
      </div>

      {ativas.length === 0 ? (
        <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
          Nenhuma posição aberta no momento. O robô segue varrendo o mercado em busca de um sinal com boa relação risco-retorno.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {ativas.map((pos) => (
            <PositionNarrativeCard key={pos.id || pos.ticker} pos={pos} onClick={() => onSelectTrade(pos)} onClose={onClosePosition} />
          ))}
        </div>
      )}
    </div>
  );
};

export const ClosedPositionsNarrative = ({ positions, onSelectTrade }) => {
  const fechadas = positions?.closed_positions || [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', maxHeight: '520px', overflowY: 'auto', paddingRight: '0.25rem' }}>
      {fechadas.length === 0 ? (
        <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
          Nenhuma operação fechada ainda.
        </div>
      ) : (
        fechadas.map((pos) => (
          <PositionNarrativeCard key={pos.id || pos.exit_date || pos.ticker} pos={pos} onClick={() => onSelectTrade(pos)} />
        ))
      )}
    </div>
  );
};

export default PositionNarrative;
