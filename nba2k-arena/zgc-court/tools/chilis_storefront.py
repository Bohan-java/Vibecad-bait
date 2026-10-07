"""N18 Chilis storefront: a lived-in, glowing interior instead of flat warm planes.

The shallow interior (world x -80..920 cm, glass at z ~2105, back wall at
z 2297, ceiling ~310 cm) gets:
- a painted, emissive back wall: warm plaster lit by the pendants, back-bar
  shelves with bottles, two menu boards, a red neon pepper, framed prints and
  seated diners in silhouette (sconce textured-emission material)
- a walnut bar-front texture on the timber planes and soft light pools on the
  dark interior floor
- seven real 3D pendant lamps over the tables (glowing bulb, shade with a lit
  inside, cord), so the interior has depth and sparkle through the glass

Everything is new geometry bound like the LDIAG1 emitters; the original parts
stay untouched underneath. World cm; models use the 180 degree object matrix
(model = world * (-1, 1, -1)).
"""
from __future__ import annotations

import copy
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import native_textures

X0, X1 = -80.0, 920.0          # interior width
WALL_Z, WALL_TOP = 2297.0, 310.0
FLOOR_Z0, FLOOR_Z1 = 2105.0, 2298.0
PENDANT_X = [40.0, 170.0, 300.0, 430.0, 560.0, 690.0, 820.0]
PENDANT_Z = 2195.0
BULB_Y = 226.0
WARM = (1.0, 0.74, 0.45)        # ~2900 K
RNG = np.random.default_rng(1975)
FONTS = '/System/Library/Fonts/Supplemental/'
MENU = ['FAJITAS', 'BABY BACK RIBS', 'BURGERS', 'SKILLET QUESO', 'MARGARITAS', 'MOLTEN CAKE']


def _font(name, size):
    try:
        return ImageFont.truetype(FONTS + name, size)
    except OSError:
        return ImageFont.load_default()

# (texture intensity) EmissiveIntensity per surface. N19: N18 washed the interior out
# to white and stole the show from the sign; now a dim amber room where only the
# pendant bulbs sparkle.
WALL_INTENSITY = 1000.0      # N24: still read off-white in N22; dimmer, deeper amber
TIMBER_INTENSITY = 700.0
FLOOR_INTENSITY = 650.0
BULB = ((1.0, 0.8, 0.55), 26000.0)
SHADE_INNER = ((1.0, 0.66, 0.36), 4500.0)


def _wall_image(w=2048, h=624):
    sx = lambda x: (x - X0) / (X1 - X0) * w
    sy = lambda y: (WALL_TOP - y) / (WALL_TOP - 6.0) * h
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    y_cm = WALL_TOP - yy / h * (WALL_TOP - 6.0)
    x_cm = X0 + xx / w * (X1 - X0)
    # warm plaster, lit from the pendants: brighter around pendant height, darker low down
    light = 0.16 + 0.14 * np.clip((y_cm - 70) / 160, 0, 1)
    for px in PENDANT_X:
        d2 = ((x_cm - px) / 75) ** 2 + ((y_cm - (BULB_Y - 10)) / 60) ** 2
        light += 0.85 * np.exp(-d2 * 1.4)
        light += 0.18 * np.exp(-(((x_cm - px) / 40) ** 2 + ((y_cm - 130) / 90) ** 2))   # cone below
    light *= 1 - 0.25 * np.clip((y_cm - 285) / 25, 0, 1)                             # ceiling shadow line
    plaster = np.array([0.86, 0.5, 0.26])
    rgb = light[..., None] * plaster[None, None, :]
    rgb *= (1 + 0.04 * RNG.standard_normal((h, w)))[..., None]                        # plaster grain
    img = Image.fromarray((np.clip(rgb, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8), 'RGB')
    d = ImageDraw.Draw(img, 'RGBA')

    # framed prints
    for x, y, fw, fh in [(150, 265, 40, 30), (205, 262, 28, 36), (620, 265, 44, 30), (700, 278, 26, 20)]:
        d.rectangle([sx(x), sy(y + fh / 2), sx(x + fw), sy(y - fh / 2)], fill=(40, 28, 20, 255))
        d.rectangle([sx(x + 3), sy(y + fh / 2 - 3), sx(x + fw - 3), sy(y - fh / 2 + 3)],
                    fill=tuple(int(c) for c in RNG.choice([(176, 64, 40), (210, 170, 110), (90, 120, 100), (200, 120, 60)])) + (255,))
    # back bar: shelves and bottles
    for shelf_y in (176.0, 220.0):
        for x in np.arange(250, 600, 5.5 + 0.0):
            if RNG.random() < 0.18:
                continue
            bw = RNG.uniform(4.0, 6.5)
            bh = RNG.uniform(13, 22)
            colour = RNG.choice([(196, 112, 36), (70, 112, 64), (226, 222, 196), (120, 40, 30), (230, 170, 70)])
            d.rectangle([sx(x), sy(shelf_y + bh), sx(x + bw), sy(shelf_y + 1)], fill=tuple(int(c) for c in colour) + (235,))
            d.rectangle([sx(x + bw * 0.25), sy(shelf_y + bh + 6), sx(x + bw * 0.65), sy(shelf_y + bh)], fill=tuple(int(c) for c in colour) + (235,))
            d.line([sx(x + bw * 0.3), sy(shelf_y + bh - 2), sx(x + bw * 0.3), sy(shelf_y + 4)], fill=(255, 246, 220, 200), width=2)
        d.rectangle([sx(240), sy(shelf_y + 1), sx(610), sy(shelf_y - 3)], fill=(58, 36, 22, 255))
        d.line([sx(240), sy(shelf_y + 1), sx(610), sy(shelf_y + 1)], fill=(255, 214, 150, 255), width=2)
    # menu boards with chalk lines and a red header
    for x in (20.0, 690.0):
        d.rectangle([sx(x), sy(255), sx(x + 115), sy(160)], fill=(30, 34, 30, 255), outline=(92, 62, 38, 255), width=5)
        d.rectangle([sx(x + 8), sy(248), sx(x + 107), sy(236)], fill=(200, 38, 30, 255))
        chalk = _font('Chalkduster.ttf', 17)
        for k, item in enumerate(MENU):
            yk = 230 - k * 11.5
            d.text((sx(x + 9), sy(yk + 4)), item, font=chalk, fill=(232, 228, 210, 215))
            d.text((sx(x + 92), sy(yk + 4)), f'{RNG.integers(28, 88)}', font=chalk, fill=(244, 204, 120, 225))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    d = ImageDraw.Draw(img, 'RGBA')
    # seated diners in silhouette, softened
    sil = Image.new('L', (w, h), 0)
    ds = ImageDraw.Draw(sil)
    for x, y in [(95, 92), (128, 88), (365, 94), (400, 90), (515, 92), (782, 91), (812, 95)]:
        ds.ellipse([sx(x - 9), sy(y + 46), sx(x + 9), sy(y + 24)], fill=255)          # head
        ds.rounded_rectangle([sx(x - 19), sy(y + 26), sx(x + 19), sy(y - 20)], radius=int(w * 0.012), fill=255)
    sil = sil.filter(ImageFilter.GaussianBlur(4))
    dark = Image.new('RGB', (w, h), (52, 30, 20))
    img = Image.composite(dark, img, sil.point(lambda v: int(v * 0.82)))
    # red neon pepper with glow
    neon = Image.new('L', (w, h), 0)
    dn = ImageDraw.Draw(neon)
    script = _font('Brush Script.ttf', 110)
    dn.text((sx(290), sy(306)), "Chili's", font=script, fill=0, stroke_width=4, stroke_fill=255)   # neon tube outline
    glow = neon.filter(ImageFilter.GaussianBlur(14))
    img = Image.composite(Image.new('RGB', (w, h), (255, 70, 50)), img, glow.point(lambda v: int(min(255, v * 2.2))))
    img = Image.composite(Image.new('RGB', (w, h), (255, 228, 215)), img, neon)
    return img


def _timber_image(w=1024, h=128):
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    plank = (xx // 46).astype(int)
    tone = 0.75 + 0.25 * RNG.random(plank.max() + 1)[plank]
    grain = 0.85 + 0.15 * np.sin(xx * 0.9 + 4 * np.sin(yy * 0.05 + plank)) * np.sin(yy * 0.3)
    shade = 0.55 + 0.45 * (1 - yy / h)                     # lit from above
    base = np.array([0.42, 0.22, 0.11])
    rgb = (tone * grain * shade)[..., None] * base
    rgb[(xx % 46) < 1.5] *= 0.35                          # plank seams
    rgb[:5] = (1.0, 0.78, 0.45)                           # brass top rail catching the light
    return Image.fromarray((np.clip(rgb, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8), 'RGB')


def _floor_image(w=1024, h=256):
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    x_cm = X0 + xx / w * (X1 - X0)
    z_cm = FLOOR_Z0 + yy / h * (FLOOR_Z1 - FLOOR_Z0)
    light = 0.10 + np.zeros_like(x_cm)
    for px in PENDANT_X:
        light += 0.55 * np.exp(-(((x_cm - px) / 55) ** 2 + ((z_cm - PENDANT_Z) / 45) ** 2))
    light += 0.25 * np.exp(-((z_cm - FLOOR_Z0) / 40) ** 2)      # spill toward the glass
    under_table = (x_cm > -1) & (x_cm < 841) & (z_cm > 2159) & (z_cm < 2222)
    light[under_table] *= 0.45
    rgb = light[..., None] * np.array([1.0, 0.72, 0.46])[None, None, :]
    rgb *= (1 + 0.05 * RNG.standard_normal((h, w)))[..., None]
    img = Image.fromarray((np.clip(rgb, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8), 'RGB')
    return img.filter(ImageFilter.GaussianBlur(2))


def _textured_material(level, extra, prefix, sconce_material, key, image, intensity):
    _, emissive, _ = native_textures.encode(image, extra)
    _, albedo, _ = native_textures.encode(Image.new('RGB', (8, 8), (60, 45, 36)), extra)
    _, metal, _ = native_textures.encode(Image.new('RGB', (8, 8), (8, 8, 8)), extra, linear=True)
    for name in [k for k in extra if k.endswith('.tld')]:
        extra.pop(name)
    level['Texture'][prefix + 'tex_' + key] = emissive
    level['Texture'][prefix + 'tex_' + key + '_albedo'] = albedo
    level['Texture'][prefix + 'tex_' + key + '_metal'] = metal
    mat = copy.deepcopy(level['Material'][sconce_material])
    mat['Resource'] = {'AlbedoMap': {'Pixelmap': prefix + 'tex_' + key + '_albedo'},
                       'EmissiveAlbedoMap': {'Pixelmap': prefix + 'tex_' + key},
                       'MetalMap': {'Pixelmap': prefix + 'tex_' + key + '_metal'},
                       'NormalAndRoughMap': copy.deepcopy(mat['Resource']['NormalAndRoughMap'])}
    mat['Parameter'].update(EmissiveIntensity=intensity, EmissiveTint=[1.0, 1.0, 1.0], AlwaysEmit=1)
    level['Material'][prefix + key] = mat
    return prefix + key


def _quad(p0, p1, p2, p3, normal, uv):
    p = np.array([p0, p1, p2, p3], float)
    n = np.tile(normal, (4, 1)).astype(float)
    tri = [(0, 1, 2), (0, 2, 3)]
    if np.dot(np.cross(p[1] - p[0], p[2] - p[0]), normal) < 0:
        tri = [(0, 2, 1), (0, 3, 2)]
    return p, n, np.array(uv, float), [i for t in tri for i in t]


class Mesh:
    def __init__(self):
        self.p, self.n, self.uv, self.ix = [], [], [], []

    def add(self, p, n, uv, ix):
        base = sum(len(a) for a in self.p)
        self.p.append(p); self.n.append(n); self.uv.append(uv)
        self.ix += [base + i for i in ix]

    def arrays(self):
        return np.concatenate(self.p), np.concatenate(self.n), np.concatenate(self.uv), np.array(self.ix)


def _frustum(mesh, cx, cz, y0, y1, r0, r1, segments=16, inward=False):
    """Open cone side from (y0, r0) to (y1, r1); outward or inward facing."""
    for k in range(segments):
        a, b = 2 * math.pi * k / segments, 2 * math.pi * (k + 1) / segments
        pts = [(cx + r0 * math.cos(a), y0, cz + r0 * math.sin(a)), (cx + r0 * math.cos(b), y0, cz + r0 * math.sin(b)),
               (cx + r1 * math.cos(b), y1, cz + r1 * math.sin(b)), (cx + r1 * math.cos(a), y1, cz + r1 * math.sin(a))]
        mid = (a + b) / 2
        slope = (r0 - r1) / max(y1 - y0, 1e-6)
        normal = np.array([math.cos(mid), slope, math.sin(mid)])
        normal /= np.linalg.norm(normal)
        if inward:
            normal = -normal
        mesh.add(*_quad(*pts, normal, [(0, 0), (1, 0), (1, 1), (0, 1)]))


def _sphere(mesh, c, r, rings=6, segments=10):
    for i in range(rings):
        t0, t1 = max(math.pi * i / rings, 0.15), min(math.pi * (i + 1) / rings, math.pi - 0.15)   # no degenerate poles
        for k in range(segments):
            a, b = 2 * math.pi * k / segments, 2 * math.pi * (k + 1) / segments
            pt = lambda t, s: np.array([c[0] + r * math.sin(t) * math.cos(s), c[1] + r * math.cos(t), c[2] + r * math.sin(t) * math.sin(s)])
            q = [pt(t0, a), pt(t0, b), pt(t1, b), pt(t1, a)]
            normal = (q[0] + q[2]) / 2 - np.asarray(c)
            normal /= np.linalg.norm(normal)
            mesh.add(*_quad(*q, normal, [(0, 0), (1, 0), (1, 1), (0, 1)]))


def _box(mesh, lo, hi):
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    for axis in range(3):
        for side in (0, 1):
            n = np.zeros(3); n[axis] = 1 if side else -1
            u, v = [a for a in range(3) if a != axis]
            c = lo.copy(); c[axis] = hi[axis] if side else lo[axis]
            pts = []
            for du, dv in [(0, 0), (1, 0), (1, 1), (0, 1)]:
                q = c.copy(); q[u] = hi[u] if du else lo[u]; q[v] = hi[v] if dv else lo[v]
                pts.append(q)
            mesh.add(*_quad(*pts, n, [(0, 0), (1, 0), (1, 1), (0, 1)]))


def _planar_uv7(p):
    span = np.ptp(p, axis=0)
    a, b = np.argsort(span)[-2:][::-1]
    q = p[:, [a, b]]
    lo, size = q.min(0), np.maximum(np.ptp(q, axis=0), 1e-6)
    return 0.03 + 0.94 * (q - lo) / size


# N26 from the night reference photo (40.jpg): uplights wash the two silver pilasters beside
# the sign, and strings of small warm bulbs hang under the awning between its arms.
PILASTER_INTENSITY = 7000.0
AWNING_STRINGS = [(1985.0, 276.0), (2045.0, 290.0)]          # (z, y) of each strand under the canvas
AWNING_ARMS_X = [-95.0, 100.0, 250.0, 400.0, 600.0, 750.0, 935.0]
AWNING_BULB = ((1.0, 0.58, 0.25), 30000.0)


def _pilaster_wash(h=256):
    y = WALL_TOP + 163.0 - np.arange(h) / h * 470.0           # v = 0 at the pilaster top (473 cm)
    band = np.exp(-0.5 * ((y - 395.0) / 42.0) ** 2) + 0.18 * np.exp(-0.5 * ((y - 330.0) / 60.0) ** 2)
    rgb = np.clip(band, 0, 1)[:, None, None] * np.array([1.0, 0.84, 0.62])[None, None, :]
    rgb = np.repeat(rgb, 8, 1)
    return Image.fromarray((np.clip(rgb, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8), 'RGB')


def _awning_strings(mesh_bulbs, mesh_wire):
    for z, y in AWNING_STRINGS:
        for x0, x1 in zip(AWNING_ARMS_X[:-1], AWNING_ARMS_X[1:]):
            pts = [np.array([x0 + (x1 - x0) * t, y - 9.0 * 4 * t * (1 - t), z]) for t in np.linspace(0, 1, 9)]
            for p0, p1 in zip(pts[:-1], pts[1:]):
                _box(mesh_wire, np.minimum(p0, p1) - 0.25, np.maximum(p0, p1) + 0.25)
            n = max(2, int(round((x1 - x0) / 26.0)))
            for k in range(n):
                t = (k + 0.5) / n
                c = np.array([x0 + (x1 - x0) * t, y - 9.0 * 4 * t * (1 - t) - 4.0, z])
                _sphere(mesh_bulbs, c, 2.2, rings=4, segments=8)


# N29: 0.4 cm skins z-fought with the walls under them (flicker under Chili's in N26-N28).
SKIN_CM = 1.5


def apply(level, archive, extra, prefix, add_emitter, emitter_material, lamp_material, sconce_material, overlay_geometry):
    """overlay_geometry(source) -> (world positions, world normals) of an existing part."""
    world = lambda a: np.asarray(a, float) * np.array([-1.0, 1.0, -1.0])
    report = {}

    # back wall: one quad 0.4 cm in front of the plane, facing the court (-z)
    wall_mat = _textured_material(level, extra, prefix, sconce_material, 'chilis_wall', _wall_image(), WALL_INTENSITY)
    z = WALL_Z - SKIN_CM
    p, n, uv, ix = _quad((X0, 6.0, z), (X1, 6.0, z), (X1, WALL_TOP, z), (X0, WALL_TOP, z), np.array([0.0, 0.0, -1.0]),
                         [(0, 1), (1, 1), (1, 0), (0, 0)])
    add_emitter(level, extra, prefix + 'chilis-wall', world(p), world(n), uv, np.array(ix), _planar_uv7(p), wall_mat)
    report['wall'] = {'intensity': WALL_INTENSITY}

    # bar front / timber planes: existing geometry, own planar UV0
    timber_mat = _textured_material(level, extra, prefix, sconce_material, 'chilis_timber', _timber_image(), TIMBER_INTENSITY)
    p, n, ix = overlay_geometry('zgc_r03:part-0102')
    p = p + n * SKIN_CM
    uv = np.stack([(p[:, 0] - X0) / (X1 - X0), (70.0 - p[:, 1]) / 64.0], 1)
    add_emitter(level, extra, prefix + 'chilis-timber', world(p), world(n), uv, ix, _planar_uv7(p), timber_mat)

    # interior floor light pools
    floor_mat = _textured_material(level, extra, prefix, sconce_material, 'chilis_floor', _floor_image(), FLOOR_INTENSITY)
    p, n, ix = overlay_geometry('zgc_r03:part-0100')
    p = p + n * SKIN_CM
    uv = np.stack([(p[:, 0] - X0) / (X1 - X0), (p[:, 2] - FLOOR_Z0) / (FLOOR_Z1 - FLOOR_Z0)], 1)
    add_emitter(level, extra, prefix + 'chilis-floor', world(p), world(n), uv, ix, _planar_uv7(p), floor_mat)

    # pendant lamps
    bulb_mat = prefix + 'emit_chilis_bulb'
    level['Material'][bulb_mat] = emitter_material(level, *BULB)
    inner_mat = prefix + 'emit_chilis_shade_inner'
    level['Material'][inner_mat] = emitter_material(level, *SHADE_INNER)
    dark = copy.deepcopy(level['Material'][lamp_material])
    dark['Parameter'].update(DefaultAlbedo=[0.05, 0.035, 0.025], EmissiveDefaultAlbedo=[0.0, 0.0, 0.0], EmissiveIntensity=0.0)
    level['Material'][prefix + 'chilis_pendant_dark'] = dark
    bulbs, inner, outer = Mesh(), Mesh(), Mesh()
    for x in PENDANT_X:
        _sphere(bulbs, (x, BULB_Y, PENDANT_Z), 4.5)
        _frustum(inner, x, PENDANT_Z, BULB_Y - 6, BULB_Y + 16, 17.0, 5.0, inward=True)
        _frustum(outer, x, PENDANT_Z, BULB_Y - 6.3, BULB_Y + 16.3, 17.4, 5.3)
        _box(outer, (x - 0.5, BULB_Y + 16, PENDANT_Z - 0.5), (x + 0.5, WALL_TOP, PENDANT_Z + 0.5))
    for name, mesh, mat in (('pendant-bulbs', bulbs, bulb_mat), ('pendant-inner', inner, inner_mat),
                            ('pendant-outer', outer, prefix + 'chilis_pendant_dark')):
        p, n, uv, ix = mesh.arrays()
        add_emitter(level, extra, prefix + 'chilis-' + name, world(p), world(n), uv, ix, _planar_uv7(p), mat)
    report['pendants'] = {'x_cm': PENDANT_X, 'z_cm': PENDANT_Z, 'bulb_y_cm': BULB_Y}

    # pilaster uplight wash: court-facing faces of the two silver pilasters (part-0085)
    wash_mat = _textured_material(level, extra, prefix, sconce_material, 'chilis_pilaster_wash', _pilaster_wash(), PILASTER_INTENSITY)
    p, n, ix = overlay_geometry('zgc_r03:part-0085')
    tris = ix.reshape(-1, 3)
    tris = tris[n[tris].mean(1)[:, 2] < -0.3]
    used = np.unique(tris)
    remap = -np.ones(len(p), np.int64); remap[used] = np.arange(len(used))
    p, n, tris = p[used] + n[used] * SKIN_CM, n[used], remap[tris]
    uv = np.stack([np.full(len(p), 0.5), (473.0 - p[:, 1]) / 470.0], 1)
    add_emitter(level, extra, prefix + 'chilis-pilaster-wash', world(p), world(n), uv, tris.reshape(-1), _planar_uv7(p), wash_mat)

    # bulb strings under the awning
    string_mat = prefix + 'emit_chilis_awning_bulbs'
    level['Material'][string_mat] = emitter_material(level, *AWNING_BULB)
    bulbs_m, wire_m = Mesh(), Mesh()
    _awning_strings(bulbs_m, wire_m)
    for name, mesh, mat in (('awning-bulbs', bulbs_m, string_mat), ('awning-wire', wire_m, prefix + 'chilis_pendant_dark')):
        p, n, uv, ix = mesh.arrays()
        add_emitter(level, extra, prefix + 'chilis-' + name, world(p), world(n), uv, ix, _planar_uv7(p), mat)
    report['pilaster_wash'] = PILASTER_INTENSITY
    report['awning_strings'] = {'strands': AWNING_STRINGS, 'arms_x': AWNING_ARMS_X}
    return report
