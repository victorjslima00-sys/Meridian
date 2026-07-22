import React, { useEffect, useRef, useState } from 'react';
import { Terminal, Cpu } from 'lucide-react';

// ─── Log de Decisões (Live) — WebSocket /ws/logs ─────────────────────────
// usabilidade 2f: este estado morava no App e cada mensagem do WebSocket
// re-renderizava o dashboard INTEIRO (com o bot varrendo ~50 tickers, uma
// mensagem a cada 1-2s) — suspeita direta da lentidão e dos timeouts de
// captura sofridos no próprio diagnóstico. Agora o socket, o buffer de
// mensagens e o indicador CONECTADO vivem aqui: mensagem de log só
// re-renderiza este painel.
//
// O componente fica SEMPRE montado (App o renderiza com visible=false nas
// outras abas) para a conexão e o histórico sobreviverem à troca de aba —
// desmontar fecharia o socket e zeraria o buffer a cada navegação.
//
// Reconexão com backoff + timeout de inatividade vieram do Track B 3e
// (inalterados): o backend não envia ping, então 20s sem NENHUMA mensagem
// (nem o "conectado" inicial) = socket morto, fecha e cai na reconexão.
const DecisionLog = ({ visible }) => {
  const [logs, setLogs] = useState([
    { t: new Date().toLocaleTimeString(), sender: 'SISTEMA', msg: 'Conexão segura estabelecida.' }
  ]);
  const [wsConnected, setWsConnected] = useState(false);
  const termRef = useRef(null);

  const wsRef = useRef(null);
  const wsReconnectTimerRef = useRef(null);
  const wsInactivityTimerRef = useRef(null);
  const wsReconnectAttemptRef = useRef(0);
  const wsUnmountedRef = useRef(false);

  useEffect(() => {
    const WS_INACTIVITY_TIMEOUT_MS = 20000;
    const WS_MAX_BACKOFF_MS = 30000;
    // Reset explícito: em dev, o StrictMode monta -> desmonta -> monta de
    // novo sincronamente; sem este reset, a flag presa em true pulava toda
    // reconexão real (bug achado ao vivo no Track B 3e).
    wsUnmountedRef.current = false;

    const clearInactivityTimer = () => {
      if (wsInactivityTimerRef.current) clearTimeout(wsInactivityTimerRef.current);
    };

    const armInactivityTimer = () => {
      clearInactivityTimer();
      wsInactivityTimerRef.current = setTimeout(() => {
        setWsConnected(false);
        wsRef.current?.close();
      }, WS_INACTIVITY_TIMEOUT_MS);
    };

    const connect = () => {
      const ws = new window.WebSocket('ws://localhost:8000/ws/logs');
      wsRef.current = ws;

      ws.onopen = () => {
        wsReconnectAttemptRef.current = 0;
        setWsConnected(true);
        armInactivityTimer();
      };
      ws.onclose = () => {
        setWsConnected(false);
        clearInactivityTimer();
        if (wsUnmountedRef.current) return;
        const attempt = wsReconnectAttemptRef.current;
        const delay = Math.min(1000 * 2 ** attempt, WS_MAX_BACKOFF_MS);
        wsReconnectAttemptRef.current = attempt + 1;
        wsReconnectTimerRef.current = setTimeout(connect, delay);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (event) => {
        armInactivityTimer();
        const data = JSON.parse(event.data);
        setLogs(prev => [...prev.slice(-49), { t: new Date().toLocaleTimeString(), sender: data.agent.toUpperCase(), msg: data.msg }]);
      };
    };

    connect();

    return () => {
      wsUnmountedRef.current = true;
      clearInactivityTimer();
      if (wsReconnectTimerRef.current) clearTimeout(wsReconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, []);

  useEffect(() => {
    if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight;
  }, [logs]);

  return (
    <div className="page-section" style={{ display: visible ? 'block' : 'none' }}>
      <div className="page-title">
        <Cpu size={22} />
        <div>
          <h2>Comitê de IA Operacional</h2>
          <p>Orquestração e inferência de modelos quantitativos</p>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', border: '1px solid rgba(0, 243, 255, 0.2)', boxShadow: '0 10px 40px rgba(0,0,0,0.5)' }}>
        <div className="panel-header" style={{ padding: '0.75rem 1.25rem', borderBottom: '1px solid rgba(0, 243, 255, 0.1)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(0, 10, 20, 0.4)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Terminal size={16} color="#00f3ff" />
            <h3 style={{ margin: 0, fontSize: '0.85rem', color: '#fff', letterSpacing: '1px', textTransform: 'uppercase' }}>Log de Decisões (Live)</h3>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.7rem', color: wsConnected ? '#10b981' : '#f43f5e', fontWeight: 800 }}>
            <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: wsConnected ? '#10b981' : '#f43f5e', boxShadow: wsConnected ? '0 0 8px #10b981' : 'none', animation: wsConnected ? 'pulsePill 1.5s infinite' : 'none' }}></div>
            {wsConnected ? 'CONECTADO' : 'DESCONECTADO'}
          </div>
        </div>

        <div ref={termRef} style={{ background: '#020617', padding: '1.25rem', height: '350px', overflowY: 'auto', fontFamily: 'JetBrains Mono, monospace', fontSize: '0.8rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {logs.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', fontStyle: 'italic', textAlign: 'center', marginTop: '2rem' }}>Aguardando inicialização do motor neural...</div>
          ) : logs.map((log, i) => {
            let badgeColor = '#64748b';
            let bgBadge = 'transparent';
            let icon = '>';

            if (log.sender === 'SYSTEM') { badgeColor = '#94a3b8'; icon = '⚙️'; }
            else if (log.sender === 'MARKETANALYST') { badgeColor = '#3b82f6'; bgBadge = 'rgba(59, 130, 246, 0.1)'; icon = '📊'; }
            else if (log.sender === 'RISKMANAGER') { badgeColor = '#f59e0b'; bgBadge = 'rgba(245, 158, 11, 0.1)'; icon = '🛡️'; }
            else if (log.sender === 'EXECUTORAGENT') { badgeColor = '#10b981'; bgBadge = 'rgba(16, 185, 129, 0.1)'; icon = '⚡'; }
            else if (log.sender === 'USER') { badgeColor = '#ec4899'; bgBadge = 'rgba(236, 72, 153, 0.1)'; icon = '👤'; }

            // Syntax highlighting without dangerouslySetInnerHTML (Fixes XSS CodeQL Alert)
            const parts = (log.msg || '').split(/\b(BUY|SELL|HOLD|PETR4\.SA|VALE3\.SA|ITUB4\.SA)\b/g);
            const formattedMsg = parts.map((part, index) => {
              if (part === 'BUY') return <span key={`part-${index}`} style={{color:'#10b981', fontWeight:'bold'}}>BUY</span>;
              if (part === 'SELL') return <span key={`part-${index}`} style={{color:'#f43f5e', fontWeight:'bold'}}>SELL</span>;
              if (part === 'HOLD') return <span key={`part-${index}`} style={{color:'#f59e0b', fontWeight:'bold'}}>HOLD</span>;
              if (['PETR4.SA', 'VALE3.SA', 'ITUB4.SA'].includes(part)) return <span key={`part-${index}`} style={{color:'#00f3ff', textDecoration:'underline'}}>{part}</span>;
              return part;
            });

            return (
              <div key={log.id || log.timestamp || i} style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start', lineHeight: 1.5, animation: 'fadeIn 0.3s ease-out' }}>
                <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem', whiteSpace: 'nowrap', paddingTop: '0.1rem' }}>[{log.t}]</span>
                <span style={{
                  color: badgeColor, background: bgBadge, padding: '0.1rem 0.5rem', borderRadius: '4px', border: `1px solid ${badgeColor}30`,
                  fontWeight: 800, fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '0.4rem', whiteSpace: 'nowrap'
                }}>
                  {icon} {log.sender}
                </span>
                <span style={{ color: log.sender === 'USER' ? '#fdf2f8' : '#e2e8f0', flex: 1 }}>{formattedMsg}</span>
              </div>
            );
          })}
        </div>
      </div>
      </div>
    </div>
  );
};

export default DecisionLog;
