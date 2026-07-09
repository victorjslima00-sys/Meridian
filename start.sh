#!/bin/bash
# Script de inicialização do Meridian
# Garante que o backend use o python3 global com PYTHONPATH correto

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "🚀 Iniciando Meridian..."
echo "📂 Root: $ROOT"

# Verificar imports críticos
python3 -c "from trading_bot.core.llm_client import ResilientLLMClient; print('✅ LLM Client OK')" 2>/dev/null || {
  echo "❌ ERRO: trading_bot não encontrado. Execute 'pip install -r requirements.txt' primeiro."
  exit 1
}

# Iniciar backend com PYTHONPATH correto
echo "🔌 Iniciando Backend (porta 8000)..."
PYTHONPATH="$ROOT" python3 "$ROOT/backend/run.py" &
BACKEND_PID=$!
echo "   Backend PID: $BACKEND_PID"

# Aguardar backend iniciar
sleep 4
curl -s http://localhost:8000/api/status | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'   Status: {d[\"status\"]}')" 2>/dev/null || echo "   ⚠️ Backend ainda iniciando..."

echo ""
echo "✅ Meridian rodando!"
echo "   Dashboard: http://localhost:5173 (se frontend estiver rodando)"
echo "   API: http://localhost:8000/api/status"
echo ""
echo "Para parar: kill $BACKEND_PID"
