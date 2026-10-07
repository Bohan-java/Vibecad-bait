"""N30 baked light on the surfaces around the court (the "hybrid" plan).

Every night light group is baked in Blender/Cycles onto receiver planes
(bake/bake_surface.py), shadows and bounce included:
  surface_plaza          floor patch x -2260..2100, z -3200..2110, 16 cm up
  surface_chilis_facade  the Chili's building front (plane z 2086, facing the court)
  surface_boots_facade   the boots building front (plane x 1606, facing the court)

Each receiving surface gets an emissive skin like the Chili's entry stone
(scene_details.entry_floor): a copy of its court-facing faces 1 cm out, UV0 planar
over the faces' own bounding box, the original albedo re-tiled through AlbedoScale,
and an emission map = baked light x albedo on the court overlay's absolute scale.
Cropping each skin to its own bounding box keeps the textures small.

The plaza ground itself (part-0019, a few huge triangles whose UVs stretch the 8k
atlas over the plaza) gets a ring of four quads around the court (the court has its
own overlay), 0.6 cm up. Their albedo is the atlas resampled through the original
triangles, so the ground looks exactly as before where no light falls.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from iff_codec import decode_attribute, resolve_binary
from scene_details import _material, _mean_albedo, _srgb_image

BAKE = Path(__file__).resolve().parent.parent / 'bake' / 'output'
COURT_RECT = (-1162.0, 1162.0, -1833.0, 1833.0)
GROUND = 'zgc_r03:part-0019'
GROUND_LIFT_CM = 0.6
SKIN_CM = 1.0
GROUND_ALBEDO_CM = 2.0
GAIN = 1.0
# N32 wet ground: after-rain puddles and damp patches on the plaza ground ring (not the
# rubber court). A world-space noise field, biased toward the strip between the fence and
# Chili's and along the fence line, sets per texel: roughness (dry 0.85 -> puddle 0.05,
# so the neon and bulbs reflect), a flat normal in the water, and a darker wet albedo.
# N33 game result: the puddles do reflect, but the gameplay camera never sees the ground
# outside the fence (fences, boards and buildings block it). Wet ground is switched off.
WET = False
WET_CM = 4.0
WET_SEED = 32
PUDDLE_ROUGH, DAMP_ROUGH, DRY_ROUGH = 0.05, 0.35, 0.85
WET_DARKEN = 0.55            # albedo x this where fully wet
# receiving parts per bake (court-facing faces only); see the N30 survey in the
# release notes. Already-skinned parts (entry stone, Chili's interior, boots shop
# windows, cornice, pilasters, glowing overlays) are not listed.
SKINS = {
    'surface_plaza': ['0017', '0043', '0023', '0032', '0190', '0198', '0199'],
    'surface_chilis_facade': ['0116', '0117', '0122', '0103', '0112', '0121'],
    'surface_boots_facade': ['0219', '0185', '0217', '0184', '0182', '0187', '0195', '0204'],
}


def _light(name, weights):
    from court_surface import _blur
    meta = json.loads((BAKE / f'{name}.meta.json').read_text(encoding='utf8'))
    light = sum(weights[g] * _blur(np.load(BAKE / f'{name}_{g}.npy').astype(float)) for g in weights)
    return meta, light.astype(np.float32)


def _frame(meta):
    """(a-coordinate fn, b-coordinate fn, a0, a1, b0, b1, face test) for a bake."""
    if meta.get('wall'):
        axis, at, a0, a1, y0, y1, facing = meta['wall']
        i = 0 if axis == 'x' else 2
        j = 2 if axis == 'x' else 0
        test = lambda P, fn: (fn[:, i] * facing > 0.7) & (np.abs(P[..., i] - at).max(1) < 40) & \
            (P[..., j].min(1) >= a0) & (P[..., j].max(1) <= a1) & (P[..., 1].max(1) <= y1)
        return (lambda p: p[..., j]), (lambda p: p[..., 1]), a0, a1, y0, y1, test
    x0, x1, z0, z1, _ = meta['region_cm']
    test = lambda P, fn: (fn[:, 1] > 0.7) & (P[..., 1].max(1) <= 30) & (P[..., 0].min(1) >= x0) & \
        (P[..., 0].max(1) <= x1) & (P[..., 2].min(1) >= z0) & (P[..., 2].max(1) <= z1)
    return (lambda p: p[..., 0]), (lambda p: p[..., 2]), x0, x1, z0, z1, test


def _crop(light, frame, lo_a, hi_a, lo_b, hi_b):
    _, _, a0, a1, b0, b1, _ = frame
    h, w = light.shape[:2]
    c0 = int(np.floor((lo_a - a0) / (a1 - a0) * w)); c1 = int(np.ceil((hi_a - a0) / (a1 - a0) * w))
    r0 = int(np.floor((lo_b - b0) / (b1 - b0) * h)); r1 = int(np.ceil((hi_b - b0) / (b1 - b0) * h))
    c0, r0 = max(c0, 0), max(r0, 0)
    c1, r1 = min(max(c1, c0 + 2), w), min(max(r1, r0 + 2), h)
    # exact world bounds of the cropped texels, so UV0 lines up with the bake
    ea0, ea1 = a0 + c0 / w * (a1 - a0), a0 + c1 / w * (a1 - a0)
    eb0, eb1 = b0 + r0 / h * (b1 - b0), b0 + r1 / h * (b1 - b0)
    return light[r0:r1, c0:c1], (ea0, ea1, eb0, eb1)


def _emit(level, extra, prefix, add_emitter, sconce_material, key, p, n, tris, uv, emission_lin, per_unit,
          albedo, normal_rough, scale, lift, peak=None):
    peak = peak or float(np.percentile(emission_lin.max(2), 99.5))
    if peak <= 1e-6:
        return None
    mat = _material(level, extra, prefix, sconce_material, key, _srgb_image(emission_lin / peak),
                    GAIN * per_unit * peak, albedo=albedo, normal_rough=normal_rough, albedo_scale=scale)
    moved = p + n * lift
    add_emitter(level, extra, prefix + key, moved * np.array([-1.0, 1.0, -1.0]), n * np.array([-1.0, 1.0, -1.0]),
                uv, tris.reshape(-1), 0.03 + 0.94 * uv, mat)
    return round(GAIN * per_unit * peak, 1)


REFLECT_HEADROOM = 0.6       # lit ground tops out at 60% of the map; streaks may reach 100%


def _skin_part(level, archive, extra, prefix, add_emitter, sconce_material, part_geometry, source, meta, light, per_unit):
    frame = _frame(meta)
    fa, fb, *_, test = frame
    model = level['Model'][source]
    part_mat = level['Material'][model['Prim'][0]['Material']]
    p, n, ix = part_geometry(source)
    uv_src = decode_attribute(archive, model, 'TEXCOORD0')[:, :2].astype(float)
    tris = ix.reshape(-1, 3)
    keep = test(p[tris], n[tris].mean(1))
    if not keep.any():
        return None
    tris = tris[keep]
    used = np.unique(tris)
    remap = -np.ones(len(p), np.int64); remap[used] = np.arange(len(used))
    p, n, uv_src, tris = p[used], n[used], uv_src[used], remap[tris]
    a, b = fa(p), fb(p)
    crop, (ea0, ea1, eb0, eb1) = _crop(light, frame, a.min(), a.max(), b.min(), b.max())
    ua, vb = (a - ea0) / (ea1 - ea0), (b - eb0) / (eb1 - eb0)
    uv = np.stack([ua, vb], 1)
    pixelmap = part_mat['Resource']['AlbedoMap']['Pixelmap']
    scale = (1.0, 1.0)
    if level['Texture'][pixelmap].get('Width', 4) > 8:            # tiled texture: keep its density
        A, *_ = np.linalg.lstsq(np.c_[a, b, np.ones(len(p))], uv_src, rcond=None)
        if abs(A[1, 0]) > abs(A[0, 0]):                           # u follows b: swap so UV0 matches
            uv = np.stack([vb, ua], 1)
            crop = crop.transpose(1, 0, 2)
            scale = (abs(A[1, 0]) * (eb1 - eb0), abs(A[0, 1]) * (ea1 - ea0))
        else:
            scale = (abs(A[0, 0]) * (ea1 - ea0), abs(A[1, 1]) * (eb1 - eb0))
    albedo = _mean_albedo(archive, level, pixelmap)
    key = 'baked_' + source.split('-')[-1]
    intensity = _emit(level, extra, prefix, add_emitter, sconce_material, key, p, n, tris, uv,
                      crop * albedo[None, None, :], per_unit, part_mat['Resource']['AlbedoMap'],
                      part_mat['Resource'].get('NormalAndRoughMap'), scale, SKIN_CM)
    return None if intensity is None else {'faces': int(len(tris)), 'intensity': intensity,
                                           'albedo_scale': [round(s, 3) for s in scale]}


def _ground_rects(x0, x1, z0, z1):
    cx0, cx1, cz0, cz1 = COURT_RECT
    return {'south': (x0, x1, z0, cz0), 'north': (x0, x1, cz1, z1),
            'west': (x0, cx0, cz0, cz1), 'east': (cx1, x1, cz0, cz1)}


def _ground_albedo(archive, level, rect, atlas):
    """Atlas texels seen through the original ground triangles over rect, sRGB uint8 (rows = z)."""
    model = level['Model'][GROUND]
    p = decode_attribute(archive, model, 'POSITION0')[:, :3].astype(float) * np.array([-1.0, 1.0, -1.0])
    uv = decode_attribute(archive, model, 'TEXCOORD0')[:, :2].astype(float)
    tris = np.frombuffer(archive.read(resolve_binary(archive, model['IndexBuffer']['Binary'])), '<u2').astype(np.int64).reshape(-1, 3)
    x0, x1, z0, z1 = rect
    w = max(2, int(round((x1 - x0) / GROUND_ALBEDO_CM))); h = max(2, int(round((z1 - z0) / GROUND_ALBEDO_CM)))
    xs = x0 + (np.arange(w) + 0.5) * (x1 - x0) / w
    zs = z0 + (np.arange(h) + 0.5) * (z1 - z0) / h
    X, Z = np.meshgrid(xs, zs)
    U = np.full(X.shape + (2,), np.nan)
    for t in tris:
        a, b, c = p[t][:, [0, 2]]
        v0, v1 = b - a, c - a
        den = v0[0] * v1[1] - v1[0] * v0[1]
        if abs(den) < 1e-9:
            continue
        dx, dz = X - a[0], Z - a[1]
        s = (dx * v1[1] - v1[0] * dz) / den
        r = (v0[0] * dz - dx * v0[1]) / den
        inside = (s >= -1e-6) & (r >= -1e-6) & (s + r <= 1 + 1e-6) & np.isnan(U[..., 0])
        if inside.any():
            ua, ub, uc = uv[t]
            U[inside] = ((1 - s - r)[inside, None] * ua + s[inside, None] * ub + r[inside, None] * uc)
    U = np.nan_to_num(U, nan=0.5)
    size = atlas.shape[0]
    iu = np.clip((U[..., 0] * size).astype(int), 0, size - 1)
    iv = np.clip((U[..., 1] * size).astype(int), 0, size - 1)
    return atlas[iv, iu]


def _wet_field(xs, zs):
    """Wetness 0 dry .. 1 standing water over the world grid xs (cols) x zs (rows)."""
    rng = np.random.default_rng(WET_SEED)
    X, Z = np.meshgrid(xs, zs)
    total = np.zeros_like(X)
    for cell, amp in ((260.0, 1.0), (90.0, 0.45), (35.0, 0.2)):
        gx0, gz0 = -2400.0, -3400.0
        nx, nz = int(4800 / cell) + 3, int(5700 / cell) + 3
        g = rng.uniform(-1, 1, (nz, nx))
        fx, fz = (X - gx0) / cell, (Z - gz0) / cell
        ix, iz = np.clip(fx.astype(int), 0, nx - 2), np.clip(fz.astype(int), 0, nz - 2)
        tx, tz = fx - ix, fz - iz
        tx, tz = tx * tx * (3 - 2 * tx), tz * tz * (3 - 2 * tz)
        total += amp * ((g[iz, ix] * (1 - tx) + g[iz, ix + 1] * tx) * (1 - tz) +
                        (g[iz + 1, ix] * (1 - tx) + g[iz + 1, ix + 1] * tx) * tz)
    cx0, cx1, cz0, cz1 = COURT_RECT
    # distance outside the court rectangle: water collects along the fence/curb
    dx = np.maximum(np.maximum(cx0 - X, X - cx1), 0)
    dz = np.maximum(np.maximum(cz0 - Z, Z - cz1), 0)
    near_fence = np.exp(-np.hypot(dx, dz) / 250.0)
    chilis = np.clip((Z - 1830.0) / 120.0, 0, 1) * (np.abs(X - 420.0) < 900)
    field = total + 0.55 * near_fence + 0.35 * chilis
    damp = np.clip((field - 0.15) / 0.35, 0, 1)
    puddle = np.clip((field - 0.62) / 0.12, 0, 1)
    return damp, puddle


def _wet_maps(rect):
    """(normal+rough RGBA image, albedo multiplier at WET_CM) for a ground rect."""
    x0, x1, z0, z1 = rect
    w = max(4, int(round((x1 - x0) / WET_CM))); h = max(4, int(round((z1 - z0) / WET_CM)))
    xs = x0 + (np.arange(w) + 0.5) * (x1 - x0) / w
    zs = z0 + (np.arange(h) + 0.5) * (z1 - z0) / h
    damp, puddle = _wet_field(xs, zs)
    rng = np.random.default_rng(WET_SEED + 1)
    grain = rng.normal(0, 1, (h, w))
    rough = DRY_ROUGH + (DAMP_ROUGH - DRY_ROUGH) * damp + (PUDDLE_ROUGH - DAMP_ROUGH) * puddle
    rough = np.clip(rough + 0.04 * grain * (1 - puddle), 0.03, 0.95)
    # dry pavement keeps a faint grain in the normal; standing water is flat
    bump = 0.06 * (1 - puddle)
    nx, ny = bump * grain, bump * np.roll(grain, 1, 1)
    norm = np.sqrt(nx ** 2 + ny ** 2 + 1)
    rgba = np.stack([0.5 + 0.5 * nx / norm, 0.5 + 0.5 * ny / norm, np.full_like(nx, 1.0), rough], 2)
    img = Image.fromarray((np.clip(rgba, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGBA')
    darken = 1 - (1 - WET_DARKEN) * np.maximum(damp * 0.6, puddle)
    return img, darken, float(puddle.mean()), float(damp.mean())


# N33: N32's puddles were there but showed no reflection (this material gets no real-time
# reflections). The reflections are painted into the emission instead: every bright source
# (Chili's letters and script, awning bulbs, festoon bulbs, boots letters, entry strips,
# A signs) mirrored in the ground as seen from a typical gameplay camera, smeared into a
# streak toward the camera as on wet asphalt, and masked by the puddles (faint on damp).
REFLECT_CAMERA = np.array([0.0, 450.0, -300.0])
STREAK_CM, STREAK_WIDTH_CM = 260.0, 16.0
REFLECT_GAIN = 2.2           # x the 99.5th percentile of the rect's lit ground
REFLECT_SOURCES = {          # overlay part -> (emitter, weight per sample)
    '0439': ('chilis_letters', 1.0), '0438': ('letter_rim', 0.6), '0083': ('gold_script', 0.5),
    '0089': ('gold_script', 0.5), '0096': ('warm_strip', 0.5), '0140': ('warm_strip', 0.5),
    '0181': ('boots_letters', 0.8), '0611': ('a_sign', 0.5), '0612': ('a_sign', 0.5),
}


def reflection_sources(part_geometry):
    """[(world xyz, linear rgb weight)] of the bright things that would mirror in water."""
    import night_scene, night_lights, chilis_storefront as cs
    out = []
    for n, (emitter, weight) in REFLECT_SOURCES.items():
        p, _, _ = part_geometry('zgc_r03:part-' + n)
        colour = np.array(night_scene.EMITTERS[emitter][0], float)
        lo, hi = p.min(0), p.max(0)
        span = hi - lo
        axis = 0 if span[0] >= span[2] else 2
        for t in np.linspace(0, 1, max(2, int(span[axis] / 18.0))):
            c = (lo + hi) / 2
            c[axis] = lo[axis] + span[axis] * t
            out.append((c, colour * weight))
    for b in night_lights.bulbs():
        out.append((np.asarray(b, float), np.array(night_lights.BULB_COLOUR) * 0.35))
    for z, y in cs.AWNING_STRINGS:
        for x in np.arange(cs.AWNING_ARMS_X[0], cs.AWNING_ARMS_X[-1], 26.0):
            out.append((np.array([x, y - 10.0, z]), np.array(cs.AWNING_BULB[0]) * 0.3))
    return out


def _reflections(sources, xs, zs, wet):
    """Painted mirror streaks over the grid, linear rgb (h, w, 3), before scaling."""
    out = np.zeros((len(zs), len(xs), 3), np.float32)
    dx_cell, dz_cell = xs[1] - xs[0], zs[1] - zs[0]
    cam = REFLECT_CAMERA
    for src, rgb in sources:
        sy = max(src[1], 1.0)
        mirror = np.array([src[0], -sy, src[2]])
        t = cam[1] / (cam[1] + sy)
        hit = cam + t * (mirror - cam)                     # where the camera sees the image on the floor
        d = np.array([cam[0] - hit[0], cam[2] - hit[2]])
        d /= max(np.hypot(*d), 1e-6)                       # streak runs toward the camera
        reach = STREAK_CM + 3 * STREAK_WIDTH_CM
        i0 = np.searchsorted(xs, hit[0] - reach); i1 = np.searchsorted(xs, hit[0] + reach)
        j0 = np.searchsorted(zs, hit[2] - reach); j1 = np.searchsorted(zs, hit[2] + reach)
        if i1 <= i0 or j1 <= j0:
            continue
        X, Z = np.meshgrid(xs[i0:i1] - hit[0], zs[j0:j1] - hit[2])
        along = X * d[0] + Z * d[1]
        across = -X * d[1] + Z * d[0]
        k = np.exp(-(across / STREAK_WIDTH_CM) ** 2) * np.where(
            along >= 0, np.exp(-along / (STREAK_CM * 0.45)), np.exp(along / 25.0))
        out[j0:j1, i0:i1] += k[..., None] * rgb[None, None, :]
    return out * wet[..., None]


def _ground(level, archive, extra, prefix, add_emitter, sconce_material, meta, light, per_unit, sources=()):
    import court_surface
    model = level['Model'][GROUND]
    part_mat = level['Material'][model['Prim'][0]['Material']]
    pixelmap = part_mat['Resource']['AlbedoMap']['Pixelmap']
    atlas, _, _ = court_surface._atlas_crop_exact(archive, level, pixelmap, (0.0, 0.0), (1.0, 1.0))
    frame = _frame(meta)
    x0, x1, z0, z1, _ = meta['region_cm']
    # keep the original ground's triangle winding (front faces)
    gp = decode_attribute(archive, model, 'POSITION0')[:, :3].astype(float) * np.array([-1.0, 1.0, -1.0])
    gt = np.frombuffer(archive.read(resolve_binary(archive, model['IndexBuffer']['Binary'])), '<u2').astype(np.int64).reshape(-1, 3)
    cr = np.cross(gp[gt[:, 1]] - gp[gt[:, 0]], gp[gt[:, 2]] - gp[gt[:, 0]])[:, 1]
    winding = np.sign(cr[np.abs(cr).argmax()])
    report = {}
    for side, rect in _ground_rects(x0, x1, z0, z1).items():
        crop, (ea0, ea1, eb0, eb1) = _crop(light, frame, *rect)
        rect = (ea0, ea1, eb0, eb1)
        srgb = _ground_albedo(archive, level, rect, atlas)
        puddles = damp = 0.0
        if WET:
            wet_img, darken, puddles, damp = _wet_maps(rect)
            dk = np.asarray(Image.fromarray((darken * 255).astype(np.uint8)).resize((srgb.shape[1], srgb.shape[0]), Image.BILINEAR), np.float32) / 255.0
            lin = (srgb / 255.0) ** 2.2 * dk[..., None]
            srgb = np.clip(lin ** (1 / 2.2) * 255 + 0.5, 0, 255).astype(np.uint8)
        small = np.asarray(Image.fromarray(srgb).resize((crop.shape[1], crop.shape[0]), Image.BOX), np.float32) / 255.0
        emission = crop * small ** 2.2
        if sources and WET:
            h, w = emission.shape[:2]
            xs = ea0 + (np.arange(w) + 0.5) * (ea1 - ea0) / w
            zs = eb0 + (np.arange(h) + 0.5) * (eb1 - eb0) / h
            damp_c, puddle_c = _wet_field(xs, zs)
            refl = _reflections(sources, xs, zs, np.maximum(puddle_c, 0.2 * damp_c))
            base = float(np.percentile(emission.max(2), 99.5))
            emission = emission + refl * (REFLECT_GAIN * base / max(float(refl.max()), 1e-6))
            fixed_peak = base / REFLECT_HEADROOM
        else:
            fixed_peak = None
        key = 'baked_ground_' + side
        import native_textures
        _, albedo_spec, _ = native_textures.encode(Image.fromarray(srgb, 'RGB'), extra)
        for name in [k for k in extra if k.endswith('.tld')]:
            extra.pop(name)
        level['Texture'][prefix + 'tex_' + key + '_ground'] = albedo_spec
        p = np.array([(ea0, 0.0, eb0), (ea1, 0.0, eb0), (ea1, 0.0, eb1), (ea0, 0.0, eb1)])
        n = np.tile([0.0, 1.0, 0.0], (4, 1))
        uv = np.array([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        tris = np.array([[0, 1, 2], [0, 2, 3]])
        if np.sign(np.cross(p[1] - p[0], p[2] - p[0])[1]) != winding:
            tris = tris[:, ::-1].copy()
        intensity = _emit(level, extra, prefix, add_emitter, sconce_material, key, p, n, tris, uv, emission, per_unit,
                          {'Pixelmap': prefix + 'tex_' + key + '_ground'}, part_mat['Resource'].get('NormalAndRoughMap'),
                          (1.0, 1.0), GROUND_LIFT_CM, peak=fixed_peak)
        report[side] = {'rect_cm': [round(v, 1) for v in rect], 'albedo': list(srgb.shape[:2]), 'intensity': intensity,
                        'puddle_fraction': round(puddles, 3), 'damp_fraction': round(damp, 3)}
    return report


def apply(level, archive, extra, prefix, add_emitter, sconce_material, part_geometry, weights, per_unit):
    report = {}
    for bake, parts in SKINS.items():
        meta, light = _light(bake, weights)
        out = {}
        for n in parts:
            r = _skin_part(level, archive, extra, prefix, add_emitter, sconce_material, part_geometry,
                           'zgc_r03:part-' + n, meta, light, per_unit)
            if r:
                out[n] = r
        if bake == 'surface_plaza':
            out['ground'] = _ground(level, archive, extra, prefix, add_emitter, sconce_material, meta, light, per_unit,
                                    reflection_sources(part_geometry))
        report[bake] = out
    return report
