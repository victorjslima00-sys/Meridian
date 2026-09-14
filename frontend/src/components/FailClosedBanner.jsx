import React from 'react';
import { ShieldAlert, WifiOff } from 'lucide-react';

export const FailClosedBanner = ({ connected, apiError }) => {
  if (connected && !apiError) return null;

  let errorDetail = 'Comunicação interrompida com o gateway B3 / Backend.';
  if (apiError) {
    if (apiError.includes('502')) {
      errorDetail = 'Erro de Comunicação com Servidor (502 Bad Gateway) — Provedor B3 indisponível.';
    } else if (apiError.includes('503')) {
      errorDetail = 'Serviço Temporariamente Indisponível (503 Service Unavailable).';
    } else if (apiError.toLowerCase().includes('timeout') || apiError.includes('ECONNABORTED')) {
      errorDetail = 'Tempo limite de resposta esgotado (Timeout) — Gateway B3 inativo.';
    } else {
      errorDetail = apiError;
    }
  }

  return (
    <div
      role="alert"
      className="fail-closed-banner"
      style={{
        width: '100%',
        background: 'linear-gradient(90deg, rgba(244,63,94,0.18) 0%, rgba(31,10,18,0.95) 100%)',
        border: '1px solid rgba(244,63,94,0.5)',
        borderLeft: '5px solid #f43f5e',
        borderRadius: '6px',
        padding: '0.75rem 1.25rem',
        marginBottom: '1rem',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '1rem',
        boxShadow: '0 4px 20px rgba(244,63,94,0.2)',
        animation: 'fadeIn 0.3s ease-out',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
        <div
          style={{
            background: 'rgba(244,63,94,0.2)',
            border: '1px solid rgba(244,63,94,0.4)',
            borderRadius: '50%',
            padding: '0.5rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#f43f5e',
          }}
        >
          <ShieldAlert size={20} />
        </div>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <strong style={{ color: '#fff', fontSize: '0.9rem', letterSpacing: '0.5px' }}>
              PROTEÇÃO FAIL-CLOSED ATIVADA — DADOS DE MERCADO INDISPONÍVEIS
            </strong>
            <span
              style={{
                fontSize: '0.65rem',
                fontWeight: 800,
                background: '#f43f5e',
                color: '#fff',
                padding: '2px 6px',
                borderRadius: '3px',
                letterSpacing: '0.5px',
              }}
            >
              FAIL-CLOSED ATIVO
            </span>
          </div>
          <p style={{ margin: 0, fontSize: '0.75rem', color: '#fda4af', marginTop: '0.15rem' }}>
            {errorDetail} Operações bloqueadas e valores congelados sem coerção a zero.
          </p>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexShrink: 0 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
            fontSize: '0.7rem',
            color: '#f43f5e',
            background: 'rgba(0,0,0,0.4)',
            padding: '0.3rem 0.6rem',
            borderRadius: '4px',
            border: '1px solid rgba(244,63,94,0.3)',
            fontWeight: 700,
          }}
        >
          <WifiOff size={14} /> SEM CONEXÃO
        </div>
      </div>
    </div>
  );
};

export default FailClosedBanner;
