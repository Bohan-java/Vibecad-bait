"""Export the OPEN saved .blend to GLB; never build replacement geometry here.

Blender --background source/scene.blend --python tools/export_scene.py --
  --output absolute/path.glb --project absolute/config/project.json
The preview builder publishes this output atomically after export succeeds.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
import bpy

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from create_scene import bind_ground_artwork, validate_scene


def main():
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--project',default=str(ROOT/'config'/'project.json'))
    options=parser.parse_args(argv)
    if not bpy.data.filepath or Path(bpy.data.filepath).suffix.lower()!='.blend':
        raise RuntimeError('Open source/scene.blend before exporting; preview requires saved Blender source.')
    source=Path(bpy.data.filepath).resolve()
    output=Path(options.output).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    project_path=Path(options.project)
    project=json.loads(project_path.read_text(encoding='utf-8-sig')) if project_path.is_file() else {}
    # External source textures refresh on each build, including packed snapshots.
    artwork=ROOT/'artwork'/'court.png'
    artwork_loaded=bind_ground_artwork(artwork)
    bpy.context.view_layer.update()
    report=validate_scene()
    if report['status']!='passed':
        raise RuntimeError('Saved source geometry validation failed: '+json.dumps(report))
    scene=bpy.context.scene
    scene['build_id']=os.environ.get('ZGC_BUILD_ID','manual')
    scene['source_version']=os.environ.get('ZGC_SOURCE_VERSION',str(project.get('source_version',scene.get('source_version','R01'))))
    scene['source_blend_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    scene['geometry_validation']='passed: source geometry only; game integration unverified'
    scene['artwork_loaded']=artwork_loaded
    # Selection is an explicit export allowlist: hide_render is not a reliable
    # glTF filter and future measurement meshes must not leak into the asset.
    helper_groups={'preview_helpers','lights'}
    helper_objects={obj.as_pointer() for name in helper_groups if (collection:=bpy.data.collections.get(name)) for obj in collection.all_objects}
    def is_helper(obj):
        if obj.type in {'CAMERA','LIGHT'}:
            return True
        current=obj
        while current:
            if current.name in helper_groups or current.as_pointer() in helper_objects:
                return True
            current=current.parent
        return False
    bpy.ops.object.select_all(action='DESELECT')
    excluded=[]
    for obj in scene.objects:
        if is_helper(obj):
            excluded.append(obj.name)
        else:
            obj.select_set(True)
    kwargs=dict(filepath=str(output),export_format='GLB',export_yup=True,
                export_texcoords=True,export_normals=True,export_materials='EXPORT',
                export_extras=True,export_cameras=False,export_lights=False,
                use_selection=True,
                export_animations=False,export_apply=True,
                export_draco_mesh_compression_enable=False,check_existing=False)
    properties=set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    kwargs={key:value for key,value in kwargs.items() if key in properties}
    result=bpy.ops.export_scene.gltf(**kwargs)
    if 'FINISHED' not in result or not output.is_file() or output.stat().st_size<100:
        raise RuntimeError('Blender GLB export did not produce a complete file')
    with output.open('rb') as stream:
        if stream.read(4)!=b'glTF':
            raise RuntimeError('Output header is not a glTF binary')
    print('ZGC_EXPORT_READY '+json.dumps({'output':str(output),'bytes':output.stat().st_size,'source':str(source),'build_id':scene['build_id'],'source_version':scene['source_version'],'geometry_validation':report['status'],'artwork_loaded':artwork_loaded,'excluded_helper_objects':excluded,'game_status':'unverified'}))


if __name__=='__main__':
    main()
