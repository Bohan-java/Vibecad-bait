"""R12 photo-grounded left-side low shop and forecourt. Staging only.

Coordinates use Blender metres. Facing the Chili's hoop, -Y is left.
The photographs confirm the side and features, not a surveyed footprint.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import bpy
import bmesh
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import refine_architecture_r02 as geometry
import refine_details_r03 as finish
from refine_chilis_current import signature
from refine_streetlight_current import lighting_signature

PREFIX='R12 left context '
STAGE=ROOT/'.build-staging/r12-left'
PARAMS={'building_x_min':-19.1,'building_x_max':2.5,'facade_y':-16.3,
        'building_back_y':-23.,'roof_height':3.86,'fence_y':-9.17,
        'entry_x':-14.60,'tree_pool':[-3.4,-13.4],
        'old_planting_cut_x':2.8,'old_planting_cut_y':-12.}
MATERIALS={};BATCHES={};ADDED=[]
PLANTING_ALLOWLIST={
    'R02 organic planted ground','R02 continuous low garden groundcover',
    'R02 curving raised stone edges','R02 curb expansion joints',
    'R02 arching ornamental grass','R02 grass warm tips',
    'R02 white allium flower stems','R02 fine white flower florets',
    'R02 shrub twig structure','R02 trees branching trunks','R02 flowerbed natural stones',
    *('R02 low groundcover leaf clusters '+str(i) for i in range(3)),
    *('R02 shrub leaves '+str(i) for i in range(3)),
    *('R02 broadleaf canopy '+str(i) for i in range(4))}

def mat(name,color,rough=.75,metal=0):
    m=finish.pbr('R12 Left | '+name,color,rough,metal)
    s=finish.shader_for(m)
    s.inputs['Emission Strength'].default_value=0
    s.inputs['Alpha'].default_value=1
    MATERIALS[name]=m
    return m

def batch(name,material,smooth=False):
    if name not in BATCHES:BATCHES[name]=geometry.Batch(name,MATERIALS[material],smooth)
    return BATCHES[name]

def mark(obj):
    obj['r12_left_context']=True;obj['layer']='background';obj['category']='architecture'
    obj['reference_images']='r12-left 01-07: side/overlap; 08: shop facade and foreground features'
    obj['measurement_status']='Photo proportions and clear gaps; metric offsets inferred, no survey'
    ADDED.append(obj.name)

def flush():
    for name,b in BATCHES.items():
        if not b.vertices:continue
        data=bpy.data.meshes.new(PREFIX+name);data.from_pydata(b.vertices,[],b.faces);data.update()
        bm=bmesh.new();bm.from_mesh(data);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(data);bm.free()
        obj=bpy.data.objects.new(PREFIX+name,data)
        bpy.data.collections['background'].objects.link(obj);obj.parent=bpy.data.objects['background']
        data.materials.append(b.mat)
        for p in data.polygons:p.use_smooth=b.smooth
        mark(obj)

def ellipsoid(b,p,scale,segments=14,rings=8):
    verts=[]
    for j in range(rings+1):
        a=-math.pi/2+math.pi*j/rings
        for i in range(segments):
            t=math.tau*i/segments
            verts.append((p[0]+scale[0]*math.cos(a)*math.cos(t),p[1]+scale[1]*math.cos(a)*math.sin(t),p[2]+scale[2]*math.sin(a)))
    b.add(verts,[(j*segments+i,j*segments+(i+1)%segments,(j+1)*segments+(i+1)%segments,(j+1)*segments+i) for j in range(rings) for i in range(segments)])

def text(name,body,x,z,width,height,material,y=None):
    curve=bpy.data.curves.new(PREFIX+name,'FONT');curve.body=body;curve.align_x='CENTER';curve.align_y='CENTER'
    curve.extrude=.005;curve.bevel_depth=.0015;curve.bevel_resolution=1
    if any(ord(c)>255 for c in body):
        curve.font=bpy.data.fonts.load(str(Path(bpy.app.binary_path).parent/'5.2/datafiles/fonts/Noto Sans CJK Regular.woff2'))
    obj=bpy.data.objects.new(PREFIX+name,curve)
    bpy.data.collections['background'].objects.link(obj);obj.parent=bpy.data.objects['background']
    obj.location=(x,y if y is not None else PARAMS['facade_y']+.175,z)
    obj.rotation_euler=(math.pi/2,0,math.pi)
    curve.materials.append(MATERIALS[material]);bpy.context.view_layer.update()
    w=max(c[0] for c in obj.bound_box)-min(c[0] for c in obj.bound_box)
    h=max(c[1] for c in obj.bound_box)-min(c[1] for c in obj.bound_box)
    s=min(width/max(w,1e-5),height/max(h,1e-5));obj.scale=(s,s,s);mark(obj)
    return obj

def palette():
    for name,color,rough,metal in (
        ('warm silver metal','858C89',.48,.52),('edge dark metal','414B48',.59,.38),
        ('deep window','354640',.44,.05),('window blue grey','536461',.5,.02),
        ('window lighter','606F69',.52,.03),('roof grey','747B75',.9,.04),
        ('plinth grey','7C827A',.95,0),('cream logo','E1DCBD',.55,.15),
        ('slab grey','92918A',.96,0),('slab variation','898C85',.96,0),('grout','565E58',1,0),
        ('warm interior','A59370',.96,0),('counter wood','786251',.91,0),
        ('planter celadon','778773',.79,0),('soil','474B38',1,0),
        ('plant leaf dark','314933',.94,0),('plant leaf mid','4B6340',.94,0),('plant leaf light','657752',.94,0),
        ('tree bark','5E5646',.97,0),('umbrella crimson','8E2630',.92,0),('umbrella ivory','D4CDB5',.93,0),
        ('notice black','242B28',.9,0),('notice cream','B6AD90',.96,0)):
        mat(name,color,rough,metal)

def shell_and_facade():
    x0=PARAMS['building_x_min'];x1=PARAMS['building_x_max'];yf=PARAMS['facade_y'];yb=PARAMS['building_back_y'];w=x1-x0
    shell=batch('rectangular low shop shell','roof grey')
    shell.box(((x0+x1)/2,(yf+yb)/2,3.73),(w,yf-yb,.26))
    shell.box(((x0+x1)/2,yb,1.8),(w,.22,3.6))
    shell.box((x0,(yf+yb)/2,1.8),(.19,yf-yb,3.6));shell.box((x1,(yf+yb)/2,1.8),(.19,yf-yb,3.6))
    lower=batch('low continuous stone plinth','plinth grey');lower.box(((x0+x1)/2,yf,0.125),(w,.30,.25))
    frame=batch('deep silver bay frames and door surrounds','warm silver metal')
    dark=batch('window inset perimeter gaskets','edge dark metal')
    # Front remains planar. A small rounded end is local trim, not an oval footprint.
    bays=12;step=w/bays
    for i in range(bays+1):frame.box((x0+i*step,yf+.022,1.55),(.085,.17,2.92))
    for z in (.30,2.51,3.16):frame.box(((x0+x1)/2,yf+.028,z),(w,.17,.073))
    # Recessed opaque native-safe glazing with depth, transoms and reflection bands.
    # No unverified alpha shader or fake transparent black plane is introduced.
    for i in range(bays):
        a=x0+i*step+.054;b=x0+(i+1)*step-.054;cx=(a+b)/2
        is_door=abs(cx-PARAMS['entry_x'])<step*.45
        glazing=batch('recessed lower glazing alternating '+str(i%3),('deep window','window blue grey','window lighter')[i%3])
        glazing.box((cx,yf-.082,1.37),(b-a,.03,2.06))
        dark.box((cx,yf+.015,1.4),(b-a+.022,.03,2.18))
        glazing.box((cx,yf+.041,1.40),(b-a-.05,.024,2.11))
        if is_door:
            for dx in (-(b-a)/4,(b-a)/4):
                frame.box((cx+dx,yf+.105,1.39),(.035,.07,2.17))
            frame.box((cx,yf+.105,1.4),(.045,.075,2.18))
            for dx in (-.105,.105):
                dark.rod((cx+dx,yf+.22,.93),(cx+dx,yf+.22,1.36),.012,segments=10)
                for zz in (.95,1.34):dark.rod((cx+dx,yf+.12,zz),(cx+dx,yf+.22,zz),.01,segments=8)
            frame.box((cx,yf+.16,2.58),(b-a+.26,.42,.12))
            lower.box((cx,yf+.27,.032),(b-a+.24,.48,.046))
        else:
            frame.box((cx,yf+.07,1.40),(.025,.047,2.1))
        # Narrow tall upper glass transom, fine vertical ribs with visible spacing.
        batch('upper dark transom glass','deep window').box((cx,yf-.015,2.845),(b-a,.075,.58))
        for j in range(1,10):frame.box((a+j*(b-a)/10,yf+.05,2.847),(.031,.07,.57))
    cornice=batch('flat horizontal metal grille cornice','warm silver metal')
    gaps=batch('cornice recessed dark gaps','edge dark metal')
    gaps.box(((x0+x1)/2,yf-.015,3.43),(w,.09,.43))
    for j in range(7):cornice.box(((x0+x1)/2,yf+.077,3.205+j*.063),(w+.12,.15,.031))
    for j in range(7):
        z=3.205+j*.063
        cornice.box((x0-.016,(yf+yb)/2,z),(.14,yf-yb,.031))
        cornice.box((x1+.016,(yf+yb)/2,z),(.14,yf-yb,.031))
    cornice.box(((x0+x1)/2,yf+.04,3.695),(w+.18,.27,.075))
    cornice.box(((x0+x1)/2,yf+.04,3.802),(w+.24,.31,.045))
    # Lettering sits over the taller dark glass band on the basket end only.
    logo_back=batch('boots sign slim dark ribbed panel','edge dark metal')
    logo_back.box((-15.1,yf+.087,2.84),(6.6,.038,.69))
    for j in range(44):frame.box((-18.32+j*.15,yf+.128,2.84),(.035,.048,.65))
    # From the court (+Y), X decreases from left to right. Word order must
    # therefore be The / boots / 泥靴 in that screen order, never reversed.
    text('The small word','The',-12.48,2.84,.5,.19,'cream logo',yf+.20)
    outline_boots(-14.58,yf+.204,2.84)
    text('boots Chinese name','泥靴',-17.45,2.84,1.50,.50,'cream logo',yf+.20)
    # Secondary low side glazing, consistent with the independent terrace view.
    side=batch('west end silver corner frames','warm silver metal')
    for yy in (yf-.2,yf-1.6,yf-3.1,yf-4.6,yb+.12):side.box((x0-.01,yy,1.63),(.13,.065,2.90))
    for zz in (.3,2.51,3.17):side.box((x0-.01,(yf+yb)/2,zz),(.13,yf-yb,.065))

def outline_boots(cx,y,cz):
    """Rounded hollow cream logo contours, derived from the visible photo word."""
    face=batch('boots rounded outlined dimensional lettering','cream logo',True)
    metal=batch('boots letter dark channel returns','edge dark metal',True)
    # u grows left to right to a viewer at +Y; source X decreases.
    starts=[-1.38,-.77,-.15,.44,.93]
    def p(u,z):return (cx-u,y,cz+z)
    def path(points,closed=False):
        points=points+([points[0]] if closed else [])
        for a,b in zip(points,points[1:]):
            face.rod(p(*a),p(*b),.019,segments=8)
            aa=Vector(p(*a));bb=Vector(p(*b));aa.y-=.022;bb.y-=.022
            metal.rod(aa,bb,.026,segments=8)
    def oval(u,z,rx,rz):
        path([(u+rx*math.cos(math.tau*i/40),z+rz*math.sin(math.tau*i/40)) for i in range(40)],True)
    # Lowercase b uses a slim parallel stem and two concentric bowl contours.
    u=starts[0]
    path([(u-.20,-.23),(u-.20,.40),(u-.10,.40),(u-.10,.16)])
    oval(u+.02,-.035,.235,.225);oval(u+.02,-.035,.145,.137)
    for u in starts[1:3]:oval(u,-.035,.246,.235);oval(u,-.035,.145,.140)
    u=starts[3]
    path([(u-.10,.36),(u-.10,.19),(u-.22,.19),(u-.22,.10),(u-.10,.10),(u-.10,-.15),(u-.07,-.23),(u+.03,-.27),(u+.17,-.24),(u+.16,-.15),(u+.04,-.17),(u,.11),(u+.17,.11),(u+.17,.20),(u,.20),(u,.36)],True)
    u=starts[4]
    path([(u+.31,.15),(u+.21,.21),(u+.04,.20),(u-.09,.12),(u-.10,.025),(u-.02,-.045),(u+.19,-.08),(u+.23,-.14),(u+.15,-.19),(u+.03,-.18),(u-.04,-.12),
          (u-.13,-.16),(u-.03,-.25),(u+.13,-.28),(u+.29,-.22),(u+.35,-.12),(u+.31,-.02),(u+.22,.045),(u+.05,.065),(u,.105),(u+.055,.13),(u+.18,.12),(u+.25,.07)],True)

def forecourt_paving():
    yf=PARAMS['facade_y'];x0=PARAMS['building_x_min'];x1=PARAMS['building_x_max']
    ground=batch('grey shop forecourt bedding','grout');ground.box(((x0+x1)/2,yf+1.64,.002),(x1-x0,3.35,.018))
    rng=random.Random(501)
    tiles=[batch('near shop grey stone slab '+str(i),'slab grey' if i==0 else 'slab variation') for i in range(2)]
    nx=24;ny=5;dx=(x1-x0)/nx;dy=3.35/ny
    for i in range(nx):
        for j in range(ny):
            tiles[int(rng.random()<.16)].box((x0+(i+.5)*dx,yf+(j+.5)*dy,.014),(dx-.011,dy-.011,.015))
    drains=batch('slim linear entry drain grate','edge dark metal')
    drains.box((PARAMS['entry_x'],yf+.48,.03),(2.40,.13,.021))
    slats=batch('drain cross bars','warm silver metal')
    for i in range(40):slats.box((PARAMS['entry_x']-1.18+i*.06,yf+.48,.044),(.014,.125,.009))
    # Cap the trimmed, previously inferred island with a quiet low stone edge.
    curb=batch('retained garden new straight termination','plinth grey')
    curb.box((2.82,-17.2,.061),(.11,6.7,.125))

def topiary(x,y,radius=.38):
    pot=batch('celadon ribbed round shop planters','planter celadon',True)
    pot.lathe((x,y,0),[(0,.015),(.21,.015),(.24,.035),(.28,.42),(.30,.48),(.285,.515),(.235,.515),(.218,.46)],40)
    for j in range(28):
        a=math.tau*j/28
        pot.rod((x+.236*math.cos(a),y+.236*math.sin(a),.07),(x+.286*math.cos(a),y+.286*math.sin(a),.47),.008,segments=5)
    soil=batch('planter and tree pit soil','soil');soil.lathe((x,y,0),[(0,.478),(.235,.478)],32)
    branch=batch('shop topiary hidden stems','tree bark',True);branch.rod((x,y,.42),(x,y,.98),.031,.020,8)
    rng=random.Random(round(x*333+y*17));leaves=[batch('shop clipped foliage '+str(i),name) for i,name in enumerate(('plant leaf dark','plant leaf mid','plant leaf light'))]
    for k in range(560):
        a=rng.uniform(0,math.tau);h=rng.uniform(-1,1);rr=radius*(.72+.28*rng.random());r=math.sqrt(1-h*h)*rr
        p=(x+math.cos(a)*r,y+math.sin(a)*r,.99+h*rr)
        leaves[rng.choices(range(3),[3,5,2])[0]].leaf(p,.085,.049,a,rng.uniform(-1,1))

def closed_umbrella(x,y):
    mast=batch('striped parasol pole and weighted crossfoot','edge dark metal',True)
    mast.rod((x,y,.05),(x,y,2.61),.029,.025,10)
    for a in (0,math.pi/2):mast.box((x,y,.028),(.63,.09,.055),a)
    for i in range(16):
        a=math.tau*i/16;b=math.tau*(i+1)/16
        profile=[(2.59,.025),(2.44,.095),(2.12,.14),(1.8,.18),(1.5,.225),(1.15,.29),(1.09,.23)]
        for j in range(len(profile)-1):
            z,r=profile[j];zz,rr=profile[j+1]
            material='umbrella crimson' if j%2 else 'umbrella ivory'
            fa=1 if i%2==0 else .80;fb=1 if i%2 else .80
            batch('folded red ivory parasol fabric '+material,material).add(
                [(x+r*fa*math.cos(a),y+r*fa*math.sin(a),z),(x+r*fb*math.cos(b),y+r*fb*math.sin(b),z),(x+rr*fb*math.cos(b),y+rr*fb*math.sin(b),zz),(x+rr*fa*math.cos(a),y+rr*fa*math.sin(a),zz)],[(0,1,2,3)])
    mast.lathe((x,y,0),[(.028,2.58),(.033,2.64),(.010,2.67)],16)

def notice(x,y,angle=0):
    metal=batch('two portable menu A frame rails','edge dark metal')
    panel=batch('two portable menu dark boards','notice black')
    for dx in (-.26,.26):
        metal.rod((x+dx,y-.2,.05),(x+dx,y+.025,1.02),.017,segments=6)
        metal.rod((x+dx,y+.30,.05),(x+dx,y+.025,1.02),.017,segments=6)
    panel.box((x,y,0.61),(.52,.044,.7),angle)
    ink=batch('menu abstract untranscribed printed blocks','notice cream')
    for i,w in enumerate((.35,.41,.28)):
        ink.box((x,y+.026,.85-i*.085),(w,.008,.018))
    ink.box((x+.035,y+.027,.40),(.29,.008,.14))

def tree_and_forecourt():
    cx,cy=PARAMS['tree_pool']
    curb=batch('round grey tree well chamfered stone wall','plinth grey',True)
    curb.lathe((cx,cy,0),[(1.22,.02),(1.30,.04),(1.31,.34),(1.28,.40),(1.07,.40),(1.05,.36),(1.06,.04)],56)
    batch('round tree well inner soil','soil').lathe((cx,cy,0),[(0,.29),(1.08,.29)],48)
    rail=batch('low dark guardrail around round tree well','edge dark metal',True)
    for a in (0,math.pi/2,math.pi,math.pi*1.5):
        rail.rod((cx+math.cos(a)*1.18,cy+math.sin(a)*1.18,.39),(cx+math.cos(a)*1.18,cy+math.sin(a)*1.18,.88),.027,segments=8)
    for i in range(48):
        a=math.tau*i/48;b=math.tau*(i+1)/48
        rail.rod((cx+1.18*math.cos(a),cy+1.18*math.sin(a),.86),(cx+1.18*math.cos(b),cy+1.18*math.sin(b),.86),.026,segments=8)
    tree=batch('left forecourt single deciduous tree branches','tree bark',True)
    tree.rod((cx,cy,.3),(cx+.12,cy-.06,2.8),.13,.065,10)
    rng=random.Random(9812)
    leaves=[batch('left forecourt deciduous foliage '+str(i),name) for i,name in enumerate(('plant leaf dark','plant leaf mid','plant leaf light'))]
    for k in range(11):
        a=math.tau*k/11;d=rng.uniform(.55,1.2);z=rng.uniform(3.15,4.40)
        end=Vector((cx+math.cos(a)*d,cy+math.sin(a)*d,z))
        p=Vector((cx+.08,cy,1.7+k*.095));middle=p.lerp(end,.57)
        tree.rod(p,middle,.038,.021,7);tree.rod(middle,end,.021,.009,6)
        for j in range(160):
            az=rng.uniform(0,math.tau);h=rng.uniform(-1,1);rr=rng.random()**(1/3);hr=math.sqrt(1-h*h)
            q=end+Vector((math.cos(az)*hr*.68*rr,math.sin(az)*hr*.65*rr,h*.72*rr))
            leaves[rng.choices(range(3),[4,5,1])[0]].leaf(q,.20,.09,az,rng.uniform(-.8,.8))
    # Only frontage furniture demonstrated in the independent shop photograph.
    # Their exact offsets are explicitly inferred, never claimed to touch the court fence.
    topiary(-17.25,-14.82);topiary(-13.1,-14.90)
    closed_umbrella(-13.55,-14.95)
    notice(-6.55,-13.82);notice(-5.88,-13.82)

def region_fingerprint(obj):
    """Stable polygon signature for the untouched far garden, independent of indices."""
    rows=[];uv=obj.data.uv_layers.active
    for p in obj.data.polygons:
        co=[obj.matrix_world@obj.data.vertices[i].co for i in p.vertices]
        if not (all(v.x>2.81 for v in co) or all(v.y>-11.99 for v in co)):continue
        row=[tuple(round(float(v),6) for v in point) for point in co]
        if uv:row += [tuple(round(float(v),6) for v in uv.data[i].uv) for i in p.loop_indices]
        rows.append(str((p.material_index,row)))
    return hashlib.sha256('\n'.join(sorted(rows)).encode()).hexdigest()

def crop_earlier_inferred_planting():
    reports=[]
    for name in sorted(PLANTING_ALLOWLIST):
        obj=bpy.data.objects.get(name)
        if not obj or obj.type!='MESH':continue
        before=signature(obj);far_before=region_fingerprint(obj);nf=len(obj.data.polygons)
        # R02 batches are authored directly in world coordinates and identity transforms.
        if any(abs(obj.matrix_world[r][c]-(1 if r==c else 0))>1e-6 for r in range(4) for c in range(4)):
            raise RuntimeError('Unexpected garden batch transform: '+name)
        bm=bmesh.new();bm.from_mesh(obj.data)
        affected=[f for f in bm.faces if all(v.co.y<-12 for v in f.verts)]
        geometry_set=set(affected)
        for f in affected:geometry_set.update(f.edges);geometry_set.update(f.verts)
        if geometry_set:
            bmesh.ops.bisect_plane(bm,geom=list(geometry_set),dist=1e-7,plane_co=(2.8,0,0),plane_no=(1,0,0),clear_inner=True,clear_outer=False)
            bm.to_mesh(obj.data);obj.data.update()
        bm.free()
        if region_fingerprint(obj)!=far_before:raise RuntimeError('Unrelated far garden polygons altered: '+name)
        if signature(obj)!=before:
            reports.append({'name':name,'faces_before':nf,'faces_after':len(obj.data.polygons),'far_region_unchanged':True,'before':before,'after':signature(obj)})
    return reports

def build():
    MATERIALS.clear();BATCHES.clear();ADDED.clear()
    protected={o.name:signature(o) for o in bpy.data.objects if o.name not in PLANTING_ALLOWLIST and not o.name.startswith(PREFIX)}
    light=lighting_signature()
    for obj in list(bpy.data.objects):
        if obj.name.startswith(PREFIX):bpy.data.objects.remove(obj,do_unlink=True)
    trimmed=crop_earlier_inferred_planting()
    palette();shell_and_facade();forecourt_paving();tree_and_forecourt();flush()
    bpy.context.view_layer.update()
    unexpected=[n for n,h in protected.items() if n not in bpy.data.objects or signature(bpy.data.objects[n])!=h]
    if unexpected:raise RuntimeError('Protected objects changed: '+str(unexpected))
    if light!=lighting_signature():raise RuntimeError('Scene lighting changed')
    report={'revision':'R12','status':'passed','parameters':PARAMS,'objects':ADDED,
        'protected_count':len(protected),'unexpected_changes':unexpected,'lights_world_exposure_unchanged':True,
        'trimmed_old_inferred_planting':trimmed,'game_verified':False,
        'evidence':[
            {'images':'01,02,03','finding':'Left court fence and basket share one frame. Low metal/glass shop extends beyond the left fence, separate from Chilis.'},
            {'images':'04,05,06','finding':'Repeated fence posts and A sign preserve overlap; boots wordmark appears toward the basket end below Xinzhongguan tower.'},
            {'images':'07','finding':'Independent side angle supports the shop and left fence relationship; not a continuous camera track.'},
            {'images':'08','finding':'Flat horizontal cornice, vertical glass ribs, silver doors, boots sign, round stone tree well/low guardrail, striped folded parasol, ball topiary planters, two portable notice boards.'}],
        'limits':['Exact setbacks, overall footprint, heights and individual object offsets are inferred from photo proportions; no surveyed dimensions.',
                  'Photo 08 seasonal snow is excluded. Summer foliage is reconstructed on the visible tree skeleton.',
                  'Native-safe opaque recessed glass representation does not reproduce optical glass transparency.',
                  'Foreground objects belong to the shop forecourt, not arbitrarily attached to the court fence.',
                  'Original basketball fence, high left lamp, Chili building, court and hoops are unchanged. Skyline is handled by the root module.'],
        'material_policy':'Native static opaque PBR, no emission, geometry lettering and details'}
    bpy.context.scene['left_context_revision']='R12 low shop and photo-local forecourt'
    return report

def renders(folder):
    scene=bpy.context.scene;camera=scene.camera
    scene.render.engine='CYCLES';scene.cycles.samples=24;scene.cycles.use_denoising=True
    scene.render.resolution_x=1400;scene.render.resolution_y=1000;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    views=[('court',(-6.6,-3.5,2.0),(-12,-16.4,2.0),23),
           ('forecourt',(-19.3,-10.7,2.5),(-11.9,-16.3,1.9),25),
           ('overview',(4,-4,12),(-10,-15.5,1.6),30)]
    for key,pos,target,lens in views:
        camera.location=pos;camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
        camera.data.type='PERSP';camera.data.lens=lens
        scene.render.filepath=str(folder/f'r12-left-{key}.png');bpy.ops.render.render(write_still=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--render',action='store_true')
    parser.add_argument('--output',default=str(STAGE/'scene-left.blend'))
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    output=Path(args.output).resolve()
    if not output.is_relative_to(ROOT) or output==ROOT/'source/scene.blend':raise RuntimeError('Staging path only')
    STAGE.mkdir(parents=True,exist_ok=True);output.parent.mkdir(parents=True,exist_ok=True)
    prefs=bpy.context.preferences.filepaths;prefs.temporary_directory=str(STAGE);prefs.save_version=0;prefs.file_preview_type='NONE';prefs.use_auto_save_temporary_files=False
    report=build();bpy.ops.wm.save_as_mainfile(filepath=str(output))
    report['output']=str(output);report['sha256']=hashlib.sha256(output.read_bytes()).hexdigest()
    (ROOT/'validation/r12-left-context-current.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('R12_LEFT_READY '+json.dumps({'output':str(output),'objects':len(ADDED),'protected':report['protected_count']}),flush=True)
    if args.render:renders(STAGE)

if __name__=='__main__':main()
