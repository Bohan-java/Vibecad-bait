"""Read the final package and audit the current basket; never rewrite an IFF."""
from __future__ import annotations
import copy
import io
import json
from pathlib import Path
import struct
import zipfile
import zlib
import numpy as np
from PIL import Image
from iff_codec import load_scne, resolve_binary

ROOT = Path(__file__).resolve().parents[1]


def audit(path):
    metadata = json.loads((ROOT / 'validation/iff-current.json').read_text(encoding='utf8'))
    if metadata['revision'] not in ('R10', 'R11', 'R12') or path.stat().st_size != metadata['output_bytes']:
        raise ValueError('Wait for the final current builder report and matching archive')
    rig = metadata['basket_rig']
    with zipfile.ZipFile(path) as current, zipfile.ZipFile(ROOT.parent / '洛克公园/arena_blacktop_ext.iff') as donor:
        b = load_scne(current.read('baskets.SCNE'))['baskets']
        original = load_scne(donor.read('baskets.SCNE'))['baskets']
        level = load_scne(current.read('level.SCNE'))['level']
        name = rig['model']; model = b['Model'][name]; old = original['Model'][name]
        assert b['Object'] == original['Object']
        for k in ('Transform', 'WeightBits', 'BlendIndexOffset', 'BlendIndexRange'):
            assert model[k] == old[k], k
        assert len(model['Transform']) == 4
        assert model['VertexFormat']['POSITION0'] == old['VertexFormat']['POSITION0']
        assert model['VertexFormat']['WEIGHTDATA0'] == old['VertexFormat']['WEIGHTDATA0']
        assert [s['Stride'] for s in model['VertexStream']] == [8, 4, 8]
        raw = [current.read(resolve_binary(current, s['Binary'])) for s in model['VertexStream']]
        n = len(raw[0]) // 8
        assert n == rig['total_vertices'] and n < 65536
        assert len(raw[1]) == n * 4 and len(raw[2]) == n * 8
        for stream in (0, 2):
            previous = donor.read(resolve_binary(donor, old['VertexStream'][stream]['Binary']))
            assert raw[stream][:len(previous)] == previous
        indices_raw = current.read(resolve_binary(current, model['IndexBuffer']['Binary']))
        assert zlib.crc32(indices_raw) == model['IndexBufferCrc32']
        indices = np.frombuffer(indices_raw, '<u2')
        old_indices = np.frombuffer(donor.read(resolve_binary(donor, old['IndexBuffer']['Binary'])), '<u2')
        assert int(indices.max()) < n
        cursor = 0; rim_verified = 0
        for lod in reversed(range(12)):
            descriptor = model['Clod']['Lods']['Lod' + str(lod)]
            assert descriptor['StartIndex'] == cursor and descriptor['NumVertices'] == n
            start = cursor
            for i, prim in enumerate(model['Prim']):
                draw = prim['LodList'][lod]
                assert draw['Start'] == cursor and draw['Count'] % 3 == 0
                values = indices[cursor:cursor + draw['Count']]
                if i < len(old['Prim']):
                    native_prim = old['Prim'][i]
                    previous = native_prim['LodList'][lod]
                    assert draw['Count'] == previous['Count']
                    if native_prim.get('Mesh') == 'basket_rimShape':
                        assert np.array_equal(values, old_indices[previous['Start']:previous['Start'] + previous['Count']])
                        rim_verified += 1
                    else:
                        assert np.all(values == 0)
                cursor += draw['Count']
            assert descriptor['NumIndices'] == cursor - start
            assert descriptor['NumTris'] == (cursor - start) // 3
        assert cursor == len(indices) and rim_verified == 12
        for model_name in original['Model']:
            if model_name.endswith((':glass', ':rimr')):
                assert b['Model'][model_name] == original['Model'][model_name]
        glass_model_name = next(k for k in original['Model'] if k.endswith(':glass'))
        assert list(model['Transform'].values()) == list(b['Model'][glass_model_name]['Transform'].values())
        bones = []
        for i, (bone_name, bone) in enumerate(model['Transform'].items()):
            rest = np.asarray(bone.get('Translate', [0., 0., 0.]))
            if 'Parent' in bone:
                rest = rest + np.asarray(bones[bone['Parent']]['rest_pivot_cm'])
            bones.append({'index': i, 'name': bone_name.split('|')[-1],
                          'parent': bone.get('Parent'), 'rest_pivot_cm': rest.tolist()})

        # Independent packed-weight parser checks pointers and integer sums.
        matrix_raw = current.read(resolve_binary(current, model['MatrixWeightsBuffer']['Binary']))
        matrix = np.frombuffer(matrix_raw, '<u4')
        old_matrix = donor.read(resolve_binary(donor, old['MatrixWeightsBuffer']['Binary']))
        assert matrix_raw.startswith(old_matrix)
        words = np.frombuffer(raw[2], '<u4').reshape(-1, 2)[:, 1]
        histogram = {'root_rigid': 0, 'base_rigid': 0, 'two_bone': 0}
        for word in words[rig['native_vertices_preserved']:]:
            word = int(word); count = (word & 255) + 1; start = word >> 8
            if count == 1:
                assert start in (0, 1)
                histogram['root_rigid' if start == 0 else 'base_rigid'] += 1
            else:
                assert count == 2 and start + count <= len(matrix)
                entries = matrix[start:start + count]
                assert set(map(int, entries >> 16)) == {0, 1}
                assert int(np.sum(entries & 65535)) == 65535
                histogram['two_bone'] += 1
        for removed in rig['source_models_removed']:
            assert removed not in level['Model']
            assert not any(o.get('Target') == removed for o in level['Object'].values())
        for kept in rig['fixed_base_models_kept_exactly_static']:
            assert kept in level['Model']

        glass_name = 'basket_stanchiont_outdoor:glass_shader_mat'
        hole_name = 'basket_stanchiont_outdoor:glasshole_shader_mat'
        from specialized_basket_glass import TEMPLATE_PATH, TEMPLATE_MATERIAL, EFFECT, SCRIPT, _binaries
        from native_floor_overlay import BinaryScene
        with zipfile.ZipFile(TEMPLATE_PATH) as dedicated_archive:
            raw_scene = dedicated_archive.read('baskets.SCNE')
            try:
                dedicated = load_scne(raw_scene)['baskets']
            except (UnicodeDecodeError, ValueError):
                dedicated = BinaryScene(raw_scene).document['baskets']
            template = dedicated['Material'][TEMPLATE_MATERIAL]
            for material_name in (glass_name, hole_name):
                material = copy.deepcopy(b['Material'][material_name])
                material['Resource'] = copy.deepcopy(template['Resource'])
                assert material == template
            assert b['Material'][glass_name]['Resource'] == b['Material'][hole_name]['Resource']
            assert b['Effect'][EFFECT] == dedicated['Effect'][EFFECT]
            assert 'Presentation' in b['Effect'][EFFECT]['Technique']['Default']['Pass']
            dedicated_dependencies = sorted(set(_binaries(dedicated['Effect'][EFFECT])) | {SCRIPT})
            assert len(dedicated_dependencies) == 15
            for dependency in dedicated_dependencies:
                assert current.read(dependency) == dedicated_archive.read(dependency)
        for effect_name, old_effect in original['Effect'].items():
            assert b['Effect'][effect_name] == old_effect
        textures = []
        for slot, resource in b['Material'][glass_name]['Resource'].items():
            spec = b['Texture'][resource['Pixelmap']]
            dds = spec['Binary'][:-4] + '.dds'
            payload = current.read(dds)
            assert spec['Binary'] not in current.NameToInfo
            width, height = spec['Width'], spec['Height']
            block = 16 if spec['Format'] in ('BC3_UNORM', 'BC7_UNORM') else 8
            data_offset = 148 if spec['Format'] == 'BC7_UNORM' else 128
            expected = sum(max(1, (max(1, width >> i) + 3) // 4) *
                           max(1, (max(1, height >> i) + 3) // 4) * block for i in range(spec['Mips']))
            assert len(payload) == data_offset + expected and spec['PixelDataSize'] == expected
            assert (width, height, spec['Mips']) == (512, 512, 10)
            im = np.asarray(Image.open(io.BytesIO(payload)).convert('RGBA'))
            assert len(np.unique(im.reshape(-1, 4), axis=0)) == 1
            channels = im[0, 0].astype(float) / 255.
            if spec.get('TexelUsage') != 'LINEAR':
                channels[:3] = np.where(channels[:3] <= .04045, channels[:3] / 12.92,
                                        ((channels[:3] + .055) / 1.055) ** 2.4)
            assert np.allclose(spec['Min'], channels, rtol=0, atol=1e-12)
            assert spec['Min'] == spec['Max']
            textures.append({'slot': slot, 'dds': dds, 'dimensions': [width, height],
                             'mips': spec['Mips'], 'decoded_rgba': im[0, 0].tolist(),
                             'exact_texture_min_max_metadata': spec['Min']})
        resource_count = 0
        def closure(value):
            nonlocal resource_count
            if isinstance(value, dict):
                for k, v in value.items():
                    if k == 'Binary' and isinstance(v, str):
                        aliases = (v, v[:-4] + '.dds' if v.endswith('.tld') else v,
                                   v[:-3] + '.bin' if v.endswith('.gz') else v)
                        assert any(a in current.NameToInfo for a in aliases), v
                        resource_count += 1
                    else:
                        closure(v)
            elif isinstance(value, list):
                for child in value:
                    closure(child)
        closure(b)
        for material in rig['weighted_materials'].values():
            mat = b['Material'][material]
            assert mat['Effect'] == rig['weighted_effect']
            assert mat['Script'] in current.NameToInfo
            for resource in mat['Resource'].values():
                assert resource['Pixelmap'] in b['Texture']
            for tech in ('AssetHires', 'AssetLores'):
                p = b['Effect'][mat['Effect']]['Technique'][tech]['Pass']['GBuffer']
                assert p['VS']['Input']['WEIGHTDATA0']['Type'] == 'uint'
                assert p['VS']['Binary'] in current.NameToInfo and p['PS']['Binary'] in current.NameToInfo
    return {'revision': metadata['revision'], 'output': str(path), 'output_bytes': path.stat().st_size,
            'build_report_sha256': metadata['output_sha256'], 'sha256_not_recomputed': True,
            'scope': 'Independent final basket rig, all LODs, native glass and basket resource closure',
            'game_tested': False, 'vertices': n, 'primitives': len(model['Prim']),
            'lod_count': 12, 'index_count': len(indices), 'native_rim_lods_exact': rim_verified,
            'native_position_and_frame_weight_prefix_exact': True,
            'native_four_bones_six_objects_glass_rimr_preserved': True,
            'bone_hierarchy': bones,
            'weight_schema': 'R32_UINT low8=count-1; rigid high24=bone; mixed high24=matrix uint32 index; matrix high16=bone, low16=UNORM16 weight',
            'new_weight_distribution': histogram, 'mixed_weights_integer_sums_65535': True,
            'moved_static_parts_absent': len(rig['source_models_removed']),
            'fixed_base_static_parts_present': len(rig['fixed_base_models_kept_exactly_static']),
            'complete_dedicated_outdoor_glass_contract_verified': True,
            'presentation_pass_and_15_native_shader_script_bytes_exact': True,
            'glass_textures': textures,
            'basket_binary_references_resolved': resource_count,
            'synthetic_pose_from_factory': rig['synthetic_pose_check'],
            'limits': ['Actual replay glass and hanging motion remain untested in game.',
                       'Full package hash, CRC and D3D resource creation are separately recorded by the root builder.']}


if __name__ == '__main__':
    path = ROOT / 'output/arena_700_int.iff'
    report = audit(path)
    (ROOT / 'validation/iff-current-independent.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report, ensure_ascii=False))
