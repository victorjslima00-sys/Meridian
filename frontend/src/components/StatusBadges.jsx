import React from 'react';
import { WifiOff, ShieldCheck, ShieldAlert, AlertTriangle } from 'lucide-react';

export const HEALTH_STATES = {
  online: { color: '#10b981', label: 'OPERACIONAL' },
  degraded: { color: '#f59e0b', label: 'DEGRADADO' },
  unprotected: { color: '#fb923c', label: 'SEM PROTEÇÃO' },
  stopped: { color: '#f43f5e', label: 'PARADO' },
};

export const HealthBadge = ({ status, connected }) => {
  if (!connected || !status) {
    return (
      <div className="conn-pill down" style={{ background: 'rgba(244,63,94,0.15)', borderColor: 'rgba(244,63,94,0.4)', color: '#f43f5e', border: '1px solid' }}>
        <WifiOff size={12} />
        FAIL-CLOSED ATIVO
      </div>
    );
  }

  const s = HEALTH_STATES[status.status] || {
    color: '#8b9bb4',
    label: (status.status || 'DESCONHECIDO').toUpperCase(),
  };

  const motivos = status.motivos_bloqueio || [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
      <div
        className="conn-pill"
        style={{
          background: `${s.color}20`,
          borderColor: `${s.color}50`,
          color: s.color,
          border: '1px solid',
        }}
      >
        <div
          style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            background: s.color,
            boxShadow: `0 0 6px ${s.color}`,
            flexShrink: 0,
          }}
        />
        {s.label}
      </div>
      {motivos.length > 0 && (
        <div style={{ fontSize: '0.62rem', color: 'var(--text-muted)', lineHeight: 1.4, paddingLeft: '0.2rem' }}>
          {motivos.join(' · ')}
        </div>
      )}
    </div>
  );
};

export const VerificationBadge = ({ status }) => {
  if (status === 'verified') {
    return (
      <span className="badge-verified" style={{ fontSize: '0.65rem', padding: '2px 6px', borderRadius: '3px', background: 'rgba(16,185,129,0.15)', color: '#10b981', border: '1px solid rgba(16,185,129,0.3)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
        <ShieldCheck size={10} /> AUDITORIA CONFORME
      </span>
    );
  }
  if (status === 'pending_approval') {
    return (
      <span className="badge-pending" style={{ fontSize: '0.65rem', padding: '2px 6px', borderRadius: '3px', background: 'rgba(245,158,11,0.15)', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.3)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
        <AlertTriangle size={10} /> AGUARDANDO APROVAÇÃO
      </span>
    );
  }
  return (
    <span className="badge-unverified" style={{ fontSize: '0.65rem', padding: '2px 6px', borderRadius: '3px', background: 'rgba(244,63,94,0.15)', color: '#f43f5e', border: '1px solid rgba(244,63,94,0.3)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
      <ShieldAlert size={10} /> NÃO VERIFICADO
    </span>
  );
};
