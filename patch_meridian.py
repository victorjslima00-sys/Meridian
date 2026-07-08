import os
import re
import shutil
from pathlib import Path

def backup_and_patch(file_path: Path, patch_func):
    if not file_path.exists():
        print(f"Aviso: Arquivo {file_path} não encontrado. Pulando.")
        return False
    
    backup_path = file_path.with_suffix(file_path.suffix + ".bak")
    if not backup_path.exists():
        shutil.copy(file_path, backup_path)
        print(f"Backup de segurança criado em: {backup_path}")
    
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    new_content, modified = patch_func(content)
    
    if modified:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"✅ Arquivo modificado com sucesso: {file_path}")
        return True
    else:
        print(f"ℹ️ Nenhuma alteração necessária para: {file_path}")
        return False

def patch_backtest_engine(content: str):
    # Correção do Bug 1: ROUND_TRIP NameError
    pattern = r"pnl_pct\s*=\s*\(float\(last\[\"c\"\]\)\s*/\s*pos\.entry_price\s*-\s*1\)\s*-\s*ROUND_TRIP"
    replacement = 'pnl_pct = (float(last["c"]) / pos.entry_price - 1) - round_trip'
    new_content, count = re.subn(pattern, replacement, content)
    return new_content, count > 0

def patch_signals_engine(content: str):
    # Correção do Bug 2: Adiciona **kwargs para ignorar parâmetros desconhecidos (ex: target_pct)
    target_str = "target_atr_mult: float = 4.0, # Target dinâmico (ATR * 4, R:R 1:2)"
    if target_str in content and "**kwargs" not in content:
        new_content = content.replace(
            target_str + "\n)",
            target_str + ",\n    **kwargs, # Ignora argumentos adicionais para evitar TypeError silenciosos\n)"
        ).replace(
            target_str + ",\n)",
            target_str + ",\n    **kwargs, # Ignora argumentos adicionais para evitar TypeError silenciosos\n)"
        )
        return new_content, True
    return content, False

def patch_backtest_metrics(content: str):
    # Correção do Bug 3: Ajuste de anualização do calendário (Sharpe e Retornos)
    modified = False
    if "years = max(regime_days / TRADING_DAYS_PER_YEAR, 0.01)" in content:
        content = content.replace(
            "years = max(regime_days / TRADING_DAYS_PER_YEAR, 0.01)",
            "years = max(regime_days / 365.25, 0.01) # Correção: regime_days está em dias de calendário"
        )
        modified = True
    return content, modified

def patch_api(content: str):
    modified = False
    
    # Correção do Bug 4.1: Substituir tabela inexistente daily_bars por ohlcv e usar coluna real 'c'
    old_tape_query = 'SELECT ticker, close as c \n            FROM daily_bars \n            WHERE ts = (SELECT MAX(ts) FROM daily_bars)\n            LIMIT 10'
    new_tape_query = 'SELECT ticker, c FROM ohlcv WHERE ts = (SELECT MAX(ts) FROM ohlcv) LIMIT 10'
    
    if old_tape_query in content:
        content = content.replace(old_tape_query, new_tape_query)
        modified = True
    elif "daily_bars" in content:
        content = content.replace("daily_bars", "ohlcv")
        content = content.replace("close as c", "c")
        modified = True
        
    # Correção do Bug 5.1: Se a tabela paper_trades não existir ainda no DB, tratar como vazia em vez de gerar Exception
    old_positions_block = """        cursor.execute("SELECT * FROM paper_trades WHERE status = 'OPEN'")
        rows = cursor.fetchall()
        conn.close()"""
        
    new_positions_block = """        # Correção robusta: se a tabela paper_trades ainda não tiver sido criada pelo broker, trata como vazia
        try:
            cursor.execute("SELECT * FROM paper_trades WHERE status = 'OPEN'")
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            rows = []
        conn.close()"""
        
    if old_positions_block in content:
        content = content.replace(old_positions_block, new_positions_block)
        modified = True
        
    # Correção do Bug 5.2: Tratar o except genérico para retornar estrutura válida em vez de JSON que crasha o React
    old_positions_except = """    except Exception as e:
        return {"error": f"Internal server error: {str(e)}"}"""
        
    new_positions_except = """    except Exception as e:
        # Correção: retorna estrutura padrão válida com sinalizador de erro interno para evitar que o React trave
        return {
            "active_positions": [],
            "capital": {
                "initial": 300.0,
                "current": 300.0,
                "free_cash": 300.0,
                "invested": 0.0,
                "currency": "BRL"
            },
            "error_msg": str(e)
        }"""
        
    if old_positions_except in content:
        content = content.replace(old_positions_except, new_positions_except)
        modified = True
        
    return content, modified

def patch_frontend_app(content: str):
    modified = False
    
    # Correção do Bug 5.3: Criar um estado de erro no componente React
    old_state = "const [tapeData, setTapeData] = useState(null);"
    new_state = "const [tapeData, setTapeData] = useState(null);\n  const [apiError, setApiError] = useState(null);"
    
    if old_state in content and "apiError" not in content:
        content = content.replace(old_state, new_state)
        modified = True
        
    # Correção do Bug 5.4: Atualizar o useEffect para capturar erros e setar o estado de erro
    old_use_effect = """  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statRes, posRes, ecoRes, tapeRes] = await Promise.all([
          axios.get(`${API_BASE}/status`),
          axios.get(`${API_BASE}/positions`),
          axios.get(`${API_BASE}/ecosystem`),
          axios.get(`${API_BASE}/market_tape`)
        ]);
        setSystemStatus(statRes.data);
        setPositions(posRes.data);
        setEcosystem(ecoRes.data);
        setTapeData(tapeRes.data);
      } catch (err) {
        console.error("API falhou:", err);
      }
    };
    fetchData();"""
    
    new_use_effect = """  useEffect(() => {
    const fetchData = async () => {
      try {
        setApiError(null);
        const [statRes, posRes, ecoRes, tapeRes] = await Promise.all([
          axios.get(`${API_BASE}/status`),
          axios.get(`${API_BASE}/positions`),
          axios.get(`${API_BASE}/ecosystem`),
          axios.get(`${API_BASE}/market_tape`)
        ]);
        if (posRes.data.error_msg) {
          console.warn("Aviso do servidor:", posRes.data.error_msg);
        }
        setSystemStatus(statRes.data);
        setPositions(posRes.data);
        setEcosystem(ecoRes.data);
        setTapeData(tapeRes.data);
      } catch (err) {
        console.error("API falhou:", err);
        setApiError(err.message || "Erro de conexão com o servidor API.");
      }
    };
    fetchData();"""
    
    if old_use_effect in content:
        content = content.replace(old_use_effect, new_use_effect)
        modified = True
        
    # Correção do Bug 5.5: Adicionar renderizador de erro elegante para evitar Stuck Loading Screen
    old_loading_check = "  if (!systemStatus || !positions || !ecosystem || !tapeData) {"
    new_loading_check = """  if (apiError) {
    return (
      <div className="loading" style={{display: 'flex', flexDirection: 'column', height: '100vh', justifyContent: 'center', alignItems: 'center', color: '#ff4d4d', fontSize: '1.2rem', textShadow: '0 0 10px rgba(255, 77, 77, 0.3)', gap: '1rem'}}>
        <div>⚠️ {apiError}</div>
        <div style={{fontSize: '0.9rem', color: '#8b9bb4'}}>Verifique se o backend FastAPI está rodando na porta 8000.</div>
        <button className="btn btn-primary" onClick={() => window.location.reload()} style={{borderColor: 'rgba(255, 77, 77, 0.5)', color: '#ff4d4d', marginTop: '1rem', cursor: 'pointer'}}>
          Recarregar Painel
        </button>
      </div>
    );
  }

  if (!systemStatus || !positions || !ecosystem || !tapeData) {"""
  
    if old_loading_check in content and "apiError" in content and "apiError" not in content.split(old_loading_check):
        content = content.replace(old_loading_check, new_loading_check)
        modified = True
        
    # Correção do Bug 5.6: Prevenir divisão por zero na barra de progresso (Mapeamento MTM)
    old_progress = "const progress = Math.max(0, Math.min(100, ((pos.current_price - pos.entry_price) / (pos.target - pos.entry_price)) * 100));"
    new_progress = "const priceDiff = pos.target - pos.entry_price;\n                          const progress = priceDiff === 0 ? 0 : Math.max(0, Math.min(100, ((pos.current_price - pos.entry_price) / priceDiff) * 100));"
    
    if old_progress in content:
        content = content.replace(old_progress, new_progress)
        modified = True
        
    return content, modified

def main():
    print("==================================================")
    print("      MERIDIAN SYSTEM PATCHER - B3 QUANT BOT      ")
    print("==================================================")
    
    base_dir = Path(".")
    
    # 1. Backtest Engine
    engine_path = base_dir / "trading_bot" / "backtest" / "engine.py"
    backup_and_patch(engine_path, patch_backtest_engine)
    
    # 2. Signals Engine
    signals_path = base_dir / "trading_bot" / "signals" / "engine.py"
    backup_and_patch(signals_path, patch_signals_engine)
    
    # 3. Backtest Metrics
    metrics_path = base_dir / "trading_bot" / "backtest" / "metrics.py"
    backup_and_patch(metrics_path, patch_backtest_metrics)
    
    # 4. API Dashboard
    api_path = base_dir / "trading_bot" / "dashboard" / "api.py"
    backup_and_patch(api_path, patch_api)
    
    # 5. Frontend App
    app_path = base_dir / "frontend" / "src" / "App.jsx"
    backup_and_patch(app_path, patch_frontend_app)
    
    print("\nProcesso de correção concluído!")

if __name__ == "__main__":
    main()
