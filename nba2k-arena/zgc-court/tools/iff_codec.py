"""Native NBA 2K26 static SCNE geometry codecs.

No game files are read by this module. Normals occupy the low 20 bits of
TANGENTFRAME0 (octahedral UNORM10); the upper 12 bits are opaque here.
For new isotropic meshes we use a native upper-bit value with neutral normal
maps. This is NOT an implementation of arbitrary tangent-space normal maps.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import PurePosixPath
import zlib

import numpy as np

IDENTITY = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]
NATIVE_FRAME_UPPER = np.uint32(0xDFE00000)


def load_scne(raw):
    text = raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw
    def unique_object(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate SCNE key requires a lossless parser: '+key)
            result[key]=value
        return result
    return json.loads(text if text.lstrip().startswith('{') else '{' + text + '}',object_pairs_hook=unique_object)


def dump_scne(document):
    """2K resource is a JSON member fragment, not a complete JSON document."""
    return json.dumps(document, ensure_ascii=False,allow_nan=False, separators=(',', ':'))[1:-1].encode('utf-8')


def resolve_binary(archive, name):
    if name in archive.NameToInfo:
        return name
    alternate = str(PurePosixPath(name).with_suffix('.bin'))
    if name.endswith('.gz') and alternate in archive.NameToInfo:
        return alternate
    raise KeyError(name)


def unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-15)


def decode_normals(packed):
    packed = np.asarray(packed, dtype=np.uint32)
    xy = np.stack((packed & 1023, (packed >> 10) & 1023), axis=-1).astype(float) / 1023. * 2. - 1.
    normal = np.concatenate((xy, (1. - np.abs(xy).sum(axis=-1))[..., None]), axis=-1)
    fold = np.maximum(-normal[..., 2], 0.)
    normal[..., :2] += np.where(normal[..., :2] >= 0, -fold[..., None], fold[..., None])
    return unit(normal)


def encode_normals(normals, upper_bits=NATIVE_FRAME_UPPER):
    n = unit(normals)
    if np.any(np.linalg.norm(n, axis=-1) < .9) or not np.isfinite(n).all():
        raise ValueError('Normals must be finite and nonzero')
    projected = n / np.abs(n).sum(axis=-1, keepdims=True)
    xy = projected[..., :2]
    folded = (1. - np.abs(xy[..., ::-1])) * np.where(xy >= 0, 1., -1.)
    xy = np.where((projected[..., 2] < 0)[..., None], folded, xy)
    q = np.clip(np.rint((xy * .5 + .5) * 1023.), 0, 1023).astype('<u4')
    return (np.asarray(upper_bits, dtype='<u4') & np.uint32(0xFFF00000)) | q[..., 0] | (q[..., 1] << 10)


def decode_attribute(archive, model, semantic):
    spec = model['VertexFormat'][semantic]
    stream = model['VertexStream'][spec.get('Stream', 0)]
    raw = archive.read(resolve_binary(archive, stream['Binary']))
    count = len(raw) // stream['Stride']
    byte_offset = spec.get('ByteOffset', 0)
    fmt = spec['Format']
    types = {'R16G16B16A16_UNORM': ('<u2', 4), 'R16G16_SNORM': ('<i2', 2),
             'R10G10B10A2_UINT': ('<u4', 1), 'R32G32B32_FLOAT': ('<f4', 3)}
    dtype, components = types[fmt]
    data = np.ndarray((count, components), dtype, raw, offset=byte_offset,
                      strides=(stream['Stride'], np.dtype(dtype).itemsize)).copy()
    if fmt == 'R10G10B10A2_UINT':
        return data[:, 0]
    if fmt.endswith('UNORM'):
        data = data.astype(float) / 65535.
    elif fmt.endswith('SNORM'):
        data = np.maximum(data.astype(float) / 32767., -1.)
    return data * np.asarray(spec.get('Scale', [1.] * components))[:components] + np.asarray(spec.get('Offset', [0.] * components))[:components]


def encode_positions(positions):
    p = np.asarray(positions, dtype=float)
    if p.ndim != 2 or p.shape[1] != 3 or not len(p) or not np.isfinite(p).all():
        raise ValueError('Expected nonempty finite Nx3 positions')
    center = (p.max(0) + p.min(0)) / 2
    span = max(float(np.ptp(p, axis=0).max()), 1e-3)
    offset = center - span / 2
    # A flat ground at Y=0 must remain exactly at Y=0. With the symmetric
    # offset, UNORM16 has no exact midpoint and raised the R07 plane by 0.28 mm.
    # Native per-axis offsets allow constant axes to use q=0 without changing
    # the precision or encoding of either varying axis.
    flat = np.ptp(p, axis=0) == 0
    offset[flat] = p[0, flat]
    quant = np.clip(np.rint((p - offset) / span * 65535), 0, 65535).astype('<u2')
    quant = np.column_stack((quant, np.full(len(p), 65535, dtype='<u2')))
    return quant.tobytes(), {'Format': 'R16G16B16A16_UNORM', 'Offset': offset.tolist() + [0.], 'Scale': [span, span, span, 1.]}


def encode_uv(uv):
    uv = np.asarray(uv, dtype=float)
    if uv.ndim != 2 or uv.shape[1] != 2 or not np.isfinite(uv).all():
        raise ValueError('Expected finite Nx2 UVs')
    offset = (uv.max(0) + uv.min(0)) / 2
    scale = np.maximum(np.ptp(uv, axis=0) / 2, 1e-8)
    q = np.clip(np.rint((uv - offset) / scale * 32767), -32767, 32767).astype('<i2')
    return q.tobytes(), {'Format': 'R16G16_SNORM', 'Offset': offset.tolist() + [0., 0.], 'Scale': scale.tolist() + [1., 1.]}


def texture_density(p, uv, triangles):
    """Conservative UV units per world unit, for native texture streaming hints."""
    if len(triangles) == 0:
        return [1e-5, 1e-5]
    t = np.asarray(triangles)
    e1, e2 = p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]]
    c = np.cross(e1, e2)
    area = np.einsum('ij,ij->i', c, c)
    good = area > 1e-12
    if not good.any():
        return [1e-5, 1e-5]
    d1, d2 = uv[t[:, 1]] - uv[t[:, 0]], uv[t[:, 2]] - uv[t[:, 0]]
    gradients = (np.cross(e2, c)[:, :, None] * d1[:, None, :] + np.cross(c, e1)[:, :, None] * d2[:, None, :]) / np.maximum(area[:, None, None], 1e-12)
    norms = np.linalg.norm(gradients[good], axis=1)
    return np.maximum(np.quantile(norms, .75, axis=0), 1e-7).tolist()


def make_static_model(name, positions, normals, uv, indices, material_name, extra, uv_lightmap=None):
    """Build a 2K26_FAST, single-material single-LOD native static mesh.

    positions/normals are already transformed to GAME coordinates (cm, Y-up).
    UV is the desired native texture UV; this function performs no V flip.
    Caller splits meshes below 65536 vertices and supplies neutral normal maps.
    extra receives the four real native IndexBuffer/VertexBuffer byte payloads.
    """
    p = np.asarray(positions, dtype=float)
    n = unit(normals)
    uv = np.asarray(uv, dtype=float)
    ix = np.asarray(indices, dtype=np.int64).reshape(-1)
    if not (0 < len(p) < 65536 and len(n) == len(p) == len(uv)):
        raise ValueError('Mesh size/attribute mismatch or R16 vertex overflow')
    if len(ix) % 3 or ix.min() < 0 or ix.max() >= len(p):
        raise ValueError('Invalid triangle-list indices')
    pb, ps = encode_positions(p)
    ub, us = encode_uv(uv)
    # The dynamic/deferred outdoor material will use no baked lightmap; valid
    # secondary coordinate streams must still be supplied for its native VS.
    lm = uv if uv_lightmap is None else np.asarray(uv_lightmap, dtype=float)
    lb, ls = encode_uv(lm)
    packed = encode_normals(n)
    attrs = np.zeros((len(p), 12), dtype=np.uint8)
    attrs[:, :4] = packed.view(np.uint8).reshape(-1, 4)
    attrs[:, 4:8] = np.frombuffer(ub, np.uint8).reshape(-1, 4)
    attrs[:, 8:12] = np.frombuffer(lb, np.uint8).reshape(-1, 4)
    ib = ix.astype('<u2').tobytes()
    def resource(prefix, raw):
        key = f'{prefix}.{hashlib.sha256(raw).hexdigest()[:16]}.bin'
        if key in extra and extra[key] != raw:
            raise ValueError('Resource hash collision')
        extra[key] = raw
        return key
    low, high = p.min(0), p.max(0)
    center = (low + high) / 2
    bounds = {'Min': low.tolist(), 'Max': high.tolist(), 'Center': center.tolist(), 'Radius': float(np.linalg.norm(p - center, axis=1).max())}
    density = texture_density(p, uv, ix.reshape(-1, 3))
    duv = {f'Duv{j}': density.copy() for j in (0, 1, 2, 7)}
    prim = {'Material': material_name, 'Mesh': name + ':mesh', 'Type': 'TRIANGLE_LIST',
            'BlendIndexRange': [0, 0], 'Start': 0, 'Count': len(ix),
            'LodList': [{'Start': 0, 'Count': len(ix)}], **bounds, **duv}
    vf = {'POSITION0': ps, 'TANGENTFRAME0': {'Format': 'R10G10B10A2_UINT', 'Stream': 2},
          'TEXCOORD0': {**us, 'Stream': 1}, 'TEXCOORD2': {**us, 'Stream': 2, 'ByteOffset': 4},
          'TEXCOORD7': {**ls, 'Stream': 2, 'ByteOffset': 8}}
    model = {'Clod': {'DataBuildMode': '2K26_FAST', 'Flag_ContinuousIndexBuffers': 1,
                     'Lods': {'Lod0': {'NumMaskBits': 0, 'NumVertices': len(p), 'NumIndices': len(ix), 'NumTris': len(ix) // 3}}},
             **bounds, **duv, 'BlendIndexOffset': 1, 'BlendIndexRange': [0, 0],
             'Transform': {name: None}, 'Prim': [prim], 'VertexFormat': vf,
             'IndexBuffer': {'Format': 'R16_UINT', 'Size': len(ib), 'Binary': resource('IndexBuffer', ib)},
             'IndexBufferCrc32': zlib.crc32(ib), 'VertexStream': []}
    for stride, raw in ((8, pb), (4, ub), (12, attrs.tobytes())):
        model['VertexStream'].append({'Stride': stride, 'Size': len(raw), 'Binary': resource('VertexBuffer', raw)})
    obj = {'Type': 'OBJECT', 'Target': name, 'Transform': name, 'Matrix': IDENTITY.copy()}
    return model, obj


def new_material(level, template_name, albedo_key, normal_key, *, color=(1, 1, 1, 1)):
    """Clone a compatible native shader and script without inventing bindings."""
    mat = copy.deepcopy(level['Material'][template_name])
    mat['Resource']['AlbedoMap'] = {'Pixelmap': albedo_key}
    mat['Resource']['NormalAndRoughMap'] = {'Pixelmap': normal_key}
    mat.setdefault('Parameter', {}).update({'AlbedoModulate': list(color), 'NormalHeight': 0., 'AlphaStyle': 'OPAQUE'})
    return mat


def hide_native_basket_visuals(baskets, archive, extra, keep_rim=True):
    """Return a copy with support/backboard/glass triangles degenerated.

    Does not remove any model, object, transform, material, marker, skin weight,
    original LOD range, or physics/gameplay metadata. Draw ranges remain valid.
    Real rim and its special reflection are kept by default. The caller must
    omit duplicate static rim/net geometry from the custom scene.
    """
    result = copy.deepcopy(baskets)
    report = []
    for name, model in result.get('Model', {}).items():
        if name.endswith(':rimr') and keep_rim:
            continue
        if not (name.endswith(':basket') or name.endswith(':glass') or name.endswith(':rimr')):
            raise ValueError('Unexpected basket model, refusing guessed hiding: ' + name)
        source_name = model['IndexBuffer']['Binary']
        raw = archive.read(resolve_binary(archive, source_name))
        if model['IndexBuffer']['Format'] != 'R16_UINT':
            raise ValueError('Unexpected native basket index format')
        original = np.frombuffer(raw, '<u2')
        patched = original.copy()
        hidden = []
        preserved = []
        for prim in model.get('Prim', []):
            ranges = prim.get('LodList') or [{'Start': prim.get('Start', 0), 'Count': prim.get('Count', 0)}]
            if keep_rim and prim.get('Mesh') == 'basket_rimShape':
                preserved.extend((r['Start'], r['Count']) for r in ranges)
                continue
            for r in ranges:
                start, count = r['Start'], r['Count']
                if start < 0 or count % 3 or start + count > len(patched):
                    raise ValueError('Invalid native primitive range')
                # 0 is an existing valid vertex; equal corners have zero area.
                patched[start:start + count] = 0
            hidden.append(prim.get('Mesh', 'unnamed'))
        for start, count in preserved:
            if not np.array_equal(patched[start:start + count], original[start:start + count]):
                raise ValueError('Hidden geometry overlaps the real rim indices')
        payload = patched.astype('<u2').tobytes()
        key = 'IndexBuffer.' + hashlib.sha256(payload).hexdigest()[:16] + '.bin'
        extra[key] = payload
        model['IndexBuffer'] = {'Format': 'R16_UINT', 'Size': len(payload), 'Binary': key}
        model['IndexBufferCrc32'] = zlib.crc32(payload)
        report.append({'model': name, 'original_binary': source_name, 'replacement_binary': key,
                       'hidden_primitive_meshes': hidden, 'rim_index_ranges_preserved': len(preserved),
                       'changed_indices': int(np.count_nonzero(patched != original)), 'index_count_preserved': len(patched)})
    if result.get('Object') != baskets.get('Object'):
        raise AssertionError('Basket objects and MAIN must remain byte-equivalent JSON values')
    for name, model in result.get('Model', {}).items():
        for key in ('Transform', 'VertexFormat', 'VertexStream', 'Prim', 'Clod'):
            if model.get(key) != baskets['Model'][name].get(key):
                raise AssertionError('Unexpected change to basket ' + key)
    return result, report
