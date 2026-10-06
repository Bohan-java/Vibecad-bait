#!/usr/bin/env python3
"""Read-only NBA 2K SCNE lighting evidence collector, Python 3.10+.

NOT a LIGHT_BRICK_MAP decoder or a game patch. No source IFF is rewritten,
no project modules are imported, and no whole-file hashes are calculated.
SCNE original bytes and duplicate-key order are retained. Only ZIP-readable
IFFs and JSON / JSON-member-fragment SCNEs are supported.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import gzip
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import zipfile

MIB = 1024 * 1024
TOKEN = re.compile(r"LIGHT[_ ]?BRICK[_ ]?MAP|LIGHT[_ ]?GRID|LIGHT[_ ]?PROBE[_ ]?GRID", re.I)
FILE_SUFFIX = re.compile(r"\.(?:bin|gz|dds|scne|fx|shader)$", re.I)
PROBE_PAYLOAD = re.compile(r"PROBE_DATA|VISIBILITY_DATA", re.I)


class Pairs(list):
    """A JSON object as an ordered list of pairs; not an ordinary dict."""


def parse_scne(raw: bytes) -> tuple[Pairs, bool]:
    text = raw.decode('utf-8-sig').strip()
    fragment = not text.startswith('{')
    obj = json.loads('{' + text + '}' if fragment else text,
                     object_pairs_hook=Pairs,
                     parse_constant=lambda token: (_ for _ in ()).throw(
                         ValueError('Non-finite JSON constant: ' + token)))
    if not isinstance(obj, Pairs):
        raise ValueError('SCNE root is not a JSON object/member fragment')
    return obj, fragment


def view(value):
    """An explicitly tagged diagnostic view, NEVER replacement SCNE JSON."""
    if isinstance(value, Pairs):
        return {'$ordered_pairs': [[k, view(v)] for k, v in value]}
    if isinstance(value, list):
        return [view(v) for v in value]
    return value


def walk(node, path=()):
    """Paths include pair indices, so duplicate names stay distinguishable."""
    yield path, node
    if isinstance(node, Pairs):
        for i, (key, val) in enumerate(node):
            yield from walk(val, path + (f'{key} [pair {i}]',))
    elif isinstance(node, list):
        for i, val in enumerate(node):
            yield from walk(val, path + (f'[{i}]',))


def leaves(node, path=()):
    for p, item in walk(node, path):
        if isinstance(item, str):
            yield p, item


def collect_selections(doc):
    """Select Light sections and actual matching labels; follow named refs.

    Selection is a heuristic evidence collection, NOT a proved dependency
    closure. Shader-generated/hash-only/opaque references may remain unknown.
    """
    selected = {}
    index = defaultdict(list)
    duplicate_keys = []
    nodes = list(walk(doc))
    for path, node in nodes:
        if not isinstance(node, Pairs):
            continue
        duplicates = {k: n for k, n in Counter(k for k, _ in node).items() if n > 1}
        if duplicates:
            duplicate_keys.append({'path': list(path), 'keys': duplicates})
        for i, (key, val) in enumerate(node):
            child = path + (f'{key} [pair {i}]',)
            index[key].append((child, val))
            if key == 'Light' or TOKEN.search(key):
                selected.setdefault(child, (val, 'matching key'))
            if isinstance(val, str) and TOKEN.search(val):
                selected.setdefault(path, (node, 'matching string in object'))
    queue = deque(selected)
    ambiguous = []
    seen_tokens = set()
    while queue:
        path = queue.popleft()
        node = selected[path][0]
        for _, token in leaves(node):
            if token in seen_tokens or not token:
                continue
            seen_tokens.add(token)
            candidates = index.get(token, [])
            if len(candidates) == 1:
                p, value = candidates[0]
                if p not in selected:
                    selected[p] = (value, 'unique exact named reference: ' + token)
                    queue.append(p)
            elif len(candidates) > 1:
                ambiguous.append({'token': token, 'candidate_paths': [list(p) for p, _ in candidates]})
            if len(selected) > 10000:
                raise ValueError('Selection limit exceeded; use a smaller SCNE or inspect raw SCNE')
    return selected, duplicate_keys, ambiguous


def collect_refs(selected):
    refs = defaultdict(list)
    for path, (node, _) in selected.items():
        for p, value in leaves(node, path):
            field = p[-1].split(' [pair ')[0] if p else ''
            if FILE_SUFFIX.search(value) or field.lower() in {'binary', 'file', 'filename', 'resource'}:
                origin = list(p)
                if origin not in refs[value]:
                    refs[value].append(origin)
    return refs


def contained(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f'Path is outside the explicitly permitted workspace: {path}')
    return resolved


def workspace_path(text: str, root: Path) -> Path:
    p = Path(text)
    return contained(p if p.is_absolute() else root / p, root)


def header_views(data: bytes):
    n = min(16, len(data) // 4)
    prefix = data[:n * 4]
    sample = data[:min(len(data), 65536) // 4 * 4]
    counter = Counter(x[0] for x in struct.iter_unpack('<I', sample))
    return {
        'interpretation': 'Raw numerical views only. No byte order, stride, index or header field is established.',
        'bytes': len(data), 'first_64_bytes_hex': data[:64].hex(' '),
        'first_u32_little_endian': list(struct.unpack('<' + 'I' * n, prefix)),
        'first_u32_big_endian': list(struct.unpack('>' + 'I' * n, prefix)),
        'remainder_mod_4': len(data) % 4,
        'sample_u32_le_bytes': len(sample),
        'sample_most_common_u32_le': counter.most_common(12),
        'gzip_magic_present': data.startswith(b'\x1f\x8b'),
    }


def resolve_ref(ref: str, archive: zipfile.ZipFile, cache_roots: list[Path], workspace: Path):
    names = defaultdict(list)
    for info in archive.infolist():
        names[info.filename].append(info)
    variants = [ref]
    if ref.endswith('.gz'):
        variants.append(str(PurePosixPath(ref).with_suffix('.bin')))
    # Exact archive name wins. .gz -> .bin is supported by the existing project codec.
    for name in variants:
        if name in names:
            if len(names[name]) != 1:
                return 'ambiguous_archive_member', None, name, None
            info = names[name][0]
            return ('archive_exact' if name == ref else 'archive_gz_to_bin_alias'), info, name, info.file_size
    matches = []
    # No recursive game-directory search, basename guessing, or network access.
    if not PurePosixPath(ref.replace('\\', '/')).is_absolute():
        for root in cache_roots:
            candidate = (root / ref).resolve()
            if candidate.is_relative_to(root) and candidate.is_relative_to(workspace) and candidate.is_file():
                matches.append(candidate)
    matches = list(dict.fromkeys(matches))
    if len(matches) == 1:
        return 'explicit_cache_exact', matches[0], str(matches[0].relative_to(workspace)), matches[0].stat().st_size
    if len(matches) > 1:
        return 'ambiguous_cached_resource', None, [str(x.relative_to(workspace)) for x in matches], None
    suggestions = [i.filename for i in archive.infolist()
                   if PurePosixPath(i.filename).name == PurePosixPath(ref).name][:12]
    return 'unresolved', None, suggestions, None


def extract(iff: Path, out: Path, workspace: Path, cache_roots: list[Path],
            scene_name='level.SCNE', max_resource=16*MIB, max_total=96*MIB,
            max_scene=32*MIB, include_probes=False):
    with iff.open('rb') as f:
        if f.read(80).startswith(b'version https://git-lfs.github.com/spec/v1'):
            raise ValueError('Input is a Git LFS pointer, not the real IFF. Obtain its real LFS contents first.')
    if not zipfile.is_zipfile(iff):
        raise ValueError('Input is not a ZIP-readable IFF; this collector does not decode proprietary game archives.')
    if out.exists():
        raise ValueError('Output path already exists; use a NEW directory. Nothing is overwritten.')
    report = {
        'tool': 'light_brick_inventory 1.1',
        'status': 'read_only_inventory_not_a_decoder_or_game_test',
        'source': str(iff.relative_to(workspace)), 'source_bytes': iff.stat().st_size,
        'whole_file_hashes_calculated': False,
        'limitations': [
            'Only the selected SCNE and exact file/named references visible in it are inspected.',
            'Not a complete dependency proof: opaque IDs, runtime scripts and other SCNEs may add dependencies.',
            'No inference that LIGHT_BRICK_MAP is the sole cause of ignored lights.',
            'Diagnostic $ordered_pairs views are not replacement SCNE files.',
            'No claim that any light loads, illuminates players, or produces dynamic shadows in game.',
        ],
        'resources': [], 'warnings': [],
    }
    with zipfile.ZipFile(iff, 'r') as archive:
        report['scene_members'] = [{'name': i.filename, 'bytes': i.file_size}
                                   for i in archive.infolist() if i.filename.lower().endswith('.scne')]
        matches = [i for i in archive.infolist() if i.filename == scene_name]
        if len(matches) != 1:
            raise ValueError(f'Expected exactly one {scene_name!r}; found {len(matches)}. Use --scene explicitly.')
        if matches[0].file_size > min(max_scene, max_total):
            raise ValueError('Selected SCNE exceeds text or total budget; inspect size before increasing limits.')
        raw = archive.read(matches[0])
        out.mkdir(parents=True, exist_ok=False)
        (out / 'scene.raw.SCNE').write_bytes(raw)
        report['scene'] = {'archive_name': scene_name, 'output': 'scene.raw.SCNE', 'bytes': len(raw)}
        try:
            doc, fragment = parse_scne(raw)
            selected, duplicates, ambiguous = collect_selections(doc)
        except (UnicodeError, ValueError, RecursionError) as e:
            report['parse_error'] = str(e)
            (out / 'manifest.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
            return report
        report['scene']['is_member_fragment'] = fragment
        report['duplicate_keys'] = duplicates
        report['ambiguous_named_references'] = ambiguous
        (out / 'selected.ordered-pairs.json').write_text(json.dumps([
            {'path': list(path), 'reason': reason, 'value': view(node)}
            for path, (node, reason) in selected.items()
        ], indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        refs = collect_refs(selected)
        total = len(raw)
        for number, (ref, origins) in enumerate(sorted(refs.items()), 1):
            status, handle, resolved, size = resolve_ref(ref, archive, cache_roots, workspace)
            row = {'reference': ref, 'origins': origins, 'resolution': status,
                   'resolved_as_or_suggestions': resolved, 'declared_bytes': size}
            report['resources'].append(row)
            if handle is None:
                row['extraction'] = 'not_resolved'
                continue
            if not include_probes and all(PROBE_PAYLOAD.search('/'.join(p)) for p in origins):
                row['extraction'] = 'skipped_probe_payload_by_default'
                continue
            if size is None or size > max_resource or total + size > max_total:
                row['extraction'] = 'skipped_explicit_size_budget'
                continue
            try:
                if isinstance(handle, zipfile.ZipInfo):
                    with archive.open(handle, 'r') as f:
                        data = f.read(max_resource + 1)
                else:
                    with handle.open('rb') as f:
                        data = f.read(max_resource + 1)
                if len(data) > max_resource or total + len(data) > max_total:
                    row['extraction'] = 'skipped_actual_size_budget'
                    continue
                name = f'resource_{number:04d}.raw.bin'
                (out / name).write_bytes(data)
                total += len(data)
                row.update(extraction='saved', output=name, raw_views=header_views(data))
                if data.startswith(b'\x1f\x8b'):
                    try:
                        with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                            decoded = gz.read(max_resource + 1)
                        if len(decoded) <= max_resource and total + len(decoded) <= max_total:
                            decoded_name = f'resource_{number:04d}.gunzip.bin'
                            (out / decoded_name).write_bytes(decoded)
                            total += len(decoded)
                            row.update(gunzip_output=decoded_name, gunzip_views=header_views(decoded))
                        else:
                            row['gunzip_status'] = 'skipped_explicit_size_budget'
                    except (OSError, EOFError) as e:
                        row['gunzip_error'] = str(e)
            except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as e:
                row.update(extraction='read_error', error=str(e))
        report['selection_count'] = len(selected)
        report['payload_bytes_saved'] = total
        report['resolution_counts'] = dict(Counter(r['resolution'] for r in report['resources']))
        report['extraction_counts'] = dict(Counter(r['extraction'] for r in report['resources']))
        report['interpretation'] = 'Unresolved resources are not proven absent from the game; budget-skipped resources are not missing.'
        (out / 'manifest.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, help='Explicitly permitted project directory')
    parser.add_argument('--iff', required=True, help='IFF path relative to workspace, or an absolute in-workspace path')
    parser.add_argument('--out', required=True, help='NEW output directory inside workspace')
    parser.add_argument('--scene', default='level.SCNE')
    parser.add_argument('--cache-root', action='append', default=[], help='Existing in-workspace resource cache; may repeat')
    parser.add_argument('--max-resource-mib', type=int, default=16)
    parser.add_argument('--max-total-mib', type=int, default=96)
    parser.add_argument('--max-scene-mib', type=int, default=32)
    parser.add_argument('--include-probes', action='store_true', help='Also copy selected probe data payloads; unnecessary for first brick-map inventory')
    args = parser.parse_args()
    try:
        root = Path(args.workspace).resolve(strict=True)
        if not root.is_dir():
            raise ValueError('Workspace is not a directory')
        iff = workspace_path(args.iff, root)
        out = workspace_path(args.out, root)
        caches = [workspace_path(p, root) for p in args.cache_root]
        if not iff.is_file() or any(not p.is_dir() for p in caches):
            raise ValueError('IFF must exist and cache roots must be existing directories')
        if min(args.max_resource_mib, args.max_total_mib, args.max_scene_mib) < 1:
            raise ValueError('Size budgets must be positive')
        report = extract(iff, out, root, caches, args.scene,
                         args.max_resource_mib*MIB, args.max_total_mib*MIB,
                         args.max_scene_mib*MIB, args.include_probes)
        print(json.dumps({k: report[k] for k in (
            'status', 'source', 'resolution_counts', 'extraction_counts', 'parse_error'
        ) if k in report}, indent=2, ensure_ascii=False))
        print('Evidence directory:', out)
        return 2 if 'parse_error' in report else 0
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        print('ERROR:', e, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
