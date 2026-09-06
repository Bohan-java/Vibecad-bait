"""NBA court markings in donor coordinates, with interpolated floor lightmap UVs.

The official diagram measures court inside edges and lane / three-point outside
edges. Geometry below respects those edge conventions; all ordinary painted
bands are two inches wide. This changes visible geometry, not 2K scoring logic.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import struct
import zlib

import numpy as np

from scene_primitives import iter_primitives

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'handoff/cache/VertexBuffer.0f3b6fcaf86b59a6.decoded.bin'
CACHE_SHA = '6aed1f28fdd729b52c415ba2a07245395299d0095fe7ba4b5c31216c7555af54'
RULE_URL = 'https://official.nba.com/rule-no-1-court-dimensions-equipment/'
DIAGRAM_URL = 'https://cdn.nba.com/manage/2026/01/Official-2025-26-NBA-Playing-Rules.pdf#page=8'
INCH, FOOT = 2.54, 30.48
WIDTH = 2 * INCH
HALF_WIDTH, HALF_LENGTH = 25 * FOOT, 47 * FOOT
RIM_FROM_BASELINE = 5.25 * FOOT
BACKBOARD_FROM_BASELINE = 4 * FOOT
LANE_HALF_OUTSIDE = 8 * FOOT
FREE_THROW_OUTSIDE = 19 * FOOT
FREE_THROW_CENTER = FREE_THROW_OUTSIDE - WIDTH / 2
THREE_OUTSIDE, CORNER_OUTSIDE = 23.75 * FOOT, 22 * FOOT
WHITE_MATERIAL = 'venice_v3:court_white_lines'
MARK_MATERIAL = 'venice_v3:court_lane_space_marks'


def _fragment(raw):
    raw = raw.strip()
    return json.loads(raw if raw.startswith(b'{') else b'{' + raw + b'}')


def _upward(triangles):
    array = np.asarray(triangles, dtype=float).reshape(-1, 3, 3)
    cross = np.cross(array[:, 1] - array[:, 0], array[:, 2] - array[:, 0])[:, 1]
    if np.any(np.abs(cross) < 1e-9):
        raise ValueError('Degenerate court marking triangle')
    reverse = cross < 0
    array[reverse] = array[reverse][:, [0, 2, 1]]
    return array


def court_geometry():
    """Return (JSON feature records, matching world-coordinate triangle arrays)."""
    features, geometry = [], []

    def add(name, triangles, **spec):
        tri = _upward(triangles)
        features.append({'name': name, 'line_width_cm': WIDTH,
                         'material': WHITE_MATERIAL, **spec,
                         'triangles': len(tri), 'min': tri.min((0, 1)).tolist(),
                         'max': tri.max((0, 1)).tolist()})
        geometry.append(tri)

    def quad(name, points, side=None, **spec):
        # Local coordinates at either end are x and distance inward from baseline.
        p = np.asarray(points, float)
        xyz = np.column_stack((p[:, 0], np.zeros(len(p)), p[:, 1]))
        if side is not None:
            xyz[:, 2] = side * (HALF_LENGTH - xyz[:, 2])
        add(name, [xyz[[0, 1, 2]], xyz[[0, 2, 3]]], **spec)

    def rectangle(name, x0, x1, d0, d1, side=None, **spec):
        quad(name, [(x0, d0), (x1, d0), (x1, d1), (x0, d1)], side,
             kind='rectangle', **spec)

    def arc(name, center, inner, outer, a0, a1, side=None, **spec):
        # <=0.5 degree segments bound maximum chord deviation to 0.007 cm
        # for the largest circle. Each vertex lies exactly on an edge radius.
        steps = max(1, math.ceil((a1 - a0) / math.radians(.5)))
        angle = np.linspace(a0, a1, steps + 1)
        outer_points = np.array(center) + outer * np.column_stack((np.cos(angle), np.sin(angle)))
        inner_points = np.array(center) + inner * np.column_stack((np.cos(angle), np.sin(angle)))
        xyz = lambda p: np.column_stack((p[:, 0], np.zeros(len(p)),
                                         p[:, 1] if side is None else side * (HALF_LENGTH - p[:, 1])))
        a, b = xyz(outer_points), xyz(inner_points)
        tri = np.concatenate((np.stack((a[:-1], b[:-1], b[1:]), 1),
                              np.stack((a[:-1], b[1:], a[1:]), 1)))
        add(name, tri, kind='arc', center_local_cm=list(center), inner_radius_cm=inner,
            outer_radius_cm=outer, angle_radians=[a0, a1], end=side, **spec)

    # Boundary inside edges are exactly 50 x 94 feet.
    for side in (-1, 1):
        x0, x1 = sorted((side * HALF_WIDTH, side * (HALF_WIDTH + WIDTH)))
        rectangle(f'boundary_sideline_{side}', x0, x1, -HALF_LENGTH, HALF_LENGTH)
        rectangle(f'boundary_baseline_{side}', -HALF_WIDTH - WIDTH, HALF_WIDTH + WIDTH,
                  0, -WIDTH, side=side)
    rectangle('division_line', -HALF_WIDTH, HALF_WIDTH, -WIDTH / 2, WIDTH / 2)
    arc('center_outer_circle', (0, 0), 6 * FOOT - WIDTH, 6 * FOOT, 0, math.tau)
    arc('center_inner_circle', (0, 0), 2 * FOOT, 2 * FOOT + WIDTH, 0, math.tau)

    for end in (-1, 1):
        prefix = f'end_{end}'
        for side in (-1, 1):
            x0, x1 = sorted((side * (LANE_HALF_OUTSIDE - WIDTH), side * LANE_HALF_OUTSIDE))
            rectangle(f'{prefix}_lane_side_{side}', x0, x1, 0, FREE_THROW_OUTSIDE, side=end)
        rectangle(f'{prefix}_free_throw_line', -LANE_HALF_OUTSIDE, LANE_HALF_OUTSIDE,
                  FREE_THROW_OUTSIDE - WIDTH, FREE_THROW_OUTSIDE, side=end)
        arc(f'{prefix}_free_throw_front', (0, FREE_THROW_CENTER), 6 * FOOT - WIDTH,
            6 * FOOT, 0, math.pi, side=end)
        for dash in range(6):
            a0 = math.pi + math.radians(dash * 30 + 5)
            arc(f'{prefix}_free_throw_dash_{dash}', (0, FREE_THROW_CENTER), 6 * FOOT - WIDTH,
                6 * FOOT, a0, a0 + math.radians(20), side=end, dashed=True)

        # Three-point ring edges meet the two straight edges without a gap:
        # distinct inner/outer endpoint angles keep their x coordinates exact.
        outer, inner = THREE_OUTSIDE, THREE_OUTSIDE - WIDTH
        x_outer, x_inner = CORNER_OUTSIDE, CORNER_OUTSIDE - WIDTH
        ao, ai = math.acos(x_outer / outer), math.acos(x_inner / inner)
        t = np.linspace(0, 1, 361)
        angles_o = ao + t * (math.pi - 2 * ao)
        angles_i = ai + t * (math.pi - 2 * ai)
        op = np.column_stack((outer * np.cos(angles_o), RIM_FROM_BASELINE + outer * np.sin(angles_o)))
        ip = np.column_stack((inner * np.cos(angles_i), RIM_FROM_BASELINE + inner * np.sin(angles_i)))
        xyz = lambda p: np.column_stack((p[:, 0], np.zeros(len(p)), end * (HALF_LENGTH - p[:, 1])))
        a, b = xyz(op), xyz(ip)
        triangles = np.concatenate((np.stack((a[:-1], b[:-1], b[1:]), 1),
                                    np.stack((a[:-1], b[1:], a[1:]), 1)))
        add(f'{prefix}_three_point_arc', triangles, kind='three_point_arc', end=end,
            center_local_cm=[0, RIM_FROM_BASELINE], inner_radius_cm=inner, outer_radius_cm=outer,
            corner_outer_cm=x_outer, corner_inner_cm=x_inner)
        for side, idx in ((1, 0), (-1, -1)):
            quad(f'{prefix}_three_point_corner_{side}',
                 [(side * x_inner, 0), (side * x_outer, 0), op[idx], ip[idx]], end,
                 kind='corner_three', outside_distance_cm=CORNER_OUTSIDE)

        arc(f'{prefix}_restricted_arc', (0, RIM_FROM_BASELINE), 4 * FOOT,
            4 * FOOT + WIDTH, 0, math.pi, side=end)
        for side in (-1, 1):
            x0, x1 = sorted((side * 4 * FOOT, side * (4 * FOOT + WIDTH)))
            rectangle(f'{prefix}_restricted_leg_{side}', x0, x1,
                      BACKBOARD_FROM_BASELINE, RIM_FROM_BASELINE, side=end)

        # Official 28-foot sideline hashes, 3 feet inward.
        for side in (-1, 1):
            x0, x1 = sorted((side * HALF_WIDTH, side * (HALF_WIDTH - 3 * FOOT)))
            rectangle(f'{prefix}_sideline_28ft_{side}', x0, x1,
                      28 * FOOT, 28 * FOOT + WIDTH, side=end)
            # Six-inch baseline ticks, three feet outside the lane's outer edge.
            x0 = side * (LANE_HALF_OUTSIDE + 3 * FOOT)
            rectangle(f'{prefix}_baseline_tick_{side}', min(x0, x0 + side * WIDTH),
                      max(x0, x0 + side * WIDTH), 0, 6 * INCH, side=end)
            # Six-inch horizontal lower-defensive-box marks, 13 feet from endline.
            xa = side * (LANE_HALF_OUTSIDE + 3 * FOOT)
            xb = xa + side * 6 * INCH
            rectangle(f'{prefix}_defensive_box_{side}', min(xa, xb), max(xa, xb),
                      13 * FOOT, 13 * FOOT + WIDTH, side=end)
            # Lane space marks: 2 x 6 inches, outside the 16-foot lane. The
            # one-foot neutral block is the documented exception to 2-inch width.
            for number, distance in enumerate((4 * FOOT, 8 * FOOT, 11 * FOOT, 14 * FOOT)):
                xa, xb = sorted((side * LANE_HALF_OUTSIDE,
                                 side * (LANE_HALF_OUTSIDE + 6 * INCH)))
                rectangle(f'{prefix}_lane_space_{side}_{number}', xa, xb, distance,
                          distance + WIDTH, side=end, material=MARK_MATERIAL)
            xa, xb = sorted((side * LANE_HALF_OUTSIDE,
                             side * (LANE_HALF_OUTSIDE + 6 * INCH)))
            rectangle(f'{prefix}_neutral_zone_{side}', xa, xb, 7 * FOOT, 8 * FOOT,
                      side=end, material=MARK_MATERIAL, line_width_cm=FOOT,
                      neutral_zone_exception=True)
    # One scorer-table-side substitution box. Donor benches are on +X side.
    for side in (-1, 1):
        z0, z1 = sorted((side * 4 * FOOT, side * (4 * FOOT + WIDTH)))
        rectangle(f'substitution_box_{side}', HALF_WIDTH, HALF_WIDTH + 3 * FOOT, z0, z1)
    return features, geometry


def _verify_donor_units(archive):
    baskets = _fragment(archive.read('baskets.SCNE'))['baskets']
    objects = baskets['Object']
    assemblies = [(name, obj) for name, obj in objects.items() if name.endswith(':basket')]
    if len(assemblies) != 2:
        raise ValueError('Expected the two unchanged donor basket assemblies')
    positions = sorted(float(obj['Matrix'][14]) for _, obj in assemblies)
    if not np.allclose(positions, [-43 * FOOT, 43 * FOOT], atol=.001):
        raise ValueError('Donor basket positions do not match cm-scaled NBA court')
    model = baskets['Model'][assemblies[0][1]['Target']]
    translations = [v.get('Translate', [0, 0, 0]) for v in model['Transform'].values() if v]
    net_offset = np.sum(translations, axis=0)
    if not math.isclose(float(net_offset[2]), 15 * INCH, abs_tol=.001):
        raise ValueError('Donor net pivot does not confirm the basket center offset')
    return {'scene_units_per_inch': INCH, 'backboard_anchor_z_cm': positions,
            'net_pivot_forward_cm': float(net_offset[2]),
            'rim_center_z_cm': [-HALF_LENGTH + RIM_FROM_BASELINE, HALF_LENGTH - RIM_FROM_BASELINE],
            'method': 'baskets.SCNE assembly Matrix plus hierarchy netpivot translations; original bytes unchanged'}


def interpolate_floor_uvs(points_xz, donor_positions, base_indices, donor_uvs):
    """Barycentric interpolation on the actual base surface; never extrapolate."""
    triangles = donor_positions[base_indices.reshape(-1, 3)][:, :, [0, 2]]
    origin = triangles[:, 0]
    e0, e1 = triangles[:, 1] - origin, triangles[:, 2] - origin
    determinant = e0[:, 0] * e1[:, 1] - e0[:, 1] * e1[:, 0]
    if np.any(np.abs(determinant) < 1e-10):
        raise ValueError('Degenerate donor base UV interpolation triangle')
    outputs = {name: np.empty((len(points_xz), 2)) for name in donor_uvs}
    ids = base_indices.reshape(-1, 3)
    for offset in range(0, len(points_xz), 256):
        points = points_xz[offset:offset + 256]
        q = points[:, None] - origin[None]
        u = (q[:, :, 0] * e1[:, 1] - q[:, :, 1] * e1[:, 0]) / determinant
        v = (e0[:, 0] * q[:, :, 1] - e0[:, 1] * q[:, :, 0]) / determinant
        valid = (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1 + 1e-7)
        if not valid.any(1).all():
            bad = points[np.flatnonzero(~valid.any(1))[0]]
            raise ValueError(f'New line point outside donor base surface: {bad.tolist()}')
        selected = valid.argmax(1)
        row = np.arange(len(points))
        weights = np.column_stack((1 - u[row, selected] - v[row, selected],
                                   u[row, selected], v[row, selected]))
        for name, values in donor_uvs.items():
            outputs[name][offset:offset + len(points)] = np.sum(values[ids[selected]] * weights[:, :, None], 1)
    return outputs


def _solid_texture(level, extra, label, rgb):
    # Three BC1 mip blocks (4x4, 2x2, 1x1), endpoint 0 at the requested RGB565.
    r, g, b = rgb
    color = round(r / 255 * 31) << 11 | round(g / 255 * 63) << 5 | round(b / 255 * 31)
    payload = struct.pack('<HHI', color, max(0, color - 1), 0) * 3
    raw = struct.pack('<4sIHBBIHHHHII', b'TLD ', 0, 4, 71, 3, 31, 4, 4, 1, 1, len(payload), len(payload)) + payload
    binary = f'venice_v3_{label}.{hashlib.sha256(raw).hexdigest()[:16]}.tld'
    key = f'local/venice_v3/{label}'
    level['Texture'][key] = {'Width': 4, 'Height': 4, 'Mips': 3, 'Format': 'BC1_UNORM',
                             'Min': [0, 0, 0, 1], 'Max': [1, 1, 1, 1],
                             'PixelDataSize': len(payload), 'Binary': binary}
    extra[binary] = raw
    return key


def apply_court(level, donor_zip, extra):
    """Replace floor markings in memory and add deterministic self-contained buffers.

    Returns a JSON-serializable report. The builder owns writing archives/files.
    It must write every ``extra`` entry. Existing shared floor shader/lightmaps
    remain as donor dependencies, while the new white/gray line textures are
    bundled. The original base Prim, vertex bytes, scene bounds and Object remain.
    """
    unit_report = _verify_donor_units(donor_zip)
    donor = _fragment(donor_zip.read('level.SCNE'))['level']
    target = donor['Object']['__floor00__']['Target']
    original = donor['Model'][target]
    current = level['Model'][target]
    if current['VertexFormat'] != original['VertexFormat'] or current['VertexStream'] != original['VertexStream']:
        raise ValueError('Unexpected floor layout before revision 3')
    raw = CACHE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CACHE_SHA or len(raw) != original['VertexStream'][0]['Size']:
        raise ValueError('Original decoded floor cache changed')
    old_count = len(raw) // 28
    old_positions = np.ndarray((old_count, 3), '<f4', raw, strides=(28, 4)).copy()
    old_indices = np.frombuffer(donor_zip.read(original['IndexBuffer']['Binary']), '<u2')
    prims = list(iter_primitives(original, indices=old_indices, vertex_count=old_count))
    base = copy.deepcopy(prims[0])
    if base['Mesh'] != 'NBA_full_court_floor_low1Shape' or base['Start'] != 0:
        raise ValueError('Unexpected donor base primitive')
    base_indices = old_indices[:base['Count']]
    features, geometry = court_geometry()
    new_positions = np.concatenate(geometry).reshape(-1, 3)
    if len(new_positions) + old_count > 65535:
        raise ValueError('New court exceeds R16 index capacity')
    if np.any(new_positions.min(0) < np.asarray(original['Min']) - 1e-6) or np.any(new_positions.max(0) > np.asarray(original['Max']) + 1e-6):
        raise ValueError('New lines expand protected donor floor bounds')
    old_uvs = {}
    for name, spec in original['VertexFormat'].items():
        if name.startswith('TEXCOORD'):
            encoded = np.ndarray((old_count, 2), '<i2', raw, offset=spec['ByteOffset'], strides=(28, 2))
            old_uvs[name] = np.maximum(encoded.astype(float) / 32767, -1) * np.array(spec.get('Scale', [1, 1]))[:2] + np.array(spec.get('Offset', [0, 0]))[:2]
    interpolated = interpolate_floor_uvs(new_positions[:, [0, 2]], old_positions, base_indices, old_uvs)
    new_bytes = bytearray(len(new_positions) * 28)
    packed_positions = np.ndarray((len(new_positions), 3), '<f4', new_bytes, strides=(28, 4))
    packed_positions[:] = new_positions
    max_uv1_error = 0.
    for name, values in interpolated.items():
        spec = original['VertexFormat'][name]
        scale = np.array(spec.get('Scale', [1, 1]))[:2]
        offset = np.array(spec.get('Offset', [0, 0]))[:2]
        snorm = (values - offset) / scale
        if np.any(np.abs(snorm) > 1 + 1e-6):
            raise ValueError(f'{name} would clip during SNORM encoding')
        quantized = np.clip(np.round(snorm * 32767), -32767, 32767).astype('<i2')
        np.ndarray((len(new_positions), 2), '<i2', new_bytes, offset=spec['ByteOffset'], strides=(28, 2))[:] = quantized
        if name == 'TEXCOORD1':
            max_uv1_error = float(np.max(np.abs(quantized / 32767 * scale + offset - values)))

    model = copy.deepcopy(current)
    model['Prim'] = [base]
    cursor = len(base_indices)
    for feature, triangles in zip(features, geometry):
        count = triangles.size // 3
        low, high = np.min(triangles, (0, 1)), np.max(triangles, (0, 1))
        center = (low + high) / 2
        model['Prim'].append({'Material': feature['material'], 'Mesh': 'venice_v3:' + feature['name'],
                              'Type': 'TRIANGLE_LIST', 'BlendIndexRange': [0, 0], 'Start': cursor,
                              'Count': count, 'Min': low.tolist(), 'Max': high.tolist(),
                              'Center': center.tolist(),
                              'Radius': float(np.linalg.norm(triangles.reshape(-1, 3) - center, axis=1).max())})
        feature.update(start=cursor, count=count)
        cursor += count
    index_bytes = np.concatenate((base_indices, np.arange(old_count, old_count + len(new_positions)))).astype('<u2').tobytes()

    def resource(label, data):
        name = f'venice_v3_{label}.{hashlib.sha256(data).hexdigest()[:16]}.bin'
        extra[name] = data
        return name

    vertex_bytes = raw + new_bytes
    model['VertexStream'] = [{'Stride': 28, 'Size': len(vertex_bytes), 'Binary': resource('court_vertices', vertex_bytes)}]
    model['IndexBuffer'] = {'Format': 'R16_UINT', 'Size': len(index_bytes), 'Binary': resource('court_indices', index_bytes)}
    model['IndexBufferCrc32'] = zlib.crc32(index_bytes)
    list(iter_primitives(model, indices=np.frombuffer(index_bytes, '<u2'), vertex_count=len(vertex_bytes) // 28))
    for material, label, color in ((WHITE_MATERIAL, 'court_white', (255, 255, 255)),
                                   (MARK_MATERIAL, 'court_lane_marks', (30, 35, 36))):
        mat = copy.deepcopy(level['Material']['floor_clutchtime_court:floor_line_mat1'])
        mat['Resource']['DetailAlbedoTexture'] = {'Pixelmap': _solid_texture(level, extra, label, color)}
        mat.setdefault('Parameter', {})['ModulateAlbedo'] = [1., 1., 1.]
        level['Material'][material] = mat
    level['Model'][target] = model
    return {'sources': [RULE_URL, DIAGRAM_URL], 'model': target, 'units_verification': unit_report,
            'playing_inside_cm': [50 * FOOT, 94 * FOOT], 'ordinary_line_width_cm': WIDTH,
            'lane_outside_width_cm': 16 * FOOT, 'free_throw_line_outside_from_baseline_cm': FREE_THROW_OUTSIDE,
            'three_point_outside_radius_cm': THREE_OUTSIDE, 'corner_three_outside_cm': CORNER_OUTSIDE,
            'line_vertices_added': len(new_positions), 'new_total_vertices': len(vertex_bytes) // 28,
            'new_total_indices': len(index_bytes) // 2, 'base_primitive_preserved': base,
            'old_vertex_prefix_byte_identical': vertex_bytes[:len(raw)] == raw,
            'base_indices_byte_identical': index_bytes[:base['Count'] * 2] == old_indices[:base['Count']].tobytes(),
            'all_new_normals_upward': bool(np.all(np.cross(new_positions.reshape(-1, 3, 3)[:, 1] - new_positions.reshape(-1, 3, 3)[:, 0], new_positions.reshape(-1, 3, 3)[:, 2] - new_positions.reshape(-1, 3, 3)[:, 0])[:, 1] > 0)),
            'protected_model_bounds_unchanged': all(model[k] == original[k] for k in ('Min', 'Max', 'Center', 'Radius')),
            'uv1_method': 'barycentric interpolation on original donor base triangles, then original R16G16_SNORM quantization',
            'uv1_max_quantization_error': max_uv1_error, 'old_four_point_and_duplicate_lane_primitives_removed': True,
            'game_scoring_logic_modified': False, 'game_runtime_verified': False, 'features': features}
