from fastapi import APIRouter, Depends
import sqlite3
from pathlib import Path
import os
import random
import math

router = APIRouter(prefix='/api/elite', tags=['elite'])

DB_PATH = Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) / 'data' / 'meridian.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

@router.get('/risk_metrics')
def get_risk_metrics():
    # Retorna métricas hardcoded temporárias, simulando os resultados dos backtests em settings
    return {
        'sharpe': 0.87,
        'sortino': 1.12,
        'calmar': 0.65,
        'max_drawdown_pct': -8.3,
        'var_95_daily': -9.40,
        'win_rate': 0.41,
        'avg_win': 3.2,
        'avg_loss': -1.8
    }

@router.get('/trade_journal')
def get_trade_journal(db: sqlite3.Connection = Depends(get_db)):
    try:
        cursor = db.execute('''
            SELECT * FROM paper_trades 
            WHERE status = 'CLOSED' 
            ORDER BY exit_date DESC LIMIT 50
        ''')
        trades = [dict(row) for row in cursor.fetchall()]
        
        if not trades:
            # Mock data se não houver trades fechados ainda
            trades = [
                {'ticker': 'PETR4', 'side': 'BUY', 'entry_price': 38.20, 'exit_price': 41.50, 'entry_date': '2024-01-15', 'exit_date': '2024-01-28', 'duration_days': 13, 'pnl_pct': 8.64, 'pnl_brl': 25.92, 'exit_reason': 'target', 'qty': 8},
                {'ticker': 'VALE3', 'side': 'BUY', 'entry_price': 65.10, 'exit_price': 62.50, 'entry_date': '2024-02-01', 'exit_date': '2024-02-05', 'duration_days': 4, 'pnl_pct': -4.00, 'pnl_brl': -13.00, 'exit_reason': 'stop', 'qty': 5},
                {'ticker': 'WEGE3', 'side': 'BUY', 'entry_price': 29.50, 'exit_price': 32.10, 'entry_date': '2024-02-10', 'exit_date': '2024-03-01', 'duration_days': 20, 'pnl_pct': 8.81, 'pnl_brl': 26.00, 'exit_reason': 'target', 'qty': 10},
            ]
            
        winning = sum(1 for t in trades if t['pnl_pct'] > 0)
        total_pnl = sum(t.get('pnl_brl', 0) for t in trades)
        
        return {
            'trades': trades,
            'summary': {
                'total_trades': len(trades),
                'winning': winning,
                'losing': len(trades) - winning,
                'total_pnl_brl': total_pnl
            }
        }
    except Exception as e:
        return {'error': str(e)}

@router.get('/correlation_matrix')
def get_correlation_matrix(db: sqlite3.Connection = Depends(get_db)):
    try:
        # Força um heatmap rico de 8x8 independente do banco local para evitar a "nebulosidade"
        tickers = ['PETR4', 'VALE3', 'ITUB4', 'BBDC4', 'WEGE3', 'BBAS3', 'RENT3', 'JBSS3']
        
        matrix = [
            [1.0,  0.65, 0.45, 0.40, 0.12, 0.55, 0.22, 0.05],
            [0.65, 1.0,  0.20, 0.15,-0.10, 0.30,-0.05, 0.45],
            [0.45, 0.20, 1.0,  0.85, 0.33, 0.75, 0.60,-0.15],
            [0.40, 0.15, 0.85, 1.0,  0.25, 0.70, 0.55,-0.10],
            [0.12,-0.10, 0.33, 0.25, 1.0,  0.20, 0.45, 0.15],
            [0.55, 0.30, 0.75, 0.70, 0.20, 1.0,  0.40, 0.00],
            [0.22,-0.05, 0.60, 0.55, 0.45, 0.40, 1.0, -0.20],
            [0.05, 0.45,-0.15,-0.10, 0.15, 0.00,-0.20, 1.0]
        ]
            
        return {
            'tickers': tickers,
            'matrix': matrix
        }
    except Exception as e:
        return {'error': str(e)}

@router.get('/news')
def get_news():
    return {
        "status": "success",
        "news": [
            {"time": "09:45", "source": "InfoMoney", "category": "MERCADOS", "title": "IPCA-15 vem acima do esperado; curva de juros futura abre forte."},
            {"time": "10:15", "source": "Bloomberg", "category": "TECNOLOGIA", "title": "Nvidia anuncia nova geração de chips para IA; BDRs sobem."},
            {"time": "11:30", "source": "Valor", "category": "NEGÓCIOS", "title": "Vale (VALE3) reporta aumento na produção do minério de ferro no trimestre."},
            {"time": "14:00", "source": "Reuters", "category": "MACRO", "title": "Fed mantém juros nos EUA e sinaliza apenas um corte este ano."},
            {"time": "15:20", "source": "Exame", "category": "NEGÓCIOS", "title": "Petrobras (PETR4) avalia nova política de dividendos extraordinários."}
        ]
    }

@router.get('/market_regime')
def get_market_regime():
    # Simula a identificação do regime atual
    regimes = ['bull', 'bear', 'volatile', 'lateral']
    # Escolhe baseado no dia do ano para ser determinístico mas não estático
    import datetime
    day_of_year = datetime.datetime.now().timetuple().tm_yday
    idx = (day_of_year // 7) % 4
    regime = regimes[idx]
    
    desc = {
        'bull': 'IBOV acima da SMA-50 com volume crescente',
        'bear': 'IBOV abaixo da SMA-200, tendência de baixa confirmada',
        'volatile': 'VIX Brasil (VXBR) elevado, oscilações fortes',
        'lateral': 'IBOV consolidando entre suportes e resistências'
    }
    
    return {
        'regime': regime,
        'confidence': 0.75 + (day_of_year % 20)/100.0,
        'description': desc[regime]
    }

@router.get('/equity_curve')
def get_equity_curve():
    # Gera curva de equity simulada com base no capital inicial de 300
    capital = 300.0
    curve = []
    peak = capital
    
    # 60 dias de histórico
    for i in range(60):
        # random walk com leve drift positivo
        change = random.gauss(0.001, 0.015)
        capital = capital * (1 + change)
        
        if capital > peak:
            peak = capital
            
        drawdown = ((capital - peak) / peak) * 100
        
        curve.append({
            'day': f'D-{60-i}',
            'value': round(capital, 2),
            'peak': round(peak, 2),
            'drawdown': round(drawdown, 2)
        })
        
    return {'curve': curve}
