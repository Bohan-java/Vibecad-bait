"""Build the hand-off bundle for the real-time local light research (ChatGPT).

Writes build/handoff/realtime_light_research.zip with:
  ours/      current night package: Light / LIGHT_* / probe-grid entries (JSON) and
             the LIGHT_BRICK_MAP runtime buffer, plus the N4 light schema we tried
  donors/    native packages with working real-time lights, decoded to JSON
             (Light section, LIGHT_* markers, light fixture objects), and their raw
             binary level.SCNE so references can be searched
  tools/     project codecs (JSON SCNE, binary SCNE tree, archive writer, patch format)
  docs/      earlier research and the in-game test history
Nothing is written into the game or the repo outside build/handoff.
"""
from __future__ import annotations

import json
import struct
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from iff_codec import load_scne                       # noqa: E402
import native_floor_overlay as nfo                    # noqa: E402

OUT = ROOT / 'build' / 'handoff' / 'realtime_light_research.zip'
DONORS = {
    'arena_blacktop_ext': ROOT.parent / 'build/high_hoop/reference/arena_blacktop_ext.iff',
    'arena_020_int': ROOT.parent / 'donor/original/arena_020_int_original.iff',
}
TOOLS = ['iff_codec.py', 'native_floor_overlay.py', 'repair_iff.py', 'native_archive.py', 'night_scene.py',
         'night_lighting.py', 'make_standalone_patch.py', 'patch_scene_current.py', 'lightmap_diag2.py', 'native_textures.py', 'make_light_research_bundle.py']
DOCS = ['docs/light-brick-research/LIGHTING_RESEARCH_V2_ZH.md', 'docs/lightmap-research/REPORT_ZH.md']


class LenientBinaryScene(nfo.BinaryScene):
    """Same E01FF891 v1 tree, but tolerates repeated object keys (suffixed #dupN)."""
    def node(self, offset, path):
        self.visited.add(offset)
        self.offsets[path] = offset
        kind = struct.unpack_from('<I', self.raw, offset + 12)[0] & 255
        if kind in (1, 2):
            count = struct.unpack_from('<I', self.raw, offset + 20)[0]
            table = self.pointer(offset + 24)
            if count == 0:
                return {} if kind == 1 else []
            children = [self.pointer(table + i * 8) for i in range(count)]
            if kind == 2:
                return [self.node(c, path + (i,)) for i, c in enumerate(children)]
            out = {}
            for c in children:
                name = self.string(c)
                key, n = name, 1
                while key in out:
                    n += 1
                    key = f'{name}#dup{n}'
                out[key] = self.node(c, path + (key,))
            return out
        if kind == 0:
            return None
        if kind == 3:
            return self.string(offset + 24)
        if kind == 5:
            return struct.unpack_from('<d', self.raw, offset + 24)[0]
        if kind == 6:
            return struct.unpack_from('<q', self.raw, offset + 24)[0]
        return f'<unknown kind {kind}>'


def read_level(raw):
    if raw[:4] == b'\x91\xf8\x1f\xe0':
        return LenientBinaryScene(raw).document['level'], 'binary E01FF891 v1'
    return load_scne(raw)['level'], 'JSON'


def light_subset(level, fixture_hint=('light', 'lamp', 'spot', 'flood')):
    objects = level.get('Object', {})
    fixtures = {k: v for k, v in objects.items() if any(h in k.lower() for h in fixture_hint)}
    return {
        'Light': level.get('Light', {}),
        'Object_LIGHT_markers': {k: v for k, v in objects.items() if k.startswith('LIGHT_')},
        'Texture_LIGHT': {k: v for k, v in level.get('Texture', {}).items() if k.startswith('LIGHT_')},
        'Object_light_fixtures_sample': dict(list(fixtures.items())[:60]),
        'counts': {s: len(v) for s, v in level.items() if isinstance(v, dict)},
    }


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as out:
        with zipfile.ZipFile(ROOT / 'output/arena_700_int.iff') as ours:
            level, kind = read_level(ours.read('level.SCNE'))
            out.writestr('ours/level_light_subset.json', json.dumps(light_subset(level), indent=1))
            spec = level['Texture']['LIGHT_BRICK_MAP_GRID_RUNTIME_DATA']
            member = spec['Binary'].replace('.gz', '.bin')
            out.writestr('ours/' + member, ours.read(member))
            out.writestr('ours/README.txt', f'Current night package ({kind} level.SCNE). Only the Sun light remains; '
                         'the LIGHT_BRICK_MAP buffer is the one inherited from the original arena_700_int.\n')
        for name, path in DONORS.items():
            with zipfile.ZipFile(path) as z:
                raw = z.read('level.SCNE')
                level, kind = read_level(raw)
                out.writestr(f'donors/{name}/level_light_subset.json', json.dumps(light_subset(level), indent=1))
                out.writestr(f'donors/{name}/level.SCNE.raw', raw)
                brick = [n for n in z.namelist() if 'brick_map' in n.lower()]
                out.writestr(f'donors/{name}/README.txt',
                             f'{path.name}: level.SCNE is {kind}. LIGHT_BRICK_MAP runtime buffer members in this IFF: '
                             f'{brick or "none (streamed from another package?)"}\n')
        for t in TOOLS:
            out.write(HERE / t, 'tools/' + t)
        for d in DOCS:
            out.write(ROOT / d, 'docs/' + Path(d).name)
        out.write(ROOT / 'build/handoff/PROMPT_ZH.md', 'PROMPT_ZH.md')
        out.write(ROOT / 'build/handoff/n4_light_schema.md', 'ours/n4_light_schema.md')
    print(OUT, OUT.stat().st_size)


if __name__ == '__main__':
    main()
