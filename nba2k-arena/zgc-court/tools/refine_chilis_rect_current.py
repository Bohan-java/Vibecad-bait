"""R12: rectangular Chili's plan, retaining the R11 photo-derived detail work.

Call build() after opening the current source. This module never publishes the
editable source or an IFF. It replaces only Chili's-owned meshes. R11's detail
builders run in planar facade frames, without changing their source files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import refine_chilis_current as detail

STAGE = ROOT / '.build-staging' / 'r12-chilis'
PARAMS = {
    'front_x': -21.05299186706543,
    'rear_x': -31.6,
    'left_y': -16.2,
    'right_y': 14.6,
    'corner_radius': 1.20,
    'entry_center_y': -4.2,
    'entry_width': 10.6,
    'terrace_center_x': -28.1,
    'terrace_width': 6.8,
}
OLD_SUBGRADE = {
    'R02 architecture Chilis lower storey conceptual glazing',
    'R02 architecture Chilis lower storey sill',
}
PHOTO_PATHS = [
    'references/chilis-detail/00_总览/新增细节总览_01.jpg',
    'references/chilis-detail/00_总览/新增细节总览_02.jpg',
    'references/chilis/00_总览/Chilis建筑与LINK_8图总览.jpg',
    'references/chilis/00_总览/周边补充_5张总览.jpg',
    'references/r12-skyline/原始截图/08_露台回看远楼_10-20.421.jpg',
    'references/r12-skyline/原始截图/09_球场与Chilis通道定位_04-46.478.jpg',
    'references/r12-left/selected/08_泥靴外观补充_03-32.525.jpg',
]


def front(y, z=0.0, offset=0.0):
    """Planar long elevation. R11 entry/alсove details use this local frame."""
    return (Vector((PARAMS['front_x'] + offset, y, z)),
            Vector((1, 0, 0)), Vector((0, 1, 0)))


def facade_frame(face, u=0.0, z=0.0, offset=0.0):
    if face == 'entry':
        return front(PARAMS['entry_center_y'] + u, z, offset)
    if face == 'alcove':
        p, n, t = front(8.72, z, offset - .89)
        return p + t * (u + .70), n, t
    if face == 'terrace':
        return (Vector((PARAMS['terrace_center_x'] + u,
                        PARAMS['left_y'] - .01 - offset, z)),
                Vector((0, -1, 0)), Vector((1, 0, 0)))
    raise ValueError(face)


def path_frames():
    """Counterclockwise exposed perimeter: left return, front, right return."""
    p = PARAMS
    fx, bx, yl, yr, r = (p[k] for k in
                         ('front_x', 'rear_x', 'left_y', 'right_y', 'corner_radius'))
    frames = []
    def append(x, y, nx, ny):
        frames.append((Vector((x, y, 0)), Vector((nx, ny, 0)),
                       Vector((-ny, nx, 0))))
    # Side lengths and the long middle are strictly straight. The roundover is
    # a 1.2 m transition, never an ellipse spanning the front of the building.
    for j in range(49):
        append(bx + (fx-r-bx)*j/48, yl, 0, -1)
    for j in range(1, 25):
        a = -math.pi/2 + math.pi/2*j/24
        append(fx-r+r*math.cos(a), yl+r+r*math.sin(a), math.cos(a), math.sin(a))
    for j in range(1, 161):
        append(fx, yl+r+(yr-yl-2*r)*j/160, 1, 0)
    for j in range(1, 25):
        a = math.pi/2*j/24
        append(fx-r+r*math.cos(a), yr-r+r*math.sin(a), math.cos(a), math.sin(a))
    for j in range(1, 49):
        append(fx-r+(bx-fx+r)*j/48, yr, 0, 1)
    return frames


def is_detail_bay(point, upper=False):
    """Do not put opaque shell sheets across the previously modelled openings."""
    x, y = point.x, point.y
    if abs(x-PARAMS['front_x']) < .001:
        if abs(y-PARAMS['entry_center_y']) <= PARAMS['entry_width']/2+.30:
            return True
        if 7.18 <= y <= 10.25 and not upper:
            return True
    if abs(y-PARAMS['left_y']) < .001:
        if abs(x-PARAMS['terrace_center_x']) <= PARAMS['terrace_width']/2+.03:
            return True
    return False


def vertical_strip(builder, frames, z0, z1, offset=0):
    v = [p+n*offset+Vector((0, 0, z)) for p, n, _ in frames for z in (z0, z1)]
    builder.add(v, [(2*j, 2*j+2, 2*j+3, 2*j+1) for j in range(len(frames)-1)])


def rectangular_envelope():
    frames = path_frames()
    shell = detail.batch('rectangular restaurant roof and rear envelope', 'roof stone')
    # The back closure is also planar. No full-width ellipse remains at any
    # elevation, including the lower storey only seen from the sunken plaza.
    roof = [p+Vector((0, 0, 4.365)) for p, _, _ in frames]
    shell.add(roof, [tuple(range(len(roof)))])
    a, b = frames[-1][0], frames[0][0]
    shell.add([a+Vector((0, 0, -.14)), b+Vector((0, 0, -.14)),
               b+Vector((0, 0, 4.365)), a+Vector((0, 0, 4.365))], [(0, 1, 2, 3)])
    lower = detail.batch('rectangular lower storey recessed glazing', 'store glazing')
    vertical_strip(lower, frames, -3.62, -.14, -.035)
    rail = detail.batch('straight eaves with short radius corner returns', 'brushed silver')
    for z, h, d in ((-.10,.18,.13),(.09,.065,.13),(3.145,.068,.13),
                     (4.40,.08,.20),(4.51,.064,.16),(4.615,.07,.21)):
        detail.folded_rail(rail, [(p+n*.07,n,t) for p,n,t in frames], z, d, h)

    glass = detail.batch('straight flank and small corner glazing', 'store glazing')
    upper = detail.batch('straight upper flank and small corner glazing', 'upper glazing')
    fins = detail.batch('straight flank individual silver fins', 'brushed silver', True)
    mullions = detail.batch('straight flank slender glazing mullions', 'black frame')
    for left, right in zip(frames, frames[1:]):
        midpoint = (left[0]+right[0])*.5
        if not is_detail_bay(midpoint):
            vertical_strip(glass, [left, right], .1, 3.145, .009)
        if not is_detail_bay(midpoint, upper=True):
            vertical_strip(upper, [left, right], 3.20, 4.38, .009)
    # Resample the actual perimeter by distance for even fin/mullion spacing.
    distance = 0.0
    next_fin, next_mullion = .07, .05
    for aa, bb in zip(frames, frames[1:]):
        length = (bb[0]-aa[0]).length
        for what, interval in (('fin', .14), ('mullion', .95)):
            cursor = next_fin if what == 'fin' else next_mullion
            while cursor <= distance+length:
                f = max(0, min(1, (cursor-distance)/max(length, 1e-9)))
                q = aa[0].lerp(bb[0], f);n = aa[1].lerp(bb[1], f).normalized()
                if not is_detail_bay(q,upper=what=='fin'):
                    angle = math.atan2(n.y,n.x)
                    if what == 'fin':
                        fins.box(q+n*.055+Vector((0,0,3.78)),(.07,.026,1.14),angle)
                    else:
                        mullions.box(q+n*.060+Vector((0,0,1.62)),(.095,.04,3.04),angle)
                cursor += interval
            if what == 'fin':next_fin = cursor
            else:next_mullion = cursor
        distance += length

    # Retain the shallow terrace room behind the R11 clear viewing apertures.
    w = PARAMS['terrace_width']
    room = detail.batch('terrace inner warm plaster return wall', 'interior warm wall')
    detail.ribbon(room,'terrace',-w/2+.1,w/2-.1,.07,3.10,-2.49,1)
    floor = detail.batch('terrace continuous interior red floor','interior red floor')
    floor.add([facade_frame('terrace',u,.035,d)[0] for u,d in
               ((-w/2,0),(w/2,0),(w/2,-2.52),(-w/2,-2.52))],[(0,1,2,3)])
    skirting = detail.batch('terrace inner low wood wainscot','interior wood')
    detail.ribbon(skirting,'terrace',-w/2+.1,w/2-.1,.06,.68,-2.47,1)


def build():
    """Incremental, deterministic and safe to call after another R12 module."""
    original_front = detail.old.front
    original_frame = detail.facade_frame
    original_envelope = detail.retained_curve
    original_replace = set(detail.REPLACE)
    original_params = dict(detail.PARAMS)
    original_revision = detail.REVISION
    try:
        detail.old.front = front
        detail.facade_frame = facade_frame
        detail.retained_curve = rectangular_envelope
        detail.REPLACE.update(OLD_SUBGRADE)
        detail.REPLACE.update(o.name for o in bpy.data.objects if o.name.startswith('R12 Chilis '))
        detail.PARAMS.update({k: PARAMS[k] for k in
                            ('entry_center_y','entry_width','terrace_center_x','terrace_width')})
        detail.PARAMS.update(terrace_side=-1,terrace_angle_deg=0.0,terrace_side_confirmed=True)
        detail.REVISION = 'R12 rectangular Chili restaurant with short rounded corners'
        report = detail.build(include_furniture=True)
        renamed={}
        for obj in bpy.data.objects:
            if obj.name.startswith(('R11 Chilis building ','R11 Chilis terrace ')):
                previous=obj.name;obj.name=previous.replace('R11 Chilis ','R12 Chilis ',1)
                obj['r12_chilis_rectangular']=True
                obj['dimension_status']='Straight main elevations; only 1.2 m front corner roundovers. Metric size estimated from photos.'
                renamed[previous]=obj.name
        def replace_names(value):
            if isinstance(value,dict):return {k:replace_names(v) for k,v in value.items()}
            if isinstance(value,list):return [replace_names(v) for v in value]
            if isinstance(value,str):return renamed.get(value,value)
            return value
        removed_old=list(report['removed_old_building_objects'])
        removed_furniture=list(report['furniture']['deleted_old_objects'])
        report=replace_names(report)
        report['removed_old_building_objects']=removed_old
        report['furniture']['deleted_old_objects']=removed_furniture
        legacy_guard='R02 architecture Chilis terrace side-walk glass guard'
        assert legacy_guard not in bpy.data.objects
        report['furniture']['historical_removed_source_objects']=[legacy_guard]
        bpy.context.scene['chilis_detail_revision'] = detail.REVISION
        report['revision'] = 'R12'
        report['parameters'] = dict(PARAMS)
        report['footprint'] = {
            'type':'rectangle with two small front corner roundovers',
            'long_straight_front_length_m': PARAMS['right_y']-PARAMS['left_y']-2*PARAMS['corner_radius'],
            'straight_front_x_max_deviation_m':0.0,
            'body_width_m':PARAMS['right_y']-PARAMS['left_y'],
            'body_depth_m':PARAMS['front_x']-PARAMS['rear_x'],
            'rounded_corner_radius_m':PARAMS['corner_radius'],
            'full_facade_ellipse_removed':True,
            'former_lower_storey_ellipse_removed':all(n not in bpy.data.objects for n in OLD_SUBGRADE),
            'sampled_xy':[list(v[0])[:2] for v in path_frames()],
        }
        report['references_actually_viewed'] = PHOTO_PATHS
        report['facade_evidence']['footprint'] = (
            'Explicit user correction: generally rectangular. New02/old02 show planar purple signboard; '
            'old03/04 show local rounded turn only; new07/08/09 show long straight court-side walk. '
            'r12 skyline08/09 anchor terrace and court; r12 left08 identifies The boots as a separate shop.')
        report['layout_limits'] = [
            'User confirmed generally rectangular form and fountain terrace around the left corner when facing the entry.',
            'Exact metric size and 1.20 m corner radius are photographic estimates, not a measured survey.',
            'Entry and terrace viewing apertures retain R11 perimeter-seam geometry; optical transparent sheets are not introduced.',
            'R11 door/sign/awning/pilaster/fountain/furniture detail geometry is regenerated in corrected planar frames.',
            'Courts, baskets, fences, LINK, other site modules, lighting and exposure are protected before/after.',
        ]
        return report
    finally:
        detail.old.front = original_front
        detail.facade_frame = original_frame
        detail.retained_curve = original_envelope
        detail.REPLACE.clear();detail.REPLACE.update(original_replace)
        detail.PARAMS.clear();detail.PARAMS.update(original_params)
        detail.REVISION = original_revision


def renders(folder):
    scene = bpy.context.scene;camera = scene.camera
    scene.render.engine='CYCLES';scene.cycles.samples=16;scene.cycles.use_denoising=True
    scene.render.resolution_x=1400;scene.render.resolution_y=1050;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    views = (
        ('footprint',(-26.0,-.8,40),(-26.0,-.8,0),'ORTHO',46),
        ('court-front',(-3,-15,7),(-21.5,-1.8,2.4),'PERSP',38),
        ('left-corner',(-13,-27,7),(-24,-12,2.5),'PERSP',43),
        ('entry',(-16.6,-4.2,2.85),(-21.05,-4.2,2.35),'PERSP',13),
        ('terrace',(-27.2,-25,4.2),(-28.1,-16.2,2.15),'PERSP',40),
    )
    for key,pos,target,typ,lens in views:
        camera.location=pos;camera.data.type=typ
        if typ=='ORTHO':camera.data.ortho_scale=lens
        else:camera.data.lens=lens
        camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
        scene.render.filepath=str(folder/f'r12-chilis-{key}.png')
        bpy.ops.render.render(write_still=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default=str(STAGE/'scene-rect.blend'))
    parser.add_argument('--render',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    output=Path(args.output).resolve()
    if not output.is_relative_to(ROOT) or output == ROOT/'source/scene.blend':
        raise RuntimeError('Use a project staging file; never overwrite canonical source from this module.')
    STAGE.mkdir(parents=True,exist_ok=True);output.parent.mkdir(parents=True,exist_ok=True)
    prefs=bpy.context.preferences.filepaths
    prefs.temporary_directory=str(STAGE);prefs.save_version=0;prefs.file_preview_type='NONE'
    prefs.use_auto_save_temporary_files=False
    report=build()
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    report.update(output=str(output),source_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    (ROOT/'validation/r12-chilis-rect.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('R12_CHILIS_READY '+json.dumps({'output':str(output),'protected':report['protected_objects'],
          'new_objects':len(report['new_building_objects'])}),flush=True)
    if args.render:renders(ROOT/'validation')


if __name__=='__main__':main()
