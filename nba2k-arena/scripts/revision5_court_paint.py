"""Add photo-supported matte paint without changing existing court markings.

New geometry is the exact planar difference between five paint domains and the
actual R4 marking triangles. Full native vertex/index prefixes are retained.
This prepares an uninstalled candidate; native depth and lighting need game QA.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import zlib

import numpy as np
from PIL import Image

from revision3_court import interpolate_floor_uvs
from revision3_textures import _color_grade, encode_texture
from revision5_paint_geometry import clip_domains, domains
from revision5_overlap_audit import audit_overlap
from scene_primitives import iter_primitives

ROOT = Path(__file__).resolve().parents[1]
BASE_MATERIAL = 'floor_clutchtime_court:area_1_mat'
PAINT_MATERIAL = 'venice_v3:court_pale_paint_r5'
# 1.25 micrometers per XZ component: just over the largest float32 ULP
# on this court (1.2207 micrometers). This is not a visible painted border.
MARKING_CLEARANCE_CM = .000125
DEPTH_BIAS = -4
SLOPE_DEPTH_BIAS = 0
DEPTH_PATHS = {
    'Default': ('Default', 'ProjectTexture', 'StoryScene', 'StorySceneHard', 'GBuffer', 'DepthNormalPrepass'),
    'Prepass': ('Default', 'DepthNormalPrepass'),
    'Mirror': ('UseHardShadowMaps',),
    'Movie': ('Default',),
}


def paint_material(base, texture_key):
    result = copy.deepcopy(base)
    result['Resource']['DetailAlbedoTexture']['Pixelmap'] = texture_key
    for technique, passes in DEPTH_PATHS.items():
        for name in passes:
            state = result['Technique'][technique]['Pass'][name]
            state['DEPTHBIAS'] = DEPTH_BIAS
            state['SLOPESCALEDEPTHBIAS'] = SLOPE_DEPTH_BIAS
    return result


def triangle_areas(triangles):
    u, v = triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    return (u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]) * .5


def pack_vertices(points_xz, positions, base_indices, source_bytes, vertex_format):
    """Interpolate at the FINAL float32 XZ, then quantize each original UV set."""
    points = np.asarray(points_xz, '<f4').astype(float)
    count = len(source_bytes) // 28
    values = {'height': np.column_stack((positions[:, 1], np.zeros(count)))}
    for name, spec in vertex_format.items():
        if name.startswith('TEXCOORD'):
            encoded = np.ndarray((count, 2), '<i2', source_bytes, offset=spec['ByteOffset'], strides=(28, 2))
            values[name] = np.maximum(encoded.astype(float) / 32767, -1) * np.array(spec.get('Scale', [1, 1]))[:2] + np.array(spec.get('Offset', [0, 0]))[:2]
    interpolated = interpolate_floor_uvs(points, positions, base_indices, values)
    output = bytearray(len(points) * 28)
    final_positions = np.ndarray((len(points), 3), '<f4', output, strides=(28, 4))
    final_positions[:, [0, 2]] = points
    final_positions[:, 1] = interpolated.pop('height')[:, 0]
    errors = {}
    for name, uv in interpolated.items():
        spec = vertex_format[name]
        scale, offset = np.array(spec.get('Scale', [1, 1]))[:2], np.array(spec.get('Offset', [0, 0]))[:2]
        snorm = (uv-offset)/scale
        if not np.isfinite(snorm).all() or np.any(np.abs(snorm) > 1+1e-6):
            raise ValueError(f'Paint {name} exceeds native SNORM bounds')
        encoded = np.clip(np.rint(snorm*32767), -32767, 32767).astype('<i2')
        np.ndarray((len(points), 2), '<i2', output, offset=spec['ByteOffset'], strides=(28, 2))[:] = encoded
        errors[name] = float(np.max(np.abs(encoded.astype(float)/32767*scale+offset-uv)))
    return bytes(output), errors


def apply_paint(level, archive, extra, *, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = level['Object']['__floor00__']['Target']
    before = copy.deepcopy(level['Model'][target])
    if len(before['VertexStream']) != 1 or before['VertexStream'][0]['Stride'] != 28 or before['IndexBuffer']['Format'] != 'R16_UINT':
        raise ValueError('Unsupported native floor layout')
    old_vb = archive.read(before['VertexStream'][0]['Binary'])
    old_ib = archive.read(before['IndexBuffer']['Binary'])
    if (len(old_vb), len(old_ib)) != (785148, 53640):
        raise ValueError('R5 expects the entire verified R4 floor')
    old_count = len(old_vb)//28
    positions = np.ndarray((old_count, 3), '<f4', old_vb, strides=(28, 4)).astype(float)
    indices = np.frombuffer(old_ib, '<u2')
    prims = list(iter_primitives(before, indices=indices, vertex_count=old_count))
    base_count = prims[0]['Count']
    if prims[0]['Start'] != 0 or base_count != 2010:
        raise ValueError('Expected 670 original base surface triangles')
    marking_triangles = positions[indices[base_count:].reshape(-1, 3)][:, :, [0, 2]]
    guarded = np.zeros(len(marking_triangles), dtype=bool)
    iterations = []
    # Guard all marking boundaries intersecting an affected paint domain.
    # Adjacent curves and straight edges then share one clearance, avoiding
    # microscopic fragments at mixed-clearance junctions. Unaffected domains
    # keep their exact boundary. Every iteration audits ALL marking triangles.
    mark_low, mark_high = marking_triangles.min(1), marking_triangles.max(1)
    for attempt in range(8):
        reports, geometry = clip_domains(marking_triangles, clearance_cm=MARKING_CLEARANCE_CM, clearance_mask=guarded)
        final_geometry, discarded = [], []
        for entry, triangles in zip(reports, geometry):
            quantized = triangles.astype('<f4').astype(float)
            areas = triangle_areas(quantized)
            keep = areas > 0
            # Float32 can collapse only microscopic slivers at boundaries.
            lost = float(np.abs(triangle_areas(triangles[~keep])).sum())
            removed = triangles[~keep]
            edges = np.linalg.norm(removed-np.roll(removed, 1, axis=1), axis=2)
            altitude = 2*np.abs(triangle_areas(removed))/np.maximum(edges.max(1), 1e-30)
            rounding = np.linalg.norm(quantized[~keep]-removed, axis=2).max(1)
            if lost > .05 or (altitude > 4*rounding+1e-7).any():
                raise ValueError(f'Float32 conversion for {entry["name"]}: lost area={lost}, minimum signed area={areas.min()}, discarded={int((~keep).sum())}')
            final_geometry.append(quantized[keep])
            discarded.append({'name': entry['name'], 'triangles': int((~keep).sum()), 'area_cm2': lost,
                              'maximum_altitude_cm': float(altitude.max(initial=0))})
            entry.update(final_triangles=int(keep.sum()), final_area_cm2=float(areas[keep].sum()))
        numeric_audit = audit_overlap(np.concatenate(final_geometry), marking_triangles)
        iterations.append({'iteration': attempt, 'guarded_markings': int(guarded.sum()),
                           'over_threshold_pairs': numeric_audit['over_threshold_pair_count'],
                           'maximum_overlap_area_cm2': numeric_audit['max_overlap_area_cm2']})
        print(f'R5 precision iteration {attempt}: {numeric_audit["over_threshold_pair_count"]} overlaps above threshold', flush=True)
        if numeric_audit['all_pairs_below_threshold']:
            break
        additions = numeric_audit['marking_triangles_over_threshold']
        old_guarded = guarded.copy()
        guarded[additions] = True
        for _, domain in domains():
            low, high = domain.min(0)-MARKING_CLEARANCE_CM, domain.max(0)+MARKING_CLEARANCE_CM
            intersects = np.all(mark_high > low, axis=1) & np.all(mark_low < high, axis=1)
            if intersects[additions].any():
                guarded[intersects] = True
        if np.array_equal(old_guarded, guarded):
            raise ValueError('Numerical guard cannot resolve a remaining overlap')
    else:
        raise ValueError('Paint precision refinement did not converge')
    np.savez_compressed(output_dir/'unquantized_geometry.npz', **{entry['name']:g for entry,g in zip(reports, geometry)})
    # Clockwise in XZ is upward winding in XYZ.
    points = np.concatenate(final_geometry)[:, ::-1].reshape(-1, 2)
    records, uv_errors = pack_vertices(points, positions, indices[:base_count], old_vb, before['VertexFormat'])
    # Deduplicate COMPLETE encoded vertices, never just XZ across potential UV seams.
    data = np.frombuffer(records, dtype='V28')
    _, first, inverse = np.unique(data, return_index=True, return_inverse=True)
    new_vb = data[first].tobytes()
    new_count = len(new_vb)//28
    if old_count + new_count > 65535:
        raise ValueError(f'Paint exceeds R16 capacity: {old_count}+{new_count}')
    new_indices = (old_count+inverse).astype('<u2')
    new_positions = np.ndarray((new_count, 3), '<f4', new_vb, strides=(28, 4)).astype(float)
    triangles_xyz = new_positions[inverse.reshape(-1, 3)]
    overlap = audit_overlap(triangles_xyz[:, :, [0, 2]], marking_triangles)
    (output_dir/'overlap_audit.json').write_text(json.dumps(overlap, indent=2)+'\n')
    if not overlap['all_pairs_below_threshold']:
        raise ValueError(f'Native paint overlaps preserved markings: {overlap["worst_pair"]}')
    if not (np.cross(triangles_xyz[:, 1]-triangles_xyz[:, 0], triangles_xyz[:, 2]-triangles_xyz[:, 0])[:, 1] > 0).all():
        raise ValueError('Invalid final native paint winding')
    if np.any(new_positions.min(0) < np.array(before['Min'])-1e-8) or np.any(new_positions.max(0) > np.array(before['Max'])+1e-8):
        raise ValueError('Paint exceeds protected native floor bounds')
    vb, ib = old_vb+new_vb, old_ib+new_indices.tobytes()
    model = copy.deepcopy(before)
    cursor = len(indices)
    start = 0
    for entry in reports:
        count = entry['final_triangles']*3
        vertices = triangles_xyz.reshape(-1, 3)[start:start+count]
        lo, hi = vertices.min(0), vertices.max(0)
        center = (lo+hi)/2
        model['Prim'].append({'Material': PAINT_MATERIAL, 'Mesh': 'venice_v3:r5_'+entry['name'],
                              'Type': 'TRIANGLE_LIST', 'BlendIndexRange': [0, 0], 'Start': cursor, 'Count': count,
                              'Min': lo.tolist(), 'Max': hi.tolist(), 'Center': center.tolist(),
                              'Radius': float(np.linalg.norm(vertices-center, axis=1).max())})
        cursor += count
        start += count

    def resource(label, raw):
        name = f'venice_v3_r5_{label}.{hashlib.sha256(raw).hexdigest()[:16]}.bin'
        extra[name] = raw
        return name

    model['VertexStream'] = [{'Stride': 28, 'Size': len(vb), 'Binary': resource('paint_vertices', vb)}]
    model['IndexBuffer'] = {'Format': 'R16_UINT', 'Size': len(ib), 'Binary': resource('paint_indices', ib)}
    model['IndexBufferCrc32'] = zlib.crc32(ib)
    list(iter_primitives(model, indices=np.frombuffer(ib, '<u2'), vertex_count=len(vb)//28))
    if model['Prim'][:len(before['Prim'])] != before['Prim'] or vb[:len(old_vb)] != old_vb or ib[:len(old_ib)] != old_ib:
        raise ValueError('Protected R4 marking prefix changed')
    mutable = {'Prim', 'VertexStream', 'IndexBuffer', 'IndexBufferCrc32'}
    if {k:v for k,v in model.items() if k not in mutable} != {k:v for k,v in before.items() if k not in mutable}:
        raise ValueError('Protected native floor metadata changed')

    manifest = json.loads((ROOT/'textures/source/polyhaven/manifest.json').read_text())
    source = next(v for v in manifest if v['asset'] == 'concrete_floor_02' and v['map'] == 'Diffuse')
    source_path = ROOT/'textures/source/polyhaven'/source['file']
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != source['sha256']:
        raise ValueError('Scanned albedo source changed')
    # Artistic encoded RGB match under shared lighting; photographs do not
    # establish physical albedo. Keep the same scan grain and UV as the base.
    painted = _color_grade(Image.open(source_path).convert('RGB'), (143, 147, 148),
                           contrast=.32, retain_color=.03, remove_stains=True)
    key, spec, raw, texture = encode_texture('court_pale_paint_r5', painted, output_dir=output_dir/'textures')
    level['Texture'][key] = spec
    extra[spec['Binary']] = raw
    level['Material'][PAINT_MATERIAL] = paint_material(level['Material'][BASE_MATERIAL], key)
    level['Model'][target] = model
    # Retain the actual exported coordinates for an independent intersection audit.
    np.savez_compressed(output_dir/'native_paint_geometry.npz', paint=triangles_xyz[:, :, [0, 2]], markings=marking_triangles)
    report = {'model': target, 'material': PAINT_MATERIAL, 'regions': reports, 'texture': texture,
              'source': source, 'encoded_rgb_target': [143, 147, 148],
              'total_vertices': len(vb)//28, 'vertices_added': new_count, 'indices_added': len(new_indices),
              'triangles_added': len(new_indices)//3, 'uv_max_quantization_error': uv_errors,
              'quantization_discarded_slivers': discarded, 'existing_vertex_prefix_preserved': True,
              'marking_clearance_cm_per_axis': MARKING_CLEARANCE_CM, 'independent_overlap_audit': overlap,
              'guarded_marking_triangle_count': int(guarded.sum()), 'precision_iterations': iterations,
              'existing_index_prefix_preserved': True, 'existing_primitive_records_preserved': True,
              'floor_bounds_and_object_preserved': True, 'all_new_triangles_upward': True,
              'depth_bias_candidate': DEPTH_BIAS, 'slope_depth_bias_candidate': SLOPE_DEPTH_BIAS,
              'depth_paths': DEPTH_PATHS,
              'game_runtime_verified': False}
    (output_dir/'paint_report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report
