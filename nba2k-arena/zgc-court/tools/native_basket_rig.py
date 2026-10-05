"""Attach source hoops to the existing, runtime-bound NBA 2K26 basket model.

Factory only: no IFF or blend is written. Call after repair_glass():
    report = attach_custom_basket(level, current_zip, donor_zip, extra,
                                  source_models=labels)

The native four-bone hierarchy, six object identities and MAIN bindings stay
unchanged. Geometry remains in basket rest/object space, not joint-local space.
All old POSITION and tangent/weight bytes are retained. The original rim index
sequence is retained at every LOD; hidden donor support draws remain degenerate.
This is a native-schema candidate with offline pose checks, not a game test.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import zipfile
import zlib

import numpy as np

from iff_codec import (decode_attribute, decode_normals, dump_scne, encode_normals,
                       encode_uv, load_scne, resolve_binary, texture_density, unit)


TEMPLATE = 'basket_stanchiont_outdoor:backboard_mat'
EXPECTED_EFFECT = 'asset.fx#af5fe6aa8a3a361d'
ROOT = Path(__file__).resolve().parents[1]


def decode_weights(words, matrix_words):
    """Return Nx4 influences from the original R32_UINT/WeightBits=16 schema.

    Low byte = influence count minus one. For rigid vertices, high 24 bits
    hold a bone index. For mixed vertices, they index 32-bit matrix entries;
    each entry has lower-16 UNORM weight and upper-16 bone index.
    """
    result = np.zeros((len(words), 4), dtype=float)
    for i, word in enumerate(words):
        word = int(word)
        count, offset = (word & 255) + 1, word >> 8
        if count == 1:
            if offset > 3:
                raise ValueError('Rigid bone outside four-bone hierarchy')
            result[i, offset] = 1.
        else:
            if offset + count > len(matrix_words):
                raise ValueError('Mixed weight pointer outside matrix buffer')
            for entry in matrix_words[offset:offset + count]:
                entry = int(entry)
                bone = entry >> 16
                if bone > 3:
                    raise ValueError('Mixed bone outside four-bone hierarchy')
                result[i, bone] += (entry & 65535) / 65535.
        if abs(result[i].sum() - 1.) > 1. / 65535:
            raise ValueError('Native weights do not sum to one')
    return result


def _resource(extra, prefix, raw):
    key = prefix + '.' + hashlib.sha256(raw).hexdigest()[:16] + '.bin'
    if key in extra and extra[key] != raw:
        raise ValueError('Resource digest collision')
    extra[key] = raw
    return key


def _bounds(p):
    low, high = p.min(0), p.max(0)
    center = (low + high) / 2
    return {'Min': low.tolist(), 'Max': high.tolist(), 'Center': center.tolist(),
            'Radius': float(np.linalg.norm(p - center, axis=1).max())}


def _matrix(obj):
    return np.asarray(obj['Matrix'], dtype=float).reshape(4, 4).T


def _read_mesh(archive, model, source_object, inverse_basket):
    p = decode_attribute(archive, model, 'POSITION0')[:, :3]
    n = decode_normals(decode_attribute(archive, model, 'TANGENTFRAME0'))
    uv = decode_attribute(archive, model, 'TEXCOORD0')[:, :2]
    world = _matrix(source_object)
    combined = inverse_basket @ world
    p = p @ combined[:3, :3].T + combined[:3, 3]
    n = unit(n @ np.linalg.inv(combined[:3, :3]))
    if np.linalg.det(combined[:3, :3]) < 0:
        raise ValueError('Unexpected mirrored source instance')
    if len(model['Prim']) != 1:
        raise ValueError('Source hoop part must have exactly one primitive')
    prim = model['Prim'][0]
    draw = prim.get('LodList', [prim])[0]
    raw = archive.read(resolve_binary(archive, model['IndexBuffer']['Binary']))
    ix = np.frombuffer(raw, '<u2')[draw.get('Start', 0):draw.get('Start', 0) + draw['Count']]
    return p, n, uv, ix.reshape(-1, 3).copy()


def _split_horizontal(p, n, uv, triangles, cuts):
    """Insert weight transition rings without changing the source surface."""
    data = np.concatenate([p, n, uv], axis=1)
    output, indices = [], []

    def clip(poly, height, below):
        result = []
        for start, end in zip(poly, poly[1:] + poly[:1]):
            a = start[1] <= height if below else start[1] >= height
            b = end[1] <= height if below else end[1] >= height
            if a:
                result.append(start)
            if a != b:
                point = start + (end - start) * ((height - start[1]) / (end[1] - start[1]))
                point[1] = height
                result.append(point)
        return result

    for tri in triangles:
        pieces = [[data[i].copy() for i in tri]]
        for height in cuts:
            next_pieces = []
            for poly in pieces:
                ys = [v[1] for v in poly]
                if min(ys) < height < max(ys):
                    next_pieces.extend([clip(poly, height, True), clip(poly, height, False)])
                else:
                    next_pieces.append(poly)
            pieces = next_pieces
        for poly in pieces:
            for j in range(1, len(poly) - 1):
                tri_data = [poly[0], poly[j], poly[j + 1]]
                if np.linalg.norm(np.cross(tri_data[1][:3] - tri_data[0][:3],
                                           tri_data[2][:3] - tri_data[0][:3])) < 1e-8:
                    continue
                start = len(output)
                output.extend(tri_data)
                indices.append([start, start + 1, start + 2])
    a = np.asarray(output)
    return a[:, :3], unit(a[:, 3:6]), a[:, 6:8], np.asarray(indices, dtype=np.int64)


def _hausdorff(a, b):
    def distance(x, y):
        result = 0.
        for start in range(0, len(x), 256):
            d = np.sum((x[start:start + 256, None, :] - y[None, :, :]) ** 2, axis=2)
            result = max(result, float(d.min(1).max()))
        return result ** .5
    return max(distance(a, b), distance(b, a))


def _weighted_material(baskets, level, name, extra, cache):
    if name in cache:
        return cache[name]
    from PIL import Image
    from native_textures import encode

    source = level['Material'][name]
    template = baskets['Material'][TEMPLATE]
    if template['Effect'] != EXPECTED_EFFECT:
        raise ValueError('Unexpected native weighted opaque material')
    effect = baskets['Effect'][EXPECTED_EFFECT]
    for tech in ('AssetHires', 'AssetLores'):
        inputs = effect['Technique'][tech]['Pass']['GBuffer']['VS']['Input']
        if set(inputs) != {'POSITION0', 'TANGENTFRAME0', 'TEXCOORD0', 'WEIGHTDATA0', 'SV_INSTANCEID0'}:
            raise ValueError('Weighted shader input signature changed')
    material = copy.deepcopy(template)
    for slot in ('AlbedoMap', 'NormalAndRoughMap'):
        pixelmap = source['Resource'][slot]['Pixelmap']
        material['Resource'][slot] = {'Pixelmap': pixelmap}
        spec = copy.deepcopy(level['Texture'][pixelmap])
        if pixelmap in baskets['Texture'] and baskets['Texture'][pixelmap] != spec:
            raise ValueError('Conflicting basket texture descriptor')
        baskets['Texture'][pixelmap] = spec
    metal = float(source.get('Parameter', {}).get('DefaultMetalness', 0.))
    metal_byte = int(np.clip(np.rint(metal * 255), 0, 255))
    pixelmap, spec, _ = encode(Image.new('RGB', (4, 4), (metal_byte,) * 3), extra, linear=True)
    baskets['Texture'][pixelmap] = spec
    material['Resource']['MetalMap'] = {'Pixelmap': pixelmap}
    material['Parameter']['AlbedoModulate'] = source.get('Parameter', {}).get('AlbedoModulate', [1., 1., 1., 1.])
    # This is a real native Effect float at offset 208. Normal maps are neutral.
    assert effect['Parameter']['NormalHeight']['Offset'] == 208
    material['Parameter']['NormalHeight'] = 0.
    if any(p.get('CULLMODE') == 'NONE' for t in source.get('Technique', {}).values()
           for p in t.get('Pass', {}).values()):
        for t in material['Technique'].values():
            for p in t.get('Pass', {}).values():
                p['CULLMODE'] = 'NONE'
    new_name = 'zgc_r09:skinned_' + name.split(':')[-1]
    baskets['Material'][new_name] = material
    cache[name] = new_name
    return new_name


def attach_custom_basket(level, current_archive, donor_archive, extra, *, source_models):
    """Mutate only level hoop Models/Objects and the extra baskets resource.

    Required: labels from native-source-build.json; call repair_glass first.
    No disk writes. ``extra`` receives native buffers, DDS/TLD aliases and the
    serialized baskets.SCNE; the root packer removes experimental raw TLDs as
    usual. Source hoops use tags, never material/part numbers.
    """
    rows = source_models.get('models', []) if isinstance(source_models, dict) else source_models
    selected = [r for r in rows if 'hoops' in r.get('tags', []) and r['model'] in level['Model']]
    if not selected or any(r['source_object'].startswith(('Backboard.', 'Rim.', 'Net')) for r in selected):
        raise ValueError('Expected fresh static source hoops after glass/rim duplicate removal')
    original = load_scne(donor_archive.read('baskets.SCNE'))['baskets']
    document = load_scne(extra.get('baskets.SCNE') or current_archive.read('baskets.SCNE'))
    baskets = document['baskets']
    if baskets['Object'] != original['Object']:
        raise ValueError('Runtime basket object bindings differ from donor')
    names = [n for n in original['Model'] if n.endswith(':basket')]
    if len(names) != 1:
        raise ValueError('Expected one shared native basket model')
    name = names[0]
    native = original['Model'][name]
    model = copy.deepcopy(native)
    if native['WeightBits'] != 16 or len(native['Transform']) != 4:
        raise ValueError('Unexpected native basket skin layout')
    if [s['Stride'] for s in native['VertexStream']] != [8, 4, 8]:
        raise ValueError('Unexpected native weighted stream strides')
    native_p = decode_attribute(donor_archive, native, 'POSITION0')[:, :3]
    native_uv = decode_attribute(donor_archive, native, 'TEXCOORD0')[:, :2]
    pos_raw = donor_archive.read(resolve_binary(donor_archive, native['VertexStream'][0]['Binary']))
    frame_raw = donor_archive.read(resolve_binary(donor_archive, native['VertexStream'][2]['Binary']))
    frames = np.frombuffer(frame_raw, '<u4').reshape(-1, 2)
    matrix_raw = donor_archive.read(resolve_binary(donor_archive, native['MatrixWeightsBuffer']['Binary']))
    matrix_words = np.frombuffer(matrix_raw, '<u4').tolist()
    native_weights = decode_weights(frames[:, 1], matrix_words)
    native_ib = np.frombuffer(donor_archive.read(resolve_binary(donor_archive, native['IndexBuffer']['Binary'])), '<u2')
    rim = next(p for p in native['Prim'] if p.get('Mesh') == 'basket_rimShape')
    base_prim = next(p for p in native['Prim'] if p.get('Mesh') == 'basket_stanchionk_baseShape')
    base_range = base_prim['LodList'][0]
    base_ids = np.unique(native_ib[base_range['Start']:base_range['Start'] + base_range['Count']])
    # Authored weight curve uses measured original support blend groups. The
    # intermediate topology follows this source column, not donor appearance.
    root_height = list(native['Transform'].values())[1]['Translate'][1]
    curve = [(root_height, 0.)]
    for word in (0x201, 0x1):
        ids = base_ids[frames[base_ids, 1] == word]
        curve.append((float(np.median(native_p[ids, 1])), float(native_weights[ids[0], 1])))
    ids = base_ids[frames[base_ids, 1] == 0x100]
    curve.append((float(native_p[ids, 1].min()), 1.))
    curve = np.asarray(curve)
    if not np.all(np.diff(curve[:, 0]) > 0):
        raise ValueError('Native support weight profile is not monotone')

    basket_instances = [o for o in baskets['Object'].values() if o.get('Target') == name]
    if len(basket_instances) != 2:
        raise ValueError('Expected two native assembly instances')
    inverse_by_side = {}
    for obj in basket_instances:
        side = 'reference_half' if obj['Matrix'][14] < 0 else 'open_half'
        inverse_by_side[side] = np.linalg.inv(_matrix(obj))
    parts, sides, fixed_static = [], {'reference_half': [], 'open_half': []}, []
    for row in selected:
        tags = set(row.get('tags', []))
        side = next((s for s in sides if s in tags), None)
        if side is None:
            raise ValueError('Hoop source part has no recognized half')
        objects = [o for o in level['Object'].values() if o.get('Target') == row['model']]
        if len(objects) != 1:
            raise ValueError('Hoop part must have exactly one static instance')
        p, n, uv, ix = _read_mesh(current_archive, level['Model'][row['model']], objects[0], inverse_by_side[side])
        # Ground hardware is already correctly static. Retain its exact two-
        # side source geometry, including intentionally irregular weld beads;
        # only the moving assembly and rooted column belong in the shared rig.
        if p[:, 1].max() < root_height:
            fixed_static.append(row['model'])
            continue
        part = dict(row=row, p=p, n=n, uv=uv, ix=ix)
        sides[side].append(part)
        if side == 'reference_half':
            parts.append(part)
    if len(sides['reference_half']) != len(sides['open_half']):
        raise ValueError('Native shared model requires equal two-side source part counts')
    symmetry = []
    material_names = {p['row']['material'] for p in parts}
    if material_names != {p['row']['material'] for p in sides['open_half']}:
        raise ValueError('Shared basket would replace different material appearances')
    for material_name in sorted(material_names):
        a = np.concatenate([p['p'] for p in sides['reference_half'] if p['row']['material'] == material_name])
        b = np.concatenate([p['p'] for p in sides['open_half'] if p['row']['material'] == material_name])
        error = _hausdorff(a, b)
        if error > .10:
            raise ValueError('Two native instances need different source geometry: ' + str((material_name, error)))
        symmetry.append({'material': material_name, 'max_geometry_difference_cm': error})

    ps = native['VertexFormat']['POSITION0']
    offset, scale = np.asarray(ps['Offset'][:3]), np.asarray(ps['Scale'][:3])
    all_p, all_uv = [native_p], [native_uv]
    all_pos_raw, all_frame_raw = [pos_raw], [frame_raw]
    new_prims, part_reports, material_cache = [], [], {}
    vertex_count = len(native_p)
    weight_cache = {}

    def word_for(weight1):
        q = int(np.clip(np.rint(weight1 * 65535), 0, 65535))
        if q == 0:
            return 0
        if q == 65535:
            return 0x100
        if q not in weight_cache:
            pointer = len(matrix_words)
            matrix_words.extend([65535 - q, (1 << 16) | q])
            weight_cache[q] = (pointer << 8) | 1
        return weight_cache[q]

    for part in parts:
        row = part['row']
        p, n, uv, ix = (part[k] for k in ('p', 'n', 'uv', 'ix'))
        original_vertices = len(p)
        if row['source_object'].startswith('Support upright.'):
            p, n, uv, ix = _split_horizontal(p, n, uv, ix, curve[:, 0])
            weight1 = np.interp(p[:, 1], curve[:, 0], curve[:, 1])
            role = 'authored root/base blend using native support profile'
        elif p[:, 1].max() < root_height:
            weight1 = np.zeros(len(p))
            role = 'fixed root 0'
        else:
            weight1 = np.ones(len(p))
            role = 'board/base bone 1'
        words = np.asarray([word_for(w) for w in weight1], dtype='<u4')
        raw_q = np.rint((p - offset) / scale * 65535)
        if np.any(raw_q < 0) or np.any(raw_q > 65535):
            raise ValueError('New basket geometry exceeds original POSITION cube')
        q = np.column_stack([raw_q.astype('<u2'), np.full(len(p), 65535, dtype='<u2')])
        decoded_p = q[:, :3].astype(float) / 65535 * scale + offset
        packed = np.column_stack([encode_normals(n), words]).astype('<u4')
        material = _weighted_material(baskets, level, row['material'], extra, material_cache)
        weights = decode_weights(words, matrix_words)
        used_bones = np.flatnonzero(weights.sum(0))
        density = texture_density(decoded_p, uv, ix)
        prim = {'Material': material, 'Mesh': 'zgc_' + row['source_object'].replace('.reference', ''),
                'Type': 'TRIANGLE_LIST', 'BlendIndexRange': [int(used_bones.min()), int(used_bones.max())],
                **_bounds(decoded_p), **{f'Duv{i}': density.copy() for i in (0, 1, 2)}}
        new_prims.append((prim, (ix + vertex_count).reshape(-1)))
        all_p.append(decoded_p); all_uv.append(uv)
        all_pos_raw.append(q.tobytes()); all_frame_raw.append(packed.tobytes())
        part_reports.append({'source_object': row['source_object'], 'source_model': row['model'],
                             'vertices_before': original_vertices, 'vertices': len(p),
                             'triangles': len(ix), 'role': role,
                             'bone_weight_words': sorted(set(map(int, words))),
                             'position_error_cm': float(np.linalg.norm(decoded_p - p, axis=1).max()),
                             'min': decoded_p.min(0).tolist(), 'max': decoded_p.max(0).tolist()})
        vertex_count += len(p)
    if vertex_count >= 65536:
        raise ValueError('Shared basket exceeds original R16 index limit')
    uv_raw, uv_spec = encode_uv(np.concatenate(all_uv))
    decoded_uv = np.frombuffer(uv_raw, '<i2').reshape(-1, 2).astype(float) / 32767
    decoded_uv = decoded_uv * np.asarray(uv_spec['Scale'][:2]) + np.asarray(uv_spec['Offset'][:2])
    rim_ids = np.unique(np.concatenate([native_ib[r['Start']:r['Start'] + r['Count']] for r in rim['LodList']]))
    rim_uv_error = float(np.abs(decoded_uv[rim_ids] - native_uv[rim_ids]).max())
    model['VertexFormat']['TEXCOORD0'] = {**uv_spec, 'Stream': 1}
    model['VertexStream'] = []
    for stride, payload in ((8, b''.join(all_pos_raw)), (4, uv_raw), (8, b''.join(all_frame_raw))):
        model['VertexStream'].append({'Stride': stride, 'Size': len(payload),
                                      'Binary': _resource(extra, 'VertexBuffer', payload)})
    assert b''.join(all_pos_raw)[:len(pos_raw)] == pos_raw
    assert b''.join(all_frame_raw)[:len(frame_raw)] == frame_raw
    weight_raw = np.asarray(matrix_words, '<u4').tobytes()
    assert weight_raw[:len(matrix_raw)] == matrix_raw
    model['MatrixWeightsBuffer'] = {'Format': 'R32_UINT', 'Dimension': 'BYTEADDRESSBUFFER',
                                   'Size': len(weight_raw), 'Binary': _resource(extra, 'MatrixWeightsBuffer', weight_raw)}
    model.update(_bounds(np.concatenate(all_p)))
    model['Prim'] = copy.deepcopy(native['Prim']) + [p for p, _ in new_prims]
    for prim in model['Prim']:
        prim['LodList'] = [None] * 12
    all_indices, lods = [], {}
    cursor = 0
    rim_checks = []
    # Contiguous per-LOD slices match the native coarse-to-fine buffer order.
    # Every custom part appears in every LOD, with all vertices resident.
    for lod in reversed(range(12)):
        start = cursor
        for i, prim in enumerate(native['Prim']):
            draw = prim['LodList'][lod]
            values = native_ib[draw['Start']:draw['Start'] + draw['Count']].copy()
            if prim.get('Mesh') != 'basket_rimShape':
                values[:] = 0
            else:
                rim_checks.append(np.array_equal(values, native_ib[draw['Start']:draw['Start'] + draw['Count']]))
            model['Prim'][i]['LodList'][lod] = {'Start': cursor, 'Count': len(values)}
            all_indices.append(values); cursor += len(values)
        for i, (_, values) in enumerate(new_prims, len(native['Prim'])):
            model['Prim'][i]['LodList'][lod] = {'Start': cursor, 'Count': len(values)}
            all_indices.append(values); cursor += len(values)
        lods['Lod' + str(lod)] = {'NumMaskBits': lod, 'NumVertices': vertex_count,
                                'StartIndex': start, 'NumIndices': cursor - start,
                                'NumTris': (cursor - start) // 3}
    for prim in model['Prim']:
        prim.update(prim['LodList'][0])
    model['Clod']['Lods'] = {f'Lod{i}': lods[f'Lod{i}'] for i in range(12)}
    ib = np.concatenate(all_indices).astype('<u2').tobytes()
    model['IndexBuffer'] = {'Format': 'R16_UINT', 'Size': len(ib), 'Binary': _resource(extra, 'IndexBuffer', ib)}
    model['IndexBufferCrc32'] = zlib.crc32(ib)
    assert all(rim_checks) and len(rim_checks) == 12
    assert model['Transform'] == native['Transform']
    assert model['BlendIndexRange'] == native['BlendIndexRange'] == [0, 2]
    baskets['Model'][name] = model
    removed = {p['row']['model'] for side in sides.values() for p in side}
    for key in list(level['Object']):
        if level['Object'][key].get('Target') in removed:
            del level['Object'][key]
    for key in removed:
        del level['Model'][key]
    assert baskets['Object'] == original['Object']
    extra['baskets.SCNE'] = dump_scne(document)

    # Independent synthetic skin delta: a 1 cm bone-1 translation. The lower
    # foot stays fixed, upper frame and native glass both move the same amount.
    support = next(r for r in part_reports if r['source_object'].startswith('Support upright.'))
    weights_all = decode_weights(np.frombuffer(b''.join(all_frame_raw), '<u4').reshape(-1, 2)[:, 1], matrix_words)
    custom_p = np.concatenate(all_p)[len(native_p):]
    custom_w = weights_all[len(native_p):]
    lower = custom_p[:, 1] < root_height - .1
    upper = custom_p[:, 1] > curve[-1, 0] + .1
    assert np.all(custom_w[lower, 1] == 0.)
    assert np.all(custom_w[upper, 1] == 1.)
    # Exercise an actual rotation about the native base pivot, with a small
    # translation, rather than testing the weights only with a translation.
    angle = np.deg2rad(1.25)
    rotation = np.array([[1., 0., 0.], [0., np.cos(angle), -np.sin(angle)],
                         [0., np.sin(angle), np.cos(angle)]])
    pivot = np.asarray(list(native['Transform'].values())[1]['Translate'])
    translation = np.array([0., -.4, .3])
    upper_pose = (custom_p - pivot) @ rotation.T + pivot + translation
    skinned = custom_p * custom_w[:, 0, None] + upper_pose * custom_w[:, 1, None]
    foot_error = float(np.linalg.norm(skinned[lower] - custom_p[lower], axis=1).max())
    frame_error = float(np.linalg.norm(skinned[upper] - upper_pose[upper], axis=1).max())
    glass_name = next(n for n in original['Model'] if n.endswith(':glass'))
    glass_model = original['Model'][glass_name]
    glass_p = decode_attribute(donor_archive, glass_model, 'POSITION0')[:, :3]
    glass_raw = donor_archive.read(resolve_binary(donor_archive, glass_model['VertexStream'][2]['Binary']))
    assert np.all(np.frombuffer(glass_raw, '<u4').reshape(-1, 2)[:, 1] == 0x100)
    glass_pose = (glass_p - pivot) @ rotation.T + pivot + translation
    # Common rigid bone 1 must preserve glass/frame separation in a trial pose.
    sample_frame = custom_p[upper][::max(1, int(upper.sum()) // 32)]
    sample_frame_pose = upper_pose[upper][::max(1, int(upper.sum()) // 32)]
    nearest = np.argmin(np.sum((sample_frame[:, None, :] - glass_p[None, :, :]) ** 2, axis=2), axis=1)
    gaps_before = np.linalg.norm(sample_frame - glass_p[nearest], axis=1)
    gaps_after = np.linalg.norm(sample_frame_pose - glass_pose[nearest], axis=1)
    gap_error = float(np.abs(gaps_after - gaps_before).max())
    assert foot_error == 0. and frame_error == 0. and gap_error < 1e-9
    return {'revision': 'R10', 'game_tested': False, 'model': name,
            'source_parts_removed_from_level': len(removed), 'source_models_removed': sorted(removed),
            'fixed_base_models_kept_exactly_static': sorted(fixed_static),
            'shared_instances': 2, 'source_canonical_side': 'reference_half', 'symmetry': symmetry,
            'native_vertices_preserved': len(native_p), 'total_vertices': vertex_count,
            'primitive_count': len(model['Prim']), 'lod_count': 12,
            'native_position_bytes_preserved': True, 'native_tangent_weight_bytes_preserved': True,
            'native_matrix_weight_prefix_preserved': True, 'native_rim_index_sequences_preserved_all_lods': True,
            'native_rim_uv_max_error': rim_uv_error,
            'native_object_and_transform_bindings_preserved': True,
            'weighted_materials': material_cache, 'weighted_effect': EXPECTED_EFFECT,
            'stream_strides': [8, 4, 8], 'weight_bits': 16,
            'weight_curve_height_cm_and_bone1_fraction': curve.tolist(),
            'synthetic_pose_check': {'fixed_lower_vertices': int(lower.sum()),
                                     'upper_frame_vertices_follow_glass_bone1': int(upper.sum()),
                                     'mixed_column_vertices': int(np.count_nonzero((custom_w[:, 1] > 0) & (custom_w[:, 1] < 1))),
                                     'column_total_vertices_after_transition_splits': support['vertices'],
                                     'trial_base_rotation_degrees': 1.25,
                                     'trial_base_translation_cm': translation.tolist(),
                                     'fixed_foot_max_displacement_cm': foot_error,
                                     'upper_frame_max_rigid_pose_error_cm': frame_error,
                                     'glass_frame_separation_max_change_cm': gap_error,
                                     'passed': True},
            'parts': part_reports,
            'limits': ['Runtime playback/hanging test is still required.',
                       'Column weight curve is an authored adaptation of measured native support weights.',
                       'Native shared basket instances replace source-side geometry differences below 0.10 cm.',
                       'Rim UV values are re-quantized to include source UV range; native rim positions and skin bytes are exact.']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--iff', default=str(ROOT / 'output/arena_700_int.iff'))
    parser.add_argument('--report', default=str(ROOT / 'validation/native-basket-rig-current.json'))
    args = parser.parse_args()
    path, report_path = Path(args.iff).resolve(), Path(args.report).resolve()
    if not path.is_relative_to(ROOT) or not report_path.is_relative_to(ROOT):
        raise ValueError('Dry-run paths must stay inside this project')
    labels = json.loads((ROOT / 'validation/native-source-build.json').read_text(encoding='utf8'))
    with zipfile.ZipFile(path) as current, zipfile.ZipFile(ROOT.parent / '洛克公园/arena_blacktop_ext.iff') as donor:
        level = load_scne(current.read('level.SCNE'))['level']
        extra = {}
        report = attach_custom_basket(level, current, donor, extra, source_models=labels)
    report['dry_run_only'] = True
    report['new_payload_count'] = len(extra)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: report[k] for k in ('total_vertices', 'primitive_count', 'lod_count',
                                          'source_parts_removed_from_level', 'synthetic_pose_check')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
