"""Importação local COTAHIST para pesquisa, sem conexão com execução/sinais."""
import argparse
from collections import Counter
import csv
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


LAYOUT_URL = 'https://www.b3.com.br/data/files/33/67/B9/50/D84057102C784E47AC094EA8/SeriesHistoricas_Layout.pdf'


class InvalidCota(ValueError):
    pass


class Quote(BaseModel):
    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    trading_date: date
    ticker: str = Field(min_length=1, max_length=12)
    market: int = Field(ge=0)
    bdi: str
    issuer: str
    specification: str
    currency: str = Field(min_length=1)
    open: Decimal = Field(ge=0)
    high: Decimal = Field(ge=0)
    low: Decimal = Field(ge=0)
    mean: Decimal = Field(ge=0)
    close: Decimal = Field(ge=0)
    bid: Decimal = Field(ge=0)
    ask: Decimal = Field(ge=0)
    trades: int = Field(ge=0)
    quantity: int = Field(ge=0)
    financial_volume: Decimal = Field(ge=0)
    quotation_factor: int = Field(gt=0)
    isin: str
    distribution: int = Field(ge=0)

    @model_validator(mode='after')
    def ordered_prices(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError('ohlc_range')
        return self


def number(text):
    if not text or any(c not in '0123456789' for c in text):
        raise InvalidCota('invalid_numeric_field')
    return int(text)


def parse_quote(line):
    if len(line) != 245 or line[:2] != '01':
        raise InvalidCota('invalid_record_length_or_type')
    number(line[2:10])
    fields = dict(trading_date=datetime.strptime(line[2:10], '%Y%m%d').date(),
                  ticker=line[12:24].strip(), market=number(line[24:27]),
                  bdi=line[10:12], issuer=line[27:39].strip(),
                  specification=line[39:49].strip(), currency=line[52:56].strip(),
                  trades=number(line[147:152]), quantity=number(line[152:170]),
                  financial_volume=Decimal(number(line[170:188])) / 100,
                  quotation_factor=number(line[210:217]), isin=line[230:242].strip(),
                  distribution=number(line[242:245]))
    for name, start in zip(('open', 'high', 'low', 'mean', 'close', 'bid', 'ask'),
                           (56, 69, 82, 95, 108, 121, 134)):
        fields[name] = Decimal(number(line[start:start + 13])) / 100
    # Campos de opções/termo são checados estruturalmente, não normalizados.
    for start, end in ((188, 201), (201, 202), (202, 210), (217, 230)):
        number(line[start:end])
    return Quote.model_validate(fields)


def flags(quote):
    issues = []
    if min(quote.open, quote.high, quote.low, quote.close) == 0:
        issues.append('zero_price')
    if quote.quantity == 0 or quote.trades == 0:
        issues.append('no_reported_trades_or_quantity')
    if quote.market not in (10, 20):
        issues.append('market_outside_cash_scope')
    if quote.currency != 'R$':
        issues.append('currency_outside_brl_scope')
    # Um centavo de arredondamento no preço médio, multiplicado pela
    # quantidade/fator, mais um centavo no financeiro: tolerância explícita.
    expected = quote.mean * quote.quantity / quote.quotation_factor
    tolerance = Decimal('0.01') * quote.quantity / quote.quotation_factor + Decimal('0.01')
    if abs(quote.financial_volume - expected) > tolerance:
        issues.append('financial_volume_mismatch')
    return issues


def read_file(path, tickers):
    quotes, issues, seen = [], [], set()
    header = None
    trailer = False
    count = 0
    market_counts = Counter()
    with Path(path).open('rb') as source:
        for count, raw in enumerate(source, 1):
            line = raw.rstrip(b'\r\n').decode('latin-1')
            try:
                if len(line) != 245 or trailer:
                    raise InvalidCota('invalid_structure')
                kind = line[:2]
                if count == 1:
                    if kind != '00' or not line[2:15].startswith('COTAHIST') or line[15:23].strip() != 'BOVESPA':
                        raise InvalidCota('invalid_header')
                    datetime.strptime(line[23:31], '%Y%m%d')
                    header = line[2:31]
                elif kind == '99':
                    # B3 consolidados/anuais usam count (total de linhas); diários recentes usam count - 2 (total de cotações).
                    if line[2:31] != header or number(line[31:42]) not in (count, count - 2):
                        raise InvalidCota('trailer_count_or_identity')
                    trailer = True
                elif kind == '01':
                    quote = parse_quote(line)
                    market_counts[str(quote.market)] += 1
                    # Validar estrutura de todos; seleção apenas após leitura.
                    if quote.ticker not in tickers:
                        continue
                    key = (quote.trading_date, quote.ticker, quote.market, quote.isin, quote.distribution)
                    if key in seen:
                        raise InvalidCota('duplicate_quote')
                    seen.add(key)
                    quote_flags = flags(quote)
                    for flag in quote_flags:
                        issues.append({'line': count, 'ticker': quote.ticker, 'code': flag})
                    quotes.append((quote, quote_flags))
                else:
                    raise InvalidCota('unexpected_record')
            except (ValueError, ArithmeticError) as exc:
                code = str(exc) if isinstance(exc, InvalidCota) else 'invalid_quote_fields'
                raise InvalidCota(f'line {count}: {code}') from None
    if not trailer or not quotes:
        raise InvalidCota('missing_trailer_or_selected_quotes')
    return quotes, issues, count, dict(market_counts)


def export_research(source, destination, tickers, source_url):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise FileExistsError('output_directory_exists')
    with source.open('rb') as file:
        digest = hashlib.file_digest(file, 'sha256').hexdigest()
    quotes, issues, total, markets = read_file(source, set(tickers))
    # Rejeitar mudança do arquivo enquanto era lido.
    with source.open('rb') as file:
        if hashlib.file_digest(file, 'sha256').hexdigest() != digest:
            raise InvalidCota('source_changed')
    selected = Counter(q.ticker for q, _ in quotes)
    report = {'source_url_declared': source_url, 'source_authenticity_verified': False,
              'source_sha256': digest, 'layout_url': LAYOUT_URL,
              'imported_at_utc': datetime.now(timezone.utc).isoformat(),
              'total_file_records': total, 'all_market_counts': markets,
              'selected_counts': dict(selected), 'missing_tickers': sorted(set(tickers) - set(selected)),
              'first_date': str(min(q.trading_date for q, _ in quotes)),
              'last_date': str(max(q.trading_date for q, _ in quotes)),
              'issues': issues, 'adjustments': 'none', 'ready_for_backtest': False,
              'calendar_coverage_verified': False,
              'structural_validation': 'passed',
              'selected_quality': 'flagged' if issues else 'passed_checks_only'}
    destination.mkdir(parents=True)
    try:
        with (destination / 'quotes.csv').open('x', encoding='utf-8', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=[*Quote.model_fields, 'quality_flags'])
            writer.writeheader()
            for quote, quote_flags in sorted(quotes, key=lambda pair: (pair[0].trading_date, pair[0].ticker)):
                writer.writerow({**quote.model_dump(), 'quality_flags': '|'.join(quote_flags)})
        # Manifesto escrito por último: sua ausência sinaliza exportação incompleta.
        (destination / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        raise  # Não publicar manifesto de sucesso se a escrita do CSV falhar.
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--tickers', nargs='+', required=True)
    parser.add_argument('--source-url', required=True, help='Origem declarada; não comprova autenticidade')
    args = parser.parse_args()
    try:
        report = export_research(args.input, args.output, args.tickers, args.source_url)
    except (OSError, ValueError):
        print(json.dumps({'ok': False, 'message': 'Importação rejeitada; confira arquivo, layout e destino novo.'}))
        return 2
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
