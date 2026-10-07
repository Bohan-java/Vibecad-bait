"""Read-only helpers; Python 3.10+, standard library only.

JSON load behavior follows tools/iff_codec.load_scne. The diagnostic uses
source-span insertions instead of reserializing the entire SCNE. Binary donor
inspection uses the supplied BinaryScene and LenientBinaryScene class bodies,
without importing the production build modules or their optional dependencies.
"""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import types
import zipfile

PREFIX = 'zgc_rtl:'
GRID_KEY = 'LIGHT_BRICK_MAP_GRID_RUNTIME_DATA'
GRID_MEMBER = 'light_brick_map_grid_runtime_data.4c92381972a58bee.bin'


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


class Bundle:
    """Read named files from the supplied research directory or ZIP; no extraction."""
    def __init__(self, path: Path | str):
        self.path = Path(path).resolve()
        require(self.path.exists(), f'Bundle missing: {self.path}')
        self.archive = None if self.path.is_dir() else zipfile.ZipFile(self.path, 'r')
        if self.archive:
            names = self.archive.namelist()
            require(len(names) == len(set(names)), 'Duplicate bundle ZIP names')

    def read(self, name: str) -> bytes:
        p = PurePosixPath(name)
        require(not p.is_absolute() and '..' not in p.parts, 'Unsafe bundle name')
        if self.archive:
            info = self.archive.getinfo(name)
            require(info.file_size <= 200_000_000, 'Bundle member exceeds read budget')
            return self.archive.read(info)
        target = (self.path / name).resolve()
        require(target.is_relative_to(self.path), 'Bundle path escapes root')
        require(target.stat().st_size <= 200_000_000, 'Bundle member exceeds read budget')
        return target.read_bytes()

    def json(self, name: str):
        return json.loads(self.read(name))

    def close(self):
        if self.archive:
            self.archive.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def load_scne(raw: bytes):
    require(not raw.startswith(b'\x91\xf8\x1f\xe0'),
            'Binary SCNE writing is intentionally unsupported; use the current JSON night SCNE')
    def unique(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out, 'Duplicate JSON key: ' + key)
            out[key] = value
        return out
    def bad_constant(s):
        raise ValueError('Non-finite JSON constant: ' + s)
    text = raw.decode('utf-8-sig')
    wrapped = text if text.lstrip().startswith('{') else '{' + text + '}'
    doc = json.loads(wrapped, object_pairs_hook=unique, parse_constant=bad_constant)
    require(isinstance(doc, dict), 'SCNE root must be an object')
    return doc


def supplied_binary_reader(bundle: Bundle):
    """Extract only the two requested class definitions; never import a build entrypoint.

    These class bodies are part of the user's supplied project. The analyzer
    deliberately executes no module-level code from the supplied tools.
    """
    def class_node(path, name):
        tree = ast.parse(bundle.read(path).decode('utf8'), filename=path)
        matches = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name]
        require(len(matches) == 1, f'Expected one {name} definition in {path}')
        return matches[0]
    env = {'struct': struct}
    node = class_node('tools/native_floor_overlay.py', 'BinaryScene')
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<supplied BinaryScene>', 'exec'), env)
    env['nfo'] = types.SimpleNamespace(BinaryScene=env['BinaryScene'])
    node = class_node('tools/make_light_research_bundle.py', 'LenientBinaryScene')
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<supplied LenientBinaryScene>', 'exec'), env)
    return env['LenientBinaryScene']


def read_donor(raw: bytes, binary_reader):
    if raw.startswith(b'\x91\xf8\x1f\xe0'):
        return binary_reader(raw).document, 'binary E01FF891 v1 / lenient diagnostic view'
    return load_scne(raw), 'JSON'


class JsonSource:
    """Locate JSON value spans and apply only explicitly requested source edits.

    Every source character outside these spans remains byte-identical in UTF-8.
    A no-op returns exactly the original bytes, including a BOM and whitespace.
    Duplicate names and non-finite numbers have already been rejected by load_scne.
    """
    def __init__(self, raw: bytes):
        self.raw = raw
        self.doc = load_scne(raw)
        self.bom = raw.startswith(b'\xef\xbb\xbf')
        text = raw.decode('utf-8-sig')
        self.fragment = not text.lstrip().startswith('{')
        self.text = '{' + text + '}' if self.fragment else text
        self.decoder = json.JSONDecoder()

    def ws(self, pos):
        while pos < len(self.text) and self.text[pos].isspace():
            pos += 1
        return pos

    def span(self, path: tuple[str, ...]):
        require(bool(path), 'Empty JSON path')
        def locate(start, depth):
            start = self.ws(start)
            require(self.text[start] == '{', 'Path is not an object: ' + repr(path[:depth]))
            pos = self.ws(start + 1)
            while self.text[pos] != '}':
                key, key_end = self.decoder.raw_decode(self.text, pos)
                require(isinstance(key, str), 'Invalid JSON member name')
                colon = self.ws(key_end)
                require(self.text[colon] == ':', 'Missing JSON colon')
                value_start = self.ws(colon + 1)
                if key == path[depth] and depth + 1 < len(path):
                    return locate(value_start, depth + 1)
                _, value_end = self.decoder.raw_decode(self.text, value_start)
                if key == path[depth]:
                    return value_start, value_end
                pos = self.ws(value_end)
                if self.text[pos] == '}':
                    break
                require(self.text[pos] == ',', 'Missing JSON comma')
                pos = self.ws(pos + 1)
            raise KeyError('/'.join(path))
        return locate(0, 0)

    def patch(self, edits: list[tuple[int, int, str]]) -> bytes:
        parts, pos = [], 0
        for start, end, replacement in sorted(edits):
            require(pos <= start <= end <= len(self.text), 'Overlapping/invalid JSON edits')
            parts.extend([self.text[pos:start], replacement])
            pos = end
        parts.append(self.text[pos:])
        text = ''.join(parts)
        if self.fragment:
            text = text[1:-1]
        raw = (b'\xef\xbb\xbf' if self.bom else b'') + text.encode('utf8')
        load_scne(raw)
        return raw

    def insert_light(self, name: str, light: dict, prepend: bool = False):
        require(name.startswith(PREFIX), 'New light must use research prefix')
        start, end = self.span(('level', 'Light'))
        require(self.text[start] == '{' and self.text[end - 1] == '}', 'Light is not an object')
        body = json.dumps(name, ensure_ascii=True) + ': ' + json.dumps(
            light, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
        nonempty = bool(self.doc['level']['Light'])
        if prepend:
            return start + 1, start + 1, '\n\t\t' + body + (',' if nonempty else '')
        pos = end - 1
        while pos > start + 1 and self.text[pos - 1].isspace():
            pos -= 1
        return pos, pos, (',' if nonempty else '') + '\n\t\t' + body
