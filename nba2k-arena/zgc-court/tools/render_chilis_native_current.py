"""Render Chili's views from the GLB decoded from the actual current game IFF.

Run with Blender --background --python tools/render_chilis_native_current.py.
This never opens source/scene.blend and never rebuilds source geometry. The
GLB's bytes must match the native-IFF preview manifest. Scene import and render
lighting are disposable; no .blend is saved. Game shaders remain approximated.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from datetime import datetime, timezone
import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
VIEW_NAMES={'entry':'chilis','terrace':'chilis_terrace','corner':'chilis_walk','relationship':None}


def sha_file(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def glb_json(path):
    with path.open('rb') as f:
        magic,version,total=struct.unpack('<4sII',f.read(12))
        if magic!=b'glTF' or version!=2 or total!=path.stat().st_size:
            raise RuntimeError('Invalid current native GLB header/size')
        length,kind=struct.unpack('<II',f.read(8))
        if kind!=0x4e4f534a:raise RuntimeError('Missing GLB JSON chunk')
        return json.loads(f.read(length))


def preview_to_blender(v):
    # The glTF importer rotates Y-up glTF into Blender's Z-up coordinates.
    # Preview (source X, source Z, -source Y) therefore returns source X/Y/Z.
    x,y,z=v
    return Vector((x,-z,y))


def box_extents(points):
    return [[min(p[i] for p in points) for i in range(3)],
            [max(p[i] for p in points) for i in range(3)]]


def expected_bounds(doc):
    points=[]
    for node in doc['nodes']:
        if 'mesh' not in node:continue
        if any(k in node for k in ('matrix','translation','rotation','scale')):
            raise RuntimeError('Decoder changed: nonidentity GLB node transforms need an explicit audit')
        for prim in doc['meshes'][node['mesh']]['primitives']:
            acc=doc['accessors'][prim['attributes']['POSITION']]
            if 'min' not in acc or 'max' not in acc:
                raise RuntimeError('Cannot verify import coordinates without native position bounds')
            points.extend(preview_to_blender(v) for v in (acc['min'],acc['max']))
    return box_extents(points)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--expect-revision',default='R11')
    parser.add_argument('--expected-iff-sha',default=None)
    parser.add_argument('--views',default='entry,terrace,corner,relationship')
    parser.add_argument('--width',type=int,default=1600)
    parser.add_argument('--height',type=int,default=1000)
    parser.add_argument('--samples',type=int,default=24)
    parser.add_argument('--threads',type=int,default=8)
    parser.add_argument('--entry-fov',type=float,default=None)
    parser.add_argument('--append-report',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    names=args.views.split(',')
    if not names or any(n not in VIEW_NAMES for n in names):raise ValueError('Unknown Chilis view')
    path=ROOT/'public/game-preview/current.glb'
    manifest_path=ROOT/'public/game-preview/manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    project=json.loads((ROOT/'config/project.json').read_text(encoding='utf-8-sig'))
    if manifest.get('kind')!='native_iff':raise RuntimeError('Input is not an actual-IFF native preview')
    if args.expect_revision not in manifest.get('iff_version',''):
        raise RuntimeError('Refusing earlier IFF preview: '+str(manifest.get('iff_version')))
    if args.expected_iff_sha and manifest['iff']['sha256']!=args.expected_iff_sha:
        raise RuntimeError('The current native preview is from a different IFF')
    glb_sha=sha_file(path)
    if glb_sha!=manifest['asset']['sha256'] or path.stat().st_size!=manifest['asset']['bytes']:
        raise RuntimeError('GLB bytes do not match actual-IFF manifest')
    doc=glb_json(path)
    if doc.get('asset',{}).get('generator')!='ZGC final IFF decoder':
        raise RuntimeError('Only actual IFF-decoder output is accepted')
    named_chilis=[n['name'] for n in doc['nodes'] if 'R11' in n.get('name','') and 'Chilis' in n.get('name','')]
    if args.expect_revision=='R11' and not named_chilis:
        raise RuntimeError('No R11 Chili geometry in actual native GLB')
    expected=expected_bounds(doc)
    runtime=ROOT/'.build-staging/chilis-native-render';runtime.mkdir(parents=True,exist_ok=True)
    bpy.context.preferences.filepaths.temporary_directory=str(runtime)
    bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
    bpy.context.preferences.filepaths.file_preview_type='NONE'
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path),merge_vertices=False)
    scene=bpy.context.scene
    imported=[obj for obj in scene.objects if obj.type=='MESH']
    actual=box_extents([obj.matrix_world@Vector(corner) for obj in imported for corner in obj.bound_box])
    coordinate_error=max(abs(actual[j][i]-expected[j][i]) for i in range(3) for j in range(2))
    if coordinate_error>.002:
        raise RuntimeError(f'glTF to Blender axis audit failed: bounds differ by {coordinate_error}m')
    # Preserve every imported material/mesh. Add only temporary viewing light.
    scene.render.engine='CYCLES';scene.cycles.samples=args.samples
    scene.cycles.use_denoising=True
    scene.render.threads_mode='FIXED';scene.render.threads=args.threads
    scene.render.resolution_x=args.width;scene.render.resolution_y=args.height
    scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
    scene.render.film_transparent=False
    scene.view_settings.view_transform='AgX';scene.view_settings.exposure=0;scene.view_settings.gamma=1
    world=bpy.data.worlds.new('Temporary neutral daylight for actual-IFF inspection');world.use_nodes=True
    world.node_tree.nodes['Background'].inputs['Color'].default_value=(.28,.32,.38,1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value=.65
    scene.world=world
    light_data=bpy.data.lights.new('Temporary native inspection sun','SUN')
    light_data.energy=2.4;light_data.angle=math.radians(7)
    light_obj=bpy.data.objects.new(light_data.name,light_data);scene.collection.objects.link(light_obj)
    light_obj.rotation_euler=(math.radians(29),math.radians(-24),math.radians(-37))
    camera_data=bpy.data.cameras.new('Temporary native inspection camera')
    camera=bpy.data.objects.new(camera_data.name,camera_data);scene.collection.objects.link(camera)
    scene.camera=camera
    camera_data.type='PERSP';camera_data.sensor_fit='VERTICAL';camera_data.sensor_height=24
    camera_data.clip_start=.06;camera_data.clip_end=600
    report={
        'revision':args.expect_revision,'validation_type':'offline_actual_iff_decoded_geometry_render',
        'input_file':str(path),'input_sha256':glb_sha,'input_bytes':path.stat().st_size,
        'iff_sha256':manifest['iff']['sha256'],'iff_bytes':manifest['iff']['bytes'],
        'native_build_id':manifest['build_id'],'manifest_sha256':sha_file(manifest_path),
        'source_geometry_read':False,'source_blend_saved':False,'input_materials_modified':False,
        'glb_generator':doc['asset']['generator'],'imported_meshes':len(imported),
        'r11_chilis_node_count':len(named_chilis),
        'coordinates':{'glTF':'(sourceX,sourceZ,-sourceY)',
                       'Blender_import':'(glTF.x,-glTF.z,glTF.y) = source X/Y/Z',
                       'expected_bounds_m':expected,'imported_bounds_m':actual,
                       'maximum_bounds_error_m':coordinate_error,'passed':True},
        'temporary_lighting':{'world_strength':.65,'sun_energy':2.4,'exposure':0},
        'capture_origin':'Blender offline render of actual-IFF decoded GLB, not a browser screenshot',
        'browser_automation_status':'Browser automatic capture unavailable this round because its plugin service file is missing; this does not claim the webpage itself failed.',
        'limitations':['Offline Blender lighting and glTF materials approximate the game.',
                       'No evidence here establishes replay glass or game animation correctness.',
                       'This test reads the decoded IFF GLB, not source scene.blend.'],
        'views':{},'game_verified':False,
    }
    for name in names:
        if name=='relationship':
            a=Vector(project['preview']['chilis_views']['chilis']['target'])
            b=Vector(project['preview']['chilis_views']['chilis_terrace']['target'])
            middle=(a+b)*.5
            config={'position':list(middle+Vector((12,8,14))),
                    'target':list(middle),'fov':55,
                    'derivation':'Elevated outside-corner view derived from both configured facade targets'}
        else:
            config=dict(project['preview']['chilis_views'][VIEW_NAMES[name]])
        if name=='entry' and args.entry_fov is not None:
            config['fov']=args.entry_fov
        pos=preview_to_blender(config['position']);target=preview_to_blender(config['target'])
        camera.location=pos
        camera.rotation_euler=(target-pos).to_track_quat('-Z','Y').to_euler()
        camera_data.lens=camera_data.sensor_height/(2*math.tan(math.radians(config['fov'])/2))
        output=ROOT/f'validation/current-chilis-native-{name}.png'
        scene.render.filepath=str(output)
        print('ZGC_NATIVE_RENDER_START '+name,flush=True)
        bpy.ops.render.render(write_still=True)
        report['views'][name]={'preview_position':config['position'],'preview_target':config['target'],
                             'blender_position':list(pos),'blender_target':list(target),
                             'vertical_fov_degrees':config['fov'],'path':str(output),
                             'sha256':sha_file(output),'width':args.width,'height':args.height}
        if name=='entry' and args.entry_fov is not None:
            report['views'][name]['camera_override']={'config_vertical_fov':project['preview']['chilis_views']['chilis']['fov'],
                'override_vertical_fov':args.entry_fov,'reason':'Widen frame to include both facade columns and EST.1975; match preview app override without changing source/export config.'}
        print('ZGC_NATIVE_RENDER_READY '+str(output),flush=True)
    if sha_file(path)!=glb_sha or sha_file(manifest_path)!=report['manifest_sha256']:
        raise RuntimeError('Native input changed during the render')
    report['completed_at_utc']=datetime.now(timezone.utc).isoformat()
    report['status']='passed_offline_import_and_render'
    target=ROOT/'validation/current-chilis-native-render.json'
    if args.append_report and target.exists():
        previous=json.loads(target.read_text(encoding='utf-8-sig'))
        if previous.get('input_sha256')!=glb_sha or previous.get('iff_sha256')!=manifest['iff']['sha256']:
            raise RuntimeError('Refusing to merge views from a different native asset')
        report['views']={**previous.get('views',{}),**report['views']}
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('ZGC_NATIVE_RENDER_REPORT '+str(target),flush=True)


if __name__=='__main__':main()
