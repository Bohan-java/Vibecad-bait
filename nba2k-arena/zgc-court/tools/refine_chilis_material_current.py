"""R13 photo-led material/fabrication pass, restricted to the court-facing Chili's.

Open the saved source first. Writes a staged blend only. Original photographs are
read-only evidence; material PNGs below are newly authored procedural material
maps, not edits to photos. Uses exportable base-color/roughness maps, scalar metal,
real fabrication geometry, no normal-map dependency or new lights/emission.
"""
from __future__ import annotations
import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import sys
import bpy
import bmesh
import numpy as np
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import refine_chilis_current as old
import refine_chilis_rect_current as rect
import refine_details_r03 as finish
from refine_streetlight_current import lighting_signature
import create_scene as source

STAGE=ROOT/'.build-staging/r13-chilis'
TEX=ROOT/'textures/r13-chilis'
PREFIX='R13 Chilis court facade '
FX=rect.PARAMS['front_x']; CY=rect.PARAMS['entry_center_y']
MATS={};BUILDERS={};ADDED=[];CHANGED=[];REMOVED=[];TEXTURES=[]
UV='R13PhysicalFinish'
PHOTO2='references/chilis-detail/01_新增原图/02_主入口门窗与字位_iziRetail_2026年1月.png'
REFERENCES=[PHOTO2]+['references/chilis-detail/01_新增原图/'+s for s in (
 '03_侧棚字标与竖向 COFFEE 招牌.jpg','04_入口外两块落地广告牌.jpg',
 '08_顺通道看门窗与雨棚连接.jpg','09_雨棚底部支撑近景.jpg','10_门内回看黑框玻璃门.jpg')]

# Exact single-object allowlist. Shared materials are never edited in place.
ENTRY_PREFIXES=('R12 Chilis building entry ','R12 Chilis terrace entry ')
FRONT_WRAPPED={
 'R12 Chilis building straight eaves with short radius corner returns',
 'R12 Chilis building straight flank individual silver fins',
 'R12 Chilis building straight flank slender glazing mullions',
 'R12 Chilis building straight flank and small corner glazing',
 'R12 Chilis building straight upper flank and small corner glazing',
}
ALCOVE={
 'R12 Chilis building red terracotta recessed elevator walls',
 'R12 Chilis building fine vertical red terracotta tile joints',
 'R12 Chilis building elevator two brushed door leaves',
 'R12 Chilis building elevator deep metal jambs',
 'R12 Chilis building elevator call plate',
}

def allowed(name):return name.startswith(ENTRY_PREFIXES+(PREFIX,)) or name in FRONT_WRAPPED|ALCOVE

def point(u,z,d=0.):return Vector((FX+d,CY+u,z))

def builder(name,material,smooth=False):
    if name not in BUILDERS:BUILDERS[name]=old.old.Batch(name,MATS[material],smooth)
    return BUILDERS[name]

def box(b,u,z,d,w,h,depth):b.box(point(u,z,d),(depth,w,h))

def rod(b,a,c,r=.01,sides=10):b.rod(a,c,r,segments=sides)

def path(b,pts,r=.006,closed=False):
    for a,c in zip(pts,pts[1:]+([pts[0]] if closed else [])):
        if (Vector(c)-Vector(a)).length>1e-7:rod(b,a,c,r,10)

def new_maps(key,color,roughness,metallic,kind,scale):
    """Small physical tiles; low contrast prevents painted-on large noise blobs."""
    rng=np.random.default_rng(13100+sum(map(ord,key)))
    n=512;yy,xx=np.mgrid[0:n,0:n]/n
    fine=finish.field(rng,n,113)-.5
    coarse=finish.field(rng,n,23)-.5
    grain=rng.random((n,n))-.5
    value=.008*fine+.003*grain
    rv=.025*fine
    if kind=='metal':
        lines=rng.random(n)-.5
        lines=np.tile(lines[None,:],(n,1))
        value=.024*lines+.005*fine
        rv=.095*lines+.021*fine
    elif kind=='fascia':
        lines=rng.random(n)-.5
        value=.013*np.tile(lines[None,:],(n,1))+.006*fine
        rv=.04*fine+.018*np.tile(lines[None,:],(n,1))
    elif kind=='stone':
        value=.033*coarse+.025*fine+.017*grain
        pores=(rng.random((n,n))>.994)*-.045
        value+=pores;rv=.058*fine+.022*grain
    elif kind=='canvas':
        weave=.5*np.sin(xx*256*math.pi)*np.sin(yy*256*math.pi)
        value=.016*weave+.018*fine+.009*coarse
        rv=.034*weave+.030*fine
    elif kind=='wood':
        streak=np.sin((xx*37+finish.field(rng,n,8)*.18)*2*math.pi)
        value=.020*streak+.012*fine+.005*grain
        rv=.033*streak+.018*fine
    elif kind=='acrylic':
        value=.003*fine+.001*grain;rv=.012*fine
    base=np.clip(np.array(finish.srgb_hex(color))[None,None,:]+value[:,:,None],0,1)
    rough=np.clip(roughness+rv,.12,.99)
    a=TEX/(key+'-basecolor.png');o=TEX/(key+'-roughness.png')
    finish.write_png(a,base)
    finish.write_png(o,np.stack((np.ones_like(rough),rough,np.ones_like(rough)*metallic),axis=-1))
    TEXTURES.extend({'path':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (a,o))
    mat=finish.pbr('R13 Chili court | '+key,color,roughness,metallic)
    sh=finish.shader_for(mat);sh.inputs['Emission Strength'].default_value=0
    sh.inputs['Emission Color'].default_value=(0,0,0,1)
    sh.inputs['Transmission Weight'].default_value=0
    sh.inputs['Alpha'].default_value=1
    sh.inputs['Coat Weight'].default_value=.16 if kind=='acrylic' else 0
    sh.inputs['Coat Roughness'].default_value=.28
    nodes=mat.node_tree.nodes;links=mat.node_tree.links
    uv=nodes.new('ShaderNodeUVMap');uv.uv_map=UV
    for p,col in ((a,True),(o,False)):
        im=bpy.data.images.load(str(p),check_existing=True)
        im.colorspace_settings.name='sRGB' if col else 'Non-Color'
        im.pack()
        node=nodes.new('ShaderNodeTexImage');node.image=im;node.extension='REPEAT'
        links.new(uv.outputs['UV'],node.inputs['Vector'])
        if col:links.new(node.outputs['Color'],sh.inputs['Base Color'])
        else:
            sep=nodes.new('ShaderNodeSeparateColor');links.new(node.outputs['Color'],sep.inputs['Color'])
            links.new(sep.outputs['Green'],sh.inputs['Roughness'])
    mat['r13_physical_tile_m']=1/scale;mat['r13_uv_scale']=scale
    mat['r13_native_metallic_scalar']=metallic;mat['no_added_emission']=True
    mat['r13_roughness_range']=[float(rough.min()),float(rough.max())]
    MATS[key]=mat
    return mat

def palette():
    # Paint/cloth are dielectric; exposed metal fittings use a high metal value.
    for args in (
       ('brushed-stainless','AEB4B4',.37,.92,'metal',1.6),
       ('dark-stainless','697573',.45,.88,'metal',1.6),
       ('warm-gold-metal','C5AA70',.30,.87,'metal',2.0),
       ('mauve-coated-fascia','786B76',.72,.02,'fascia',1.7),
       ('acrylic-orange-face','DB7B21',.30,0,'acrylic',3.0),
       ('acrylic-warm-channel','EAB04D',.28,0,'acrylic',3.0),
       ('red-orange-letter-return','A54424',.40,.10,'fascia',2.0),
       ('letter-back-casing','693621',.52,.18,'fascia',2.0),
       ('acrylic-green-pepper','66815B',.31,0,'acrylic',3.0),
       ('black-powder-coat','222826',.47,.02,'fascia',2.6),
       ('rubber-weather-seal','222422',.89,0,'fascia',3.0),
       ('cream-canvas','C3B493',.94,0,'canvas',3.0),
       ('canvas-seam','A99D83',.94,0,'canvas',3.0),
       ('grey-stone','95998F',.93,0,'stone',2.1),
       ('grey-stone-light','A0A197',.92,0,'stone',2.1),
       ('grey-stone-dark','899086',.96,0,'stone',2.1),
       ('cement-mortar','70756F',.97,0,'stone',3.0),
       ('terracotta-glazed','895846',.42,0,'fascia',3.0),
       ('terracotta-grout','9D7D66',.91,0,'stone',3.0),
       ('oak-cabinet','A68B61',.75,0,'wood',1.5),
       ('dark-interior-timber','634C3D',.76,0,'wood',1.8),
       ('warm-plaster','AD9D84',.95,0,'stone',2.0),
       ('unlit-opal-diffuser','D2D2C3',.57,0,'acrylic',3.0),
    ):new_maps(*args)

def assign_uv(obj):
    if obj.type!='MESH':return
    mesh=obj.data;uv=mesh.uv_layers.get(UV) or mesh.uv_layers.new(name=UV)
    mesh.uv_layers.active=uv;uv.active_render=True
    normal_matrix=obj.matrix_world.to_3x3().inverted().transposed()
    for poly in mesh.polygons:
        mat=mesh.materials[poly.material_index] if mesh.materials else None
        if not mat or not mat.name.startswith('R13 Chili court | '):continue
        scale=mat.get('r13_uv_scale',2.)
        n=(normal_matrix@poly.normal).normalized();axis=max(range(3),key=lambda i:abs(n[i]))
        axes=((1,2),(0,2),(0,1))[axis]
        for li in poly.loop_indices:
            p=obj.matrix_world@mesh.vertices[mesh.loops[li].vertex_index].co
            uv.data[li].uv=(p[axes[0]]*scale,p[axes[1]]*scale)
    obj['r13_finish_uv']=UV

def set_mat(obj,key,front_only=False):
    if obj.type=='FONT':
        obj.data=obj.data.copy();obj.data.materials.clear();obj.data.materials.append(MATS[key])
        # Convert only the allowed object so generated UVs survive native export.
        bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
        bpy.ops.object.convert(target='MESH');obj=bpy.context.view_layer.objects.active
    else:obj.data=obj.data.copy()
    if front_only:
        index=len(obj.data.materials);obj.data.materials.append(MATS[key])
        for poly in obj.data.polygons:
            center=obj.matrix_world@poly.center
            if center.x>FX-.13 and rect.PARAMS['left_y']+1.18<center.y<rect.PARAMS['right_y']-1.18:
                poly.material_index=index
    else:
        obj.data.materials.clear();obj.data.materials.append(MATS[key])
        for poly in obj.data.polygons:poly.material_index=0
    assign_uv(obj);CHANGED.append(obj.name)
    return obj

def existing_finishes():
    rules=[
      (('solid dusty mauve',''),'mauve-coated-fascia'),
    ]
    for obj in list(bpy.data.objects):
        n=obj.name
        if not allowed(n) or n.startswith(PREFIX):continue
        key=None
        if n in FRONT_WRAPPED:
            if 'eaves' in n or 'silver fins' in n:key='brushed-stainless'
            elif 'mullions' in n:key='black-powder-coat'
            # Preserve inherited opaque glazing route and tint, no new glass.
        elif n in ALCOVE:
            key=('terracotta-glazed' if 'recessed elevator walls' in n else
                 'terracotta-grout' if 'tile joints' in n else
                 'black-powder-coat' if 'call plate' in n else 'brushed-stainless')
        elif 'solid dusty mauve' in n:key='mauve-coated-fascia'
        elif 'CAFE AND BAR' in n or 'EST 1975' in n:key='warm-gold-metal'
        elif any(s in n for s in ('concave rolled silver','three folded cornice','paired long door pulls')):key='brushed-stainless'
        elif 'pilaster folded seam' in n:key='dark-stainless'
        elif 'diffuser strips' in n:key='unlit-opal-diffuser'
        elif 'cream retractable' in n:key='cream-canvas'
        elif 'sewn canvas seams' in n:key='canvas-seam'
        elif any(s in n for s in ('slender black','hinged retractable','transom','narrow reveal','menu stands','sloped menu lectern','small feet','interior table legs')):key='black-powder-coat'
        elif 'stone course' in n:key=['grey-stone','grey-stone-dark','grey-stone-light'][int(n[-1])]
        elif 'mortar bedding' in n or 'dark mineral floor' in n:key='cement-mortar'
        elif 'oak welcome cabinet' in n:key='oak-cabinet'
        elif 'timber planes' in n or 'table tops' in n:key='dark-interior-timber'
        elif 'warm back plane' in n:key='warm-plaster'
        if key:
            obj=set_mat(obj,key,n in FRONT_WRAPPED)
            # Gentle real edge catches only where metal is fabricated as bars.
            if any(s in n for s in ('slender black','three folded cornice','paired long door pulls','oak welcome cabinet')):
                mod=obj.modifiers.new('R13 small manufactured edge radius','BEVEL');mod.width=.0018
                mod.segments=2;mod.limit_method='ANGLE';mod.angle_limit=.45
                bpy.context.view_layer.objects.active=obj
                bpy.ops.object.modifier_apply(modifier=mod.name)
                assign_uv(obj)

def inset_poly(poly,d):
    """Mitered inset of the existing hand-shaped simple commercial contours."""
    area=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(poly,poly[1:]+[poly[0]]))*.5
    sign=1 if area>0 else -1;result=[]
    for i,p in enumerate(poly):
        before=Vector(poly[i-1]);here=Vector(p);after=Vector(poly[(i+1)%len(poly)])
        e1=(here-before).normalized();e2=(after-here).normalized()
        n1=Vector((-e1.y,e1.x))*sign;n2=Vector((-e2.y,e2.x))*sign
        bis=n1+n2
        if bis.length<1e-6:q=here+n1*d
        else:
            bis.normalize();length=min(d/max(.25,bis.dot(n1)),d*2.5)
            q=here+bis*length
        result.append(tuple(q))
    return result

def extruded(b,contour,back,front):
    n=len(contour)
    b.add([point(u,z,d) for d in (back,front) for u,z in contour],
          [tuple(reversed(range(n))),tuple(range(n,n*2))]+
          [(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)])

def continuous_lamp_channel(b,contour,depth,radius=.0045,sides=12):
    """A single watertight sweep, not capped cylinders meeting as beads.

    The contour is planar. A shared miter ring connects consecutive straight /
    Bezier edges without round caps, and keeps the original hard letter corners.
    Smooth shading then interpolates around the tube's circumference only.
    """
    points=[Vector(p) for p in contour];verts=[]
    for i,p in enumerate(points):
        e1=(p-points[i-1]).normalized();e2=(points[(i+1)%len(points)]-p).normalized()
        n1=Vector((-e1.y,e1.x));n2=Vector((-e2.y,e2.x));bis=n1+n2
        if bis.length<1e-6:bis=n1
        bis.normalize();miter=min(2.1,1/max(.4,abs(bis.dot(n1))))
        for j in range(sides):
            a=2*math.pi*j/sides;q=p+bis*(radius*math.sin(a)*miter)
            verts.append(point(q.x,q.y,depth+radius*math.cos(a)))
    count=len(points);faces=[]
    for i in range(count):
        for j in range(sides):
            faces.append((i*sides+j,((i+1)%count)*sides+j,
                         ((i+1)%count)*sides+(j+1)%sides,i*sides+(j+1)%sides))
    b.add(verts,faces)

def lamp_letters():
    for n in ('entry logo warm orange letter bodies','entry logo fine golden edge','entry logo green pepper apostrophe'):
        obj=bpy.data.objects.get('R12 Chilis building '+n)
        if obj:REMOVED.append(obj.name);bpy.data.objects.remove(obj,do_unlink=True)
    casing=builder('channel letters deep rear casing','letter-back-casing')
    shell=builder('channel letters red orange return walls','red-orange-letter-return')
    face=builder('channel letters inset amber acrylic faces','acrylic-orange-face')
    trim=builder('channel letters fine unlit diffuser outline','acrylic-warm-channel',True)
    fasteners=builder('channel letters concealed standoffs','dark-stainless',True)
    width,height,z=3.02,.91,3.80;sx=width/3.51;sz=height/1.22
    contours=[]
    for contour,xbase in old.glyphs():
        poly=[((x+xbase-1.755)*sx,z+(y-.61)*sz) for x,y in contour[:-1]]
        contours.append(poly)
        extruded(casing,poly,.073,.119)
        extruded(shell,poly,.116,.176)
        inner=inset_poly(poly,.006)
        extruded(face,inner,.176,.184)
        continuous_lamp_channel(trim,inset_poly(poly,.012),.186,.0045,12)
        center=np.asarray(poly).mean(axis=0)
        rod(fasteners,point(*center,.025),point(*center,.080),.013,12)
    green=builder('pepper apostrophe shaped acrylic front','acrylic-green-pepper')
    greenback=builder('pepper apostrophe extruded return','letter-back-casing')
    # Same tapered curved pepper silhouette; solid rather than an unrelated dash.
    pts=old.bezier((2.72,1.02),(2.96,1.11),(2.68,1.30),(2.87,1.27),18)
    pts+=old.bezier((2.87,1.27),(3.09,1.19),(2.98,.91),(2.74,.91),18)
    pepper=[((x-1.755)*sx,z+(y-.61)*sz) for x,y in pts]
    extruded(greenback,pepper,.10,.178);extruded(green,inset_poly(pepper,.003),.178,.188)
    return {'width_m':width,'height_m':height,'casing_depth_m':.111,
      'acrylic_face_thickness_m':.008,'diffuser_channel_diameter_m':.009,
      'glyph_source':'Unchanged R11/R12 hand-shaped commercial contours from old.glyphs(); layered in original footprint',
      'contour_sha256':hashlib.sha256(json.dumps(contours).encode()).hexdigest(),
      'no_emission':True,'evidence':PHOTO2}

def fabrication():
    steel=builder('door pull escutcheons hinge pins and countersunk fixings','brushed-stainless',True)
    black=builder('door closer articulated arms and threshold track','black-powder-coat')
    seals=builder('door leaf perimeter recessed weather seals','rubber-weather-seal')
    screw=builder('pilaster seam countersunk fastener heads','dark-stainless',True)
    for side in (-1,1):
        u=side*.16
        for z in (1.03,1.65):
            rod(steel,point(u,z,.075),point(u,z,.084),.027,20)
            for du in (-.017,.017):rod(screw,point(u+du,z,.084),point(u+du,z,.087),.003,8)
        for z in (.41,1.41,2.38):
            rod(steel,point(side*1.235,z-.062,.101),point(side*1.235,z+.062,.101),.012,16)
        # Closer body sits inside the transom; narrow two-link arm below it.
        box(black,side*.87,2.699,-.057,.23,.065,.056)
        path(black,[point(side*.92,2.662,-.035),point(side*.66,2.659,.024),point(side*.35,2.65,.01)],.009)
        for edge in (side*.02,side*1.215):box(seals,edge,1.447,-.008,.013,2.59,.021)
        box(seals,side*.64,.098,.026,1.205,.014,.026)
        for zu in (.16,1.25,2.35,3.18,4.29):
            for du in (-.284,.284):
                uu=side*5.30+du
                rod(screw,point(uu,zu,.252),point(uu,zu,.255),.0048,10)
    # Threshold grooves are real separated dark insets, not a featureless slab.
    for d in (.00,.035,.07,.105):box(seals,0,.054,d,2.61,.003,.004)
    awn=builder('awning rectangular arms brackets and knuckle end caps','black-powder-coat')
    bolts=builder('awning stainless pins and front rail end plates','brushed-stainless',True)
    seam=builder('awning rolled front hem and sewn end returns','canvas-seam',True)
    count=max(4,round(10.4/1.6))
    for i in range(count+1):
        u=-5.2+.12+10.16*i/count
        box(awn,u,3.13,.115,.095,.12,.075)
        for uu,zz,dd in ((u,3.13,.18),(u+.13,3.06,.76),(u,2.98,1.47)):
            rod(bolts,point(uu-.029,zz,dd),point(uu+.029,zz,dd),.029,16)
            rod(screw,point(uu+.030,zz,dd),point(uu+.034,zz,dd),.011,6)
        box(awn,u,3.185,.087,.083,.033,.048)
    for side in (-1,1):
        box(awn,side*5.2,2.985,1.485,.027,.061,.078)
        path(seam,[point(side*5.2,3.19,.14),point(side*5.2,3.1,.76),point(side*5.2,3.005,1.5)],.005)
    pts=[]
    for i in range(257):
        u=-5.2+10.4*i/256;scallop=.028*(1-math.cos(i/256*2*math.pi*16))
        pts.append(point(u,2.73-scallop,1.505))
    path(seam,pts,.004)
    obj=bpy.data.objects.get('R12 Chilis building entry cream retractable canvas and scalloped valance')
    if obj:
        # The inherited canopy/valance normals face down/inward. Thicken toward
        # those normals; the outer face must stay behind the existing Chinese
        # lettering at d=1.506 (valance face d=1.505).
        mod=obj.modifiers.new('R13 woven canopy real edge thickness','SOLIDIFY');mod.thickness=.004;mod.offset=1
        bpy.context.view_layer.objects.active=obj;bpy.ops.object.modifier_apply(modifier=mod.name);assign_uv(obj)
    # Paving retains precisely the existing tile layout, with shallow bevels only
    # at tile edges; no generic cement substitution over the metal architecture.
    bevel=builder('entry stone exposed front tile bevel band','grey-stone-dark')
    for i in range(16):
        a=-5.475+i*.70;b=min(a+.687,5.475)
        if b>a:
            bevel.add([point(a,.022,2.076),point(b,.022,2.076),point(b,.025,2.073),point(a,.025,2.073)],[(0,1,2,3)])
    # Photo 02's oak host stand carries a small dark chili's mark on its front.
    # Reuse the photographed identity contours rather than an arbitrary font.
    cabinet=builder('welcome cabinet small dark identity inlay','black-powder-coat')
    for contour,base in old.glyphs():
        poly=[(3.25+(x+base-1.755)*.205/3.51,.71+(y-.61)*.068/1.22) for x,y in contour[:-1]]
        extruded(cabinet,poly,1.057,1.060)

def finish_builders():
    for name,b in BUILDERS.items():
        data=bpy.data.meshes.new(PREFIX+name);data.from_pydata(b.vertices,[],b.faces);data.update()
        bm=bmesh.new();bm.from_mesh(data)
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(data);bm.free()
        obj=bpy.data.objects.new(PREFIX+name,data);bpy.data.collections['background'].objects.link(obj)
        obj.parent=bpy.data.objects['background'];data.materials.append(b.mat)
        for p in data.polygons:p.use_smooth=b.smooth
        obj['layer']='background';obj['category']='architecture';obj['r13_chilis_court']=True
        obj['reference_images']='Chilis-detail 02,08,09,10; no new emissive lighting'
        assign_uv(obj);ADDED.append(obj.name)

def build():
    STAGE.mkdir(parents=True,exist_ok=True);TEX.mkdir(parents=True,exist_ok=True)
    protected={o.name:old.signature(o) for o in bpy.data.objects if not allowed(o.name)}
    geometries={o.name:hashlib.sha256(array('f',[x for v in o.data.vertices for x in v.co]).tobytes()).hexdigest()
                for o in bpy.data.objects if o.type=='MESH' and o.name in FRONT_WRAPPED}
    light=lighting_signature()
    # Rerunning the staged builder is deterministic and never stacks details.
    for obj in list(bpy.data.objects):
        if obj.name.startswith(PREFIX):bpy.data.objects.remove(obj,do_unlink=True)
    palette();existing_finishes();letters=lamp_letters();fabrication();finish_builders()
    bpy.context.view_layer.update()
    unexpected=[n for n,h in protected.items() if n not in bpy.data.objects or old.signature(bpy.data.objects[n])!=h]
    if unexpected:raise RuntimeError('Protected source changed: '+str(unexpected))
    if light!=lighting_signature():raise RuntimeError('Lighting/exposure changed')
    for n,h in geometries.items():
        now=hashlib.sha256(array('f',[x for v in bpy.data.objects[n].data.vertices for x in v.co]).tobytes()).hexdigest()
        if now!=h:raise RuntimeError('Rectangular body/wrapped facade geometry altered: '+n)
    check=source.validate_scene()
    if check['status']!='passed':raise RuntimeError(json.dumps(check))
    mats={n:{'metallic_scalar':float(m.get('r13_native_metallic_scalar')),
              'roughness_range':list(m.get('r13_roughness_range')),'physical_tile_m':float(m.get('r13_physical_tile_m')),
              'emission':float(finish.shader_for(m).inputs['Emission Strength'].default_value)} for n,m in MATS.items()}
    assert all(v['emission']==0 for v in mats.values())
    scene=bpy.context.scene;scene['chilis_material_revision']='R13 court-facing fabrication and material finish'
    return {'revision':'R13','status':'passed','game_verified':False,'protected_objects':len(protected),
      'changed_existing_objects':CHANGED,'removed_superseded_objects':REMOVED,'new_objects':ADDED,
      'unexpected_protected_changes':unexpected,'rectangular_layout_unchanged':True,'lights_world_exposure_preserved':True,
      'wrapped_nonfront_faces_keep_original_material':True,'materials':mats,'textures':TEXTURES,
      'sign_fabrication':letters,'explicit_uv_channel':UV,'references_actually_viewed':REFERENCES,
      'native_requirements':['baseColor and roughness image export','scalar metallic','native NormalHeight remains zero',
        'all added emitters zero; acrylic is opaque unlit surface, not a simulated light source'],
      'photo_mapping':[
        {'photo':'新增02','elements':'灰紫门头细竖纹、三层拉丝银檐、凹银柱、独立双门把手、厚灯箱字红橙侧壳/橙面/浅色内缘、小金字、灰色错缝门前石材、右侧迎宾台'},
        {'photo':'新增08/09','elements':'米色织物雨棚前后双面、黑细支臂与金属关节、波浪布前沿、卷边缝线'},
        {'photo':'新增10','elements':'门框内侧闭门机构和窄门楣细节；仅重建可见五金，不改变门位'},
        {'photo':'原Chilis08','elements':'红褐窄砖凹口和竖拉丝不锈钢电梯，按釉砖处理而非水泥'},
      ],
      'limits':['Exact millimetre construction details inferred from photo proportions, not a measured survey.',
        'Seasonal snow, flowers, people and Christmas decorations remain excluded.',
        'R13 changes only court-facing building/entry families; left terrace, all court/bench/native anchors protected.',
        'Native static glass route unchanged; game-compatible opening geometry retained.'],
      'nba_validation':check}

def renders(folder,only=None):
    scene=bpy.context.scene;cam=scene.camera
    scene.render.engine='CYCLES';scene.cycles.samples=20;scene.cycles.use_denoising=True
    scene.render.resolution_x=1500;scene.render.resolution_y=1050;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    for label,pos,target,lens in (
      ('entry-overall',(FX+3.05,CY,2.8),(FX,CY,2.40),9.5),
      ('sign-close',(FX+2.45,CY-1.9,3.82),(FX+.10,CY,3.80),44),
      ('entry-right',(FX+3.45,CY+2.15,2.1),(FX,CY+.55,1.6),30),
      ('awning-below',(FX+2.4,CY-4.5,1.75),(FX+.70,CY,2.75),24),
    ):
        if only and label!=only:continue
        cam.location=pos;cam.data.type='PERSP';cam.data.lens=lens
        cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler()
        scene.render.filepath=str(folder/f'r13-chilis-{label}.png');bpy.ops.render.render(write_still=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',default=str(STAGE/'scene-chilis-material.blend'))
    ap.add_argument('--render',action='store_true')
    ap.add_argument('--render-sign',action='store_true')
    args=ap.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    output=Path(args.output).resolve()
    if not output.is_relative_to(STAGE.resolve()):raise RuntimeError('Only R13 staging output is allowed')
    prefs=bpy.context.preferences.filepaths;prefs.temporary_directory=str(STAGE);prefs.save_version=0
    prefs.file_preview_type='NONE';prefs.use_auto_save_temporary_files=False
    report=build();bpy.ops.wm.save_as_mainfile(filepath=str(output))
    report.update(output=str(output),source_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    (STAGE/'chilis-material-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('R13_CHILIS_STAGE_READY '+json.dumps({'output':str(output),'changed':len(CHANGED),'new':len(ADDED),'protected':report['protected_objects']}),flush=True)
    if args.render:renders(STAGE)
    elif args.render_sign:renders(STAGE,'sign-close')

if __name__=='__main__':main()
