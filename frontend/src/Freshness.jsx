import React, { useEffect, useState } from 'react';

// ─── Frescor de dado ao vivo (Track B 3c, endurecido na rodada de
// usabilidade 2a) ────────────────────────────────────────────────────
// timeAgo/FreshnessTag moraram em App.jsx até o fix dos "números
// congelados": o rótulo só re-renderizava quando ALGUM estado do App
// mudava — na prática, quem o mantinha vivo eram as mensagens do
// WebSocket, por acaso. Agora o tag tem ticker próprio de 1s e envelhece
// de forma determinística, e ganhou o estado transitório "atualizando..."
// para o retorno de aba oculta (o usuário precisa VER que o sistema
// percebeu a volta e está buscando, não só o número trocar sozinho).

export const timeAgo = (isoString) => {
  if (!isoString) return 'nunca';
  const diffMs = Date.now() - new Date(isoString).getTime();
  if (diffMs < 0) return 'agora';
  const s = Math.floor(diffMs / 1000);
  if (s < 60) return `há ${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `há ${m}min`;
  const h = Math.floor(m / 60);
  return `há ${h}h${m % 60 ? ` ${m % 60}min` : ''}`;
};

export const FreshnessTag = ({ ts, refreshing }) => {
  const [, setTick] = useState(0);
  useEffect(() => {
    const iv = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(iv);
  }, []);
  return (
    <span style={{ fontSize: '0.68rem', color: refreshing ? 'var(--cyan)' : 'var(--text-muted)', fontFamily: 'monospace', fontWeight: 400, whiteSpace: 'nowrap' }}>
      {refreshing ? 'atualizando...' : `atualizado ${timeAgo(ts)}`}
    </span>
  );
};
