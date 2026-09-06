"""Replace only the two generated coastal prop models with finer geometry.

The five images depict one court. Reference 04 clearly supports an open green
bin, a folded pale liner and an adjacent grey cylinder/dome; refs 04/05 support
open aluminium bleachers. Exact hardware, dimensions and the liner folds are
design choices. No people, lettering, new lights or collision are fabricated.
"""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile

import numpy as np
from PIL import Image

from revision3_landscape import M, Mesh, bleachers
from revision3_mesh import make_unbaked_material
from revision3_textures import encode_texture


CHANGED_MODELS = (M('bins'), M('bleachers'))
MOVED_OBJECT = M('bins_2')
PROP_MATERIALS = {
    'prop_bin_green': ((32, 67, 48), .92),
    'prop_bin_inside': ((19, 30, 23), .98),
    'prop_liner': ((177, 183, 172), .86),
}


def _revolve(mesh, material, profile, *, center=(0., 0.), sides=64,
             inward=False, bottom=False, top=False):
    """Lathe increasing height/radius pairs; walls can face the cavity."""
    profile = np.asarray(profile, dtype=float)
    angles = np.linspace(0, 2*np.pi, sides+1)
    radial = np.column_stack((np.sin(angles), np.zeros(sides+1), np.cos(angles)))
    x, z = center
    for (y0, r0), (y1, r1) in zip(profile[:-1], profile[1:]):
        rings = [radial*r+[x,y,z] for y,r in ((y0,r0),(y1,r1))]
        normals = radial.copy(); normals[:,1] = -(r1-r0)/(y1-y0)
        normals /= np.linalg.norm(normals, axis=1)[:,None]
        for i in range(sides):
            p = np.array([rings[0][i],rings[0][i+1],rings[1][i+1],rings[1][i]])
            uv = np.array([[i/sides,y0/100],[(i+1)/sides,y0/100],[(i+1)/sides,y1/100],[i/sides,y1/100]])
            ns = np.array([normals[i],normals[i+1],normals[i+1],normals[i]])
            if inward:
                p, uv, ns = p[::-1], uv[::-1], -ns[::-1]
            mesh.quad(material,p,uv,ns)
    for enabled, (y,r), upper in ((bottom,profile[0],False),(top,profile[-1],True)):
        if enabled:
            ring = radial*r+[x,y,z]
            for i in range(sides):
                points = np.array([[x,y,z],ring[i],ring[i+1]])
                if not upper:
                    points = points[::-1]
                mesh.tri(material,points,points[:,[0,2]]/100)


def _rolled_rim(mesh):
    """Continuous round lip joins the outer body and the inset inner wall."""
    a = np.linspace(0,2*np.pi,65)
    b = np.linspace(0,2*np.pi,13)
    rings, normals = [], []
    for angle in b:
        radius = 31.55 + 1.05*np.cos(angle)
        rings.append(np.column_stack((np.sin(a)*radius,np.full(65,96+1.05*np.sin(angle)),np.cos(a)*radius)))
        normals.append(np.column_stack((np.sin(a)*np.cos(angle),np.full(65,np.sin(angle)),np.cos(a)*np.cos(angle))))
    for j in range(12):
        for i in range(64):
            mesh.quad('prop_bin_green',[rings[j][i],rings[j][i+1],rings[j+1][i+1],rings[j+1][i]],
                      [[i/64,j/12],[(i+1)/64,j/12],[(i+1)/64,(j+1)/12],[i/64,(j+1)/12]],
                      [normals[j][i],normals[j][i+1],normals[j+1][i+1],normals[j+1][i]])


def _liner(mesh):
    """Independent thin cloth-like bag surface, folded over the open rim.

    The verified opaque material is retained. Geometric folds and a pale matte
    color represent the visible cuff; this is not a claim of physically correct
    plastic transmission. Both sides are explicit geometry, without new flags.
    """
    count = 256
    angles = np.linspace(0,2*np.pi,count+1)
    # Inner wall -> top fold -> outer hanging cuff. The opening stays empty.
    # Rise entirely inside the lip, clear its y=97.05 top, then fold outward.
    # A direct diagonal over the lip intersects the torus in little green spots.
    profile = [(80.,29.3),(90.,29.9),(95.,30.1),(98.5,30.05),
               (99.4,32.4),(97.3,33.8),(94.,34.2),
               (88.,34.2),(82.,34.0),(76.,33.9),(71.,33.6)]
    rings=[]
    for j,(height,radius) in enumerate(profile):
        t=j/(len(profile)-1)
        cuff = max(0.,(t-.5)*2)
        # Multiple wavelengths, slightly spiralling folds and an uneven free
        # hem avoid a perfect horizontal plastic collar.
        radial_fold = (.25+1.2*cuff)*(np.sin(17*angles-4*t)+.38*np.sin(31*angles+2*t))
        r = radius+radial_fold
        y = height + .45*np.sin(13*angles+1.3*t) + cuff*(6*np.sin(angles+.5)+2.6*np.sin(3*angles))
        rings.append(np.column_stack((np.sin(angles)*r,y,np.cos(angles)*r)))
    # Differentiate this same periodic surface rather than shade each triangle
    # as a separate flat facet. The free hem uses a one-sided derivative; the
    # angular seam uses exact wrapped neighbours and identical endpoint normals.
    grid=np.asarray(rings)[:,:count]
    angular=np.roll(grid,-1,axis=1)-np.roll(grid,1,axis=1)
    longitudinal=np.gradient(grid,axis=0,edge_order=2)
    normals=np.cross(angular,longitudinal)
    lengths=np.linalg.norm(normals,axis=2,keepdims=True)
    if np.any(lengths<1e-9):
        raise ValueError('Degenerate liner surface derivative')
    normals/=lengths
    rings=np.concatenate((grid,grid[:,:1]),axis=1)
    normals=np.concatenate((normals,normals[:,:1]),axis=1)
    for j in range(len(rings)-1):
        for i in range(count):
            mesh.quad('prop_liner',[rings[j][i],rings[j][i+1],rings[j+1][i+1],rings[j+1][i]],
                      [[i/count,j/10],[(i+1)/count,j/10],[(i+1)/count,(j+1)/10],[i/count,(j+1)/10]],
                      [normals[j][i],normals[j][i+1],normals[j+1][i+1],normals[j+1][i]],
                      double=True)


def bins_geometry() -> Mesh:
    """Preserve the original generated pair's centers (0,0) and (76,0), cm."""
    mesh=Mesh()
    # The shell has a real cavity: no disc across its mouth and a dark inset
    # inner wall/bottom. Its original roughly 96 cm height is retained.
    _revolve(mesh,'prop_bin_green',[(0,27.8),(2.5,29),(7,29.4),(33,30.2),
                                  (35,31.1),(38,31.2),(40,30.4),(87,31.7),(96,31.55)],bottom=True)
    _revolve(mesh,'prop_bin_inside',[(5,26.5),(40,28.5),(91,30.4),(96,30.5)],inward=True)
    _revolve(mesh,'prop_bin_inside',[(4.8,26.5),(5,26.5)],top=True)
    _rolled_rim(mesh)
    _liner(mesh)
    # The neighbouring object's function is not reliably legible in the photo.
    # Model its grey cylinder and smoothly rounded concrete crown, not a shiny
    # metal lid, and do not invent an opening, label, logo or ashtray.
    _revolve(mesh,'concrete',[(0,27),(3,29),(8,29.5),(82,31),
                             (86,32),(89,34.5),(92,35.3),(95,35),(98,33),(99,31.5)],
             center=(76,0),bottom=True,top=True)
    rings=[]; ns=[]
    angles=np.linspace(0,2*np.pi,65)
    for elevation in np.linspace(0,np.pi/2,25):
        radius=24*np.cos(elevation);y=99+28*np.sin(elevation)
        rings.append(np.column_stack((76+radius*np.sin(angles),np.full(65,y),radius*np.cos(angles))))
        n=np.column_stack((np.sin(angles)*np.cos(elevation)/24,
                           np.full(65,np.sin(elevation)/28),np.cos(angles)*np.cos(elevation)/24))
        n/=np.linalg.norm(n,axis=1)[:,None];ns.append(n)
    for j in range(24):
        for i in range(64):
            mesh.quad('concrete',[rings[j][i],rings[j][i+1],rings[j+1][i+1],rings[j+1][i]],
                      [[i/64,j/24],[(i+1)/64,j/24],[(i+1)/64,(j+1)/24],[i/64,(j+1)/24]],
                      [ns[j][i],ns[j][i+1],ns[j+1][i+1],ns[j+1][i]])
    return mesh


def bleachers_geometry() -> Mesh:
    """Keep the existing five rows, add feet and open triangulated bracing."""
    mesh=bleachers()
    for z in (-490.,-245.,0.,245.,490.):
        mesh.box('dark_metal',[-142,3,z],[355,6,12],bevel=1)
        for x in (-308.,24.):
            mesh.box('dark_metal',[x,1,z],[27,2,25],bevel=1)
    for row in range(5):
        x=-row*71;y=45+row*38
        mesh.tube('dark_metal',[x,y-6,-490],[x,y-6,490],2.7,sides=12)
        for z in (-522.8,522.8):
            mesh.box('aluminum',[x,y,z],[40.2,5.3,1.6],bevel=.5)
    # The diagonal members are real open rods, not a solid replacement wall.
    for z0,z1 in zip((-490.,-245.,0.,245.),(-245.,0.,245.,490.)):
        mesh.tube('dark_metal',[-284,9,z0],[-284,190,z1],2.25,sides=12)
        mesh.tube('dark_metal',[-284,190,z0],[-284,9,z1],2.25,sides=12)
    for z in (-490.,490.):
        mesh.tube('dark_metal',[24,7,z],[-284,188,z],2.5,sides=12)
        mesh.tube('dark_metal',[-308,7,z],[0,40,z],2.5,sides=12)
    # References 04/05 show silver/galvanized supports throughout. Merge the
    # exact existing geometry and attributes, recoloring only this bleacher.
    for channel in (mesh.parts,mesh.uv,mesh.normals):
        channel[M('aluminum')].extend(channel.pop(M('dark_metal')))
    return mesh


def _materials(level, extra):
    added=[];textures=[]
    # The established encoder's temporary verification images do not become
    # unrelated repository outputs. The final resources live only in extra.
    with tempfile.TemporaryDirectory(prefix='venice_props_') as directory:
        for label,(rgb,roughness) in PROP_MATERIALS.items():
            refs=[]
            images=((label,Image.new('RGB',(4,4),rgb),False),
                    (label+'_normal',Image.new('RGBA',(4,4),(128,128,0,round(roughness*255))),True))
            for texture_label,image,linear in images:
                key,spec,raw,audit=encode_texture(texture_label,image,linear=linear,output_dir=directory)
                if key in level['Texture']:
                    raise ValueError(f'Prop texture already exists: {key}')
                binary=spec['Binary']
                if binary in extra and extra[binary] != raw:
                    raise ValueError(f'Prop binary collision: {binary}')
                extra[binary]=raw;level['Texture'][key]=spec;refs.append(key)
                textures.append({k:v for k,v in audit.items() if k not in ('source_png','decoded_png')})
            make_unbaked_material(level,M(label),*refs)
            added.append(M(label))
    return added,textures


def apply_props(level, extra):
    """Replace bins/bleachers Models and move one generated bin onto paving.

    New content-addressed binaries are appended. Existing resources are never
    removed or overwritten. The only Object edit is generated bins_2 Matrix[12]
    from 1110 to 940 cm, explicitly authorized to clear the 30 cm grass step.
    """
    for name in CHANGED_MODELS:
        if name not in level['Model']:
            raise ValueError(f'Expected generated R3 model: {name}')
    if any(M(name) in level['Material'] for name in PROP_MATERIALS):
        raise ValueError('Refined prop materials already exist')
    if any(M(name) not in level['Material'] for name in ('concrete','aluminum','dark_metal')):
        raise ValueError('Expected R3 landscape materials')
    moving=level['Object'].get(MOVED_OBJECT)
    if (not moving or moving.get('Type')!='OBJECT' or moving.get('Target')!=M('bins')
        or len(moving.get('Matrix',[]))!=16 or moving['Matrix'][12:15]!=[1110.,0.,2650.]):
        raise ValueError('Expected generated bins_2 position (1110, 0, 2650)')
    staged=copy.deepcopy(level);pending=dict(extra)
    old_matrix=copy.deepcopy(moving['Matrix'])
    staged['Object'][MOVED_OBJECT]['Matrix'][12]=940.
    old_models={key:copy.deepcopy(level['Model'][key]) for key in CHANGED_MODELS}
    materials,textures=_materials(staged,pending)
    reports=[]
    for short,mesh in (('bins',bins_geometry()),('bleachers',bleachers_geometry())):
        del staged['Model'][M(short)]
        reports.append(mesh.export(staged,pending,short))
    model=staged['Model'][M('bins')]
    lo,hi=model['Min'],model['Max']
    corners=np.array([[x,y,z,1.] for x in (lo[0],hi[0]) for y in (lo[1],hi[1]) for z in (lo[2],hi[2])])
    grounded=corners@np.asarray(staged['Object'][MOVED_OBJECT]['Matrix']).reshape(4,4)
    grounded_lo,grounded_hi=grounded[:,:3].min(0),grounded[:,:3].max(0)
    if grounded_hi[0]>=1100 or abs(grounded_lo[1])>1e-6:
        raise ValueError('Relocated bin must stand entirely on the known paving side')
    # Assert the precise mutation boundary before committing either mapping.
    for section,values in level.items():
        if isinstance(values,dict):
            for key,value in values.items():
                if section=='Model' and key in CHANGED_MODELS:
                    continue
                if section=='Object' and key==MOVED_OBJECT:
                    expected=copy.deepcopy(value);expected['Matrix'][12]=940.
                    if staged[section][key]!=expected:
                        raise AssertionError('Unexpected generated bin Object edit')
                    continue
                if staged[section][key] != value:
                    raise AssertionError(f'Unexpected original scene change: {section}/{key}')
        elif staged[section] != values:
            raise AssertionError(f'Unexpected scene section change: {section}')
    for binary,data in extra.items():
        if pending.get(binary) != data:
            raise AssertionError(f'Existing resource changed: {binary}')
    objects=[name for name,obj in level['Object'].items() if obj.get('Target') in CHANGED_MODELS]
    added_binary=sorted(set(pending)-set(extra))
    level.clear();level.update(staged);extra.clear();extra.update(pending)
    return {'changed_model_keys':list(CHANGED_MODELS),'models':reports,
            'added_materials':materials,'added_textures':textures,'added_binary_resources':added_binary,
            'preserved_object_names':[name for name in objects if name!=MOVED_OBJECT],
            'changed_object_keys':[MOVED_OBJECT],
            'object_changes':{MOVED_OBJECT:{'before_matrix':old_matrix,
                'after_matrix':copy.deepcopy(staged['Object'][MOVED_OBJECT]['Matrix']),
                'only_changed_matrix_index':12,'before_x_cm':1110.,'after_x_cm':940.,
                'new_world_bounds_min':grounded_lo.tolist(),'new_world_bounds_max':grounded_hi.tolist(),
                'grounding_basis':'Known R3 first grass terrace starts at x=1100 and is 30 cm high; relocated complete pair is below x=1052, on the y=-0.4 paved plane with its original y=0 base retained'}},
            'all_original_donor_object_values_preserved':True,
            'all_other_original_scene_values_preserved':True,'existing_binary_resources_preserved':True,
            'prior_model_spec_sha256':{key:hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest() for key,value in old_models.items()},
            'reference_images':['arena_reference_04.png','arena_reference_05.png'],
            'bin_shell_wall_thickness_cm':'approximately 1 to 3.5; separate interior wall and bottom',
            'liner_material':'new pale rough dielectric on explicit folded front/back geometry; opaque shader path',
            'liner_transmission_simulated':False,'concrete_dome_uses_metal_material':False,
            'bleacher_rows':5,'bleacher_metal_material':M('aluminum'),
            'new_light_objects':0,'new_collision_resources':0,
            'dimensions_and_folds_are_design_choices':True,'game_render_verified':False}
