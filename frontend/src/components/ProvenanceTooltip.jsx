import React, { useState } from 'react';
import { Copy, Check, Info } from 'lucide-react';
import { formatDate } from '../utils/formatters';

export const ProvenanceTooltip = ({ provenance, label, children }) => {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const hash = provenance?.source_sha256;
  const is64Hex = typeof hash === 'string' && /^[a-f0-9]{64}$/i.test(hash);
  const status = provenance?.verification_status;
  const isVerified = status === 'verified' && is64Hex;
  const isUnverified = provenance?.verification_status !== 'verified' || !is64Hex;
  const isPending = status === 'pending_approval';
  const isUnavailable = status === 'unavailable';

  const handleCopy = async (e) => {
    e.stopPropagation();
    if (!hash) return;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(hash);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    } catch {
      // Fallback if clipboard API rejects
      setCopied(false);
    }
  };

  const truncatedHash = is64Hex
    ? `${hash.slice(0, 8)}...${hash.slice(-8)}`
    : (typeof hash === 'string' ? `${hash.slice(0, 12)} (inválido)` : null);

  return (
    <div
      className="provenance-wrapper"
      style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      {children ? (
        children
      ) : (
        <button
          type="button"
          aria-label={`Proveniência de ${label || 'métrica'}`}
          onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
          style={{
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            padding: '2px',
            display: 'inline-flex',
            alignItems: 'center',
            color: isVerified ? '#10b981' : isPending ? '#f59e0b' : isUnavailable ? '#f43f5e' : '#8b9bb4',
          }}
        >
          <Info size={12} />
        </button>
      )}

      {open && (
        <div
          role="tooltip"
          className="provenance-popover"
          style={{
            position: 'absolute',
            bottom: '100%',
            left: '50%',
            transform: 'translateX(-50%)',
            marginBottom: '6px',
            width: '280px',
            zIndex: 1000,
            background: '#0B0F17',
            border: '1px solid rgba(197, 160, 89, 0.3)',
            borderRadius: '6px',
            boxShadow: '0 8px 24px rgba(0,0,0,0.85)',
            padding: '0.75rem',
            color: '#e2e8f0',
            fontSize: '0.72rem',
            lineHeight: 1.4,
            pointerEvents: 'auto',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.4rem', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '0.35rem' }}>
            <span style={{ fontWeight: 700, color: '#DFBF7A', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              {label || 'Proveniência do Dado'}
            </span>
            {isVerified ? (
              <span className="badge-verified" style={{ fontSize: '0.62rem', padding: '1px 5px', borderRadius: '3px', background: 'rgba(16,185,129,0.15)', color: '#10b981', border: '1px solid rgba(16,185,129,0.3)' }}>
                Auditoria Conforme
              </span>
            ) : isPending ? (
              <span className="badge-pending" style={{ fontSize: '0.62rem', padding: '1px 5px', borderRadius: '3px', background: 'rgba(245,158,11,0.15)', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.3)' }}>
                Aguardando Aprovação
              </span>
            ) : isUnavailable ? (
              <span className="badge-unavailable" style={{ fontSize: '0.62rem', padding: '1px 5px', borderRadius: '3px', background: 'rgba(244,63,94,0.15)', color: '#f43f5e', border: '1px solid rgba(244,63,94,0.3)' }}>
                Indisponível
              </span>
            ) : (
              <span className="badge-unverified" style={{ fontSize: '0.62rem', padding: '1px 5px', borderRadius: '3px', background: 'rgba(139,155,180,0.15)', color: '#8b9bb4', border: '1px solid rgba(139,155,180,0.3)' }}>
                {!is64Hex && hash ? 'Hash Inválido' : 'Não Verificado'}
              </span>
            )}
          </div>

          {!provenance ? (
            <div style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
              Sem Registro de Proveniência
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Origem: </span>
                <span style={{ fontFamily: 'JetBrains Mono, monospace' }}>
                  {provenance.source_ref || 'Origem indisponível'}
                </span>
              </div>

              {hash && (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
                  <div style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    <span style={{ color: 'var(--text-muted)' }}>SHA-256: </span>
                    <span style={{ fontFamily: 'JetBrains Mono, monospace', color: is64Hex ? '#DFBF7A' : '#f43f5e' }}>
                      {truncatedHash}
                    </span>
                  </div>
                  {is64Hex && (
                    <button
                      type="button"
                      onClick={handleCopy}
                      title="Copiar Hash Completo"
                      style={{
                        background: 'rgba(255,255,255,0.05)',
                        border: '1px solid rgba(255,255,255,0.1)',
                        color: copied ? '#10b981' : '#e2e8f0',
                        borderRadius: '3px',
                        padding: '2px 5px',
                        cursor: 'pointer',
                        fontSize: '0.65rem',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '2px',
                      }}
                    >
                      {copied ? <Check size={10} /> : <Copy size={10} />}
                      {copied ? 'Copiado!' : 'Copiar'}
                    </button>
                  )}
                </div>
              )}

              <div>
                <span style={{ color: 'var(--text-muted)' }}>Registrado em: </span>
                <span>{formatDate(provenance.observed_at || provenance.generated_at_utc)}</span>
              </div>

              {isUnverified && (
                <div style={{ color: isUnavailable ? '#f43f5e' : '#f59e0b', fontSize: '0.65rem', marginTop: '0.2rem', fontStyle: 'italic' }}>
                  {isUnavailable
                    ? 'Dado indisponível ou fonte não verificada (Fail-Closed ativo).'
                    : 'Registro descritivo da base local; sem homologação independente.'}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ProvenanceTooltip;
