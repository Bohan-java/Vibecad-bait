"""Photo-based incremental R02 court detailing, applied to an open .blend.

All sources, backups and outputs stay inside this project. No game package writes.
Run after refine_environment_r02.py; it leaves the NBA design anchors untouched.
"""
from __future__ import annotations
import argparse
import json
import math
import sys
from pathlib import Path
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import create_scene as src


def setup():
    for name in ('gameplay_anchors','reference_half','open_half','fence','background','lights','preview_helpers'):
        src.GROUPS[name] = (bpy.data.collections[name], bpy.data.objects[name])
    mat_names = {
        'steel':'Hoops | brushed grey steel', 'white':'Hoops | white board markings',
        'orange':'Hoops | vermilion rim', 'fence':'Fence | grey framework',
        'banner':'Fence | near-black NBA panels', 'padding':'Hoops | charcoal safety padding'}
    for k,name in mat_names.items(): src.MATS[k] = bpy.data.materials[name]
    for k,name,color,rough,metal in (
        ('bolts','R02 | galvanized bolt heads',(.38,.42,.43),.43,.7),
        ('rubber','R02 | dark rubber lower rail',(.037,.042,.043),.91,0),
        ('foot','R02 | weathered concrete feet',(.33,.34,.31),.95,0),
        ('netwhite','R02 | net off white',(.76,.77,.72),.9,0),
        ('netred','R02 | net muted red',(.57,.045,.063),.87,0),
        ('netblue','R02 | net navy',(.042,.088,.17),.88,0)):
        src.MATS[k] = bpy.data.materials.get(name) or src.material(name,color,rough,metal)


def delete_exact(name):
    if (obj:=bpy.data.objects.get(name)):
        bpy.data.objects.remove(obj, do_unlink=True)


def detail(obj, refs='07,11,14,15,16'):
    obj['r02_detail'] = True
    obj['reference_images'] = refs
    obj['reconstruction'] = 'Observed construction language; minor dimensions inferred. Visual source only.'
    return obj


def cylinder(name,xyz,radius,depth,mat,layer,axis='Z',vertices=12):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices,radius=radius,depth=depth,location=xyz)
    obj=bpy.context.object; obj.name=name
    if axis=='X': obj.rotation_euler.y=math.pi/2
    elif axis=='Y': obj.rotation_euler.x=math.pi/2
    obj.data.materials.append(mat)
    src.link(obj,layer)
    return detail(obj)


def hoops():
    for side,suffix in ((-1,'reference'),(1,'open')):
        layer='reference_half' if side<0 else 'open_half'
        pole_x=side*(src.LENGTH/2+.95); face_x=side*src.BOARD_X; rim_x=side*src.RIM_X
        base=bpy.data.objects[f'Base plate.{suffix}']
        base.dimensions=(.53,.59,.032); base.location.z=.025
        upright=bpy.data.objects[f'Support upright.{suffix}']
        upright.dimensions=(.18,.19,3.18); upright.location.z=1.62
        # Photographs show an exposed, slim grey post rather than a large pad.
        delete_exact(f'Column safety wrap.{suffix}')
        for prefix in ('Cantilever top','Cantilever brace','Board rear mount'):
            delete_exact(f'{prefix}.{suffix}')
        for name,a,b,w,d in (
            ('main reach',(pole_x,0,3.13),(face_x+side*.06,0,src.RIM_TOP-.085),.16,.16),
            ('upper reach',(pole_x,0,3.34),(face_x+side*.08,0,3.63),.047,.047),
            ('rear brace',(pole_x,0,2.66),(pole_x-side*.81,0,3.075),.065,.065)):
            detail(src.beam(f'R02 {name}.{suffix}',a,b,w,d,src.MATS['steel'],layer,.006))
        for sign in (-1,1):
            detail(src.beam(f'R02 board diagonal {sign}.{suffix}',
                (face_x+side*.065,0,3.10),(face_x+side*.065,sign*.79,3.73),
                .023,.027,src.MATS['steel'],layer,.003))
            detail(src.beam(f'R02 back stay {sign}.{suffix}',
                (pole_x-side*.26,0,3.18),(face_x+side*.075,sign*.73,3.18),
                .025,.025,src.MATS['steel'],layer,.003))
        for y in (-.215,.215):
            for dx in (-.175,.175):
                cylinder(f'R02 floor anchor.{suffix}.{dx}.{y}',(pole_x+dx,y,.051),.018,.018,src.MATS['bolts'],layer)
                cylinder(f'R02 anchor washer.{suffix}.{dx}.{y}',(pole_x+dx,y,.042),.027,.006,src.MATS['bolts'],layer)
        detail(src.cube(f'R02 black lower board rail.{suffix}',
            (face_x,0,src.BOARD_BOTTOM-.015),(.08,src.BOARD_WIDTH+.06,.07),src.MATS['rubber'],layer,.01))
        for yy in (-src.BOARD_WIDTH/2,src.BOARD_WIDTH/2):
            detail(src.cube(f'R02 black rail return {yy}.{suffix}',
                (face_x,yy,src.BOARD_BOTTOM+.20),(.075,.064,.43),src.MATS['rubber'],layer,.009))
        for yy in (-.76,.76):
            for zz in (src.BOARD_BOTTOM+.12,src.BOARD_BOTTOM+src.BOARD_HEIGHT-.12):
                cylinder(f'R02 board fixing.{suffix}.{yy}.{zz}',(face_x-side*.029,yy,zz),.012,.01,src.MATS['bolts'],layer,'X')
        for obj in list(bpy.data.objects):
            if obj.name.startswith('Board target ') and obj.name.endswith('.'+suffix):
                bpy.data.objects.remove(obj,do_unlink=True)
        # A single annular mesh removes coplanar overlap at the four corners.
        w,h,stroke=.6096,.4572,.0508
        bottom=src.RIM_TOP-.03
        tx=face_x-side*.025
        yz=[(-w/2,bottom),(w/2,bottom),(w/2,bottom+h),(-w/2,bottom+h),
            (-w/2+stroke,bottom+stroke),(w/2-stroke,bottom+stroke),
            (w/2-stroke,bottom+h-stroke),(-w/2+stroke,bottom+h-stroke)]
        faces=[(i,(i+1)%4,(i+1)%4+4,i+4) for i in range(4)]
        if side>0: faces=[tuple(reversed(f)) for f in faces]
        mesh=bpy.data.meshes.new(f'R02 target ring mesh.{suffix}')
        mesh.from_pydata([(tx,y,z) for y,z in yz],[],faces);mesh.update()
        target=bpy.data.objects.new(f'R02 board target outline.{suffix}',mesh)
        src.GROUPS[layer][0].objects.link(target);src.link(target,layer)
        mesh.materials.append(src.MATS['white']);detail(target)
        # Reference net has off-white upper, red centre and navy lower strands.
        for obj in list(bpy.data.objects):
            if obj.name.startswith('Net ') and obj.name.endswith('.'+suffix): bpy.data.objects.remove(obj,do_unlink=True)
        n,levels=12,8
        radii=[.227,.221,.210,.190,.162,.145,.132,.12]
        zs=[src.RIM_TOP-.029-k*.061 for k in range(levels)]
        for direction in (-1,1):
            for i in range(n):
                points=[]
                for k in range(levels):
                    angle=2*math.pi*(i+direction*k*.5)/n
                    points.append((rim_x+radii[k]*math.cos(angle),radii[k]*math.sin(angle),zs[k]))
                for band,(start,end,material) in enumerate(((0,2,'netwhite'),(2,5,'netred'),(5,7,'netblue'))):
                    detail(src.tube(f'R02 net {direction}.{i}.{band}.{suffix}',points[start:end+1],.0027,src.MATS[material],layer))
        # Small attachment loops rather than a floating net below the rim.
        for i in range(n):
            a=2*math.pi*i/n
            center=Vector((rim_x+.23*math.cos(a),.23*math.sin(a),src.RIM_TOP-.017))
            points=[tuple(center+Vector((.009*math.cos(t)*math.cos(a),.009*math.cos(t)*math.sin(a),.014*math.sin(t)))) for t in [j*math.tau/12 for j in range(12)]]
            detail(src.tube(f'R02 net hook.{suffix}.{i}',points,.002,src.MATS['orange'],layer,True))


def fence_details():
    posts=[obj for obj in bpy.data.objects if 'fence' in obj.name.lower() and ' post ' in obj.name]
    for i,obj in enumerate(posts):
        x,y,_=obj.location
        detail(src.cube(f'R02 fence weighted foot {i}',(x,y,.054),(.37,.43,.105),src.MATS['foot'],'fence',.036),'07,12,14,17')
        for z in (.74,2.04,3.62):
            detail(src.cube(f'R02 fence clamp {i}.{z}',(x,y,z),(.086,.086,.033),src.MATS['bolts'],'fence',.004),'07,12,14')
    # Supported perimeter signs, one each side near the reference end.
    for sign,x in ((1,-9.5),(-1,-11.9)):
        y=sign*9.17; inward=-sign
        z=2.03
        panel=detail(src.cube(f'R02 fence A badge {sign}',(x,y+inward*.031,z),(.61,.028,.87),src.MATS['banner'],'fence',.095),'12,13,15,18')
        points=[]
        for i in range(64):
            a=i*math.tau/64
            # Vertically elongated badge outline, drawn on the court-facing side.
            points.append((x+.252*math.copysign(abs(math.cos(a))**.4,math.cos(a)),y+inward*.05,z+.377*math.copysign(abs(math.sin(a))**.4,math.sin(a))))
        detail(src.tube(f'R02 A badge outline {sign}',points,.012,src.MATS['white'],'fence',True),'13,15,18')
        facing='-y' if sign>0 else '+y'
        detail(src.text_mesh(f'R02 fence A glyph {sign}','A',(x,y+inward*.052,z),.62,src.MATS['white'],'fence',facing),'13,15,18')


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    output=Path(args.output).resolve()
    if not output.is_relative_to(ROOT): raise RuntimeError('Output must stay inside zgc-court')
    runtime=ROOT/'.build-staging'/'r02'/'runtime'; runtime.mkdir(parents=True,exist_ok=True)
    prefs=bpy.context.preferences.filepaths
    prefs.temporary_directory=str(runtime); prefs.file_preview_type='NONE'; prefs.use_auto_save_temporary_files=False; prefs.save_version=0
    for obj in list(bpy.data.objects):
        if obj.get('r02_detail'): bpy.data.objects.remove(obj,do_unlink=True)
    setup(); hoops(); fence_details(); src.bind_ground_artwork()
    bpy.context.view_layer.update()
    report=src.validate_scene()
    if report['status']!='passed': raise RuntimeError(json.dumps(report))
    bpy.context.scene['source_version']='R02'
    bpy.context.scene['art_stage']='Reference detail pass; building separation provisional pending new views'
    output.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    (ROOT/'source'/'geometry_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('ZGC_COURT_R02_READY '+json.dumps({'file':str(output),'objects':len(bpy.data.objects),'geometry':report['status']}))


if __name__=='__main__': main()
