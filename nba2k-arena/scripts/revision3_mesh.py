"""Revision 3 CLOD mesh export using the donor's actual tangent-frame codec.

Evidence: donor VS.3e4e8775aa14fa50.shader, DXIL VCMain instructions
%105..%110, %214..%294. The shader explicitly decodes:
  bits  0.. 9: octahedral normal x, mapped by 2/1023 - 1
  bits 10..19: octahedral normal y, mapped by 2/1023 - 1
  bits 20..21: reference axis (0=x, 1=y, 2 or 3=z)
  bits 22..29: tangent cosine, mapped by 2/255 - 1
  bit      31: tangent sine sign (set=positive)
  bit      30: tangent handedness (set=+1)

N = normalize(oct_decode(x,y)); A = normalize(cross(N, reference_axis));
B = cross(A,N); T = A*cosine + B*sign*sqrt(saturate(1-cosine*cosine)).
No donor frame sampling, nearest-neighbor lookup, or shader binary editing is
used by this exporter. UV gradients determine tangent direction and handedness.

make_unbaked_material preserves the complete donor Default technique and adds
the donor's existing position-only CSM depth pass to an isolated effect.
It does not alias incompatible GBuffer passes or invent
Object.UserData/lightmap bindings. Runtime scheduling remains game-unverified.
"""
from __future__ import annotations

import copy
import hashlib
import zlib

import numpy as np

TEMPLATE_MATERIAL = 'clutchtime_floor_apron:floor_mat'
TEMPLATE_EFFECT = 'layer_base_CLOD.fx#72407e286031da1b'
DEFAULT_VS = 'VS.3e4e8775aa14fa50.shader'
DEFAULT_PS = 'PS.5e38eeba1e81863d.shader'
UNBAKED_EFFECT = 'venice_v3:unbaked_layer_base_CLOD'


def _unit(values):
    values = np.asarray(values, dtype=np.float64)
    lengths = np.linalg.norm(values, axis=-1, keepdims=True)
    if not np.all(np.isfinite(values)) or np.any(lengths < 1e-12):
        raise ValueError('Expected finite nonzero vectors')
    return values / lengths


def _decode_normal(words):
    words = np.asarray(words, dtype=np.uint32)
    x = (words & 1023).astype(float) * (2 / 1023) - 1
    y = ((words >> 10) & 1023).astype(float) * (2 / 1023) - 1
    z = 1 - np.abs(x) - np.abs(y)
    fold = np.maximum(-z, 0)
    x += np.where(x >= 0, -fold, fold)
    y += np.where(y >= 0, -fold, fold)
    return _unit(np.stack((x, y, z), axis=-1))


def decode_tangent_frames(words):
    """Evaluate the donor VS frame decode; return normal, tangent, handedness."""
    words = np.asarray(words, dtype=np.uint32)
    normals = _decode_normal(words)
    axis = np.eye(3)[np.minimum((words >> 20) & 3, 2)]
    a = _unit(np.cross(normals, axis))
    b = np.cross(a, normals)
    cosine = ((words >> 22) & 255).astype(float) * (2 / 255) - 1
    sine = np.sqrt(np.maximum(0, 1 - cosine * cosine)) * np.where((words >> 31) & 1, 1, -1)
    tangents = a * cosine[..., None] + b * sine[..., None]
    handedness = np.where((words >> 30) & 1, 1, -1)
    return normals, tangents, handedness


def encode_tangent_frames(normals, tangents, handedness):
    """Invert the verified codec, choosing the least-error reference axis."""
    normals = _unit(normals)
    tangents = _unit(tangents)
    if normals.ndim != 2 or normals.shape[1] != 3 or tangents.shape != normals.shape:
        raise ValueError('Normals and tangents must both be N x 3')
    handedness = np.broadcast_to(np.asarray(handedness), (len(normals),))
    if not np.all(np.isin(handedness, (-1, 1))):
        raise ValueError('Handedness must be -1 or +1')
    octahedral = normals / np.abs(normals).sum(axis=-1, keepdims=True)
    x, y = octahedral[:, 0].copy(), octahedral[:, 1].copy()
    lower = octahedral[:, 2] < 0
    octahedral[lower, 0] = (1 - np.abs(y[lower])) * np.where(x[lower] >= 0, 1, -1)
    octahedral[lower, 1] = (1 - np.abs(x[lower])) * np.where(y[lower] >= 0, 1, -1)
    coordinates = np.rint((octahedral[:, :2] + 1) * 511.5).clip(0, 1023).astype(np.uint32)
    base = coordinates[:, 0] | (coordinates[:, 1] << 10)
    decoded_normals = _decode_normal(base)
    # Encode tangent in the plane of the quantized normal actually used by VS.
    tangents = _unit(tangents - decoded_normals * (tangents * decoded_normals).sum(-1, keepdims=True))
    result = np.zeros(len(normals), dtype=np.uint32)
    best_dot = np.full(len(normals), -np.inf)
    for axis_index in range(3):
        a = np.cross(decoded_normals, np.eye(3)[axis_index])
        lengths = np.linalg.norm(a, axis=-1, keepdims=True)
        a /= np.maximum(lengths, 1e-20)
        b = np.cross(a, decoded_normals)
        cosine = (a * tangents).sum(-1)
        sine = (b * tangents).sum(-1)
        packed_cosine = np.rint((cosine + 1) * 127.5).clip(0, 255).astype(np.uint32)
        quantized_cosine = packed_cosine.astype(float) * (2 / 255) - 1
        quantized_sine = np.sqrt(np.maximum(0, 1 - quantized_cosine * quantized_cosine)) * np.where(sine >= 0, 1, -1)
        reconstructed = a * quantized_cosine[:, None] + b * quantized_sine[:, None]
        dot = (reconstructed * tangents).sum(-1)
        use = (lengths[:, 0] > 1e-8) & (dot > best_dot)
        packed = (base | (np.uint32(axis_index) << 20) | (packed_cosine << 22)
                  | ((handedness > 0).astype(np.uint32) << 30) | ((sine >= 0).astype(np.uint32) << 31))
        result[use], best_dot[use] = packed[use], dot[use]
    if not np.all(np.isfinite(best_dot)):
        raise ValueError('Cannot construct a tangent basis')
    return result.astype('<u4')


def make_unbaked_material(level, name, albedo_texture, normal_texture):
    """Add a material using original Default shaders and a verified CSM pass.

    Retains all original Default pass/RootConst/ResourceMapping/Script bindings.
    The original OnlyDepthCSM pass has identical shader and resource bindings to
    Default.DepthOnlyPrepass, with its own original depth state/mask. Other donor
    techniques require baked resources and are not included in this effect.
    No changes are made to original scene effects/materials.
    """
    if name in level['Material']:
        raise ValueError(f'Material already exists: {name}')
    for texture in (albedo_texture, normal_texture):
        if texture not in level['Texture']:
            raise KeyError(f'Texture must be added before its material: {texture}')
    template = level['Material'][TEMPLATE_MATERIAL]
    if template['Effect'] != TEMPLATE_EFFECT:
        raise ValueError('Unexpected donor apron effect')
    source_effect = level['Effect'][TEMPLATE_EFFECT]
    default = source_effect['Technique']['Default']
    color_pass = default['Pass']['Default']
    if color_pass['VS']['Binary'] != DEFAULT_VS or color_pass['PS']['Binary'] != DEFAULT_PS:
        raise ValueError('Unexpected donor Default shaders; re-audit the codec first')
    required_uvs = {'TEXCOORD0', 'TEXCOORD1', 'TEXCOORD2'}
    if not required_uvs <= set(color_pass['VS']['Input']):
        raise ValueError('Unexpected Default shader inputs')
    for rendering_pass in default['Pass'].values():
        if 'TEXCOORD7' in rendering_pass.get('VS', {}).get('Input', {}):
            raise ValueError('Default path unexpectedly requires baked UV7')
    effect = copy.deepcopy(source_effect)
    effect['Technique'] = {'Default': copy.deepcopy(default)}
    caster = source_effect['Technique']['HiresLightmap']['Pass']['OnlyDepthCSM']
    depth = default['Pass']['DepthOnlyPrepass']
    for binding in ('VS', 'PS', 'ResourceMapping'):
        if caster[binding] != depth[binding]:
            raise ValueError('CSM pass is not binding-compatible with the verified position-only path')
    effect['Technique']['Default']['Pass']['OnlyDepthCSM'] = copy.deepcopy(caster)
    if UNBAKED_EFFECT in level['Effect'] and level['Effect'][UNBAKED_EFFECT] != effect:
        raise ValueError('Conflicting unbaked effect')
    level['Effect'][UNBAKED_EFFECT] = effect
    material = copy.deepcopy(template)
    material['Effect'] = UNBAKED_EFFECT
    material['Technique'] = {'Default': copy.deepcopy(template['Technique']['Default'])}
    material['Technique']['Default']['Pass']['OnlyDepthCSM'] = copy.deepcopy(template['Technique']['HiresLightmap']['Pass']['OnlyDepthCSM'])
    material['Resource']['AlbedoMap']['Pixelmap'] = albedo_texture
    material['Resource']['NormalAndRoughMap']['Pixelmap'] = normal_texture
    material['Parameter']['AlbedoModulate'] = [1., 1., 1., 1.]
    material['Parameter']['NormalHeight'] = 0.
    level['Material'][name] = material
    return {'material': name, 'effect': UNBAKED_EFFECT, 'techniques': ['Default'],
            'default_vs': DEFAULT_VS, 'default_ps': DEFAULT_PS,
            'additional_position_only_shadow_pass': 'OnlyDepthCSM',
            'shader_binaries_modified': False, 'lightmap_uv7_required': False,
            'runtime_render_dispatch_verified': False}


def planar_triangle_uvs(triangles):
    """Local nondegenerate UVs for solid-color or per-face repeating surfaces."""
    triangles = np.asarray(triangles, dtype=float)
    e1, e2 = triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    normal = _unit(np.cross(e1, e2))
    tangent = _unit(e1)
    bitangent = np.cross(normal, tangent)
    uv = np.zeros((len(triangles), 3, 2))
    uv[:, 1, 0] = np.linalg.norm(e1, axis=1)
    uv[:, 2, 0] = (e2 * tangent).sum(-1)
    uv[:, 2, 1] = (e2 * bitangent).sum(-1)
    uv -= uv.min(axis=1, keepdims=True)
    uv /= np.maximum(uv.max(axis=(1, 2), keepdims=True), 1e-12)
    return uv


def _triangle_basis(triangles, uvs, normals):
    e1, e2 = triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    du1, du2 = uvs[:, 1] - uvs[:, 0], uvs[:, 2] - uvs[:, 0]
    determinant = du1[:, 0] * du2[:, 1] - du1[:, 1] * du2[:, 0]
    if np.any(np.abs(determinant) < 1e-12):
        raise ValueError('Degenerate UV triangle: provide a valid mapping')
    tangent = (e1 * du2[:, 1, None] - e2 * du1[:, 1, None]) / determinant[:, None]
    bitangent = (e2 * du1[:, 0, None] - e1 * du2[:, 0, None]) / determinant[:, None]
    tangent = np.repeat(tangent, 3, axis=0)
    bitangent = np.repeat(bitangent, 3, axis=0)
    tangent = _unit(tangent - normals * (normals * tangent).sum(-1, keepdims=True))
    handedness = np.where((np.cross(normals, tangent) * bitangent).sum(-1) >= 0, 1, -1)
    return tangent, handedness


def export_mesh(level, extra, name, parts, *, uv_parts=None, normal_parts=None):
    """Append one CLOD model and binary resources; objects are caller-owned.

    parts maps material names to T x 3 x 3 triangle arrays. Optional uv_parts
    maps the same names to T x 3 x 2 arrays, and normal_parts to T x 3 x 3.
    Every vertex is explicit; maximum 65,535 vertices per model. Returns bounds,
    counts and measured codec/quantization errors for inclusion in build audit.
    """
    if name in level['Model']:
        raise ValueError(f'Model already exists: {name}')
    triangles, texture_coordinates, vertex_normals, specifications = [], [], [], []
    cursor = 0
    for material, values in parts.items():
        if material not in level['Material']:
            raise KeyError(f'Missing material: {material}')
        faces = np.asarray(values, dtype=np.float64)
        if faces.size == 0:
            continue
        if faces.ndim != 3 or faces.shape[1:] != (3, 3) or not np.all(np.isfinite(faces)):
            raise ValueError('Triangles must be finite T x 3 x 3 arrays')
        face_normals = _unit(np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0]))
        uv = planar_triangle_uvs(faces) if uv_parts is None or material not in uv_parts else np.asarray(uv_parts[material], dtype=float)
        if uv.shape != (len(faces), 3, 2) or not np.all(np.isfinite(uv)):
            raise ValueError('UVs must be finite T x 3 x 2 arrays')
        if normal_parts is None or material not in normal_parts:
            normals = np.repeat(face_normals, 3, axis=0)
        else:
            normals = np.asarray(normal_parts[material], dtype=float)
            if normals.shape != faces.shape:
                raise ValueError('Vertex normals must match triangle shape')
            normals = _unit(normals.reshape(-1, 3))
        count = len(faces) * 3
        specifications.append((material, cursor, count))
        cursor += count
        triangles.append(faces)
        texture_coordinates.append(uv)
        vertex_normals.append(normals)
    if not triangles or cursor >= 65536:
        raise ValueError('Model must contain 1..65,535 explicit vertices')
    faces = np.concatenate(triangles)
    positions = faces.reshape(-1, 3)
    uvs = np.concatenate(texture_coordinates)
    normals = np.concatenate(vertex_normals)
    # Packed SNORM UVs receive the same Offset/Scale used in the donor layout.
    flat_uv = uvs.reshape(-1, 2)
    uv_offset = (flat_uv.min(0) + flat_uv.max(0)) / 2
    uv_scale = (flat_uv.max(0) - flat_uv.min(0)) / 2
    uv_scale = np.maximum(uv_scale, 1e-9)
    packed_uv = np.rint((flat_uv - uv_offset) / uv_scale * 32767).clip(-32767, 32767).astype('<i2')
    decoded_uv = packed_uv.astype(float) / 32767 * uv_scale + uv_offset
    # Derive frames from the quantized UV gradient consumed by the actual VS.
    tangents, handedness = _triangle_basis(faces, decoded_uv.reshape(-1, 3, 2), normals)
    frames = encode_tangent_frames(normals, tangents, handedness)
    decoded_normal, decoded_tangent, decoded_hand = decode_tangent_frames(frames)
    lo, hi = positions.min(0), positions.max(0)
    center = (lo + hi) / 2
    span = float((hi - lo).max())
    offset = center - span / 2
    quantized_xyz = np.rint((positions - offset) / span * 65535).clip(0, 65535).astype('<u2')
    packed_positions = np.column_stack((quantized_xyz, np.full(cursor, 65535, dtype='<u2'))).astype('<u2')
    attributes = np.zeros((cursor, 20), dtype=np.uint8)
    attributes[:, :4] = frames.view(np.uint8).reshape(cursor, 4)
    attributes[:, 4:8] = packed_uv.view(np.uint8).reshape(cursor, 4)
    attributes[:, 8:12] = packed_uv.view(np.uint8).reshape(cursor, 4)
    buffers = [packed_positions.tobytes(), packed_uv.tobytes(), attributes.tobytes()]
    indices = np.arange(cursor, dtype='<u2').tobytes()

    def resource(prefix, raw):
        binary = f'{prefix}.{hashlib.sha256(raw).hexdigest()[:16]}.bin'
        if binary in extra and extra[binary] != raw:
            raise ValueError('Resource hash collision')
        extra[binary] = raw
        return binary

    template = next(m for n, m in level['Model'].items() if 'floor_apron:' in n)
    vf = copy.deepcopy(template['VertexFormat'])
    vf['POSITION0']['Offset'], vf['POSITION0']['Scale'] = offset.tolist() + [0.], [span] * 3 + [1.]
    for key, spec in vf.items():
        if key.startswith('TEXCOORD'):
            spec['Offset'], spec['Scale'] = [0.] * 4, [1.] * 4
            if key in ('TEXCOORD0', 'TEXCOORD1', 'TEXCOORD2'):
                spec['Offset'], spec['Scale'] = uv_offset.tolist() + [0., 0.], uv_scale.tolist() + [1., 1.]
    radius = float(np.linalg.norm(positions - center, axis=1).max())
    prims = []
    for index, (material, start, count) in enumerate(specifications):
        section = positions[start:start + count]
        prims.append({'Material': material, 'Mesh': f'{name}_part_{index}', 'Type': 'TRIANGLE_LIST',
                      'BlendIndexRange': [0, 0], 'Start': start, 'Count': count,
                      'Radius': radius, 'Center': center.tolist(), 'Min': section.min(0).tolist(), 'Max': section.max(0).tolist(),
                      'LodList': [{'Start': start, 'Count': count}]})
    model = {'Clod': {'DataBuildMode': '2K21_FAST', 'Flag_ContinuousIndexBuffers': 1,
                       'Lods': {'Lod0': {'NumMaskBits': 0, 'NumVertices': cursor, 'NumIndices': cursor, 'NumTris': cursor // 3}}},
             'Radius': radius, 'Center': center.tolist(), 'Min': lo.tolist(), 'Max': hi.tolist(),
             'BlendIndexOffset': 1, 'BlendIndexRange': [0, 0], 'Transform': {name: None},
             'Prim': prims, 'VertexFormat': vf,
             'IndexBuffer': {'Format': 'R16_UINT', 'Size': len(indices), 'Binary': resource('IndexBuffer', indices)},
             'IndexBufferCrc32': zlib.crc32(indices),
             'VertexStream': [{'Stride': stride, 'Size': len(raw), 'Binary': resource('VertexBuffer', raw)}
                              for stride, raw in zip((8, 4, 20), buffers)]}
    level['Model'][name] = model
    angle = lambda a, b: np.degrees(np.arccos(np.clip((a * b).sum(-1), -1, 1)))
    return {'model': name, 'vertices': cursor, 'triangles': cursor // 3, 'parts': len(prims),
            'bounds_min': lo.tolist(), 'bounds_max': hi.tolist(),
            'max_normal_error_degrees': float(angle(normals, decoded_normal).max()),
            'max_tangent_error_degrees': float(angle(tangents, decoded_tangent).max()),
            'handedness_mismatches': int(np.count_nonzero(decoded_hand != handedness)),
            'max_position_error': float(np.abs(quantized_xyz.astype(float) / 65535 * span + offset - positions).max()),
            'max_uv_error': float(np.abs(decoded_uv - flat_uv).max()),
            'codec': 'donor_DXIL_octahedral10x2_axis2_cos8_sign1_hand1',
            'donor_frame_samples_used': 0, 'game_render_verified': False}
