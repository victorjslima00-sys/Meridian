"""Coleta D1 da demo para pesquisa; não alimenta sinais nem envia ordens."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .mt5_diagnostics import _demo_account, _Blocked, _failure, load_sdk


class Bar(BaseModel):
    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    time: int = Field(gt=0)
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    tick_volume: int = Field(ge=0)
    spread: int = Field(ge=0)
    real_volume: int = Field(ge=0)

    @model_validator(mode="after")
    def price_range(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("invalid_ohlc")
        return self


def validate_bars(raw, start, end):
    if raw is None or len(raw) == 0:
        raise ValueError("history_unavailable")
    result = []
    previous = 0
    for row in raw:
        values = {k: row[k].item() if hasattr(row[k], "item") else row[k]
                  for k in Bar.model_fields}
        bar = Bar.model_validate(values)
        if not start.timestamp() <= bar.time <= end.timestamp() or bar.time <= previous:
            raise ValueError("invalid_timeline")
        previous = bar.time
        result.append(bar.model_dump())
    return result


def collect(api, *, terminal, server, symbols, start, end):
    result = _failure("collection_failed", "Coleta indisponível; nenhum dado liberado.")
    try:
        now = datetime.now(timezone.utc)
        if (not server.strip() or not symbols or len(set(symbols)) != len(symbols)
                or start.tzinfo is None or end.tzinfo is None or not start < end < now
                or end.date() >= now.date()):
            raise ValueError("invalid_request")
        if api.initialize(terminal, timeout=10000) is not True:
            raise _Blocked("connection_failed", "Abra o MT5 e conecte a conta demo.")
        _, before = _demo_account(api, server)
        datasets = {}
        for symbol in symbols:
            _, current = _demo_account(api, server)
            if current != before:
                raise _Blocked("account_changed", "Conta alterada; coleta descartada.")
            bars = validate_bars(api.copy_rates_range(symbol, api.TIMEFRAME_D1, start, end), start, end)
            datasets[symbol] = {
                "bars": bars, "count": len(bars),
                "first_bar_utc": datetime.fromtimestamp(bars[0]["time"], timezone.utc).isoformat(),
                "last_bar_utc": datetime.fromtimestamp(bars[-1]["time"], timezone.utc).isoformat(),
                "zero_real_volume_count": sum(b["real_volume"] == 0 for b in bars),
            }
        _, after = _demo_account(api, server)
        if after != before:
            raise _Blocked("account_changed", "Conta alterada; coleta descartada.")
        result = {"ok": True, "read_only": True, "order_execution_tested": False,
                  "source": "MetaTrader5 demo", "server": server, "currency": before.currency,
                  "collected_at_utc": now.isoformat(), "timeframe": "D1",
                  "requested_start_utc": start.isoformat(), "requested_end_utc": end.isoformat(),
                  "adjustment_policy": "unknown", "calendar_completeness_verified": False,
                  "ready_for_backtest": False, "datasets": datasets}
    except _Blocked as exc:
        result = _failure(exc.code, exc.message)
    except Exception:
        pass  # Não expor registros nativos, identidade ou exceções da corretora.
    finally:
        try:
            api.shutdown()
        except Exception:
            result = _failure("disconnect_failed", "Falha ao encerrar conexão; coleta descartada.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terminal", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", required=True, help="Data UTC YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Data UTC YYYY-MM-DD, inclusiva; anterior a hoje")
    parser.add_argument("--output", required=True, help="Novo arquivo JSON; não sobrescreve")
    args = parser.parse_args()
    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
    terminal = Path(args.terminal)
    if not terminal.is_absolute() or not terminal.is_file() or terminal.suffix.lower() != ".exe":
        parser.error("Terminal inválido")
    result = collect(load_sdk(), terminal=str(terminal), server=args.server,
                     symbols=args.symbols, start=start, end=end)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2, allow_nan=False)
    summary = {k: v for k, v in result.items() if k != "datasets"}
    summary["datasets"] = {k: {f: v for f, v in d.items() if f != "bars"}
                           for k, d in result.get("datasets", {}).items()}
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
