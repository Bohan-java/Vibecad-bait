"""N19 visible details: Chilis entry stone lit by the store, boots shop windows glowing.

Chilis entry stone (parts 0091-0093 stone courses, 0095 mortar; world x -128..968,
z 1893..2100, under the awning): the stone textures tile, so each part gets an
overlay whose UV0 is planar over the entry and the stone is re-tiled through the
sconce material's AlbedoScaleX/Y (fitted from the original UVs), while the
emission map (bake/bake_surface.py --region, the entry bake) uses UV0 directly.
Emission is the baked store light times the stone's mean albedo, on the same
absolute scale as the court overlay.

boots shop (parts 0201-0203, the long lower glazing facing the court at
x ~1625, z -245..1905): the court-facing faces get a dim, cool-white pharmacy
interior (ceiling light strip, shelves of coloured products) so the left of the
frame is a lit street shop instead of a black wall.
"""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

import native_textures

ENTRY_BAKE = Path(__file__).resolve().parent.parent / 'bake' / 'output' / 'surface_entry'
ENTRY_PARTS = ['zgc_r03:part-0091', 'zgc_r03:part-0092', 'zgc_r03:part-0093', 'zgc_r03:part-0095']
BOOTS_PARTS = ['zgc_r03:part-0201', 'zgc_r03:part-0202', 'zgc_r03:part-0203']
BOOTS_Z = (-245.0, 1905.0)
BOOTS_Y = (34.0, 246.0)
BOOTS_INTENSITY = 1600.0
ENTRY_GAIN = 1.6   # N24: with CONTRAST 1.6 the shared scale already lifts the entry ~15% over N19-N23          # the entry is where the store light pours out; a touch above the court's scale
RNG = np.random.default_rng(26)


def _material(level, extra, prefix, sconce_material, key, emissive_image, intensity, albedo=None,
              normal_rough=None, albedo_scale=(1.0, 1.0)):
    _, emissive, _ = native_textures.encode(emissive_image, extra)
    _, metal, _ = native_textures.encode(Image.new('RGB', (8, 8), (0, 0, 0)), extra, linear=True)
    flat = None
    if albedo is None:
        _, flat, _ = native_textures.encode(Image.new('RGB', (8, 8), (40, 40, 44)), extra)
    for name in [k for k in extra if k.endswith('.tld')]:
        extra.pop(name)
    level['Texture'][prefix + 'tex_' + key] = emissive
    level['Texture'][prefix + 'tex_' + key + '_metal'] = metal
    if flat is not None:
        level['Texture'][prefix + 'tex_' + key + '_albedo'] = flat
        albedo = {'Pixelmap': prefix + 'tex_' + key + '_albedo'}
    mat = copy.deepcopy(level['Material'][sconce_material])
    mat['Resource'] = {'AlbedoMap': copy.deepcopy(albedo),
                       'EmissiveAlbedoMap': {'Pixelmap': prefix + 'tex_' + key},
                       'MetalMap': {'Pixelmap': prefix + 'tex_' + key + '_metal'},
                       'NormalAndRoughMap': copy.deepcopy(normal_rough or mat['Resource']['NormalAndRoughMap'])}
    mat['Parameter'].update(EmissiveIntensity=float(intensity), EmissiveTint=[1.0, 1.0, 1.0], AlwaysEmit=1,
                            AlbedoScaleX=float(albedo_scale[0]), AlbedoScaleY=float(albedo_scale[1]),
                            NormalScaleX=float(albedo_scale[0]), NormalScaleY=float(albedo_scale[1]))
    level['Material'][prefix + key] = mat
    return prefix + key


def _srgb_image(linear):
    linear = np.clip(linear, 0, 1)
    srgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)
    return Image.fromarray((srgb * 255 + 0.5).astype(np.uint8), 'RGB')


def _mean_albedo(archive, level, pixelmap):
    """Linear mean colour of a BC1 albedo texture (falls back to mid grey)."""
    import court_surface
    spec = level['Texture'].get(pixelmap, {})
    if spec.get('Format') != 'BC1_UNORM':
        return np.array([0.25, 0.25, 0.25])
    img, _, _ = court_surface._atlas_region(archive, level, pixelmap, 0, 1, 0, 1, 1)
    lin = np.where(img <= 0.04045, img / 12.92, ((img + 0.055) / 1.055) ** 2.4)
    return lin.reshape(-1, 3).mean(0)


def entry_floor(level, archive, extra, prefix, add_emitter, sconce_material, part_geometry, weights, intensity_per_unit):
    import json
    from court_surface import _blur
    meta = json.loads(Path(f'{ENTRY_BAKE}.meta.json').read_text(encoding='utf8'))
    x0, x1, z0, z1, _ = meta['region_cm']
    light = sum(weights[g] * _blur(np.load(f'{ENTRY_BAKE}_{g}.npy').astype(float)) for g in weights)
    h, w = light.shape[:2]
    report = {}
    for source in ENTRY_PARTS:
        from iff_codec import decode_attribute
        model = level['Model'][source]
        part_mat = level['Material'][model['Prim'][0]['Material']]
        p, n, ix = part_geometry(source)
        uv_src = decode_attribute(archive, model, 'TEXCOORD0')[:, :2].astype(float)
        tris = ix.reshape(-1, 3)
        keep = n[tris].mean(1)[:, 1] > 0.5
        tris = tris[keep]
        used = np.unique(tris)
        remap = -np.ones(len(p), np.int64); remap[used] = np.arange(len(used))
        p, n, uv_src, tris = p[used], n[used], uv_src[used], remap[tris]
        # original texture density: uv = A [x, z, 1]
        A, *_ = np.linalg.lstsq(np.c_[p[:, 0], p[:, 2], np.ones(len(p))], uv_src, rcond=None)
        swap = abs(A[1, 0]) > abs(A[0, 0])        # u follows world z
        span_x, span_z = x1 - x0, z1 - z0
        ux = (p[:, 0] - x0) / span_x
        vz = (p[:, 2] - z0) / span_z
        uv = np.stack([vz, ux], 1) if swap else np.stack([ux, vz], 1)
        if swap:
            scale = (abs(A[1, 0]) * span_z, abs(A[0, 1]) * span_x)
        else:
            scale = (abs(A[0, 0]) * span_x, abs(A[1, 1]) * span_z)
        albedo = _mean_albedo(archive, level, part_mat['Resource']['AlbedoMap']['Pixelmap'])
        img = light * albedo[None, None, :]                      # rows = z, cols = x
        if swap:
            img = img.transpose(1, 0, 2)                          # rows = x, cols = z
        peak = float(np.percentile(img.max(2), 99.5))
        key = 'entry_' + source.split('-')[-1]
        mat = _material(level, extra, prefix, sconce_material, key, _srgb_image(img / peak),
                        ENTRY_GAIN * intensity_per_unit * peak, albedo=part_mat['Resource']['AlbedoMap'],
                        normal_rough=part_mat['Resource'].get('NormalAndRoughMap'), albedo_scale=scale)
        lifted = p + n * 1.0
        add_emitter(level, extra, prefix + key, lifted * np.array([-1.0, 1.0, -1.0]), n * np.array([-1.0, 1.0, -1.0]),
                    uv, tris.reshape(-1), 0.03 + 0.94 * np.stack([ux, vz], 1), mat)
        report[source] = {'albedo_scale': [round(s, 3) for s in scale], 'uv_follows_z': bool(swap),
                          'mean_albedo_linear': albedo.round(3).tolist(), 'intensity': round(ENTRY_GAIN * intensity_per_unit * peak, 1)}
    return report


def _boots_image(w=2048, h=256):
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    t = yy / h                                             # 0 top .. 1 bottom
    light = 0.22 + 0.5 * np.exp(-((t - 0.06) / 0.07) ** 2) + 0.25 * (1 - t)
    rgb = light[..., None] * np.array([0.88, 0.93, 1.0])[None, None, :]
    rgb[:6] = (1.0, 1.0, 0.98)                             # ceiling light strip
    img = _srgb_image(rgb).convert('RGB')
    a = np.asarray(img).copy()
    palette = np.array([(230, 80, 90), (90, 160, 220), (245, 240, 235), (120, 200, 150), (250, 200, 80), (190, 140, 220)])
    for shelf_top in (70, 120, 170):
        a[shelf_top:shelf_top + 4] = (60, 66, 76)
        x = 0
        while x < w:
            bw = int(RNG.integers(6, 16))
            if RNG.random() < 0.85:
                bh = int(RNG.integers(14, 34))
                c = palette[RNG.integers(len(palette))] * RNG.uniform(0.55, 0.9)
                a[shelf_top - bh:shelf_top, x:x + bw - 2] = c.astype(np.uint8)
            x += bw
    for x in range(0, w, 220):                              # shop fittings between bays
        a[:, x:x + 10] = (a[:, x:x + 10] * 0.35).astype(np.uint8)
    return Image.fromarray(a).filter(ImageFilter.GaussianBlur(1.2))


def boots_windows(level, archive, extra, prefix, add_emitter, sconce_material, part_geometry):
    mat = _material(level, extra, prefix, sconce_material, 'boots_windows', _boots_image(), BOOTS_INTENSITY)
    report = {}
    for source in BOOTS_PARTS:
        p, n, ix = part_geometry(source)
        tris = ix.reshape(-1, 3)
        tris = tris[n[tris].mean(1)[:, 0] < -0.5]               # faces looking at the court (-x)
        used = np.unique(tris)
        remap = -np.ones(len(p), np.int64); remap[used] = np.arange(len(used))
        p, n, tris = p[used], n[used], remap[tris]
        u = (p[:, 2] - BOOTS_Z[0]) / (BOOTS_Z[1] - BOOTS_Z[0])
        v = (BOOTS_Y[1] - p[:, 1]) / (BOOTS_Y[1] - BOOTS_Y[0])
        lifted = p + n * 1.0
        name = prefix + 'boots-window-' + source.split('-')[-1]
        add_emitter(level, extra, name, lifted * np.array([-1.0, 1.0, -1.0]), n * np.array([-1.0, 1.0, -1.0]),
                    np.stack([u, v], 1), tris.reshape(-1), 0.03 + 0.94 * np.stack([u, 1 - v], 1), mat)
        report[source] = {'faces': int(len(tris))}
    return {'intensity': BOOTS_INTENSITY, 'parts': report}
