"""Bake night-light spherical harmonics at the game's light probes (Blender + Cycles).

Run from nba2k-arena/zgc-court (Blender 5.x, also works on 4.x):

  blender -b source/scene.blend -P bake/bake_probes.py -- --out bake/output/probe_sh.ndjson

Optional: --limit 3 (quick test), --res 128, --samples 128, --groups a_signs,chilis

What it does
- Never saves the .blend. Everything below happens in memory.
- Turns the world black and disables every existing light, camera-only helper
  and any emission already in the materials, so ONLY the night lights in
  bake/bake_lights.json contribute (the game keeps its own moonlit ambient;
  this bake is added on top of it).
- For every probe in bake/probes_3_0_2.json and every light group, renders one
  equirectangular panorama (2*res x res) from the probe position and projects the radiance
  onto 9 real SH coefficients per RGB channel, expressed in GAME world axes
  (x = -Blender Y, y = Blender Z (up), z = -Blender X) with the usual order
  [Y00, Y1-1(y), Y10(z), Y11(x), Y2-2(xy), Y2-1(yz), Y20(3z^2-1), Y21(xz), Y22(x^2-y^2)].
  The game probes store L1 as (Y, Z, X), confirmed by an in-game test.
- Appends one JSON line per probe to --out, flushing after each probe, so an
  interrupted bake can simply be started again with the same command; already
  finished probes are skipped.

One panorama per group instead of six cube faces: Cycles' per-render overhead
dominates at these sizes, so a 256x128 panorama costs about as much as one 16x16
face while giving ~20x more samples (small bright emitters such as the A signs
were noticeably noisy and edge-biased with 16x16 faces). The pixel -> direction
mapping was checked against cube-face renders and against where the floodlight
and A signs appear in the image (camera rotated to look along +Y with +Z up:
centre column = +Y, columns increase toward +X, rows bottom-up = latitude
-90..+90 degrees).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent   # nba2k-arena/zgc-court
HELPER_COLLECTIONS = ('preview_helpers', 'lights')   # same allowlist logic as tools/export_scene.py


def parse():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--out', default=str(HERE / 'output' / 'probe_sh.ndjson'))
    p.add_argument('--probes', default=str(HERE / 'probes_3_0_2.json'))
    p.add_argument('--lights', default=str(HERE / 'bake_lights.json'))
    p.add_argument('--res', type=int, default=128, help='panorama height in pixels (width is 2x)')
    p.add_argument('--samples', type=int, default=128)
    p.add_argument('--limit', type=int, default=0, help='bake only the first N probes (test run)')
    p.add_argument('--groups', default='', help='comma separated subset of light groups')
    p.add_argument('--cpu', action='store_true', help='force CPU rendering')
    return p.parse_args(argv)


def setup_gpu(force_cpu):
    scene = bpy.context.scene
    if force_cpu:
        scene.cycles.device = 'CPU'
        return 'CPU'
    prefs = bpy.context.preferences.addons['cycles'].preferences
    for kind in ('OPTIX', 'CUDA', 'HIP', 'METAL', 'ONEAPI'):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
            devices = [d for d in prefs.devices if d.type != 'CPU']
            if devices:
                for d in prefs.devices:
                    d.use = True
                scene.cycles.device = 'GPU'
                return kind + ': ' + ', '.join(d.name for d in devices)
        except Exception:
            continue
    scene.cycles.device = 'CPU'
    return 'CPU (no GPU backend found)'


def relink_images():
    """scene.blend stores absolute paths from the authoring PC (E:/CodexData/2karena/zgc-court/...).
    Missing images render magenta in Cycles and would tint every bounce, so re-point
    them at the same relative path inside this checkout."""
    fixed, missing = [], []
    for img in bpy.data.images:
        if img.source != 'FILE' or img.packed_file is not None or not img.filepath:
            continue
        current = Path(bpy.path.abspath(img.filepath))
        if current.exists():
            continue
        parts = img.filepath.replace('\\', '/').split('/')
        candidate = None
        for marker in ('zgc-court',):
            if marker in parts:
                candidate = PROJECT.joinpath(*parts[parts.index(marker) + 1:])
        if candidate is not None and candidate.exists():
            img.filepath = str(candidate)
            img.reload()
            fixed.append(img.name)
        else:
            missing.append(img.filepath)
    print(f'[bake] relinked {len(fixed)} images', flush=True)
    if missing:
        raise RuntimeError('Images still missing (would render magenta): ' + ', '.join(missing))


def setup_scene(res, samples):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.max_bounces = 6
    scene.render.use_persistent_data = True
    scene.render.resolution_x, scene.render.resolution_y = 2 * res, res
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = 'OPEN_EXR'
    scene.render.image_settings.color_depth = '32'
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    world = bpy.data.worlds.new('bake_black_world')
    world.use_nodes = True
    bg = world.node_tree.nodes.get('Background')
    bg.inputs['Color'].default_value = (0, 0, 0, 1)
    bg.inputs['Strength'].default_value = 0.0
    scene.world = world
    # Disable existing lights/cameras, preview helpers (reference photo planes etc.)
    # and any emission already in materials.
    helpers = set()
    for name in HELPER_COLLECTIONS:
        collection = bpy.data.collections.get(name)
        if collection:
            helpers.update(o.name for o in collection.all_objects)
    hidden = 0
    for obj in scene.objects:
        if obj.type in {'LIGHT', 'CAMERA'} or obj.name in helpers:
            obj.hide_render = True
            hidden += 1
    print(f'[bake] hidden {hidden} lights/cameras/helpers', flush=True)
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        for node in mat.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED' and 'Emission Strength' in node.inputs:
                node.inputs['Emission Strength'].default_value = 0.0
            if node.type == 'EMISSION':
                node.inputs['Strength'].default_value = 0.0
    cam_data = bpy.data.cameras.new('bake_probe_camera')
    cam_data.type = 'PANO'
    cam_data.panorama_type = 'EQUIRECTANGULAR'
    cam_data.clip_start = 0.01
    cam_data.clip_end = 5000.0
    cam = bpy.data.objects.new('bake_probe_camera', cam_data)
    cam.rotation_euler = (math.pi / 2, 0.0, 0.0)   # look along +Y, +Z up
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def emission_material(name, colour, strength):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    out = nodes.new('ShaderNodeOutputMaterial')
    em = nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = (*colour, 1.0)
    em.inputs['Strength'].default_value = strength
    mat.node_tree.links.new(em.outputs['Emission'], out.inputs['Surface'])
    return mat, em


def setup_lights(spec, wanted):
    """Returns {group: [(emission node, strength) ...], [(light object, power) ...]}."""
    scene = bpy.context.scene
    groups = {}
    missing = []
    for group, entry in spec['groups'].items():
        if wanted and group not in wanted:
            continue
        nodes, lights = [], []
        for k, emitter in enumerate(entry['emitters']):
            mat, node = emission_material(f'bake_{group}_{k}', emitter['colour'], emitter['strength'])
            nodes.append((node, emitter['strength']))
            for name in emitter['objects']:
                obj = bpy.data.objects.get(name)
                if obj is None or obj.type not in {'MESH', 'CURVE', 'FONT', 'SURFACE'}:
                    missing.append(name)
                    continue
                obj.hide_render = False
                obj.data.materials.clear()
                obj.data.materials.append(mat)
        for light in entry['lights']:
            data = bpy.data.lights.new(light['name'], light['type'])
            data.color = light['colour']
            data.energy = light['power']
            if light['type'] == 'AREA':
                data.shape = 'RECTANGLE'
                data.size = light['size_x']
                data.size_y = light['size_y']
            if light['type'] == 'SPOT':
                data.spot_size = math.radians(light['spot_size_deg'])
                data.spot_blend = 0.4
            obj = bpy.data.objects.new(light['name'], data)
            obj.location = light['location']
            if light.get('aim') is not None:
                direction = Vector(light['aim']) - Vector(light['location'])
                obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
            scene.collection.objects.link(obj)
            lights.append((obj, light['power']))
        groups[group] = (nodes, lights)
    if missing:
        raise RuntimeError('Light source objects not found in the .blend: ' + ', '.join(sorted(set(missing))))
    return groups


def enable_group(groups, active):
    for group, (nodes, lights) in groups.items():
        on = group == active
        for node, strength in nodes:
            node.inputs['Strength'].default_value = strength if on else 0.0
        for obj, power in lights:
            obj.hide_render = not on


def pano_rays(res):
    """Blender-axis unit rays and solid angles for the 2*res x res equirectangular image
    (pixel rows bottom-up, as Blender stores them)."""
    width, height = 2 * res, res
    lon = ((np.arange(width) + 0.5) / width - 0.5) * 2.0 * math.pi
    lat = ((np.arange(height) + 0.5) / height - 0.5) * math.pi
    lon, lat = np.meshgrid(lon, lat)
    lon, lat = lon.ravel(), lat.ravel()
    rays = np.stack([np.cos(lat) * np.sin(lon), np.cos(lat) * np.cos(lon), np.sin(lat)], axis=1)
    solid = (2.0 * math.pi / width) * (math.pi / height) * np.cos(lat)
    return rays, solid


def sh_basis(d):
    """d: N x 3 GAME-axis unit vectors -> N x 9 real SH basis values."""
    x, y, z = d[:, 0], d[:, 1], d[:, 2]
    return np.stack([
        np.full_like(x, 0.282095),
        0.488603 * y, 0.488603 * z, 0.488603 * x,
        1.092548 * x * y, 1.092548 * y * z, 0.315392 * (3 * z * z - 1),
        1.092548 * x * z, 0.546274 * (x * x - y * y)], axis=1)


def render_pano(path):
    bpy.context.view_layer.update()
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path, check_existing=False)
    px = np.array(img.pixels[:], dtype=np.float64).reshape(-1, img.channels)[:, :3]
    bpy.data.images.remove(img)
    return px


def main():
    args = parse()
    probes = json.loads(Path(args.probes).read_text(encoding='utf8'))['probes']
    spec = json.loads(Path(args.lights).read_text(encoding='utf8'))
    wanted = {g for g in args.groups.split(',') if g}
    if args.limit:
        probes = probes[:args.limit]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.read_text(encoding='utf8').splitlines():
            if line.strip():
                row = json.loads(line)
                done.add((row['sector'], row['id']))
    relink_images()
    device = setup_gpu(args.cpu)
    cam = setup_scene(args.res, args.samples)
    groups = setup_lights(spec, wanted)
    rays, solid = pano_rays(args.res)
    assert abs(solid.sum() - 4 * math.pi) < 0.01 * 4 * math.pi
    basis = sh_basis(np.stack([-rays[:, 1], rays[:, 2], -rays[:, 0]], axis=1))   # game axes
    tmp = tempfile.mkdtemp(prefix='zgc_bake_')
    pano_path = os.path.join(tmp, 'pano.exr')
    print(f'[bake] device {device}; {len(probes)} probes, {len(done)} already done; groups {list(groups)}', flush=True)
    start = time.time()
    with out.open('a', encoding='utf8') as stream:
        for n, probe in enumerate(probes):
            if (probe['sector'], probe['id']) in done:
                continue
            cam.location = probe['blender_m']
            result = {}
            for group in groups:
                enable_group(groups, group)
                radiance = render_pano(pano_path)
                coeffs = basis.T @ (radiance * solid[:, None])
                result[group] = np.round(coeffs, 7).tolist()
            stream.write(json.dumps({'sector': probe['sector'], 'id': probe['id'], 'world_cm': probe['world_cm'],
                                     'sh_rgb_9x3': result}) + '\n')
            stream.flush()
            elapsed = time.time() - start
            print(f'[bake] probe {n + 1}/{len(probes)} id {probe["id"]} done ({elapsed / 60:.1f} min)', flush=True)
    meta = {'blender': bpy.app.version_string, 'device': device, 'camera': 'equirectangular', 'res': args.res, 'samples': args.samples,
            'groups': list(groups), 'sh_axes': 'game world x=-Blender Y, y=Blender Z (up), z=-Blender X',
            'sh_order': ['Y00', 'Y1-1(y)', 'Y10(z)', 'Y11(x)', 'Y2-2(xy)', 'Y2-1(yz)', 'Y20(3z^2-1)', 'Y21(xz)', 'Y22(x^2-y^2)'],
            'quantity': 'radiance SH coefficients (integral of radiance * basis over the sphere), linear RGB',
            'lights_spec': spec}
    Path(str(out) + '.meta.json').write_text(json.dumps(meta, indent=1), encoding='utf8')
    print('[bake] finished', flush=True)


if __name__ == '__main__':
    main()
