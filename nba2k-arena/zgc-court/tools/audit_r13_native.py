"""Preserve the existing site and prove the facade material transfer in the IFF."""
from pathlib import Path
import argparse
import copy
import hashlib
import io
import json
import zipfile
import numpy as np
from PIL import Image
from audit_chilis_iff_current import NativeSnapshot, jhash
from iff_codec import load_scne, resolve_binary

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'validation/r13-protected-native-baseline.json'


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def native_snapshot(path):
    labels = read(ROOT / 'validation/native-source-build.json')
    with zipfile.ZipFile(path) as archive:
        snapshot = NativeSnapshot(archive, {r['model']: r['source_object'] for r in labels['models']})
        protected, excluded = snapshot.protected()
        baskets = load_scne(archive.read('baskets.SCNE'))['baskets']
        models = copy.deepcopy(baskets['Model'])
        for name, model in models.items():
            for stream in model.get('VertexStream', []):
                stream['Binary'] = snapshot.bhash(stream['Binary'])
            model['IndexBuffer']['Binary'] = snapshot.bhash(model['IndexBuffer']['Binary'])
            for prim in model.get('Prim', []):
                prim.pop('Material', None)  # Geometry contract, with glass explicitly out of scope.
        level = snapshot.level
        return {'protected_models': protected, 'excluded_chilis': excluded,
                'baskets_objects': baskets['Object'], 'baskets_model_geometry': models,
                'baskets_effects': baskets['Effect'],
                'level_markers': {n: v for n, v in level['Object'].items() if v.get('Type') == 'MARKER'},
                'level_lights': level['Light'], 'level_attributes': level['Attribute'],
                'postfx_sha256': hashlib.sha256(archive.read('PostEffect.FxTweakables')).hexdigest()}


def audit_materials(path):
    labels = read(ROOT / 'validation/native-source-build.json')
    assets_path = Path(labels['source_assets_metadata'])
    assets = read(assets_path)
    rows = []
    with zipfile.ZipFile(path) as archive:
        level = load_scne(archive.read('level.SCNE'))['level']
        for source in assets['materials']:
            if 'R13 Chili' not in source['name']:
                continue
            name = f"zgc_r03:material_{source['id']:03d}"
            mat = level['Material'][name]
            assert mat['Effect'].startswith('asset_CLOD.fx#'), source['name']
            assert mat['Parameter']['DefaultMetalness'] == source['metallic']
            assert mat['Parameter']['NormalHeight'] == 0.
            maps = {}
            for slot in ('AlbedoMap', 'NormalAndRoughMap'):
                spec = level['Texture'][mat['Resource'][slot]['Pixelmap']]
                payload = archive.read(str(Path(spec['Binary']).with_suffix('.dds')))
                image = np.asarray(Image.open(io.BytesIO(payload)).convert('RGBA'))
                maps[slot] = {'size': [spec['Width'], spec['Height']], 'mips': spec['Mips'],
                              'sha256': hashlib.sha256(payload).hexdigest(),
                              'min': image.min(axis=(0, 1)).tolist(), 'max': image.max(axis=(0, 1)).tolist()}
                assert spec['Mips'] > 1
            nr = maps['NormalAndRoughMap']
            assert 0 <= nr['min'][3] <= nr['max'][3] <= 255
            rows.append({'source_material': source['name'], 'native_material': name,
                         'metallic': mat['Parameter']['DefaultMetalness'], 'textures': maps,
                         'normal_map_neutral_for_native_compatibility': True})
    assert len(rows) >= 8, 'Expected independently mapped facade material families'
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capture-baseline', action='store_true')
    parser.add_argument('--path')
    args = parser.parse_args()
    path = Path(args.path).resolve() if args.path else ROOT / 'output/arena_700_int.iff'
    assert path.is_relative_to(ROOT)
    delivery = read(ROOT / 'validation/iff-current.json')
    current = native_snapshot(path)
    if args.capture_baseline:
        assert delivery['revision'] == 'R12.1' and not BASE.exists()
        BASE.write_text(json.dumps({'iff_sha256': delivery['output_sha256'], **current}, ensure_ascii=False, indent=2), encoding='utf8')
        print('R12.1 protected native baseline captured')
        return
    before = read(BASE)
    changed = []
    for key, value in current.items():
        if key == 'excluded_chilis':
            continue
        if key == 'protected_models':
            assert set(value) == set(before[key]), 'Protected non-Chilis object set changed'
            changed.extend(n for n in value if value[n] != before[key][n])
        else:
            assert value == before[key], 'Protected native contract changed: ' + key
    # Re-exporting the identical buffers can slightly vary Blender's derived
    # Duv density hints. Accept only the separately proven, bounded metadata
    # differences for these exact two archives; every other contract stays exact.
    duv_proofs = []
    if changed:
        duv = read(ROOT / 'validation/r13-native-duv-audit.json')
        assert duv['status'] == 'passed'
        assert duv['baseline_iff_sha256'] == before['iff_sha256']
        assert duv['candidate_iff_sha256'] == delivery['output_sha256']
        assert set(changed) == {p['source_object'] for p in duv['proofs']}
        for name in changed:
            expected = copy.deepcopy(before['protected_models'][name])
            for proof in (p for p in duv['proofs'] if p['source_object'] == name):
                assert proof['outside_duv_full_model_exactly_equal']
                assert proof['restoring_only_duv_reproduces_old_canonical_hash']
                assert proof['before'] in expected
                assert proof['after'] in current['protected_models'][name]
                for scalar in proof['exact_scalar_differences']:
                    assert scalar['absolute_error'] < 3e-7 and scalar['relative_error'] < 3e-6
                expected[expected.index(proof['before'])] = proof['after']
                duv_proofs.append(proof)
            assert sorted(expected, key=lambda r: r['canonical_sha256']) == current['protected_models'][name]
    materials = audit_materials(path)
    result = {'revision': 'R13', 'status': 'passed', 'iff_sha256': delivery['output_sha256'],
              'baseline_sha256': before['iff_sha256'], 'protected_objects': len(current['protected_models']),
              'protected_models': sum(map(len, current['protected_models'].values())),
              'non_chilis_geometry_material_or_transform_changes': [],
              'derived_duv_metadata_differences': duv_proofs,
              'basket_geometry_skeleton_and_objects_unchanged': True,
              'global_lights_postfx_markers_unchanged': True, 'materials': materials,
              'game_tested': False}
    (ROOT / 'validation/r13-native-current.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'status': result['status'], 'protected_objects': result['protected_objects'], 'facade_materials': len(materials)}))


if __name__ == '__main__':
    main()
