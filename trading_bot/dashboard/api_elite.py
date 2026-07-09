"""
Meridian Elite Trader API Router
Endpoints avançados: risk metrics, trade journal, correlation matrix,
market regime detection e equity curve.
"""
from fastapi import APIRouter
import sqlite3
import os
import math
import random
import datetime
from pathlib import Path

router = APIRouter(prefix="/api/elite", tags=["elite"])

DB_PATH = Path(__file__).parent.parent.parent / "data" / "trading_bot.db"


def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ─── GET /api/elite/risk_metrics ─────────────────────────────────────────────
@router.get("/risk_metrics")
def get_risk_metrics():
    """
    Retorna métricas de risco calculadas.
    Por ora usa valores realistas de mock; nas próximas fases virão da tabela
    paper_trades via cálculo de série temporal.
    """
    try:
        conn = _get_db()
        cursor = conn.cursor()

        # Tenta calcular win rate real a partir do paper_trades
        try:
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins
                FROM paper_trades
                WHERE status = 'CLOSED'
            """)
            row = cursor.fetchone()
            total = row["total"] if row and row["total"] else 0
            wins  = row["wins"]  if row and row["wins"]  else 0
            win_rate = (wins / total) if total > 0 else 0.38
        except Exception:
            total, wins, win_rate = 0, 0, 0.38
        finally:
            conn.close()

        return {
            "sharpe":           0.87,
            "sortino":          1.12,
            "calmar":           0.65,
            "max_drawdown_pct": -8.3,
            "var_95_daily":     -9.40,
            "win_rate":         round(win_rate, 4) if total > 0 else 0.38,
            "avg_win":          3.2,
            "avg_loss":         -1.8,
        }
    except Exception:
        return {
            "sharpe":           0.87,
            "sortino":          1.12,
            "calmar":           0.65,
            "max_drawdown_pct": -8.3,
            "var_95_daily":     -9.40,
            "win_rate":         0.38,
            "avg_win":          3.2,
            "avg_loss":         -1.8,
        }


# ─── GET /api/elite/trade_journal ────────────────────────────────────────────
_MOCK_TRADES = [
    {
        "ticker":       "PETR4",
        "side":         "BUY",
        "entry_price":  38.20,
        "exit_price":   41.50,
        "entry_date":   "2024-01-15",
        "exit_date":    "2024-01-28",
        "duration_days": 13,
        "pnl_pct":      8.64,
        "pnl_brl":      25.92,
        "exit_reason":  "target",
        "qty":          8,
    },
    {
        "ticker":       "VALE3",
        "side":         "BUY",
        "entry_price":  68.40,
        "exit_price":   64.10,
        "entry_date":   "2024-01-20",
        "exit_date":    "2024-02-01",
        "duration_days": 12,
        "pnl_pct":      -6.29,
        "pnl_brl":      -21.50,
        "exit_reason":  "stop",
        "qty":          5,
    },
    {
        "ticker":       "ITUB4",
        "side":         "BUY",
        "entry_price":  32.80,
        "exit_price":   35.20,
        "entry_date":   "2024-02-05",
        "exit_date":    "2024-02-18",
        "duration_days": 13,
        "pnl_pct":      7.32,
        "pnl_brl":      19.20,
        "exit_reason":  "target",
        "qty":          8,
    },
    {
        "ticker":       "BBDC4",
        "side":         "BUY",
        "entry_price":  14.60,
        "exit_price":   13.90,
        "entry_date":   "2024-02-12",
        "exit_date":    "2024-02-20",
        "duration_days": 8,
        "pnl_pct":      -4.79,
        "pnl_brl":      -11.20,
        "exit_reason":  "stop",
        "qty":          16,
    },
    {
        "ticker":       "WEGE3",
        "side":         "BUY",
        "entry_price":  44.30,
        "exit_price":   49.80,
        "entry_date":   "2024-03-01",
        "exit_date":    "2024-03-19",
        "duration_days": 18,
        "pnl_pct":      12.42,
        "pnl_brl":      33.00,
        "exit_reason":  "target",
        "qty":          6,
    },
    {
        "ticker":       "ABEV3",
        "side":         "BUY",
        "entry_price":  11.40,
        "exit_price":   10.85,
        "entry_date":   "2024-03-05",
        "exit_date":    "2024-03-12",
        "duration_days": 7,
        "pnl_pct":      -4.82,
        "pnl_brl":      -11.00,
        "exit_reason":  "stop",
        "qty":          20,
    },
    {
        "ticker":       "MGLU3",
        "side":         "BUY",
        "entry_price":  3.15,
        "exit_price":   3.58,
        "entry_date":   "2024-03-15",
        "exit_date":    "2024-03-28",
        "duration_days": 13,
        "pnl_pct":      13.65,
        "pnl_brl":      21.50,
        "exit_reason":  "target",
        "qty":          50,
    },
]


@router.get("/trade_journal")
def get_trade_journal():
    """
    Retorna o diário de trades do paper_trades.
    Se a tabela estiver vazia, usa dados de exemplo realistas.
    """
    try:
        conn = _get_db()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT ticker, side, price, qty, status
                FROM paper_trades
                WHERE status = 'CLOSED'
                ORDER BY id DESC
                LIMIT 50
            """)
            rows = cursor.fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()

        if rows:
            trades = []
            for r in rows:
                entry = r["price"] or 0.0
                trades.append({
                    "ticker":        r["ticker"],
                    "side":          r["side"],
                    "entry_price":   entry,
                    "exit_price":    entry,  # sem exit_price na tabela atual
                    "entry_date":    "—",
                    "exit_date":     "—",
                    "duration_days": 0,
                    "pnl_pct":       0.0,
                    "pnl_brl":       0.0,
                    "exit_reason":   "n/a",
                    "qty":           r["qty"],
                })
        else:
            trades = _MOCK_TRADES

        winning = [t for t in trades if t["pnl_pct"] > 0]
        losing  = [t for t in trades if t["pnl_pct"] <= 0]
        total_pnl = round(sum(t["pnl_brl"] for t in trades), 2)

        return {
            "trades": trades,
            "summary": {
                "total_trades": len(trades),
                "winning":      len(winning),
                "losing":       len(losing),
                "total_pnl_brl": total_pnl,
            }
        }
    except Exception as exc:
        return {
            "trades": _MOCK_TRADES,
            "summary": {
                "total_trades": len(_MOCK_TRADES),
                "winning":      len([t for t in _MOCK_TRADES if t["pnl_pct"] > 0]),
                "losing":       len([t for t in _MOCK_TRADES if t["pnl_pct"] <= 0]),
                "total_pnl_brl": round(sum(t["pnl_brl"] for t in _MOCK_TRADES), 2),
            },
            "error": str(exc),
        }


# ─── GET /api/elite/correlation_matrix ───────────────────────────────────────
_MOCK_TICKERS = ["PETR4", "VALE3", "ITUB4", "BBDC4"]
_MOCK_MATRIX  = [
    [1.00,  0.72,  0.45,  0.41],
    [0.72,  1.00,  0.38,  0.34],
    [0.45,  0.38,  1.00,  0.88],
    [0.41,  0.34,  0.88,  1.00],
]


@router.get("/correlation_matrix")
def get_correlation_matrix():
    """
    Calcula a matriz de correlação de Pearson dos retornos diários
    usando os últimos 60 pregões da tabela ohlcv.
    Retorna mock 4x4 se o DB estiver vazio.
    """
    try:
        conn = _get_db()
        cursor = conn.cursor()

        # Pega tickers e seus fechamentos dos últimos 60 dias
        try:
            cursor.execute("""
                SELECT DISTINCT ticker FROM ohlcv
                WHERE ticker NOT LIKE '^%'
                ORDER BY ticker
                LIMIT 10
            """)
            tickers = [r["ticker"] for r in cursor.fetchall()]

            if not tickers:
                conn.close()
                return {"tickers": _MOCK_TICKERS, "matrix": _MOCK_MATRIX}

            prices_by_ticker = {}
            for t in tickers:
                cursor.execute("""
                    SELECT ts, c FROM ohlcv
                    WHERE ticker = ?
                    ORDER BY ts DESC LIMIT 60
                """, [t])
                rows = cursor.fetchall()
                if len(rows) < 10:
                    continue
                rows = list(reversed(rows))
                closes = [r["c"] for r in rows]
                # Retornos diários
                returns = [(closes[i] - closes[i-1]) / closes[i-1]
                           for i in range(1, len(closes))]
                prices_by_ticker[t] = returns

            conn.close()

            valid_tickers = list(prices_by_ticker.keys())
            if len(valid_tickers) < 2:
                return {"tickers": _MOCK_TICKERS, "matrix": _MOCK_MATRIX}

            n = len(valid_tickers)

            def pearson(x, y):
                """Coeficiente de Pearson entre duas listas de mesma dimensão."""
                min_len = min(len(x), len(y))
                if min_len < 2:
                    return 0.0
                x, y = x[:min_len], y[:min_len]
                xm = sum(x) / min_len
                ym = sum(y) / min_len
                num   = sum((a - xm) * (b - ym) for a, b in zip(x, y))
                den_x = math.sqrt(sum((a - xm) ** 2 for a in x))
                den_y = math.sqrt(sum((b - ym) ** 2 for b in y))
                if den_x == 0 or den_y == 0:
                    return 0.0
                return round(num / (den_x * den_y), 4)

            matrix = []
            for i, ti in enumerate(valid_tickers):
                row = []
                for j, tj in enumerate(valid_tickers):
                    if i == j:
                        row.append(1.0)
                    elif j < i:
                        row.append(matrix[j][i])  # symmetric
                    else:
                        row.append(pearson(prices_by_ticker[ti], prices_by_ticker[tj]))
                matrix.append(row)

            return {"tickers": valid_tickers, "matrix": matrix}

        except Exception:
            conn.close()
            return {"tickers": _MOCK_TICKERS, "matrix": _MOCK_MATRIX}

    except Exception:
        return {"tickers": _MOCK_TICKERS, "matrix": _MOCK_MATRIX}


# ─── GET /api/elite/market_regime ────────────────────────────────────────────
@router.get("/market_regime")
def get_market_regime():
    """
    Detecta regime de mercado com base nos dados do IBOV (^BVSP) na tabela ohlcv.
    Compara fechamento atual vs SMA-50.
    """
    try:
        conn = _get_db()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT ts, c FROM ohlcv
                WHERE ticker IN ('^BVSP', 'IBOV', '^IBOV')
                ORDER BY ts DESC LIMIT 60
            """)
            rows = cursor.fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()

        if len(rows) >= 10:
            closes = [r["c"] for r in rows]  # DESC order
            current = closes[0]
            sma50 = sum(closes[:min(50, len(closes))]) / min(50, len(closes))
            diff_pct = round((current - sma50) / sma50 * 100, 2)

            # Regime detection
            if diff_pct > 1.5:
                regime = "bull"
                desc   = f"IBOV {diff_pct:+.1f}% acima da SMA-50 — tendência de alta confirmada."
                conf   = round(min(0.95, 0.6 + abs(diff_pct) * 0.05), 2)
            elif diff_pct < -3.0:
                regime = "bear"
                desc   = f"IBOV {diff_pct:+.1f}% abaixo da SMA-50 — pressão vendedora predomina."
                conf   = round(min(0.92, 0.55 + abs(diff_pct) * 0.04), 2)
            elif abs(diff_pct) <= 1.0:
                # Check volatility via daily range
                ranges = [abs(rows[i]["c"] - rows[i+1]["c"]) / rows[i+1]["c"] * 100
                          for i in range(min(10, len(rows)-1))]
                avg_vol = sum(ranges) / len(ranges)
                if avg_vol > 1.8:
                    regime = "volatile"
                    desc   = "Mercado com alta volatilidade intraday — Guard-Rail em modo restritivo."
                    conf   = round(0.65 + avg_vol * 0.03, 2)
                else:
                    regime = "lateral"
                    desc   = f"IBOV {diff_pct:+.1f}% vs SMA-50. Sem tendência definida — aguardar breakout."
                    conf   = 0.58
            else:
                regime = "lateral"
                desc   = f"IBOV {diff_pct:+.1f}% vs SMA-50. Zona de indecisão."
                conf   = 0.52

            return {
                "regime":       regime,
                "confidence":   conf,
                "description":  desc,
                "ibov_vs_sma50": diff_pct,
            }

        # Fallback mock
        return {
            "regime":       "bull",
            "confidence":   0.78,
            "description":  "IBOV acima da SMA-50 com volume crescente (dado de exemplo).",
            "ibov_vs_sma50": 2.3,
        }

    except Exception:
        return {
            "regime":       "bull",
            "confidence":   0.78,
            "description":  "IBOV acima da SMA-50 com volume crescente (dado de exemplo).",
            "ibov_vs_sma50": 2.3,
        }


# ─── GET /api/elite/equity_curve ─────────────────────────────────────────────
@router.get("/equity_curve")
def get_equity_curve():
    """
    Retorna 60 pontos da curva de equity com peak e drawdown.
    Usa dados reais de paper_trades se disponíveis,
    caso contrário gera série simulada com o capital inicial do settings.
    """
    try:
        # Tenta ler capital inicial do settings
        try:
            from trading_bot.core.config import AppConfig
            cfg = AppConfig.load()
            initial_capital = cfg.get("risk", "capital_initial", default=300.0)
        except Exception:
            initial_capital = 300.0

        conn = _get_db()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT pnl FROM paper_trades
                WHERE status = 'CLOSED'
                ORDER BY id
                LIMIT 60
            """)
            rows = cursor.fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()

        if rows and len(rows) >= 3:
            # Build from real PnL data
            curve = []
            capital = initial_capital
            peak = capital
            for i, r in enumerate(rows):
                pnl = r["pnl"] if r["pnl"] else 0.0
                capital = round(capital + pnl, 2)
                if capital > peak:
                    peak = capital
                drawdown = round(capital - peak, 2) if capital < peak else 0.0
                curve.append({
                    "day":      f"D{i+1}",
                    "value":    capital,
                    "peak":     round(peak, 2),
                    "drawdown": drawdown,
                })
        else:
            # Generate realistic mock equity curve
            curve = _generate_mock_equity(initial_capital, 60)

        return {"curve": curve}

    except Exception:
        return {"curve": _generate_mock_equity(300.0, 60)}


def _generate_mock_equity(initial: float, n: int = 60) -> list:
    """
    Gera curva de equity simulada realista com:
    - tendência ligeiramente positiva (+8% ao longo do período)
    - ruído gaussiano
    - drawdowns intermitentes
    """
    random.seed(42)  # Reproducível
    capital = initial
    peak = capital
    curve = []

    drift = (initial * 0.08) / n  # alvo: +8% total

    for i in range(n):
        # Daily P&L: drift + noise
        daily_return = random.gauss(drift, initial * 0.012)
        capital = round(capital + daily_return, 2)
        capital = max(capital, initial * 0.70)  # floor at -30%

        if capital > peak:
            peak = capital

        drawdown = round(capital - peak, 2) if capital < peak else 0.0

        curve.append({
            "day":      f"D{i+1}",
            "value":    capital,
            "peak":     round(peak, 2),
            "drawdown": drawdown,
        })

    return curve
