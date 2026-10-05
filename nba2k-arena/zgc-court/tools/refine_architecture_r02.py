"""Incrementally correct Chili's / LINK architecture from the 13 new references.

Open the current .blend first. Default output is a staging file. Court, hoops,
fence and the completed garden are protected by before/after geometry hashes.
The drawings in the supplied reference pack are NOT treated as current surveys.
"""
from __future__ import annotations
import argparse
from array import array
import hashlib
import json
import math
import random
import sys
from pathlib import Path
import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
PI=math.pi
RNG=random.Random(261004)
MATERIALS={}
BATCHES={}
COLLECTION=None
PARENT=None
CX,CY,RX,RY=-27.1,-.8,6.2,15.4
BACK_X=-31.6


def rgb(hex_color):
    values=[int(hex_color[i:i+2],16)/255 for i in (0,2,4)]
    return tuple(v/12.92 if v<.04045 else ((v+.055)/1.055)**2.4 for v in values)


def material(name,color,rough=.75,metal=0,emission=0):
    key='R02 architecture | '+name
    mat=bpy.data.materials.get(key) or bpy.data.materials.new(key)
    mat.use_nodes=True
    nodes=mat.node_tree.nodes
    shader=next((n for n in nodes if n.type=='BSDF_PRINCIPLED'),None)
    if shader is None:
        shader=nodes.new('ShaderNodeBsdfPrincipled')
        out=next((n for n in nodes if n.type=='OUTPUT_MATERIAL'),None) or nodes.new('ShaderNodeOutputMaterial')
        mat.node_tree.links.new(shader.outputs['BSDF'],out.inputs['Surface'])
    rgba=(*rgb(color),1)
    shader.inputs['Base Color'].default_value=rgba
    shader.inputs['Roughness'].default_value=rough
    shader.inputs['Metallic'].default_value=metal
    if emission:
        shader.inputs['Emission Color'].default_value=rgba
        shader.inputs['Emission Strength'].default_value=emission
    mat.diffuse_color=rgba
    mat.use_backface_culling=False
    MATERIALS[name]=mat
    return mat


class Batch:
    def __init__(self,name,mat,smooth=False):
        self.name='R02 architecture '+name;self.mat=mat;self.smooth=smooth
        self.vertices=[];self.faces=[]

    def add(self,vertices,faces):
        offset=len(self.vertices)
        self.vertices.extend(tuple(v) for v in vertices)
        self.faces.extend(tuple(offset+i for i in f) for f in faces)

    def box(self,centre,size,angle=0):
        x,y,z=centre;a,b,c=[v*.5 for v in size]
        cs,sn=math.cos(angle),math.sin(angle)
        vertices=[]
        for xx,yy,zz in ((-a,-b,-c),(a,-b,-c),(a,b,-c),(-a,b,-c),(-a,-b,c),(a,-b,c),(a,b,c),(-a,b,c)):
            vertices.append((x+xx*cs-yy*sn,y+xx*sn+yy*cs,z+zz))
        self.add(vertices,((0,3,2,1),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7),(4,5,6,7)))

    def rod(self,p1,p2,r1,r2=None,segments=8):
        p1,p2=Vector(p1),Vector(p2);w=(p2-p1).normalized()
        u=w.cross(Vector((0,0,1)))
        if u.length<1e-6:u=w.cross(Vector((0,1,0)))
        u.normalize();v=w.cross(u).normalized()
        r2=r1 if r2 is None else r2
        vertices=[]
        for p,r in ((p1,r1),(p2,r2)):
            for i in range(segments):
                a=2*PI*i/segments
                vertices.append(p+(u*math.cos(a)+v*math.sin(a))*r)
        faces=[tuple(reversed(range(segments))),tuple(range(segments,segments*2))]
        faces += [(i,(i+1)%segments,(i+1)%segments+segments,i+segments) for i in range(segments)]
        self.add(vertices,faces)

    def lathe(self,centre,profile,segments=48):
        x,y,z=centre
        vertices=[(x+r*math.cos(i*2*PI/segments),y+r*math.sin(i*2*PI/segments),z+zz) for r,zz in profile for i in range(segments)]
        faces=[]
        for j in range(len(profile)-1):
            for i in range(segments):
                k=j*segments+i;n=j*segments+(i+1)%segments
                faces.append((k,n,n+segments,k+segments))
        self.add(vertices,faces)

    def leaf(self,p,length,width,angle,tilt):
        p=Vector(p)
        a=Vector((math.cos(angle)*math.cos(tilt),math.sin(angle)*math.cos(tilt),math.sin(tilt)))
        b=Vector((-math.sin(angle),math.cos(angle),0))
        self.add((p-a*length*.5,p+b*width*.5,p+a*length*.5,p-b*width*.5,p+a.cross(b)*.012),((0,4,1),(1,4,2),(2,4,3),(3,4,0)))

    def finish(self):
        if not self.vertices:return None
        data=bpy.data.meshes.new(self.name)
        data.from_pydata(self.vertices,[],self.faces);data.update()
        obj=bpy.data.objects.new(self.name,data)
        COLLECTION.objects.link(obj);obj.parent=PARENT
        data.materials.append(self.mat)
        for face in data.polygons:face.use_smooth=self.smooth
        mark(obj)
        return obj


def batch(name,mat,smooth=False):
    if name not in BATCHES:BATCHES[name]=Batch(name,MATERIALS[mat],smooth)
    return BATCHES[name]


def mark(obj):
    obj['r02_architecture']=True
    obj['layer']='background'
    obj['reference_pack']='references/chilis; 01 group photos 01–08 and 02 group real facade photos 01–02'
    obj['measurement_status']='Visual reconstruction; all site offsets, curvature and heights inferred, no measured survey'


def front(y,z=0,offset=0):
    t=max(-.999999,min(.999999,(y-CY)/RY))
    x=CX+RX*math.sqrt(1-t*t)
    derivative=-RX*t/(RY*math.sqrt(1-t*t))
    normal=Vector((1,-derivative,0)).normalized()
    tangent=Vector((derivative,1,0)).normalized()
    return Vector((x,y,z))+normal*offset,normal,tangent


def curved_strip(name,mat,y1,y2,z1,z2,offset=.025,segments=64):
    builder=batch(name,mat)
    vertices=[]
    for i in range(segments+1):
        y=y1+(y2-y1)*i/segments
        p,n,t=front(y,offset=offset)
        vertices.extend(((p.x,p.y,z1),(p.x,p.y,z2)))
    builder.add(vertices,[(i*2,i*2+2,i*2+3,i*2+1) for i in range(segments)])


def cornice(name,mat,y1,y2,z,height=.075,depth=.13,offset=.05,segments=76):
    builder=batch(name,mat,True)
    vertices=[]
    for i in range(segments+1):
        y=y1+(y2-y1)*i/segments
        p,n,t=front(y,z,offset)
        vertices += [p-n*depth/2+Vector((0,0,-height/2)),p+n*depth/2+Vector((0,0,-height/2)),p+n*depth/2+Vector((0,0,height/2)),p-n*depth/2+Vector((0,0,height/2))]
    faces=[]
    for i in range(segments):
        for j in range(4):faces.append((i*4+j,(i+1)*4+j,(i+1)*4+(j+1)%4,i*4+(j+1)%4))
    builder.add(vertices,faces)


def text(name,body,pos,size,mat,normal=Vector((1,0,0)),align='CENTER'):
    data=bpy.data.curves.new('R02 architecture '+name,'FONT')
    data.body=body;data.size=size;data.align_x=align;data.align_y='CENTER'
    data.extrude=.004;data.bevel_depth=.002;data.bevel_resolution=1
    obj=bpy.data.objects.new('R02 architecture '+name,data)
    COLLECTION.objects.link(obj);obj.parent=PARENT
    obj.location=pos
    obj.rotation_euler=(PI/2,0,math.atan2(normal.y,normal.x)+PI/2)
    data.materials.append(MATERIALS[mat]);mark(obj)
    return obj


def curved_label(name,body,y,z,size,mat):
    pos,n,t=front(y,z,.074)
    return text(name,body,pos,size,mat,n)


def make_chilis():
    low,high=CY-RY+.06,CY+RY-.06
    ys=[low+(high-low)*i/88 for i in range(89)]
    footprint=[(BACK_X,low)]+[(front(y)[0].x,y) for y in ys]+[(BACK_X,high)]
    shell=batch('Chilis curved low building shell','cladding')
    n=len(footprint)
    shell.add([(x,y,4.365) for x,y in footprint],[tuple(range(n))])
    # Plain unseen rear and end walls only. The arc is built separately below.
    for a,b in ((footprint[0],footprint[1]),(footprint[-2],footprint[-1]),(footprint[-1],footprint[0])):
        shell.add([(a[0],a[1],-3.7),(b[0],b[1],-3.7),(b[0],b[1],4.36),(a[0],a[1],4.36)],[(0,1,2,3)])
    curved_strip('Chilis lower storey conceptual glazing','lower_glass',low,high,-3.62,-.14,0,88)
    cornice('Chilis lower storey sill','metal',low,high,-.10,.18,.13)
    # At court level the restaurant occupies one low storey. The observed lower
    # street storey lies below z=0 and is retained as a volume, not exposed by
    # inventing an excavation through the already modeled flat plaza.
    for y1,y2 in ((low,7.2),(10.25,high)):
        curved_strip('Chilis dark curved glazing','glass',y1,y2,.10,3.145,.009,max(8,int((y2-y1)*4)))
    for y1,y2 in ((low,-6.45),(6.45,high)):
        curved_strip('Chilis upper pale glazing','clerestory',y1,y2,3.19,4.34,.013,max(8,int((y2-y1)*4)))
    curved_strip('Chilis local brown sign fascia','sign_brown',-6.45,6.45,3.19,4.34,.02,40)
    frames=batch('Chilis vertical glazing frames','frame')
    for i in range(23):
        y=low+(high-low)*i/22
        if 7.15<y<10.35:continue
        p,n,t=front(y,1.65,.049)
        frames.box(p,(.11,.058,3.05),math.atan2(n.y,n.x))
    for y in (-6.5,6.5):
        p,n,t=front(y,2.24,.12)
        frames.box(p,(.24,.18,4.47),math.atan2(n.y,n.x))
    fins=batch('Chilis fine upper vertical ribs','pale_metal')
    for i in range(164):
        y=low+(high-low)*i/163
        if -6.42<y<6.42:continue
        p,n,t=front(y,3.77,.045)
        fins.box(p,(.054,.026,1.10),math.atan2(n.y,n.x))
    for z in (.09,3.145,4.38,4.50,4.615):
        cornice('Chilis continuous silver curved cornice','metal',low,high,z,.08 if z>4 else .09,.15 if z>4 else .10)
    curved_label('Chilis principal orange identity',"chili's",-.65,3.75,.90,'neon_orange')
    curved_label('Chilis cafe descriptor','CAFE & BAR',-4.6,3.69,.215,'warm_letter')
    curved_label('Chilis establishment date','EST. 1975',4.4,3.68,.235,'warm_letter')
    # Small green apostrophe detail separates the logo from a plain red word.
    p,n,t=front(.28,4.10,.081)
    logo=batch('Chilis green apostrophe','logo_green',True)
    logo.rod(p+t*.08,p+t*.12+Vector((0,0,.15)),.026,.022,7)
    # Shallow observed roof projection; its interior function is deliberately not
    # assigned. Do not turn it into a tall second retail floor above the court.
    roof=batch('Chilis observed roof projection','roof_stone')
    roof.box((-27.0,-.35,4.89),(4.15,7.0,1.08))
    roof.box((-26.99,-.35,5.475),(4.32,7.23,.09))
    vents=batch('Chilis roof projection recessed panels','roof_panel')
    for yy in (-2.55,-.35,1.85):vents.box((-24.905,yy,4.92),(.016,1.43,.53))
    make_awning();make_alcove();make_terrace()


def make_awning():
    fabric=batch('Chilis cream fabric awning and scalloped valance','canvas')
    y1,y2=-6.1,6.15
    vertices=[];segments=64
    for i in range(segments+1):
        y=y1+(y2-y1)*i/segments
        for distance,z in ((.12,3.175),(1.06,3.045),(2.10,2.86)):
            p,n,t=front(y,z,distance)
            vertices.append(p)
    faces=[]
    for i in range(segments):
        faces.extend(((i*3,i*3+1,(i+1)*3+1,(i+1)*3),(i*3+1,i*3+2,(i+1)*3+2,(i+1)*3+1)))
    fabric.add(vertices,faces)
    valance=[]
    for i in range(segments+1):
        y=y1+(y2-y1)*i/segments
        p,n,t=front(y,2.86,2.101)
        valance.extend((p,p+Vector((0,0,-.175-.032*math.cos(i*PI/2)))))
    fabric.add(valance,[(i*2,i*2+1,i*2+3,i*2+2) for i in range(segments)])
    rails=batch('Chilis awning slender metal arms','awning_arm',True)
    for y in (-5.8,-3.0,0,3.0,5.8):
        a,n,t=front(y,3.14,.10);b,_,_=front(y,2.88,2.08)
        rails.rod(a,b,.025,segments=6)
    pos,n,t=front(-.6,2.785,2.12)
    text('Chilis awning wordmark',"chili's",pos,.23,'awning_print',n)


def oriented_wall(builder,p,tangent,normal,width,height,depth):
    builder.box(p,(depth,width,height),math.atan2(normal.y,normal.x))


def make_alcove():
    y=8.72;p,n,t=front(y)
    tile=batch('Chilis rust tile elevator alcove','rust_tile')
    # Recess: back, two return walls, soffit and plinth; front remains open.
    back=p-n*.89
    oriented_wall(tile,back+Vector((0,0,1.65)),t,n,3.03,3.30,.10)
    for side in (-1,1):
        centre=p-n*.40+t*side*1.50+Vector((0,0,1.65))
        oriented_wall(tile,centre,t,n,.10,3.3,1.01)
    oriented_wall(tile,p-n*.4+Vector((0,0,3.26)),t,n,3.10,.10,1.02)
    grout=batch('Chilis fine vertical tile joints','tile_grout')
    for i in range(43):
        pos=back+n*.057+t*(-1.46+i*2.92/42)+Vector((0,0,1.65))
        oriented_wall(grout,pos,t,n,.007,3.18,.003)
    for z in (.66,1.3,1.94,2.58):
        oriented_wall(grout,back+n*.058+Vector((0,0,z)),t,n,3.00,.007,.004)
    door=batch('Chilis brushed elevator doors','elevator',True)
    trim=batch('Chilis elevator trim','metal')
    for side in (-1,1):
        centre=back+n*.087+t*(-.68+side*.234)+Vector((0,0,1.27))
        oriented_wall(door,centre,t,n,.463,2.35,.024)
    for offset in (-1.195,-.165):
        oriented_wall(trim,back+n*.087+t*offset+Vector((0,0,1.28)),t,n,.061,2.45,.055)
    oriented_wall(trim,back+n*.087+t*(-.68)+Vector((0,0,2.50)),t,n,1.13,.065,.056)
    label_pos=back+n*.075+t*.61+Vector((0,0,1.92))
    text('Chilis alcove secondary logo',"chili's",label_pos,.38,'neon_orange',n)
    text('Chilis alcove cafe descriptor','CAFE & BAR',label_pos+Vector((0,0,-.32)),.132,'warm_letter',n)
    text('Chilis alcove date','EST. 1975',label_pos+Vector((0,0,-.51)),.125,'warm_letter',n)
    controls=batch('Chilis small lift control plate','frame')
    oriented_wall(controls,back+n*.10+t*(-.06)+Vector((0,0,1.17)),t,n,.075,.24,.026)


def make_terrace():
    deck=batch('Chilis narrow restaurant terrace','terrace')
    vertices=[];segments=76
    low,high=-12.5,13.0
    for i in range(segments+1):
        y=low+(high-low)*i/segments
        for offset in (.10,3.25):
            p,n,t=front(y,.033,offset);vertices.append(p)
    deck.add(vertices,[(i*2,i*2+1,i*2+3,i*2+2) for i in range(segments)])
    edge=batch('Chilis terrace low rounded curb','terrace_edge',True)
    joints=batch('Chilis terrace fine paving joints','terrace_joint')
    for i in range(76):
        y=low+(high-low)*i/76;y2=low+(high-low)*(i+1)/76
        a,n,t=front(y,.018,3.25);b,_,_=front(y2,.018,3.25)
        edge.rod(a,b,.037,segments=8)
    for i in range(38):
        y=low+(high-low)*i/37
        a,n,t=front(y,.034,.16);b,_,_=front(y,.034,3.14)
        joints.rod(a,b,.0035,segments=4)
    # Three intimate outdoor settings below the cream awning.
    tops=batch('Chilis terrace dark cafe tables','wood',True)
    steel=batch('Chilis terrace cafe furniture frames','furniture',True)
    wicker=batch('Chilis terrace red brown chair slats','wicker')
    for yy in (-4.4,-.6,3.25):
        p,n,t=front(yy,offset=1.43)
        tops.lathe(p,[(0,.785),(.36,.785),(.365,.76),(.36,.727),(0,.727)],40)
        steel.rod(p+Vector((0,0,.08)),p+Vector((0,0,.73)),.045,segments=8)
        for a in (0,2*PI/3,4*PI/3):
            steel.rod(p+Vector((0,0,.12)),p+Vector((math.cos(a)*.30,math.sin(a)*.30,.055)),.023,segments=6)
        for side in (-1,1):
            c=p+t*.64*side
            angle=math.atan2(t.y*side,t.x*side)
            wicker.box(c+Vector((0,0,.44)),(.39,.39,.047),angle)
            outward=t*side
            for k in range(5):
                centre=c+outward*.20+Vector((0,0,.62+k*.046))
                wicker.box(centre,(.028,.40,.028),angle)
            for dx in (-.16,.16):
                for dy in (-.15,.15):
                    q=c+Vector((math.cos(angle)*dx-math.sin(angle)*dy,math.sin(angle)*dx+math.cos(angle)*dy,.08))
                    steel.rod(q,q+Vector((0,0,.34)),.015,segments=5)
    # Folded neutral parasols, visible in new image 07; no snow transplanted.
    cloth=batch('Chilis folded terrace parasols','canvas')
    for y in (-2.55,5.5):
        p,n,t=front(y,offset=2.4)
        steel.rod(p,p+Vector((0,0,2.72)),.021,segments=8)
        cloth.lathe(p,[(.06,.87),(.23,1.16),(.17,1.79),(.05,2.64),(0,2.69)],18)
    pots=batch('Chilis terrace planters','pot')
    leaves=batch('Chilis terrace planter foliage','plant',True)
    for yy in (-10,-7.6,11.9):
        p,n,t=front(yy,offset=1.70)
        pots.box(p+Vector((0,0,.22)),(.55,1.22,.44),math.atan2(n.y,n.x))
        for k in range(160):
            q=p+n*RNG.uniform(-.2,.2)+t*RNG.uniform(-.55,.55)+Vector((0,0,RNG.uniform(.43,.82)))
            leaves.leaf(q,RNG.uniform(.10,.18),RNG.uniform(.045,.07),RNG.random()*2*PI,RNG.uniform(-.3,.8))
    # Local transparent terrace guard only around the observed outer side walk;
    # it does not extend the basketball fence or enclose the open half.
    rail=batch('Chilis terrace side-walk handrail','metal',True)
    glass=batch('Chilis terrace side-walk glass guard','guard_glass')
    for i in range(15):
        y=8.0+i*.45;y2=8.0+(i+1)*.45
        p,n,t=front(y,offset=4.5);q,_,_=front(y2,offset=4.5)
        rail.rod(p+Vector((0,0,1.04)),q+Vector((0,0,1.04)),.028,segments=8)
        if i%3==0:rail.rod(p,p+Vector((0,0,1.07)),.027,segments=8)
        glass.add([p+Vector((0,0,.12)),q+Vector((0,0,.12)),q+Vector((0,0,.96)),p+Vector((0,0,.96))],[(0,1,2,3)])
    # A small pale tiered fountain is visible in new 07. Scale/position inferred.
    p,n,t=front(-8.0,offset=2.12)
    stone=batch('Chilis small observed tiered fountain','fountain',True)
    stone.lathe(p,[(0,.08),(.61,.08),(.65,.20),(.66,.37),(.56,.43),(.52,.27),(.14,.27),(.12,.98),(.06,1.09),(0,1.1)],48)
    for radius,z in ((.34,.62),(.24,.85),(.14,1.05)):
        stone.lathe(p,[(.05,z-.09),(radius*.87,z-.025),(radius,z),(radius,z+.045),(.05,z+.02)],40)
    water=batch('Chilis fountain muted blue basin','water')
    water.lathe(p,[(0,.285),(.52,.285)],40)
    bollards=batch('Chilis low walkway bollards','bollard',True)
    for y in (-11.2,-7,6.8,10.7,13.6):
        p,n,t=front(y,offset=3.8)
        bollards.rod(p,p+Vector((0,0,.70)),.065,segments=10)


def make_link():
    # Independent large background mass: a real geometric lane separates its
    # nearest face (-36m) from the restaurant rear (-31.6m). 4.4m is provisional.
    body=batch('LINK separate large pale mall volume','link_stone')
    body.box((-42.0,0,4.15),(12,36,16.1))
    front_x=-35.985
    panel_mats=['link_stone','link_stone_light','link_stone_dark']
    for row in range(22):
        z=-.6+row*.58
        for col in range(30):
            y=-17.4+col*1.18
            mat=panel_mats[(row*17+col*7)%11%3]
            batch('LINK individual cladding tone '+mat,mat).box((front_x,y,z),(.045,1.166,.569))
    shadow=batch('LINK recessed glazing bays','link_glass')
    fins=batch('LINK structural bays and projecting ledges','link_frame')
    for yy,width in ((-12.3,3.7),(8.8,4.8)):
        for z in (1.15,3.65,6.15,8.65):
            shadow.box((front_x+.040,yy,z),(.032,width,1.84))
            fins.box((front_x+.17,yy,z-1.0),(.44,width+.3,.16))
            for dy in (-width*.5,0,width*.5):
                fins.box((front_x+.09,yy+dy,z),(.13,.048,1.88))
    red=batch('LINK independent upper red fascia','link_red')
    red.box((front_x+.075,-2.5,10.20),(.12,30.6,1.15))
    fins.box((front_x+.30,0,12.2),(.80,36.8,.20))
    shadow.box((front_x+.054,-2.0,11.3),(.04,31.4,.64))
    for y in range(-16,16,2):fins.box((front_x+.096,y,11.3),(.10,.052,.68))
    text('LINK rear high red band identity','LINK PLAZA',(front_x+.151,-2.0,10.18),.89,'link_letter')
    # The documented glass corner belongs to LINK. The pre-existing distant
    # office tower remains a separate object of unconfirmed identity.
    corner=batch('LINK integrated glazed corner','link_corner_glass')
    corner.box((-39.4,19.6,5.15),(8.4,5.2,18.0))
    corner_frame=batch('LINK glass corner fine mullions','link_corner_frame')
    for yy in (17.15,18.0,18.85,19.7,20.55,21.4,22.18):
        corner_frame.box((-35.18,yy,5.15),(.055,.035,17.9))
    for zz in (-2.9,-1.5,0,1.5,3,4.5,6,7.5,9,10.5,12,13.9):
        corner_frame.box((-35.175,19.6,zz),(.065,5.18,.04))
    for xx in (-43.55,-42.2,-40.8,-39.4,-38,-36.6,-35.2):
        corner_frame.box((xx,22.225,5.15),(.035,.06,17.9))
    for zz in (-2.9,-1.5,0,1.5,3,4.5,6,7.5,9,10.5,12,13.9):
        corner_frame.box((-39.4,22.226,zz),(8.35,.06,.035))
    red.box((-35.13,17.0,5.75),(.11,.22,15.8))


def outdated(obj):
    old_prefixes=('Mall principal volume','Mall horizontal warm red band','Mall roof overhang','Mall clerestory glazing','Mall storefront fascia','Storefront glass ','Storefront mullion ','Mall upper horizontal joint ','Mall pilaster ','Chilis storefront sign','Chilis cafe descriptor','Mall Link Plaza sign','Chilis awning','R02 detached provisional LINK','R02 provisional detached LINK')
    return bool(obj.get('r02_architecture')) or obj.name.startswith(old_prefixes)


def geometry_fingerprint(objects):
    digest=hashlib.sha256()
    for obj in sorted(objects,key=lambda o:o.name):
        digest.update(obj.name.encode('utf-8'))
        digest.update(array('f',[value for row in obj.matrix_world for value in row]).tobytes())
        if obj.type=='MESH':
            positions=array('f',[0.0])*(len(obj.data.vertices)*3)
            obj.data.vertices.foreach_get('co',positions)
            digest.update(positions.tobytes())
            indices=array('i',[0])*len(obj.data.loops)
            obj.data.loops.foreach_get('vertex_index',indices)
            digest.update(indices.tobytes())
    return digest.hexdigest()


def build():
    global COLLECTION,PARENT
    COLLECTION=bpy.data.collections.get('background');PARENT=bpy.data.objects.get('background')
    if COLLECTION is None or PARENT is None:raise RuntimeError('Open the saved project .blend first')
    BATCHES.clear();MATERIALS.clear();RNG.seed(261004)
    bpy.context.view_layer.update()
    protected=[obj for obj in bpy.data.objects if obj.type=='MESH' and not outdated(obj)]
    before=geometry_fingerprint(protected)
    removed=[]
    for obj in list(bpy.data.objects):
        if outdated(obj):removed.append(obj.name);bpy.data.objects.remove(obj,do_unlink=True)
    palettes={
        'cladding':('A2A7A0',.76,0),'glass':('445D62',.17,.38),'lower_glass':('394C51',.27,.25),
        'clerestory':('7F9694',.42,.35),'frame':('485354',.51,.55),'metal':('A6AEA7',.40,.58),
        'pale_metal':('A1ABA4',.57,.40),'sign_brown':('614A48',.68,.05),'neon_orange':('F97323',.43,.12),
        'warm_letter':('E0D9BF',.49,.1),'logo_green':('62B749',.39,.05),'roof_stone':('BFBEAC',.84,0),'roof_panel':('99998B',.86,0),
        'canvas':('D2C1A1',.92,0),'awning_arm':('626D66',.53,.5),'awning_print':('433C31',.88,0),
        'rust_tile':('985B43',.40,.05),'tile_grout':('B17453',.74,0),'elevator':('A1A7A5',.27,.87),
        'terrace':('B7BAAF',.96,0),'terrace_edge':('9FA99F',.86,0),'terrace_joint':('98A298',.96,0),
        'wood':('61463C',.79,0),'furniture':('3D4441',.51,.45),'wicker':('774E41',.91,0),'pot':('784C3D',.86,0),'plant':('517146',.91,0),
        'guard_glass':('ABBDB7',.2,.18),'fountain':('D0D2C6',.7,0),'water':('466C7E',.18,.25),'bollard':('43514C',.61,.35),
        'link_stone':('C3BA9D',.86,0),'link_stone_light':('C7BEA4',.86,0),'link_stone_dark':('BEB59B',.86,0),
        'link_glass':('36535D',.27,.3),'link_frame':('A4AA9C',.65,.35),'link_red':('BE4E35',.72,.05),
        'link_letter':('DFE0D5',.58,.12),'link_blue':('466A9B',.61,.12),'link_corner_glass':('759D9E',.23,.33),'link_corner_frame':('728D89',.59,.45)
    }
    for name,(color,rough,metal) in palettes.items():material(name,color,rough,metal,.24 if name=='neon_orange' else 0)
    make_chilis();make_link()
    new=[obj for builder in BATCHES.values() if (obj:=builder.finish()) is not None]
    # Physical glass guards use alpha; building glazing remains opaque PBR to
    # avoid layers of transparency and invented restaurant interiors.
    glass=MATERIALS['guard_glass']
    shader=next(n for n in glass.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    shader.inputs['Alpha'].default_value=.21
    glass.diffuse_color=(*rgb('ABBDB7'),.21)
    glass.surface_render_method='DITHERED'
    bpy.context.view_layer.update()
    after=geometry_fingerprint(protected)
    if before!=after:raise RuntimeError('Protected court / hoops / fence / garden geometry changed')
    intrusion=[]
    for obj in new:
        for v in obj.data.vertices:
            p=obj.matrix_world@v.co
            if abs(p.x)<14.3256 and abs(p.y)<7.62 and p.z>0:
                intrusion.append(obj.name);break
    if intrusion:raise RuntimeError('Architecture enters gameplay rectangle: '+str(intrusion))
    bpy.context.scene['architecture_revision']='R02 architecture corrected from supplied 13-image Chili\'s/LINK package'
    bpy.context.scene['site_elevation_status']='Upper court/terrace kept at z=0; lower storey volume below, surrounding true site levels not completely reconstructed'
    report={
        'status':'passed','removed_old_architecture_objects':removed,'new_batched_meshes':len(new),
        'new_mesh_vertices':sum(len(o.data.vertices) for o in new),'protected_mesh_objects':len(protected),
        'protected_geometry_sha256_before':before,'protected_geometry_sha256_after':after,'protected_geometry_unchanged':before==after,
        'raised_architecture_inside_playing_area':intrusion,
        'source_evidence':{
            'chilis_curve_glazing_cornice':['new 01/01','new 01/02','new 01/03','new 01/04','new 01/07'],
            'brown_sign_canvas_terrace':['new 01/02','new 01/04','new 01/05','new 01/07'],
            'rust_alcove':['new 01/08'],
            'link_separate_behind':['new 01/05','new 01/06','old part1/07','old part1/10'],
            'link_mass_material':['new 02/01 actual facade photograph','new 02/02 actual glazed-corner photograph']},
        'inferred_parameters_m':{'chilis_frontmost_x':CX+RX,'chilis_rear_x':BACK_X,'chilis_upper_storey_cornice_z':4.615,'chilis_local_roof_projection_top':5.52,'link_nearest_face_x':-36,'minimum_chilis_rear_to_link_front_gap':4.4},
        'limits':['Curvature, heights, relative shifts and site gaps are visual inferences, not measurements.','Lower public street/storey exists as a volume below the court level; full site elevation changes are not reconstructed.','Old satellite maps and design plans were not treated as current aerial evidence.','Distant glass office tower retains unconfirmed identity and is not the LINK mall.','Court, hoop, fence and garden mesh geometry are unchanged; no game output or game validation performed.']}
    return report


def render(output):
    scene=bpy.context.scene
    scene.render.engine='CYCLES';scene.cycles.samples=36;scene.cycles.use_denoising=True
    scene.render.resolution_x=1700;scene.render.resolution_y=1100;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    camera=scene.camera;camera.data.type='PERSP';camera.data.lens=40
    camera.location=(32,-37,26)
    camera.rotation_euler=(Vector((-10,1,2.4))-camera.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=str(output.parent/'architecture-overview.png');bpy.ops.render.render(write_still=True)
    camera.location=(-4.0,-6.8,2.05);camera.data.lens=27
    camera.rotation_euler=(Vector((-23,.8,3.0))-camera.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=str(output.parent/'architecture-front.png');bpy.ops.render.render(write_still=True)


def main():
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default=str(ROOT/'.build-staging'/'r02'/'scene-architecture.blend'))
    parser.add_argument('--render',action='store_true')
    args=parser.parse_args(argv);output=Path(args.output).resolve()
    if ROOT not in output.parents:raise RuntimeError('Output must stay inside project')
    output.parent.mkdir(parents=True,exist_ok=True)
    runtime=ROOT/'.build-staging'/'r02'/'runtime';runtime.mkdir(parents=True,exist_ok=True)
    bpy.context.preferences.filepaths.temporary_directory=str(runtime)
    bpy.context.preferences.filepaths.file_preview_type='NONE'
    bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
    bpy.context.preferences.filepaths.save_version=0
    for image in bpy.data.images:
        if image.source=='FILE' and image.filepath:
            absolute=bpy.path.abspath(image.filepath)
            if Path(absolute).is_file():image.filepath=absolute
    report=build()
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    (output.parent/'architecture-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('R02_ARCHITECTURE_READY '+json.dumps({'output':str(output),'status':report['status'],'new_meshes':report['new_batched_meshes'],'protected_unchanged':report['protected_geometry_unchanged']}))
    if args.render:render(output)


if __name__=='__main__':main()
