"""Bake night light onto the court floor (phase 2 surface bake, Blender + Cycles).

Run from nba2k-arena/zgc-court:

  blender -b source/scene.blend -P bake/bake_surface.py -- --out bake/output/surface

Uses the same light setup as bake_probes.py (only the night lights in
bake_lights.json, black world, existing emission and lights off). A white
receiver plane is laid 0.5 cm above the court floor (world x +-1162 cm,
z +-1833 cm, i.e. the whole court model zgc_r03:part-0772) and baked:

  <out>_<group>.npy   DIFFUSE direct+indirect, no colour: the light arriving
                      on the floor from that group, shadows included (H x W x 3)
  <out>_ao.npy        ambient occlusion within --ao-distance (H x W)

Image rows run along world z (row 0 = z -1833), columns along world x
(column 0 = x -1162). Never saves the .blend.

--region x0,x1,z0,z1,y (world cm) bakes another floor patch instead, e.g. the
Chilis entry stone: --region -130,970,1890,2102,2 --out bake/output/surface_entry

--wall axis,at,a0,a1,y0,y1,facing (world cm) bakes a vertical receiver instead:
the plane world_<axis> = at, spanning the other horizontal axis a0..a1 and world
y y0..y1, facing +1/-1 along <axis>, lifted 0.5 cm toward the facing side. Rows
run along world y (row 0 = y0), columns along the other axis (column 0 = a0).
e.g. the Chilis facade: --wall z,2086,-1480,1640,0,470,-1
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import bpy
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
argv, sys.argv = sys.argv, sys.argv[:1]
import bake_probes as bp   # noqa: E402
sys.argv = argv

X_HALF_CM, Z_HALF_CM = 1162.0, 1833.0
LIFT_M = 0.005


def parse():
    a = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--out', default=str(HERE / 'output' / 'surface'))
    p.add_argument('--width', type=int, default=1024, help='pixels along world x; height follows the court aspect')
    p.add_argument('--samples', type=int, default=256)
    p.add_argument('--ao-distance', type=float, default=1.5, help='metres')
    p.add_argument('--groups', default='')
    p.add_argument('--cpu', action='store_true')
    p.add_argument('--region', default='', help='x0,x1,z0,z1,y world cm (default: the court)')
    p.add_argument('--wall', default='', help='axis,at,a0,a1,y0,y1,facing (vertical receiver)')
    return p.parse_args(a)


def _corners(region, wall):
    """Four receiver corners in world cm, (u, v) per corner, and the world facing normal."""
    if wall:
        axis, at, a0, a1, y0, y1, facing = wall
        at = float(at) + float(facing) * LIFT_M * 100
        out = []
        for sa, sy in [(0, 0), (1, 0), (1, 1), (0, 1)]:
            a, y = (a1 if sa else a0), (y1 if sy else y0)
            out.append(((at, y, a) if axis == 'x' else (a, y, at), (sa, sy)))
        normal = (float(facing), 0.0, 0.0) if axis == 'x' else (0.0, 0.0, float(facing))
        return out, normal
    x0, x1, z0, z1, y = region
    return [((x1 if sx else x0, y + LIFT_M * 100, z1 if sz else z0), (sx, sz))
            for sx, sz in [(0, 0), (1, 0), (1, 1), (0, 1)]], (0.0, 1.0, 0.0)


def receiver(width, height, region, wall=None):
    # Blender X = -world_z/100, Y = -world_x/100, Z = world_y/100
    corners, (nx, ny, nz) = _corners(region, wall)
    verts = [(-z / 100, -x / 100, y / 100) for (x, y, z), _ in corners]
    uvs = [uv for _, uv in corners]
    mesh = bpy.data.meshes.new('bake_court_receiver')
    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    mesh.update()
    want = (-nz, -nx, ny)
    if sum(a * b for a, b in zip(mesh.polygons[0].normal, want)) < 0:
        mesh.flip_normals()
    uv = mesh.uv_layers.new(name='bake')
    for loop in mesh.loops:
        uv.data[loop.index].uv = uvs[loop.vertex_index]
    obj = bpy.data.objects.new('bake_court_receiver', mesh)
    bpy.context.scene.collection.objects.link(obj)
    mat = bpy.data.materials.new('bake_court_receiver')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (1, 1, 1, 1)
    bsdf.inputs['Roughness'].default_value = 1.0
    image = bpy.data.images.new('bake_court', width, height, float_buffer=True, alpha=False)
    node = nodes.new('ShaderNodeTexImage')
    node.image = image
    nodes.active = node
    mesh.materials.append(mat)
    return obj, image


def bake(obj, image, kind):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if kind == 'AO':
        bpy.ops.object.bake(type='AO', margin=4, use_clear=True)
    else:
        bpy.ops.object.bake(type='DIFFUSE', pass_filter={'DIRECT', 'INDIRECT'}, margin=4, use_clear=True)
    px = np.array(image.pixels[:], dtype=np.float32).reshape(image.size[1], image.size[0], 4)
    return px


def main():
    args = parse()
    spec = json.loads((HERE / 'bake_lights.json').read_text(encoding='utf8'))
    wanted = {g for g in args.groups.split(',') if g}
    region = [float(v) for v in args.region.split(',')] if args.region else [-X_HALF_CM, X_HALF_CM, -Z_HALF_CM, Z_HALF_CM, 0.0]
    wall = None
    if args.wall:
        f = args.wall.split(',')
        wall = [f[0]] + [float(v) for v in f[1:]]
    width = args.width
    if wall:
        height = max(4, int(round(width * (wall[5] - wall[4]) / (wall[3] - wall[2]))))
    else:
        height = max(4, int(round(width * (region[3] - region[2]) / (region[1] - region[0]))))
    bp.relink_images()
    device = bp.setup_gpu(args.cpu)
    bp.setup_scene(16, args.samples)
    scene = bpy.context.scene
    scene.cycles.samples = args.samples
    scene.world.light_settings.distance = args.ao_distance
    groups = bp.setup_lights(spec, wanted)
    obj, image = receiver(width, height, region, wall)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f'[surface] device {device}; {width}x{height}; groups {list(groups)}', flush=True)
    start = time.time()
    for group in groups:
        bp.enable_group(groups, group)
        px = bake(obj, image, 'DIFFUSE')
        np.save(f'{out}_{group}.npy', px[:, :, :3])
        print(f'[surface] {group} done ({(time.time() - start) / 60:.1f} min), max {px[:, :, :3].max():.4g}', flush=True)
    px = bake(obj, image, 'AO')
    np.save(f'{out}_ao.npy', px[:, :, 0])
    meta = {'blender': bpy.app.version_string, 'device': device, 'width': width, 'height': height,
            'samples': args.samples, 'ao_distance_m': args.ao_distance, 'groups': list(groups),
            'region_cm': region if not wall else None, 'wall': wall,
            'mapping': ('row 0 = world y0, column 0 = a0; receiver 0.5 cm in front' if wall
                        else 'row 0 = world z0, column 0 = world x0; receiver 0.5 cm above y')}
    Path(f'{out}.meta.json').write_text(json.dumps(meta, indent=1), encoding='utf8')
    print(f'[surface] finished ({(time.time() - start) / 60:.1f} min)', flush=True)


if __name__ == '__main__':
    main()
