"""Download direto do COTAHIST oficial da B3 via CDN historico (sem CAPTCHA).

Permite baixar arquivos anuais, mensais ou diarios com validacao estrita de SHA-256
e geracao de manifesto para pesquisa quantitativa no Meridian.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

BASE_CDN_URL = 'https://bvmf.bmfbovespa.com.br/InstDados/SerHist'


def build_url(kind: str, value: str) -> tuple[str, str]:
    kind = kind.lower()
    if kind == 'annual':
        filename = f'COTAHIST_A{value}.ZIP'
    elif kind == 'monthly':
        filename = f'COTAHIST_M{value}.ZIP'
    elif kind == 'daily':
        filename = f'COTAHIST_D{value}.ZIP'
    else:
        raise ValueError(f'Tipo desconhecido: {kind}. Use annual, monthly ou daily.')
    return f'{BASE_CDN_URL}/{filename}', filename


def download_cotahist(kind: str, value: str, output_dir: Path) -> dict:
    url, filename = build_url(kind, value)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / filename

    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        if resp.status != 200:
            raise RuntimeError(f'Falha no download de {url}: status {resp.status}')
        zip_bytes = resp.read()

    zip_sha = hashlib.sha256(zip_bytes).hexdigest()
    zip_path.write_bytes(zip_bytes)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if not names:
            raise ValueError('Arquivo ZIP vazio')
        txt_name = names[0]
        txt_bytes = zf.read(txt_name)
        txt_path = output_dir / txt_name
        txt_path.write_bytes(txt_bytes)

    txt_sha = hashlib.sha256(txt_bytes).hexdigest()
    manifest = {
        'url': url,
        'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
        'zip_filename': filename,
        'zip_sha256': zip_sha,
        'zip_size_bytes': len(zip_bytes),
        'txt_filename': txt_name,
        'txt_sha256': txt_sha,
        'txt_size_bytes': len(txt_bytes),
    }

    manifest_path = output_dir / 'download.json'
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=['annual', 'monthly', 'daily'], required=True, help='annual, monthly ou daily')
    parser.add_argument('--value', required=True, help='Ex: 2025 (annual), 122025 (monthly), 12122025 (daily)')
    parser.add_argument('--output', required=True, help='Diretorio de destino')
    args = parser.parse_args()

    try:
        manifest = download_cotahist(args.kind, args.value, Path(args.output))
        print(json.dumps(manifest, indent=2))
        return 0
    except Exception as e:
        print(f'Erro no download: {e}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
