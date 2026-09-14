from decimal import Decimal
import json

import pytest

from trading_bot.data.cotahist import InvalidCota, export_research, flags, parse_quote, read_file


def row(ticker='PETR4', market='010', factor=1):
    # Fixture sintética identificada; offsets conferidos com o layout B3.
    text = list(' ' * 245)
    def put(start, end, value):
        assert len(value) == end - start
        text[start:end] = value
    put(0, 2, '01'); put(2, 10, '20260102'); put(10, 12, '02')
    put(12, 24, ticker.ljust(12)); put(24, 27, market)
    put(27, 39, 'PETROBRAS'.ljust(12)); put(39, 49, 'PN'.ljust(10))
    put(52, 56, 'R$  ')
    for start, value in zip((56, 69, 82, 95, 108, 121, 134), (1000, 1200, 900, 1050, 1100, 0, 0)):
        put(start, start + 13, f'{value:013d}')
    put(147, 152, '00010'); put(152, 170, f'{100 * factor:018d}')
    put(170, 188, f'{105000:018d}'); put(188, 201, '0' * 13)
    put(201, 202, '0'); put(202, 210, '99991231')
    put(210, 217, f'{factor:07d}'); put(217, 230, '0' * 13)
    put(230, 242, 'BRPETRACNPR6'); put(242, 245, '100')
    return ''.join(text)


def source(tmp_path, records):
    header = ('00' + 'COTAHIST.2026' + 'BOVESPA ' + '20260103').ljust(245)
    trailer = ('99' + header[2:31] + f'{len(records) + 2:011d}').ljust(245)
    path = tmp_path / 'source.txt'
    path.write_bytes(('\r\n'.join([header, *records, trailer]) + '\r\n').encode('latin-1'))
    return path


def test_layout_factor_isin_and_decimal_precision():
    quote = parse_quote(row(factor=1000))
    assert quote.quotation_factor == 1000
    assert quote.isin == 'BRPETRACNPR6'
    assert quote.distribution == 100
    assert quote.open == Decimal('10.00')
    assert quote.financial_volume == Decimal('1050.00')
    assert not flags(quote)


@pytest.mark.parametrize('bad', [row()[:241], row() + ' ', row()[:56] + '-' + row()[57:],
                               row()[:56] + 'X' + row()[57:], row()[:2] + '20260230' + row()[10:]])
def test_corrupted_input_is_not_repaired(bad):
    with pytest.raises(ValueError):
        parse_quote(bad)


def test_financial_volume_factor_100_detected():
    text = row()
    quote = parse_quote(text[:170] + f'{1050:018d}' + text[188:])
    assert 'financial_volume_mismatch' in flags(quote)


def test_reject_duplicate_and_do_not_export(tmp_path):
    path = source(tmp_path, [row(), row()])
    output = tmp_path / 'out'
    with pytest.raises(InvalidCota, match='duplicate'):
        export_research(path, output, ['PETR4'], 'test-fixture')
    assert not output.exists()


def test_market_identity_preserved_and_manifest_not_trading_permission(tmp_path):
    path = source(tmp_path, [row(), row('PETR4F', '020')])
    original = path.read_bytes()
    output = tmp_path / 'out'
    report = export_research(path, output, ['PETR4', 'PETR4F', 'MISSING'], 'test-fixture')
    assert report['total_file_records'] == 4
    assert report['all_market_counts'] == {'10': 1, '20': 1}
    assert report['missing_tickers'] == ['MISSING']
    assert report['ready_for_backtest'] is False
    assert report['source_authenticity_verified'] is False
    assert path.read_bytes() == original
    assert json.loads((output / 'manifest.json').read_text())['source_sha256']
    with pytest.raises(FileExistsError):
        export_research(path, output, ['PETR4'], 'test-fixture')


def test_missing_or_incorrect_trailer_rejected(tmp_path):
    path = source(tmp_path, [row()])
    lines = path.read_bytes().splitlines()
    path.write_bytes(b'\n'.join(lines[:-1]))
    with pytest.raises(InvalidCota, match='trailer'):
        read_file(path, {'PETR4'})
    path = source(tmp_path, [row()])
    path.write_bytes(path.read_bytes().replace(b'00000000003', b'00000000004'))
    with pytest.raises(InvalidCota, match='trailer'):
        read_file(path, {'PETR4'})


def test_daily_trailer_count_excluding_header_trailer_accepted(tmp_path):
    header = ('00' + 'COTAHIST.2026' + 'BOVESPA ' + '20260911').ljust(245)
    # Formato diário B3 2026 registra o número de cotações (count - 2), não o total de linhas.
    trailer = ('99' + header[2:31] + f'{1:011d}').ljust(245)
    path = tmp_path / 'source_daily.txt'
    path.write_bytes(('\r\n'.join([header, row(), trailer]) + '\r\n').encode('latin-1'))
    quotes, issues, total, markets = read_file(path, {'PETR4'})
    assert total == 3
    assert len(quotes) == 1



def test_ohlc_inconsistent_rejected():
    text = row()
    with pytest.raises(ValueError):
        parse_quote(text[:108] + f'{2000:013d}' + text[121:])
