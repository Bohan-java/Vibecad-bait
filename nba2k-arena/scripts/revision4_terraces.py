"""Round the generated three-tier grass bank; preserve objects and donor data.

Photo-supported feature: low terraced grass with curved returns, one court side.
All radii and distances below are design choices, not photogrammetric recovery.
The mesh also closes R3's real ground gap at x1100..2435, |z|5050..6500.
"""
from __future__ import annotations
from pathlib import Path

import numpy as np

from revision3_landscape import Mesh, IDENTITY
from revision3_mesh import decode_tangent_frames, export_mesh

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'venice_v3:grass_terraces'
HEIGHTS = (30., 65., 100.)
FRONTS = (1100., 1545., 1990.)
RETURN_X = 2435.
CURVE_START_Z = 4000.
RADII = tuple(RETURN_X - x for x in FRONTS)
FAR_X = 4100.
END_Z = 8000.
CURB_WIDTH = 18.


def fronts_at(z):
    t = np.maximum(np.abs(np.asarray(z, float)) - CURVE_START_Z, 0)
    return np.array([RETURN_X - np.sqrt(np.maximum(r*r - np.minimum(t, r)**2, 0))
                     for r in RADII]).T


def ground_height(z):
    """A far tie-in meets existing coast grass at |z|8000 without a vertical hole."""
    t = np.clip((np.abs(np.asarray(z, float)) - 6000.) / 2000., 0, 1)
    s = t*t*(3 - 2*t)
    return -.4 + 100.7 * s


def far_height(z):
    t = np.clip((np.abs(np.asarray(z, float)) - 6000.) / 2000., 0, 1)
    return 100. + .3*t*t*(3 - 2*t)


def surface_height(x, z):
    """Analytic design surface, excluding the same-height concrete curb strips."""
    if not 1100 <= x <= FAR_X or abs(z) > END_Z:
        raise ValueError('Point outside grass-bank design domain')
    fronts = fronts_at(z)
    if x >= fronts[2]:
        return float(far_height(z))
    if x >= fronts[1]:
        return HEIGHTS[1]
    if x >= fronts[0]:
        return HEIGHTS[0]
    return float(ground_height(z))


def _samples():
    # Dense circular sampling, merged with a one-centimeter minimum separation.
    # This stays above the native 0.244 cm position step for the 160 m span.
    values = {0., CURVE_START_Z, 6000., END_Z}
    values.update(np.arange(0, END_Z + 1, 100.).tolist())
    for radius in RADII:
        values.update((CURVE_START_Z + radius*np.sin(np.linspace(0, np.pi/2, 97))).tolist())
    required = {0., CURVE_START_Z, 6000., END_Z, *(CURVE_START_Z + r for r in RADII)}
    selected = []
    for value in sorted(values):
        if selected and value-selected[-1] < 1.:
            if value in required:
                selected[-1] = value
        else:
            selected.append(value)
    return np.unique(np.r_[-np.array(selected)[::-1], selected])


def terrace_geometry():
    mesh = Mesh()
    zs = _samples()
    fronts = fronts_at(zs)

    def surface(material, left, right, heights):
        for j, (z0, z1) in enumerate(zip(zs[:-1], zs[1:])):
            p = np.array([[left[j], heights[j], z0], [left[j+1], heights[j+1], z1],
                          [right[j+1], heights[j+1], z1], [right[j], heights[j], z0]])
            mesh.quad(material, p, p[:, [0, 2]]/200.)

    ground = ground_height(zs)
    # Actual lower grass terrain closes the old hole, not a floating cover/card.
    surface('grass', np.full(len(zs), 1100.), fronts[:, 0], ground)
    for tier, top in enumerate(HEIGHTS):
        left = fronts[:, tier]
        right = fronts[:, tier+1] if tier < 2 else np.full(len(zs), FAR_X)
        upper = np.full(len(zs), top) if tier < 2 else far_height(zs)
        lower = np.maximum(ground, -.4 if tier == 0 else HEIGHTS[tier-1])
        upper = np.maximum(upper, lower)
        # Horizontal cap and turf share an edge, with no layered coplanar faces.
        cap_end = np.minimum(left + CURB_WIDTH, right)
        surface('concrete', left, cap_end, upper)
        surface('grass', cap_end, right, upper)
        for j, (z0, z1) in enumerate(zip(zs[:-1], zs[1:])):
            p = np.array([[left[j], lower[j], z0], [left[j+1], lower[j+1], z1],
                          [left[j+1], upper[j+1], z1], [left[j], upper[j], z0]])
            mesh.quad('concrete', p, p[:, [2, 1]]/200.)
    # Snap to the exporter lattice first. Zero-area slivers become shared edges
    # at native precision, rather than surviving as invalid exported triangles.
    all_points = np.concatenate(list(mesh.parts.values())).reshape(-1, 3)
    lo, hi = all_points.min(0), all_points.max(0)
    span = float((hi-lo).max()); offset = (lo+hi)/2-span/2
    removed = 0
    for material in list(mesh.parts):
        faces = np.asarray(mesh.parts[material])
        faces = np.rint((faces-offset)/span*65535)/65535*span+offset
        cross = np.cross(faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0])
        valid = np.linalg.norm(cross, axis=1) > 1e-7
        removed += int(np.count_nonzero(~valid))
        faces, cross = faces[valid], cross[valid]
        normals = cross / np.linalg.norm(cross, axis=1)[:, None]
        # Every top uses world X/Z; front walls use Z/Y. Recompute UVs after
        # quantization so tangent derivation sees the geometry that is exported.
        uvs = faces[:, :, [0, 2]]/200
        walls = np.abs(normals[:, 1]) < .1
        uvs[walls] = faces[walls][:, :, [2, 1]]/200
        mesh.parts[material] = list(faces)
        mesh.uv[material] = list(uvs)
        mesh.normals[material] = list(np.repeat(normals[:, None, :], 3, axis=1))
    return mesh, {'samples_along_z': len(zs), 'native_zero_area_slivers_removed': removed,
                  'native_position_step_cm': span/65535}


def decode_export(model, extra):
    spec = model['VertexFormat']['POSITION0']; stream = model['VertexStream'][0]
    packed = np.frombuffer(extra[stream['Binary']], '<u2').reshape(-1, 4)
    positions = packed[:, :3]/65535*np.array(spec['Scale'][:3])+spec['Offset'][:3]
    indices = np.frombuffer(extra[model['IndexBuffer']['Binary']], '<u2')
    if len(indices) * 2 != model['IndexBuffer']['Size'] or indices.max() >= len(positions):
        raise ValueError('Exported index buffer invalid')
    triangles = positions[indices].reshape(-1, 3, 3)
    normal_spec = model['VertexFormat']['TANGENTFRAME0']
    s = model['VertexStream'][normal_spec.get('Stream', 0)]
    words = np.ndarray((len(positions),), '<u4', extra[s['Binary']],
                       offset=normal_spec.get('ByteOffset', 0), strides=(s['Stride'],))
    normals = decode_tangent_frames(words)[0]
    return triangles, normals[indices].reshape(-1, 3, 3)


def height_on_triangles(triangles, x, z):
    p = np.asarray(triangles)
    # Explicit indexing keeps arrays T x 2, independent of advanced-index order.
    a, b, c = p[:, 0][:, [0, 2]], p[:, 1][:, [0, 2]], p[:, 2][:, [0, 2]]
    e1, e2, q = b-a, c-a, np.array([x, z])-a
    det = e1[:, 0]*e2[:, 1]-e1[:, 1]*e2[:, 0]
    valid = np.abs(det) > 1e-9
    u = np.zeros(len(p)); v = np.zeros(len(p))
    u[valid] = (q[valid, 0]*e2[valid, 1]-q[valid, 1]*e2[valid, 0])/det[valid]
    v[valid] = (e1[valid, 0]*q[valid, 1]-e1[valid, 1]*q[valid, 0])/det[valid]
    inside = valid & (u >= -1e-7) & (v >= -1e-7) & (u+v <= 1+1e-7)
    if not np.any(inside):
        raise ValueError(f'No exported terrain under ({x}, {z})')
    heights = p[:, 0, 1]+u*(p[:, 1, 1]-p[:, 0, 1])+v*(p[:, 2, 1]-p[:, 0, 1])
    return float(heights[inside].max())


def _grounded_objects(level, triangles):
    groups = {}
    for name, obj in level['Object'].items():
        if not name.startswith('venice_v3:') or not any(w in name for w in ('palm_', 'coastal_double_lamp', 'stacked_stone')):
            continue
        matrix = obj.get('Matrix', IDENTITY)
        position = tuple(float(v) for v in matrix[12:15])
        if position[0] < 1100:
            continue  # Unchanged opposite-side palms are outside this model.
        groups.setdefault(position, []).append(name)
    result = []
    for (x, y, z), names in groups.items():
        height = height_on_triangles(triangles, x, z)
        error = y-height
        if abs(error) > .3:
            raise ValueError(f'Existing object would lose ground: {names[0]} ({error:.3f} cm)')
        # Verify the trunk/base support disc as well as its exact center.
        radius = 27. if 'palm_' in names[0] else (23. if 'lamp' in names[0] else 48.)
        disk = [height_on_triangles(triangles, x+radius*np.cos(a), z+radius*np.sin(a))
                for a in np.linspace(0, 2*np.pi, 9)[:-1]]
        if max(abs(y-h) for h in disk) > .3:
            raise ValueError(f'Object footprint crosses a terrace step: {names[0]}')
        result.append({'objects': names, 'position_cm': [x, y, z], 'exported_ground_y': height,
                       'base_error_cm': error, 'support_radius_cm': radius, 'footprint_supported': True})
    return result


def save_preview(triangles, model, grounding, output_dir):
    from PIL import Image, ImageDraw, ImageFont
    output_dir = Path(output_dir).resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (1700, 940), '#f2f0e8'); draw = ImageDraw.Draw(image)
    font_path = '/System/Library/Fonts/Supplemental/Arial.ttf'
    font = ImageFont.truetype(font_path, 18) if Path(font_path).exists() else ImageFont.load_default()
    big = ImageFont.truetype(font_path, 25) if Path(font_path).exists() else font
    colors = []
    for prim in model['Prim']:
        colors.extend([(128, 148, 92) if prim['Material'].endswith(':grass') else (200, 192, 172)] * (prim['Count']//3))
    colors = np.asarray(colors)
    draw.text((35, 22), 'R4 rounded grass bank - actual native-buffer geometry', fill='#243024', font=big)
    draw.text((35, 59), 'One court side only. Design dimensions; no photo measurement or game-render claim.', fill='#4f574d', font=font)
    # Top view uses true horizontal proportions and actual exported polygons.
    flat = triangles[:, :, [2, 0]]
    scale = 1590/16200
    screen = flat.copy(); screen[:, :, 0] = 55+(screen[:, :, 0]+8100)*scale
    screen[:, :, 1] = 155+(screen[:, :, 1]-950)*scale
    for face, color in zip(screen, colors):
        draw.polygon([tuple(v) for v in face], fill=tuple(color))
    for item in grounding:
        x, _, z = item['position_cm']; px, py = 55+(z+8100)*scale, 155+(x-950)*scale
        draw.ellipse((px-4, py-4, px+4, py+4), fill='#243524')
    draw.text((40, 112), 'Plan: Z -8000 to +8000 cm; X 1100 to 4100 cm. Dots = unchanged supported plants / lamps.', fill='#374132', font=font)
    draw.text((40, 495), 'Near-end return, vertical scale x8 for inspection:', fill='#374132', font=font)
    keep = (triangles[:, :, 2].mean(1)>3500) & (triangles[:, :, 2].mean(1)<6500)
    points = triangles[keep].copy(); points[:, :, 0]-=2600; points[:, :, 2]-=5000; points[:, :, 1]*=8
    view = np.array([-1., 1.1, 1.3]); view/=np.linalg.norm(view)
    right = np.cross(view, [0.,1.,0.]); right/=np.linalg.norm(right)
    up = np.cross(right, view)
    projected = np.stack([points@right, -(points@up)], axis=-1)
    lo = projected.reshape(-1,2).min(0); hi = projected.reshape(-1,2).max(0)
    scale = min(1500/(hi[0]-lo[0]), 360/(hi[1]-lo[1]))
    projected = (projected-lo)*scale + [90, 540]
    depth = (points@view).mean(1)
    normals = np.cross(points[:,1]-points[:,0], points[:,2]-points[:,0])
    normals/=np.linalg.norm(normals,axis=1)[:,None]
    light = np.array([-1.,2.,.5]);light/=np.linalg.norm(light)
    shaded = np.clip(colors[keep]*(.66+.34*np.clip(normals@light,0,1))[:,None],0,255).astype(int)
    for i in np.argsort(depth):
        draw.polygon([tuple(v) for v in projected[i]], fill=tuple(shaded[i]))
    path=output_dir/'terraces_exported.png'; image.save(path)
    return str(path)


def apply_terraces(level, extra, *, output_dir=None):
    """Replace exactly one generated model, after validating exported terrain."""
    if MODEL not in level['Model']:
        raise ValueError('Call after R3 landscape has created grass_terraces')
    objects = [o for o in level['Object'].values() if o.get('Target') == MODEL]
    if not objects or any(not np.allclose(o.get('Matrix', IDENTITY), IDENTITY, atol=1e-8) for o in objects):
        raise ValueError('Expected unchanged identity placement of the existing grass bank')
    mesh, geometry_report = terrace_geometry()
    staged = dict(level); staged['Model'] = dict(level['Model']); del staged['Model'][MODEL]
    generated = {}
    exported = export_mesh(staged, generated, MODEL, mesh.parts, uv_parts=mesh.uv, normal_parts=mesh.normals)
    model = staged['Model'][MODEL]
    triangles, normals = decode_export(model, generated)
    cross = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
    area2 = np.linalg.norm(cross, axis=1)
    if np.any(area2 <= 1e-7):
        raise ValueError('Native quantization produced a degenerate terrain face')
    directions = cross/area2[:, None]
    agreement = (directions[:, None, :]*normals).sum(-1)
    if agreement.min() < .999:
        raise ValueError('Exported terrain normals disagree with winding')
    horizontal = np.abs(directions[:, 1]) > .1
    if np.any(directions[horizontal, 1] <= 0) or np.any(directions[~horizontal, 0] > .001):
        raise ValueError('Terrain tops/front walls face the wrong direction')
    if triangles[:, :, 0].min() < 1099.8:
        raise ValueError('Grass bank intrudes toward the protected court')
    projected_area = float(np.abs(cross[:, 1]).sum()/2)
    expected_area = float(np.ptp(triangles[:, :, 0])*np.ptp(triangles[:, :, 2]))
    if abs(projected_area-expected_area) > .01:
        raise ValueError('Terrain horizontal coverage area has gaps or overlaps')
    grounding = _grounded_objects(level, triangles)
    coverage = []
    # Includes the exact previously empty region and both round returns.
    for z in np.r_[np.linspace(-7999, 7999, 49), [-6499, -5500, -5051, 5051, 5500, 6499]]:
        for x in np.linspace(1101, 4099, 25):
            height = height_on_triangles(triangles, x, z)
            if not np.isfinite(height):
                raise ValueError('Non-finite terrain coverage height')
            coverage.append(height)
    for key, value in generated.items():
        if key in extra and extra[key] != value:
            raise ValueError('New terrain buffer would overwrite differing resource bytes')
    preview = save_preview(triangles, model, grounding, output_dir) if output_dir is not None else None
    level['Model'][MODEL] = model
    extra.update(generated)
    unaffected_palms = {}
    for name, obj in level['Object'].items():
        if name.startswith('venice_v3:palm_'):
            xyz = tuple(obj.get('Matrix', IDENTITY)[12:15])
            if xyz[0] < 1100:
                unaffected_palms.setdefault(xyz, []).append(name)
    return {'model': exported, 'geometry': geometry_report,
            'changed_models': [MODEL], 'changed_objects': [], 'changed_other_scene_sections': [],
            'new_binary_resources': sorted(generated), 'old_binary_resources_modified': False,
            'new_collision_resources': 0, 'reference_images': ['arena_reference_02.png', 'arena_reference_04.png'],
            'dimensions_are_design_parameters_not_photo_measurements': True,
            'tier_heights_cm': list(HEIGHTS), 'straight_front_x_cm': list(FRONTS),
            'return_center_x_cm': RETURN_X, 'return_start_abs_z_cm': CURVE_START_Z,
            'return_radii_cm': list(RADII), 'far_grass_tie_in_abs_z_cm': [6000, END_Z],
            'old_uncovered_ground_cm': {'x': [1100, 2435], 'abs_z': [5050, 6500]},
            'old_gap_closed_by_continuous_ground_surface': True,
            'coverage_rays_passed': len(coverage), 'all_exported_faces_nondegenerate': True,
            'projected_coverage_area_cm2': projected_area,
            'rectangular_domain_area_cm2': expected_area,
            'minimum_normal_winding_dot': float(agreement.min()), 'grounding': grounding,
            'unchanged_palms_outside_this_model': [{'position_cm': list(xyz), 'objects': names}
                                                   for xyz, names in unaffected_palms.items()],
            'all_original_object_matrices_preserved': True, 'preview': preview,
            'game_render_verified': False}
