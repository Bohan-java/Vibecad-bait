"""R03 incremental material/fabrication detail pass on the OPEN source .blend.

Writes only project-local texture assets and a staging .blend. Existing geometry,
NBA anchors, court art, paving atlas and architecture layout remain protected.
The textures are actual PNGs with explicit R03Finish / R03Glass UV maps; the
new seams, fittings and net braids are real geometry exported through glTF.
"""
from __future__ import annotations
import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import sys
import zlib
import bpy
import numpy as np
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import refine_architecture_r02 as primitives
import create_scene as source

PI=math.pi
RNG=random.Random(260304)
TEXTURES=ROOT/'textures'/'r03'
BUILDERS={}
MATERIALS={}
TEXTURE_REPORT=[]


def srgb_hex(value):
    return tuple(int(value[i:i+2],16)/255 for i in (0,2,4))


def linear_hex(value):
    return tuple(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in srgb_hex(value))


def shader_for(mat):
    mat.use_nodes=True
    return next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')


def pbr(name,color,roughness=.7,metallic=0):
    mat=bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes=True
    shader=next((n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
    if shader is None:
        shader=mat.node_tree.nodes.new('ShaderNodeBsdfPrincipled')
        out=next((n for n in mat.node_tree.nodes if n.type=='OUTPUT_MATERIAL'),None) or mat.node_tree.nodes.new('ShaderNodeOutputMaterial')
        mat.node_tree.links.new(shader.outputs['BSDF'],out.inputs['Surface'])
    for key in ('Base Color','Roughness','Metallic','Normal'):
        for link in list(shader.inputs[key].links):mat.node_tree.links.remove(link)
    rgba=(*linear_hex(color),1)
    shader.inputs['Base Color'].default_value=rgba
    shader.inputs['Roughness'].default_value=roughness
    shader.inputs['Metallic'].default_value=metallic
    mat.diffuse_color=rgba
    mat.use_backface_culling=False
    MATERIALS[name]=mat
    return mat


def write_png(path,pixels):
    """Write a new deterministic procedural material map, not edit a photograph."""
    pixels=np.ascontiguousarray(np.clip(pixels,0,1)*255+.5,dtype=np.uint8)
    h,w,c=pixels.shape
    color_type=6 if c==4 else 2
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    raw=b''.join(b'\0'+pixels[row].tobytes() for row in range(h))
    payload=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,color_type,0,0,0))+chunk(b'IDAT',zlib.compress(raw,8))+chunk(b'IEND',b'')
    path.write_bytes(payload)
    TEXTURE_REPORT.append({'file':str(path.relative_to(ROOT)),'size':[w,h],'channels':c,'sha256':hashlib.sha256(payload).hexdigest()})
    return path


def field(rng,size,grid):
    small=rng.random((grid,grid))
    p=np.arange(size)*grid/size
    index=np.floor(p).astype(int)%grid
    t=p-np.floor(p);t=t*t*(3-2*t)
    a=small[index[:,None],index[None,:]]
    b=small[(index[:,None]+1)%grid,index[None,:]]
    c=small[index[:,None],(index[None,:]+1)%grid]
    d=small[(index[:,None]+1)%grid,(index[None,:]+1)%grid]
    return (a*(1-t[:,None])+b*t[:,None])*(1-t[None,:])+(c*(1-t[:,None])+d*t[:,None])*t[None,:]


def maps():
    TEXTURES.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(260303)
    n=512
    coarse=field(rng,n,22)-.5
    fine=field(rng,n,124)-.5
    grit=rng.random((n,n))-.5
    zinc=.063*coarse+.021*fine+.010*grit
    base=np.zeros((n,n,3))+np.array([.55,.575,.57])+zinc[:,:,None]
    rough=np.clip(.43+.14*coarse+.06*fine,.29,.58)
    metal=np.zeros((n,n))+.87
    write_png(TEXTURES/'steel-basecolor.png',base)
    write_png(TEXTURES/'steel-orm.png',np.stack((np.ones((n,n)),rough,metal),axis=-1))
    height=.08*coarse+.035*fine+.012*grit
    dx=np.roll(height,-1,axis=1)-np.roll(height,1,axis=1)
    dy=np.roll(height,-1,axis=0)-np.roll(height,1,axis=0)
    normal=np.stack((-dx*1.6,-dy*1.6,np.ones((n,n))),axis=-1)
    normal/=np.linalg.norm(normal,axis=2,keepdims=True)
    write_png(TEXTURES/'steel-normal.png',normal*.5+.5)
    coat_variation=.016*fine+.007*grit
    orange=np.zeros((n,n,3))+np.array(srgb_hex('D8582B'))+coat_variation[:,:,None]
    write_png(TEXTURES/'rim-paint-basecolor.png',orange)
    write_png(TEXTURES/'rim-paint-orm.png',np.stack((np.ones((n,n)),.30+.045*fine,np.ones((n,n))*.13),axis=-1))
    stone_noise=.037*field(rng,n,53)+.018*grit
    stone=np.zeros((n,n,3))+np.array(srgb_hex('A1A79C'))+stone_noise[:,:,None]
    write_png(TEXTURES/'curb-basecolor.png',stone)
    yy,xx=np.mgrid[0:n,0:n]/n
    grain=np.sin((xx*61+field(rng,n,8)*.32)*2*PI)*.017+fine*.013+grit*.006
    timber=np.zeros((n,n,3))+np.array(srgb_hex('76564A'))+grain[:,:,None]
    write_png(TEXTURES/'bench-timber-basecolor.png',timber)
    # Board edge contamination stays very restrained; clear central transparency
    # uses standard glTF alpha blending, not a Blender-only transparent mix node.
    h,w=256,512
    vv,uu=np.mgrid[0:h,0:w]/np.array([h-1,w-1])[:,None,None]
    border=np.exp(-np.minimum.reduce([uu,1-uu,vv,1-vv])*32)
    alpha=.115+.135*border
    board=np.zeros((h,w,4));board[:,:,:3]=np.array([.73,.84,.81]);board[:,:,3]=alpha
    write_png(TEXTURES/'backboard-clear-rgba.png',board)


def bind_image(mat,filename,kind,uv_name='R03Finish'):
    nodes=mat.node_tree.nodes;links=mat.node_tree.links
    uv=nodes.get('R03 explicit UV '+uv_name) or nodes.new('ShaderNodeUVMap')
    uv.name='R03 explicit UV '+uv_name;uv.uv_map=uv_name
    tex=nodes.get('R03 '+filename) or nodes.new('ShaderNodeTexImage')
    tex.name='R03 '+filename
    image=bpy.data.images.load(str(TEXTURES/filename),check_existing=True)
    image.colorspace_settings.name='sRGB' if kind in ('base','rgba') else 'Non-Color'
    tex.image=image;tex.extension='REPEAT';tex.interpolation='Linear'
    links.new(uv.outputs['UV'],tex.inputs['Vector'])
    shader=shader_for(mat)
    if kind in ('base','rgba'):
        links.new(tex.outputs['Color'],shader.inputs['Base Color'])
        if kind=='rgba':links.new(tex.outputs['Alpha'],shader.inputs['Alpha'])
    elif kind=='orm':
        split=nodes.new('ShaderNodeSeparateColor');split.name='R03 packed ORM channels'
        links.new(tex.outputs['Color'],split.inputs['Color'])
        links.new(split.outputs['Green'],shader.inputs['Roughness'])
        links.new(split.outputs['Blue'],shader.inputs['Metallic'])
    elif kind=='normal':
        normal=nodes.new('ShaderNodeNormalMap');normal.name='R03 baked tangent-space finish'
        normal.uv_map=uv_name;normal.inputs['Strength'].default_value=.23
        links.new(tex.outputs['Color'],normal.inputs['Color']);links.new(normal.outputs['Normal'],shader.inputs['Normal'])
    mat['r03_texture_uv']=uv_name
    return image


def box_uv(obj,name='R03Finish',scale=5):
    mesh=obj.data
    uv=mesh.uv_layers.get(name) or mesh.uv_layers.new(name=name)
    mesh.uv_layers.active=uv;uv.active_render=True
    normal_matrix=obj.matrix_world.to_3x3().inverted().transposed()
    for polygon in mesh.polygons:
        normal=(normal_matrix@polygon.normal).normalized()
        axis=max(range(3),key=lambda i:abs(normal[i]))
        axes=((1,2),(0,2),(0,1))[axis]
        for li in polygon.loop_indices:
            p=obj.matrix_world@mesh.vertices[mesh.loops[li].vertex_index].co
            uv.data[li].uv=(p[axes[0]]*scale,p[axes[1]]*scale)
    obj['finish_uv_channel']=name


def apply_finishes():
    steel=pbr('Hoops | brushed grey steel','8C9391',.43,.87)
    bind_image(steel,'steel-basecolor.png','base');bind_image(steel,'steel-orm.png','orm');bind_image(steel,'steel-normal.png','normal')
    paint=pbr('Hoops | vermilion rim','D8582B',.30,.13)
    bind_image(paint,'rim-paint-basecolor.png','base');bind_image(paint,'rim-paint-orm.png','orm')
    shader_for(paint).inputs['Coat Weight'].default_value=.24
    shader_for(paint).inputs['Coat Roughness'].default_value=.26
    pbr('R02 | galvanized bolt heads','A1A8A4',.31,.91)
    pbr('R02 | dark rubber lower rail','272D2A',.91,0)
    pbr('Hoops | white board markings','E6E8DF',.55,0)
    pbr('R02 | net off white','D9DACD',.91,0)
    pbr('R02 | net muted red','BB3941',.89,0)
    pbr('R02 | net navy','354F68',.88,0)
    curb=bpy.data.materials.get('R02 environment | curb')
    if curb:bind_image(curb,'curb-basecolor.png','base')
    timber=bpy.data.materials.get('R02 environment | timber')
    if timber:bind_image(timber,'bench-timber-basecolor.png','base')
    furniture=bpy.data.materials.get('R02 environment | furniture')
    if furniture:
        shader=shader_for(furniture);shader.inputs['Roughness'].default_value=.37;shader.inputs['Metallic'].default_value=.65
    glass=pbr('Hoops | transparent backboard','BBCFCC',.11,0)
    bind_image(glass,'backboard-clear-rgba.png','rgba','R03Glass')
    glass.surface_render_method='DITHERED';glass.use_transparency_overlap=False
    shader_for(glass).inputs['IOR'].default_value=1.50
    shader_for(glass).inputs['Coat Weight'].default_value=.16
    shader_for(glass).inputs['Coat Roughness'].default_value=.10
    mapped=[]
    for obj in bpy.data.objects:
        if obj.type!='MESH':continue
        used={m.name for m in obj.data.materials if m}
        if used & {'Hoops | brushed grey steel','Hoops | vermilion rim','R02 environment | curb','R02 environment | timber'}:
            box_uv(obj,scale=4.2 if 'R02 environment | timber' not in used else 2.0);mapped.append(obj.name)
        if obj.name.startswith('Backboard.'):
            uv=obj.data.uv_layers.get('R03Glass') or obj.data.uv_layers.new(name='R03Glass')
            obj.data.uv_layers.active=uv;uv.active_render=True
            for loop in obj.data.loops:
                p=obj.matrix_world@obj.data.vertices[loop.vertex_index].co
                uv.data[loop.index].uv=(p.y/source.BOARD_WIDTH+.5,(p.z-source.BOARD_BOTTOM)/source.BOARD_HEIGHT)
            obj['finish_uv_channel']='R03Glass';mapped.append(obj.name)
    return mapped


class DetailBatch(primitives.Batch):
    def __init__(self,name,mat,layer,smooth=True):
        super().__init__(name,mat,smooth)
        self.name='R03 '+name;self.layer=layer

    def tube(self,points,radius=.001,sides=4):
        points=[Vector(p) for p in points]
        vertices=[]
        for i,p in enumerate(points):
            tangent=(points[min(i+1,len(points)-1)]-points[max(i-1,0)]).normalized()
            u=tangent.cross(Vector((0,0,1)))
            if u.length<.01:u=tangent.cross(Vector((0,1,0)))
            u.normalize();v=tangent.cross(u).normalized()
            for j in range(sides):vertices.append(p+radius*(u*math.cos(j*2*PI/sides)+v*math.sin(j*2*PI/sides)))
        faces=[]
        for i in range(len(points)-1):
            for j in range(sides):faces.append((i*sides+j,i*sides+(j+1)%sides,(i+1)*sides+(j+1)%sides,(i+1)*sides+j))
        self.add(vertices,faces)

    def finish(self):
        if not self.vertices:return None
        mesh=bpy.data.meshes.new(self.name);mesh.from_pydata(self.vertices,[],self.faces);mesh.update()
        obj=bpy.data.objects.new(self.name,mesh)
        collection=bpy.data.collections[self.layer];collection.objects.link(obj)
        obj.parent=bpy.data.objects[self.layer]
        mesh.materials.append(self.mat)
        for face in mesh.polygons:face.use_smooth=self.smooth
        obj['r03_detail']=True;obj['layer']=self.layer
        obj['category']='hoops' if self.layer in ('reference_half','open_half') else 'background'
        obj['reference_images']='Existing court 07,11,14,15,16 and garden 20,22–26; small fabrication details inferred'
        obj['game_status']='Source visual detail; game verification not implied'
        box_uv(obj,scale=4.2)
        return obj


def batch(name,mat,layer='background',smooth=True):
    if name not in BUILDERS:BUILDERS[name]=DetailBatch(name,MATERIALS[mat] if isinstance(mat,str) else mat,layer,smooth)
    return BUILDERS[name]


def extra_materials():
    for name,color,rough,metal in (
        ('R03 | weld grey','6D7972',.53,.72),('R03 | steel edge highlights','AEB8B0',.29,.9),
        ('R03 | machining recess','303934',.75,.3),('R03 | glass green edge','628C81',.13,.08),
        ('R03 | clear seal gasket','242E29',.88,0),('R03 | braid off white','AFB5A6',.94,0),
        ('R03 | braid red','8D2933',.94,0),('R03 | braid navy','223B51',.93,0),
        ('R03 | drain cast iron','626D65',.72,.65),('R03 | drain recess','333D35',.98,0),
        ('R03 | leaf dry olive','777246',.97,0),('R03 | leaf warm tan','927C54',.98,0),
        ('R03 | small bed stones','94998A',.94,0),('R03 | flower soft ivory','E9E8D7',.89,0)
    ):pbr(name,color,rough,metal)


def hardware():
    for sign,suffix in ((-1,'reference'),(1,'open')):
        layer='reference_half' if sign<0 else 'open_half'
        pole=sign*(source.LENGTH/2+.95);board=sign*source.BOARD_X;rim=sign*source.RIM_X
        weld=batch('support weld beads.'+suffix,'R03 | weld grey',layer)
        bright=batch('machined collars and hex heads.'+suffix,'R03 | steel edge highlights',layer)
        recess=batch('bolt head recess marks.'+suffix,'R03 | machining recess',layer,False)
        # Small true fillet beads at the upright/base-plate joint.
        corners=[Vector((pole-.095,-.102,.045)),Vector((pole+.095,-.102,.045)),Vector((pole+.095,.102,.045)),Vector((pole-.095,.102,.045))]
        for a,b in zip(corners,corners[1:]+corners[:1]):
            edge=b-a
            for i in range(max(2,int(edge.length/.009))):
                p=a+edge*(i+.5)/max(2,int(edge.length/.009))
                weld.rod(p+Vector((-.003,0,-.001)),p+Vector((.003,0,.001)),.0045,.0036,6)
        for yy in (-.215,.215):
            for dx in (-.175,.175):
                p=Vector((pole+dx,yy,.062))
                bright.rod(p,p+Vector((0,0,.009)),.015,.015,6)
                recess.box(p+Vector((0,0,.0093)),(.017,.003,.0012))
        # Fastener relief and black washers on the existing board fixing points.
        for y in (-.76,.76):
            for z in (source.BOARD_BOTTOM+.12,source.BOARD_BOTTOM+source.BOARD_HEIGHT-.12):
                p=Vector((board-sign*.037,y,z))
                bright.rod(p,p+Vector((-sign*.007,0,0)),.0092,.0092,6)
                recess.rod(p+Vector((sign*.004,0,0)),p+Vector((sign*.006,0,0)),.016,.016,12)
        for y in (-.045,.045):
            for z in (2.944,3.015):
                p=Vector((board-sign*.073,y,z))
                bright.rod(p,p+Vector((-sign*.008,0,0)),.0085,.0085,6)
        # Shallow gussets sit behind/below the rim connection, outside aperture.
        gusset=batch('painted rim support gussets.'+suffix,bpy.data.materials['Hoops | vermilion rim'],layer,False)
        for y in (-.029,.029):
            points=[(board-sign*.068,y,2.933),(board-sign*.068,y,3.004),(rim+sign*.237,y,3.004)]
            gusset.add(points,[(0,1,2)])
        # Two-frame interfaces get restrained weld collars, not random rust.
        for position in ((pole,0,3.13),(pole,0,3.34)):
            p=Vector(position)
            for i in range(12):
                y=-.09+i*.016
                weld.rod((p.x-sign*.085,y,p.z-.07),(p.x-sign*.084,y+.006,p.z-.064),.0024,.0021,5)
        glass_edge=batch('backboard subtle green edge.'+suffix,'R03 | glass green edge',layer)
        gasket=batch('backboard frame seating gaskets.'+suffix,'R03 | clear seal gasket',layer)
        for y in (-source.BOARD_WIDTH/2+.012,source.BOARD_WIDTH/2-.012):
            glass_edge.box((board+sign*.005,y,source.BOARD_BOTTOM+source.BOARD_HEIGHT/2),(.012,.006,source.BOARD_HEIGHT-.028))
            gasket.box((board+sign*.013,y+math.copysign(.008,y),source.BOARD_BOTTOM+source.BOARD_HEIGHT/2),(.007,.005,source.BOARD_HEIGHT-.015))
        glass_edge.box((board+sign*.005,0,source.BOARD_BOTTOM+source.BOARD_HEIGHT-.013),(.012,source.BOARD_WIDTH-.04,.006))


def braids():
    material_names={0:'R03 | braid off white',1:'R03 | braid red',2:'R03 | braid navy'}
    curves=[obj for obj in bpy.data.objects if obj.type=='CURVE' and obj.name.startswith('R02 net ') and 'hook' not in obj.name]
    total=0
    for obj in curves:
        parts=obj.name.split('.')
        band=int(parts[-2]);suffix=parts[-1]
        layer='reference_half' if suffix=='reference' else 'open_half'
        builder=batch('woven net filament band '+str(band)+'.'+suffix,material_names[band],layer)
        points=[obj.matrix_world@p.co.to_3d() for p in obj.data.splines[0].points]
        length_so_far=0
        for first,last in zip(points,points[1:]):
            tangent=(last-first).normalized();length=(last-first).length
            u=tangent.cross(Vector((0,0,1))).normalized();v=tangent.cross(u).normalized()
            steps=max(3,math.ceil(length/.0044))
            for phase in (0,PI):
                coil=[]
                for i in range(steps+1):
                    t=i/steps;theta=(length_so_far+length*t)*2*PI/.014+phase
                    p=first.lerp(last,t)+.00247*(math.cos(theta)*u+math.sin(theta)*v)
                    coil.append(p)
                builder.tube(coil,.00047,4);total+=1
            length_so_far+=length
    return total


def small_environment():
    steel=batch('plaza drain grate bars','R03 | drain cast iron')
    void=batch('plaza drain dark slots','R03 | drain recess',smooth=False)
    for x,y,angle in ((8.2,-13.3,.11),(17.7,12.8,-.08),(22.0,5.65,.12)):
        void.box((x,y,.001),(.63,.17,.008),angle)
        for side in (-1,1):
            steel.box((x,y+side*.081,.006),(.64,.014,.012),angle)
        for i in range(16):
            dx=-.294+i*.0392
            p=(x+math.cos(angle)*dx,y+math.sin(angle)*dx,.008)
            steel.box(p,(.010,.16,.012),angle)
    screws=batch('canopy bench recessed fasteners','R03 | steel edge highlights')
    marks=batch('canopy bench screw slots','R03 | machining recess',smooth=False)
    for x,y,r in ((-8,13.1,2.9),(-6.2,16.0,3.05)):
        for j in range(20):
            a=.08*PI+j*.052
            for offset in (-.12,.12):
                xx=x+math.cos(a)*(r*.72+offset);yy=y+math.sin(a)*(r*.72+offset)
                screws.rod((xx,yy,.493),(xx,yy,.497),.0062,.0062,8)
                marks.box((xx,yy,.4975),(.008,.0017,.001),a)
    dry=[batch('small fallen olive leaves','R03 | leaf dry olive'),batch('small fallen tan leaves','R03 | leaf warm tan')]
    stones=batch('small flowerbed aggregate','R03 | small bed stones')
    # Restrained natural scatter immediately beside existing planted beds.
    for i in range(72):
        x=RNG.uniform(-3,15);y=-13.30+RNG.uniform(-.14,.20)
        if i%3==0:
            dry[i%2].leaf((x,y,.006),RNG.uniform(.055,.105),RNG.uniform(.025,.046),RNG.random()*2*PI,RNG.uniform(-.08,.14))
        else:
            a=RNG.random()*2*PI
            stones.lathe((x,y-.24,.019),[(0,-.013),(.017,-.008),(.022,.006),(.014,.019),(0,.023)],7)
    # A few individual petals at existing allium borders, not a new flower bed.
    petals=batch('allium fallen petal highlights','R03 | flower soft ivory')
    for i in range(35):
        x=RNG.uniform(-1,11);y=-13.45+RNG.uniform(-.08,.14)
        petals.leaf((x,y,.006),.018,.011,RNG.random()*2*PI,.07)


def snapshot():
    result={}
    for obj in sorted(bpy.data.objects,key=lambda o:o.name):
        if obj.get('r03_detail'):continue
        if obj.type not in ('MESH','CURVE','EMPTY'):continue
        digest=hashlib.sha256()
        digest.update(array('f',[v for row in obj.matrix_world for v in row]).tobytes())
        if obj.type=='MESH':
            co=array('f',[0.0])*(len(obj.data.vertices)*3);obj.data.vertices.foreach_get('co',co);digest.update(co.tobytes())
            vi=array('i',[0])*len(obj.data.loops);obj.data.loops.foreach_get('vertex_index',vi);digest.update(vi.tobytes())
        elif obj.type=='CURVE':
            digest.update(str(obj.data.bevel_depth).encode())
            for spline in obj.data.splines:
                for point in spline.points:digest.update(array('f',point.co).tobytes())
        result[obj.name]=digest.hexdigest()
    return result


def build():
    BUILDERS.clear();MATERIALS.clear();TEXTURE_REPORT.clear();RNG.seed(260304)
    for obj in list(bpy.data.objects):
        if obj.get('r03_detail'):bpy.data.objects.remove(obj,do_unlink=True)
    bpy.context.view_layer.update()
    before=snapshot()
    art_before={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT/'artwork'/'court.svg',ROOT/'artwork'/'paving-atlas.png',ROOT/'artwork'/'paving-atlas.svg')}
    maps();mapped=apply_finishes();extra_materials();hardware();strands=braids();small_environment()
    extras=[obj for builder in BUILDERS.values() if (obj:=builder.finish()) is not None]
    bpy.context.view_layer.update()
    after=snapshot()
    changed=[name for name in before if before[name]!=after.get(name)]
    if changed:raise RuntimeError('Original geometry changed: '+str(changed))
    geometry=source.validate_scene()
    if geometry['status']!='passed':raise RuntimeError(json.dumps(geometry))
    art_after={path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in art_before}
    if art_before!=art_after:raise RuntimeError('Court artwork or paving atlas changed')
    intrusion=[]
    for obj in extras:
        if obj.get('layer')!='background':continue
        for vertex in obj.data.vertices:
            p=obj.matrix_world@vertex.co
            if abs(p.x)<14.3256 and abs(p.y)<7.62 and p.z>.003:intrusion.append(obj.name);break
    if intrusion:raise RuntimeError('Environment detail intrudes into play area: '+str(intrusion))
    bpy.context.scene['detail_revision']='R03 metal / transparent board / woven net / fine landscape details'
    bpy.context.scene['source_version']='R03'
    return {'status':'passed','preserved_original_objects':len(before),'changed_original_geometry':changed,'nba_geometry':geometry,'artwork_unchanged':art_before==art_after,'new_detail_meshes':len(extras),'new_detail_vertices':sum(len(o.data.vertices) for o in extras),'net_twist_segments':strands,'explicitly_uv_mapped_existing_meshes':mapped,'textures':TEXTURE_REPORT,'environment_intrusions':intrusion,'game_note':'PNG base color / roughness / metallic maps and true geometry available. Fine tangent normal map is preview detail; game adapter may use neutral normal until tangent encoding is validated. Glass alpha and clearcoat require actual game material route verification.'}


def render(output):
    scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=56;scene.cycles.use_denoising=True
    scene.render.resolution_x=1600;scene.render.resolution_y=1100;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    camera=scene.camera;camera.data.type='PERSP'
    for name,position,target,lens in (
        ('r03-hoop-detail',(-10.5,-2.3,3.35),(-13.05,0,3.08),44),
        ('r03-support-detail',(-14.0,-1.1,1.15),(-15.25,0,.23),52),
        ('r03-garden-detail',(8.5,-10.6,1.9),(5,-16.2,.45),43)
    ):
        camera.location=position;camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.lens=lens
        scene.render.filepath=str(output.parent/(name+'.png'));bpy.ops.render.render(write_still=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=str(ROOT/'.build-staging'/'r03'/'scene-details.blend'));parser.add_argument('--render',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    output=Path(args.output).resolve()
    if ROOT not in output.parents:raise RuntimeError('Output must stay in project')
    # The user now requires retaining only the latest version. Historical
    # backups are not a prerequisite for this idempotent staged refinement.
    output.parent.mkdir(parents=True,exist_ok=True)
    runtime=output.parent/'runtime';runtime.mkdir(parents=True,exist_ok=True)
    prefs=bpy.context.preferences.filepaths;prefs.temporary_directory=str(runtime);prefs.file_preview_type='NONE';prefs.use_auto_save_temporary_files=False;prefs.save_version=0
    for image in bpy.data.images:
        if image.source=='FILE' and image.filepath:
            path=Path(bpy.path.abspath(image.filepath))
            if path.is_file():image.filepath=str(path)
    report=build()
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    (output.parent/'details-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('R03_DETAILS_READY '+json.dumps({'output':str(output),'status':report['status'],'new_meshes':report['new_detail_meshes'],'new_vertices':report['new_detail_vertices'],'preserved_objects':report['preserved_original_objects']}))
    if args.render:render(output)


if __name__=='__main__':main()
