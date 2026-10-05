"""R09 photo-based fence orientation and unlit fabricated A signs.

Incremental current-source edit only. The court, atlas mapping, baskets and all
anchors are protected. Artwork and runtime basket changes belong to other tools.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import bpy
import bmesh
from mathutils import Matrix, Vector

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import create_scene as source
import refine_architecture_r02 as primitive
import refine_details_r03 as finish
from refine_hoop_current import snapshot
from refine_details_current import capsule_points

REVISION='R09 asymmetric photo fence and unlit fabricated A'
STAGE=ROOT/'.build-staging/fence-current'
ALLOWED=set()
REMOVED=[]
ADDED=[]


def mark(obj):
    obj['r09_fence_detail']=True;obj['layer']='fence';obj['category']='fence'
    obj['reference_images']='13,15,18 for A form; 03,18,21 for asymmetric opening'
    obj['measurement_status']='Photo-supported shape and relative extent; absolute dimensions inferred, not surveyed.'
    ADDED.append(obj.name)
    return obj


def delete(obj):
    ALLOWED.add(obj.name);REMOVED.append(obj.name)
    data=obj.data if obj.type=='MESH' else None
    bpy.data.objects.remove(obj,do_unlink=True)
    if data and data.users==0:bpy.data.meshes.remove(data)


def make_mesh(name,vertices,faces,material,smooth=False):
    if (old:=bpy.data.objects.get(name)):delete(old)
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(vertices,[],faces);mesh.update()
    bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(mesh);bm.free()
    mesh.materials.append(material)
    for face in mesh.polygons:face.use_smooth=smooth
    obj=bpy.data.objects.new(name,mesh);bpy.data.collections['fence'].objects.link(obj)
    obj.parent=bpy.data.objects['fence'];return mark(obj)


def reflect_mesh(obj):
    ALLOWED.add(obj.name)
    # Bake the mirror while reversing winding. No negative scale remains in the
    # saved source or exported primitive; mesh UVs travel with their loops.
    transform=Matrix.Diagonal((1,-1,1,1))@obj.matrix_world
    if obj.data.users>1:obj.data=obj.data.copy()
    bm=bmesh.new();bm.from_mesh(obj.data)
    bmesh.ops.transform(bm,verts=list(bm.verts),matrix=transform)
    bmesh.ops.reverse_faces(bm,faces=list(bm.faces))
    bm.to_mesh(obj.data);bm.free();obj.data.update();obj.matrix_world=Matrix.Identity(4)


def exchange_fence_sides():
    original=[]
    for obj in list(bpy.data.objects):
        if 'North partial fence' not in obj.name and 'South partial fence' not in obj.name:continue
        old_name=obj.name;ALLOWED.add(old_name);original.append((obj,old_name))
        if obj.type=='MESH':reflect_mesh(obj)
        elif obj.type=='FONT':
            obj.location.y*=-1
            obj.rotation_euler.z=math.pi if obj.location.y<0 else 0.
        else:raise RuntimeError('Unexpected partial-fence object '+obj.type)
        obj['r09_original_name']=old_name
        obj.name='R09 temporary swap '+old_name
    for obj,old_name in original:
        name=old_name.replace('North partial fence','TEMP_SIDE').replace('South partial fence','North partial fence').replace('TEMP_SIDE','South partial fence')
        obj.name=name;ALLOWED.add(name)
        obj['top_view_orientation']='Chili’s up: negative Y left (long), positive Y right (short)'
    # Foot blocks and clamps were separate R02 batches with no run prefix.
    for obj in list(bpy.data.objects):
        if not obj.name.startswith(('R02 fence weighted foot ','R02 fence clamp ')):continue
        if abs(obj.matrix_world.translation.y)>9.10:reflect_mesh(obj)
    return len(original)


def rebuild_cloth_seams_and_printed_outlines():
    # Combined mesh batches include the end fence. Rebuild only their narrow
    # hems/outlines after moving the panels; cloth and print remain non-lighting.
    seam=bpy.data.materials['Current | cloth stitched seam']
    white=bpy.data.materials['Hoops | white board markings']
    hems=primitive.Batch('cloth hems',seam,True);rings=primitive.Batch('printed outlines',white,True)
    for obj in bpy.data.objects:
        if ' NBA ATELIER panel ' not in obj.name:continue
        # Mirrored side mesh is now in world coordinates; bound its original
        # panel plane in world space. The end fence still has its local basis.
        p=[obj.matrix_world@v.co for v in obj.data.vertices]
        xmin,xmax=min(v.x for v in p),max(v.x for v in p)
        ymin,ymax=min(v.y for v in p),max(v.y for v in p)
        if obj.name.startswith('End fence'):
            mid=(xmin+xmax)/2
            for d in (-.018,.018):
                for z in (.040,.650):hems.rod((mid+d,ymin+.018,z),(mid+d,ymax-.018,z),.0016,.0016,4)
                for y in (ymin+.018,ymax-.018):hems.rod((mid+d,y,.045),(mid+d,y,.645),.0016,.0016,4)
        else:
            mid=(ymin+ymax)/2
            for d in (-.018,.018):
                for z in (.040,.650):hems.rod((xmin+.018,mid+d,z),(xmax-.018,mid+d,z),.0016,.0016,4)
                for x in (xmin+.018,xmax-.018):hems.rod((x,mid+d,.045),(x,mid+d,.645),.0016,.0016,4)
    for obj in bpy.data.objects:
        if not obj.name.startswith('Current A logo '):continue
        orient=obj.rotation_euler.to_matrix()
        points=[obj.location+orient@Vector((x,y,.0008)) for x,y in capsule_points(.133,.231,.048)]
        for a,b in zip(points,points[1:]):rings.rod(a,b,.004,.004,6)
    make_mesh('Current cloth stitched hems',hems.vertices,hems.faces,seam,True)
    make_mesh('Current A banner badge outlines',rings.vertices,rings.faces,white,True)


def capsule(width,height,count=40):
    radius=width/2;offset=height/2-radius
    points=[]
    for center_z,start in ((offset,0),(-offset,math.pi)):
        for i in range(count+1):
            angle=start+i*math.pi/count
            points.append((radius*math.cos(angle),center_z+radius*math.sin(angle)))
    return points


def extruded_polygon(name,points,center,side,depth,material):
    cx,cy,cz=center;n=len(points)
    vertices=[(cx+x,cy-side*d,cz+z) for d in (0,depth) for x,z in points]
    faces=[tuple(reversed(range(n))),tuple(range(n,n*2))]
    faces += [(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)]
    return make_mesh(name,vertices,faces,material)


def swept_strip(name,path,center,side,radius,depth,material,dome=False):
    cx,cy,cz=center;vertices=[];faces=[]
    # Rounded clear-white diffuser uses a semicircular front face and flat rear.
    # The supporting dark channel has a full round section behind it.
    profile=[(radius*math.cos(math.pi*i/10),depth*math.sin(math.pi*i/10)) for i in range(11)] if dome else [(radius*math.cos(2*math.pi*i/12),depth*math.sin(2*math.pi*i/12)) for i in range(12)]
    for i,(x,z) in enumerate(path):
        before=Vector(path[max(0,i-1)]);after=Vector(path[min(len(path)-1,i+1)])
        tangent=(after-before).normalized();normal=Vector((-tangent.y,tangent.x))
        for radial,outward in profile:vertices.append((cx+x+normal.x*radial,cy-side*outward,cz+z+normal.y*radial))
    count=len(profile)
    for i in range(len(path)-1):
        for k in range(count):faces.append((i*count+k,i*count+(k+1)%count,(i+1)*count+(k+1)%count,(i+1)*count+k))
    faces.extend((tuple(reversed(range(count))),tuple((len(path)-1)*count+k for k in range(count))))
    return make_mesh(name,vertices,faces,material,True)


def letter_a(name,center,side,material,scale=1.,depth=.006):
    # Long, narrow brand silhouette rather than a generic font A. Separate hole
    # spline creates a real open triangular counter. Converted to actual mesh.
    outer=[(-.135,-.36),(-.052,.36),(.052,.36),(.135,-.36),(.052,-.36),(.033,-.187),(-.033,-.187),(-.052,-.36)]
    inner=[(-.018,-.104),(.018,-.104),(0,.185)]
    data=bpy.data.curves.new(name,'CURVE');data.dimensions='2D';data.fill_mode='BOTH';data.resolution_u=1
    data.extrude=depth;data.bevel_depth=.001;data.bevel_resolution=2
    for contour in (outer,inner):
        spline=data.splines.new('POLY');spline.points.add(len(contour)-1)
        for p,(x,z) in zip(spline.points,contour):p.co=(x*scale,z*scale,0,1)
        spline.use_cyclic_u=True
    data.materials.append(material)
    obj=bpy.data.objects.new(name,data);bpy.data.collections['fence'].objects.link(obj);obj.parent=bpy.data.objects['fence']
    obj.location=center;obj.rotation_euler=(math.pi/2,0,0 if side>0 else math.pi)
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
    bpy.ops.object.convert(target='MESH');obj=bpy.context.view_layer.objects.active
    return mark(obj)


def unlit_signs():
    case=finish.pbr('R09 | A sign charcoal enclosure','202824',.76,.10)
    channel=finish.pbr('R09 | A sign dark strip channel','141B18',.80,.08)
    diffuser=finish.pbr('R09 | A sign unlit white diffuser','E5E7DF',.66,0)
    metal=finish.pbr('R09 | A sign brackets','59635C',.72,.22)
    for mat in (case,channel,diffuser,metal):
        shader=finish.shader_for(mat);shader.inputs['Emission Strength'].default_value=0
        mat['emission_enabled']=False
    for obj in list(bpy.data.objects):
        if obj.name.startswith(('R02 fence A badge ','R02 A badge outline ','R02 fence A glyph ')):delete(obj)
    records=[]
    for side,x in ((-1,-9.5),(1,-11.9)):
        suffix='left' if side<0 else 'right';center=(x,side*9.123,2.03)
        plate=extruded_polygon('R09 A capsule enclosure.'+suffix,capsule(.565,1.17),center,side,.022,case)
        # Centreline height1.1m, with short unlit black interruptions at the
        # top/bottom. These are visible in photographs13,15,18.
        r=.233;offset=.312;gap_angle=.082
        right=[]
        for i in range(33):
            a=math.pi/2-gap_angle-(math.pi/2-gap_angle)*i/32;right.append((r*math.cos(a),offset+r*math.sin(a)))
        right.append((r,-offset))
        for i in range(1,33):
            a=-(math.pi/2-gap_angle)*i/32;right.append((r*math.cos(a),-offset+r*math.sin(a)))
        for direction in (-1,1):
            path=[(direction*u,v) for u,v in right]
            track_center=(x,side*9.094,2.03)
            swept_strip(f'R09 A recessed channel {direction}.{suffix}',path,track_center,side,.030,.014,channel)
            swept_strip(f'R09 A unlit diffuser {direction}.{suffix}',path,(x,side*9.081,2.03),side,.023,.011,diffuser,True)
        letter_a('R09 A inner letter channel.'+suffix,(x,side*9.096,2.03),side,channel,1.065,.009)
        letter_a('R09 A inner white diffuser.'+suffix,(x,side*9.082,2.03),side,diffuser,1.,.006)
        brackets=primitive.Batch('badge stand-offs',metal)
        for z in (1.73,2.33):brackets.box((x,side*9.153,z),(.058,.041,.064))
        make_mesh('R09 A stand-off brackets.'+suffix,brackets.vertices,brackets.faces,metal)
        plate['outline_to_height_ratio']=1.17/.565
        records.append({'side':suffix,'center_m':list(center),'enclosure_width_height_m':[.565,1.17],
                        'height_width_ratio':1.17/.565,'white_outline':'Two real domed diffuser strips in charcoal channels, interrupted at top/bottom',
                        'inner_A':'Extruded narrow silhouette with real triangular counter','emission':False,
                        'dimensions':'Inferred visual proportions; no surveyed sign size'})
    return records


def validate_extents():
    rows={}
    for prefix,side in (('South','left'),('North','right')):
        posts=[o.matrix_world@v.co for o in bpy.data.objects if o.name.startswith(prefix+' partial fence post ') for v in o.data.vertices]
        xmin,xmax=min(p.x for p in posts),max(p.x for p in posts)
        rows[side]={'source_y_m':-9.17 if side=='left' else 9.17,'start_x_m':round(xmin+.0375,4),'end_x_m':round(xmax-.0375,4),
                    'post_outer_extent_x_m':[xmin,xmax],'run_length_m':round(xmax-xmin-.075,4),'extent_status':'Relative orientation corrected; absolute spacing/endpoints remain inferred.'}
    assert abs(rows['left']['end_x_m']+2.8)<.001 and abs(rows['right']['end_x_m']+4.8)<.001
    return rows


def renders():
    scene=bpy.context.scene;camera=scene.camera
    scene.render.engine='CYCLES';scene.cycles.samples=36;scene.cycles.use_denoising=True
    scene.render.resolution_x=1500;scene.render.resolution_y=1200;scene.render.resolution_percentage=100
    for name,position,target,lens in (
        ('current-fence-A',(-8.0,-5.3,2.35),(-9.5,-9.13,1.85),62),
        ('current-fence-opening',(7,-25,16),(-7,0,.2),48),
    ):
        camera.data.type='PERSP';camera.data.lens=lens;camera.location=position
        camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
        scene.render.filepath=str(ROOT/'validation'/f'{name}.png');bpy.ops.render.render(write_still=True)
    # Explicit photo-comparison orientation: negative X / Chili’s at screen top,
    # negative Y at screen left. Saved source camera is unchanged before render.
    camera.data.type='ORTHO';camera.data.ortho_scale=42;camera.location=(-4,0,40)
    camera.rotation_euler=(0,0,math.pi/2)
    scene.render.resolution_x=1500;scene.render.resolution_y=1500
    scene.render.filepath=str(ROOT/'validation/current-fence-top.png');bpy.ops.render.render(write_still=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=str(ROOT/'source/scene.blend'));parser.add_argument('--render',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    output=Path(args.output).resolve()
    if not output.is_relative_to(ROOT):raise ValueError('Output outside project')
    if bpy.context.scene.get('fence_detail_revision')==REVISION:raise RuntimeError('Already applied; export saved source directly')
    STAGE.mkdir(parents=True,exist_ok=True);backup=STAGE/'source-before.blend'
    if not backup.exists():shutil.copy2(bpy.data.filepath,backup)
    prefs=bpy.context.preferences.filepaths;prefs.temporary_directory=str(STAGE);prefs.file_preview_type='NONE';prefs.save_version=0;prefs.use_auto_save_temporary_files=False
    bpy.context.view_layer.update();before=snapshot();swapped=exchange_fence_sides();bpy.context.view_layer.update()
    rebuild_cloth_seams_and_printed_outlines();signs=unlit_signs()
    # This existing low wave is the sole non-atlas surface needing a color
    # correction; photographs22–24 show warm mineral paving rather than white.
    wave=finish.pbr('R02 environment | ivory_wave','D2D0C3',.94,0)
    wave['photo_color_note']='Warm mineral ivory, inferred from22–24; not a calibrated photo color measurement.'
    bpy.context.view_layer.update();after=snapshot();unexpected=[n for n,h in before.items() if n not in ALLOWED and after.get(n)!=h]
    if unexpected:raise RuntimeError('Protected geometry changed: '+str(unexpected))
    extents=validate_extents();geometry=source.validate_scene()
    if geometry['status']!='passed':raise RuntimeError(json.dumps(geometry))
    report={'status':'passed','source_output':str(output),'orientation':'Chili’s / negative X up; negative Y left; positive Y right',
            'photo_evidence':{'13,15,18':'Narrow vertical A enclosure, rounded ends, top/bottom white-strip interruptions. White shape modeled as unlit fabricated parts.',
                              '03,18,21':'The layered-canopy side opens earlier; this is positive Y / right when Chili’s is up. Relative extent supported, metric endpoints inferred.',
                              '22,23,24':'Grey, warm mineral paving and local ivory low wave. Atlas colors owned by artwork agent.'},
            'fence_runs':extents,'exchanged_named_objects':swapped,'signs':signs,'removed_objects':REMOVED,'new_objects':ADDED,
            'protected_objects_unchanged':sum(n not in ALLOWED for n in before),'unexpected_changes':unexpected,
            'court_height_m':0,'court_mesh_uv_and_atlas_material_unchanged':True,'all_baskets_and_anchors_unchanged':True,
            'bottom_cloth_marks':'Printed small marks remain distinct from fabricated large A signs.',
            'non_atlas_paving_change':{'object':'R02 observed low plaza wave outside court','material':'R02 environment | ivory_wave','srgb':'#D2D0C3','roughness':.94,'geometry_unchanged':True},
            'geometry_validation':geometry,'game_package_written':False}
    bpy.context.scene['fence_detail_revision']=REVISION
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    (ROOT/'validation/current-fence-detail.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('FENCE_CURRENT_SAVED '+str(output),flush=True)
    if args.render:renders()


if __name__=='__main__':main()
