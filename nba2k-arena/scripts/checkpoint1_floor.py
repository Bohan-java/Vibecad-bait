"""Inspect donor floor triangles and build a focused line-repair candidate.

No game installation, network, shader changes, or legacy rebuilds. The candidate
changes the floor Prim list and restores two donor line-albedo references. Existing
vertex/index bytes, court/basket transforms, collisions, lights, and trees remain
unchanged. This is a diagnostic checkpoint, not a standard-court certification.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from scene_primitives import iter_primitives

ROOT = Path(__file__).resolve().parents[1]
DONOR = ROOT / 'donor/original/arena_020_int_original.iff'
SOURCE = ROOT / 'output/revision2/arena_700_int.iff'
FLOOR_SOURCE = ROOT / 'output/revision2/arena_700_int_floor.iff'
CACHE = ROOT / 'handoff/cache/VertexBuffer.0f3b6fcaf86b59a6.decoded.bin'
REPORT_DIR = ROOT / 'docs/checkpoint1'
OUTPUT_DIR = ROOT / 'output/checkpoint1/line_fix'
EXPECTED = {
    DONOR: '42865ecaf8dd923c4d901509263af3b242c00975f4284b917ba79ce8fbbced46',
    SOURCE: '5d74fdab31ee29e0fe888af10c7370efc329ecc76ceb72c2f1d3eb6aa92bd499',
    FLOOR_SOURCE: '5f23522f783614d1572dca4f904132659f0d9ad4bd266b8148cbaacd333cf2ce',
    CACHE: '6aed1f28fdd729b52c415ba2a07245395299d0095fe7ba4b5c31216c7555af54',
}
REMOVED_MESH = 'line_four_point_lowShape'
LINE_MATERIALS = ('floor_clutchtime_court:floor_line_mat', 'floor_clutchtime_court:floor_line_mat1')


def donor_line_slots():
    with zipfile.ZipFile(DONOR) as archive:
        level = load_scene(archive)
    return {name: copy.deepcopy(level['Material'][name]['Resource']['DetailAlbedoTexture'])
            for name in LINE_MATERIALS}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verified_inputs():
    for path, expected in EXPECTED.items():
        if digest(path) != expected:
            raise ValueError(f'Archived input changed: {path.relative_to(ROOT)}')


def load_scene(archive):
    raw = archive.read('level.SCNE').strip()
    return json.loads(raw if raw.startswith(b'{') else b'{' + raw + b'}')['level']


def floor_data():
    verified_inputs()
    with zipfile.ZipFile(DONOR) as archive:
        level = load_scene(archive)
        target = level['Object']['__floor00__']['Target']
        model = level['Model'][target]
        indices = np.frombuffer(archive.read(model['IndexBuffer']['Binary']), '<u2')
    raw = CACHE.read_bytes()
    stream = model['VertexStream'][0]
    if len(raw) != stream['Size'] or stream['Stride'] != 28:
        raise ValueError('Unexpected donor floor layout')
    positions = np.ndarray((len(raw) // 28, 3), '<f4', raw, strides=(28, 4)).copy()
    prims = list(iter_primitives(model, indices=indices, vertex_count=len(positions)))
    return target, model, positions, indices, prims


def candidate_scene(source):
    """Materialize inherited offsets before omitting a draw, without rebasing bytes."""
    result = copy.deepcopy(source)
    target = source['Object']['__floor00__']['Target']
    original = source['Model'][target]
    resolved = list(iter_primitives(original))
    removed = [p for p in resolved if p.get('Mesh') == REMOVED_MESH]
    if len(removed) != 1:
        raise ValueError('Expected exactly one donor four-point-line primitive')
    result['Model'][target]['Prim'] = [p for p in resolved if p.get('Mesh') != REMOVED_MESH]
    for name, slot in donor_line_slots().items():
        # The donor map's RGB is white and its alpha varies. V2's opaque BC1
        # replacement erased the mask used by this alpha-blended floor effect.
        # Reuse original texture metadata and the game's existing shared asset.
        if slot['Pixelmap'] not in result['Texture']:
            raise ValueError('Original line texture metadata is missing')
        result['Material'][name]['Resource']['DetailAlbedoTexture'] = slot
    return result, removed[0]


def validate_pair(main_path, floor_path):
    """Independently check the packed result against the exact archived input."""
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(main_path) as result:
        if result.testzip() is not None:
            raise ValueError('Candidate ZIP CRC failure')
        if source.namelist() != result.namelist():
            raise ValueError('Archive entries changed')
        changed = [name for name in source.namelist() if source.read(name) != result.read(name)]
        if changed != ['level.SCNE']:
            raise ValueError(f'Unexpected resource changes: {changed}')
        before, after = load_scene(source), load_scene(result)
        target = before['Object']['__floor00__']['Target']
        old_model, new_model = before['Model'][target], after['Model'][target]
        expected = [p for p in iter_primitives(old_model) if p.get('Mesh') != REMOVED_MESH]
        actual = list(iter_primitives(new_model))
        if actual != expected:
            raise ValueError('Retained primitive ranges/materials changed')
        if len(actual) != len(old_model['Prim']) - 1:
            raise ValueError('Unexpected removed primitive count')
        # Restore only the allowed list; the entire scene must then compare equal.
        restored = copy.deepcopy(after)
        restored['Model'][target]['Prim'] = copy.deepcopy(old_model['Prim'])
        for name, slot in donor_line_slots().items():
            if after['Material'][name]['Resource']['DetailAlbedoTexture'] != slot:
                raise ValueError('Donor alpha-bearing line texture reference was not restored')
            restored['Material'][name]['Resource']['DetailAlbedoTexture'] = copy.deepcopy(
                before['Material'][name]['Resource']['DetailAlbedoTexture'])
        if restored != before:
            raise ValueError('Scene changed outside floor Prim list / two line texture slots')
        ib = np.frombuffer(result.read(new_model['IndexBuffer']['Binary']), '<u2')
        list(iter_primitives(new_model, indices=ib, vertex_count=len(CACHE.read_bytes()) // 28))
        # The next draw must retain its old absolute index offset after removal.
        tail = next(p for p in actual if p['Mesh'] == 'line_free_throw_circle_lowShape')
        if tail['Start'] != 4878:
            raise ValueError('Free-throw circle was accidentally rebased')
    if digest(floor_path) != EXPECTED[FLOOR_SOURCE]:
        raise ValueError('Companion floor changed')
    with zipfile.ZipFile(floor_path) as archive:
        if archive.testzip() is not None:
            raise ValueError('Companion floor ZIP CRC failure')
    return {
        'archive_entries_preserved': True,
        'changed_archive_entries': changed,
        'only_floor_primitive_list_and_two_line_albedo_slots_changed': True,
        'donor_alpha_bearing_line_texture_references_restored': True,
        'retained_absolute_index_ranges_and_materials_unchanged': True,
        'vertex_and_index_buffers_unchanged': True,
        'all_objects_baskets_collisions_lights_and_trees_unchanged': True,
        'companion_floor_byte_identical_to_v2': True,
        'retained_primitives': len(actual),
        'free_throw_circle_start': tail['Start'],
        'game_runtime_verified': False,
    }


def build():
    verified_inputs()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    main_path, floor_path = OUTPUT_DIR / SOURCE.name, OUTPUT_DIR / FLOOR_SOURCE.name
    # Fixed paths deliberately prevent this utility from targeting game directories.
    with zipfile.ZipFile(SOURCE) as source:
        scene, removed = candidate_scene(load_scene(source))
        raw = json.dumps({'level': scene}, separators=(',', ':')).encode()[1:-1]
        with zipfile.ZipFile(main_path, 'w') as target:
            target.comment = source.comment
            for info in source.infolist():
                target.writestr(info, raw if info.filename == 'level.SCNE' else source.read(info))
    shutil.copyfile(FLOOR_SOURCE, floor_path)
    checks = validate_pair(main_path, floor_path)
    verified_inputs()
    report = {
        'status': 'STATICALLY_VERIFIED_DIAGNOSTIC_GAME_UNTESTED',
        'purpose': 'Remove four-point draw and restore donor line alpha-mask references; not a complete standard-court fix.',
        'base': str(SOURCE.relative_to(ROOT)),
        'base_sha256': EXPECTED[SOURCE],
        'removed_draw': {k: removed[k] for k in ('Mesh', 'Start', 'Count', 'Material')},
        'restored_line_slots': donor_line_slots(),
        'shared_resource_dependency': 'Original floor_line texture bytes are not bundled; the game must resolve its donor shared resource. Mask shape and runtime appearance are unverified.',
        'preserved_game_scoring_logic': 'Unchanged; hiding a visible line does not change scoring rules.',
        'files': [{'path': str(p.relative_to(ROOT)), 'bytes': p.stat().st_size,
                   'sha256': digest(p)} for p in (main_path, floor_path)],
        'checks': checks,
    }
    (OUTPUT_DIR / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


LABELS = [
    '00  Base surface / apron extent', '01  Sideline tabs',
    '02  Inner lane tabs', '03  Inner lane lines', '04  Outer lane tabs',
    '05  Lane / free-throw lines', '06  Midcourt side stubs',
    '07  Three-point lines', '08  FOUR-POINT LINES',
    '09  Free-throw circles', '10  Restricted-area arcs', '11  Sidelines / baselines',
]
COLORS = ['#45545b', '#ffdd78', '#cf9dff', '#ff90b0', '#8de3e0', '#7dc6ff',
          '#eea764', '#ffffff', '#ff645e', '#d3e882', '#65d9a6', '#cbd5e1']


def font(size):
    try:
        return ImageFont.truetype('DejaVuSans.ttf', size)
    except OSError:
        return ImageFont.load_default(size=size)


def draw_court(draw, box, positions, indices, prims, *, isolate=None, omit_four=False):
    x, y, w, h = box
    scale = min(w / 2050, h / 3900)
    def project(triangle):
        return [(x + w / 2 + float(p[0]) * scale, y + h / 2 - float(p[2]) * scale) for p in triangle]
    for n, prim in enumerate(prims):
        if omit_four and prim['Mesh'] == REMOVED_MESH:
            continue
        if isolate is not None and n not in (0, isolate):
            continue
        triangles = positions[indices[prim['Start']:prim['Start'] + prim['Count']].reshape(-1, 3)]
        for tri in triangles:
            draw.polygon(project(tri), fill=COLORS[n])


def audit():
    target, model, positions, indices, prims = floor_data()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    layers = []
    for n, prim in enumerate(prims):
        used = positions[indices[prim['Start']:prim['Start'] + prim['Count']]]
        layers.append({
            'number': n, 'label': LABELS[n], 'mesh': prim['Mesh'],
            'start': prim['Start'], 'count': prim['Count'], 'triangles': prim['Count'] // 3,
            'material': prim['Material'], 'actual_min': used.min(0).tolist(),
            'actual_max': used.max(0).tolist(), 'color': COLORS[n],
        })
    report = {
        'source': str(DONOR.relative_to(ROOT)), 'donor_sha256': EXPECTED[DONOR],
        'decoded_vertex_cache_sha256': EXPECTED[CACHE], 'floor_model': target,
        'units': 'Original donor coordinate units; no dimensional standard inferred.',
        'vertices': len(positions), 'indices': len(indices), 'layers': layers,
        'interpretation': [
            'The model extent includes out-of-bounds surface. It is not the playing rectangle.',
            'Four-point arcs are a distinct donor primitive (08), independent of an extra floor package.',
            'The midcourt primitive (06) contains side stubs, not a continuous center line/circle.',
            'This top-down triangle audit is not a rendered or in-game preview.',
        ],
    }
    (REPORT_DIR / 'floor_layers.json').write_text(json.dumps(report, indent=2) + '\n')
    im = Image.new('RGB', (1680, 1380), '#132027'); draw = ImageDraw.Draw(im)
    draw.text((30, 18), 'CHECKPOINT 1 / DONOR FLOOR TRIANGLE AUDIT', font=font(26), fill='white')
    draw.text((30, 54), 'Actual index ranges / donor coordinates / isolated layers / NOT an in-game render', font=font(17), fill='#c0d0d5')
    for i in range(12):
        col, row = i % 6, i // 6; x, y = 20 + col * 275, 96 + row * 630
        draw.rounded_rectangle((x, y, x + 264, y + 610), radius=10, fill='#23323b')
        draw.text((x + 10, y + 12), LABELS[i], font=font(13), fill=COLORS[i] if i else 'white')
        draw.text((x + 10, y + 34), f"start {prims[i]['Start']} / {prims[i]['Count']//3} triangles", font=font(12), fill='#c0d0d5')
        draw_court(draw, (x + 8, y + 65, 248, 525), positions, indices, prims, isolate=i)
    im.save(REPORT_DIR / 'floor_layers.png')
    im = Image.new('RGB', (1260, 1060), '#132027'); draw = ImageDraw.Draw(im)
    draw.text((28, 18), 'CHECKPOINT 1 / FOUR-POINT DRAW REMOVED', font=font(25), fill='white')
    draw.text((28, 54), 'Triangle extents only. Restored texture alpha is NOT simulated. NOT game-verified.', font=font(16), fill='#c0d0d5')
    for side, omit in enumerate((False, True)):
        x = 28 + side * 625
        draw.text((x, 104), 'ARCHIVED V2 / four-point arcs in red' if not omit else 'CANDIDATE / other lines retain original ranges', font=font(17), fill='white')
        draw_court(draw, (x + 35, 142, 490, 865), positions, indices, prims, omit_four=omit)
    im.save(REPORT_DIR / 'four_point_comparison.png')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', action='store_true', help='Write decoded line maps and JSON under docs/checkpoint1')
    parser.add_argument('--build', action='store_true', help='Write focused line-repair IFF pair under output/checkpoint1/line_fix')
    parser.add_argument('--validate', action='store_true', help='Validate the already packed checkpoint pair without writing')
    args = parser.parse_args()
    if not any((args.audit, args.build, args.validate)):
        parser.error('Choose --audit, --build or --validate')
    if args.audit:
        report = audit()
        print(json.dumps({'audit_layers': len(report['layers']), 'vertices': report['vertices']}))
    if args.build:
        report = build()
        print(json.dumps({'files': report['files'], 'status': report['status']}))
    if args.validate:
        verified_inputs()
        print(json.dumps(validate_pair(OUTPUT_DIR / SOURCE.name, OUTPUT_DIR / FLOOR_SOURCE.name)))


if __name__ == '__main__':
    main()
