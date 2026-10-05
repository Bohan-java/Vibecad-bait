"""Bind a shared world-XY paving atlas to existing ground meshes only.

Blender --background existing-stage.blend --python tools/refine_paving_r02.py --
  --output project/.build-staging/paving-stage.blend --report ...json
No vertices, faces, object transforms, anchors or raised environment are changed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

import bpy

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from create_scene import bind_ground_artwork, validate_scene


def mesh_fingerprint(obj):
    payload={'vertices':[list(v.co) for v in obj.data.vertices],
             'faces':[list(p.vertices) for p in obj.data.polygons],
             'matrix':[list(row) for row in obj.matrix_world]}
    return hashlib.sha256(json.dumps(payload,separators=(',',':')).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--report',default=str(ROOT/'validation'/'r02-paving-validation.json'))
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    output=Path(args.output).resolve();report_path=Path(args.report).resolve()
    if not output.is_relative_to(ROOT) or not report_path.is_relative_to(ROOT):
        raise ValueError('All outputs must remain inside the authorized project')
    if not bpy.data.filepath:
        raise RuntimeError('Load an existing saved Blender source first')
    runtime=ROOT/'.build-staging'/'paving-runtime';runtime.mkdir(parents=True,exist_ok=True)
    bpy.context.preferences.filepaths.temporary_directory=str(runtime)
    bpy.context.preferences.filepaths.file_preview_type='NONE'
    bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
    bpy.context.preferences.filepaths.save_version=0
    atlas=ROOT/'artwork'/'paving-atlas.png'
    if not atlas.is_file():raise RuntimeError('Run rasterize_artwork.mjs to generate the current atlas first')
    xmin,xmax,ymin,ymax=map(float,ET.parse(ROOT/'artwork'/'paving-context.svg').getroot().attrib['data-world-bounds'].split(','))
    original_source=str(Path(bpy.data.filepath).resolve())
    before_objects=set(bpy.data.objects.keys())
    before_meshes={obj.name:mesh_fingerprint(obj) for obj in bpy.data.objects if obj.type=='MESH'}
    anchors_before={obj.name:list(obj.matrix_world.translation) for obj in bpy.data.objects if obj.name.startswith(('rim_top_center.','backboard_front.','baseline_midpoint.'))}
    court=bpy.data.objects.get('court_surface')
    base=[obj for obj in bpy.data.objects if obj.type=='MESH' and obj.name.startswith('R02 continuous pale plaza ground')]
    # The old flat silver ribbon is already a paving mesh, not planting or
    # furniture. Bind it to the same atlas so it cannot cover the continuation
    # with a conflicting solid fill. Its geometry remains byte-for-byte intact.
    old_flat_ribbon=[obj for obj in bpy.data.objects if obj.type=='MESH' and obj.name.startswith('R02 soft grey plaza transition')]
    if court is None or len(base)!=1:raise RuntimeError('Expected one court_surface and one existing R02 plaza base')
    material=bpy.data.materials.get('Court | editable artwork')
    if material is None:raise RuntimeError('Original editable court material is missing')
    material['ground_artwork_mode']='world-paving-atlas'
    material['atlas_world_bounds']=[xmin,xmax,ymin,ymax]
    material['editable_sources']='artwork/court.svg; artwork/paving-context.svg'
    touched=[]
    for obj in [court,*base,*old_flat_ribbon]:
        slots=list(obj.data.materials)
        if material not in slots:obj.data.materials.append(material)
        material_index=list(obj.data.materials).index(material)
        uv=obj.data.uv_layers.get('PavingWorldXY') or obj.data.uv_layers.new(name='PavingWorldXY')
        obj.data.uv_layers.active=uv
        uv.active_render=True
        count=0
        for face in obj.data.polygons:
            if obj is court or face.normal.z>0.5:
                face.material_index=material_index;count+=1
            for loop_index in face.loop_indices:
                co=obj.matrix_world @ obj.data.vertices[obj.data.loops[loop_index].vertex_index].co
                uv.data[loop_index].uv=((co.x-xmin)/(xmax-xmin),(co.y-ymin)/(ymax-ymin))
        obj['ground_artwork_mode']='world-paving-atlas'
        obj['paving_atlas_world_bounds']=[xmin,xmax,ymin,ymax]
        coords=[item.uv[:] for item in uv.data]
        touched.append({'object':obj.name,'textured_faces':count,'vertices':len(obj.data.vertices),'faces':len(obj.data.polygons),
                        'uv_range':{'u':[min(v[0] for v in coords),max(v[0] for v in coords)],'v':[min(v[1] for v in coords),max(v[1] for v in coords)]}})
    bind_result=bind_ground_artwork()
    if bind_result is not True:raise RuntimeError('Shared paving atlas could not be bound')
    tex=material.node_tree.nodes.get('Editable court artwork')
    uvnode=material.node_tree.nodes.get('World paving UV map') or material.node_tree.nodes.new('ShaderNodeUVMap')
    uvnode.name='World paving UV map';uvnode.uv_map='PavingWorldXY'
    material.node_tree.links.new(uvnode.outputs['UV'],tex.inputs['Vector'])
    bpy.context.view_layer.update()
    geometry=validate_scene()
    changed_meshes=[obj.name for obj in bpy.data.objects if obj.type=='MESH' and mesh_fingerprint(obj)!=before_meshes.get(obj.name)]
    anchors_after={obj.name:list(obj.matrix_world.translation) for obj in bpy.data.objects if obj.name in anchors_before}
    checks={'source_geometry_passed':geometry['status']=='passed','all_mesh_vertices_faces_transforms_unchanged':not changed_meshes,
            'object_count_unchanged':before_objects==set(bpy.data.objects.keys()),'anchors_unchanged':anchors_before==anchors_after,
            'shared_image':tex.image.filepath==str(atlas.resolve()),'bind_return_type':type(bind_result).__name__,'bind_return_value':bind_result,'image_extension':'EXTEND',
            'court_material_count':len({p.material_index for p in court.data.polygons})}
    if not all(checks[k] for k in ('source_geometry_passed','all_mesh_vertices_faces_transforms_unchanged','object_count_unchanged','anchors_unchanged','shared_image')):
        raise RuntimeError(json.dumps(checks))
    bpy.context.scene['ground_artwork_mode']='world-paving-atlas'
    bpy.context.scene['paving_atlas_world_bounds']=[xmin,xmax,ymin,ymax]
    bpy.context.scene['artwork_source']='court.svg + paving-context.svg -> paving-atlas.png; central geometry unchanged'
    output.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    report={'status':'passed','source':original_source,'output':str(output),'scope':'ground materials and world XY UVs only',
            'world_bounds_m':[xmin,xmax,ymin,ymax],'texture':{'path':str(atlas),'width':tex.image.size[0],'height':tex.image.size[1],
            'bytes':atlas.stat().st_size,'sha256':hashlib.sha256(atlas.read_bytes()).hexdigest()},'touched':touched,'checks':checks,
            'geometry_validation':geometry,'changed_meshes':changed_meshes,
            'game_iff_status':'unverified; no game resource changed'}
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('ZGC_PAVING_READY '+json.dumps({'output':str(output),'report':str(report_path),'status':'passed','texture_bytes':atlas.stat().st_size}))


if __name__=='__main__':main()
