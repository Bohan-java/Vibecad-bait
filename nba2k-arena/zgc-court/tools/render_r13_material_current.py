"""Six material/detail views of the GLB decoded from the published R13 IFF.

Blender --background --python tools/render_r13_material_current.py -- \
    --views entry,sign,hardware,awning,paving,backboard

No source blend is opened or saved. Imported meshes/materials are untouched.
Only disposable viewing lights/camera are created. Native IFF, decoded GLB,
delivery manifest, imported bounds and material signatures are checked.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import zipfile

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from iff_codec import load_scne
from render_chilis_native_current import (
    box_extents, expected_bounds, glb_json, preview_to_blender, sha_file,
)
from render_context_native_current import material_signature

NAMES = ('entry', 'sign', 'hardware', 'awning', 'paving', 'backboard')
REPORT = ROOT / 'validation/r13-native-visual-validation.json'


def view_config(project, name):
    """Camera positions are photographic/source coordinates before native yaw."""
    if name == 'entry':
        return {
            'position': [-17.403, -4.20, 2.60],
            'target': [-21.053, -4.20, 2.45], 'fov': 90.,
            'purpose': 'Main court-facing entrance, complete sign fascia, columns and awning',
            'derivation': 'Root-confirmed camera in the doorway/fence corridor: source X=frontX+3.65, Y=-4.2; 90 degree vertical FOV includes both silver columns without hiding the fence',
        }
    views = {
        'sign': {
            'position': [-17.953, -4.20, 3.80],
            'target': [-20.869, -4.20, 3.80], 'fov': 55.,
            'purpose': 'Non-emitting built-up Chili logo faces, rims, letter depth and fascia surface',
            'derivation': 'R13 facade builder confirms logo face X=-21.053+.184, Y=-4.2, Z=3.8, width 3.02 metres',
        },
        'hardware': {
            'position': [-16.90, -7.00, 1.70],
            'target': [-20.98, -6.75, 1.62], 'fov': 54.,
            'purpose': 'Left metal column, door leaves, brushed metal pulls, glazing reveals and lower threshold',
            'derivation': 'R13 facade builder confirms left column Y=-9.5 and entry pulls Y=-4.2+/-0.16; pulls Z=.94..1.74 / X=-21.053+.124',
        },
        'awning': {
            'position': [-16.90, -8.05, 2.08],
            'target': [-20.05, -6.40, 3.03], 'fov': 53.,
            'purpose': 'Oblique underside of canvas awning, stitched seams, valance and articulated metal supports',
            'derivation': 'Awning extends 0.14..1.505 metres toward court; support / canopy Z=2.98..3.20',
        },
        'paving': {
            'position': [-17.75, -4.95, 2.22],
            'target': [-20.00, -4.50, .03], 'fov': 54.,
            'purpose': 'Entrance grey stone, mineral variation, paving joints and metal threshold',
            'derivation': 'R13 facade builder confirms local stone apron X=-21.053+.08..2.076, Y=-9.675..1.275, Z=.025',
        },
        'backboard': {
            'position': [-9.72, -2.65, 3.52],
            'target': [-13.105, 0., 3.36], 'fov': 28.,
            'purpose': 'Native dynamic backboard neutral glass opacity, softened reflections, white target and native frame',
            'derivation': 'Photo-half native backboard plane source X=-13.1064; face toward court, moderate oblique front view',
        },
    }
    return views[name]


def native_material_snapshot(archive, doc):
    """Record actual native controls/texture ranges, never inferred shader values."""
    selected = set()
    node_counts = {'chilis': 0, 'r13': 0, 'basket_glass': 0}
    for node in doc['nodes']:
        if 'mesh' not in node:
            continue
        label = node.get('name', '')
        relevant = 'Chilis' in label or 'chilis' in label
        node_counts['chilis'] += int(relevant)
        node_counts['r13'] += int('R13' in label)
        for prim in doc['meshes'][node['mesh']]['primitives']:
            if 'material' not in prim:
                continue
            material = doc['materials'][prim['material']]
            name = material.get('extras', {}).get('native_material', material.get('name', ''))
            glass = name.endswith((':glass_shader_mat', ':glasshole_shader_mat'))
            node_counts['basket_glass'] += int(glass)
            if relevant or glass:
                selected.add(name)
    records = []
    for scene_member in ('level.SCNE', 'baskets.SCNE'):
        section = next(iter(load_scne(archive.read(scene_member)).values()))
        for name in sorted(selected.intersection(section.get('Material', {}))):
            material = section['Material'][name]
            effect = section['Effect'][material['Effect']]
            textures = {}
            for slot, resource in material.get('Resource', {}).items():
                pixelmap = resource.get('Pixelmap')
                if not pixelmap or pixelmap not in section.get('Texture', {}):
                    continue
                spec = section['Texture'][pixelmap]
                textures[slot] = {'pixelmap': pixelmap, **{
                    key: spec[key] for key in
                    ('Width', 'Height', 'Mips', 'Format', 'Min', 'Max', 'TexelUsage', 'Binary')
                    if key in spec
                }}
            effect_values = {key: value['Value'] for key, value in effect.get('Parameter', {}).items()
                             if 'Value' in value}
            previews = [m for m in doc.get('materials', [])
                        if m.get('extras', {}).get('native_material', m.get('name', '')) == name]
            records.append({
                'scene_member': scene_member, 'name': name, 'native_effect': material['Effect'],
                'native_material_parameters': material.get('Parameter', {}),
                'native_effect_declared_default_values': effect_values,
                'native_texture_descriptors': textures,
                'native_material_definition_sha256': hashlib.sha256(
                    json.dumps(material, sort_keys=True, separators=(',', ':')).encode('utf8')).hexdigest(),
                'preview_materials': previews,
            })
    if not node_counts['chilis'] or not node_counts['basket_glass']:
        raise RuntimeError('Actual native GLB lacks required Chili or glass material subjects')
    return {'selected_native_material_count': len(records), 'subject_node_counts': node_counts, 'materials': records}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-iff-sha')
    parser.add_argument('--views', default=','.join(NAMES))
    parser.add_argument('--width', type=int, default=1600)
    parser.add_argument('--height', type=int, default=1000)
    parser.add_argument('--samples', type=int, default=24)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--append-report', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    names = args.views.split(',')
    if not names or any(n not in NAMES for n in names) or len(set(names)) != len(names):
        raise ValueError('Unknown or duplicate R13 material view')
    if not (1 <= args.samples <= 512 and 1 <= args.threads <= 64 and
            320 <= args.width <= 4096 and 240 <= args.height <= 4096):
        raise ValueError('Invalid inspection render limits')

    asset = ROOT / 'public/game-preview/current.glb'
    manifest_path = ROOT / 'public/game-preview/manifest.json'
    iff_path = ROOT / 'output/arena_700_int.iff'
    delivery_path = ROOT / 'validation/iff-current.json'
    project_path = ROOT / 'config/project.json'
    native = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    delivery = json.loads(delivery_path.read_text(encoding='utf-8-sig'))
    project = json.loads(project_path.read_text(encoding='utf-8-sig'))
    if delivery.get('revision') != 'R13' or native.get('kind') != 'native_iff' or not native.get('iff_version', '').startswith('R13'):
        raise RuntimeError('Refuse a non-R13 delivery or a preview not decoded from the actual IFF')
    iff_sha = sha_file(iff_path)
    if not iff_sha == delivery['output_sha256'] == native['iff']['sha256']:
        raise RuntimeError('Actual IFF, delivery report and native preview hashes differ')
    if args.expected_iff_sha and args.expected_iff_sha != iff_sha:
        raise RuntimeError('Unexpected final IFF hash')
    if not iff_path.stat().st_size == delivery['output_bytes'] == native['iff']['bytes']:
        raise RuntimeError('Actual IFF size differs from current manifests')
    glb_sha = sha_file(asset)
    if glb_sha != native['asset']['sha256'] or asset.stat().st_size != native['asset']['bytes']:
        raise RuntimeError('Native GLB hash/size differs from the actual-IFF manifest')
    doc = glb_json(asset)
    if doc.get('asset', {}).get('generator') != 'ZGC final IFF decoder':
        raise RuntimeError('Only actual IFF-decoder output is accepted')
    yaw = native.get('game_world_yaw_degrees')
    if yaw != 180:
        raise RuntimeError('Expected the preserved 180 degree Blacktop half-court orientation')
    rotation = Matrix.Rotation(math.radians(yaw), 3, 'Z')
    with zipfile.ZipFile(iff_path) as archive:
        materials = native_material_snapshot(archive, doc)
    expected = expected_bounds(doc)
    immutable_paths = (asset, manifest_path, iff_path, delivery_path, project_path)
    original_stats = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in immutable_paths}
    original_hashes = {str(p): sha_file(p) for p in (manifest_path, delivery_path, project_path)}

    previous = None
    if args.append_report and REPORT.exists():
        previous = json.loads(REPORT.read_text(encoding='utf-8-sig'))
        if previous.get('iff_sha256') != iff_sha or previous.get('input_glb_sha256') != glb_sha:
            raise RuntimeError('Cannot append views from a different native IFF or GLB')
        for name, row in previous.get('views', {}).items():
            image_path = Path(row['path']).resolve()
            if not image_path.is_relative_to(ROOT / 'validation') or not image_path.exists() or sha_file(image_path) != row['sha256']:
                raise RuntimeError('Cannot append to a report with missing/changed prior image: ' + name)

    runtime = ROOT / '.build-staging/r13-native-render'
    runtime.mkdir(parents=True, exist_ok=True)
    bpy.context.preferences.filepaths.temporary_directory = str(runtime)
    bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
    bpy.context.preferences.filepaths.file_preview_type = 'NONE'
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(asset), merge_vertices=False)
    scene = bpy.context.scene
    imported = [o for o in scene.objects if o.type == 'MESH']
    actual = box_extents([o.matrix_world @ Vector(c) for o in imported for c in o.bound_box])
    error = max(abs(actual[j][i]-expected[j][i]) for i in range(3) for j in range(2))
    if error > .002:
        raise RuntimeError(f'Native GLB axis/import bounds differ by {error} metres')
    material_before = material_signature()

    scene.render.engine = 'CYCLES'
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = True
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = args.threads
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    world = bpy.data.worlds.new('Temporary R13 actual-IFF inspection daylight')
    world.use_nodes = True
    # Broad neutral viewing illumination exposes the shaded facade's material
    # detail. This world exists only in this unsaved inspection scene.
    world.node_tree.nodes['Background'].inputs['Color'].default_value = (.65, .70, .80, 1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1.
    scene.world = world
    sunlight = bpy.data.lights.new('Temporary R13 native inspection sun', 'SUN')
    sunlight.energy = 2.4
    sunlight.angle = math.radians(7)
    sun = bpy.data.objects.new(sunlight.name, sunlight)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(29), math.radians(-24), math.radians(-37+yaw))
    camera_data = bpy.data.cameras.new('Temporary R13 native inspection camera')
    camera = bpy.data.objects.new(camera_data.name, camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = 'PERSP'
    camera_data.sensor_fit = 'VERTICAL'
    camera_data.sensor_height = 24
    camera_data.clip_start = .035
    camera_data.clip_end = 4000

    report = {
        'revision': 'R13', 'status': 'rendering',
        'validation_type': 'offline_actual_iff_decoded_geometry_render',
        'capture_origin': 'Blender renders of actual-IFF decoded GLB; not browser screenshots or game captures',
        'iff_path': str(iff_path), 'iff_sha256': iff_sha, 'iff_bytes': iff_path.stat().st_size,
        'input_glb': str(asset), 'input_glb_sha256': glb_sha, 'input_glb_bytes': asset.stat().st_size,
        'native_build_id': native['build_id'], 'native_manifest_sha256': original_hashes[str(manifest_path)],
        'configuration_sha256': original_hashes[str(project_path)], 'glb_generator': doc['asset']['generator'],
        'source_geometry_read': False, 'source_blend_saved': False, 'input_materials_modified': False,
        'material_signature_before': material_before, 'imported_meshes': len(imported),
        'native_material_snapshot': materials,
        'coordinates': {
            'glTF_to_Blender': '(glTF.x,-glTF.z,glTF.y)',
            'source_camera_to_native_Blender': '180 degree rotation around Blender Z / (x,y,z)->(-x,-y,z)',
            'game_world_yaw_degrees': yaw, 'expected_bounds_m': expected, 'imported_bounds_m': actual,
            'maximum_bounds_error_m': error, 'passed': True,
        },
        'temporary_lighting': {'world_color': [.65, .70, .80], 'world_strength': 1., 'sun_energy': 2.4, 'sun_rotation_z_degrees': -37+yaw,
                               'exposure': 0, 'saved_to_source': False, 'native_light_modified': False},
        'glass_interpretation': {
            'material_origin': 'Native specialized basket_glass DDS; source Backboard placeholders are removed during package assembly',
            'alpha_change': '10/255 to 36/255 means less transparent with unchanged neutral tint',
            'roughness_change': 'R 16/255 to 82/255 softens reflected detail; it does not prove lower total reflected energy',
            'browser_and_Blender_limit': 'Standard alpha/PBR approximation cannot reproduce every native reflection or replay pass',
        },
        'views': {}, 'game_verified': False,
        'limitations': [
            'Offline lighting and glTF materials approximate native game shaders.',
            'Replay glass, dynamic hoop movement and final game reflection response require an in-game observation.',
            'This records import/render integrity; image composition and material quality require separate visual inspection.',
        ],
    }
    for name in names:
        config = view_config(project, name)
        pos = rotation @ Vector(config['position'])
        target = rotation @ Vector(config['target'])
        camera.location = pos
        camera.rotation_euler = (target-pos).to_track_quat('-Z', 'Y').to_euler()
        fov = float(config['fov'])
        if not 5 < fov < 140:
            raise RuntimeError('Invalid camera vertical FOV')
        camera_data.lens = camera_data.sensor_height / (2*math.tan(math.radians(fov)/2))
        output = ROOT / f'validation/current-r13-{name}.png'
        scene.render.filepath = str(output)
        print('R13_NATIVE_RENDER_START '+name, flush=True)
        bpy.ops.render.render(write_still=True)
        report['views'][name] = {
            'purpose': config['purpose'], 'configuration_source': config['derivation'],
            'photographic_source_position': config['position'], 'photographic_source_target': config['target'],
            'blender_position': list(pos), 'blender_target': list(target), 'vertical_fov_degrees': fov,
            'camera_clip_m': [camera_data.clip_start, camera_data.clip_end],
            'path': str(output), 'sha256': sha_file(output), 'width': args.width, 'height': args.height,
            'samples': args.samples, 'threads': args.threads,
            'actual_iff_sha256': iff_sha, 'actual_native_glb_sha256': glb_sha,
        }
        print('R13_NATIVE_RENDER_READY '+str(output), flush=True)

    material_after = material_signature()
    if material_after != material_before:
        raise RuntimeError('Imported material signature changed during temporary render setup')
    report['material_signature_after'] = material_after
    for name, stats in original_stats.items():
        p = Path(name)
        if stats != (p.stat().st_size, p.stat().st_mtime_ns):
            raise RuntimeError('Current input changed during render: '+name)
    if sha_file(asset) != glb_sha or sha_file(iff_path) != iff_sha:
        raise RuntimeError('Actual IFF or decoded GLB changed during rendering')
    for name, digest in original_hashes.items():
        if sha_file(Path(name)) != digest:
            raise RuntimeError('Current manifest or camera configuration changed during render: '+name)
    if previous:
        if previous.get('material_signature_after') != material_after:
            raise RuntimeError('Cannot append images with a different imported material signature')
        report['views'] = {**previous.get('views', {}), **report['views']}
    report['status'] = 'passed_offline_import_and_render'
    report['completed_at_utc'] = datetime.now(timezone.utc).isoformat()
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print('R13_NATIVE_RENDER_REPORT '+str(REPORT), flush=True)


if __name__ == '__main__':
    main()
