"""R12 photographic skyline directions; economical opaque facade geometry.

The supplied frames establish relative bearings, facade silhouettes and overlap,
not surveyed dimensions. No compass claim or invented exact site coordinates.
"""
from __future__ import annotations
import math
import random
from pathlib import Path
import sys
import bpy
import bmesh
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from refine_architecture_r02 import Batch
from refine_details_r03 import pbr

PREFIX='R12 skyline '
SPECS=[
 {'id':'new_zhongguan','name':'新中关','centre':[-54,-88], 'width':38,'depth':24,'height':49,'angle':2.70,'photos':[1,2], 'identity':'Readable red vertical name; high confidence'},
 {'id':'ifc','name':'互联网金融中心（外形比对）','centre':[-105,32], 'width':51,'depth':27,'height':83,'angle':1.28,'photos':[4,5], 'identity':'Shape attribution from supplied manifest, not measured'},
 {'id':'new_oriental','name':'新东方南楼','centre':[-12,94], 'width':33,'depth':23,'height':60,'angle':.127,'photos':[3,4], 'identity':'Readable roof lettering'},
 {'id':'sinosteel','name':'中钢国际广场','centre':[91,101], 'width':35,'depth':29,'height':113,'angle':-.735,'photos':[6,7], 'identity':'Stepped crown and narrow blue-green elevation shape match'},
 {'id':'curved_green','name':'浅绿弧面楼（疑似 e 世界）','centre':[130,24], 'width':69,'depth':31,'height':50,'angle':-1.388,'photos':[7,8], 'identity':'Unconfirmed identity; no readable building name; label remains tentative'},
 {'id':'blue_white','name':'露台照片远处蓝白楼（未确认）','centre':[183,-35], 'width':29,'depth':25,'height':39,'angle':-1.760,'photos':[8], 'identity':'Unidentified distant blue-white volume, not assigned a real name'},
]

def build():
    assert not any(o.name.startswith(PREFIX) for o in bpy.data.objects),'Do not duplicate skyline'
    removed=[]
    for o in list(bpy.data.objects):
        if o.name=='Glazed tower silhouette' or o.name.startswith(('Tower fine','Tower horizontal')):
            removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
    mats={k:pbr(PREFIX+k,c,r,m) for k,c,r,m in [
        ('glass','527479',.45,.22),('glass_light','709096',.49,.15),('glass_dark','466369',.47,.18),
        ('glass_green','73968D',.52,.15),('glass_sino','63868A',.48,.18),('sino_horizontal','6D8B8D',.58,.20),('stone','AEA99C',.82,0),('concrete','858D8B',.92,0),
        ('shadow','38494C',.94,0),('mullion','9CA8A6',.62,.25),('red','9C4349',.83,0),
        ('white','BFC7C2',.78,0),('terrain','969D97',.98,0),('tree_trunk','505347',.96,0),
        ('leaves_dark','465948',.98,0),('leaves_mid','52684E',.98,0),('leaves_light','627455',.98,0) ]}
    batches={}
    def batch(n,k):
        key=n+' '+k
        if key not in batches:batches[key]=Batch(key,mats[k])
        return batches[key]
    def local(s,x,y,z):
        a=s['angle'];cx,cy=s['centre']
        return (cx+x*math.cos(a)-y*math.sin(a),cy+x*math.sin(a)+y*math.cos(a),z)
    def box(s,n,k,x,y,z,w,d,h):
        batch(s['id']+' '+n,k).box(local(s,x,y,z),(w,d,h),s['angle'])
    def panel(s,n,k,x0,x1,z0,z1,y):
        batch(s['id']+' '+n,k).add([local(s,x0,y,z0),local(s,x1,y,z0),local(s,x1,y,z1),local(s,x0,y,z1)],[(0,1,2,3)])
    def grid(s,w,d,h,style):
        # Four real faces, not a camera-facing billboard, for multi-angle views.
        for side,(turn,sw,sd) in enumerate([(0,w,d),(math.pi,w,d),(math.pi/2,d,w),(-math.pi/2,d,w)]):
            q=dict(s);q['angle']=s['angle']+turn
            cols=max(5,round(sw/(2.1 if style=='beige' else .92 if s['id']=='sinosteel' else 1.75)));rows=max(6,round(h/3.15))
            for j in range(rows):
                z0=j*h/rows;z1=(j+1)*h/rows
                for i in range(cols):
                    x0=-sw/2+i*sw/cols;x1=x0+sw/cols
                    k=('glass_light','glass','glass_dark')[(i*7+j*11+side*3)%9//3]
                    if s['id']=='sinosteel':k='glass_sino'
                    if style=='green':k=('glass_green','glass_light','glass_dark')[(i*17+j*23)%11//4]
                    frame=.30 if style=='beige' and i>=max(2,cols//3) else .045
                    panel(q,'glazing',k,x0+frame,x1-frame,z0+.12,z1-.13,-sd/2-.018)
            # Beige piers / silver slender mullions, not a solid metal wall.
            material='stone' if style=='beige' else 'mullion'
            for i in range(cols+1):
                width=.54 if style=='beige' and i>=max(2,cols//3) else .075
                box(q,'vertical fins',material,-sw/2+i*sw/cols,-sd/2-.07,h/2,width,.13,h)
            for j in range(rows+1):
                if style=='beige':
                    if j%2==0:box(q,'stone paired floor bands','stone',sw/6,-sd/2-.07,j*h/rows,sw*2/3,.13,.36)
                    box(q,'glass thin floor bands','mullion',-sw/3,-sd/2-.07,j*h/rows,sw/3,.07,.04)
                else:
                    box(q,'floor bands','sino_horizontal' if s['id']=='sinosteel' else material,0,-sd/2-.07,j*h/rows,sw,.13,.035 if s['id']=='sinosteel' else .062)
    for s in SPECS:
        w,d,h=s['width'],s['depth'],s['height'];kind=s['id']
        core_h=h-7 if kind=='ifc' else h-4 if kind in ('sinosteel','new_oriental') else h
        if kind=='curved_green':
            # Shallow convex glass front and an uneven high parapet, visible in
            # 07 / terrace 08. No guessed logo is put onto this building.
            box(s,'rear volume','glass_green',0,3,h/2,w,d-6,h)
            cols=46;rows=15
            for i in range(cols):
                x0=-w/2+i*w/cols;x1=x0+w/cols
                def yy(x):return -d/2-4.0*(1-(2*x/w)**2)
                top0=h+3*(abs(2*x0/w)**1.8);top1=h+3*(abs(2*x1/w)**1.8)
                for j in range(rows):
                    z0=j*(h-5)/rows;z1=(j+1)*(h-5)/rows
                    k='white' if (i*13+j*19)%37==0 else ('glass_green','glass_light','glass_dark')[(i*5+j*3)%11//4]
                    b=batch(kind+' curved glazing',k)
                    b.add([local(s,x0,yy(x0),z0),local(s,x1,yy(x1),z0),local(s,x1,yy(x1),z1),local(s,x0,yy(x0),z1)],[(0,1,2,3)])
                batch(kind+' crown','glass_light').add([local(s,x0,yy(x0),h-5),local(s,x1,yy(x1),h-5),local(s,x1,yy(x1),top1),local(s,x0,yy(x0),top0)],[(0,1,2,3)])
                batch(kind+' vertical crown fins','mullion').rod(local(s,x0,yy(x0)-.025,0),local(s,x0,yy(x0)-.025,top0),.065,segments=4)
            for j in range(rows+1):
                for i in range(cols):
                    x0=-w/2+i*w/cols;x1=x0+w/cols
                    batch(kind+' curved floors','mullion').rod(local(s,x0,yy(x0)-.04,j*(h-5)/rows),local(s,x1,yy(x1)-.04,j*(h-5)/rows),.065,segments=4)
        else:
            box(s,'body','shadow',0,0,core_h/2,w,d,core_h)
            grid(s,w,d,core_h,'beige' if kind=='new_zhongguan' else 'glass')
        if kind=='new_zhongguan':
            for x in (-w/2,w/2):box(s,'stone edge','stone',x,0,h/2,.5,d,h)
            box(s,'stone crown','stone',w/6,-d/2-.11,h-.4,w*.67,.28,.8)
            # Photo has a thin red vertical New Zhongguan identity on the
            # glazed third; real text rather than an unrelated placeholder.
            make_text(s,'新\n中\n关',(-w*.34,-d/2-.12,h-12),1.9,mats['red'],local)
        elif kind=='ifc':
            for x in (-w/2+1.0,w/2-1.0):box(s,'sandstone side pier','stone',x,0,h/2,1.35,d+.2,h)
            box(s,'open crown cap','stone',0,0,h-.7,w+.8,d+1,1.4)
            for i in range(7):box(s,'open roof loggia pier','mullion',-w/2+2+i*(w-4)/6,-d/2,core_h+3,.5,.65,6)
        elif kind=='new_oriental':
            box(s,'upper central step','glass',0,0,h-2,w*.64,d,4)
            for x in (-w/2,w/2):box(s,'pale edge fin','mullion',x,0,core_h/2,.55,d,core_h)
            make_text(s,'新东方',(0,-d/2-.14,h-3.1),2.05,mats['white'],local)
        elif kind=='sinosteel':
            box(s,'upper unequal crown','glass',-w*.16,0,h-2,w*.68,d,4)
            box(s,'recessed narrow crown','glass_dark',w*.37,0,h-4.8,w*.22,d-.5,2.4)
            for x in (-w/2,w/2):box(s,'crown stone cheek','stone',x,0,core_h/2,.9,d+.4,core_h)
        elif kind=='blue_white':
            for x in (-w/2+1.8,w/2-1.8):box(s,'pale ends','white',x,0,h/2,3.2,d,h)
        box(s,'plinth','concrete',0,0,.45,w+3,d+3,.9)
    # Extend the world below the existing zero-height ground. Tiles keep
    # per-mesh quantisation precise and introduce no raised playable overlay.
    for i in range(8):
        for j in range(8):
            x=-280+i*80;y=-280+j*80
            b=batch(f'ground tile {i}-{j}','terrain')
            b.add([(x-40,y-40,-.16),(x+40,y-40,-.16),(x+40,y+40,-.16),(x-40,y+40,-.16)],[(0,1,2,3)])
    rng=random.Random(261204)
    tree_rows=[]
    def tree(x,y,h,r,group):
        tree_rows.append([round(x,3),round(y,3),round(h,3),group])
        trunk=batch('background trunks '+group,'tree_trunk')
        trunk.rod((x,y,-.1),(x,y,h*.69),.20,.07,7)
        for j in range(3):
            angle=j*2.1+.4
            trunk.rod((x,y,h*.32),(x+r*.60*math.cos(angle),y+r*.60*math.sin(angle),h*.74),.105,.025,7)
        # Preserve the established placement RNG sequence while changing only
        # the individual crowns. Appearance uses its own deterministic stream.
        low='understory' in group or 'low' in group
        distant=group.startswith('horizon')
        for _ in range(7*(476 if low else 475)):rng.random()
        leaf_rng=random.Random(f'{x:.7f}:{y:.7f}:{h:.7f}:{group}')
        # Open, spatial leaf clusters replace every closed stone-like shell.
        # Each opaque leaf is a diamond of two triangles, never an alpha card.
        # Near groups use finer and more numerous leaves; remote groups use
        # broader foliage fragments whose overlap covers the ground edge.
        count=124 if distant else (248 if low else 260)
        for clump in range(7):
            a=clump*2.3999+leaf_rng.uniform(-.22,.22)
            rad=r*(.06 if clump==0 else leaf_rng.uniform(.28,.62))
            cx=x+rad*math.cos(a);cy=y+rad*math.sin(a)
            cz=h*(.51+.30*leaf_rng.random());rr=r*(.49+.24*leaf_rng.random());rz=h*(.23+.09*leaf_rng.random())
            if low:cz=h*(.32+.08*leaf_rng.random());rz=h*.48
            # An occasional thin secondary fork can be seen between leaves.
            if not low and clump%2:
                trunk.rod((x,y,h*.55),(cx,cy,cz),.04,.012,5)
            for k in range(count):
                ang=leaf_rng.random()*math.tau;v=leaf_rng.uniform(-1,1)
                lat=math.sqrt(1-v*v);distance=leaf_rng.random()**.34
                warp=1+.14*math.sin(ang*3+clump)
                q=Vector((cx+rr*lat*math.cos(ang)*distance*warp,
                          cy+rr*lat*math.sin(ang)*distance/warp,
                          cz+rz*v*distance))
                if low:
                    # The lower strata meet the soil. Repeated side-on leaves
                    # here hide the distant ground edge without solid globes.
                    if k<count*.22:q.z=leaf_rng.uniform(.025,h*.23)
                    q.z=max(.018,q.z)
                length=leaf_rng.uniform(.77,1.34) if distant else leaf_rng.uniform(.46,.81)
                width=length*leaf_rng.uniform(.46,.73)
                yaw=leaf_rng.uniform(0,math.tau);tilt=leaf_rng.uniform(-1.16,1.16)
                if low and k<count*.22:tilt=leaf_rng.uniform(.40,1.28)
                axis=Vector((math.cos(yaw)*math.cos(tilt),math.sin(yaw)*math.cos(tilt),math.sin(tilt)))
                cross=Vector((-math.sin(yaw),math.cos(yaw),0))
                vertices=[q-axis*length*.50,q+cross*width*.50,
                          q+axis*length*.50,q-cross*width*.50]
                colour=leaf_rng.choices(['leaves_dark','leaves_mid','leaves_light'],[5,7,2])[0]
                batch('background foliage '+group,colour).add(vertices,[(0,1,2),(0,2,3)])
    # More detail/irregular canopy at the open plaza edge documented in 07;
    # groups leave the existing close trees and the left storefront legible.
    for i in range(24):
        tree(51+rng.random()*17,-47+i*4.5+rng.uniform(-2,2),5+rng.random()*9,3.5+rng.random()*1.8,'open plaza')
    for i in range(18):tree(-43+i*4.3+rng.uniform(-2,2),54+rng.random()*15,5+rng.random()*10,3+rng.random()*1.8,'canopy side')
    for i in range(10):tree(8+i*4+rng.uniform(-1.3,1.3),-37-rng.random()*9,5+rng.random()*8,3+rng.random()*1.5,'left open end')
    for group,rows in [('open understory',[(48+rng.random()*13,-48+i*5) for i in range(22)]),('canopy understory',[(-44+i*5,51+rng.random()*10) for i in range(18)])]:
        for x,y in rows:tree(x,y,2.8+rng.random()*3.5,2.5+rng.random(),group)
    # Unphotographed distant sectors use a conservative anonymous treeline,
    # never asserted as exact photographed individual trees.
    for i in range(155):
        a=2*math.pi*i/155;radius=193+8*math.sin(a*7)
        tree(radius*math.cos(a),radius*math.sin(a),12+rng.random()*11,5.2+rng.random()*1.5,f'horizon {i//20}')
        tree((radius-4)*math.cos(a),(radius-4)*math.sin(a),4+rng.random()*3,4.8+rng.random(),f'horizon low {i//20}')
    made=[]
    for key,b in batches.items():
        mesh=bpy.data.meshes.new(PREFIX+key);mesh.from_pydata(b.vertices,[],b.faces);mesh.update()
        bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(mesh);bm.free()
        mesh.materials.append(b.mat)
        if 'foliage' in key:
            for face in mesh.polygons:face.use_smooth=True
        o=bpy.data.objects.new(PREFIX+key,mesh);bpy.data.collections['background'].objects.link(o);o.parent=bpy.data.objects['background']
        o['layer']='background';o['r12_skyline']=True;o['measurement_status']='Photographic relative bearing/shape; all metric offsets inferred, not survey'
        made.append(o.name)
    bpy.context.view_layer.update()
    made=sorted(o.name for o in bpy.data.objects if o.name.startswith(PREFIX))
    return {'revision':'R12','status':'passed','objects':made,'removed_placeholder_objects':removed,'building_specs':SPECS,
       'tree_centres_m':tree_rows,'terrain_bounds_m':[[-320,-320,-.16],[320,320,-.16]],
       'reference_directory':'references/r12-skyline','all_offsets_are_inferred':True,'measured_compass_bearings':False,
       'relative_order_checks':{'new_zhongguan_left_fence_side':SPECS[0]['centre'][1]<-9.17,'ifc_behind_link':SPECS[1]['centre'][0]<-48,'new_oriental_canopy_side':SPECS[2]['centre'][1]>40,'sinosteel_left_of_curved_building_looking_open_half':SPECS[3]['centre'][1]>SPECS[4]['centre'][1]},
       'horizon_limit':'Anonymous distant treeline closes unphotographed sectors; not a measured reconstruction of every tree. Camera views beyond the supplied range are approximate.',
       'materials':'Opaque non-emitting facade panels/low-poly mullions, native DDS material resources; no skybox, transparency or exposure changes.'}

def make_text(s,body,xyz,size,mat,local):
    data=bpy.data.curves.new(PREFIX+s['id']+' sign','FONT');data.body=body;data.size=size;data.align_x='CENTER';data.align_y='CENTER';data.space_line=.90
    font=Path('C:/Windows/Fonts/msyh.ttc')
    if font.exists():data.font=bpy.data.fonts.load(str(font))
    o=bpy.data.objects.new(PREFIX+s['id']+' identity',data);bpy.data.collections['background'].objects.link(o);o.parent=bpy.data.objects['background']
    o.location=local(s,*xyz);o.rotation_euler=(math.pi/2,0,s['angle']);data.materials.append(mat);o['layer']='background';o['r12_skyline']=True

if __name__=='__main__':
    import json
    result=build();print(json.dumps(result,ensure_ascii=True))
