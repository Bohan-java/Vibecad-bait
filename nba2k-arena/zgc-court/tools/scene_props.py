"""N34 visible details: lamp-lit tree canopies and courtside clutter.

Tree canopies (R02 broadleaf canopy parts 0013-0016, upward-facing low-poly crown shells
above the fence line): the plaza post heads (y 536) and the festoon bulbs sit inside or under
the crowns, but probes are too coarse to light a crown from below, so they read as
black blobs. Their downward-facing faces get an emissive skin whose map is the
analytic direct light from those lamps (area lights facing down: cos x cos / pi d^2;
bulbs: point lights), in the same units as the Cycles surface bakes, so the court
overlay's per-unit scale and the probe-calibrated group weights apply. Top-down
planar UV over each crown, 8 cm texels. No shadows (a crown is lit from inside).

Courtside clutter (inside the fence, out of play): along the west bench (x -884..-839,
seat ~45 cm, back at x -883) a duffel bag, a backpack, a towel over the seat edge,
water bottles and a spare ball under the bench; against the east fence a backpack
and a small speaker. Plain primitives with flat colours on the sconce material at
zero emission, lit by the probes and the two real-time A lights.
"""
from __future__ import annotations

import copy
import math

import numpy as np
from PIL import Image

import native_textures
from chilis_storefront import Mesh, _box, _frustum, _quad, _sphere

CANOPIES = ['0013', '0014', '0015', '0016']
CANOPY_CM = 8.0
CANOPY_GAIN = 10.0           # physical level on dark green leaves (~0.03 albedo) was invisible
CANOPY_KEEP = 0.04           # skin only faces with at least 4% of the crown's peak light (performance)


def _flat(level, extra, prefix, sconce_material, key, srgb, emission=None, intensity=0.0, rough=None):
    _, albedo, _ = native_textures.encode(Image.new('RGB', (8, 8), tuple(int(c) for c in srgb)), extra)
    _, emis, _ = native_textures.encode(emission if emission is not None else Image.new('RGB', (8, 8), (0, 0, 0)), extra)
    _, metal, _ = native_textures.encode(Image.new('RGB', (8, 8), (0, 0, 0)), extra, linear=True)
    nr = None
    if rough is not None:
        _, nr, _ = native_textures.encode(Image.new('RGBA', (8, 8), (128, 128, 255, int(rough * 255))), extra, linear=True)
    for name in [k for k in extra if k.endswith('.tld')]:
        extra.pop(name)
    for suffix, spec in (('_albedo', albedo), ('', emis), ('_metal', metal)) + ((('_nr', nr),) if nr else ()):
        level['Texture'][prefix + 'tex_' + key + suffix] = spec
    mat = copy.deepcopy(level['Material'][sconce_material])
    mat['Resource'] = {'AlbedoMap': {'Pixelmap': prefix + 'tex_' + key + '_albedo'},
                       'EmissiveAlbedoMap': {'Pixelmap': prefix + 'tex_' + key},
                       'MetalMap': {'Pixelmap': prefix + 'tex_' + key + '_metal'},
                       'NormalAndRoughMap': ({'Pixelmap': prefix + 'tex_' + key + '_nr'} if nr
                                             else copy.deepcopy(mat['Resource']['NormalAndRoughMap']))}
    mat['Parameter'].update(EmissiveIntensity=float(intensity), EmissiveTint=[1.0, 1.0, 1.0], AlwaysEmit=1,
                            AlbedoScaleX=1.0, AlbedoScaleY=1.0, NormalScaleX=1.0, NormalScaleY=1.0)
    level['Material'][prefix + key] = mat
    return prefix + key


def _lamps(weights):
    """[(position cm, linear rgb, kind, watts x group weight)]"""
    import night_lights as nl
    out = []
    for (x0, x1), (z0, z1) in nl.POST_HEADS:
        out.append((np.array([(x0 + x1) / 2, nl.POST_HEAD_Y, (z0 + z1) / 2]), np.array(nl.POST_COLOUR),
                    'down', nl.POST_BAKE_WATTS * weights.get('plaza_posts', 0.0)))
    for b in nl.bulbs():
        out.append((np.asarray(b, float), np.array(nl.BULB_COLOUR), 'point', nl.BULB_BAKE_WATTS * weights.get('festoon', 0.0)))
    return out


def _irradiance(p, n, lamps):
    """Diffuse radiance (albedo 1) at points p with normals n, rgb, in bake units."""
    out = np.zeros((len(p), 3))
    for pos, rgb, kind, watts in lamps:
        d = pos[None, :] - p
        dist2 = np.maximum((d ** 2).sum(1), 0.0) / 1e4 + 0.04            # m^2, soft near field
        l = d / np.sqrt(np.maximum((d ** 2).sum(1), 1e-9))[:, None]
        cos_s = np.clip((n * l).sum(1), 0, 1)
        if kind == 'down':
            cos_l = np.clip(l[:, 1], 0, 1)                                 # light only below the head
            e = watts * cos_l * cos_s / (math.pi * dist2)
        else:
            e = watts * cos_s / (4 * math.pi * dist2)
        out += (e / math.pi)[:, None] * rgb[None, :]
    return out


def _rasterise_top(p, tris, values, x0, z0, w, h, cell):
    """Paint per-vertex values into a top-down grid (rows = z); later triangles overwrite."""
    img = np.zeros((h, w, values.shape[1]), np.float32)
    hit = np.zeros((h, w), bool)
    q = np.stack([(p[:, 0] - x0) / cell, (p[:, 2] - z0) / cell], 1)
    for t in tris:
        a, b, c = q[t]
        lo = np.floor(np.minimum(np.minimum(a, b), c)).astype(int); hi = np.ceil(np.maximum(np.maximum(a, b), c)).astype(int)
        lo = np.clip(lo, 0, [w - 1, h - 1]); hi = np.clip(hi, 0, [w - 1, h - 1])
        xs, ys = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1))
        pts = np.stack([xs.ravel() + 0.5, ys.ravel() + 0.5], 1)
        v0, v1 = b - a, c - a
        den = v0[0] * v1[1] - v1[0] * v0[1]
        if abs(den) < 1e-9:
            continue
        d = pts - a
        s = (d[:, 0] * v1[1] - v1[0] * d[:, 1]) / den
        r = (v0[0] * d[:, 1] - d[:, 0] * v0[1]) / den
        inside = (s >= -0.05) & (r >= -0.05) & (s + r <= 1.05)
        if not inside.any():
            continue
        wgt = np.stack([1 - s - r, s, r], 1)[inside]
        ij = pts[inside].astype(int)
        val = wgt @ values[t]
        cur = img[ij[:, 1], ij[:, 0]]
        img[ij[:, 1], ij[:, 0]] = np.maximum(cur, val)                    # brightest layer wins
        hit[ij[:, 1], ij[:, 0]] = True
    return img, hit


def tree_glow(level, archive, extra, prefix, add_emitter, sconce_material, part_geometry, weights, per_unit):
    from scene_details import _mean_albedo, _srgb_image
    lamps = _lamps(weights)
    report = {}
    for n in CANOPIES:
        source = 'zgc_r03:part-' + n
        part_mat = level['Material'][level['Model'][source]['Prim'][0]['Material']]
        p, nrm, ix = part_geometry(source)
        # the crowns are upward-facing shells seen from below as back faces: the skin is a
        # flipped copy (normals down, winding reversed) just under the shell
        tris = ix.reshape(-1, 3)[:, ::-1].copy()
        nrm = -nrm
        used = np.unique(tris)
        remap = -np.ones(len(p), np.int64); remap[used] = np.arange(len(used))
        p, nrm, tris = p[used], nrm[used], remap[tris]
        light = _irradiance(p, nrm, lamps)
        face = light.max(1)[tris].max(1)
        lit = face > CANOPY_KEEP * np.percentile(face, 99.5)
        tris = tris[lit]
        used = np.unique(tris)
        remap = -np.ones(len(p), np.int64); remap[used] = np.arange(len(used))
        p, nrm, light, tris = p[used], nrm[used], light[used], remap[tris]
        albedo = _mean_albedo(archive, level, part_mat['Resource']['AlbedoMap']['Pixelmap'])
        x0, z0 = p[:, 0].min() - CANOPY_CM, p[:, 2].min() - CANOPY_CM
        w = int(math.ceil((p[:, 0].max() + CANOPY_CM - x0) / CANOPY_CM)); h = int(math.ceil((p[:, 2].max() + CANOPY_CM - z0) / CANOPY_CM))
        img, hit = _rasterise_top(p, tris, light * albedo[None, :], x0, z0, w, h, CANOPY_CM)
        peak = float(np.percentile(img.max(2)[hit], 99.5)) if hit.any() else 0.0
        if peak <= 1e-6:
            continue
        key = 'canopy_' + n
        uv = np.stack([(p[:, 0] - x0) / (w * CANOPY_CM), (p[:, 2] - z0) / (h * CANOPY_CM)], 1)
        mean_srgb = np.clip(albedo ** (1 / 2.2) * 255, 0, 255)
        mat = _flat(level, extra, prefix, sconce_material, key, mean_srgb, _srgb_image(img / peak),
                    CANOPY_GAIN * per_unit * peak)
        moved = p + nrm * 1.0
        add_emitter(level, extra, prefix + key, moved * np.array([-1.0, 1.0, -1.0]), nrm * np.array([-1.0, 1.0, -1.0]),
                    uv, tris.reshape(-1), 0.03 + 0.94 * uv, mat)
        report[n] = {'faces': int(len(tris)), 'vertices': int(len(p)), 'texture': [w, h],
                     'intensity': round(CANOPY_GAIN * per_unit * peak, 1)}
    return report


# ---- courtside clutter ---------------------------------------------------------------

SEAT_Y = 45.5
SEAT_X = (-880.0, -841.0)


def _cylinder_x(mesh, c, r, length, segments=12):
    """Closed cylinder lying along world z (a duffel bag)."""
    cx, cy, cz = c
    for k in range(segments):
        a, b = 2 * math.pi * k / segments, 2 * math.pi * (k + 1) / segments
        p = lambda ang, z: (cx + r * math.cos(ang), cy + r * math.sin(ang), z)
        q = [p(a, cz - length / 2), p(b, cz - length / 2), p(b, cz + length / 2), p(a, cz + length / 2)]
        mid = (a + b) / 2
        mesh.add(*_quad(*q, np.array([math.cos(mid), math.sin(mid), 0.0]), [(0, 0), (1, 0), (1, 1), (0, 1)]))
    for side in (-1, 1):
        z = cz + side * length / 2
        for k in range(segments):
            a, b = 2 * math.pi * k / segments, 2 * math.pi * (k + 1) / segments
            q = [(cx, cy, z), (cx + r * math.cos(a), cy + r * math.sin(a), z), (cx + r * math.cos(b), cy + r * math.sin(b), z),
                 (cx, cy, z)]
            mesh.add(*_quad(*q, np.array([0.0, 0.0, float(side)]), [(0, 0), (1, 0), (1, 1), (0, 1)]))


def _bottle(mesh_body, mesh_cap, x, z, lying=False, h=22.0, r=3.4):
    if lying:
        _cylinder_x(mesh_body, (x, r, z), r, h)
        _cylinder_x(mesh_cap, (x, r, z + h / 2 + 1.5), r * 0.55, 3.0)
        return
    _frustum(mesh_body, x, z, 0.0, h * 0.78, r, r, segments=12)
    _frustum(mesh_body, x, z, h * 0.78, h * 0.92, r, r * 0.45, segments=12)
    _box(mesh_body, (x - r * 0.7, h * 0.78 - 0.1, z - r * 0.7), (x + r * 0.7, h * 0.78, z + r * 0.7))
    _frustum(mesh_cap, x, z, h * 0.92, h, r * 0.5, r * 0.5, segments=10)
    _box(mesh_cap, (x - r * 0.5, h - 0.2, z - r * 0.5), (x + r * 0.5, h, z + r * 0.5))


def _backpack(mesh_body, mesh_strap, base, facing, lean=0.0):
    """Upright backpack on a surface at base (x, y, z); facing +1/-1 along x = the side with the pocket."""
    x, y, z = base
    w, d, h = 30.0, 16.0, 42.0
    _box(mesh_body, (x - d / 2 + lean, y, z - w / 2), (x + d / 2 + lean, y + h, z + w / 2))
    _box(mesh_body, (x - d / 2 + 2 + lean, y + h, z - w / 2 + 3), (x + d / 2 - 2 + lean, y + h + 4, z + w / 2 - 3))   # rounded top
    px = x + facing * (d / 2 + 3) + lean
    _box(mesh_body, (min(px, px - facing * 6), y + 6, z - 10), (max(px, px - facing * 6), y + 22, z + 10))           # front pocket
    sx = x - facing * (d / 2 + 1) + lean
    for dz in (-8, 8):
        _box(mesh_strap, (min(sx, sx - facing * 2), y + 4, z + dz - 2.5), (max(sx, sx - facing * 2), y + h - 4, z + dz + 2.5))


def _towel(mesh, z, width=42.0):
    """Folded over the seat front edge: a strip on the seat and a fall down the front."""
    x_back, x_edge = -858.0, SEAT_X[1] + 0.8
    _box(mesh, (x_back, SEAT_Y, z - width / 2), (x_edge, SEAT_Y + 1.2, z + width / 2))
    _box(mesh, (x_edge - 1.2, SEAT_Y - 26.0, z - width / 2 + 1), (x_edge, SEAT_Y + 1.2, z + width / 2 - 1))


def _speaker(mesh_body, mesh_grille, x, z):
    _box(mesh_body, (x - 7, 0, z - 16), (x + 7, 17, z + 16))
    _box(mesh_body, (x - 2, 17, z - 10), (x + 2, 20, z + 10))                       # handle
    _box(mesh_grille, (x - 7.6, 3, z - 14), (x - 7.0, 14, z + 14))                 # grille faces the court (-x)


def props(level, extra, prefix, add_emitter, sconce_material):
    from night_scene import _planar_uv7
    meshes = {name: Mesh() for name in ('duffel', 'duffel_trim', 'pack_navy', 'pack_red', 'strap', 'towel',
                                        'bottle_blue', 'bottle_orange', 'cap', 'ball', 'speaker', 'grille')}
    m = meshes
    # west bench
    _cylinder_x(m['duffel'], ((SEAT_X[0] + SEAT_X[1]) / 2, SEAT_Y + 15.0, 310.0), 15.0, 58.0)
    _box(m['duffel_trim'], (SEAT_X[0] + 4, SEAT_Y + 28.5, 290.0), (SEAT_X[1] - 4, SEAT_Y + 31.0, 330.0))   # handles
    _backpack(m['pack_navy'], m['strap'], (-864.0, SEAT_Y, -420.0), +1, lean=4.0)
    _towel(m['towel'], 610.0)
    for x, z, kind in ((-822.0, 236.0, 'bottle_blue'), (-819.0, 249.0, 'bottle_blue'), (-824.0, -512.0, 'bottle_orange')):
        _bottle(m[kind], m['cap'], x, z)
    _bottle(m['bottle_blue'], m['cap'], -830.0, -470.0, lying=True)
    _sphere(m['ball'], (-866.0, 12.2, 840.0), 12.2, rings=8, segments=14)
    # east fence
    _backpack(m['pack_red'], m['strap'], (886.0, 0.0, -180.0), -1, lean=-5.0)
    _speaker(m['speaker'], m['grille'], 884.0, 160.0)
    colours = {'duffel': (24, 26, 30), 'duffel_trim': (190, 30, 34), 'pack_navy': (30, 40, 70), 'pack_red': (150, 32, 30),
               'strap': (20, 20, 22), 'towel': (214, 212, 204), 'bottle_blue': (70, 140, 200), 'bottle_orange': (230, 120, 30),
               'cap': (235, 235, 235), 'ball': (190, 86, 32), 'speaker': (28, 28, 30), 'grille': (60, 60, 64)}
    rough = {'bottle_blue': 0.25, 'bottle_orange': 0.25, 'cap': 0.4, 'speaker': 0.5}
    report = {}
    for name, mesh in meshes.items():
        if not mesh.p:
            continue
        p, n, uv, ix = mesh.arrays()
        mat = _flat(level, extra, prefix, sconce_material, 'prop_' + name, colours[name], rough=rough.get(name))
        add_emitter(level, extra, prefix + 'prop-' + name, p * np.array([-1.0, 1.0, -1.0]), n * np.array([-1.0, 1.0, -1.0]),
                    uv, ix, _planar_uv7(p), mat)
        report[name] = int(len(p))
    return report


# ---- far half: decorative hoop on the stripped stanchion plate, cones and cooler off court -----
# (Wrong premise, see N37: the gameplay basket1 is drawn at the far end.) The far end lost its hoop (only part-0647 "Base plate.open" and its anchors remain, centred
# at world (0, 0, -1527)); the gameplay basket1 (board plane at world z -1310) is hidden in
# half-court play, so the far half reads empty. A static hoop stands on the old plate:
# square steel post, gooseneck, painted steel board (170 x 95, bottom at 290.4 like the
# gameplay board), orange rim at 305, and a static chain net (chains hang; no cloth needed).
FAR_BOARD_Z = -1310.0
FAR_PLATE_Z = -1527.5
RIM_Y, RIM_R = 305.0, 22.9


def _tube(mesh, a, b, r, segments=6):
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    length = np.linalg.norm(d)
    if length < 1e-6:
        return
    d /= length
    ref = np.array([0.0, 1.0, 0.0]) if abs(d[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(d, ref); u /= np.linalg.norm(u)
    v = np.cross(d, u)
    for k in range(segments):
        t0, t1 = 2 * math.pi * k / segments, 2 * math.pi * (k + 1) / segments
        o0 = (math.cos(t0) * u + math.sin(t0) * v) * r
        o1 = (math.cos(t1) * u + math.sin(t1) * v) * r
        nm = (math.cos((t0 + t1) / 2) * u + math.sin((t0 + t1) / 2) * v)
        mesh.add(*_quad(a + o0, a + o1, b + o1, b + o0, nm, [(0, 0), (1, 0), (1, 1), (0, 1)]))


def _board_image(w=512, h=288):
    rng = np.random.default_rng(1310)
    base = np.array([214, 214, 208], np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    grime = rng.normal(0, 1, (h // 8 + 1, w // 8 + 1))
    grime = np.asarray(Image.fromarray(((grime - grime.min()) / np.ptp(grime) * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32) / 255
    rgb = base[None, None, :] * (0.86 + 0.1 * grime[..., None]) * (1 - 0.18 * (yy / h)[..., None] ** 2)
    line = np.array([196, 58, 30], np.float32)
    cm = w / 170.0
    t = 5 * cm
    border = (xx < t) | (xx > w - t) | (yy < t) | (yy > h - t)
    sq_w, sq_h = 59 * cm, 45 * cm
    x0, x1 = w / 2 - sq_w / 2, w / 2 + sq_w / 2
    y1 = h - (305.0 - 290.4 - 0.0) * cm            # square bottom at rim height (rows from top)
    y0 = y1 - sq_h
    square = (((np.abs(xx - x0) < t / 2) | (np.abs(xx - x1) < t / 2)) & (yy > y0 - t / 2) & (yy < y1 + t / 2)) | \
             ((np.abs(yy - y0) < t / 2) & (xx > x0 - t / 2) & (xx < x1 + t / 2)) | \
             ((np.abs(yy - y1) < t / 2) & (xx > x0 - t / 2) & (xx < x1 + t / 2))
    chip = rng.random((h, w)) > 0.06
    paint = (border | square) & chip
    rgb[paint] = line * (0.9 + 0.08 * grime[paint][:, None])
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), 'RGB')


def far_court(level, extra, prefix, add_emitter, sconce_material):
    from night_scene import _planar_uv7
    m = {name: Mesh() for name in ('cone', 'cone_band', 'cooler', 'cooler_lid')}
    # drill cones along the far free-throw lane, and a cooler by the east sideline
    # N36: the far half is played on, so the cones are stacked off court next to the cooler
    x, z = 868.0, -1060.0
    for k in range(4):
        y = 2.5 + 5.5 * k
        _frustum(m['cone'], x, z, y, y + 46, 13, 2.2, segments=12)
        _box(m['cone'], (x - 17, y - 2.5, z - 17), (x + 17, y, z + 17))
    _frustum(m['cone_band'], x, z, 2.5 + 16.5 + 24, 2.5 + 16.5 + 32, 7.15, 5.85, segments=12)
    _box(m['cooler'], (842, 0, -980), (884, 34, -922))
    _box(m['cooler_lid'], (840, 34, -982), (886, 40, -920))
    colours = {'cone': (235, 96, 20), 'cone_band': (230, 230, 226), 'cooler': (36, 92, 170), 'cooler_lid': (232, 232, 228)}
    rough = {}
    report = {}
    for name, mesh in m.items():
        p, n, uv, ix = mesh.arrays()
        mat = _flat(level, extra, prefix, sconce_material, 'far_' + name, colours[name], rough=rough.get(name))
        add_emitter(level, extra, prefix + 'far-' + name, p * np.array([-1.0, 1.0, -1.0]), n * np.array([-1.0, 1.0, -1.0]),
                    uv, ix, _planar_uv7(p), mat)
        report[name] = int(len(p))
    return report


# NOT USED since N37 (the game draws basket1 there; the copy overlapped it).
# N36: "both hoops the same": the far hoop is the near gameplay hoop itself, copied prim by
# prim from baskets.SCNE (bind pose; basket1's placement = basket0's turned 180 degrees and
# moved to game z +1310.64, i.e. world = model - (0, 0, 1310.64)). Every prim keeps its own
# UV0 and textures (copied Texture entries) on the sconce material at zero emission. The
# glass sheets cannot use basket_glass.fx in the level, so they are opaque: the same dusty
# glass map composited over a dark night background, which is how the near board reads.
# The near net is the game's cloth; the far one is a static white cord net of the same size.
NET_ROWS, NET_DROP, NET_TAPER = 6, 7.4, 0.42


def _copy_texture(level, baskets, prefix, key):
    new = prefix + 'farhoop_tex:' + key.split('/')[-1]
    level['Texture'][new] = copy.deepcopy(baskets['Texture'][key])
    return {'Pixelmap': new}


def far_hoop(level, archive, extra, prefix, add_emitter, sconce_material):
    from iff_codec import load_scne, decode_attribute, decode_normals, resolve_binary
    from night_scene import _planar_uv7
    import backboard_glass as bg
    baskets = load_scne(archive.read('baskets.SCNE'))['baskets']
    shift = np.array([0.0, 0.0, -1310.64001])
    report = {}
    for suffix in (':basket', ':glass'):
        key = [k for k in baskets['Model'] if k.endswith('basket0' + suffix)][0]
        model = baskets['Model'][key]
        p = decode_attribute(archive, model, 'POSITION0')[:, :3].astype(float)
        n = decode_normals(decode_attribute(archive, model, 'TANGENTFRAME0'))
        uv = decode_attribute(archive, model, 'TEXCOORD0')[:, :2].astype(float)
        ix = np.frombuffer(archive.read(resolve_binary(archive, model['IndexBuffer']['Binary'])),
                           '<u2' if len(p) < 65536 else '<u4').astype(np.int64)
        world_p, world_n = p + shift, n
        for k, prim in enumerate(model['Prim']):
            mat_key = prim.get('Material')
            if mat_key is None or 'glasshole' in mat_key:
                continue
            tris = ix[prim['Start']:prim['Start'] + prim['Count']].reshape(-1, 3)
            used = np.unique(tris)
            if len(used) < 3:
                continue                                      # prims the R09 build collapsed away
            remap = -np.ones(len(p), np.int64); remap[used] = np.arange(len(used))
            pp, nn, uu, tt = world_p[used], world_n[used], uv[used], remap[tris]
            name = 'farhoop-' + (prim.get('Mesh') or str(k)).replace(' ', '_')
            src = baskets['Material'][mat_key]
            mat = copy.deepcopy(level['Material'][sconce_material])
            if 'glass' in mat_key:
                maps = bg._rasterise(uv, ix[prim['Start']:prim['Start'] + prim['Count']].reshape(-1, 3),
                                     np.stack([p[:, 0], p[:, 1], *bg._attributes(p)], 1), 512)
                rgba, _ = bg._dusty(maps[..., 0], maps[..., 1], maps[..., 2], maps[..., 3])
                night = np.array([26.0, 28.0, 30.0])
                rgb = rgba[..., :3] + night[None, None, :] * (1 - rgba[..., 3:] / 255.0)
                _, alb, _ = native_textures.encode(Image.fromarray(np.clip(rgb + 0.5, 0, 255).astype(np.uint8), 'RGB'), extra)
                _, nr, _ = native_textures.encode(Image.new('RGBA', (8, 8), (128, 128, 255, 110)), extra, linear=True)
                for t in [t for t in extra if t.endswith('.tld')]:
                    extra.pop(t)
                level['Texture'][prefix + 'tex_' + name + '_albedo'] = alb
                level['Texture'][prefix + 'tex_' + name + '_nr'] = nr
                albedo, normal_rough = {'Pixelmap': prefix + 'tex_' + name + '_albedo'}, {'Pixelmap': prefix + 'tex_' + name + '_nr'}
            else:
                res = src.get('Resource', {})
                albedo = _copy_texture(level, baskets, prefix, res['AlbedoMap']['Pixelmap'])
                normal_rough = (_copy_texture(level, baskets, prefix, res['NormalAndRoughMap']['Pixelmap'])
                                if 'NormalAndRoughMap' in res else copy.deepcopy(mat['Resource']['NormalAndRoughMap']))
            _, black, _ = native_textures.encode(Image.new('RGB', (8, 8), (0, 0, 0)), extra)
            for t in [t for t in extra if t.endswith('.tld')]:
                extra.pop(t)
            level['Texture'][prefix + 'tex_' + name + '_black'] = black
            metal = (_copy_texture(level, baskets, prefix, src['Resource']['MetalMap']['Pixelmap'])
                     if 'MetalMap' in src.get('Resource', {}) else {'Pixelmap': prefix + 'tex_' + name + '_black'})
            mat['Resource'] = {'AlbedoMap': albedo, 'EmissiveAlbedoMap': {'Pixelmap': prefix + 'tex_' + name + '_black'},
                               'MetalMap': metal, 'NormalAndRoughMap': normal_rough}
            mat['Parameter'].update(EmissiveIntensity=0.0, EmissiveTint=[1.0, 1.0, 1.0], AlwaysEmit=1,
                                    AlbedoScaleX=1.0, AlbedoScaleY=1.0, NormalScaleX=1.0, NormalScaleY=1.0)
            level['Material'][prefix + name] = mat
            add_emitter(level, extra, prefix + name, pp * np.array([-1.0, 1.0, -1.0]), nn * np.array([-1.0, 1.0, -1.0]),
                        uu, tt.reshape(-1), _planar_uv7(pp), prefix + name)
            report[name] = int(len(pp))
    # static white cord net under the copied rim (rim centre from the rig: model (0, 307.2, 38.1))
    rim = np.array([0.0, 307.2, 38.1]) + shift
    net = Mesh()
    hooks = 12
    pts = {}
    for k in range(NET_ROWS + 1):
        rad = RIM_R * (1 - NET_TAPER * k / NET_ROWS)
        off = 0.5 if k % 2 else 0.0
        for i in range(hooks):
            ang = 2 * math.pi * (i + off) / hooks
            pts[k, i] = rim + np.array([rad * math.cos(ang), -2.0 - NET_DROP * k, rad * math.sin(ang)])
    for k in range(NET_ROWS):
        for i in range(hooks):
            for j in ((i, (i + 1) % hooks) if k % 2 == 0 else ((i - 1) % hooks, i)):
                _tube(net, pts[k, i], pts[k + 1, j], 0.35, segments=4)
    p, nrm, uvn, ixn = net.arrays()
    mat = _flat(level, extra, prefix, sconce_material, 'farhoop_net', (226, 226, 222), rough=0.8)
    add_emitter(level, extra, prefix + 'farhoop-net', p * np.array([-1.0, 1.0, -1.0]), nrm * np.array([-1.0, 1.0, -1.0]),
                uvn, ixn, _planar_uv7(p), mat)
    report['net'] = int(len(p))
    return report
