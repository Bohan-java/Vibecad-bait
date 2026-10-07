"""Added night lights: festoon bulbs on the Chilis-side fence (N22), the plaza's own
lamp posts switched on and two vending machines on the far half (N26).

N26 structure: the scene already has four 5.55 m plaza lamp posts with twin heads
(zgc_r03:part-0046, "plaza discreet fixtures") at the SW/SE corners of the far half,
the west side and the south plaza; they were never lit, while N22 invented two extra
lamps (one right next to an existing post). N26 lights the real posts instead and
drops the invented ones; the far half also gets two lit vending machines so it has
its own light and life instead of an empty dark foreground.

One source of truth for both sides:
- game fixtures (bulbs, sockets, wires, lamp poles, heads and glowing lenses) as
  new native-bound geometry, and
- Blender bake lights for the same fixtures (bake/bake_lights.json groups
  'festoon' and 'plaza_lamps', written by `python3 tools/night_lights.py`), so
  the probe bake lights players and the surface bake lights the floor, with
  shadows, exactly where the fixtures are.

Art direction: warm 2400 K filament bulbs strung post-to-post along the north
fence (Chilis side) and two posts down each side fence, sagging 32 cm, one bulb
every ~46 cm; two 5.2 m plaza lamps outside the side fences (3500 K, light
falling down onto the plaza and the court edge). World cm unless noted.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

POST_TOP_Y = 372.0
WIRE_Y = 366.0
SAG_CM = 32.0
BULB_SPACING_CM = 46.0
BULB_DROP_CM = 9.0
BULB_RADIUS_CM = 3.8
NORTH_Z = 1608.0
NORTH_X = [-917.0, -688.0, -458.0, -229.0, 0.0, 229.0, 459.0, 688.0, 917.0]
EAST = [(917.0, 1608.0), (917.0, 1387.0), (917.0, 1166.0)]
WEST = [(-917.0, 1608.0), (-917.0, 1383.0), (-917.0, 1157.0)]
BULB_COLOUR = (1.0, 0.47, 0.15)        # N24: amber ~2200 K (N22 read as small white dots)
BULB_EMISSION = 45000.0
BULB_BAKE_WATTS = 3.5
LAMPS = [  # (base x, base z, arm direction x, arm direction z): arms reach toward the court
    (1265.0, -160.0, -1.0, 0.0),
    (-1300.0, 140.0, 1.0, 0.0),
]
LAMP_HEIGHT = 520.0
ARM_CM = 70.0
LENS = (40.0, 18.0)                    # along the arm, across
LAMP_COLOUR = (1.0, 0.87, 0.7)         # ~3500 K
LAMP_EMISSION = 18000.0
LAMP_BAKE_WATTS = 260.0


def spans():
    north = [((NORTH_X[i], NORTH_Z), (NORTH_X[i + 1], NORTH_Z)) for i in range(len(NORTH_X) - 1)]
    side = [(EAST[i], EAST[i + 1]) for i in range(len(EAST) - 1)] + [(WEST[i], WEST[i + 1]) for i in range(len(WEST) - 1)]
    return north + side


def wire_point(a, b, t):
    x = a[0] + (b[0] - a[0]) * t
    z = a[1] + (b[1] - a[1]) * t
    return np.array([x, WIRE_Y - SAG_CM * 4 * t * (1 - t), z])


def bulbs():
    out = []
    for a, b in spans():
        n = max(2, int(round(math.hypot(b[0] - a[0], b[1] - a[1]) / BULB_SPACING_CM)))
        for k in range(n):
            w = wire_point(a, b, (k + 0.5) / n)
            out.append(w - np.array([0.0, BULB_DROP_CM, 0.0]))
    return out


def lamp_parts():
    """[(base, top, head centre, arm dir)] per lamp."""
    out = []
    for x, z, dx, dz in LAMPS:
        base = np.array([x, 0.0, z])
        top = np.array([x, LAMP_HEIGHT, z])
        head = top + np.array([dx, 0.0, dz]) * ARM_CM + np.array([0.0, -8.0, 0.0])
        out.append((base, top, head, np.array([dx, 0.0, dz])))
    return out


def to_blender(p):
    return [round(-p[2] / 100, 4), round(-p[0] / 100, 4), round(p[1] / 100, 4)]


# Existing twin-head posts: head footprints (world cm) measured from part-0046; head underside y 536.
POST_HEADS = [
    ((-1220.0, -1200.0), (-96.0, -64.0)), ((-1220.0, -1200.0), (-135.0, -104.0)),
    ((-1231.0, -1209.0), (-1645.0, -1614.0)), ((-1231.0, -1209.0), (-1685.0, -1655.0)),
    ((1259.0, 1281.0), (-1776.0, -1745.0)), ((1259.0, 1281.0), (-1816.0, -1784.0)),
    ((669.0, 690.0), (-2996.0, -2965.0)), ((669.0, 690.0), (-3036.0, -3004.0)),
]
POST_HEAD_Y = 536.0
POST_COLOUR = (1.0, 0.86, 0.68)        # ~3600 K, a touch warmer than the court's cool night
POST_EMISSION = 16000.0
POST_BAKE_WATTS = 170.0
# Vending machines on the far half's east side, fronts facing the court (-x).
VENDING = [  # (front x, centre z, body colour linear, header colour sRGB)
    (1142.0, -955.0, (0.42, 0.02, 0.025), (214, 30, 38)),
    (1142.0, -1067.0, (0.02, 0.07, 0.32), (30, 92, 196)),
]
VEND_W, VEND_H, VEND_D = 104.0, 186.0, 76.0
VEND_EMISSION = 2600.0
VEND_BAKE_WATTS = 95.0


def bake_groups():
    festoon = [{'name': f'bake_festoon_{i:03d}', 'type': 'POINT', 'location': to_blender(p),
                'radius': BULB_RADIUS_CM / 100, 'aim': None, 'colour': list(BULB_COLOUR), 'power': BULB_BAKE_WATTS}
               for i, p in enumerate(bulbs())]
    posts = []
    for i, ((x0, x1), (z0, z1)) in enumerate(POST_HEADS):
        c = np.array([(x0 + x1) / 2, POST_HEAD_Y - 1.0, (z0 + z1) / 2])
        # AREA faces Blender -Z (down); size_x runs along Blender X = world -z
        posts.append({'name': f'bake_plaza_post_{i}', 'type': 'AREA', 'location': to_blender(c),
                      'size_x': (z1 - z0) / 100, 'size_y': (x1 - x0) / 100, 'aim': None,
                      'colour': list(POST_COLOUR), 'power': POST_BAKE_WATTS})
    vend = []
    for i, (fx, cz, _, _) in enumerate(VENDING):
        c = np.array([fx - 1.0, 112.0, cz])
        vend.append({'name': f'bake_vending_{i}', 'type': 'AREA', 'location': to_blender(c),
                     'size_x': (VEND_W - 14) / 100, 'size_y': 1.3, 'aim': to_blender(c - np.array([100.0, 0.0, 0.0])),
                     'colour': [0.93, 0.96, 1.0], 'power': VEND_BAKE_WATTS})
    return {'festoon': {'emitters': [], 'lights': festoon,
                        'note': 'N22 warm filament bulbs strung along the north fence and the first two side spans.'},
            'plaza_posts': {'emitters': [], 'lights': posts,
                            'note': 'N26 the scene\'s own four twin-head plaza lamp posts (part-0046), lenses facing down.'},
            'vending': {'emitters': [], 'lights': vend,
                        'note': 'N26 two vending machine fronts on the far half, facing the court.'}}


# ---------------------------------------------------------------- game geometry
def _mesh_add(mesh, p, n, ix):
    base = sum(len(a) for a in mesh[0])
    mesh[0].append(np.asarray(p, float)); mesh[1].append(np.asarray(n, float)); mesh[2].extend(base + i for i in ix)


def _quad(mesh, pts, normal):
    pts = np.asarray(pts, float)
    tri = [0, 1, 2, 0, 2, 3]
    if np.dot(np.cross(pts[1] - pts[0], pts[2] - pts[0]), normal) < 0:
        tri = [0, 2, 1, 0, 3, 2]
    _mesh_add(mesh, pts, np.tile(normal, (4, 1)), tri)


def _sphere(mesh, c, r, rings=6, segments=10):
    c = np.asarray(c, float)
    for i in range(rings):
        t0, t1 = max(math.pi * i / rings, 0.15), min(math.pi * (i + 1) / rings, math.pi - 0.15)
        for k in range(segments):
            a, b = 2 * math.pi * k / segments, 2 * math.pi * (k + 1) / segments
            pt = lambda t, s: c + r * np.array([math.sin(t) * math.cos(s), math.cos(t), math.sin(t) * math.sin(s)])
            q = [pt(t0, a), pt(t0, b), pt(t1, b), pt(t1, a)]
            n = (q[0] + q[2]) / 2 - c
            _quad(mesh, q, n / np.linalg.norm(n))


def _tube(mesh, a, b, r, segments=8):
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    d /= np.linalg.norm(d)
    u = np.cross(d, [0.0, 1.0, 0.0] if abs(d[1]) < 0.9 else [1.0, 0.0, 0.0]); u /= np.linalg.norm(u)
    v = np.cross(d, u)
    for k in range(segments):
        s0, s1 = 2 * math.pi * k / segments, 2 * math.pi * (k + 1) / segments
        o0, o1 = u * math.cos(s0) + v * math.sin(s0), u * math.cos(s1) + v * math.sin(s1)
        n = (o0 + o1) / np.linalg.norm(o0 + o1)
        _quad(mesh, [a + o0 * r, a + o1 * r, b + o1 * r, b + o0 * r], n)


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
            _quad(mesh, pts, n)


def _arrays(mesh):
    return np.concatenate(mesh[0]), np.concatenate(mesh[1]), np.array(mesh[2])


def apply(level, archive, extra, prefix, add_emitter, emitter_material, lamp_material, sconce_material):
    world = lambda a: np.asarray(a, float) * np.array([-1.0, 1.0, -1.0])
    def emit_uv(level, extra, name, p, n, uv, ix, material):
        add_emitter(level, extra, name, world(p), world(n), uv, ix, planar_uv7(p), material)

    def planar_uv7(p):
        span = np.ptp(p, axis=0)
        a, b = np.argsort(span)[-2:][::-1]
        q = p[:, [a, b]]
        return 0.03 + 0.94 * (q - q.min(0)) / np.maximum(np.ptp(q, axis=0), 1e-6)

    def emit(name, mesh, material):
        p, n, ix = _arrays(mesh)
        add_emitter(level, extra, prefix + name, world(p), world(n), np.zeros((len(p), 2)), ix, planar_uv7(p), material)

    import copy
    dark = copy.deepcopy(level['Material'][lamp_material])
    dark['Parameter'].update(DefaultAlbedo=[0.03, 0.03, 0.032], EmissiveDefaultAlbedo=[0.0, 0.0, 0.0], EmissiveIntensity=0.0)
    level['Material'][prefix + 'fixture_dark'] = dark
    metal = copy.deepcopy(dark)
    metal['Parameter'].update(DefaultAlbedo=[0.16, 0.16, 0.17])
    level['Material'][prefix + 'fixture_grey'] = metal
    level['Material'][prefix + 'emit_festoon'] = emitter_material(level, BULB_COLOUR, BULB_EMISSION)

    glow, wires = ([], [], []), ([], [], [])
    for a, b in spans():
        pts = [wire_point(a, b, t) for t in np.linspace(0, 1, 13)]
        for p0, p1 in zip(pts[:-1], pts[1:]):
            _tube(wires, p0, p1, 0.35, segments=4)
    for c in bulbs():
        _sphere(glow, c, BULB_RADIUS_CM)
        _tube(wires, c + [0, BULB_RADIUS_CM * 0.8, 0], c + [0, BULB_DROP_CM, 0], 0.9, segments=6)   # socket + drop
    emit('festoon-bulbs', glow, prefix + 'emit_festoon')
    emit('festoon-wires', wires, prefix + 'fixture_dark')

    # existing plaza posts: glowing lens under each twin head, a hair below the housing
    level['Material'][prefix + 'emit_plaza_post'] = emitter_material(level, POST_COLOUR, POST_EMISSION)
    lenses = ([], [], [])
    for (x0, x1), (z0, z1) in POST_HEADS:
        y = POST_HEAD_Y - 0.4
        _quad(lenses, [(x0 + 1.5, y, z0 + 1.5), (x1 - 1.5, y, z0 + 1.5), (x1 - 1.5, y, z1 - 1.5), (x0 + 1.5, y, z1 - 1.5)],
              np.array([0.0, -1.0, 0.0]))
    emit('plaza-post-lenses', lenses, prefix + 'emit_plaza_post')

    vending = _vending(level, extra, prefix, emit, emit_uv, sconce_material, lamp_material)
    return {'festoon_bulbs': len(bulbs()), 'festoon_spans': len(spans()), 'plaza_post_heads': len(POST_HEADS),
            'vending': vending, 'bulb': {'colour': BULB_COLOUR, 'emission': BULB_EMISSION},
            'post': {'colour': POST_COLOUR, 'emission': POST_EMISSION}}


def _vending_front(header, size=(256, 512)):
    """Front panel: brand header, backlit product window with rows of bottles, button strip, dark tray."""
    from PIL import Image, ImageDraw, ImageFilter
    w, h = size
    rng = np.random.default_rng(int(sum(header)))
    img = Image.new('RGB', size, (18, 18, 20))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, int(h * 0.12)], fill=header)
    d.rectangle([int(w * 0.08), int(h * 0.035), int(w * 0.62), int(h * 0.085)], fill=(250, 250, 250))
    top, bottom = int(h * 0.15), int(h * 0.70)
    d.rectangle([int(w * 0.05), top, int(w * 0.95), bottom], fill=(236, 240, 246))      # backlit window
    rows = 4
    palette = [(220, 40, 40), (250, 160, 40), (60, 170, 80), (40, 120, 220), (245, 245, 245), (120, 70, 40), (250, 220, 60)]
    for r in range(rows):
        y1 = top + (bottom - top) * (r + 1) / rows - 6
        y0 = y1 - (bottom - top) / rows * 0.62
        for k in range(7):
            x0 = w * 0.08 + k * w * 0.123
            c = palette[rng.integers(len(palette))]
            d.rounded_rectangle([x0, y0, x0 + w * 0.08, y1], radius=4, fill=c)
            d.line([x0 + w * 0.02, y0 + 4, x0 + w * 0.02, y1 - 4], fill=(255, 255, 255), width=2)
        d.rectangle([w * 0.05, y1 + 1, w * 0.95, y1 + 5], fill=(150, 150, 160))           # shelf lip
    for k in range(7):                                                                     # selection buttons
        x0 = w * 0.08 + k * w * 0.123
        d.rectangle([x0, bottom + 10, x0 + w * 0.08, bottom + 18], fill=(120, 230, 140))
    d.rectangle([int(w * 0.62), int(h * 0.74), int(w * 0.9), int(h * 0.80)], fill=(40, 200, 255))   # payment screen
    d.rectangle([int(w * 0.12), int(h * 0.84), int(w * 0.88), int(h * 0.95)], fill=(6, 6, 8))       # dispenser tray
    return img.filter(ImageFilter.GaussianBlur(0.6))


def _vending(level, extra, prefix, emit, emit_uv, sconce_material, lamp_material):
    import copy
    import native_textures
    from PIL import Image
    out = []
    for i, (fx, cz, body, header) in enumerate(VENDING):
        _, front_tex, _ = native_textures.encode(_vending_front(header), extra)
        _, albedo, _ = native_textures.encode(Image.new('RGB', (8, 8), (30, 30, 34)), extra)
        _, metal, _ = native_textures.encode(Image.new('RGB', (8, 8), (20, 20, 20)), extra, linear=True)
        for name in [k for k in extra if k.endswith('.tld')]:
            extra.pop(name)
        level['Texture'][prefix + f'tex_vending_{i}'] = front_tex
        level['Texture'][prefix + f'tex_vending_{i}_albedo'] = albedo
        level['Texture'][prefix + f'tex_vending_{i}_metal'] = metal
        mat = copy.deepcopy(level['Material'][sconce_material])
        mat['Resource'] = {'AlbedoMap': {'Pixelmap': prefix + f'tex_vending_{i}_albedo'},
                           'EmissiveAlbedoMap': {'Pixelmap': prefix + f'tex_vending_{i}'},
                           'MetalMap': {'Pixelmap': prefix + f'tex_vending_{i}_metal'},
                           'NormalAndRoughMap': copy.deepcopy(mat['Resource']['NormalAndRoughMap'])}
        mat['Parameter'].update(EmissiveIntensity=VEND_EMISSION, EmissiveTint=[1.0, 1.0, 1.0], AlwaysEmit=1)
        level['Material'][prefix + f'vending_front_{i}'] = mat
        shell = copy.deepcopy(level['Material'][lamp_material])
        shell['Parameter'].update(DefaultAlbedo=list(body), EmissiveDefaultAlbedo=[0.0, 0.0, 0.0], EmissiveIntensity=0.0)
        level['Material'][prefix + f'vending_body_{i}'] = shell
        z0, z1 = cz - VEND_W / 2, cz + VEND_W / 2
        body_mesh = ([], [], [])
        _box(body_mesh, (fx, 0.0, z0), (fx + VEND_D, VEND_H, z1))
        emit(f'vending-body-{i}', body_mesh, prefix + f'vending_body_{i}')
        front = ([], [], [])
        x = fx - 0.4
        # seen from the court (looking +x) +z is screen-right (LDIAG tiles: looking +z, +x is screen-left)
        p = np.array([(x, 4.0, z0 + 4), (x, 4.0, z1 - 4), (x, VEND_H - 4, z1 - 4), (x, VEND_H - 4, z0 + 4)])
        _quad(front, p, np.array([-1.0, 0.0, 0.0]))
        pts, nrm, ix = _arrays(front)
        # UV0: u across the front (left to right seen from the court), v top-down
        uv = np.array([(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)])
        out.append({'front_x': fx, 'centre_z': cz, 'body': body})
        emit_uv(level, extra, prefix + f'vending-front-{i}', pts, nrm, uv, ix, prefix + f'vending_front_{i}')
    return out


if __name__ == '__main__':
    path = Path(__file__).resolve().parent.parent / 'bake' / 'bake_lights.json'
    spec = json.loads(path.read_text(encoding='utf8'))
    groups = bake_groups()
    spec['groups'].pop('plaza_lamps', None)                     # N26: replaced by the scene's own posts
    for g in ('plaza_posts', 'vending'):                       # festoon stays as baked in N22
        spec['groups'][g] = groups[g]
    path.write_text(json.dumps(spec, indent=1), encoding='utf8')
    print('wrote', path, {g: len(v['lights']) for g, v in spec['groups'].items()})
