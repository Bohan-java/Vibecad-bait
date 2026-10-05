"""Incremental R02 environment refinement of the OPEN .blend.

Never regenerates court/hoop/fence geometry. The default save is a staging file.
Run: blender --background source/scene.blend --python-exit-code 1
     --python tools/refine_environment_r02.py -- --output <staging.blend>
Optional --render writes two review renders beside the staging .blend.
All landscape placement remains inferred from photos 03,15,20,22–26.
"""
from __future__ import annotations
import argparse
import json
import math
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
RNG=random.Random(260326)
COLLECTION=None
PARENT=None
MATS={}
BATCHES={}
PI=math.pi


def linear(hex_value):
    rgb=[int(hex_value[i:i+2],16)/255 for i in (0,2,4)]
    return tuple(c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in rgb)


def mat(name,color,rough=.82,metal=0):
    full='R02 environment | '+name
    m=bpy.data.materials.get(full) or bpy.data.materials.new(full)
    m.use_nodes=True
    p=next((n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
    if p is None:
        p=m.node_tree.nodes.new('ShaderNodeBsdfPrincipled')
        out=next((n for n in m.node_tree.nodes if n.type=='OUTPUT_MATERIAL'),None) or m.node_tree.nodes.new('ShaderNodeOutputMaterial')
        m.node_tree.links.new(p.outputs['BSDF'],out.inputs['Surface'])
    rgba=(*linear(color),1)
    p.inputs['Base Color'].default_value=rgba
    p.inputs['Roughness'].default_value=rough
    p.inputs['Metallic'].default_value=metal
    m.diffuse_color=rgba
    m.use_backface_culling=False
    MATS[name]=m
    return m


class MeshBatch:
    def __init__(self,name,material,smooth=False):
        self.name=name; self.material=material; self.smooth=smooth
        self.v=[];self.f=[]

    def geometry(self,vertices,faces):
        offset=len(self.v)
        self.v.extend(tuple(v) for v in vertices)
        self.f.extend(tuple(i+offset for i in face) for face in faces)

    def box(self,center,size,angle=0):
        x,y,z=center; a,b,c=[s/2 for s in size]
        cs,sn=math.cos(angle),math.sin(angle)
        verts=[]
        for dx,dy,dz in ((-a,-b,-c),(a,-b,-c),(a,b,-c),(-a,b,-c),(-a,-b,c),(a,-b,c),(a,b,c),(-a,b,c)):
            verts.append((x+cs*dx-sn*dy,y+sn*dx+cs*dy,z+dz))
        self.geometry(verts,((0,3,2,1),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7),(4,5,6,7)))

    def rod(self,start,end,r1,r2=None,sides=6):
        a,b=Vector(start),Vector(end)
        tangent=b-a
        if tangent.length<1e-6:return
        w=tangent.normalized()
        u=w.cross(Vector((0,0,1)))
        if u.length<1e-6:u=w.cross(Vector((0,1,0)))
        u.normalize();v=w.cross(u).normalized()
        r2=r1 if r2 is None else r2
        vertices=[]
        for p,r in ((a,r1),(b,r2)):
            for i in range(sides):
                angle=2*PI*i/sides
                vertices.append(p+r*(u*math.cos(angle)+v*math.sin(angle)))
        faces=[tuple(reversed(range(sides))),tuple(range(sides,2*sides))]
        faces.extend((i,(i+1)%sides,(i+1)%sides+sides,i+sides) for i in range(sides))
        self.geometry(vertices,faces)

    def polyline(self,points,radius=.01,sides=5):
        for a,b in zip(points,points[1:]):self.rod(a,b,radius,sides=sides)

    def leaf(self,center,length,width,azimuth,tilt=.25,roll=0):
        """Five-point folded leaf, a shaped surface rather than a round blob."""
        p=Vector(center)
        axis=Vector((math.cos(azimuth)*math.cos(tilt),math.sin(azimuth)*math.cos(tilt),math.sin(tilt)))
        side=Vector((-math.sin(azimuth),math.cos(azimuth),0))
        normal=axis.cross(side).normalized()
        sideways=side*math.cos(roll)+normal*math.sin(roll)
        ridge=normal*width*.14
        vertices=(p-axis*length*.48,p+sideways*width*.5,p+axis*length*.55,p-sideways*width*.5,p+ridge)
        self.geometry(vertices,((0,4,1),(1,4,2),(2,4,3),(3,4,0)))

    def ellipsoid(self,center,radii,segments=8,rings=4):
        cx,cy,cz=center;rx,ry,rz=radii
        verts=[]
        for j in range(rings+1):
            b=PI*j/rings
            for i in range(segments):
                a=2*PI*i/segments
                verts.append((cx+rx*math.sin(b)*math.cos(a),cy+ry*math.sin(b)*math.sin(a),cz+rz*math.cos(b)))
        faces=[]
        for j in range(rings):
            for i in range(segments):
                k=j*segments+i;n=j*segments+(i+1)%segments
                faces.append((k,n,n+segments,k+segments))
        self.geometry(verts,faces)

    def lathe(self,center,profile,segments=64):
        cx,cy,cz=center
        verts=[(cx+r*math.cos(2*PI*i/segments),cy+r*math.sin(2*PI*i/segments),cz+z) for r,z in profile for i in range(segments)]
        faces=[]
        for j in range(len(profile)-1):
            for i in range(segments):
                k=j*segments+i;n=j*segments+(i+1)%segments
                faces.append((k,n,n+segments,k+segments))
        self.geometry(verts,faces)

    def finish(self):
        if not self.v:return None
        mesh=bpy.data.meshes.new(self.name)
        mesh.from_pydata(self.v,[],self.f);mesh.update()
        obj=bpy.data.objects.new(self.name,mesh)
        COLLECTION.objects.link(obj);obj.parent=PARENT
        mesh.materials.append(self.material)
        if self.smooth:
            for polygon in mesh.polygons:polygon.use_smooth=True
        obj['r02_environment']=True
        obj['layer']='background'
        obj['reference_images']='03,15,20,22,23,24,25,26'
        obj['layout_confidence']='Photo-supported forms; exact size and spacing inferred'
        return obj


def batch(name,material,smooth=False):
    if name not in BATCHES:BATCHES[name]=MeshBatch(name,MATS[material],smooth)
    return BATCHES[name]


def curve_polygon(cx,cy,rx,ry,angle,seed,count=96):
    rand=random.Random(seed)
    phase=rand.uniform(0,2*PI)
    points=[]
    for i in range(count):
        a=i*2*PI/count
        wobble=1+.068*math.sin(3*a+phase)+.031*math.sin(5*a-phase)
        x=math.cos(a)*rx*wobble;y=math.sin(a)*ry*wobble
        points.append((cx+x*math.cos(angle)-y*math.sin(angle),cy+x*math.sin(angle)+y*math.cos(angle)))
    return points


def organic_bed(index,cx,cy,rx,ry,angle):
    points=curve_polygon(cx,cy,rx,ry,angle,index+81)
    soil=batch('R02 organic planted ground','soil')
    soil.geometry([(x,y,.062) for x,y in points],[tuple(range(len(points)))])
    # Continuous low living groundcover under the taller planting. A gently
    # uneven leafy base replaces the bare, perfectly flat dark blockout soil.
    cover=batch('R02 continuous low garden groundcover','groundcover',True)
    vertices=[(cx,cy,.145)]
    rings=13;n=len(points)
    for ring in range(1,rings+1):
        t=ring/rings
        for i,(x,y) in enumerate(points):
            xx=cx+(x-cx)*t;yy=cy+(y-cy)*t
            z=.082+(.045+.026*math.sin(xx*2.2)*math.cos(yy*2.7))*(1-t*t)
            vertices.append((xx,yy,z))
    faces=[(0,1+i,1+(i+1)%n) for i in range(n)]
    for ring in range(rings-1):
        first=1+ring*n
        for i in range(n):
            j=(i+1)%n
            faces.append((first+i,first+i+n,first+j+n,first+j))
    cover.geometry(vertices,faces)
    curb=batch('R02 curving raised stone edges','curb')
    n=len(points)
    verts=[]
    for i,(x,y) in enumerate(points):
        tangent=Vector(points[(i+1)%n])-Vector(points[(i-1)%n])
        normal=Vector((tangent.y,-tangent.x)).normalized()
        # Chamfered top and definite thickness are visible at walk-up distance.
        for offset,z in ((-.015,-.012),(.12,-.012),(.12,.098),(.10,.123),(.00,.123),(-.015,.098)):
            verts.append((x+normal.x*offset,y+normal.y*offset,z))
    faces=[]
    for i in range(n):
        for j in range(6):
            faces.append((i*6+j,((i+1)%n)*6+j,((i+1)%n)*6+(j+1)%6,i*6+(j+1)%6))
    curb.geometry(verts,faces)
    # Inset dark expansion joints at plausible stone lengths, separate from court.
    joints=batch('R02 curb expansion joints','joint')
    for i in range(0,n,4):
        x,y=points[i];xn,yn=points[(i+1)%n]
        tangent=Vector((xn-x,yn-y));theta=math.atan2(tangent.y,tangent.x)
        joints.box((x,y,.124),(.011,.14,.003),theta)
    return points


def within_gameplay(x,y,margin=1.86):
    return abs(x)<14.3256+margin and abs(y)<7.62+margin


def paving():
    base=batch('R02 continuous pale plaza ground','pale_paving')
    base.box((-3,11,-.052),(96,86,.10))
    # Seam and stone inserts belong only to the surrounding plaza, never the NBA
    # playing rectangle or its one-piece apron. They do not become ground lines.
    seams=batch('R02 exterior stone fine joints','paving_joint')
    for y in range(-25,39,2):
        for x in range(-25,41,2):
            if within_gameplay(x,y,2.3):continue
            if x<-19 and abs(y)<18:continue
            seams.box((x,y,-.001),(1.992,.011,.001))
            seams.box((x-1,y+1,-.001),(.011,1.992,.001))
    inserts=batch('R02 scattered grey stone inserts','stone_insert')
    for i in range(86):
        x=RNG.uniform(-17,38);y=RNG.uniform(-25,36)
        if within_gameplay(x,y,3):continue
        if abs(y)<8 and x<18:continue
        inserts.box((x,y,-.0008),(.28,.49,.001))
    # Broad curved paving zone; not a set of invented concentric stripes.
    ribbon=batch('R02 soft grey plaza transition','silver_paving')
    verts=[]
    for i in range(65):
        t=i/64
        x=15.8+18*t
        y=-10.6+8.4*math.sin(t*PI*.93)
        dx=18;dy=8.4*PI*.93*math.cos(t*PI*.93)
        normal=Vector((-dy,dx)).normalized()
        half=1.7+.7*math.sin(t*PI)
        verts += [(x+normal.x*half,y+normal.y*half,-.00035),(x-normal.x*half,y-normal.y*half,-.00035)]
    faces=[]
    for i in range(64):
        face=(i*2,i*2+1,i*2+3,i*2+2)
        if not any(within_gameplay(verts[k][0],verts[k][1]) for k in face):faces.append(face)
    ribbon.geometry(verts,faces)
    # The shallow pale wave visible in 22/24/26 remains beyond the hoop/runoff.
    wave=batch('R02 observed low plaza wave outside court','ivory_wave',True)
    cx,cy=23.9,-.35;rx,ry=4.7,3.45
    vertices=[(cx,cy,.3982)]
    segments,rings=72,12
    for j in range(1,rings+1):
        radius=j/rings
        for i in range(segments):
            a=i*2*PI/segments
            height=.40*(1-radius*radius)**2-.0018
            vertices.append((cx+rx*radius*math.cos(a),cy+ry*radius*math.sin(a),height))
    faces=[(0,1+i,1+(i+1)%segments) for i in range(segments)]
    for j in range(rings-1):
        first=1+j*segments
        for i in range(segments):
            n=(i+1)%segments
            faces.append((first+i,first+i+segments,first+n+segments,first+n))
    wave.geometry(vertices,faces)


def random_point_in_ellipse(cx,cy,rx,ry,angle=0,outer=.88):
    a=RNG.random()*2*PI;r=math.sqrt(RNG.random())*outer
    x=rx*r*math.cos(a);y=ry*r*math.sin(a)
    return cx+x*math.cos(angle)-y*math.sin(angle),cy+x*math.sin(angle)+y*math.cos(angle)


def broad_tree(x,y,height=6.2,radius=2.2,seed=1):
    rng=random.Random(seed)
    woody=batch('R02 trees branching trunks','bark',True)
    trunk=[(x,y,.04),(x+.06,y-.02,height*.31),(x-.06,y+.03,height*.56),(x+.19,y+.11,height*.80)]
    for i in range(len(trunk)-1):woody.rod(trunk[i],trunk[i+1],.17*(1-i*.23),.17*(.77-i*.23),9)
    leaf_batches=[batch('R02 broadleaf canopy '+str(i),'leaf'+str(i),True) for i in range(4)]
    for k in range(14):
        theta=rng.uniform(0,2*PI)
        d=radius*rng.uniform(.25,.87)
        z=height*rng.uniform(.64,.94)
        centre=Vector((x+math.cos(theta)*d,y+math.sin(theta)*d,z))
        attachment=Vector((x,y,height*rng.uniform(.40,.70)))
        middle=attachment.lerp(centre,.53)+Vector((0,0,.16))
        woody.rod(attachment,middle,.055,.025,6)
        woody.rod(middle,centre,.025,.009,5)
        for i in range(185):
            az=rng.uniform(0,2*PI);elevation=rng.uniform(-1,1);r=rng.random()**(1/3)
            horizontal=math.sqrt(1-elevation**2)
            p=centre+Vector((math.cos(az)*horizontal*radius*.53*r,math.sin(az)*horizontal*radius*.47*r,elevation*radius*.58*r))
            length=rng.uniform(.21,.33)
            leaf_batches[rng.choices(range(4),weights=[3,4,3,1])[0]].leaf(p,length,length*rng.uniform(.36,.55),rng.uniform(0,2*PI),rng.uniform(-.7,.7),rng.uniform(-.8,.8))
    # Stake tripods are clearly visible around young plaza trees in 23 and 24.
    if radius<1.8:
        for angle in (0,2.1,4.2):
            woody.rod((x+math.cos(angle)*.67,y+math.sin(angle)*.67,.06),(x+math.cos(angle)*.1,y+math.sin(angle)*.1,1.83),.035,.027,6)


def willow(x,y,height=8.3,radius=3.45,seed=2):
    rng=random.Random(seed)
    wood=batch('R02 willow branches','willow_bark',True)
    twigs=batch('R02 willow hanging filaments','twig',True)
    leaf_batches=[batch('R02 willow leaves '+str(i),'willow'+str(i),True) for i in range(3)]
    wood.rod((x,y,.06),(x+.17,y+.06,height*.62),.28,.10,10)
    for k in range(13):
        a=2*PI*k/13+rng.uniform(-.2,.2)
        reach=radius*rng.uniform(.63,1.0)
        p0=Vector((x+.12,y+.04,height*(.43+.08*math.sin(a))))
        p1=Vector((x+math.cos(a)*reach*.54,y+math.sin(a)*reach*.54,height*.79))
        p2=Vector((x+math.cos(a)*reach,y+math.sin(a)*reach,height*rng.uniform(.73,.85)))
        wood.rod(p0,p1,.083,.042,7);wood.rod(p1,p2,.042,.012,6)
        for j in range(11):
            centre=p1.lerp(p2,j/10)
            centre+=Vector((rng.uniform(-.45,.45),rng.uniform(-.45,.45),rng.uniform(-.2,.18)))
            drop=rng.uniform(height*.34,height*.60)
            outward=Vector((math.cos(a),math.sin(a),0))
            points=[]
            for i in range(13):
                t=i/12
                p=centre+outward*(.64*math.sin(t*PI*.85))+Vector((math.sin(t*4+a)*.07,math.cos(t*3+a)*.07,-drop*t**.83))
                points.append(p)
            twigs.polyline(points,.0048,4)
            # Narrow lance-shaped leaves hang on both sides of each frond.
            for i in range(49):
                t=(i+.3)/49
                index=min(11,int(t*12));blend=t*12-index
                p=points[index].lerp(points[index+1],blend)
                for side in (-1,1):
                    offset=Vector((math.cos(a+side*PI/2),math.sin(a+side*PI/2),-.6))*.065
                    leaf_batches[rng.randrange(3)].leaf(p+offset,rng.uniform(.22,.31),rng.uniform(.042,.061),a+side*rng.uniform(.7,1.8),rng.uniform(-1.35,-.85),rng.uniform(-.3,.3))
        for i in range(95):
            aa=rng.uniform(0,2*PI);d=rng.uniform(.06,.64)
            pos=p2+Vector((math.cos(aa)*d,math.sin(aa)*d,rng.uniform(-.3,.5)))
            leaf_batches[rng.randrange(3)].leaf(pos,.24,.054,aa,rng.uniform(-.5,.5),rng.uniform(-.4,.4))
    # A light crown of fine twigs/leaves joins the hanging curtains naturally.
    for i in range(1700):
        a=rng.uniform(0,2*PI);r=radius*math.sqrt(rng.random())*.68
        z=height*.73+height*.19*math.sqrt(max(0,1-(r/(radius*.7))**2))+rng.uniform(-.25,.25)
        leaf_batches[rng.randrange(3)].leaf((x+r*math.cos(a),y+r*math.sin(a),z),.30,.075,a,rng.uniform(-.6,.4),0)


def shrub(x,y,size=.68):
    wood=batch('R02 shrub twig structure','twig',True)
    leaves=[batch('R02 shrub leaves '+str(i),'shrub'+str(i),True) for i in range(3)]
    for k in range(5):
        a=RNG.random()*2*PI
        wood.rod((x,y,.09),(x+math.cos(a)*size*.35,y+math.sin(a)*size*.35,size*.9),.012,.004,4)
    for i in range(215):
        a=RNG.random()*2*PI;r=math.sqrt(RNG.random())*size
        z=.14+RNG.random()**.5*size*.94*math.sqrt(max(0,1-(r/size)**2))
        leaves[RNG.randrange(3)].leaf((x+r*math.cos(a),y+r*math.sin(a),z),RNG.uniform(.16,.25),RNG.uniform(.070,.125),RNG.random()*2*PI,RNG.uniform(-.3,.7),RNG.uniform(-.4,.4))


def grass(x,y,size=.65):
    green=batch('R02 arching ornamental grass','grass',True)
    dry=batch('R02 grass warm tips','dry_grass',True)
    for i in range(22):
        a=RNG.random()*2*PI;length=size*RNG.uniform(.7,1.4);width=RNG.uniform(.012,.024)
        side=Vector((-math.sin(a),math.cos(a),0))
        p=Vector((x+RNG.uniform(-.1,.1),y+RNG.uniform(-.1,.1),.10))
        vertices=[]
        for j in range(5):
            t=j/4
            reach=.5*length*t*t
            centre=p+Vector((math.cos(a)*reach,math.sin(a)*reach,length*(t-.24*t*t)))
            vertices.extend((centre+side*width*(1-t),centre-side*width*(1-t)))
        faces=[(j*2,j*2+1,j*2+3,j*2+2) for j in range(4)]
        (dry if i%7==0 else green).geometry(vertices,faces)


def flowers(x,y,count=5):
    stems=batch('R02 white allium flower stems','flower_stem',True)
    heads=batch('R02 fine white flower florets','flower_white',True)
    for i in range(count):
        xx=x+RNG.uniform(-.3,.3);yy=y+RNG.uniform(-.3,.3);h=RNG.uniform(.52,1.01)
        top=Vector((xx+RNG.uniform(-.05,.05),yy+RNG.uniform(-.05,.05),h))
        stems.rod((xx,yy,.1),top,.006,.0035,5)
        for j in range(27):
            a=j*2.399963;z=1-2*(j+.5)/27
            r=math.sqrt(1-z*z)
            normal=Vector((r*math.cos(a),r*math.sin(a),z))
            p=top+normal*.085
            stems.rod(top,p,.0018,.001,3)
            heads.leaf(p,.041,.03,a,RNG.uniform(-PI/2,PI/2),0)
            heads.leaf(p,.032,.027,a+PI/2,RNG.uniform(-PI/2,PI/2),.4)
    grass(x,y,.34)


def planting():
    beds=[(0,8.8,17.2,12.6,3.75,-.025),(1,25.5,10.2,6.15,4.25,.18),(2,25.2,-11.8,6.0,4.4,-.16),(3,4.0,-17.2,12.0,3.6,.055),(4,-16.8,18.9,4.3,3.4,-.08)]
    for index,cx,cy,rx,ry,angle in beds:
        organic_bed(index,cx,cy,rx,ry,angle)
        for k in range(19 if index<4 else 9):
            x,y=random_point_in_ellipse(cx,cy,rx,ry,angle,.79)
            shrub(x,y,RNG.uniform(.5,.9))
        cover_leaves=[batch('R02 low groundcover leaf clusters '+str(i),'groundleaf'+str(i),True) for i in range(3)]
        for k in range(64 if index<4 else 30):
            xx,yy=random_point_in_ellipse(cx,cy,rx,ry,angle,.93)
            for j in range(39):
                a=RNG.random()*2*PI;r=RNG.random()**.5*RNG.uniform(.27,.49)
                z=.15+RNG.random()*.12*math.sqrt(max(0,1-r/.5))
                cover_leaves[RNG.randrange(3)].leaf((xx+math.cos(a)*r,yy+math.sin(a)*r,z),RNG.uniform(.13,.20),RNG.uniform(.065,.11),a,RNG.uniform(.08,.67),RNG.uniform(-.3,.3))
        # Grasses and allium drift along the inside edge rather than a grid.
        boundary=curve_polygon(cx,cy,rx*.86,ry*.84,angle,index+81,36)
        for k,(x,y) in enumerate(boundary):
            grass(x,y,RNG.uniform(.42,.74))
            if k%2==0:flowers(x+RNG.uniform(-.22,.22),y+RNG.uniform(-.18,.18),RNG.randint(3,6))
    willow(25.6,10.5,8.6,3.5,722)
    willow(28.1,-11.5,7.35,2.9,727)
    trees=[(-1.3,17.3,6.3,1.7),(4.1,18.0,6.7,1.9),(12.4,17.7,6.8,1.8),(18.3,17.2,6.0,1.5),(-4.5,-17.1,6.1,1.6),(3.2,-17.8,6.9,1.9),(12.3,-17.0,6.4,1.75),(23.0,-13.0,6.0,1.6),(29.4,9.3,6.2,1.6),(-17.6,19.5,6.6,1.9)]
    for i,(x,y,h,r) in enumerate(trees):broad_tree(x,y,h,r,930+i)
    # Garden rocks and buried edging are subdued, visible in photo 25.
    rocks=batch('R02 flowerbed natural stones','rock',True)
    for i in range(24):
        x=RNG.uniform(-4,14);y=-14.35+RNG.uniform(-.25,.18)
        rocks.ellipsoid((x,y,.16),(RNG.uniform(.2,.45),RNG.uniform(.2,.35),RNG.uniform(.12,.24)),9,4)


def circular_furniture(cx,cy,roof_z=3.15,radius=1.9):
    metal=batch('R02 curved funnel shelters','canopy_metal',True)
    # One continuous double-curvature surface, from narrow shaft to shallow dish.
    profile=[(.095,0),(.10,1.45),(.11,1.76),(.14,1.96),(.23,2.15),(.39,2.37),(.63,2.60),(.97,2.80),(1.34,2.95),(1.69,3.04),(1.90,3.07),(1.92,3.105),(1.90,3.14),(1.67,3.125),(1.31,3.095),(.97,3.055),(.63,3.025),(.32,3.005),(.10,3.0),(0,3.0)]
    profile=[(r*radius/1.9,z*roof_z/3.15) for r,z in profile]
    metal.lathe((cx,cy,0),profile,80)
    rings=batch('R02 shelter bright thin lips','canopy_lip',True)
    rings.lathe((cx,cy,0),[(radius*.998,roof_z*.973),(radius*1.01,roof_z*.984),(radius,roof_z*.996)],80)
    # Grey metal table and drum seats as seen beneath the funnel canopy in 25.
    furniture=batch('R02 plaza metal tables and stools','furniture',True)
    tx,ty=cx+.57,cy-.20
    furniture.lathe((tx,ty,0),[(0,.735),(.73,.735),(.76,.72),(.76,.675),(.72,.663),(.11,.663),(.085,.08),(0,.08)],48)
    for a in (.25*PI,.83*PI,1.4*PI):
        x=tx+math.cos(a)*1.04;y=ty+math.sin(a)*1.04
        furniture.lathe((x,y,0),[(0,.45),(.24,.45),(.255,.43),(.255,.04),(.235,.018),(0,.018)],32)
        rings.lathe((x,y,0),[(.256,.413),(.256,.432)],32)


def layered_canopies():
    roof=batch('R02 layered disk roof shells','canopy_metal',True)
    shade=batch('R02 disk roof recessed undersides','canopy_shade',True)
    rim=batch('R02 disk roof fine perimeter lips','canopy_lip',True)
    poles=batch('R02 slender circular canopy posts','canopy_metal',True)
    wood=batch('R02 curved bench timber slats','timber')
    structure=batch('R02 bench dark supports','bench_metal',True)
    discs=[(-8,13.1,3.05,2.9),(-11.1,14,3.75,3.1),(-6.2,16,4.43,3.05),(-10,17.4,5.05,3.2)]
    for n,(x,y,z,r) in enumerate(discs):
        roof.lathe((x,y,z),[(0,.095),(r*.46,.095),(r*.92,.065),(r,.015),(r+.01,-.038),(r*.975,-.09),(r*.90,-.10),(r*.47,-.14),(0,-.14)],80)
        shade.lathe((x,y,z),[(r*.83,-.106),(r*.78,-.119),(r*.39,-.177),(.40,-.18)],80)
        rim.lathe((x,y,z),[(r*.975,-.091),(r*1.001,-.035),(r*1.001,.005)],80)
        for k in range(8):
            a=2*PI*k/8
            p1=(x+math.cos(a)*.38,y+math.sin(a)*.38,z-.18)
            p2=(x+math.cos(a)*r*.84,y+math.sin(a)*r*.84,z-.112)
            poles.rod(p1,p2,.022,.019,5)
        for dx,dy in ((-r*.47,-r*.38),(r*.47,r*.25)):
            poles.rod((x+dx,y+dy,.08),(x+dx,y+dy,z-.14),.068,.065,12)
            poles.lathe((x+dx,y+dy,0),[(.17,.02),(.17,.12),(.076,.14)],24)
        # Slats on two gently curved benches, with a supported thin backrest.
        if n in (0,2):
            for j in range(20):
                a=.08*PI+j*.052
                xx=x+math.cos(a)*r*.72;yy=y+math.sin(a)*r*.72
                wood.box((xx,yy,.47),(.105,.43,.045),a)
                wood.box((x+math.cos(a)*(r*.72+.23),y+math.sin(a)*(r*.72+.23),.81),(.108,.04,.26),a)
            for a in (.15*PI,.35*PI):
                xx=x+math.cos(a)*r*.72;yy=y+math.sin(a)*r*.72
                structure.rod((xx,yy,.05),(xx,yy,.43),.04,sides=6)
                structure.rod((xx,yy,.44),(x+math.cos(a)*(r*.72+.24),y+math.sin(a)*(r*.72+.24),.94),.028,sides=6)


def signage_and_lights():
    framework=batch('R02 plaza discreet fixtures','fixture',True)
    pale=batch('R02 pale signage and sculptural loop','sign_white',True)
    # Freestanding ART PARK letters and loop sculpture visible in photo 23.
    x,y=1.5,13.7
    for k in range(3):
        pts=[]
        for j in range(65):
            a=2*PI*j/64
            q=Vector((.55*math.cos(a),.55*math.sin(a),0))
            if k==0:q=Vector((q.x,q.y*.38,q.y*.925))
            elif k==1:q=Vector((q.x*.5,q.y,q.x*.866))
            else:q=Vector((q.x,q.y*.52,-q.y*.85))
            pts.append(q+Vector((x-1.1,y,.70)))
        pale.polyline(pts,.025,6)
    curve=bpy.data.curves.new('R02 ART PARK editable lettering','FONT')
    curve.body='ART PARK';curve.size=.34;curve.extrude=.013
    curve.align_x='CENTER';curve.align_y='CENTER'
    obj=bpy.data.objects.new('R02 ART PARK garden sign',curve)
    COLLECTION.objects.link(obj);obj.parent=PARENT
    obj.location=(x+.45,y,.40);obj.rotation_euler=(PI/2,0,0)
    obj.data.materials.append(MATS['sign_white'])
    obj['r02_environment']=True;obj['layer']='background';obj['reference_images']='23'
    for k,(xx,yy) in enumerate(((1,12.1),(16.5,12.2),(17.8,-12.7),(30,-6.8))):
        framework.rod((xx,yy,0),(xx,yy,5.55),.053,.044,10)
        for side in (-1,1):
            framework.box((xx+side*.20,yy,5.40),(.31,.21,.09))
        framework.lathe((xx,yy,0),[(.13,0),(.13,.06),(.065,.1)],16)
    # Small wayfinding arms are visible in 25; no invented brand claims.
    framework.rod((18.7,8.2,0),(18.7,8.2,2.25),.032,sides=8)
    pale.box((18.4,8.2,2.00),(.8,.07,.14))
    pale.box((19.0,8.2,1.8),(.78,.07,.14))
    # Advertising panel silhouettes are retained; unreadable image content is
    # deliberately simplified as subdued printed blocks rather than invented ads.
    poster_palette=['poster_warm','poster_dark','poster_cream','poster_blue','poster_red']
    for i in range(10):
        xx=21.0+i*.88;yy=6.7+.034*(i-4.5)**2
        a=.12
        framework.box((xx,yy,.95),(.69,.05,1.72),a)
        framework.rod((xx-.26,yy,.02),(xx-.26,yy,1.79),.02,sides=5)
        framework.rod((xx+.26,yy,.02),(xx+.26,yy,1.79),.02,sides=5)
        for d in (-.25,.25):framework.box((xx+d,yy,.035),(.10,.45,.05),a)
        material=poster_palette[i%len(poster_palette)]
        surface=batch('R02 distant poster faces '+material,material)
        surface.box((xx,yy-.031,.96),(.61,.004,1.57),a)
        ink=batch('R02 distant poster abstract printed detail','poster_ink')
        ink.box((xx,yy-.035,1.39),(.39,.003,.043),a)
        ink.box((xx-.06,yy-.035,1.26),(.27,.003,.025),a)
        pale.box((xx,yy-.036,.50),(.39,.003,.035),a)


def separate_link_context():
    """A detached provisional LINK mass; do not equate it with the glass tower."""
    building=batch('R02 detached provisional LINK building','link_cladding')
    glazing=batch('R02 detached provisional LINK glazing','link_glass')
    trim=batch('R02 detached provisional LINK trim','link_trim')
    building.box((-34.2,20.6,4.0),(7.0,9.0,8.0))
    glazing.box((-30.68,20.6,3.2),(.06,8.45,5.7))
    trim.box((-30.58,20.6,6.50),(.14,8.75,.66))
    for y in (17.3,18.9,20.5,22.1,23.7):
        trim.box((-30.60,y,3.2),(.12,.07,5.7))
    curve=bpy.data.curves.new('R02 detached LINK editable identity label','FONT')
    curve.body='LINK PLAZA';curve.size=.46;curve.extrude=.008
    curve.align_x='CENTER';curve.align_y='CENTER'
    obj=bpy.data.objects.new('R02 provisional detached LINK identity',curve)
    COLLECTION.objects.link(obj);obj.parent=PARENT
    obj.location=(-30.47,20.6,6.5);obj.rotation_euler=(PI/2,0,PI/2)
    curve.materials.append(MATS['sign_white'])
    obj['r02_environment']=True;obj['layer']='background'
    obj['layout_confidence']='User requires LINK separate from Chili\'s; exact landmark identity, facade and position unresolved pending new views'
    obj['reference_images']='user correction plus 03,15; exact building identity unresolved'


def prepare():
    global COLLECTION,PARENT
    if not bpy.data.filepath:raise RuntimeError('Open the current source .blend first')
    COLLECTION=bpy.data.collections.get('background')
    if COLLECTION is None:raise RuntimeError('Expected existing background collection')
    PARENT=bpy.data.objects.get('background')
    # Clean only prior R02 environment outputs and specifically identified R01
    # blockout landscape assets. No court, anchor, hoop or fence data is touched.
    old_prefixes=('Plaza tree ','North planted strip','South planted island','Layered plaza canopy disc ','Canopy underside inset ','Canopy support ','Canopy bench seat ','Canopy bench leg ','Open plaza context','Mall Link Plaza sign')
    removed=[]
    for obj in list(bpy.data.objects):
        if obj.get('r02_environment') or obj.name.startswith(old_prefixes):
            removed.append(obj.name);bpy.data.objects.remove(obj,do_unlink=True)
    # Separate the tower from Chili's by an explicitly provisional side/rear gap.
    delta=Vector((-1.3,24,0))
    for obj in list(COLLECTION.objects):
        if obj.name=='Glazed tower silhouette' or obj.name.startswith(('Tower fine vertical ','Tower horizontal ')):
            if not obj.get('r02_tower_separated'):
                obj.location+=delta
                obj['r02_tower_separated']=True
            obj['layout_confidence']='User corrected separate buildings; side/rear placement inferred pending new views'
            obj['building_identity']='Glazed background tower; identity as LINK is NOT confirmed'
            obj['reference_images']='03,15,22,24,26'
    return removed


def build():
    removed=prepare()
    palette={
        'pale_paving':('C1C2B7',.96,0),'silver_paving':('B9BCB6',.96,0),'paving_joint':('A9AFA9',1,0),
        'stone_insert':('AFB5B0',.94,0),'ivory_wave':('DDDED1',.93,0),'curb':('AAAFA7',.86,0),'joint':('6E746C',.95,0),
        'soil':('444734',1,0),'groundcover':('3A5231',1,0),'groundleaf0':('415C34',.97,0),'groundleaf1':('526D40',.94,0),'groundleaf2':('607848',.95,0),'bark':('655A45',1,0),'willow_bark':('635D49',1,0),'twig':('556045',1,0),
        'leaf0':('32533B',.88,0),'leaf1':('52734A',.9,0),'leaf2':('67894C',.9,0),'leaf3':('85A362',.86,0),
        'willow0':('425E31',.91,0),'willow1':('627D3F',.91,0),'willow2':('7C9153',.88,0),
        'shrub0':('254834',.96,0),'shrub1':('3C6041',.94,0),'shrub2':('587543',.91,0),
        'grass':('75845B',.94,0),'dry_grass':('A9A382',.98,0),'flower_stem':('708053',.92,0),'flower_white':('E7E8DB',.9,0),
        'rock':('858D87',.92,0),'canopy_metal':('8B938B',.48,.45),'canopy_lip':('B0B6AB',.39,.5),'canopy_shade':('606B62',.65,.3),
        'furniture':('A5ADA4',.47,.40),'timber':('765347',.82,0),'bench_metal':('49564F',.7,.35),
        'fixture':('667770',.6,.4),'sign_white':('D8DED4',.68,.15),
        'poster_warm':('A27050',.92,0),'poster_dark':('515254',.92,0),'poster_cream':('C7B48B',.92,0),'poster_blue':('60949D',.92,0),'poster_red':('985B4F',.92,0),'poster_ink':('E0D9C9',.92,0),
        'link_cladding':('AAA99C',.84,0),'link_glass':('526E6B',.36,.2),'link_trim':('756E5D',.68,.15)
    }
    for name,(color,rough,metal) in palette.items():mat(name,color,rough,metal)
    apron=bpy.data.materials.get('Ground | neutral mineral apron')
    if apron:
        p=next((n for n in apron.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
        if p:
            p.inputs['Base Color'].default_value=(*linear('C1C2B7'),1)
            p.inputs['Roughness'].default_value=.93
        apron.diffuse_color=(*linear('C1C2B7'),1)
    paving();planting();layered_canopies()
    for params in ((19.3,4.8,3.25,1.95),(20.2,-5.3,3.05,1.8),(30.3,3.0,2.85,1.6)):
        circular_furniture(*params)
    signage_and_lights();separate_link_context()
    new=[]
    for value in BATCHES.values():
        obj=value.finish()
        if obj:new.append(obj)
    # Background geometry cannot enter the precise playing rectangle at any
    # raised height. Ground/low paving are the deliberate exception below z=0.
    bpy.context.view_layer.update()
    violations=[]
    for obj in new:
        if 'ground' in obj.name or 'paving' in obj.name or 'joints' in obj.name or 'inserts' in obj.name:continue
        for vertex in obj.data.vertices:
            p=obj.matrix_world@vertex.co
            if abs(p.x)<14.3256 and abs(p.y)<7.62 and p.z>.003:
                violations.append(obj.name);break
    if violations:raise RuntimeError('Raised environment intrudes into playable area: '+str(violations))
    bpy.context.scene['environment_revision']='R02 photo-informed garden refinement'
    bpy.context.scene['environment_placement']='inferred from photos 03,15,20,22–26; tower spacing awaits new views'
    report={'status':'passed','scope':'background plus apron base color only; existing gameplay anchors, court mesh, hoops and fence untouched','removed_r01_objects':len(removed),'new_batched_mesh_objects':len(new),'new_vertices':sum(len(o.data.vertices) for o in new),'new_faces':sum(len(o.data.polygons) for o in new),'raised_environment_inside_gameplay':violations,'tower_translation_m':[-1.3,24,0],'tower_spacing_status':'inferred from user correction, adjustable pending more photographs','building_identity':'Glass tower is unconfirmed identity; detached LINK volume is a clearly provisional separate mass; LINK text removed from Chili\'s','apron_base_srgb':'#c1c2b7','references':['03','15','20','22','23','24','25','26'],'game_status':'unverified'}
    return report


def render_review(output):
    scene=bpy.context.scene
    scene.render.engine='CYCLES';scene.cycles.samples=32;scene.cycles.use_denoising=True
    scene.render.resolution_x=1700;scene.render.resolution_y=1100;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    camera=scene.camera
    camera.data.type='PERSP';camera.data.lens=43
    camera.location=(36,-38,29)
    camera.rotation_euler=(Vector((1,2,1.3))-camera.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=str(output.parent/'environment-overview.png')
    bpy.ops.render.render(write_still=True)
    camera.location=(9,-9,4.1);camera.data.lens=35
    camera.rotation_euler=(Vector((25,8.5,3.0))-camera.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=str(output.parent/'environment-garden.png')
    bpy.ops.render.render(write_still=True)


def main():
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default=str(ROOT/'.build-staging'/'r02'/'scene-environment.blend'))
    parser.add_argument('--render',action='store_true')
    opts=parser.parse_args(argv)
    output=Path(opts.output).resolve()
    if not str(output).lower().startswith(str(ROOT).lower()+str(Path('/'))):
        # Path separators differ between Windows and Path('/'); use parents.
        if ROOT not in output.parents:raise RuntimeError('Output must remain inside zgc-court project')
    output.parent.mkdir(parents=True,exist_ok=True)
    runtime=ROOT/'.build-staging'/'r02'/'runtime';runtime.mkdir(parents=True,exist_ok=True)
    bpy.context.preferences.filepaths.temporary_directory=str(runtime)
    bpy.context.preferences.filepaths.file_preview_type='NONE'
    bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
    bpy.context.preferences.filepaths.save_version=0
    # Ensure external artwork remains valid when saving the staging .blend into
    # a different directory. The final integration can keep project-relative paths.
    for image in bpy.data.images:
        if image.source=='FILE' and image.filepath:
            absolute=bpy.path.abspath(image.filepath)
            if Path(absolute).is_file():image.filepath=absolute
    report=build()
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    (output.parent/'environment-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('R02_ENVIRONMENT_READY '+json.dumps({'output':str(output),**report}))
    if opts.render:render_review(output)


if __name__=='__main__':main()
