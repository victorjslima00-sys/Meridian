"""Offline preflight for the demo prototype. Never connects or places orders."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_bot.broker.mt5_history import Bar, validate_bars


class Dataset(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    bars: list[Bar] = Field(min_length=1)
    count: int = Field(gt=0)
    first_bar_utc: datetime
    last_bar_utc: datetime
    zero_real_volume_count: int = Field(ge=0)


class Collection(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    ok: Literal[True]
    read_only: Literal[True]
    order_execution_tested: Literal[False]
    source: Literal['MetaTrader5 demo']
    server: Literal['XPMT5-DEMO']
    currency: Literal['BRL']
    collected_at_utc: datetime
    timeframe: Literal['D1']
    requested_start_utc: datetime
    requested_end_utc: datetime
    adjustment_policy: str
    calendar_completeness_verified: bool
    ready_for_backtest: bool
    datasets: dict[str, Dataset] = Field(min_length=1)

    @model_validator(mode='after')
    def consistency(self):
        start, end, collected = self.requested_start_utc, self.requested_end_utc, self.collected_at_utc
        if any(d.tzinfo is None for d in (start, end, collected)):
            raise ValueError('timezone_required')
        if not start < end < collected or end.date() >= collected.date():
            raise ValueError('invalid_collection_window')
        for symbol, dataset in self.datasets.items():
            if not symbol.strip():
                raise ValueError('empty_symbol')
            bars = validate_bars([b.model_dump() for b in dataset.bars], start, end)
            days = [datetime.fromtimestamp(b['time'], timezone.utc).date() for b in bars]
            if len(set(days)) != len(days):
                raise ValueError('duplicate_daily_bar')
            if (dataset.count != len(bars)
                    or dataset.first_bar_utc != datetime.fromtimestamp(bars[0]['time'], timezone.utc)
                    or dataset.last_bar_utc != datetime.fromtimestamp(bars[-1]['time'], timezone.utc)
                    or dataset.zero_real_volume_count != sum(b['real_volume'] == 0 for b in bars)):
                raise ValueError('inconsistent_summary')
        return self


def inspect_collection(raw: bytes):
    """Structural validity is not approval. Never infer adjusted prices."""
    result = {
        'prototype_stage': 'offline_data_preflight',
        'input_sha256': hashlib.sha256(raw).hexdigest(),
        'inspected_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'blocked', 'signal_status': 'not_evaluated',
        'order_status': 'not_attempted', 'performance': None,
        'blockers': [], 'datasets': {},
    }
    try:
        collection = Collection.model_validate_json(raw)
        if collection.collected_at_utc > datetime.now(timezone.utc):
            raise ValueError('future_collection')
    except ValueError:
        result['blockers'] = ['invalid_collection']
        return result
    result['source_declared'] = collection.source
    result['collected_at_utc'] = collection.collected_at_utc.isoformat()
    result['structural_validation'] = 'passed'
    # These producer flags are declarations, never a substitute for reviewed evidence.
    result['blockers'] = ['reviewed_signal_dataset_required', 'execution_not_implemented']
    if collection.adjustment_policy == 'unknown':
        result['blockers'].append('adjustment_policy_unknown')
    if not collection.calendar_completeness_verified:
        result['blockers'].append('calendar_evidence_not_attached_to_collection')
    for symbol, dataset in collection.datasets.items():
        result['datasets'][symbol] = {
            'bars': dataset.count,
            'first_bar_utc': dataset.first_bar_utc.isoformat(),
            'last_bar_utc': dataset.last_bar_utc.isoformat(),
            'zero_real_volume_count': dataset.zero_real_volume_count,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True, help='New JSON file; never overwritten')
    args = parser.parse_args()
    result = inspect_collection(Path(args.input).read_bytes())
    with Path(args.output).open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 2 if result['status'] == 'blocked' else 0


if __name__ == '__main__':
    raise SystemExit(main())
