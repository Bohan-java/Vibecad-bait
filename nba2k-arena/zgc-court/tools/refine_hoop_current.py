"""Incrementally align photo-based supports to the one verified native glass.

Run only on the current saved source. Never regenerate the court, scenery, or
runtime rim/net. Native glass is retained by the parent IFF adapter; this source
sheet is its bounds-matched preview placeholder. Photographs establish form,
not surveyed dimensions. No game package is written by this script.
"""
from __future__ import annotations
import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import bpy
from mathutils import Matrix, Vector

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import create_scene as source
import refine_architecture_r02 as primitive
import refine_details_r03 as finish

REVISION='Native-glass aligned photo hoop R08'
ALLOWED=set()
REMOVED=[]
ADDED=[]
STAGE=ROOT/'.build-staging/hoop-current'


def snapshot():
    result={}
    for obj in bpy.data.objects:
        if obj.type not in ('MESH','CURVE','FONT','EMPTY'):continue
        h=hashlib.sha256(array('f',[v for row in obj.matrix_world for v in row]).tobytes())
        if obj.type=='MESH':
            for attr,seq,typecode in (('co',obj.data.vertices,'f'),('vertex_index',obj.data.loops,'i')):
                values=array(typecode,[0])*(len(seq)*(3 if attr=='co' else 1));seq.foreach_get(attr,values);h.update(values.tobytes())
            for uv in obj.data.uv_layers:
                values=array('f',[0])*(len(uv.data)*2);uv.data.foreach_get('uv',values);h.update(values.tobytes())
        elif obj.type=='FONT':h.update(obj.data.body.encode('utf8'))
        elif obj.type=='CURVE':
            h.update(str(obj.data.bevel_depth).encode())
            for spline in obj.data.splines:
                for p in spline.points:h.update(array('f',p.co).tobytes())
        result[obj.name]=h.hexdigest()
    return result


def tag(obj,layer):
    obj['r08_hoop_detail']=True;obj['layer']=layer;obj['category']='hoops'
    obj['reference_images']='07,10,11,14,15,16,19'
    obj['reconstruction']='Photo-supported form; small fabrication dimensions inferred, not measured.'
    ADDED.append(obj.name)
    return obj


def delete(obj):
    ALLOWED.add(obj.name);REMOVED.append(obj.name)
    data=obj.data if obj.type=='MESH' else None
    bpy.data.objects.remove(obj,do_unlink=True)
    if data and data.users==0:bpy.data.meshes.remove(data)


def new_mesh(name,vertices,faces,material,layer,smooth=False):
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(vertices,[],faces);mesh.update()
    mesh.materials.append(material)
    for face in mesh.polygons:face.use_smooth=smooth
    obj=bpy.data.objects.new(name,mesh);bpy.data.collections[layer].objects.link(obj)
    obj.parent=bpy.data.objects[layer]
    return tag(obj,layer)


def box(name,center,dimensions,material,layer,bevel=.002):
    obj=source.cube(name,center,dimensions,material,layer,bevel)
    if bevel:
        for mod in obj.modifiers:
            if mod.type=='BEVEL':mod.segments=3
    return tag(obj,layer)


def cylinder(name,a,b,radius,material,layer,segments=32):
    builder=primitive.Batch(name,material,True);builder.rod(a,b,radius,radius,segments)
    obj=new_mesh(name,builder.vertices,builder.faces,material,layer,True)
    # Polygon end caps stay flat; side normals are smoothly interpolated.
    for face in obj.data.polygons:
        if len(face.vertices)>4:face.use_smooth=False
    return obj


def retain_base_hardware(obj):
    """Keep the existing low fittings; remove old floating board/rim fittings."""
    ALLOWED.add(obj.name)
    old=obj.data
    keep=[p for p in old.polygons if all((obj.matrix_world@old.vertices[i].co).z<.5 for i in p.vertices)]
    used=sorted({i for p in keep for i in p.vertices});lookup={v:i for i,v in enumerate(used)}
    verts=[tuple(obj.matrix_world@old.vertices[i].co) for i in used]
    faces=[tuple(lookup[i] for i in p.vertices) for p in keep]
    mesh=bpy.data.meshes.new(obj.name+' retained floor hardware');mesh.from_pydata(verts,[],faces);mesh.update()
    for mat in old.materials:mesh.materials.append(mat)
    for face in mesh.polygons:face.use_smooth=True
    obj.data=mesh;obj.matrix_world=Matrix.Identity(4)
    if old.users==0:bpy.data.meshes.remove(old)


def setup():
    for layer in ('reference_half','open_half'):
        source.GROUPS[layer]=(bpy.data.collections[layer],bpy.data.objects[layer])
    material={
        'steel':finish.pbr('R08 | muted grey tubular steel','67716C',.68,.18),
        'edge':finish.pbr('R08 | slim satin silver board frame','9FA7A1',.52,.28),
        'rubber':finish.pbr('R08 | charcoal moulded lower board padding','202927',.91,0),
        'white':finish.pbr('R08 | flat white board paint','E4E6DF',.74,0),
        'seal':finish.pbr('R08 | restrained dark board seals','28342F',.93,0),
        'bolt':finish.pbr('R08 | small dull steel fasteners','858E87',.59,.38),
    }
    glass=finish.pbr('Hoops | transparent backboard','8F9B97',.14,0)
    shader=finish.shader_for(glass)
    for link in list(shader.inputs['Alpha'].links):glass.node_tree.links.remove(link)
    shader.inputs['Alpha'].default_value=.08
    shader.inputs['Transmission Weight'].default_value=0
    glass.diffuse_color=(*finish.linear_hex('8F9B97'),.08)
    glass.surface_render_method='DITHERED';glass.use_transparent_shadow=True
    material['glass']=glass
    return material


def native_glass_bounds():
    doc=json.loads((ROOT/'validation/native-basket-alignment.json').read_text(encoding='utf8'))
    entries=[m for name,m in doc.items() if name.endswith(':glass')]
    if len(entries)!=1:raise ValueError('Require one verified native glass model')
    result={}
    for inst in entries[0]['instances']:
        suffix='reference' if inst['blender_max'][0]<0 else 'open'
        result[suffix]=(Vector(inst['blender_min']),Vector(inst['blender_max']))
    if set(result)!={'reference','open'}:raise ValueError('Require both native glass instances')
    return result


def placeholder(side,suffix,lo,hi,materials):
    old=bpy.data.objects['Backboard.'+suffix];ALLOWED.add(old.name)
    # Unit cube is deliberately a bounds proxy, not a replacement skeleton.
    verts=[(x,y,z) for x in (lo.x,hi.x) for y in (lo.y,hi.y) for z in (lo.z,hi.z)]
    faces=[(0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3)]
    mesh=bpy.data.meshes.new('Native bounds glass placeholder.'+suffix);mesh.from_pydata(verts,[],faces);mesh.update()
    mesh.materials.append(materials['glass']);previous=old.data;old.data=mesh;old.matrix_world=Matrix.Identity(4)
    for mod in list(old.modifiers):old.modifiers.remove(mod)
    if previous.users==0:bpy.data.meshes.remove(previous)
    old['native_glass_bounds_min']=list(lo);old['native_glass_bounds_max']=list(hi)
    old['native_glass_alignment']='Verified active native glass world bounds; source is preview placeholder only.'
    old['front_x_m']=hi.x if side<0 else lo.x
    old['expected_width_m']=hi.y-lo.y;old['expected_height_m']=hi.z-lo.z
    old['expected_bottom_m']=lo.z
    old['expected_front_x_m']=hi.x if side<0 else lo.x
    old['game_export_strategy']='Omit placeholder; retain native glass binding with one unmarked transparent material.'
    return old


def refine():
    mats=setup();bounds=native_glass_bounds();alignment=[]
    for side,suffix in ((-1,'reference'),(1,'open')):
        layer='reference_half' if side<0 else 'open_half'
        lo,hi=bounds[suffix];front=hi.x if side<0 else lo.x;back=lo.x if side<0 else hi.x
        cy=(lo.y+hi.y)/2;cz=(lo.z+hi.z)/2;width=hi.y-lo.y;height=hi.z-lo.z
        pole=side*(source.LENGTH/2+.95)
        # Replace only earlier frame/support approximations and their now-wrong
        # fixing positions. Rim, mounting plate, connectors, nets and anchors stay.
        prefixes=('Board edge ','R02 upper reach.','R02 main reach.','R02 rear brace.',
                  'R02 board diagonal ','R02 back stay ','R02 black lower board rail.',
                  'R02 black rail return ','R02 board fixing.','R02 board target outline.',
                  'R03 backboard frame seating gaskets.','R03 backboard subtle green edge.',
                  'R03 painted rim support gussets.')
        for obj in list(bpy.data.objects):
            if ((obj.name.endswith('.'+suffix) and obj.name.startswith(prefixes)) or
                    obj.name.startswith('R02 board fixing.'+suffix+'.')):delete(obj)
        for prefix in ('R03 machined collars and hex heads.','R03 bolt head recess marks.','R03 support weld beads.'):
            obj=bpy.data.objects.get(prefix+suffix)
            if obj:retain_base_hardware(obj)
        placeholder(side,suffix,lo,hi,mats)

        # The visible frame follows the exact glass perimeter, with no second
        # painted outer perimeter. Photo 07/19: thin silver top and sides, dark
        # continuous lower impact padding and shorter upward returns.
        frame_x=(front+back)/2+side*.005
        for yy in (lo.y,hi.y):
            box(f'R08 board side frame {yy:+.4f}.{suffix}',(frame_x,yy,cz-.0125),(.032,.025,height),mats['edge'],layer,.0013)
        box('R08 board top frame.'+suffix,(frame_x,cy,hi.z),(.032,width+.025,.025),mats['edge'],layer,.0022)
        box('R08 board lower structural rail.'+suffix,(back+side*.011,cy,lo.z+.003),(.034,width,.027),mats['steel'],layer,.002)
        box('R08 board lower safety pad.'+suffix,(frame_x,cy,lo.z-.003),(.060,width+.056,.059),mats['rubber'],layer,.009)
        for edge,yy in enumerate((lo.y,hi.y)):
            box(f'R08 board corner safety pad {edge}.{suffix}',(frame_x,yy,lo.z+.129),(.061,.058,.284),mats['rubber'],layer,.009)
        seal=primitive.Batch('seals',mats['seal'],True)
        for yy in (lo.y+.012,hi.y-.012):seal.box((back+side*.003,yy,cz),(.007,.004,height-.034))
        seal.box((back+side*.003,cy,hi.z-.012),(.007,width-.029,.004))
        new_mesh('R08 seated glass gaskets.'+suffix,seal.vertices,seal.faces,mats['seal'],layer)

        # Paint sits 0.5 mm in front of glass, replacing the old floating 25 mm
        # offset. Native adapter removes its texture-based copy, not this mesh.
        tw,th,stroke=.6096,.4572,.040
        bottom=source.RIM_TOP-.030;x=front-side*.0005
        yz=[(-tw/2,bottom),(tw/2,bottom),(tw/2,bottom+th),(-tw/2,bottom+th),
            (-tw/2+stroke,bottom+stroke),(tw/2-stroke,bottom+stroke),
            (tw/2-stroke,bottom+th-stroke),(-tw/2+stroke,bottom+th-stroke)]
        faces=[(i,(i+1)%4,(i+1)%4+4,i+4) for i in range(4)]
        if side>0:faces=[tuple(reversed(f)) for f in faces]
        target=new_mesh('R08 single printed board target.'+suffix,[(x,y,z) for y,z in yz],faces,mats['white'],layer)
        target['single_visible_target']=True;target['surface_offset_m']=.0005

        # Photo 10/15/16 shows one circular main reach below the backboard; no
        # extra diagonal crosses the upper clear board. Retain post/base layout.
        main_start=(pole,0,3.13);main_end=(back+side*.030,0,3.010)
        cylinder('R08 round main reach.'+suffix,main_start,main_end,.077,mats['steel'],layer,48)
        cylinder('R08 lower post brace.'+suffix,(pole,0,2.70),(pole-side*.79,0,3.085),.032,mats['steel'],layer,24)
        box('R08 board rear mounting saddle.'+suffix,(back+side*.021,0,3.010),(.027,.156,.168),mats['steel'],layer,.004)
        # Fine V braces are contained behind the glass. The two horizontal
        # rear stays end at the lower padded corner lugs seen in photo 15.
        join=(back+side*.056,0,3.091)
        hardware=primitive.Batch('board hardware',mats['bolt'],True)
        lugs=primitive.Batch('rear lugs',mats['steel'],False)
        for sign in (-1,1):
            top_y=cy+sign*(width/2-.075);top_z=hi.z-.102
            end=(back+side*.036,top_y,top_z)
            cylinder(f'R08 board V brace {sign}.{suffix}',join,end,.0105,mats['steel'],layer,20)
            stay_y=cy+sign*(width/2-.023);stay_z=lo.z+.233
            stay_end=Vector((back+side*.049,stay_y,stay_z))
            stay_start=Vector((pole-side*.23,0,3.145))
            direction=(stay_end-stay_start).normalized()
            cylinder(f'R08 round rear stay {sign}.{suffix}',stay_start,stay_end-direction*.072,.015,mats['steel'],layer,24)
            cylinder(f'R08 threaded rear stay end {sign}.{suffix}',stay_end-direction*.086,stay_end,.0075,mats['bolt'],layer,16)
            # Short ears and restrained bolt heads join the rods rather than
            # floating in the transparent panel.
            lugs.box((back+side*.029,stay_y,stay_z),(.046,.043,.051))
            lugs.box((back+side*.017,top_y,top_z),(.029,.046,.046))
            for yy,zz in ((stay_y,stay_z),(top_y,top_z)):
                hardware.rod((front-side*.001,yy,zz),(front-side*.004,yy,zz),.010,.010,16)
                hardware.rod((front-side*.004,yy,zz),(front-side*.007,yy,zz),.006,.006,6)
            # The small rear collar represents the visible adjustable clevis.
            hardware.rod(stay_end-direction*.064,stay_end-direction*.054,.012,.012,6)
        new_mesh('R08 rear connection lugs.'+suffix,lugs.vertices,lugs.faces,mats['steel'],layer)
        new_mesh('R08 connected board fasteners.'+suffix,hardware.vertices,hardware.faces,mats['bolt'],layer,True)
        alignment.append({'side':suffix,'native_glass_min_m':list(lo),'native_glass_max_m':list(hi),
                          'sheet_width_m':width,'sheet_height_m':height,'front_x_m':front,
                          'target_width_height_stroke_m':[tw,th,stroke],'target_bottom_m':bottom,
                          'target_surface_offset_m':.0005,'native_glass_vertices_modified':False,
                          'dimensions_note':'Glass dimensions decoded from package; minor support dimensions are photo-informed, not a site survey.'})
    return alignment


def render_views():
    scene=bpy.context.scene;camera=scene.camera
    scene.render.engine='CYCLES';scene.cycles.samples=40;scene.cycles.use_denoising=True
    scene.render.resolution_x=1500;scene.render.resolution_y=1200;scene.render.resolution_percentage=100
    for name,pos,target,lens in (
        ('current-hoop-detail',(-10.5,-2.3,3.35),(-13.05,0,3.24),46),
        ('current-hoop-side',(-14.6,-3.5,2.90),(-13.45,0,3.20),50),
        ('current-hoop-front',(-7.5,0,3.2),(-13.25,0,3.30),67),
    ):
        camera.data.type='PERSP';camera.data.lens=lens;camera.location=pos
        camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
        scene.render.filepath=str(ROOT/'validation'/f'{name}.png');bpy.ops.render.render(write_still=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=str(ROOT/'source/scene.blend'));parser.add_argument('--render',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    out=Path(args.output).resolve()
    if not out.is_relative_to(ROOT):raise ValueError('Output outside project')
    if bpy.context.scene.get('hoop_alignment_revision')==REVISION:raise RuntimeError('Already applied; export saved source directly')
    STAGE.mkdir(parents=True,exist_ok=True);backup=STAGE/'source-before.blend'
    if not backup.exists():shutil.copy2(bpy.data.filepath,backup)
    pref=bpy.context.preferences.filepaths;pref.temporary_directory=str(STAGE);pref.file_preview_type='NONE';pref.save_version=0;pref.use_auto_save_temporary_files=False
    bpy.context.view_layer.update();before=snapshot();alignment=refine();bpy.context.view_layer.update();after=snapshot()
    unexpected=[name for name,value in before.items() if name not in ALLOWED and after.get(name)!=value]
    if unexpected:raise RuntimeError('Unexpected protected changes: '+str(unexpected))
    validation=source.validate_scene()
    if validation['status']!='passed':raise RuntimeError('Geometry validation failed: '+json.dumps(validation))
    bpy.context.scene['hoop_alignment_revision']=REVISION
    report={'status':'passed','source_output':str(out),'source_native_conflict':{'old_source_board_bottom_m':2.7432,
            'native_board_bottom_m':2.9043453196879536,'lower_edge_difference_mm':161.1453196879536,
            'second_white_target':'Native albedo markings and source geometry previously duplicated; parent material adapter removes native markings.'},
            'alignment':alignment,'removed_objects':REMOVED,'added_objects':ADDED,'allowed_modified_objects':sorted(ALLOWED),
            'protected_objects_unchanged':len(before)-len(ALLOWED),'unexpected_geometry_changes':unexpected,
            'gameplay_anchors_rim_net_unchanged':True,'court_geometry_and_uv_unchanged':True,
            'native_package_written':False,'native_material_repair_owned_by_parent':True,'nba_geometry':validation}
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    (ROOT/'validation/current-hoop-alignment.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    (ROOT/'source/geometry_validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf8')
    print('HOOP_ALIGNMENT_SAVED '+str(out),flush=True)
    if args.render:render_views()


if __name__=='__main__':main()
