"""Read-only basket resource, authoring bind geometry and skin-weight audit.

No IFF is rewritten. Bind positions are the stored authoring positions, checked
against each original Prim bound. They are NOT an evaluated game animation.
The rimr model is a reflection-pass helper, not a second physical rim. Its
runtime rimpivot matrix is unavailable and must not be replaced with identity.

Weight decoding follows original glass/basket VS DXIL: low 8 bits + 1 is the
influence count. A rigid vertex stores its palette index in the upper 24 bits;
otherwise those bits address uint32 MatrixWeightsBuffer entries, each holding
UNORM16 weight below a uint16 palette index. Shaders fetch these in pairs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import numpy as np

from revision3_preview import Reader
from scene_primitives import iter_primitives

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'arena_clutchtime_int_master@GameObjects@MAIN@basket0:'
SHADER_EVIDENCE = {
    'glass': 'VS.7686a8a62e2bfb95.shader',
    'basket': 'VS.f36b0f5e570448d9.shader',
    'rim_reflection': 'VS.95138f09aa9d1d31.shader',
}


def fragment(raw):
    raw = raw.strip()
    return json.loads(raw if raw.startswith(b'{') else b'{' + raw + b'}')


def decode_weights(words, matrix_weights, *, palette_size=None):
    """Return CSR arrays (offsets, palette_indices, weights), without renormalizing.

    For odd counts > 1 the verified shader also reads one padding influence;
    require that padding to have zero weight instead of silently discarding it.
    Palette indices are model-local shader indices, not assumed hierarchy ids.
    """
    values = np.asarray(words)
    if values.ndim != 1 or values.dtype.kind not in 'iu':
        raise ValueError('WEIGHTDATA must be a one-dimensional integer array')
    if np.any(values < 0) or np.any(values.astype(np.uint64) > 0xffffffff):
        raise ValueError('WEIGHTDATA exceeds uint32 range')
    if len(matrix_weights) % 4:
        raise ValueError('MatrixWeightsBuffer must contain complete uint32 entries')
    table = np.frombuffer(matrix_weights, '<u4')
    offsets, joints, weights = [0], [], []
    decoded = {}
    for value in values.tolist():
        value = int(value)
        if value not in decoded:
            count, start = (value & 255) + 1, value >> 8
            if count == 1:
                ji, wi = np.array([start]), np.array([1.])
            else:
                read_count = (count + 1) // 2 * 2
                if start + read_count > len(table):
                    raise ValueError('Weight influence range exceeds MatrixWeightsBuffer')
                packed = table[start:start + read_count]
                ji, wi = (packed >> 16).astype(int), (packed & 65535).astype(float) / 65535
                if count != read_count and wi[-1] != 0:
                    raise ValueError('Odd influence count has nonzero shader padding weight')
                if abs(float(wi.sum()) - 1) > 1 / 65535 + 1e-12:
                    raise ValueError('Skin weights do not sum to one')
                # Even a zero-weight entry is fetched by the native shader.
            if palette_size is not None and (np.any(ji < 0) or np.any(ji >= palette_size)):
                raise ValueError('Skin palette index outside supplied palette')
            decoded[value] = (ji, wi)
        ji, wi = decoded[value]
        joints.extend(ji.tolist())
        weights.extend(wi.tolist())
        offsets.append(len(joints))
    return {'offsets': np.array(offsets, dtype=np.int64),
            'palette_indices': np.array(joints, dtype=np.int64),
            'weights': np.array(weights, dtype=float)}


def apply_skin_palette(positions, skin, matrices):
    """Evaluate verified 3x4 shader palette math when actual matrices are supplied.

    This deliberately does not invent inverse bind matrices or a live pose from
    the scene's Translate fields. Caller supplies the complete skin palette.
    """
    positions, matrices = np.asarray(positions, float), np.asarray(matrices, float)
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError('Expected Nx3 positions')
    if matrices.ndim != 3 or matrices.shape[1:] != (3, 4):
        raise ValueError('Expected shader palette Nx3x4 matrices')
    offsets, ids, weights = skin['offsets'], skin['palette_indices'], skin['weights']
    if len(offsets) != len(positions) + 1 or offsets[0] != 0 or offsets[-1] != len(ids):
        raise ValueError('Invalid skin offsets')
    if len(weights) != len(ids) or np.any(np.diff(offsets) < 1):
        raise ValueError('Invalid skin influence arrays')
    if np.any(ids < 0) or np.any(ids >= len(matrices)):
        raise ValueError('Skin palette index outside supplied palette')
    if not all(np.isfinite(a).all() for a in (positions, matrices, weights)):
        raise ValueError('Non-finite skin input')
    vertices = np.repeat(np.arange(len(positions)), np.diff(offsets))
    homogeneous = np.column_stack([positions, np.ones(len(positions))])
    transformed = np.einsum('nij,nj->ni', matrices[ids], homogeneous[vertices])
    result = np.zeros_like(positions)
    np.add.at(result, vertices, transformed * weights[:, None])
    return result


def hierarchy_bind_transforms(model):
    """Resolve the donor's translation-only hierarchy; never call it skin palette."""
    entries = list(model.get('Transform', {}).items())
    transforms, visiting = {}, set()

    def resolve(index):
        if index in transforms:
            return transforms[index]
        if index in visiting:
            raise ValueError('Cycle in transform hierarchy')
        if not 0 <= index < len(entries):
            raise ValueError('Transform parent outside hierarchy')
        visiting.add(index)
        name, node = entries[index]
        node = node or {}
        unsupported = set(node) - {'Parent', 'Child', 'Sibling', 'Translate'}
        if unsupported:
            raise ValueError(f'Unverified transform fields: {sorted(unsupported)}')
        local = np.eye(4)
        local[:3, 3] = node.get('Translate', [0, 0, 0])
        parent = node.get('Parent')
        world = resolve(parent) @ local if parent is not None else local
        visiting.remove(index)
        transforms[index] = world
        return world

    return [{'index': i, 'name': name, 'parent': (node or {}).get('Parent'),
             'matrix': resolve(i).tolist(),
             'translation_cm': resolve(i)[:3, 3].tolist(),
             'null_authoring_node': node is None}
            for i, (name, node) in enumerate(entries)]


def classify_primitive(model_name, index):
    """Exact donor Prim inventory. Shared material names cannot separate parts."""
    if model_name.endswith(':rimr'):
        return 'rim_reflection_only'
    if model_name.endswith(':glass'):
        return 'backboard_glass' if index == 3 else 'shotclock_glass'
    if model_name.endswith(':basket'):
        if index <= 13:
            return 'indoor_stanchion_and_padding'
        if index <= 87:
            return 'shotclocks_supports_wires_and_speakers'
        if index in (88, 89, 90):
            return 'backboard_frame_and_target'
        if index == 91:
            return 'rim_hinge_gasket'
        if index == 92:
            return 'backboard_padding'
        if index in (93, 94, 95, 96):
            return 'backboard_led_lights'
        if index in (97, 98):
            return 'backboard_brand_decals'
        if index == 99:
            return 'physical_rim'
    return 'unclassified'


def decode_bind_model(model, reader):
    """Decode available original top-LOD geometry with bounded quantization error.

    Missing resources raise; no generated stand-ins and no added joint offsets.
    Caller must honor reflection-only classification on the resulting geometry.
    """
    if model['VertexFormat']['POSITION0']['Format'] != 'R16G16B16A16_UNORM':
        raise ValueError('Basket bound validation currently verifies native UNORM16 positions only')
    positions = reader.attribute(model, 'POSITION0')[:, :3]
    spec = model['IndexBuffer']
    dtype = {'R16_UINT': '<u2', 'R32_UINT': '<u4'}.get(spec['Format'])
    if dtype is None:
        raise ValueError('Unverified index format')
    indices = np.frombuffer(reader.raw(spec['Binary'], spec['Size']), dtype)
    prims = list(iter_primitives(model, indices=indices, vertex_count=len(positions)))
    step = np.array(model['VertexFormat']['POSITION0'].get('Scale', [1, 1, 1]))[:3] / 65535
    tolerance = float(np.max(step) * 1.05 + .0002)
    bounds = []
    for i, prim in enumerate(prims):
        selected = indices[prim['Start']:prim['Start'] + prim['Count']]
        if not len(selected):
            continue
        used = positions[selected]
        low, high = used.min(0), used.max(0)
        # Authoring bounds are independently supplied by the original asset.
        error = float(max(np.max(abs(low - prim['Min'])), np.max(abs(high - prim['Max']))))
        if error > tolerance:
            raise ValueError(f'Prim {i} bind geometry disagrees with authoring bounds: {error}')
        bounds.append({'primitive': i, 'min': low.tolist(), 'max': high.tolist(),
                       'max_authoring_bounds_error_cm': error})
    result = {'positions': positions, 'indices': indices, 'primitives': prims,
              'bound_checks': bounds, 'quantization_tolerance_cm': tolerance,
              'uv0': reader.attribute(model, 'TEXCOORD0')[:, :2]}
    if 'WEIGHTDATA0' in model['VertexFormat']:
        if model.get('WeightBits') != 16:
            raise ValueError('Only native WeightBits16 layout is verified')
        f = model['VertexFormat']['WEIGHTDATA0']
        if f['Format'] != 'R32_UINT':
            raise ValueError('Unverified weight semantic format')
        stream = model['VertexStream'][f.get('Stream', 0)]
        raw = reader.raw(stream['Binary'], stream['Size'])
        words = np.ndarray((len(positions),), '<u4', raw,
                           offset=f.get('ByteOffset', 0), strides=(stream['Stride'],))
        table_spec = model['MatrixWeightsBuffer']
        table = reader.raw(table_spec['Binary'], table_spec['Size'])
        skin = decode_weights(words, table)
        result['skin'] = skin
        result['weight_words'] = words
    return result


def audit_baskets(archive, reader=None, *, include_geometry=False):
    """Return JSON-compatible resource/primitive/preview audit; mutate nothing."""
    scene = fragment(archive.read('baskets.SCNE'))['baskets']
    reader = reader or Reader(archive)
    models, resources, resource_keys = {}, [], set()

    def inventory(value, path):
        if isinstance(value, dict):
            if 'Binary' in value:
                key = value['Binary']
                if (path, key) not in resource_keys:
                    resource_keys.add((path, key))
                    entry = {'path': path, 'binary': key,
                             'expected_uncompressed_bytes': value.get('Size'),
                             'pixel_payload_bytes': value.get('PixelDataSize'),
                             'format': value.get('Format')}
                    try:
                        raw = reader.raw(key, value.get('Size'))
                        entry.update(available=True, bytes_read=len(raw),
                                     sha256=hashlib.sha256(raw).hexdigest())
                    except ValueError as exc:
                        entry.update(available=False, reason=str(exc))
                    resources.append(entry)
            for key, child in value.items():
                inventory(child, f'{path}/{key}')
        elif isinstance(value, list):
            for i, child in enumerate(value):
                inventory(child, f'{path}/{i}')

    # Effects contain many repeated shader references; inventory each path so
    # missing texture/buffer references remain distinguishable from shader data.
    inventory(scene, 'baskets')
    for name, model in scene['Model'].items():
        prims = list(iter_primitives(model))
        entry = {'authoring_bounds_min': model['Min'], 'authoring_bounds_max': model['Max'],
                 'hierarchy': hierarchy_bind_transforms(model),
                 'blend_index_offset': model.get('BlendIndexOffset'),
                 'blend_index_range': model.get('BlendIndexRange'),
                 'classification': 'reflection_only' if name.endswith(':rimr') else 'physical_geometry',
                 'primitives': [], 'decoded': False}
        for i, prim in enumerate(prims):
            entry['primitives'].append({'index': i, 'material': prim['Material'],
                'mesh': prim.get('Mesh'), 'category': classify_primitive(name, i),
                'start': prim['Start'], 'count': prim['Count'],
                'lod_ranges': [{'start': lod.get('Start', prim['Start']),
                                'count': lod.get('Count', prim['Count'])}
                               for lod in prim.get('LodList', [])],
                'blend_index_range': prim.get('BlendIndexRange'),
                'min': prim.get('Min'), 'max': prim.get('Max')})
        try:
            decoded = decode_bind_model(model, reader)
            entry.update(decoded=True, vertices=len(decoded['positions']),
                         top_lod_triangles=sum(p['Count'] for p in prims) // 3,
                         bound_checks=decoded['bound_checks'],
                         quantization_tolerance_cm=decoded['quantization_tolerance_cm'],
                         pose='validated_authoring_bind_positions_not_live_animation')
            if 'skin' in decoded:
                skin = decoded['skin']
                entry['skin_summary'] = {
                    'weight_words': [int(v) for v in np.unique(decoded['weight_words'])],
                    'palette_indices': [int(v) for v in np.unique(skin['palette_indices'])],
                    'influence_counts': [int(v) for v in np.unique(np.diff(skin['offsets']))],
                    'palette_to_hierarchy_runtime_mapping_verified': False}
            if include_geometry:
                entry['geometry'] = {k: decoded[k].tolist() for k in ('positions', 'indices', 'uv0')}
                if 'skin' in decoded:
                    entry['geometry']['skin'] = {k: v.tolist() for k, v in decoded['skin'].items()}
        except ValueError as exc:
            entry['reason'] = str(exc)
        models[name] = entry
    objects = []
    for name, obj in scene['Object'].items():
        if obj.get('Type') != 'OBJECT':
            continue
        reflection = obj['Target'].endswith(':rimr')
        objects.append({'name': name, 'model': obj['Target'], 'matrix': obj.get('Matrix'),
                        'transform_reference': obj.get('Transform'),
                        'display_in_opaque_geometry_preview': not reflection,
                        'runtime_pose_verified': False,
                        'reason': 'Reflection-only shader has no Default opaque technique; runtime rimpivot matrix unavailable'
                                  if reflection else 'Authoring bind positions use Object.Matrix once; joint deltas are not evaluated'})
    geometry_missing = [r for r in resources if not r['available'] and r['path'].startswith('baskets/Model/')]
    return {'schema': 'revision4_basket_audit_v1', 'models': models, 'objects': objects,
            'resources': resources, 'missing_geometry_resources': geometry_missing,
            'shader_evidence': SHADER_EVIDENCE,
            'main_marker': scene['Object']['MAIN'],
            'cloth_net_geometry_embedded': False,
            'net_evidence': 'MAIN.VC_NetType=CLOTH, netpivot nodes exist; no net Prim/Model in baskets.SCNE',
            'runtime_skin_palette_available': False,
            'all_iff_bytes_unchanged': True,
            'game_runtime_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iff', type=Path, default=ROOT / 'donor/original/arena_020_int_original.iff')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/revision4/basket_audit.json')
    parser.add_argument('--include-geometry', action='store_true')
    args = parser.parse_args()
    before = hashlib.sha256(args.iff.read_bytes()).hexdigest()
    with zipfile.ZipFile(args.iff) as archive:
        report = audit_baskets(archive, include_geometry=args.include_geometry)
    if hashlib.sha256(args.iff.read_bytes()).hexdigest() != before:
        raise RuntimeError('Source archive changed during read-only audit')
    report.update(source=str(args.iff), source_sha256=before)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'decoded_models': sum(m['decoded'] for m in report['models'].values()),
                      'missing_geometry_resources': len(report['missing_geometry_resources'])}))


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    main()
