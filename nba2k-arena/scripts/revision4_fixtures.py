"""Photo-supported coastal street fixtures, outside the protected court.

References 01 (right edge), 02 (among the palms) and 03 (right grass side)
show the same family of silver double-headed curved street lamps. Dimensions,
hardware and placement below are explicit design choices, not measurements
recovered from the five 640 x 480 photographs. No light/gameplay fields are added.
"""
from __future__ import annotations

import copy
import math

import numpy as np

from revision3_landscape import IDENTITY, M, Mesh, add_object
from revision3_mesh import make_unbaked_material


DEFAULT_PLACEMENTS = (
    (2900., 100., -1600., math.pi / 2),
    (2900., 100., 750., math.pi / 2),
    (2900., 100., 3050., math.pi / 2),
)
MODEL_NAME = 'coastal_double_lamp'


def _lathe(mesh, material, profile, *, x=0., z=0., sides=48, bottom=True, top=True):
    """Revolve increasing (height, radius) pairs with outward-facing normals."""
    profile = np.asarray(profile, dtype=float)
    angles = np.linspace(0, 2 * np.pi, sides + 1)
    radial = np.column_stack((np.sin(angles), np.zeros(sides + 1), np.cos(angles)))
    for (y0, r0), (y1, r1) in zip(profile[:-1], profile[1:]):
        ring0 = radial * r0 + [x, y0, z]
        ring1 = radial * r1 + [x, y1, z]
        ns = radial.copy()
        ns[:, 1] = -(r1 - r0) / (y1 - y0)
        ns /= np.linalg.norm(ns, axis=1)[:, None]
        for i in range(sides):
            mesh.quad(material, [ring0[i], ring0[i+1], ring1[i+1], ring1[i]],
                      [[i/sides, y0/100], [(i+1)/sides, y0/100],
                       [(i+1)/sides, y1/100], [i/sides, y1/100]],
                      [ns[i], ns[i+1], ns[i+1], ns[i]])
    for enabled, (y, radius), reverse in ((bottom, profile[0], True), (top, profile[-1], False)):
        if not enabled:
            continue
        ring = radial * radius + [x, y, z]
        for i in range(sides):
            points = np.array([[x, y, z], ring[i], ring[i+1]])
            if reverse:
                points = points[::-1]
            mesh.tri(material, points, points[:, [0, 2]] / 100)


def _curved_arm(mesh, sign, height, reach):
    """A single smooth shepherd's hook with no internal segment caps."""
    controls = np.array([[0, height-30, 0], [0, height+50, 0],
                         [sign*reach, height+90, 0], [sign*reach, height+20, 0]])
    t = np.linspace(0, 1, 33)[:, None]
    centers = (1-t)**3 * controls[0] + 3*(1-t)**2*t * controls[1] + 3*(1-t)*t*t * controls[2] + t**3 * controls[3]
    tangent = 3*(1-t)**2*(controls[1]-controls[0]) + 6*(1-t)*t*(controls[2]-controls[1]) + 3*t*t*(controls[3]-controls[2])
    tangent /= np.linalg.norm(tangent, axis=1)[:, None]
    across = np.cross(tangent, [0., 0., 1.])
    angles = np.linspace(0, 2*np.pi, 17)
    normals = np.cos(angles)[None, :, None] * np.array([0., 0., 1.]) + np.sin(angles)[None, :, None] * across[:, None, :]
    rings = centers[:, None, :] + 3.2 * normals
    distance = np.r_[0., np.cumsum(np.linalg.norm(np.diff(centers, axis=0), axis=1))]
    for j in range(len(centers)-1):
        for i in range(16):
            mesh.quad('aluminum', [rings[j,i], rings[j,i+1], rings[j+1,i+1], rings[j+1,i]],
                      [[i/16,distance[j]/100],[(i+1)/16,distance[j]/100],
                       [(i+1)/16,distance[j+1]/100],[i/16,distance[j+1]/100]],
                      [normals[j,i], normals[j,i+1], normals[j+1,i+1], normals[j+1,i]])
    # Ends are physically covered by the shaft and lamp socket, respectively.


def fixture_geometry(*, pole_height_cm=520., arm_reach_cm=78., shade_radius_cm=33.) -> Mesh:
    """A double lamp at origin; local ground is y=0 and heads extend along x.

    The defaults produce a roughly 5.8 m overall fixture. Shaft height does not
    include the curved arm rise. The factory rejects implausible/unsafe parameter
    combinations rather than emitting overlapping or non-finite geometry.
    """
    values = np.array([pole_height_cm, arm_reach_cm, shade_radius_cm], dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError('Fixture dimensions must be finite')
    if not 300 <= pole_height_cm <= 1000:
        raise ValueError('Pole design height must be between 300 and 1000 cm')
    if not 18 <= shade_radius_cm <= 60 or not 2*shade_radius_cm < arm_reach_cm <= 180:
        raise ValueError('Lamp heads require separated shades and a reach of at most 180 cm')
    mesh = Mesh()
    mesh.box('aluminum', [0, 2, 0], [31, 4, 31], bevel=2.5)
    _lathe(mesh, 'aluminum', [(4, 12), (9, 12), (13, 9.4),
                            (50, 8.3), (pole_height_cm, 4.9)])
    # Ordinary fastening/access hardware is design detail; the low-res photos
    # do not resolve exact bolt count, manufacturers or writing.
    for x in (-10.5, 10.5):
        for z in (-10.5, 10.5):
            _lathe(mesh, 'dark_metal', [(4, 2.1), (7.2, 2.1)], x=x, z=z, sides=6)
    mesh.box('dark_metal', [0, 66, 8.3], [5.5, 21, .8], bevel=.3)
    _lathe(mesh, 'aluminum', [(pole_height_cm-35, 6.3), (pole_height_cm-27, 6.3)])
    shade = np.array([[-36,19], [-34,22], [-27,23], [-25,28],
                      [-23,29.5], [-21,24], [-15,24], [-12,33],
                      [-9,32.5], [-7,21], [-3,13], [0,7.5]], dtype=float)
    shade[:, 1] *= shade_radius_cm/33
    for sign in (-1, 1):
        _curved_arm(mesh, sign, pole_height_cm, arm_reach_cm)
        profile = shade.copy(); profile[:, 0] += pole_height_cm+20
        _lathe(mesh, 'aluminum', profile, x=sign*arm_reach_cm, bottom=False)
        # The underside is shaded in daylight, not a fabricated emissive bulb.
        _lathe(mesh, 'dark_metal', [(pole_height_cm-17.3, 17.7*shade_radius_cm/33),
                                   (pole_height_cm-15.8, 18.9*shade_radius_cm/33)],
               x=sign*arm_reach_cm)
    return mesh


def _world_bounds(lo, hi, matrix):
    corners = np.array([[x, y, z, 1.] for x in (lo[0], hi[0])
                        for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    transform = np.asarray(matrix, dtype=float)
    if transform.shape != (16,) or not np.all(np.isfinite(transform)):
        raise ValueError('Expected a finite column-major Object Matrix')
    result = corners @ transform.reshape(4, 4)
    return result[:, :3].min(0), result[:, :3].max(0)


def apply_fixtures(level, extra, textures=None, *, placements=DEFAULT_PLACEMENTS,
                   pole_height_cm=520., arm_reach_cm=78., shade_radius_cm=33.,
                   court_clearance_cm=60.):
    """Append one native mesh and design-positioned instances, atomically.

    Call after apply_landscape to reuse its two materials, or provide the same
    textures mapping to create them. Every complete fixture bound must be outside
    the original floor bounds plus clearance. Original scene values, collision,
    original Objects, materials and lighting are never edited.
    """
    if not math.isfinite(court_clearance_cm) or court_clearance_cm < 0:
        raise ValueError('Court clearance must be finite and non-negative')
    placements = np.asarray(placements, dtype=float)
    if placements.ndim != 2 or placements.shape[1] != 4 or len(placements) == 0 or not np.all(np.isfinite(placements)):
        raise ValueError('Placements must be finite nonempty (x, y, z, yaw) rows')
    if M(MODEL_NAME) in level['Model']:
        raise ValueError('Fixture model already exists')
    names = [M(f'{MODEL_NAME}_{i}') for i in range(len(placements))]
    if any(name in level['Object'] for name in names):
        raise ValueError('Fixture object already exists')
    mesh = fixture_geometry(pole_height_cm=pole_height_cm, arm_reach_cm=arm_reach_cm,
                            shade_radius_cm=shade_radius_cm)
    points = np.concatenate(list(mesh.parts.values())).reshape(-1, 3)
    lo, hi = points.min(0), points.max(0)
    floor_object = level['Object']['__floor00__']
    floor = level['Model'][floor_object['Target']]
    floor_lo, floor_hi = _world_bounds(floor['Min'], floor['Max'], floor_object.get('Matrix', IDENTITY))
    staged = copy.deepcopy(level)
    staged_extra = dict(extra)
    objects, bounds = [], []
    for i, (x, y, z, yaw) in enumerate(placements):
        item = add_object(staged, M(MODEL_NAME), f'{MODEL_NAME}_{i}', (x, y, z), yaw)
        world_lo, world_hi = _world_bounds(lo, hi, staged['Object'][item['object']]['Matrix'])
        gap = np.maximum(np.maximum(floor_lo[[0, 2]]-world_hi[[0, 2]],
                                    world_lo[[0, 2]]-floor_hi[[0, 2]]), 0)
        if not np.any(gap > court_clearance_cm):
            raise ValueError('Entire fixture must clear the protected court bounds')
        objects.append(item)
        bounds.append({'min': world_lo.tolist(), 'max': world_hi.tolist(),
                       'court_aabb_clearance_cm': float(np.linalg.norm(gap))})
    for key in ('aluminum', 'dark_metal'):
        if M(key) not in staged['Material']:
            if textures is None:
                raise ValueError('Call after apply_landscape or provide its texture mapping')
            make_unbaked_material(staged, M(key), textures[key], textures[key+'_normal'])
            staged['Material'][M(key)]['Parameter']['NormalHeight'] = 0.
    model = mesh.export(staged, staged_extra, MODEL_NAME)
    level.clear(); level.update(staged)
    extra.clear(); extra.update(staged_extra)
    return {'model': model, 'placements': objects, 'world_bounds': bounds,
            'reference_images': ['arena_reference_01.png', 'arena_reference_02.png', 'arena_reference_03.png'],
            'evidence': 'Paired downward lamp shades on curved silver arms beside the grass/palms',
            'dimensions_are_design_parameters_not_photo_measurements': True,
            'pole_height_cm': float(pole_height_cm), 'arm_reach_cm': float(arm_reach_cm),
            'shade_radius_cm': float(shade_radius_cm), 'court_clearance_cm': float(court_clearance_cm),
            'new_light_objects': 0, 'new_collision_resources': 0,
            'original_scene_values_preserved': True, 'game_render_verified': False}
