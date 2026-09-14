from unittest.mock import MagicMock, patch
import zipfile, io, json
from pathlib import Path
import pytest

from scripts.download_cotahist import build_url, download_cotahist


def test_build_url_valid():
    url, fn = build_url('annual', '2025')
    assert url == 'https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A2025.ZIP'
    assert fn == 'COTAHIST_A2025.ZIP'

    url, fn = build_url('monthly', '122025')
    assert fn == 'COTAHIST_M122025.ZIP'

    url, fn = build_url('daily', '12122025')
    assert fn == 'COTAHIST_D12122025.ZIP'


def test_build_url_invalid():
    with pytest.raises(ValueError):
        build_url('invalid', '123')


def test_download_cotahist_success(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('COTAHIST_D12122025.TXT', b'00COTAHIST...99')
    zip_bytes = buf.getvalue()

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = zip_bytes

    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        manifest = download_cotahist('daily', '12122025', tmp_path)

        assert manifest['zip_filename'] == 'COTAHIST_D12122025.ZIP'
        assert manifest['txt_filename'] == 'COTAHIST_D12122025.TXT'
        assert (tmp_path / 'download.json').exists()
        assert (tmp_path / 'COTAHIST_D12122025.TXT').exists()
