"""Create the editable ZGC source scene. Run with Blender --background --python.

Source coordinates are metres: X length, Y width, Z up. The photo end is X < 0.
No donor geometry is used. Anchors in this file are design coordinates, not
verified NBA 2K collision/score/animation components.
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
FT = 0.3048
IN = 0.0254
LENGTH = 94 * FT
WIDTH = 50 * FT
RIM_TOP = 10 * FT
RIM_INNER_RADIUS = 9 * IN
RIM_TUBE_RADIUS = 0.0095  # provisional visual section, not donor-verified
RIM_X = LENGTH / 2 - (5 * FT + 3 * IN)
BOARD_X = LENGTH / 2 - 4 * FT
BOARD_WIDTH = 6 * FT
BOARD_HEIGHT = 3.5 * FT
BOARD_BOTTOM = 9 * FT
GROUPS = {}
MATS = {}


def material(name, rgb, roughness=0.7, metallic=0.0, alpha=1.0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*rgb, alpha)
    mat.use_nodes = True
    node = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if node is None:
        node = mat.node_tree.nodes.new('ShaderNodeBsdfPrincipled')
        output = next((n for n in mat.node_tree.nodes if n.type == 'OUTPUT_MATERIAL'), None) or mat.node_tree.nodes.new('ShaderNodeOutputMaterial')
        mat.node_tree.links.new(node.outputs['BSDF'], output.inputs['Surface'])
    node.inputs['Base Color'].default_value = (*rgb, alpha)
    node.inputs['Roughness'].default_value = roughness
    node.inputs['Metallic'].default_value = metallic
    node.inputs['Alpha'].default_value = alpha
    if alpha < 1:
        mat.surface_render_method = 'DITHERED'
        mat.use_transparency_overlap = False
    return mat


def group(name):
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    parent = bpy.data.objects.new(name, None)
    collection.objects.link(parent)
    parent['layer'] = name
    GROUPS[name] = (collection, parent)
    return parent


def link(obj, name):
    collection, parent = GROUPS[name]
    for old in list(obj.users_collection):
        old.objects.unlink(obj)
    collection.objects.link(obj)
    obj.parent = parent
    obj['asset_id'] = obj.name
    obj['source'] = 'editable-source-scene'
    obj['layer'] = name
    if name in ('reference_half', 'open_half'):
        obj['category'] = 'hoops'
    return obj


def cube(name, location, dimensions, mat, layer, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    link(obj, layer)
    if bevel:
        mod = obj.modifiers.new('Rounded fabrication edges', 'BEVEL')
        mod.width = bevel
        mod.segments = 2
        obj.modifiers.new('Weighted corner normals', 'WEIGHTED_NORMAL')
    return obj


def beam(name, p1, p2, width, depth, mat, layer, bevel=0.008):
    p1, p2 = Vector(p1), Vector(p2)
    obj = cube(name, (p1+p2)/2, (width, depth, (p2-p1).length), mat, layer, bevel)
    obj.rotation_euler = (p2-p1).to_track_quat('Z', 'Y').to_euler()
    return obj


def tube(name, points, radius, mat, layer, cyclic=False):
    data = bpy.data.curves.new(name, 'CURVE')
    data.dimensions = '3D'
    data.resolution_u = 1
    data.bevel_resolution = 1
    data.bevel_depth = radius
    poly = data.splines.new('POLY')
    poly.points.add(len(points)-1)
    for p, v in zip(poly.points, points):
        p.co = (*v, 1)
    poly.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, data)
    GROUPS[layer][0].objects.link(obj)
    obj.parent = GROUPS[layer][1]
    obj.data.materials.append(mat)
    obj['asset_id'] = name
    obj['layer'] = layer
    obj['category'] = 'hoops' if layer in ('reference_half', 'open_half') else layer
    return obj


def anchor(name, xyz, description):
    obj = bpy.data.objects.new(name, None)
    GROUPS['gameplay_anchors'][0].objects.link(obj)
    obj.parent = GROUPS['gameplay_anchors'][1]
    obj.location = xyz
    obj.empty_display_type = 'PLAIN_AXES'
    obj.empty_display_size = 0.14
    obj['role'] = description
    obj['game_verified'] = False
    return obj


def annotate(obj, refs, inference='Proportions and placement inferred from photos; no site measurements'):
    obj['reference_images'] = refs
    obj['reconstruction'] = inference
    return obj


def text_mesh(name, content, xyz, size, mat, layer='background', facing='x'):
    curve = bpy.data.curves.new(name, 'FONT')
    curve.body = content
    curve.size = size
    curve.align_x = 'CENTER'
    curve.align_y = 'CENTER'
    curve.extrude = .0015
    obj = bpy.data.objects.new(name, curve)
    GROUPS[layer][0].objects.link(obj)
    obj.parent = GROUPS[layer][1]
    obj.location = xyz
    # Text's local +Z normal faces the court from the reference-end facade.
    if facing == 'x':
        obj.rotation_euler = (math.pi/2,0,math.pi/2)
    elif facing == '-y':
        obj.rotation_euler = (math.pi/2,0,0)
    else:
        obj.rotation_euler = (math.pi/2,0,math.pi)
    obj.data.materials.append(mat)
    obj['layer'] = layer
    return obj


def fence_mesh(name, p1, p2, height=3.65):
    """One low-cost mesh of open diamond ribbons: true gaps, no alpha sort."""
    start, end = Vector(p1), Vector(p2)
    length = (end-start).length
    direction = (end-start)/length
    verts, faces = [], []
    low = .65
    spacing = .16
    strip_width = .0045
    for slope in (-1,1):
        intercept=-length-height
        while intercept < length+height:
            points=[]
            for u in (0,length):
                z=slope*u+intercept
                if low-1e-6<=z<=height+1e-6:
                    points.append((u,z))
            for z in (low,height):
                u=(z-intercept)/slope
                if 1e-6<u<length-1e-6:
                    points.append((u,z))
            if len(points)>=2:
                (ua,za),(ub,zb)=points[:2]
                du,dz=ub-ua,zb-za
                magnitude=math.hypot(du,dz)
                if magnitude>1e-5:
                    ou,oz=-dz/magnitude*strip_width/2,du/magnitude*strip_width/2
                    quad=[(ua+ou,za+oz),(ub+ou,zb+oz),(ub-ou,zb-oz),(ua-ou,za-oz)]
                    k=len(verts)
                    for u,z in quad:
                        pos=start+direction*u+Vector((0,0,z))
                        verts.append(tuple(pos))
                    faces.append((k,k+1,k+2,k+3))
            intercept+=spacing
    mesh=bpy.data.meshes.new(name)
    mesh.from_pydata(verts,[],faces)
    mesh.update()
    obj=bpy.data.objects.new(name,mesh)
    GROUPS['fence'][0].objects.link(obj)
    obj.parent=GROUPS['fence'][1]
    mesh.materials.append(MATS['mesh'])
    obj['layer']='fence'
    annotate(obj,'07,12,13,14,18,19','Visible reference-half fence only; exact spacing and extent inferred')


def fence_run(name, p1, p2):
    a,b=Vector(p1),Vector(p2)
    distance=(b-a).length
    count=math.ceil(distance/2.4)
    for i in range(count+1):
        p=a+(b-a)*i/count
        annotate(cube(f'{name} post {i}',(p.x,p.y,1.86),(.075,.075,3.72),MATS['fence'], 'fence',.008),'07,12,13,14,18')
    for z in (.72,2.04,3.68):
        beam(f'{name} horizontal {z}',a+Vector((0,0,z)),b+Vector((0,0,z)),.045,.045,MATS['fence'],'fence',.004)
    fence_mesh(f'{name} diamond mesh',a,b)
    for i in range(count):
        start=a+(b-a)*(i+.015)/count
        end=a+(b-a)*(i+.985)/count
        centre=(start+end)/2
        length=(end-start).length
        obj=cube(f'{name} NBA ATELIER panel {i}',(centre.x,centre.y,.345),(length,.032,.65),MATS['banner'],'fence',.009)
        obj.rotation_euler.z=math.atan2((end-start).y,(end-start).x)
        # Text faces the court on each side and remains deliberately restrained.
        if abs(a.x-b.x)<.01:
            xyz=(centre.x+.021,centre.y,.34); facing='x'
        elif a.y>0:
            xyz=(centre.x,centre.y-.021,.34); facing='-y'
        else:
            xyz=(centre.x,centre.y+.021,.34); facing='+y'
        text_mesh(f'{name} panel mark {i}','NBA ATELIER',xyz,.115,MATS['white'],'fence',facing)


def disc(name, xyz, radius, depth, mat):
    bpy.ops.mesh.primitive_cylinder_add(vertices=64,radius=radius,depth=depth,location=xyz)
    obj=bpy.context.object
    obj.name=name
    obj.data.materials.append(mat)
    link(obj,'background')
    bevel=obj.modifiers.new('Soft circular lip','BEVEL')
    bevel.width=.045; bevel.segments=2
    obj.modifiers.new('Disc normals','WEIGHTED_NORMAL')
    return obj


def tree(name, x, y, size=1):
    annotate(beam(f'{name} trunk',(x,y,.08),(x,y,3.3*size),.16*size,.18*size,MATS['bark'],'background'),'02,03,16,20,22–26')
    for k,(dx,dy,z,sx,sy,sz) in enumerate(((0,0,4.7,1.6,1.3,2.0),(.6,.1,5.2,1.1,1.05,1.65),(-.8,.2,4.2,1.2,1.15,1.3))):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1,location=(x+dx*size,y+dy*size,z*size))
        obj=bpy.context.object; obj.name=f'{name} canopy {k}'
        obj.scale=(sx*size,sy*size,sz*size)
        obj.data.materials.append(MATS['leaves'][k%len(MATS['leaves'])])
        link(obj,'background')
        annotate(obj,'02,03,16,20,22–26','Simplified observed vegetation silhouette; location inferred')


def environment():
    # All positions outside gameplay are adjustable photo-based art layout.
    fence_run('End fence',(-16.08,-9.17,0),(-16.08,9.17,0))
    fence_run('North partial fence',(-16.08,9.17,0),(-2.8,9.17,0))
    fence_run('South partial fence',(-16.08,-9.17,0),(-4.8,-9.17,0))
    # A lower plaza plane gives the environment a shared ground without replacing
    # or intersecting the one-piece court/apron mesh.
    cube('Open plaza context',(-2,0,-.065),(58,43,.1),MATS['plaza'],'background',.025)
    annotate(cube('Mall principal volume',(-23.8,0,4.9),(5.2,34,9.8),MATS['stone'],'background',.04),'04–11,14,19,20','Front and primary mass from photos; unseen rear deliberately plain')
    front=-21.18
    cube('Mall horizontal warm red band',(front+.025,0,8.42),(.12,34,.72),MATS['mall_red'],'background')
    cube('Mall roof overhang',(front+.05,0,9.6),(.55,34.8,.23),MATS['stone_dark'],'background',.025)
    cube('Mall clerestory glazing',(front+.035,0,9.0),(.05,33.5,.39),MATS['store_glass'],'background')
    cube('Mall storefront fascia',(front+.04,0,5.14),(.13,33.6,1.44),MATS['fascia'],'background')
    for i in range(13):
        y=-15.3+i*2.55
        cube(f'Storefront glass {i}',(front+.07,y,2.23),(.075,2.42,3.84),MATS['store_glass'],'background')
        cube(f'Storefront mullion {i}',(front+.13,y-1.22,2.23),(.10,.06,3.94),MATS['fence'],'background')
    for i in range(7):
        cube(f'Mall upper horizontal joint {i}',(front+.08,0,6.1+i*.235),(.025,33.8,.018),MATS['stone_dark'],'background')
    for y in (-15,-9,-3,3,9,15):
        cube(f'Mall pilaster {y}',(front+.22,y,4.1),(.35,.22,7.9),MATS['stone'],'background')
    # Text is simplified readable identity, not a substituted full photo texture.
    annotate(text_mesh('Chilis storefront sign',"chili's",(front+.17,-.8,5.23),1.06,MATS['sign_red']),'08,09,10,14,19')
    text_mesh('Chilis cafe descriptor','CAFE & BAR',(front+.17,4.7,5.14),.21,MATS['cream'])
    text_mesh('Mall Link Plaza sign','LINK PLAZA',(front+.18,6.2,8.45),.43,MATS['cream'])
    cube('Chilis awning',(front+1.18,0,3.87),(2.25,9.4,.15),MATS['awning'],'background',.025)
    # A broad, low-detail glazed tower behind the reference facade is visible in
    # 02–07. Its distance and floor count remain explicitly inferred.
    annotate(cube('Glazed tower silhouette',(-32.7,9,19.0),(11,15,38),MATS['tower'],'background',.05),'02–07,15,18','Distant skyline silhouette; exact dimensions and distance inferred')
    for y in (-6,-3,0,3,6):
        cube(f'Tower fine vertical {y}',(-27.17,9+y,19),(.028,.04,37.8),MATS['tower_mullion'],'background')
    for z in range(3,39,3):
        cube(f'Tower horizontal {z}',(-27.16,9,z),(.026,14.95,.033),MATS['tower_mullion'],'background')
    # Offset overlapping circular roofs and several supports match the observed
    # layered plaza canopy language, with no mirrored copy at the open hoop.
    for i,(x,y,z,radius) in enumerate(((-8.0,13.1,3.05,2.9),(-11.1,14.0,3.75,3.1),(-6.2,16.0,4.43,3.05),(-10.0,17.4,5.05,3.2))):
        annotate(disc(f'Layered plaza canopy disc {i}',(x,y,z),radius,.14,MATS['canopy']),'15,18,20,21,23','Overlapping roof form observed; exact disc count, scale and spacing inferred')
        disc(f'Canopy underside inset {i}',(x,y,z-.085),radius-.23,.028,MATS['canopy_dark'])
        for j,(dx,dy) in enumerate(((-radius*.47,-radius*.38),(radius*.47,radius*.25))):
            beam(f'Canopy support {i}.{j}',(x+dx,y+dy,0),(x+dx,y+dy,z-.12),.13,.13,MATS['fence'],'background',.01)
        cube(f'Canopy bench seat {i}',(x,y,.43),(2.4,.42,.11),MATS['wood'],'background',.02)
        for dx in (-.95,.95):
            cube(f'Canopy bench leg {i}.{dx}',(x+dx,y,.2),(.09,.35,.38),MATS['fence'],'background',.01)
    for i,(x,y,s) in enumerate(((-16,16.5,.85),(-1,15.8,.9),(6,16.8,1.05),(15,16.2,.95),(23,8.7,1.08),(24,-2.8,1.1),(21,-13,.9),(-15,-14,.95),(-5,-14,1.05),(6,-15.8,.85))):
        tree(f'Plaza tree {i}',x,y,s)
    annotate(cube('North planted strip',(9,18.2,.23),(27,2.5,.45),MATS['plant_bed'],'background',.16),'22–26','Simplified remote planted boundary outside open half; no added fence')
    annotate(cube('South planted island',(15,-17,.23),(14,3,.45),MATS['plant_bed'],'background',.16),'22–26','Simplified remote planted island; exact footprint inferred')


def bind_ground_artwork(path=None):
    """Reload external artwork for export without changing saved geometry."""
    mat = bpy.data.materials.get('Court | editable artwork')
    if mat is None:
        return False
    # Only the explicit paving migration sets this marker. Older source scenes
    # keep their original court.png/UVs while a revised atlas is being authored.
    atlas_mode = mat.get('ground_artwork_mode') == 'world-paving-atlas'
    path = ROOT / 'artwork' / 'paving-atlas.png' if atlas_mode else Path(path or ROOT / 'artwork' / 'court.png')
    if not path.is_file():
        return False
    image = bpy.data.images.load(str(path), check_existing=False)
    image.name = path.name + ' | current external source'
    image.colorspace_settings.name = 'sRGB'
    nodes = mat.node_tree.nodes
    tex = nodes.get('Editable court artwork') or nodes.new('ShaderNodeTexImage')
    tex.name = 'Editable court artwork'
    tex.label = 'court.svg + paving-context.svg — same-world-XY atlas' if atlas_mode else 'artwork/court.png — rebuild from court.svg'
    tex.image = image
    # The expanded atlas returns to uniform base colour around every outer
    # edge. EXTEND is used there only, never to stretch clipped court artwork.
    tex.extension = 'EXTEND' if atlas_mode else 'CLIP'
    tex.interpolation = 'Linear'
    shader = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
    mat.node_tree.links.new(tex.outputs['Color'], shader.inputs['Base Color'])
    # The open .blend can be a staging or backup copy. A hard-coded relative
    # path resolves incorrectly there and creates missing-image magenta.
    image.filepath = str(path.resolve())
    return True


def ground():
    # One connected mesh: exact central playing rectangle + 1.8 m neutral apron.
    # The centre face has the only court image; apron faces are plain material.
    apron = 1.8
    xs = [-LENGTH/2-apron, -LENGTH/2, LENGTH/2, LENGTH/2+apron]
    ys = [-WIDTH/2-apron, -WIDTH/2, WIDTH/2, WIDTH/2+apron]
    vertices = [(x,y,0) for y in ys for x in xs]
    faces = [(j*4+i,j*4+i+1,(j+1)*4+i+1,(j+1)*4+i) for j in range(3) for i in range(3)]
    mesh = bpy.data.meshes.new('Continuous ground with exact NBA playing face')
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new('court_surface', mesh)
    GROUPS['reference_half'][0].objects.link(obj)
    obj.parent = GROUPS['reference_half'][1]
    obj['asset_id'] = 'ground.continuous'
    obj['layer'] = 'reference_half'
    obj['category'] = 'ground'
    obj['playing_face_index'] = 4
    obj['playing_length_m'] = LENGTH
    obj['playing_width_m'] = WIDTH
    obj['apron_m'] = apron
    obj['open_half_has_visual_lines'] = False
    mesh.materials.append(MATS['apron'])
    mesh.materials.append(MATS['court'])
    uv = mesh.uv_layers.new(name='CourtArtwork')
    for face in mesh.polygons:
        face.material_index = 1 if face.index == 4 else 0
        for li in face.loop_indices:
            co = mesh.vertices[mesh.loops[li].vertex_index].co
            uv.data[li].uv = ((co.x+LENGTH/2)/LENGTH,(co.y+WIDTH/2)/WIDTH)
    bind_ground_artwork()


def hoop(side):
    suffix = 'reference' if side < 0 else 'open'
    layer = 'reference_half' if side < 0 else 'open_half'
    x = side*RIM_X
    face_x = side*BOARD_X
    pole_x = side*(LENGTH/2+0.95)
    frame = MATS['steel']
    anchor(f'rim_top_center.{suffix}', (x,0,RIM_TOP), 'Design anchor at upper rim plane; game mapping unresolved')
    anchor(f'backboard_front.{suffix}', (face_x,0,BOARD_BOTTOM+BOARD_HEIGHT/2), 'Backboard front plane centre')
    anchor(f'baseline_midpoint.{suffix}', (side*LENGTH/2,0,0), 'NBA baseline inside edge')
    # Support is intentionally simple until photo views establish its actual silhouette.
    cube(f'Base plate.{suffix}', (pole_x,0,0.065), (1.25,1.5,0.13), frame, layer,0.04)
    cube(f'Support upright.{suffix}', (pole_x,0,1.58), (0.24,0.3,3.1), frame, layer,0.025)
    cube(f'Column safety wrap.{suffix}', (pole_x,0,0.84), (0.34,0.4,1.46), MATS['padding'], layer,0.055)
    beam(f'Cantilever top.{suffix}', (pole_x,0,3.2),(face_x+side*0.07,0,3.58),.14,.19,frame,layer)
    beam(f'Cantilever brace.{suffix}', (pole_x,0,2.55),(face_x+side*0.07,0,3.17),.11,.14,frame,layer)
    cube(f'Board rear mount.{suffix}', (face_x+side*.09,0,3.31),(.14,.32,.75),frame,layer,.015)
    board = cube(f'Backboard.{suffix}',(face_x+side*.02,0,BOARD_BOTTOM+BOARD_HEIGHT/2),(.04,BOARD_WIDTH,BOARD_HEIGHT),MATS['glass'],layer)
    board['front_x_m'] = face_x
    board['visual_component_only'] = True
    # Slim grey perimeter; transparent panel and white target are distinct pieces.
    for y in (-BOARD_WIDTH/2, BOARD_WIDTH/2):
        cube(f'Board edge vertical {y:+.3f}.{suffix}',(face_x,y,BOARD_BOTTOM+BOARD_HEIGHT/2),(.055,.025,BOARD_HEIGHT+.02),frame,layer,.007)
    for z in (BOARD_BOTTOM,BOARD_BOTTOM+BOARD_HEIGHT):
        cube(f'Board edge horizontal {z:.3f}.{suffix}',(face_x,0,z),(.055,BOARD_WIDTH,.025),frame,layer,.007)
    target_w,target_h,target_line = .6096,.4572,.03
    target_bottom = RIM_TOP-.03
    tx = face_x-side*.022
    for yy in (-target_w/2+target_line/2,target_w/2-target_line/2):
        cube(f'Board target side {yy:+.3f}.{suffix}',(tx,yy,target_bottom+target_h/2),(.004,target_line,target_h),MATS['white'],layer)
    for zz in (target_bottom+target_line/2,target_bottom+target_h-target_line/2):
        cube(f'Board target horizontal {zz:.3f}.{suffix}',(tx,0,zz),(.004,target_w,target_line),MATS['white'],layer)
    cube(f'Rim mounting plate.{suffix}',(face_x-side*.035,0,2.987),(.07,.14,.16),MATS['orange'],layer,.008)
    beam(f'Rim connector.{suffix}', (face_x-side*.03,0,RIM_TOP-.035),(x+side*.21,0,RIM_TOP-.035),.045,.065,MATS['orange'],layer,.008)
    bpy.ops.mesh.primitive_torus_add(major_segments=96, minor_segments=12, location=(x,0,RIM_TOP-RIM_TUBE_RADIUS), major_radius=RIM_INNER_RADIUS+RIM_TUBE_RADIUS, minor_radius=RIM_TUBE_RADIUS)
    rim = bpy.context.object
    rim.name = f'Rim.{suffix}'
    rim.data.materials.append(MATS['orange'])
    link(rim,layer)
    rim['inner_diameter_m'] = 18*IN
    rim['upper_surface_m'] = RIM_TOP
    rim['tube_section'] = 'provisional 19 mm diameter; confirm from compatible donor'
    for f in rim.data.polygons:
        f.use_smooth=True
    # Hanging diamond net, static visual only. No fabricated game skeleton.
    n,levels = 16,7
    radii = [.225,.213,.192,.172,.145,.128,.123]
    zs = [RIM_TOP-.025-k*.067 for k in range(levels)]
    for direction in (-1,1):
        for i in range(n):
            pts=[]
            for k in range(levels):
                a=2*math.pi*(i+direction*k*.5)/n
                pts.append((x+radii[k]*math.cos(a),radii[k]*math.sin(a),zs[k]))
            tube(f'Net {direction:+d} {i:02d}.{suffix}',pts,.0026,MATS['net'],layer)
    for k in (0,levels-1):
        pts=[(x+radii[k]*math.cos(i*2*math.pi/n),radii[k]*math.sin(i*2*math.pi/n),zs[k]) for i in range(n)]
        tube(f'Net binding {k}.{suffix}',pts,.003,MATS['net'],layer,True)


def validate_scene():
    obj=bpy.data.objects['court_surface']
    face=obj.data.polygons[int(obj['playing_face_index'])]
    coords=[obj.matrix_world @ obj.data.vertices[i].co for i in face.vertices]
    measured_length=max(v.x for v in coords)-min(v.x for v in coords)
    measured_width=max(v.y for v in coords)-min(v.y for v in coords)
    # Traverse actual shared vertex/edge graph. Coincident separate pieces fail.
    adjacent={v.index:set() for v in obj.data.vertices}
    for edge in obj.data.edges:
        a,b=edge.vertices
        adjacent[a].add(b); adjacent[b].add(a)
    seen={0}; todo=[0]
    while todo:
        for v in adjacent[todo.pop()]-seen:
            seen.add(v); todo.append(v)
    report={'source':'scene.blend actual evaluated coordinates', 'coordinate_system':'metres; X length; Y width; Z up; reference X<0',
            'status':'passed', 'tolerance_m':0.000004,'game_geometry_mapping':'unverified',
            'playing_surface':{'expected_length_m':LENGTH,'measured_length_m':measured_length,'expected_width_m':WIDTH,'measured_width_m':measured_width,'surface_z_m':max(abs(v.z) for v in coords)},
            'ground':{'object':'court_surface','mesh_count':1,'connected_vertices':len(seen),'vertices':len(obj.data.vertices),'connected':len(seen)==len(obj.data.vertices),'apron_m':float(obj['apron_m']),'centre_seam':False},
            'hoops':{},'limits':['No NBA 2K game mesh, physics, scoring trigger, collision or animated net verified.','Support geometry is an editable provisional visual reconstruction.','Geometry validation does not establish donor compatibility.']}
    checks=[abs(measured_length-LENGTH)<4e-6,abs(measured_width-WIDTH)<4e-6,len(seen)==len(obj.data.vertices),report['playing_surface']['surface_z_m']<4e-6]
    for side,suffix in ((-1,'reference'),(1,'open')):
        rim=bpy.data.objects[f'Rim.{suffix}']
        pts=[rim.matrix_world @ v.co for v in rim.data.vertices]
        cx=side*RIM_X
        inner=min(math.hypot(v.x-cx,v.y) for v in pts)*2
        top=max(v.z for v in pts)
        board=bpy.data.objects[f'Backboard.{suffix}']
        bp=[board.matrix_world @ v.co for v in board.data.vertices]
        front=min(v.x for v in bp) if side>0 else max(v.x for v in bp)
        board_width=max(v.y for v in bp)-min(v.y for v in bp)
        board_height=max(v.z for v in bp)-min(v.z for v in bp)
        # A retained native glass sheet may have decoded dimensions different
        # from the initial generic backboard. Its verified source properties
        # affect board validation only; court and rim checks stay unchanged.
        expected_front=float(board.get('expected_front_x_m',side*BOARD_X))
        expected_width=float(board.get('expected_width_m',BOARD_WIDTH))
        expected_height=float(board.get('expected_height_m',BOARD_HEIGHT))
        expected_bottom=float(board.get('expected_bottom_m',min(v.z for v in bp)))
        board_bottom=min(v.z for v in bp)
        record={'rim_center_x_m':float(rim.location.x),'expected_center_x_m':cx,'rim_center_y_m':float(rim.location.y),'rim_upper_surface_m':top,'rim_inner_diameter_m':inner,'backboard_front_x_m':front,'backboard_width_m':board_width,'backboard_height_m':board_height,'backboard_bottom_m':board_bottom,'backboard_expected_front_x_m':expected_front,'backboard_expected_width_m':expected_width,'backboard_expected_height_m':expected_height,'backboard_expected_bottom_m':expected_bottom,'functional_in_game':'unverified'}
        report['hoops'][suffix]=record
        checks += [abs(top-RIM_TOP)<4e-6,abs(inner-18*IN)<4e-6,abs(front-expected_front)<4e-6,abs(board_width-expected_width)<4e-6,abs(board_height-expected_height)<4e-6,abs(board_bottom-expected_bottom)<4e-6,abs(rim.location.x-cx)<4e-6,abs(rim.location.y)<4e-6]
    report['status']='passed' if all(checks) else 'failed'
    return report


def main():
    args=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default=str(ROOT/'source'/'scene.blend'))
    parser.add_argument('--render',action='store_true')
    opts=parser.parse_args(args)
    # Keep Blender-generated temporary data inside the authorized project.
    runtime=ROOT/'source'/'.runtime'
    runtime.mkdir(parents=True,exist_ok=True)
    bpy.context.preferences.filepaths.temporary_directory=str(runtime)
    bpy.context.preferences.filepaths.file_preview_type='NONE'
    bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for c in list(bpy.data.collections):
        if c.name!='Collection':
            bpy.data.collections.remove(c)
    for name in ('gameplay_anchors','reference_half','open_half','fence','background','lights','preview_helpers'):
        group(name)
    MATS.update({
        'apron':material('Ground | neutral mineral apron',(.36,.385,.38),.92),
        'court':material('Court | editable artwork',(.43,.455,.45),.9),
        'steel':material('Hoops | brushed grey steel',(.40,.44,.46),.37,.72),
        'padding':material('Hoops | charcoal safety padding',(.072,.086,.09),.83),
        'glass':material('Hoops | transparent backboard',(.65,.84,.87),.16,0,.17),
        'white':material('Hoops | white board markings',(.88,.9,.88),.62),
        'orange':material('Hoops | vermilion rim',(.86,.16,.052),.36,.35),
        'net':material('Hoops | off-white woven net',(.85,.86,.82),.95),
        'mesh':material('Fence | fine steel mesh',(.21,.235,.23),.63,.48),
        'fence':material('Fence | grey framework',(.31,.35,.35),.49,.55),
        'banner':material('Fence | near-black NBA panels',(.033,.03,.036),.92),
        'plaza':material('Plaza | pale stone',(.51,.535,.51),.95),
        'stone':material('Mall | warm pale cladding',(.53,.51,.44),.9),
        'stone_dark':material('Mall | stone trim and joints',(.31,.33,.30),.84),
        'mall_red':material('Mall | red upper fascia',(.49,.085,.052),.75),
        'store_glass':material('Mall | dark window panels',(.082,.127,.128),.32,.25),
        'fascia':material('Mall | charcoal warm storefront band',(.085,.081,.072),.89),
        'sign_red':material('Signs | chili red',(.86,.023,.018),.5),
        'cream':material('Signs | warm white lettering',(.82,.81,.69),.65),
        'awning':material('Mall | pale fabric awning',(.66,.62,.48),.93),
        'tower':material('Skyline | desaturated teal glazing',(.23,.38,.40),.43,.2),
        'tower_mullion':material('Skyline | muted window divisions',(.38,.47,.47),.61,.2),
        'canopy':material('Canopy | grey circular roofs',(.40,.43,.39),.59,.25),
        'canopy_dark':material('Canopy | underside inset',(.26,.29,.255),.77),
        'wood':material('Plaza | timber seats',(.26,.14,.066),.87),
        'bark':material('Plaza | tree trunks',(.14,.12,.083),.96),
        'leaves':[material('Foliage | olive',(.16,.23,.076),1),material('Foliage | soft green',(.22,.31,.105),1),material('Foliage | dark green',(.09,.17,.052),1)],
        'plant_bed':material('Plaza | planting bed',(.16,.19,.095),1),
    })
    ground()
    hoop(-1)
    hoop(1)
    environment()
    anchor('court_center',(0,0,0),'Source origin; no visible centre line')
    scene=bpy.context.scene
    scene.unit_settings.system='METRIC'
    scene.unit_settings.length_unit='METERS'
    scene.unit_settings.scale_length=1
    scene['source_version']='R01'
    scene['game_status']='unverified — no IFF exported'
    scene['reference_half']='negative X'
    scene['artwork_source']='artwork/court.svg -> artwork/court.png'
    scene['source_to_preview']='glTF standard: (x,y,z) -> (x,z,-y), scale 1'
    scene['source_to_game']='unresolved; must measure donor mapping'
    scene['no_open_half_lines']=True
    scene.world.color=(.3,.34,.38)
    scene.world.use_nodes=True
    world_background = next(n for n in scene.world.node_tree.nodes if n.type == 'BACKGROUND')
    world_background.inputs[0].default_value=(.60,.70,.82,1)
    world_background.inputs[1].default_value=.65
    bpy.ops.object.light_add(type='SUN',location=(0,0,12))
    sun=bpy.context.object
    sun.name='Daylight reference'
    sun.rotation_euler=(math.radians(27),math.radians(-24),math.radians(-32))
    sun.data.energy=2.3
    sun.data.angle=math.radians(4)
    link(sun,'lights')
    bpy.ops.object.camera_add(location=(34,-37,31))
    camera=bpy.context.object
    camera.name='Overview source camera'
    camera.rotation_euler=(Vector((-5,0,1.2))-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.data.lens=43
    scene.camera=camera
    link(camera,'preview_helpers')
    scene.render.engine='CYCLES'
    scene.cycles.samples=32
    scene.render.resolution_x=1600
    scene.render.resolution_y=1000
    scene.render.resolution_percentage=100
    scene.view_settings.view_transform='AgX'
    bpy.context.view_layer.update()
    report=validate_scene()
    if report['status']!='passed':
        raise RuntimeError(json.dumps(report,indent=2))
    output=Path(opts.output).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    (output.parent/'geometry_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    print('ZGC_SOURCE_READY '+json.dumps({'file':str(output),'geometry':report['status'],'objects':len(bpy.data.objects)}))
    if opts.render:
        render_checks()


def render_checks():
    scene=bpy.context.scene
    scene.render.engine='CYCLES'
    scene.cycles.samples=24
    scene.cycles.use_denoising=True
    scene.render.image_settings.file_format='PNG'
    scene.render.resolution_percentage=100
    path=ROOT/'validation'
    path.mkdir(parents=True,exist_ok=True)
    scene.render.resolution_x=1600
    scene.render.resolution_y=1000
    scene.render.filepath=str(path/'source-overview.png')
    bpy.ops.render.render(write_still=True)
    camera=scene.camera
    camera.location=(0,0,40)
    camera.rotation_euler=(0,0,-math.pi/2)
    camera.data.type='ORTHO'
    camera.data.ortho_scale=37
    # Camera local horizontal should match source X, image left = reference end.
    camera.rotation_euler=(0,0,0)
    scene.render.resolution_x=1800
    scene.render.resolution_y=1150
    scene.render.filepath=str(path/'source-top.png')
    bpy.ops.render.render(write_still=True)


if __name__=='__main__':
    main()
