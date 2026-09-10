"""Bounded source acquisition and strict tabular IO. Run by file path, not package."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def write_json(path: Path, value, *, pretty=False):
    """Replace one complete LF artifact atomically, including strict finite JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False,
                         indent=2 if pretty else None,
                         separators=None if pretty else (',', ':')) + '\n'
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_json(path: Path, max_bytes=80_000_000):
    if Path(path).stat().st_size > max_bytes:
        raise ValueError('JSON exceeds the declared byte limit')
    def invalid(value):
        raise ValueError('Nonfinite JSON constant: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), parse_constant=invalid)


def number(value, *, missing=('', '-9999', 'NULL', 'N/A'), nullable=False):
    if value is None or str(value).strip() in missing:
        if nullable:
            return None
        raise ValueError('Required numeric value is missing')
    if isinstance(value, bool):
        raise TypeError('Boolean is not a scientific numeric value')
    out = float(value)
    if not math.isfinite(out):
        raise ValueError('Scientific numbers must be finite')
    return out


def read_table(path: Path, *, encoding='utf-8-sig', delimiter=',', max_rows=1_000_000):
    """Logical record IDs survive quoted newlines. Never silently repair ragged rows."""
    with Path(path).open(encoding=encoding, newline='') as stream:
        yield from table_stream(stream, delimiter=delimiter, max_rows=max_rows)


def table_stream(stream, *, delimiter=',', max_rows=1_000_000):
    reader = csv.DictReader(stream, delimiter=delimiter, strict=True)
    fields = reader.fieldnames
    if not fields or len(set(fields)) != len(fields) or any(not f.strip() for f in fields):
        raise ValueError('Missing, duplicate or blank column names')
    for index, row in enumerate(reader, 2):
        if index - 1 > max_rows:
            raise ValueError('Table exceeds row limit')
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f'Ragged logical record {index}')
        yield {'_row': str(index), **row}


def zip_table(path: Path, member: str, *, encoding='cp1252', delimiter='\t', max_bytes=400_000_000):
    """Read one named member without filesystem extraction or path traversal."""
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(member)
        if info.file_size > max_bytes or info.flag_bits & 1:
            raise ValueError('Oversized or encrypted source member')
        with archive.open(info) as binary, io.TextIOWrapper(binary, encoding=encoding, newline='') as stream:
            yield from table_stream(stream, delimiter=delimiter)


def acquire(cache: Path, *, manifest=None):
    """Download only fixed research-selected sources, with byte and SHA gates."""
    manifest = manifest or load_json(ROOT / 'data/sources/manifest.json')
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    receipts = []
    for source in manifest['files']:
        name = source['file']
        if Path(name).name != name:
            raise ValueError('Source filename must be a basename')
        target = cache / name
        if target.exists():
            if digest(target) != source['sha256']:
                raise ValueError('Existing source hash mismatch: ' + name)
        elif source.get('bundled'):
            payload = ROOT / source['bundled']
            if digest(payload) != source['sha256']:
                raise ValueError('Bundled licensed subset hash mismatch')
            target.write_bytes(payload.read_bytes())
        else:
            parsed = urllib.parse.urlsplit(source['url'])
            if parsed.scheme != 'https' or parsed.username or parsed.password or not parsed.hostname:
                raise ValueError('Invalid acquisition URL')
            partial = target.with_suffix(target.suffix + '.part')
            request = urllib.request.Request(source['url'], headers={'User-Agent': 'Sondara-source-acquisition/1'})
            count = 0
            with urllib.request.urlopen(request, timeout=60) as response, partial.open('wb') as stream:
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > source['bytes']:
                        raise ValueError('Source byte bound exceeded: ' + name)
                    stream.write(chunk)
            if count != source['bytes'] or digest(partial) != source['sha256']:
                raise ValueError('Incomplete or changed upstream source: ' + name)
            os.replace(partial, target)
        receipts.append({'file': name, 'bytes': target.stat().st_size, 'sha256': digest(target)})
    write_json(cache / 'acquisition.json', {'schema': 'drillhole.acquisition/v1', 'files': receipts}, pretty=True)
    return receipts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['acquire'])
    parser.add_argument('--cache', type=Path, default=ROOT / 'build/sources')
    args = parser.parse_args()
    print(json.dumps(acquire(args.cache), indent=2))
