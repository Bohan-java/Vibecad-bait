"""Black individual bench chairs aligned to r12_seating native role anchors.

This is a user-requested practical addition, not a claimed object in the site
photographs.  All seats share a straight right-side row; no source object moves.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
import bmesh
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from r12_seating import seat_layout, SEAT_Y, SPACING, CENTRE_GAP_HALF
import refine_architecture_r02 as primitive
import refine_details_r03 as finish

PREFIX = 'R12 right bench '


def rounded_prism(batch, center, size, radius=.025, corner_steps=5, back=False):
    """Smooth outline with flat fabric faces and bevelled edge section."""
    cx, cy, cz = center
    width, depth, thickness = size
    corners = [(-width/2+radius, -depth/2+radius, math.pi),
               ( width/2-radius, -depth/2+radius, math.pi*1.5),
               ( width/2-radius,  depth/2-radius, 0.),
               (-width/2+radius,  depth/2-radius, math.pi*.5)]
    perimeter = []
    for u, v, angle in corners:
        for j in range(corner_steps+1):
            a = angle + math.pi*.5*j/corner_steps
            perimeter.append((u+radius*math.cos(a), v+radius*math.sin(a)))
    vertices=[]
    for z, scale in ((-thickness/2,.96),(-thickness*.28,1.),(thickness*.28,1.),(thickness/2,.96)):
        for u, v in perimeter:
            if back:
                # A padded vertical back with a modest rearward rake.
                vertices.append((cx+u*scale, cy+z+v*.10, cz+v*scale))
            else:
                vertices.append((cx+u*scale,cy+v*scale,cz+z))
    count=len(perimeter)
    faces=[tuple(reversed(range(count))),tuple(range(count*3,count*4))]
    for ring in range(3):
        for i in range(count):
            j=(i+1)%count
            faces.append((ring*count+i,ring*count+j,(ring+1)*count+j,(ring+1)*count+i))
    batch.add(vertices,faces)


def build_bench_geometry():
    if any(obj.name.startswith(PREFIX) for obj in bpy.data.objects):
        raise RuntimeError('R12 seating already exists; do not append duplicate benches')
    materials = {
        'frames': finish.pbr('R12 bench | satin black steel', '202323', .58, .48),
        'pads': finish.pbr('R12 bench | black seat and back pads', '141616', .88, .01),
        'feet': finish.pbr('R12 bench | rubber feet and hinge covers', '101212', .95, 0),
        'hardware': finish.pbr('R12 bench | recessed dark metal pivots', '454B49', .54, .60),
    }
    for material in materials.values():
        shader=finish.shader_for(material)
        shader.inputs['Emission Strength'].default_value=0
    batches={key:primitive.Batch(key,mat,key!='pads') for key,mat in materials.items()}
    frames,pads,feet,hardware=[batches[key] for key in ('frames','pads','feet','hardware')]
    rows=seat_layout()
    for row in rows:
        x,y,_=row['source_position_m']
        rounded_prism(pads,(x,y,.452),(.464,.426,.046),.034)
        rounded_prism(pads,(x,y+.206,.748),(.458,.242,.034),.030,back=True)
        # Folding crossed tubular legs with braced rails, capped feet and small
        # pivots; padding stays fully black with no unrequested sponsor logo.
        for dx in (-.209,.209):
            frames.rod((x+dx,y-.252,.030),(x+dx,y+.182,.442),.012,.012,12)
            frames.rod((x+dx,y+.252,.030),(x+dx,y-.176,.441),.012,.012,12)
            frames.rod((x+dx,y+.174,.437),(x+dx,y+.230,.893),.013,.013,12)
            for dy in (-.252,.252):
                feet.box((x+dx,y+dy,.018),(.036,.060,.036))
            hardware.rod((x+dx-.009,y,.256),(x+dx+.009,y,.256),.024,.024,16)
            feet.rod((x+dx-.011,y,.256),(x+dx+.011,y,.256),.015,.015,12)
        for dy,z in ((-.177,.423),(.179,.423),(-.16,.146),(.16,.146)):
            frames.rod((x-.208,y+dy,z),(x+.208,y+dy,z),.011,.011,12)
        # Curved top rail visible above the back cushion.
        frames.rod((x-.207,y+.228,.889),(x+.207,y+.228,.889),.012,.012,12)
    made=[]
    for key,batch in batches.items():
        mesh=bpy.data.meshes.new(PREFIX+key)
        mesh.from_pydata(batch.vertices,[],batch.faces);mesh.update()
        bm=bmesh.new();bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(mesh);bm.free()
        mesh.materials.append(materials[key])
        for face in mesh.polygons:face.use_smooth=(key!='pads' and len(face.vertices)==4)
        obj=bpy.data.objects.new(PREFIX+key,mesh)
        bpy.data.collections['background'].objects.link(obj)
        obj.parent=bpy.data.objects['background']
        obj['r12_seating']=True;obj['layer']='background';obj['category']='seating'
        obj['placement_evidence']='User-requested right-side substitutes/coach bench, independent positions from existing native NBA role-marker schema.'
        obj['seat_count']=44;obj['native_role_names']=json.dumps([row['marker'] for row in rows])
        made.append(obj)
    bpy.context.view_layer.update()
    bounds=[obj.matrix_world@Vector(corner) for obj in made for corner in obj.bound_box]
    minimum=[min(v[i] for v in bounds) for i in range(3)]
    maximum=[max(v[i] for v in bounds) for i in range(3)]
    assert minimum[1]>7.62 and maximum[1]<9.17
    assert SPACING>.464 and CENTRE_GAP_HALF*2>.464
    report={'revision':'R12','status':'geometry_and_spacing_verified','objects':[o.name for o in made],
            'chairs':rows,'chair_count':44,'teams':2,'chairs_per_team':22,
            'source_bounds_m':{'min':minimum,'max':maximum},
            'seat_top_height_m':.475,'chair_back_top_m':.905,'centre_spacing_m':SPACING,
            'minimum_chair_to_sideline_m':minimum[1]-7.62,
            'minimum_chair_to_fence_axis_m':9.17-maximum[1],
            'group_clear_opening_m':2*CENTRE_GAP_HALF-.464,
            'appearance':'Individual black padded folding chairs, satin black tubular steel, crossed legs, caps and pivots.',
            'requested_addition_not_photo_claim':True,'native_marker_height_cm':0,
            'geometry_unchanged_except_new_chairs':True,
            'game_tested':False,'runtime_limit':'The marker floor height and yaw are native conventions; seated skeleton placement on padding remains an in-game check.',
            'vertices':sum(len(o.data.vertices) for o in made),
            'triangles':sum(sum(len(f.vertices)-2 for f in o.data.polygons) for o in made)}
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default=str(ROOT/'.build-staging/r12-seating/scene-seating.blend'))
    parser.add_argument('--render',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    output=Path(args.output).resolve()
    if not output.is_relative_to(ROOT) or output==ROOT/'source/scene.blend':
        raise ValueError('Seating module only publishes staging files')
    output.parent.mkdir(parents=True,exist_ok=True)
    bpy.context.preferences.filepaths.temporary_directory=str(output.parent)
    bpy.context.preferences.filepaths.save_version=0
    bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
    from refine_hoop_current import snapshot
    from refine_streetlight_current import lighting_signature
    before=snapshot();lights=lighting_signature()
    report=build_bench_geometry()
    after=snapshot()
    changed=[name for name,value in before.items() if after.get(name)!=value]
    if changed or lighting_signature()!=lights:raise RuntimeError('Protected scene changed: '+str(changed))
    report['protected_original_objects']=len(before)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    (ROOT/'validation/r12-seating-geometry.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    if args.render:
        scene=bpy.context.scene;camera=scene.camera
        scene.render.engine='CYCLES';scene.cycles.samples=24;scene.cycles.use_denoising=True
        scene.render.resolution_x=1280;scene.render.resolution_y=900;scene.render.resolution_percentage=100
        camera.location=(-4.1,5.4,1.7)
        camera.rotation_euler=(Vector((-6.2,8.58,.48))-camera.location).to_track_quat('-Z','Y').to_euler()
        camera.data.type='PERSP';camera.data.lens=47
        scene.render.image_settings.file_format='PNG'
        scene.render.filepath=str(ROOT/'validation/r12-seating-detail.png')
        bpy.ops.render.render(write_still=True)
    print(json.dumps({k:report[k] for k in ('chair_count','source_bounds_m','vertices','triangles','protected_original_objects')}))


if __name__=='__main__':main()
