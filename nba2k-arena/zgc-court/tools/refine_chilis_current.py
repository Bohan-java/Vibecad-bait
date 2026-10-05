"""R11 incremental Chili's facade reconstruction from the supplied photographs.

Only the explicit Chili's object family is replaceable.  The two visible facade
types are independent modules: entry (mauve sign, black double door) and terrace
(open silver fins, large letters).  Terrace side/rotation is an editable site
inference until the user confirms its relationship to the basketball court.
No lights, emission, game assets or editable source are changed by default.
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
from mathutils import Matrix, Vector

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import refine_architecture_r02 as old
import refine_details_r03 as finish
import create_scene as source
from refine_streetlight_current import lighting_signature

PI=math.pi
STAGE=ROOT/'.build-staging/chilis-current'
PREFIX='R11 Chilis building '
REVISION='R11 photograph separated entry and terrace facades'
BUILDERS={}
MATERIALS={}
ADDED=[]
PARAMS={'entry_center_y':-4.2,'entry_width':10.6,'terrace_side':-1,
        'terrace_center_x':-28.1,'terrace_width':6.8,'terrace_angle_deg':0.,
        'terrace_side_confirmed':True}
terrace_layout={'u_range':(-3.4,3.4),'depth':3.35,'fountain_u':.30,
                'fountain_offset':2.20,'tables':[(-2.0,1.65,0),(2.0,1.65,0)],
                'interior_tables':[(-1.85,-1.25,0),(1.85,-1.25,0)],
                'parasols':[(-2.10,2.60,True,PI/2),(2.10,2.60,True,-PI/2)],
                'planters':[(-3.0,.55),(3.0,.55)]}
entry_layout={'menus':[(-2.90,1.05),(-2.24,1.05),(-1.58,1.05)],
              'welcome':True,'lectern':(2.5,1.20),'host_desk':(3.25,.80)}

REPLACE_SUFFIXES={
    'curved low building shell','dark curved glazing','upper pale glazing',
    'local brown sign fascia','vertical glazing frames','fine upper vertical ribs',
    'continuous silver curved cornice','principal orange identity','cafe descriptor',
    'establishment date','green apostrophe','roof projection recessed panels','observed roof projection',
    'cream fabric awning and scalloped valance','awning slender metal arms',
    'awning wordmark','rust tile elevator alcove','fine vertical tile joints',
    'brushed elevator doors','elevator trim','alcove secondary logo',
    'alcove cafe descriptor','alcove date','small lift control plate'}
REPLACE={f'R02 architecture Chilis {n}' for n in REPLACE_SUFFIXES}


def material(name,color,roughness=.7,metallic=0.):
    mat=finish.pbr('R11 Chilis | '+name,color,roughness,metallic)
    sh=finish.shader_for(mat)
    sh.inputs['Emission Strength'].default_value=0
    sh.inputs['Emission Color'].default_value=(0,0,0,1)
    mat.use_backface_culling=False
    MATERIALS[name]=mat
    return mat


def mark(obj,refs='new 01,02,07,08,09,10; older Chili facade photographs'):
    obj['r11_chilis']=True;obj['layer']='background';obj['category']='architecture'
    obj['reference_images']=refs
    obj['dimension_status']='Photo proportions, not a measured survey; site orientation explicitly recorded in report'
    ADDED.append(obj.name)


def mesh(name,vertices,faces,mat,smooth=False):
    data=bpy.data.meshes.new(PREFIX+name)
    data.from_pydata(vertices,[],faces);data.update()
    bm=bmesh.new();bm.from_mesh(data)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(data);bm.free()
    obj=bpy.data.objects.new(PREFIX+name,data)
    bpy.data.collections['background'].objects.link(obj);obj.parent=bpy.data.objects['background']
    data.materials.append(mat)
    for f in data.polygons:f.use_smooth=smooth
    mark(obj)
    return obj


def batch(name,mat,smooth=False):
    if name not in BUILDERS:BUILDERS[name]=(old.Batch(name,MATERIALS[mat],smooth),smooth)
    return BUILDERS[name][0]


def facade_frame(face,u=0.,z=0.,offset=0.):
    """Return world point, outward normal, local left-to-right tangent (metres)."""
    if face=='entry':return old.front(PARAMS['entry_center_y']+u,z,offset)
    if face=='alcove':
        p,n,t=old.front(8.72,z,offset-.89)
        return p+t*(u+.70),n,t
    if face!='terrace':raise ValueError(face)
    side=PARAMS['terrace_side']
    n=Vector((0.,side,0.));t=Vector((-side,0.,0.))
    rotation=Matrix.Rotation(math.radians(PARAMS['terrace_angle_deg']),3,'Z')
    n=rotation@n;t=rotation@t
    y=old.CY+side*(old.RY+.01)
    p=Vector((PARAMS['terrace_center_x'],y,z))+t*u+n*offset
    return p,n,t


def facade_point(face,u=0.,z=0.,offset=0.):return facade_frame(face,u,z,offset)[0]


def box_on(builder,face,u,z,offset,width,height,depth):
    p,n,t=facade_frame(face,u,z,offset)
    builder.box(p,(depth,width,height),math.atan2(n.y,n.x))


def ribbon(builder,face,u0,u1,z0,z1,offset=0.,segments=40):
    vertices=[]
    for i in range(segments+1):
        u=u0+(u1-u0)*i/segments
        vertices += [facade_point(face,u,z0,offset),facade_point(face,u,z1,offset)]
    builder.add(vertices,[(2*i,2*i+2,2*i+3,2*i+1) for i in range(segments)])


def tube_path(builder,points,radius=.012,segments=8,closed=False):
    for a,b in zip(points,points[1:]+([points[0]] if closed else [])):
        if (Vector(b)-Vector(a)).length>1e-7:builder.rod(a,b,radius,segments=segments)


def folded_rail(builder,frames,z,depth=.14,height=.075):
    """Sweep a closed bent-sheet profile with planar bands and tiny bevels."""
    profile=[(-depth*.44,-height*.5),(depth*.40,-height*.5),(depth*.53,-height*.28),
             (depth*.53,height*.28),(depth*.40,height*.5),(-depth*.44,height*.5)]
    vertices=[]
    for p,n,t in frames:
        vertices.extend(p+n*d+Vector((0,0,z+zz)) for d,zz in profile)
    q=len(profile);faces=[tuple(reversed(range(q))),tuple(range((len(frames)-1)*q,len(frames)*q))]
    faces.extend((i*q+j,(i+1)*q+j,(i+1)*q+(j+1)%q,i*q+(j+1)%q)
                 for i in range(len(frames)-1) for j in range(q))
    builder.add(vertices,faces)


def linear_text(name,body,face,u,z,offset,width,height,mat,extrude=.006):
    data=bpy.data.curves.new(PREFIX+name,'FONT');data.body=body
    data.align_x='CENTER';data.align_y='CENTER';data.size=1
    data.extrude=extrude;data.bevel_depth=.0016;data.bevel_resolution=2
    obj=bpy.data.objects.new(PREFIX+name,data)
    bpy.data.collections['background'].objects.link(obj);obj.parent=bpy.data.objects['background']
    p,n,t=facade_frame(face,u,z,offset);obj.location=p
    obj.rotation_euler=(PI/2,0,math.atan2(n.y,n.x)+PI/2)
    data.materials.append(MATERIALS[mat]);mark(obj)
    bpy.context.view_layer.update()
    xs=[c[0] for c in obj.bound_box];ys=[c[1] for c in obj.bound_box]
    obj.scale.x=width/(max(xs)-min(xs));obj.scale.y=height/(max(ys)-min(ys))
    return obj


def chinese(name,face,width,u=0.):
    data=bpy.data.curves.new(PREFIX+name,'FONT')
    data.body='奇利斯美式小餐馆';data.align_x='CENTER';data.align_y='CENTER'
    data.font=bpy.data.fonts.load(str(Path(bpy.app.binary_path).parent/'5.2/datafiles/fonts/Noto Sans CJK Regular.woff2'))
    data.size=.28;data.extrude=.0012
    obj=bpy.data.objects.new(PREFIX+name,data)
    bpy.data.collections['background'].objects.link(obj);obj.parent=bpy.data.objects['background']
    p,n,t=facade_frame(face,u,2.875,1.506);obj.location=p
    obj.rotation_euler=(PI/2,0,math.atan2(n.y,n.x)+PI/2)
    data.materials.append(MATERIALS['letter black']);mark(obj,'new 01,02')
    bpy.context.view_layer.update();w=max(c[0] for c in obj.bound_box)-min(c[0] for c in obj.bound_box)
    h=max(c[1] for c in obj.bound_box)-min(c[1] for c in obj.bound_box)
    # Uniform character proportions are more important than stretching glyphs
    # to fill a guessed width; letter height occupies about 60% of the valance.
    size=min(width/w,.185/h);obj.scale*=size
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
    bpy.ops.object.convert(target='MESH')
    return bpy.context.view_layer.objects.active


def bezier(p0,p1,p2,p3,steps=12):
    return [tuple((1-t)**3*a+3*(1-t)**2*t*b+3*(1-t)*t*t*c+t**3*d
                  for a,b,c,d in zip(p0,p1,p2,p3)) for t in [i/steps for i in range(steps)]]


def glyphs():
    """Hand-shaped commercial lowercase contours, rather than a generic font."""
    def path(start,*pieces):
        out=[];p=start
        for item in pieces:
            if len(item)==2:out.append(p);p=item
            else:
                b,c,end=item;out.extend(bezier(p,b,c,end));p=end
        out.append(p);return out
    c=path((.61,.61),((.43,.91),(.02,.84),(.02,.40)),((.02,-.05),(.48,-.1),(.64,.16)),(.52,.25),((.40,.05),(.18,.12),(.18,.39)),((.18,.69),(.40,.76),(.51,.55)),(.61,.61))
    h=path((.02,1.22),(.18,1.22),(.18,.67),((.29,.84),(.62,.83),(.62,.49)),(.62,0),(.46,0),(.46,.46),((.46,.73),(.18,.65),(.18,.43)),(.18,0),(.02,0),(.02,1.22))
    i=[(.02,0),(.18,0),(.18,.77),(.02,.77),(.02,0)]
    l=[(.02,0),(.18,0),(.18,1.22),(.02,1.22),(.02,0)]
    s=path((.58,.66),((.40,.92),(.03,.81),(.03,.56)),((.03,.38),(.21,.32),(.39,.29)),((.59,.26),(.46,.09),(.29,.12)),((.21,.12),(.12,.19),(.09,.24)),(.0,.14),((.20,-.15),(.63,-.02),(.63,.22)),((.63,.45),(.31,.45),(.22,.50)),((.04,.65),(.35,.76),(.48,.57)),(.58,.66))
    circle=[(.10+.099*math.cos(k*2*PI/32),1.03+.099*math.sin(k*2*PI/32)) for k in range(33)]
    return [(c,0),(h,.76),(i,1.52),(circle,1.52),(l,1.90),(i,2.28),(circle,2.28),(s,2.88)]


def logo(face,width,height,z,offset=.17,name=None):
    name=name or face
    red=batch(name+' logo warm orange letter bodies','logo orange',True)
    gold=batch(name+' logo fine golden edge','logo edge',True)
    leaf=batch(name+' logo green pepper apostrophe','logo green',True)
    sx=width/3.51;sz=height/1.22
    for contour,xbase in glyphs():
        # The same contour creates a real extrusion and a fine proud edge.
        pts=[facade_point(face,(x+xbase-1.755)*sx,z+(y-.61)*sz,offset) for x,y in contour[:-1]]
        if len(pts)<3:continue
        n=len(pts);norm=facade_frame(face)[1]
        red.add(pts+[p+norm*.031 for p in pts],[tuple(reversed(range(n))),tuple(range(n,n*2))]+[(k,(k+1)%n,(k+1)%n+n,k+n) for k in range(n)])
        tube_path(gold,[p+norm*.035 for p in pts],.011 if width>2.5 else .008,8,True)
    # Curled pepper apostrophe in green; it is not a floating straight dash.
    points=bezier((2.72,1.02),(2.96,1.11),(2.68,1.30),(2.87,1.27),14)
    points+=bezier((2.87,1.27),(3.09,1.19),(2.98,.91),(2.74,.91),16)
    tube_path(leaf,[facade_point(face,(x-1.755)*sx,z+(y-.61)*sz,offset+.035) for x,y in points],.025 if width>2.5 else .019,10)


def cornice(face,width):
    metal=batch(face+' three folded cornice rails','brushed silver')
    dark=batch(face+' cornice narrow reveal','metal shadow')
    frames=[facade_frame(face,-width/2+width*i/88,0,.08) for i in range(89)]
    for z,h,d in ((3.18,.09,.13),(4.415,.085,.20),(4.515,.064,.16),(4.615,.070,.21)):
        folded_rail(metal,frames,z,d,h)
    for z in (4.46,4.56):ribbon(dark,face,-width/2,width/2,z,z+.021,.067)


def concave_columns(face,width):
    silver=batch(face+' concave rolled silver pilasters','brushed silver',True)
    seams=batch(face+' pilaster folded seam flanges','silver dark')
    lens=batch(face+' narrow vertical diffuser strips unlit','diffuser')
    for side in (-1,1):
        u=side*width/2;vs=[];steps=20
        # Sculpted inward channel, with two rolled edges and a coved crown.
        for iz,z in enumerate((.035,4.61)):
            for j in range(steps+1):
                uu=-.27+.54*j/steps
                depth=.23-.17*math.sqrt(max(0,1-(uu/.27)**2))
                top=z+(.11*(abs(uu)/.27)**3 if iz else 0.)
                vs.append(facade_point(face,u+uu,top,depth))
        silver.add(vs,[(j,j+1,steps+2+j,steps+1+j) for j in range(steps)])
        for du in (-.284,.284):
            tube_path(silver,[facade_point(face,u+du,.025,.245),facade_point(face,u+du,4.73,.245)],.024,10)
            box_on(seams,face,u+du,2.37,.12,.034,4.70,.11)
        box_on(seams,face,u,2.03,.099,.10,2.58,.040)
        box_on(lens,face,u,2.03,.127,.064,2.52,.011)


def glazing_and_entry(face,width):
    if face=='terrace':
        glazing=batch('terrace five wide weather screen edge strips','clear weather screen')
        frame=batch('terrace slender ivory weather screen mullions','screen ivory')
        seams=batch('terrace lower clear screen seams','screen ivory')
        for j in range(5):
            a=-width/2+.26+(width-.52)*j/5;b=-width/2+.26+(width-.52)*(j+1)/5
            # Static native translucent shaders are not established compatible.
            # Model perimeter seams and leave the clear viewing area physically
            # open instead of exporting an opaque or unverified alpha sheet.
            for u in (a+.035,b-.035):box_on(glazing,face,u,1.61,.041,.005,2.94,.004)
            for z in (.095,3.125):box_on(glazing,face,(a+b)/2,z,.041,b-a-.069,.005,.004)
            box_on(frame,face,a,1.62,.067,.048,3.02,.065)
        box_on(frame,face,width/2-.26,1.62,.067,.048,3.02,.065)
        for z in (.085,3.14):box_on(frame,face,0,z,.050,width-.48,.047,.075)
        for z in (.19,):box_on(seams,face,0,z,.061,width-.55,.009,.007)
        return
    glass=batch(face+' clear window and door perimeter seams','clear weather screen')
    frames=batch(face+' slender black window and double door frames','black frame')
    silver=batch(face+' paired long door pulls hinges and threshold','brushed silver',True)
    depths=batch(face+' door transom and narrow reveals','metal shadow')
    # Black double door is an actual pair inside an inset structural reveal.
    centers=[-width/2+.28+(width-.56)*i/10 for i in range(11)]
    if face=='entry':centers=sorted([v for v in centers if abs(v)>1.31]+[-1.31,1.31])
    for a,b in zip(centers,centers[1:]):
        if face=='entry' and a<1.30 and b> -1.30:continue
        for u in (a+.030,b-.030):box_on(glass,face,u,1.615,.023,.005,2.995,.004)
        for z in (.116,3.114):box_on(glass,face,(a+b)/2,z,.023,b-a-.06,.005,.004)
        box_on(frames,face,a,1.615,.065,.041,3.0,.080)
    for z in (.095,3.14):box_on(frames,face,0,z,.049,width,.055,.09)
    if face=='entry':
        for side in (-1,1):
            u=side*.640
            for du in (-.595,.595):box_on(glass,face,u+du,1.455,-.043,.004,2.61,.004)
            for du in (-.630,.630):box_on(frames,face,u+du,1.44,.035,.075,2.70,.08)
            for z in (.105,2.79):box_on(frames,face,u,z,.035,1.32,.076,.08)
            pullu=side*.16
            tube_path(silver,[facade_point(face,pullu,.94,.124),facade_point(face,pullu,1.74,.124)],.018,10)
            for z in (1.03,1.65):tube_path(silver,[facade_point(face,pullu,z,.061),facade_point(face,pullu,z,.128)],.010,8)
            for z in (.41,2.38):box_on(silver,face,side*1.235,z,.099,.036,.13,.054)
        box_on(depths,face,0,2.945,-.015,2.62,.28,.08)
        box_on(glass,face,0,3.085,.013,2.54,.005,.004)
        box_on(silver,face,0,.035,.08,2.64,.034,.22)


def awning(face,width):
    fabric=batch(face+' cream retractable canvas and scalloped valance','canvas')
    arms=batch(face+' hinged retractable awning frame','awning steel',True)
    seams=batch(face+' sewn canvas seams','canvas seam')
    segments=80;verts=[]
    for i in range(segments+1):
        u=-width/2+width*i/segments
        for d,z in ((.14,3.19),(.76,3.10),(1.50,3.005)):verts.append(facade_point(face,u,z,d))
    fabric.add(verts,[(3*i+k,3*(i+1)+k,3*(i+1)+k+1,3*i+k+1) for i in range(segments) for k in (0,1)])
    verts=[]
    for i in range(segments+1):
        u=-width/2+width*i/segments
        scallop=.028*(1-math.cos(i/segments*2*PI*16))
        verts.extend((facade_point(face,u,3.01,1.505),facade_point(face,u,2.73-scallop,1.505)))
    fabric.add(verts,[(i*2,i*2+2,i*2+3,i*2+1) for i in range(segments)])
    count=max(4,round(width/1.6))
    for i in range(count+1):
        u=-width/2+.12+(width-.24)*i/count
        a=facade_point(face,u,3.13,.18);b=facade_point(face,u+.13,3.06,.76);c=facade_point(face,u,2.98,1.47)
        tube_path(arms,[a,b,c],.023,8)
        p,n,t=facade_frame(face,u,3.12,.15)
        arms.rod(p-t*.045,p+t*.045,.037,segments=12)
        tube_path(seams,[facade_point(face,u,3.20,.15),facade_point(face,u,3.11,.76),facade_point(face,u,3.01,1.49)],.003,5)
    tube_path(arms,[facade_point(face,-width/2,2.989,1.487),facade_point(face,width/2,2.989,1.487)],.032,10)
    chinese(face+' exact Chinese canvas inscription',face,3.05 if face=='entry' else 2.98,.8 if face=='entry' else 0.)


def facade(face):
    width=PARAMS[face+'_width']
    if face=='entry':
        fascia=batch('entry solid dusty mauve sign panel','mauve fascia')
        ribbon(fascia,face,-width/2,width/2,3.20,4.39,.012,60)
    else:
        recess=batch('terrace fin backing recessed shadow','metal shadow')
        ribbon(recess,face,-width/2,width/2,3.2,4.39,-.015)
    fins=batch(face+' individually folded vertical facade fins','brushed silver',True)
    if face=='terrace':
        for j in range(round(width/.098)):
            u=-width/2+.05+j*.098
            # A folded V face has both relief and edge highlight under daylight.
            vs=[facade_point(face,u+du,z,d) for z in (3.22,4.375) for du,d in ((-.034,.025),(0,.064),(.034,.025))]
            fins.add(vs,[(0,1,4,3),(1,2,5,4)])
    concave_columns(face,width);cornice(face,width+.66)
    glazing_and_entry(face,width);awning(face,width-.20)
    if face=='entry':
        logo(face,3.02,.91,3.80,.12)
        linear_text('entry CAFE AND BAR','CAFE & BAR',face,-3.60,3.76,.113,1.46,.22,'warm lettering')
        linear_text('entry EST 1975','EST. 1975',face,3.68,3.76,.113,1.44,.205,'warm lettering')
    else:
        logo(face,3.38,1.13,3.80,.11)
        linear_text('terrace CAFE AND BAR','CAFE & BAR',face,-2.61,3.28,.125,1.48,.22,'warm lettering')
        linear_text('terrace EST 1975','EST. 1975',face,2.62,3.28,.125,1.47,.22,'warm lettering')


def retained_curve():
    """Rebuild only restaurant shell/windows, leaving LINK and every site layer."""
    low,high=old.CY-old.RY+.06,old.CY+old.RY-.06
    ys=[low+(high-low)*i/100 for i in range(101)]
    footprint=[(old.BACK_X,low)]+[(old.front(y)[0].x,y) for y in ys]+[(old.BACK_X,high)]
    shell=batch('retained curved restaurant envelope','roof stone')
    n=len(footprint)
    shell.add([(x,y,4.365) for x,y in footprint],[tuple(range(n))])
    wall_segments=[(footprint[-1],footprint[0])]
    if PARAMS['terrace_side']>0:wall_segments.append((footprint[0],footprint[1]))
    else:wall_segments.append((footprint[-2],footprint[-1]))
    for a,b in wall_segments:
        shell.add([(a[0],a[1],-3.7),(b[0],b[1],-3.7),(b[0],b[1],4.36),(a[0],a[1],4.36)],[(0,1,2,3)])
    # Side facade enclosure is a narrow actual volume joined into the existing
    # shell, not a disconnected billboard.  Position remains switchable.
    w=PARAMS['terrace_width'];p,norm,t=facade_frame('terrace')
    v=[p+t*u-norm*d+Vector((0,0,z)) for z in (.06,4.36) for u,d in ((-w/2,0),(w/2,0),(w/2,2.55),(-w/2,2.55))]
    shell.add(v,[(4,5,6,7),(0,4,7,3),(2,6,5,1),(3,7,6,2)])
    room=batch('terrace inner warm plaster return wall','interior warm wall')
    ribbon(room,'terrace',-w/2+.1,w/2-.1,.07,3.10,-2.49,1)
    floor=batch('terrace continuous interior red floor','interior red floor')
    floor.add([facade_point('terrace',-w/2,.035,0),facade_point('terrace',w/2,.035,0),
               facade_point('terrace',w/2,.035,-2.52),facade_point('terrace',-w/2,.035,-2.52)],[(0,1,2,3)])
    skirting=batch('terrace inner low wood wainscot','interior wood')
    ribbon(skirting,'terrace',-w/2+.1,w/2-.1,.06,.68,-2.47,1)
    glass=batch('unmodified extent flank curved glass','store glazing')
    ribs=batch('curved flank individual silver ribs','brushed silver',True)
    upper=batch('curved flank upper glazing','upper glazing')
    frames=batch('curved flank slender mullions','black frame')
    c=PARAMS['entry_center_y'];ew=PARAMS['entry_width']
    spans=[(low,c-ew/2-.30),(c+ew/2+.30,7.18),(10.25,high)]
    for y0,y1 in spans:
        if y1<=y0:continue
        seg=max(8,int((y1-y0)*10));vs=[];uv=[]
        for i in range(seg+1):
            y=y0+(y1-y0)*i/seg;p,n,t=old.front(y,offset=.01)
            vs += [(p.x,p.y,.10),(p.x,p.y,3.145)]
            uv += [(p.x,p.y,3.20),(p.x,p.y,4.38)]
        fs=[(2*i,2*i+2,2*i+3,2*i+1) for i in range(seg)]
        glass.add(vs,fs);upper.add(uv,fs)
        for j in range(max(1,int((y1-y0)/.14))):
            y=y0+.07+j*.14;p,n,t=old.front(y,3.78,.055)
            ribs.box(p,(.070,.026,1.14),math.atan2(n.y,n.x))
        for j in range(max(1,int((y1-y0)/.95))):
            y=y0+.05+j*.95;p,n,t=old.front(y,1.62,.060)
            frames.box(p,(.095,.04,3.04),math.atan2(n.y,n.x))
    # Continuous rails around the original curve remain correctly aligned.
    rail=batch('continuous original curved folded eaves','brushed silver')
    frames=[old.front(y,0,.07) for y in ys]
    for z,h,d in ((.09,.065,.13),(3.145,.068,.13),(4.40,.08,.20),(4.51,.064,.16),(4.615,.07,.21)):
        folded_rail(rail,frames,z,d,h)


def entry_paving():
    joints=batch('entry local grey stone mortar bedding','entry joint')
    w=PARAMS['entry_width']+.35;segments=48;v=[]
    for i in range(segments+1):
        u=-w/2+w*i/segments
        v.extend((facade_point('entry',u,.021,.05),facade_point('entry',u,.021,2.12)))
    joints.add(v,[(2*i,2*i+1,2*i+3,2*i+2) for i in range(segments)])
    for row in range(7):
        d=.08+row*.287
        for col in range(16):
            a=-w/2+col*.70+(.35 if row%2 else 0);b=min(a+.687,w/2)
            if a>=w/2 or b<=-w/2:continue
            a=max(a,-w/2)
            tile=batch('entry grey staggered stone course '+str((col+row)%3),'entry stone '+str((col+row)%3))
            tile.add([facade_point('entry',a,.025,d),facade_point('entry',b,.025,d),
                      facade_point('entry',b,.025,d+.274),facade_point('entry',a,.025,d+.274)],[(0,1,2,3)])


def entry_interior():
    """Only the shallow room elements visible through new02/new10 windows."""
    w=PARAMS['entry_width']-.60
    wall=batch('entry shallow interior warm back plane','interior warm wall')
    ribbon(wall,'entry',-w/2,w/2,.06,3.10,-1.92,64)
    wood=batch('entry shallow interior warm timber planes','interior wood')
    ribbon(wood,'entry',-w/2,w/2,.06,.65,-1.89,64)
    floor=batch('entry shallow interior dark mineral floor','entry joint')
    v=[]
    for j in range(49):
        u=-w/2+w*j/48;v.extend((facade_point('entry',u,.034,0),facade_point('entry',u,.034,-1.93)))
    floor.add(v,[(2*i,2*i+2,2*i+3,2*i+1) for i in range(48)])
    upholstery=batch('entry visible low green upholstered benches','interior green upholstery')
    legs=batch('entry visible interior table legs','black frame')
    top=batch('entry visible shallow wood table tops','interior tabletop')
    for side in (-1,1):
        center=side*3.2
        box_on(upholstery,'entry',center,.47,-1.42,2.36,.13,.45)
        box_on(upholstery,'entry',center,.85,-1.71,2.38,.69,.095)
        box_on(wood,'entry',center,.23,-1.46,2.35,.34,.39)
        for shift in (-.60,.60):
            u=center+shift
            box_on(top,'entry',u,.775,-.85,.82,.053,.63)
            box_on(legs,'entry',u,.401,-.85,.066,.70,.064)
            box_on(legs,'entry',u,.055,-.85,.52,.047,.38)
        for k in range(11):
            box_on(wood,'entry',center-1.12+k*.22,.39,-1.687,.013,.62,.012)


def roof_louvres():
    body=batch('terrace roof projection solid body and folded cap','roof stone')
    housing=batch('three roof louvre framed recesses','roof recess')
    trim=batch('roof louvre fine reveal borders','silver dark')
    blades=batch('roof louvre pitched blades','brushed silver')
    box_on(body,'terrace',0,4.89,-1.15,4.78,1.08,2.00)
    box_on(body,'terrace',0,5.475,-1.15,4.96,.09,2.18)
    for uu in (-1.57,0,1.57):
        box_on(housing,'terrace',uu,4.92,-.132,1.36,.55,.035)
        for side in (-1,1):box_on(trim,'terrace',uu+side*.698,4.92,-.101,.037,.61,.08)
        for z in (4.61,5.23):box_on(trim,'terrace',uu,z,-.101,1.43,.037,.08)
        for j in range(9):
            z=4.662+j*.062
            # Sloped folded blade with dark reveal behind, not a black rectangle.
            blades.add([facade_point('terrace',uu-.657,z-.012,-.084),facade_point('terrace',uu+.657,z-.012,-.084),
                        facade_point('terrace',uu+.657,z+.025,-.14),facade_point('terrace',uu-.657,z+.025,-.14)],[(0,1,2,3)])


def alcove():
    tile=batch('red terracotta recessed elevator walls','terracotta')
    grout=batch('fine vertical red terracotta tile joints','terracotta grout')
    p,n,t=old.front(8.72);back=p-n*.89
    def wall(builder,center,w,h,d):builder.box(center,(d,w,h),math.atan2(n.y,n.x))
    wall(tile,back+Vector((0,0,1.65)),3.03,3.30,.10)
    for side in (-1,1):wall(tile,p-n*.40+t*side*1.50+Vector((0,0,1.65)),.10,3.3,1.01)
    wall(tile,p-n*.40+Vector((0,0,3.26)),3.10,.10,1.02)
    for i in range(57):wall(grout,back+n*.057+t*(-1.48+i*2.96/56)+Vector((0,0,1.65)),.005,3.22,.003)
    for z in (.81,1.63,2.45):wall(grout,back+n*.058+Vector((0,0,z)),3.00,.005,.004)
    doors=batch('elevator two brushed door leaves','elevator steel')
    trim=batch('elevator deep metal jambs','brushed silver')
    for side in (-1,1):wall(doors,back+n*.087+t*(-.71+side*.255)+Vector((0,0,1.25)),.505,2.35,.024)
    for dx in (-1.255,-.165):wall(trim,back+n*.10+t*dx+Vector((0,0,1.27)),.065,2.46,.081)
    wall(trim,back+n*.10+t*(-.71)+Vector((0,0,2.51)),1.16,.066,.081)
    # A local frame allows the same drawn lettering to work in the recess.
    logo('alcove',1.11,.42,2.01,.074)
    linear_text('alcove cafe descriptor','CAFE & BAR','alcove',0,1.64,.080,1.09,.133,'warm lettering')
    linear_text('alcove established date','EST. 1975','alcove',0,1.42,.080,.84,.113,'warm lettering')
    controls=batch('elevator call plate','black frame')
    wall(controls,back+n*.10+t*(-.02)+Vector((0,0,1.17)),.07,.22,.027)


def palette():
    for name,color,rough,metal in (
        ('brushed silver','B0B5B0',.43,.66),('silver dark','7F8783',.51,.57),('metal shadow','414A48',.72,.10),
        ('diffuser','E0E0D4',.79,.0),('mauve fascia','766870',.81,.03),('store glazing','354847',.25,.16),
        ('upper glazing','778D89',.44,.24),('black frame','232B29',.57,.29),('canvas','C5B698',.98,0),
        ('canvas seam','A99B82',.97,0),('awning steel','494D47',.72,.25),('letter black','2F3230',.83,0),
        ('warm lettering','D9C899',.50,.20),('logo orange','C76024',.54,.14),('logo edge','ECA34A',.45,.14),
        ('logo green','65A45B',.57,.06),('roof stone','ACAFA5',.89,0),('roof recess','707B74',.89,0),
        ('terracotta','A4664D',.75,.03),('terracotta grout','BF886D',.92,0),('elevator steel','A4AAA5',.35,.79),
        ('entry joint','737C75',.98,0),('entry stone 0','9B9F96',.96,0),('entry stone 1','979E94',.96,0),('entry stone 2','A1A398',.96,0),
        ('clear weather screen','9FB0AB',.17,.05),('screen ivory','C0BEB1',.61,.21),
        ('interior warm wall','B5A184',.94,0),('interior red floor','89543E',.97,0),('interior wood','67483A',.89,0),
        ('interior green upholstery','315248',.91,0),('interior tabletop','A18059',.85,0)):
        material(name,color,rough,metal)


def signature(obj):
    h=hashlib.sha256();h.update(obj.type.encode());h.update(array('f',[v for r in obj.matrix_world for v in r]).tobytes())
    if obj.type=='MESH':
        h.update(array('f',[v for p in obj.data.vertices for v in p.co]).tobytes())
        h.update(array('i',[l.vertex_index for l in obj.data.loops]).tobytes())
        for uv in obj.data.uv_layers:h.update(array('f',[v for l in uv.data for v in l.uv]).tobytes())
        h.update(array('i',[p.material_index for p in obj.data.polygons]).tobytes())
    elif obj.type=='FONT':h.update(str((obj.data.body,obj.data.size,obj.data.extrude,obj.data.bevel_depth,obj.data.fill_mode)).encode())
    if hasattr(obj.data,'materials'):
        for m in obj.data.materials:
            if not m:continue
            h.update(m.name.encode())
            if m.use_nodes:
                for node in m.node_tree.nodes:
                    h.update((node.name+node.type).encode())
                    if node.type=='TEX_IMAGE':h.update(str(node.image.filepath if node.image else None).encode())
                    for i in node.inputs:
                        if hasattr(i,'default_value'):h.update(str(list(i.default_value) if hasattr(i.default_value,'__len__') else i.default_value).encode())
    return h.hexdigest()


def build(include_furniture=True):
    ADDED.clear();BUILDERS.clear();MATERIALS.clear()
    furniture=None;allowed=set(REPLACE)
    if include_furniture:
        import chilis_terrace_details as furniture
        allowed.update(furniture.OLD_NAMES)
    protected={o.name:signature(o) for o in bpy.data.objects if o.name not in allowed and not o.name.startswith(('R11 Chilis building ','R11 Chilis terrace '))}
    before_light=lighting_signature();removed=[]
    for o in list(bpy.data.objects):
        if o.name in REPLACE or o.name.startswith(PREFIX):removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
    palette();retained_curve();facade('entry');facade('terrace');roof_louvres();alcove();entry_paving();entry_interior()
    for name,(builder,smooth) in BUILDERS.items():
        if builder.vertices:mesh(name,builder.vertices,builder.faces,builder.mat,smooth)
    furniture_report=furniture.build(sys.modules[__name__]) if furniture else {'status':'not included in this stage'}
    bpy.context.view_layer.update()
    changes=[n for n,h in protected.items() if n not in bpy.data.objects or signature(bpy.data.objects[n])!=h]
    if changes:raise RuntimeError('Protected objects changed: '+str(changes))
    if lighting_signature()!=before_light:raise RuntimeError('Light or exposure changed')
    validation=source.validate_scene()
    if validation['status']!='passed':raise RuntimeError(json.dumps(validation))
    report={'revision':'R11','status':'passed','game_verified':False,'parameters':PARAMS,
            'facade_frames':{face:{**dict(zip(('origin','outward_normal','tangent'),[list(v) for v in facade_frame(face)])),
                                  'width_m':PARAMS[face+'_width']} for face in ('entry','terrace')},
            'removed_old_building_objects':removed,
            'new_building_objects':ADDED,'protected_objects':len(protected),'unexpected_changes':changes,
            'non_chilis_geometry_materials_transforms_uv_preserved':True,'lights_world_exposure_preserved':True,
            'facade_evidence':{'entry':'New02 and court photo19: mauve board, black double door, small logo, scalloped awning, coved silver columns',
                'terrace':'New01: larger logo directly over individual silver fins, no mauve sign panel, cream Chinese awning',
                'awning':'New08/09/10: articulated slender black supports and scalloped valance',
                'roof':'New01: three real horizontal louvre panels'},
            'layout_limits':['User confirmed: facing the main entry, fountain terrace is around the left corner (negative Y); exact turning angle remains inferred.',
                'Entry glazing and terrace clear weather-screen viewing areas are open geometry with perimeter seams and framing; optical transparent sheets are deliberately not exported because the native static alpha path is unverified.',
                'Metric widths, heights, curvature and site gaps remain photo-derived estimates.',
                'Seasonal snow, flowers, Christmas decorations and interior people are not copied into permanent summer architecture.'],
            'furniture':furniture_report,'nba_validation':validation}
    bpy.context.scene['chilis_detail_revision']=REVISION
    return report


def renders(folder):
    scene=bpy.context.scene;camera=scene.camera
    scene.render.engine='CYCLES';scene.cycles.samples=24;scene.cycles.use_denoising=True
    scene.render.resolution_x=1400;scene.render.resolution_y=1050;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    for key,face,u,z,offset,lens in (
        ('entry','entry',0,2.8,4.15,13),('entry-door','entry',.5,2.1,3.6,27),
        ('terrace','terrace',0,2.9,11,40),('terrace-oblique','terrace',5,4.2,10,40),
        ('terrace-louvres','terrace',0,5.1,9,52)):
        target=facade_point(face,0,2.6,0)
        camera.location=facade_point(face,u,z,offset)
        camera.data.type='PERSP';camera.data.lens=lens
        camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler()
        scene.render.filepath=str(folder/f'chilis-{key}.png');bpy.ops.render.render(write_still=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=str(STAGE/'scene-chilis.blend'))
    parser.add_argument('--terrace-side',type=int,choices=(-1,1),default=-1)
    parser.add_argument('--terrace-angle',type=float,default=0.)
    parser.add_argument('--side-confirmed',action='store_true');parser.add_argument('--render',action='store_true')
    parser.add_argument('--without-furniture',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    output=Path(args.output).resolve()
    if not output.is_relative_to(ROOT) or output==ROOT/'source/scene.blend':raise RuntimeError('Use a project staging file; root publishes the final source.')
    PARAMS.update(terrace_side=args.terrace_side,terrace_angle_deg=args.terrace_angle,terrace_side_confirmed=args.side_confirmed)
    STAGE.mkdir(parents=True,exist_ok=True);output.parent.mkdir(parents=True,exist_ok=True)
    prefs=bpy.context.preferences.filepaths;prefs.temporary_directory=str(STAGE);prefs.save_version=0;prefs.file_preview_type='NONE';prefs.use_auto_save_temporary_files=False
    report=build(not args.without_furniture)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    report.update(output=str(output),source_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    (STAGE/'chilis-building-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('CHILIS_STAGE_READY '+json.dumps({'output':str(output),'protected':report['protected_objects'],'new_building_objects':len(ADDED)}),flush=True)
    if args.render:renders(STAGE)


if __name__=='__main__':main()
