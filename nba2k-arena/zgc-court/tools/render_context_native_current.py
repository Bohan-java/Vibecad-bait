"""Render R12 inspection views from the GLB decoded from the actual final IFF.

Blender --background --python tools/render_context_native_current.py -- ...
This refuses R11 or source-GLB input, reads no source blend, never saves a blend,
and never alters an imported material. Lighting exists only in this disposable
inspection scene. A successful render is not a game-runtime verification.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from render_chilis_native_current import sha_file,glb_json,preview_to_blender,expected_bounds,box_extents

NAMES=('bench','left_shop','chilis','skyline_open','skyline_left','overview')
REPORT=ROOT/'validation/r12-native-visual-validation.json'


def material_signature():
    """Check that camera/render setup didn't rewrite any imported material."""
    records=[]
    for material in sorted(bpy.data.materials,key=lambda m:m.name):
        row={'name':material.name,'diffuse_color':list(material.diffuse_color),'nodes':[],'links':[]}
        if material.use_nodes:
            for node in material.node_tree.nodes:
                inputs={}
                for i,socket in enumerate(node.inputs):
                    if hasattr(socket,'default_value'):
                        value=socket.default_value
                        inputs[str(i)]=list(value) if hasattr(value,'__len__') and not isinstance(value,str) else value
                row['nodes'].append({'type':node.type,'name':node.name,'inputs':inputs,
                    'image':node.image.name if node.type=='TEX_IMAGE' and node.image else None})
            row['links']=[(l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier)
                          for l in material.node_tree.links]
        records.append(row)
    return hashlib.sha256(json.dumps(records,sort_keys=True,ensure_ascii=False,default=str).encode('utf8')).hexdigest()


def view_config(project,name):
    config=project['preview']['chilis_views']
    if name in config:
        result={**config[name],'configuration_source':'config/project.json preview.chilis_views.'+name}
        if name=='chilis':
            result['fov']=90
            result['configuration_source']+=' with preview/app.js entrance FOV override 90 degrees'
        return result
    if name=='overview':
        return {'position':[30,23,26],'target':[-12,2,0],'fov':48,
                'configuration_source':'Root-approved overview: source (30,-26,23) toward (-12,0,2), vertical FOV 48 degrees'}
    raise RuntimeError('Missing current configured inspection camera: '+name)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--expected-iff-sha',default=None)
    parser.add_argument('--views',default=','.join(NAMES))
    parser.add_argument('--width',type=int,default=1600)
    parser.add_argument('--height',type=int,default=1000)
    parser.add_argument('--samples',type=int,default=24)
    parser.add_argument('--threads',type=int,default=8)
    parser.add_argument('--append-report',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    names=args.views.split(',')
    if not names or any(n not in NAMES for n in names) or len(names)!=len(set(names)):
        raise ValueError('Unknown or duplicate R12 context view')
    if not(1<=args.samples<=512 and 1<=args.threads<=64 and 320<=args.width<=4096 and 240<=args.height<=4096):
        raise ValueError('Invalid inspection render limits')
    asset=ROOT/'public/game-preview/current.glb'
    native_manifest_path=ROOT/'public/game-preview/manifest.json'
    output_iff=ROOT/'output/arena_700_int.iff'
    delivery_path=ROOT/'validation/iff-current.json'
    native=json.loads(native_manifest_path.read_text(encoding='utf-8-sig'))
    delivery=json.loads(delivery_path.read_text(encoding='utf-8-sig'))
    project_path=ROOT/'config/project.json'
    project=json.loads(project_path.read_text(encoding='utf-8-sig'))
    if delivery.get('revision')!='R12' or native.get('kind')!='native_iff' or not native.get('iff_version','').startswith('R12'):
        raise RuntimeError('Refuse non-R12 or non-IFF native preview')
    iff_sha=sha_file(output_iff)
    if not iff_sha==delivery['output_sha256']==native['iff']['sha256']:
        raise RuntimeError('Actual IFF, delivery report and native preview hashes differ')
    if args.expected_iff_sha and args.expected_iff_sha!=iff_sha:
        raise RuntimeError('Unexpected final IFF hash')
    if not output_iff.stat().st_size==delivery['output_bytes']==native['iff']['bytes']:
        raise RuntimeError('Actual IFF size differs from current manifests')
    glb_sha=sha_file(asset)
    if glb_sha!=native['asset']['sha256'] or asset.stat().st_size!=native['asset']['bytes']:
        raise RuntimeError('Actual-IFF decoded GLB hash/size mismatch')
    doc=glb_json(asset)
    if doc.get('asset',{}).get('generator')!='ZGC final IFF decoder':
        raise RuntimeError('Source GLB cannot substitute for actual-IFF geometry')
    families={key:sum(key in node.get('name','') for node in doc['nodes'])
              for key in ('R12 Chilis ','R12 left context ','R12 right bench ','R12 skyline ')}
    if not all(families.values()):raise RuntimeError('Missing R12 family in actual native GLB: '+str(families))
    expected=expected_bounds(doc)
    original_stats={str(p):(p.stat().st_size,p.stat().st_mtime_ns)
                    for p in (asset,native_manifest_path,output_iff,delivery_path,project_path)}
    runtime=ROOT/'.build-staging/r12-native-render';runtime.mkdir(parents=True,exist_ok=True)
    bpy.context.preferences.filepaths.temporary_directory=str(runtime)
    bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
    bpy.context.preferences.filepaths.file_preview_type='NONE'
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(asset),merge_vertices=False)
    scene=bpy.context.scene
    imported=[o for o in scene.objects if o.type=='MESH']
    actual=box_extents([o.matrix_world@Vector(c) for o in imported for c in o.bound_box])
    error=max(abs(actual[j][i]-expected[j][i]) for i in range(3) for j in range(2))
    if error>.002:raise RuntimeError(f'Native GLB axis/import bounds differ by {error} metres')
    material_before=material_signature()
    scene.render.engine='CYCLES';scene.cycles.samples=args.samples;scene.cycles.use_denoising=True
    scene.render.threads_mode='FIXED';scene.render.threads=args.threads
    scene.render.resolution_x=args.width;scene.render.resolution_y=args.height;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG';scene.render.film_transparent=False
    scene.view_settings.view_transform='AgX';scene.view_settings.exposure=0;scene.view_settings.gamma=1
    world=bpy.data.worlds.new('Temporary R12 actual-IFF inspection daylight');world.use_nodes=True
    world.node_tree.nodes['Background'].inputs['Color'].default_value=(.28,.32,.38,1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value=.65;scene.world=world
    sunlight=bpy.data.lights.new('Temporary R12 native inspection sun','SUN')
    sunlight.energy=2.4;sunlight.angle=math.radians(7)
    sun=bpy.data.objects.new(sunlight.name,sunlight);scene.collection.objects.link(sun)
    sun.rotation_euler=(math.radians(29),math.radians(-24),math.radians(-37))
    camera_data=bpy.data.cameras.new('Temporary R12 native inspection camera')
    camera=bpy.data.objects.new(camera_data.name,camera_data);scene.collection.objects.link(camera);scene.camera=camera
    camera_data.type='PERSP';camera_data.sensor_fit='VERTICAL';camera_data.sensor_height=24
    camera_data.clip_start=.06;camera_data.clip_end=4000
    report={'revision':'R12','status':'rendering','validation_type':'offline_actual_iff_decoded_geometry_render',
        'capture_origin':'Blender renders of actual-IFF decoded GLB; not browser screenshots or game captures',
        'iff_path':str(output_iff),'iff_sha256':iff_sha,'iff_bytes':output_iff.stat().st_size,
        'input_glb':str(asset),'input_glb_sha256':glb_sha,'input_glb_bytes':asset.stat().st_size,
        'native_build_id':native['build_id'],'native_manifest_sha256':sha_file(native_manifest_path),
        'configuration_sha256':sha_file(project_path),'glb_generator':doc['asset']['generator'],
        'source_geometry_read':False,'source_blend_saved':False,'input_materials_modified':False,
        'material_signature_before':material_before,'imported_meshes':len(imported),'r12_families':families,
        'coordinates':{'glTF':'(sourceX,sourceZ,-sourceY)','Blender_import':'(glTF.x,-glTF.z,glTF.y)',
            'expected_bounds_m':expected,'imported_bounds_m':actual,'maximum_bounds_error_m':error,'passed':True},
        'temporary_lighting':{'world_strength':.65,'sun_energy':2.4,'exposure':0,'saved_to_source':False},
        'views':{},'game_verified':False,
        'limitations':['Lighting and glTF materials approximate the game shaders.',
                      'Bench role selection, animation, replay glass and dynamic nets require game verification.',
                      'This report records import/render checks; a human or agent must separately inspect the images.']}
    for name in names:
        config=view_config(project,name)
        pos=preview_to_blender(config['position']);target=preview_to_blender(config['target'])
        camera.location=pos;camera.rotation_euler=(target-pos).to_track_quat('-Z','Y').to_euler()
        fov=float(config['fov'])
        if not 5<fov<140:raise RuntimeError('Invalid camera vertical FOV')
        camera_data.lens=camera_data.sensor_height/(2*math.tan(math.radians(fov)/2))
        output=ROOT/f'validation/current-context-{name}.png'
        scene.render.filepath=str(output)
        print('R12_NATIVE_RENDER_START '+name,flush=True)
        bpy.ops.render.render(write_still=True)
        report['views'][name]={'configuration_source':config['configuration_source'],
            'preview_position':config['position'],'preview_target':config['target'],
            'blender_position':list(pos),'blender_target':list(target),'vertical_fov_degrees':fov,
            'camera_clip_m':[camera_data.clip_start,camera_data.clip_end],
            'path':str(output),'sha256':sha_file(output),'width':args.width,'height':args.height,
            'actual_iff_sha256':iff_sha,'actual_native_glb_sha256':glb_sha}
        print('R12_NATIVE_RENDER_READY '+str(output),flush=True)
    material_after=material_signature()
    if material_after!=material_before:raise RuntimeError('Imported material changed during render setup')
    report['material_signature_after']=material_after
    for name,stat in original_stats.items():
        p=Path(name)
        if stat!=(p.stat().st_size,p.stat().st_mtime_ns):raise RuntimeError('Current input changed during render: '+name)
    if sha_file(asset)!=glb_sha:raise RuntimeError('Native GLB changed during render')
    if args.append_report and REPORT.exists():
        previous=json.loads(REPORT.read_text(encoding='utf-8-sig'))
        if previous.get('iff_sha256')!=iff_sha or previous.get('input_glb_sha256')!=glb_sha:
            raise RuntimeError('Cannot mix images from different native builds')
        report['views']={**previous.get('views',{}),**report['views']}
    report['status']='passed_offline_import_and_render'
    report['completed_at_utc']=datetime.now(timezone.utc).isoformat()
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('R12_NATIVE_RENDER_REPORT '+str(REPORT),flush=True)


if __name__=='__main__':main()
