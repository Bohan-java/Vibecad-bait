"""Replace one generated building, retaining the scene and native render path.

References 02–05 support a low grey mass and pale rectangular subdivisions.
They do not establish doors, handles, windows, a use, or measured dimensions.
The 6 mm recess is a restrained design approximation, not a recovered detail.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np

from revision3_landscape import M, Mesh
from revision3_mesh import decode_tangent_frames
from revision3_textures import _color_grade, decode_tld_mips, encode_texture


MODEL = M('service_building')
PREFIX = 'building_r6_'
BODY_MIN = np.array([-480., 0., -3520.])
BODY_MAX = np.array([720., 300., -2900.])
FULL_MIN = [-490., 0., -3530.]
FULL_MAX = [730., 308., -2890.]
RECESS_CM = .6
LINE_WIDTH_CM = 1.8
NORMAL_HEIGHT = .08
COLORS = {'wall': (118, 119, 117), 'joint': (143, 144, 140),
          'roof': (106, 108, 106)}
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / 'build/revision6/building'


def _quad(mesh, role, points):
    """Physical 2 m texture repeat on every face, including narrow returns."""
    p = np.asarray(points, dtype=float)
    n = np.cross(p[1]-p[0], p[2]-p[0])
    uv = np.delete(p, int(np.argmax(np.abs(n))), axis=1) / 200.
    mesh.quad(PREFIX+role, p, uv)


def building_geometry():
    """Continuous closed body with tiled, recessed front; no overlay sheets."""
    mesh = Mesh()
    x0, y0, back = BODY_MIN
    x1, y1, front = BODY_MAX
    # The entire front is built below. There is no full coplanar wall behind it.
    _quad(mesh, 'wall', [[x0,y0,back],[x0,y0,front],[x0,y1,front],[x0,y1,back]])
    _quad(mesh, 'wall', [[x1,y0,front],[x1,y0,back],[x1,y1,back],[x1,y1,front]])
    _quad(mesh, 'wall', [[x1,y0,back],[x0,y0,back],[x0,y1,back],[x1,y1,back]])
    _quad(mesh, 'wall', [[x0,y0,front],[x0,y0,back],[x1,y0,back],[x1,y0,front]])
    _quad(mesh, 'wall', [[x0,y1,back],[x0,y1,front],[x1,y1,front],[x1,y1,back]])

    half = LINE_WIDTH_CM/2
    vertical = (-450., -120., 250., 690.)
    horizontal = (38., 260.)
    xs = sorted([x0,x1]+[x+d for x in vertical for d in (-half,half)])
    ys = sorted([y0,y1]+[y+d for y in horizontal for d in (-half,half)])
    recessed = np.zeros((len(ys)-1,len(xs)-1),dtype=bool)
    for j,(a,b) in enumerate(zip(ys[:-1],ys[1:])):
        y = (a+b)/2
        for i,(l,r) in enumerate(zip(xs[:-1],xs[1:])):
            x = (l+r)/2
            recessed[j,i] = (
                (min(abs(x-v) for v in vertical)<half and horizontal[0]-half<y<horizontal[-1]+half)
                or (min(abs(y-h) for h in horizontal)<half and vertical[0]-half<x<vertical[-1]+half))
            z = front-RECESS_CM*recessed[j,i]
            _quad(mesh, 'joint' if recessed[j,i] else 'wall',
                  [[l,a,z],[r,a,z],[r,b,z],[l,b,z]])
    # Each depth discontinuity has exactly one outward-facing solid return.
    for j,(a,b) in enumerate(zip(ys[:-1],ys[1:])):
        for i,x in enumerate(xs[1:-1],start=1):
            left,right = recessed[j,i-1],recessed[j,i]
            if left == right:
                continue
            p = [[x,a,front],[x,a,front-RECESS_CM],
                 [x,b,front-RECESS_CM],[x,b,front]]  # +X, towards right recess
            _quad(mesh,'joint',p if right else p[::-1])
    for j,y in enumerate(ys[1:-1],start=1):
        for i,(l,r) in enumerate(zip(xs[:-1],xs[1:])):
            below,above = recessed[j-1,i],recessed[j,i]
            if below == above:
                continue
            p = [[l,y,front],[r,y,front],[r,y,front-RECESS_CM],[l,y,front-RECESS_CM]]
            _quad(mesh,'joint',p if above else p[::-1])  # +Y towards upper recess
    # Existing 8 cm top lip and 10 cm overhang; only its material changes.
    mesh.box(PREFIX+'roof',[120.,304.,-3210.],[1220.,8.,640.],bevel=1.,tile=200.)
    return mesh


def _read_binary(name, archive, extra):
    return extra[name] if name in extra else archive.read(name)


def _materials(level, archive, extra):
    source = level['Material'][M('concrete')]
    source_key = source['Resource']['AlbedoMap']['Pixelmap']
    normal_key = source['Resource']['NormalAndRoughMap']['Pixelmap']
    source_spec, normal_spec = level['Texture'][source_key],level['Texture'][normal_key]
    source_raw = _read_binary(source_spec['Binary'],archive,extra)
    normal_raw = _read_binary(normal_spec['Binary'],archive,extra)
    decoded = decode_tld_mips(source_raw,source_spec)[0].convert('RGB')
    normals = np.asarray(decode_tld_mips(normal_raw,normal_spec)[0])
    if source_spec['Format'] != 'BC1_UNORM' or normal_spec['Format'] != 'BC3_UNORM':
        raise ValueError('Expected verified R3 concrete BC1 color and BC3 normal/roughness')
    if source.get('Parameter',{}).get('AlbedoModulate') != [1.,1.,1.,1.]:
        raise ValueError('Unexpected source concrete color modulation')
    if normals.shape[-1] != 4 or normals[:,:,3].min() < 220:
        raise ValueError('Expected rough concrete normal map with roughness in alpha')
    archive_names = set(archive.namelist())
    audits=[]
    with tempfile.TemporaryDirectory(prefix='building_r6_') as directory:
        for role,rgb in COLORS.items():
            label=PREFIX+role;key=M(label)
            # Keep source resolution; suppress broad stains and yellow chroma.
            color=_color_grade(decoded,rgb,contrast=.22,retain_color=.015,remove_stains=True)
            _,spec,raw,audit=encode_texture(label,color,output_dir=directory)
            binary=spec['Binary']
            if binary in extra and extra[binary]!=raw:
                raise ValueError(f'Building resource collision: {binary}')
            if binary in archive_names and archive.read(binary)!=raw:
                raise ValueError(f'Existing archive resource collision: {binary}')
            extra[binary]=raw;level['Texture'][key]=spec
            material=copy.deepcopy(source)
            material['Resource']['AlbedoMap']['Pixelmap']=key
            material['Parameter']['NormalHeight']=NORMAL_HEIGHT
            level['Material'][key]=material
            audit={k:v for k,v in audit.items() if k not in ('source_png','decoded_png')}
            audit['key']=key;audits.append(audit)
    return {'textures':audits,'source_albedo_texture':source_key,
            'source_albedo_sha256':hashlib.sha256(source_raw).hexdigest(),
            'source_resolution_preserved':[source_spec['Width'],source_spec['Height']],
            'normal_texture_reused_unchanged':normal_key,
            'normal_sha256':hashlib.sha256(normal_raw).hexdigest(),
            'roughness_alpha_decoded_range':[int(normals[:,:,3].min())/255,int(normals[:,:,3].max())/255],
            'normal_height':NORMAL_HEIGHT,'encoded_color_targets':COLORS,
            'original_concrete_material_and_textures_preserved':True,
            'existing_effect_and_pass_bindings_copied_unchanged':source['Effect']}


def _verify_native(model, extra):
    """Read the actual emitted buffers, including recess after quantization."""
    vb=model['VertexStream'];spec=model['VertexFormat']['POSITION0']
    p=np.frombuffer(extra[vb[0]['Binary']],dtype='<u2').reshape(-1,4)[:,:3]
    p=p.astype(float)/65535*np.asarray(spec['Scale'][:3])+spec['Offset'][:3]
    indices=np.frombuffer(extra[model['IndexBuffer']['Binary']],dtype='<u2')
    if model['IndexBuffer']['Format']!='R16_UINT' or indices.max()>=len(p):
        raise ValueError('Invalid native building indices')
    faces=p[indices].reshape(-1,3,3)
    cross=np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0])
    lengths=np.linalg.norm(cross,axis=1)
    if lengths.min()<=1e-7:
        raise ValueError('Native quantization collapsed a building face')
    attrib=np.frombuffer(extra[vb[2]['Binary']],dtype=np.uint8).reshape(-1,20)
    normal,_,_=decode_tangent_frames(attrib[:,:4].copy().view('<u4').ravel())
    agreement=(normal[indices].reshape(-1,3,3)*cross[:,None,:]/lengths[:,None,None]).sum(2)
    if agreement.min()<.999:
        raise ValueError('Native building normal faces against its geometry')
    # Take only actual front-facing flat faces, excluding side returns and roof.
    front_levels={}
    for prim in model['Prim']:
        if prim['Material'] not in (M(PREFIX+'wall'),M(PREFIX+'joint')):
            continue
        pts=p[indices[prim['Start']:prim['Start']+prim['Count']]].reshape(-1,3,3)
        n=np.cross(pts[:,1]-pts[:,0],pts[:,2]-pts[:,0])
        front=(n[:,2]>0)&(pts[:,:,2].min(1)>-2902)
        front_levels[prim['Material']]=float(np.median(pts[front,:,2]))
    depth=front_levels[M(PREFIX+'wall')]-front_levels[M(PREFIX+'joint')]
    if not .55<depth<.65:
        raise ValueError(f'Native shallow recess lost: {depth}')
    return {'decoded_recess_cm':depth,'minimum_native_triangle_double_area_cm2':float(lengths.min()),
            'minimum_native_normal_dot':float(agreement.min()),
            'index_format':model['IndexBuffer']['Format'],'native_triangle_count':len(faces),
            'zero_area_triangles':0,'coplanar_front_overlay_sheets':0}


def apply_building(level, archive, extra, output_dir=DEFAULT_OUTPUT):
    """Atomically replace only service_building, appending private resources.

    archive is an open ZipFile (or read/namelist compatible reader). Existing
    binary bytes are read only. output_dir optionally receives a small audit;
    texture encoder inspection files remain temporary. Pass None for no files.
    """
    old=level['Model'].get(MODEL)
    if not old or old.get('Min')!=FULL_MIN or old.get('Max')!=FULL_MAX:
        raise ValueError('Expected original generated service_building envelope')
    if M('concrete') not in level['Material']:
        raise ValueError('Expected existing verified concrete material')
    names=[M(PREFIX+role) for role in COLORS]
    if any(key in level[section] for section in ('Material','Texture') for key in names):
        raise ValueError('R6 building material or texture already exists')
    objects=[key for key,value in level['Object'].items() if value.get('Target')==MODEL]
    if not objects:
        raise ValueError('Expected existing building Object; never invent its placement')
    staged=copy.deepcopy(level);pending=dict(extra)
    material_report=_materials(staged,archive,pending)
    mesh=building_geometry()
    del staged['Model'][MODEL]
    model_report=mesh.export(staged,pending,'service_building')
    native_report=_verify_native(staged['Model'][MODEL],pending)
    # Resource hashes may coincide with an existing archive entry. Never allow
    # new geometry to shadow original bytes with different contents.
    archive_names=set(archive.namelist())
    for name in set(pending)-set(extra):
        if name in archive_names and archive.read(name)!=pending[name]:
            raise ValueError(f'Existing archive binary would be replaced: {name}')
    for section,values in level.items():
        if isinstance(values,dict):
            expected_add=set(names) if section in ('Texture','Material') else set()
            if set(staged[section])-set(values)!=expected_add:
                raise AssertionError(f'Unexpected new entries in {section}')
            for key,value in values.items():
                if section=='Model' and key==MODEL:
                    continue
                if staged[section].get(key)!=value:
                    raise AssertionError(f'Protected scene value changed: {section}/{key}')
        elif staged[section]!=values:
            raise AssertionError(f'Protected scene section changed: {section}')
    if any(pending.get(name)!=raw for name,raw in extra.items()):
        raise AssertionError('Existing binary resource changed')
    if staged['Model'][MODEL]['Min']!=FULL_MIN or staged['Model'][MODEL]['Max']!=FULL_MAX:
        raise AssertionError('Building outer envelope changed')
    report={'changed_model_keys':[MODEL],'changed_object_keys':[],
            'preserved_building_objects':objects,'model':model_report,'native_validation':native_report,
            'added_materials':names,'added_textures':material_report['textures'],
            'added_binary_resources':sorted(set(pending)-set(extra)),
            'materials':material_report,
            'body_bounds_min_cm':BODY_MIN.tolist(),'body_bounds_max_cm':BODY_MAX.tolist(),
            'roof_bounds_min_cm':FULL_MIN[:1]+[300.,FULL_MIN[2]],
            'roof_bounds_max_cm':FULL_MAX,'recess_design_cm':RECESS_CM,
            'line_width_design_cm':LINE_WIDTH_CM,'added_doors_handles_windows_or_signs':0,
            'all_other_original_scene_values_preserved':True,
            'all_existing_binary_resources_preserved':True,'new_collision_resources':0,
            'prior_model_spec_sha256':hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest(),
            'reference_images':[f'arena_reference_{i:02d}.png' for i in (2,3,4,5)],
            'dimensions_color_and_recess_are_design_approximations':True,
            'game_render_verified':False}
    if output_dir is not None:
        directory=Path(output_dir);directory.mkdir(parents=True,exist_ok=True)
        (directory/'building_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    level.clear();level.update(staged);extra.clear();extra.update(pending)
    return report
