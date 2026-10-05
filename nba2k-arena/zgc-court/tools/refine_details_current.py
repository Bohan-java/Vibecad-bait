"""Photo-supported detail pass on the current OPEN Blender source.

This is incremental: no court/architecture generator is run and no artwork,
game IFF, runtime rim/net, layout, or gameplay anchor is edited.
"""
from __future__ import annotations
import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import sys
import bpy
import numpy as np
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import refine_architecture_r02 as geom
import refine_environment_r02 as garden
import refine_details_r03 as finish
import create_scene as source

PI=math.pi
STAGE=ROOT/'.build-staging/details'
TEXTURES=ROOT/'textures/current'
RNG=random.Random(260607)
ALLOWED=set()
CHANGES=[]


def mark(obj,layer,reference):
    obj['current_photo_detail']=True;obj['layer']=layer
    obj['category']='hoops' if layer in ('reference_half','open_half') else layer
    obj['reference_images']=reference


def replace_mesh(obj,vertices,faces,smooth=True):
    ALLOWED.add(obj.name)
    old=obj.data;materials=list(old.materials)
    data=bpy.data.meshes.new(obj.name+' current mesh');data.from_pydata(vertices,[],faces);data.update()
    for mat in materials:data.materials.append(mat)
    obj.data=data
    for p in data.polygons:p.use_smooth=smooth
    for mod in list(obj.modifiers):obj.modifiers.remove(mod)
    if old.users==0:bpy.data.meshes.remove(old)
    return data


def new_mesh(name,vertices,faces,mat,layer,smooth=True):
    obj=bpy.data.objects.get(name)
    if obj:bpy.data.objects.remove(obj,do_unlink=True)
    data=bpy.data.meshes.new(name);data.from_pydata(vertices,[],faces);data.update()
    data.materials.append(mat)
    for face in data.polygons:face.use_smooth=smooth
    obj=bpy.data.objects.new(name,data);bpy.data.collections[layer].objects.link(obj)
    obj.parent=bpy.data.objects[layer];mark(obj,layer,'07,14,15,25; Chili’s 02,07')
    return obj


def pbr(name,color,rough=.8,metal=0):
    return finish.pbr(name,color,rough,metal)


def texture(mat,path,uv_name):
    node=mat.node_tree.nodes.new('ShaderNodeTexImage');node.name='Current explicit material image'
    node.image=bpy.data.images.load(str(path),check_existing=True);node.image.colorspace_settings.name='sRGB'
    uv=mat.node_tree.nodes.new('ShaderNodeUVMap');uv.uv_map=uv_name
    mat.node_tree.links.new(uv.outputs['UV'],node.inputs['Vector'])
    mat.node_tree.links.new(node.outputs['Color'],finish.shader_for(mat).inputs['Base Color'])
    mat['explicit_uv_channel']=uv_name


def material_maps():
    TEXTURES.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(260607);n=512
    y,x=np.mgrid[0:n,0:n]
    grain=(rng.random((n,n))-.5)*.007
    weave=.006*np.sin(x*PI/2)*np.sin(y*PI/2)
    cloth=np.zeros((n,n,3))+np.array([.135,.132,.145])+(grain+weave)[:,:,None]
    finish.write_png(TEXTURES/'fence-cloth-basecolor.png',cloth)
    # A small baked leafy underlayer complements real shaped leaves; all leaf
    # material coordinates are explicit UVs and survive the native export path.
    leafy=np.zeros((n,n,3))+np.array([.135,.215,.115])
    leafy+=(rng.random((n,n,1))-.5)*.020
    for i in range(72):
        cx,cy=rng.random(2)*n;a=rng.random()*2*PI
        dx=(x-cx+n/2)%n-n/2;dy=(y-cy+n/2)%n-n/2
        u=dx*np.cos(a)+dy*np.sin(a);v=-dx*np.sin(a)+dy*np.cos(a)
        q=(u/rng.uniform(22,39))**2+(v/rng.uniform(9,15))**2
        mask=q<1
        shade=.018+.032*(1-np.clip(q,0,1))+.012*(u>0)
        for c,m in enumerate((.65,1.,.48)):leafy[:,:,c][mask]+=shade[mask]*m
    finish.write_png(TEXTURES/'living-groundcover-basecolor.png',np.clip(leafy,0,1))


def supports():
    steel=pbr('Hoops | brushed grey steel','747D77',.66,.24)
    rods=pbr('Current | matte grey painted round supports','606A63',.69,.20)
    count=0
    for obj in list(bpy.data.objects):
        if not obj.name.startswith(('R02 board diagonal ','R02 back stay ')):continue
        co=np.array([v.co[:] for v in obj.data.vertices])
        zlo,zhi=float(co[:,2].min()),float(co[:,2].max())
        builder=geom.Batch('round support',rods,True)
        builder.rod((0,0,zlo),(0,0,zhi),.0125,.0125,12)
        replace_mesh(obj,builder.vertices,builder.faces)
        obj.data.materials.clear();obj.data.materials.append(rods)
        obj['photo_detail_reference']='15: round rear rods; original centreline and endpoints retained'
        count+=1
    # The photographic frame is a painted uniform grey; exposed bolt heads
    # remain separate materials rather than making the whole frame polished.
    CHANGES.append({'detail':'painted support finish and round rear stays','replaced_rods':count,
                    'main_post_beam_geometry_changed':False})


def capsule_points(width,height,radius,steps=8):
    points=[]
    for cx,cy,start in ((width/2-radius,height/2-radius,0),(-width/2+radius,height/2-radius,PI/2),
                        (-width/2+radius,-height/2+radius,PI),(width/2-radius,-height/2+radius,3*PI/2)):
        for i in range(steps+1):
            a=start+i*(PI/2)/steps;points.append((cx+radius*math.cos(a),cy+radius*math.sin(a)))
    points.append(points[0]);return points


def fence_cloth():
    cloth=pbr('Fence | near-black NBA panels','242228',.98,0)
    texture(cloth,TEXTURES/'fence-cloth-basecolor.png','Current cloth UV')
    seam=pbr('Current | cloth stitched seam','343239',.98,0)
    white=bpy.data.materials['Hoops | white board markings']
    seams=geom.Batch('seams',seam,True);rings=geom.Batch('badge rings',white,True)
    panels=[o for o in bpy.data.objects if ' NBA ATELIER panel ' in o.name]
    for k,obj in enumerate(panels):
        co=np.array([v.co[:] for v in obj.data.vertices]);width=float(np.ptp(co[:,0]));height=.65
        verts=[];faces=[];nx,nz=28,8
        for side in (-1,1):
            offset=len(verts)
            for j in range(nz+1):
                v=j/nz;z=(v-.5)*height
                for i in range(nx+1):
                    u=i/nx;xx=(u-.5)*width
                    wrinkle=.0035*math.sin(PI*u)*math.sin(PI*v)*math.sin(9*PI*u+k*.9)
                    yy=side*.016+wrinkle
                    verts.append((xx,yy,z))
            for j in range(nz):
                for i in range(nx):
                    a=offset+j*(nx+1)+i
                    f=(a,a+1,a+nx+2,a+nx+1)
                    faces.append(f if side<0 else tuple(reversed(f)))
        replace_mesh(obj,verts,faces)
        uv=obj.data.uv_layers.new(name='Current cloth UV')
        for loop in obj.data.loops:
            p=obj.data.vertices[loop.vertex_index].co;uv.data[loop.index].uv=(p.x*6,p.z*6)
        # Straight stitched hems remain attached to each separate fabric panel.
        for side in (-1,1):
            for z in (-.305,.305):
                a=obj.matrix_world@Vector((-width/2+.018,side*.018,z))
                b=obj.matrix_world@Vector((width/2-.018,side*.018,z))
                seams.rod(a,b,.0016,.0016,4)
            for x in (-width/2+.018,width/2-.018):
                seams.rod(obj.matrix_world@Vector((x,side*.018,-.30)),obj.matrix_world@Vector((x,side*.018,.30)),.0016,.0016,4)
    marks=[o for o in bpy.data.objects if ' fence panel mark ' in o.name]
    for old in marks:
        ALLOWED.add(old.name);old.location.z=.255;old.data.size=.105
        normal=old.rotation_euler.to_matrix()@Vector((0,0,1))
        old.location+=normal*.007
        label_name='Current A logo '+old.name
        existing=bpy.data.objects.get(label_name)
        if existing:bpy.data.objects.remove(existing,do_unlink=True)
        data=old.data.copy();data.body='A';data.size=.183;data.align_x='CENTER';data.align_y='CENTER'
        data.extrude=.0006;data.bevel_depth=0;data.materials.clear();data.materials.append(white)
        label=bpy.data.objects.new(label_name,data);bpy.data.collections['fence'].objects.link(label)
        label.parent=bpy.data.objects['fence'];label.location=old.location;label.location.z=.467
        label.rotation_euler=old.rotation_euler;label.scale.x=.69;mark(label,'fence','07,14')
        orient=old.rotation_euler.to_matrix()
        points=[label.location+orient@Vector((x,y,.0008)) for x,y in capsule_points(.133,.231,.048)]
        for a,b in zip(points,points[1:]):rings.rod(a,b,.004,.004,6)
    new_mesh('Current cloth stitched hems',seams.vertices,seams.faces,seam,'fence')
    new_mesh('Current A banner badge outlines',rings.vertices,rings.faces,white,'fence')
    CHANGES.append({'detail':'separate cloth panels with upper A badge and lower NBA ATELIER','panels':len(panels),'badge_labels':len(marks)})


def chilis_signs():
    awning=bpy.data.objects['R02 architecture Chilis awning wordmark'];ALLOWED.add(awning.name)
    font_path=Path(bpy.app.binary_path).parent/'5.2/datafiles/fonts/Noto Sans CJK Regular.woff2'
    if not font_path.is_file():raise RuntimeError('Bundled verified Chinese font missing')
    font=bpy.data.fonts.load(str(font_path))
    if awning.type!='FONT':
        old=awning.data;awning.data=bpy.data.curves.new('Current Chinese awning inscription','FONT')
        awning.data.materials.append(bpy.data.materials['R02 architecture | awning_print'])
    awning.data.font=font;awning.data.body='奇利斯美式小餐馆'
    awning.data.size=.25;awning.data.extrude=.0007;awning.data.bevel_depth=0
    awning.data.align_x='CENTER';awning.data.align_y='CENTER'
    bpy.context.view_layer.update()
    local_width=max(v[0] for v in awning.bound_box)-min(v[0] for v in awning.bound_box)
    awning.data.size*=2.22/local_width
    bpy.context.view_layer.update()
    evaluated=awning.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh=bpy.data.meshes.new_from_object(evaluated,depsgraph=bpy.context.evaluated_depsgraph_get())
    if len(mesh.vertices)<1000:raise RuntimeError('Chinese font glyph test unexpectedly small')
    bpy.data.meshes.remove(mesh)
    bpy.ops.object.select_all(action='DESELECT');awning.select_set(True)
    bpy.context.view_layer.objects.active=awning
    bpy.ops.object.convert(target='MESH')
    awning=bpy.context.view_layer.objects.active;mesh=awning.data
    awning['inscription']='奇利斯美式小餐馆';awning['reference_images']='Chili’s 02,07'
    # Existing Latin glyphs are retained, but expressed as actual tubular
    # outlines. Native export retains shape/color even without emission support.
    logo=bpy.data.objects['R02 architecture Chilis principal orange identity'];ALLOWED.add(logo.name)
    if logo.type!='FONT':raise RuntimeError('Expected editable original principal Chili font')
    logo.data.fill_mode='NONE';logo.data.extrude=0;logo.data.bevel_depth=.0105;logo.data.bevel_resolution=3
    orange=pbr('R02 architecture | neon_orange','FF862B',.4,.04)
    shader=finish.shader_for(orange);shader.inputs['Emission Color'].default_value=(*finish.linear_hex('F97919'),1)
    shader.inputs['Emission Strength'].default_value=.24
    green=pbr('R02 architecture | logo_green','65AD35',.5,0)
    CHANGES.append({'detail':'correct Chinese cream-awning inscription and outlined Chili neon','chinese_glyph_mesh_vertices':len(mesh.vertices),
                    'awning_text':awning['inscription'],'font_origin':'Blender bundled Noto Sans CJK SC Regular; glyphs embedded as mesh',
                    'building_positions_changed':False})


def leaf(builder,center,length,width,angle,tilt,roll=0):
    p=Vector(center);axis=Vector((math.cos(angle)*math.cos(tilt),math.sin(angle)*math.cos(tilt),math.sin(tilt)))
    side=Vector((-math.sin(angle),math.cos(angle),0));normal=axis.cross(side).normalized()
    side=side*math.cos(roll)+normal*math.sin(roll)
    outline=[]
    for i in range(8):
        a=i*2*PI/8
        outline.append(p+axis*(math.cos(a)*length*.5)+side*(math.sin(a)*width*.5))
    builder.add(outline+[p+normal*width*.075],[(i,(i+1)%8,8) for i in range(8)])


def point_in_polygon(x,y,points):
    inside=False;j=len(points)-1
    for i,(xi,yi) in enumerate(points):
        xj,yj=points[j]
        if ((yi>y)!=(yj>y)) and x<(xj-xi)*(y-yi)/(yj-yi)+xi:inside=not inside
        j=i
    return inside


def planting_detail():
    names=['R02 low groundcover leaf clusters '+str(i) for i in range(3)]
    colors=['36522E','405D35','506B3D'];builders=[]
    for i,name in enumerate(names):
        mat=pbr('R02 environment | groundleaf'+str(i),colors[i],.91,0)
        builders.append(geom.Batch(name,mat,True))
    beds=[(0,8.8,17.2,12.6,3.75,-.025),(1,25.5,10.2,6.15,4.25,.18),
          (2,25.2,-11.8,6.,4.4,-.16),(3,4.,-17.2,12.,3.6,.055),(4,-16.8,18.9,4.3,3.4,-.08)]
    leaves=0
    for index,cx,cy,rx,ry,angle in beds:
        polygon=garden.curve_polygon(cx,cy,rx*.95,ry*.95,angle,index+81,96)
        minx,maxx=min(x for x,y in polygon),max(x for x,y in polygon)
        miny,maxy=min(y for x,y in polygon),max(y for x,y in polygon)
        for yy in np.arange(miny,maxy,.155):
            for xx in np.arange(minx,maxx,.155):
                x=xx+RNG.uniform(-.065,.065);y=yy+RNG.uniform(-.065,.065)
                if not point_in_polygon(x,y,polygon):continue
                z=.155+.035*math.sin(x*1.8)*math.cos(y*2.3)+RNG.uniform(0,.045)
                leaf(builders[RNG.randrange(3)],(x,y,z),RNG.uniform(.145,.20),RNG.uniform(.085,.12),RNG.random()*2*PI,RNG.uniform(.10,.43),RNG.uniform(-.2,.2));leaves+=1
    for name,builder in zip(names,builders):
        obj=bpy.data.objects[name];replace_mesh(obj,builder.vertices,builder.faces)
        obj.data.materials.clear();obj.data.materials.append(builder.mat)
    base=bpy.data.objects['R02 continuous low garden groundcover']
    mat=pbr('R02 environment | groundcover','344D2C',.98,0)
    texture(mat,TEXTURES/'living-groundcover-basecolor.png','Current living cover UV')
    finish.box_uv(base,'Current living cover UV',scale=2.)
    heads=bpy.data.objects['R02 fine white flower florets']
    if 'current_flower_centers' in heads:
        centres=np.array(heads['current_flower_centers']).reshape(-1,3)
    else:
        vertices=np.array([v.co[:] for v in heads.data.vertices])
        if len(vertices)%270:raise RuntimeError('Expected original 27 paired-floret groups')
        centres=vertices.reshape(-1,270,3).mean(axis=1)
        heads['current_flower_centers']=centres.reshape(-1).tolist()
    white=pbr('R02 environment | flower_white','EAEADC',.88,0)
    builder=geom.Batch('white flowering heads',white,True)
    for centre in centres:
        radius=RNG.uniform(.078,.098)
        for j in range(52):
            a=j*2.399963;z=1-2*(j+.5)/52;r=math.sqrt(1-z*z)
            normal=Vector((r*math.cos(a),r*math.sin(a),z))
            u=normal.cross(Vector((0,0,1)))
            if u.length<.01:u=normal.cross(Vector((0,1,0)))
            u.normalize();v=normal.cross(u)
            p=Vector(centre)+normal*radius
            for k in range(3):
                t=k*2*PI/3;axis=u*math.cos(t)+v*math.sin(t);side=normal.cross(axis)
                petal=(p-axis*.005,p+axis*.010+side*.009,p+axis*.025+normal*.003,p+axis*.010-side*.009)
                builder.add(petal,[(0,1,2),(0,2,3)])
    replace_mesh(heads,builder.vertices,builder.faces)
    heads.data.materials.clear();heads.data.materials.append(white)
    CHANGES.append({'detail':'denser rounded-leaf cover inside existing beds and fuller white spherical flower clusters',
                    'shaped_low_leaves':leaves,'existing_flower_heads_retained_at_same_centres':len(centres),'new_planting_footprints':False})


def extend_visual_apron():
    """Parent-requested neutral cover extent; exact central NBA face is fixed."""
    court=bpy.data.objects['court_surface'];ALLOWED.add(court.name)
    face=court.data.polygons[int(court['playing_face_index'])]
    centre=[court.data.vertices[i].co.copy() for i in face.vertices]
    uv=court.data.uv_layers.get('PavingWorldXY')
    if uv is None:raise RuntimeError('Expected existing world atlas UV')
    before_uv=[tuple(uv.data[i].uv) for i in face.loop_indices]
    changed=set()
    for v in court.data.vertices:
        if abs(v.co.x)>source.LENGTH/2+.002:
            v.co.x=math.copysign(source.LENGTH/2+4.0,v.co.x);changed.add(v.index)
        if abs(v.co.y)>source.WIDTH/2+.002:
            v.co.y=math.copysign(source.WIDTH/2+4.0,v.co.y);changed.add(v.index)
        if abs(v.co.z)>1e-7:raise RuntimeError('Court height must remain zero')
    for loop in court.data.loops:
        if loop.vertex_index in changed:
            co=court.matrix_world@court.data.vertices[loop.vertex_index].co
            uv.data[loop.index].uv=((co.x+18)/56,(co.y+18)/36)
    court['apron_m']=4.0
    court['apron_scope']='Neutral visual plaza cover extent only; central NBA playing geometry and painted-art scale unchanged'
    court.data.update()
    if centre!=[court.data.vertices[i].co for i in face.vertices]:raise RuntimeError('Central court geometry changed')
    if before_uv!=[tuple(uv.data[i].uv) for i in face.loop_indices]:raise RuntimeError('Central court UV changed')
    CHANGES.append({'detail':'neutral plaza cover apron','apron_m':4.0,'changed_outer_grid_vertices':len(changed),
                    'world_bounds_m':[-source.LENGTH/2-4,source.LENGTH/2+4,-source.WIDTH/2-4,source.WIDTH/2+4],
                    'playing_face_coordinates_and_uv_exactly_preserved':True,'height_m':0.0,
                    'scope':'Photo artwork is not extended; source cover only, native depth bias owned by parent'})


def snapshot():
    result={}
    for obj in bpy.data.objects:
        if obj.get('current_photo_detail'):continue
        if obj.type not in ('MESH','CURVE','FONT','EMPTY'):continue
        h=hashlib.sha256();h.update(array('f',[v for row in obj.matrix_world for v in row]).tobytes())
        if obj.type=='MESH':
            co=array('f',[0.])*(len(obj.data.vertices)*3);obj.data.vertices.foreach_get('co',co);h.update(co.tobytes())
            ix=array('i',[0])*len(obj.data.loops);obj.data.loops.foreach_get('vertex_index',ix);h.update(ix.tobytes())
        elif obj.type=='FONT':h.update(obj.data.body.encode());h.update(str((obj.data.size,obj.data.extrude,obj.data.bevel_depth,obj.data.fill_mode)).encode())
        elif obj.type=='CURVE':
            h.update(str(obj.data.bevel_depth).encode())
            for spline in obj.data.splines:
                for p in spline.points:h.update(array('f',p.co).tobytes())
        result[obj.name]=h.hexdigest()
    return result


def renders():
    scene=bpy.context.scene;camera=scene.camera
    scene.render.engine='CYCLES';scene.cycles.samples=36;scene.cycles.use_denoising=True
    scene.render.resolution_x=1600;scene.render.resolution_y=1050;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    for name,pos,target,lens in (
        ('current-hoop-detail',(-10.5,-2.3,3.35),(-13.05,0,3.08),44),
        ('current-garden-detail',(8.5,-10.6,1.9),(5,-16.2,.45),43),
        ('current-chilis-detail',(-11,-3.5,3.9),(-21.,-.4,3.4),47),
        ('current-fence-detail',(-12.8,-5.1,1.15),(-16.1,-5.75,.38),52),
    ):
        camera.data.type='PERSP';camera.data.lens=lens;camera.location=pos
        camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
        scene.render.filepath=str(ROOT/'validation'/f'{name}.png');bpy.ops.render.render(write_still=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=str(ROOT/'source/scene.blend'));parser.add_argument('--render',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    output=Path(args.output).resolve()
    if not output.is_relative_to(ROOT):raise ValueError('Output outside project')
    if bpy.context.scene.get('detail_revision')=='Current photo-aligned support, fabric, Chili signage and planting detail':
        raise RuntimeError('This detail pass is already saved in the open scene. Export the source directly; do not regenerate it.')
    STAGE.mkdir(parents=True,exist_ok=True);backup=STAGE/'source-before.blend'
    if not backup.exists():shutil.copy2(bpy.data.filepath,backup)
    prefs=bpy.context.preferences.filepaths;prefs.temporary_directory=str(STAGE)
    prefs.file_preview_type='NONE';prefs.use_auto_save_temporary_files=False;prefs.save_version=0
    bpy.context.view_layer.update();before=snapshot()
    material_maps();supports();fence_cloth();chilis_signs();planting_detail();extend_visual_apron()
    bpy.context.view_layer.update();after=snapshot()
    unexpected=[n for n,h in before.items() if n not in ALLOWED and after.get(n)!=h]
    if unexpected:raise RuntimeError('Protected source geometry changed: '+str(unexpected))
    validation=source.validate_scene()
    if validation['status']!='passed':raise RuntimeError(json.dumps(validation))
    report={'status':'passed','changed_details':CHANGES,'allowed_changed_object_names':sorted(ALLOWED),
            'protected_objects_unchanged':len(before)-len(ALLOWED),'unexpected_geometry_changes':unexpected,
            'nba_geometry':validation,'artwork_files_written':False,'runtime_rim_net_written':False,
            'temporary_backup':str(backup),'source_output':str(output),'preview_notes':'Current source screenshots; runtime rim and cloth are separate game assets.'}
    bpy.context.scene['detail_revision']='Current photo-aligned support, fabric, Chili signage and planting detail'
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    (ROOT/'validation/current-detail-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('CURRENT_DETAILS_SAVED '+json.dumps({'source':str(output),'changed_objects':len(ALLOWED),'protected':report['protected_objects_unchanged']}),flush=True)
    if args.render:renders()


if __name__=='__main__':main()
