"""N18 court surface light: the Blender surface bake (bake/bake_surface.py) on the court floor.

LDIAG2/3 (2026-10-06) showed, on lightmapped simplepbr receivers:
- our own BC4 lightmap is sampled through UV7 and scales the surface lighting
  down (it cannot brighten: Min/Max did not change anything);
- the sconce textured emission shows coloured patterns on the floor
  (EmissiveIntensity ~2000 reads as a soft lamp pool).

So the court model zgc_r03:part-0772 (one 2324 x 3666 cm sheet, unique UV0 in
the r03 atlas) gets a copy 0.3 cm above it with the sconce material:
- AlbedoMap / NormalAndRoughMap: the court's own (same UV0, so it matches)
- EmissiveAlbedoMap: court albedo x baked night light (A signs, Chilis, boots,
  floodlight with the probe-calibrated group weights), shadows included
- UV7 = UV0 and a BC4 lightmap = ambient occlusion from the bake, so fence
  bases, chairs and the hoop ground the scene
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import native_textures
from iff_codec import decode_attribute, decode_normals, resolve_binary

COURT = 'zgc_r03:part-0772'
BAKE = Path(__file__).resolve().parent.parent / 'bake' / 'output' / 'surface'
X_HALF_CM, Z_HALF_CM = 1162.0, 1833.0
EMISSION_SIZE = 2048
LIGHTMAP_SIZE = 1024
LIFT_CM = 0.8   # N29: 0.3 cm could z-fight at a distance
PEAK_EMISSION = 520.0       # N25: -20% more so white paint stops clipping (N24 650)
PEAK_EMISSION_N19 = 1000.0      # EmissiveIntensity reached by the brightest 0.2% of the lit floor (N18 1400 read as dusk)
CONTRAST = 1.6             # gamma on the normalised light: dim falloff drops faster, pools keep their peak
AO_BASE = 0.55              # N25: darker unlit floor so the pools stand out (LDIAG2: q ~0.84 = untouched floor)
AO_FLOOR = 0.25


def _bc1_decode(blocks):
    """blocks: (n, 8) uint8 -> (n, 16, 3) float sRGB 0..1 (opaque BC1)."""
    c = blocks[:, :4].view('<u2').astype(np.int32)
    def rgb(v):
        return np.stack([(v >> 11) & 31, (v >> 5) & 63, v & 31], -1) / np.array([31.0, 63.0, 31.0])
    c0, c1 = rgb(c[:, 0]), rgb(c[:, 1])
    four = (c[:, 0] > c[:, 1])[:, None]
    p2 = np.where(four, (2 * c0 + c1) / 3, (c0 + c1) / 2)
    p3 = np.where(four, (c0 + 2 * c1) / 3, 0.0)
    palette = np.stack([c0, c1, p2, p3], 1)                         # n, 4, 3
    bits = blocks[:, 4:8].copy().view('<u4')[:, 0]
    index = (bits[:, None] >> (2 * np.arange(16, dtype=np.uint32))) & 3
    return np.take_along_axis(palette, index[:, :, None].astype(np.int64).repeat(3, 2), 1)


def _atlas_region(archive, level, pixelmap, u0, u1, v0, v1, step):
    """Decode the BC1 atlas over [u0,u1) x [v0,v1) and box-reduce by `step` texels."""
    spec = level['Texture'][pixelmap]
    from night_scene import _texture_archive_name
    data = archive.read(_texture_archive_name(spec['Binary']))
    assert data[84:88] == b'DXT1'
    w = spec['Width']
    bx0, bx1 = int(u0 * w) // 4, int(np.ceil(u1 * w / 4))
    by0, by1 = int(v0 * w) // 4, int(np.ceil(v1 * w / 4))
    rows = []
    for by in range(by0, by1):
        start = 128 + (by * (w // 4) + bx0) * 8
        blocks = np.frombuffer(data[start:start + (bx1 - bx0) * 8], np.uint8).reshape(-1, 8)
        px = _bc1_decode(blocks).reshape(-1, 4, 4, 3).transpose(1, 0, 2, 3).reshape(4, -1, 3)
        rows.append(px)
    img = np.concatenate(rows, 0)                                     # texels, rows = v
    h, wd = img.shape[0] // step * step, img.shape[1] // step * step
    img = img[:h, :wd].reshape(h // step, step, wd // step, step, 3).mean((1, 3))
    return img, bx0 * 4 // step, by0 * 4 // step


def _barycentric_world(uv, pos, ix, uv_grid):
    """World xz for every UV grid point inside a court triangle; NaN elsewhere."""
    out = np.full(uv_grid.shape[:-1] + (2,), np.nan)
    flat = uv_grid.reshape(-1, 2)
    res = out.reshape(-1, 2)
    for t in ix.reshape(-1, 3):
        a, b, c = uv[t]
        v0, v1, p = b - a, c - a, flat - a
        den = v0[0] * v1[1] - v1[0] * v0[1]
        if abs(den) < 1e-12:
            continue
        s = (p[:, 0] * v1[1] - v1[0] * p[:, 1]) / den
        r = (v0[0] * p[:, 1] - p[:, 0] * v0[1]) / den
        inside = (s >= -1e-6) & (r >= -1e-6) & (s + r <= 1 + 1e-6)
        wa, wb, wc = pos[t][:, [0, 2]]
        res[inside] = (wa + s[inside, None] * (wb - wa) + r[inside, None] * (wc - wa))
    return out


def _sample(img, x_cm, z_cm):
    """Bilinear sample of a bake image (rows along z, columns along x)."""
    h, w = img.shape[:2]
    fx = np.clip((x_cm + X_HALF_CM) / (2 * X_HALF_CM) * w - 0.5, 0, w - 1.001)
    fz = np.clip((z_cm + Z_HALF_CM) / (2 * Z_HALF_CM) * h - 0.5, 0, h - 1.001)
    x0, z0 = fx.astype(int), fz.astype(int)
    tx, tz = fx - x0, fz - z0
    if img.ndim == 3:
        tx, tz = tx[..., None], tz[..., None]
    return ((img[z0, x0] * (1 - tx) + img[z0, x0 + 1] * tx) * (1 - tz) +
            (img[z0 + 1, x0] * (1 - tx) + img[z0 + 1, x0 + 1] * tx) * tz)


def _blur(img, sigma=1.0):
    k = np.exp(-0.5 * (np.arange(-3, 4) / sigma) ** 2); k /= k.sum()
    for axis in (0, 1):
        img = sum(np.roll(img, s, axis) * w for s, w in zip(range(-3, 4), k))
    return img


def _bc4_dds(header, image):
    """image: (n, n) 0..255 -> DX10 BC4 DDS with 2 mips, header cloned from the lamp lightmap."""
    from lightmap_diag2 import bc4_encode
    n = image.shape[0]
    mip1 = image.reshape(n // 2, 2, n // 2, 2).mean((1, 3))
    payload = bc4_encode(image) + bc4_encode(mip1)
    h = bytearray(header)
    h[12:16] = n.to_bytes(4, 'little'); h[16:20] = n.to_bytes(4, 'little')
    h[20:24] = (n * n // 2).to_bytes(4, 'little')
    return bytes(h) + payload, len(payload)


# N20 surface character. Outdoor rubber courts are not a clean print: granules, dust at
# the fence, sneaker scuffs where play concentrates, faded paint and old water marks.
ALBEDO_SIZE = (4096, 2048)        # (u, v) texels over the court only (u follows world -z, v world +x)
EMISSION_SIZE_UV = (2048, 1024)
DETAIL_TILE_CM = 45.0             # rubber granule normal/roughness tile
HOOP_Z_CM = 1270.0
RNG = np.random.default_rng(2026)


def _noise(shape, cells, rng, octaves=4):
    """Smooth value noise in [-1, 1] (sum of bicubic-upsampled random grids)."""
    h, w = shape
    out = np.zeros(shape, np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        cw, ch = max(2, int(cells * 2 ** o * w / max(h, w))), max(2, int(cells * 2 ** o * h / max(h, w)))
        grid = Image.fromarray(rng.random((ch, cw)).astype(np.float32), 'F')
        out += amp * (np.asarray(grid.resize((w, h), Image.BICUBIC)) * 2 - 1)
        total += amp
        amp *= 0.5
    return out / total


def _atlas_crop_exact(archive, level, pixelmap, lo, hi):
    """The atlas texels covering [lo, hi] in UV, block aligned and NOT resampled (N20 resampled
    to 4096x2048 and the floor went soft). Returns uint8 (rows = v) and the exact UV bounds."""
    spec = level['Texture'][pixelmap]
    from night_scene import _texture_archive_name
    data = archive.read(_texture_archive_name(spec['Binary']))
    assert data[84:88] == b'DXT1'
    w = spec['Width']
    bx0, bx1 = int(lo[0] * w) // 4, int(np.ceil(hi[0] * w / 4))
    by0, by1 = int(lo[1] * w) // 4, int(np.ceil(hi[1] * w / 4))
    out = np.empty(((by1 - by0) * 4, (bx1 - bx0) * 4, 3), np.uint8)
    for k, by in enumerate(range(by0, by1)):
        start = 128 + (by * (w // 4) + bx0) * 8
        blocks = np.frombuffer(data[start:start + (bx1 - bx0) * 8], np.uint8).reshape(-1, 8)
        px = _bc1_decode(blocks).reshape(-1, 4, 4, 3).transpose(1, 0, 2, 3).reshape(4, -1, 3)
        out[k * 4:k * 4 + 4] = (px * 255 + 0.5).astype(np.uint8)
    return out, np.array([bx0 * 4 / w, by0 * 4 / w]), np.array([bx1 * 4 / w, by1 * 4 / w])


def _wear(x, z, albedo_lin):
    """Linear albedo with outdoor wear. x, z: world cm per texel."""
    h, w = x.shape
    lum = albedo_lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    # play traffic: keys under both hoops, top of the arcs, centre circle
    traffic = np.zeros_like(x)
    for hz in (HOOP_Z_CM, -HOOP_Z_CM):
        d_hoop = np.hypot(x, z - hz)
        traffic += np.exp(-(d_hoop / 420) ** 2) + 0.45 * np.exp(-((d_hoop - 700) / 160) ** 2) * (np.abs(z) < 1300)
    traffic += 0.5 * np.exp(-(np.hypot(x, z) / 350) ** 2)
    traffic = np.clip(traffic, 0, 1).astype(np.float32)
    # dust collects along the fence line and in the corners, away from play
    edge = np.minimum(np.minimum(906 - np.abs(x), 1433 - np.abs(z)), 400)
    edge = np.clip(edge, 0, None)
    dust = np.exp(-edge / 90) * 0.22 + (1 - traffic) * 0.04
    dust *= 0.7 + 0.3 * (_noise((h, w), 6, RNG) * 0.5 + 0.5)
    granule = _noise((h, w), 900, RNG, octaves=2) * 0.05
    blotch = np.clip(_noise((h, w), 10, RNG, octaves=3) - 0.35, 0, None) * 0.35     # old water marks
    out = albedo_lin * (1 + granule.astype(np.float32))[..., None]
    out *= (1 - dust - blotch * 0.25)[..., None]
    # faded paint: bright paint loses some saturation and brightness where play is heavy
    paint = np.clip((lum - 0.12) / 0.3, 0, 1)
    fleck = np.clip(_noise((h, w), 220, RNG, octaves=2) * 0.5 + 0.5, 0, 1) ** 3
    fade = paint * traffic * (0.10 + 0.35 * fleck)
    grey = (out @ np.array([0.2126, 0.7152, 0.0722], np.float32))[..., None] * np.array([0.92, 0.92, 0.95], np.float32)
    out = out * (1 - fade[..., None]) + grey * 0.75 * fade[..., None]
    return np.clip(out, 0, 1).astype(np.float32), traffic


def _scuffs(img, x, z, traffic, clusters=900):
    """Soft dark rubber smears: clusters of short overlapping strokes where players plant and turn,
    plus faint round dusty ball marks; denser where play is heavy."""
    h, w = x.shape
    layer = Image.new('L', (w, h), 0)
    d = ImageDraw.Draw(layer)
    flat_t = traffic.reshape(-1) ** 2
    prob = flat_t / flat_t.sum()
    px_per_cm = w / max(1.0, float(np.ptp(z)))
    for i in RNG.choice(flat_t.size, size=clusters, p=prob):
        r0, c0 = divmod(int(i), w)
        heading = RNG.uniform(0, np.pi)
        for _ in range(int(RNG.integers(2, 7))):
            r = r0 + RNG.normal(0, 6) * px_per_cm
            c = c0 + RNG.normal(0, 6) * px_per_cm
            ang = heading + RNG.normal(0, 0.5)
            length = RNG.uniform(6, 24) * px_per_cm
            dx, dy = np.cos(ang) * length / 2, np.sin(ang) * length / 2
            d.line([c - dx, r - dy, c + dx, r + dy], fill=int(RNG.uniform(18, 55)),
                   width=max(2, int(RNG.uniform(1.5, 4.0) * px_per_cm)))
    for i in RNG.choice(flat_t.size, size=160, p=prob):
        r, c = divmod(int(i), w)
        rad = RNG.uniform(8, 12) * px_per_cm
        d.ellipse([c - rad, r - rad, c + rad, r + rad], fill=int(RNG.uniform(8, 20)))
    layer = np.asarray(layer.filter(ImageFilter.GaussianBlur(2.2))).astype(np.float32) / 255
    return img * (1 - 0.6 * layer[..., None])


def _detail_normal_rough(size=512):
    """Tileable rubber granule normal (RG) + roughness (A), neutral B, as an RGBA image."""
    rng = np.random.default_rng(7)
    height = np.zeros((size, size))
    for cells, amp in ((size // 3, 1.0), (size // 8, 0.5), (size // 32, 0.35)):
        g = rng.random((cells, cells))
        g = np.tile(g, (3, 3))
        up = np.asarray(Image.fromarray(g.astype(np.float32), 'F').resize((size * 3, size * 3), Image.BICUBIC))
        height += amp * up[size:2 * size, size:2 * size]
    gx = (np.roll(height, -1, 1) - np.roll(height, 1, 1)) * 0.5
    gy = (np.roll(height, -1, 0) - np.roll(height, 1, 0)) * 0.5
    strength = 2.2
    nx, ny = -gx * strength, -gy * strength
    norm = np.sqrt(nx ** 2 + ny ** 2 + 1)
    rgba = np.zeros((size, size, 4))
    rgba[..., 0] = 0.5 + 0.5 * nx / norm
    rgba[..., 1] = 0.5 + 0.5 * ny / norm
    rough = 0.9 + 0.06 * (height - height.mean()) / (height.std() + 1e-9) * 0.5
    rgba[..., 3] = np.clip(rough, 0.82, 0.98)
    return Image.fromarray((rgba * 255 + 0.5).astype(np.uint8), 'RGBA')


def _to_lin(srgb):
    srgb = srgb.astype(np.float32)
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4).astype(np.float32)


def _to_srgb_u8(lin):
    lin = np.clip(lin, 0, 1).astype(np.float32)
    s = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return (s * 255 + 0.5).astype(np.uint8)


def apply(level, archive, extra, prefix, add_emitter, sconce_material, lamp_object, weights):
    from night_scene import _texture_archive_name
    model = level['Model'][COURT]
    floor_mat = level['Material'][model['Prim'][0]['Material']]
    pos = decode_attribute(archive, model, 'POSITION0')[:, :3].astype(float) * np.array([-1.0, 1.0, -1.0])
    nrm = decode_normals(decode_attribute(archive, model, 'TANGENTFRAME0')) * np.array([-1.0, 1.0, -1.0])
    uv = decode_attribute(archive, model, 'TEXCOORD0')[:, :2].astype(float)
    ix = np.frombuffer(archive.read(resolve_binary(archive, model['IndexBuffer']['Binary'])), '<u2').astype(np.int64)
    crop, lo, hi = _atlas_crop_exact(archive, level, floor_mat['Resource']['AlbedoMap']['Pixelmap'], uv.min(0), uv.max(0))
    uvn = (uv - lo) / (hi - lo)                                   # court-only UV, texel-exact with the atlas crop
    A_uv, *_ = np.linalg.lstsq(np.c_[uv, np.ones(len(uv))], pos[:, [0, 2]], rcond=None)

    def world_grid(w, h):
        gu, gv = (np.arange(w) + 0.5) / w, (np.arange(h) + 0.5) / h
        grid = lo + np.stack(np.meshgrid(gu, gv), -1) * (hi - lo)
        xz = _barycentric_world(uv, pos, ix, grid)
        # the sheet is a rectangle; fill rare edge misses from the nearest row/column
        bad = np.isnan(xz[..., 0])
        if bad.any():
            A, *_ = np.linalg.lstsq(np.c_[uv, np.ones(len(uv))], pos[:, [0, 2]], rcond=None)
            xz[bad] = np.c_[grid[bad], np.ones(int(bad.sum()))] @ A
        return xz[..., 0], xz[..., 1]

    # albedo with wear, at the atlas' own resolution (affine texel -> world is exact enough for wear)
    ah, aw = crop.shape[:2]
    gu = (lo[0] + (np.arange(aw, dtype=np.float32) + 0.5) / aw * (hi[0] - lo[0]))
    gv = (lo[1] + (np.arange(ah, dtype=np.float32) + 0.5) / ah * (hi[1] - lo[1]))
    U, V = np.meshgrid(gu, gv)
    x = (U * A_uv[0, 0] + V * A_uv[1, 0] + A_uv[2, 0]).astype(np.float32)
    z = (U * A_uv[0, 1] + V * A_uv[1, 1] + A_uv[2, 1]).astype(np.float32)
    del U, V
    worn_lin, traffic = _wear(x, z, _to_lin(crop / 255.0))
    worn = _scuffs(_to_srgb_u8(worn_lin).astype(np.float32) / 255, x, z, traffic)
    del worn_lin, x, z, traffic
    worn_u8 = (np.clip(worn, 0, 1) * 255 + 0.5).astype(np.uint8)
    del worn
    _, albedo_tex, _ = native_textures.encode(Image.fromarray(worn_u8, 'RGB'), extra)

    # emission = worn albedo x baked light
    light = sum(weights[g] * _blur(np.load(f'{BAKE}_{g}.npy').astype(float)) for g in weights)
    ew, eh = (aw // 2) // 4 * 4, (ah // 2) // 4 * 4               # emission at half the atlas density
    ex, ez = world_grid(ew, eh)
    lit = _sample(light, ex, ez)
    peak = float(np.percentile(lit.max(2), 99.8))
    lit = peak * (np.clip(lit / peak, 0, None) ** CONTRAST)
    alb_small = _to_lin(np.asarray(Image.fromarray(worn_u8).resize((ew, eh), Image.BOX)) / 255.0)
    del worn_u8
    emission = alb_small * lit
    scale = float(np.percentile(emission.max(2), 99.8))       # before the far-half lift: the near half keeps its level
    from night_scene import far_half_gain
    emission = np.clip(emission * far_half_gain(ez)[..., None] / scale, 0, 1)
    srgb = np.where(emission <= 0.0031308, emission * 12.92, 1.055 * emission ** (1 / 2.4) - 0.055)
    _, emissive, _ = native_textures.encode(Image.fromarray((srgb * 255 + 0.5).astype(np.uint8), 'RGB'), extra)
    _, metal, _ = native_textures.encode(Image.new('RGB', (8, 8), (0, 0, 0)), extra, linear=True)
    _, detail, _ = native_textures.encode(_detail_normal_rough(), extra, linear=True)
    for name in [k for k in extra if k.endswith('.tld')]:
        extra.pop(name)
    level['Texture'][prefix + 'tex_court_albedo'] = albedo_tex
    level['Texture'][prefix + 'tex_court_light'] = emissive
    level['Texture'][prefix + 'tex_court_metal'] = metal
    level['Texture'][prefix + 'tex_court_detail'] = detail
    span_u_cm, span_v_cm = float(np.ptp(pos[:, 2])), float(np.ptp(pos[:, 0]))   # u follows world z, v world x
    tiles = (span_u_cm / DETAIL_TILE_CM, span_v_cm / DETAIL_TILE_CM)
    mat = copy.deepcopy(level['Material'][sconce_material])
    mat['Resource'] = {'AlbedoMap': {'Pixelmap': prefix + 'tex_court_albedo'},
                       'EmissiveAlbedoMap': {'Pixelmap': prefix + 'tex_court_light'},
                       'MetalMap': {'Pixelmap': prefix + 'tex_court_metal'},
                       'NormalAndRoughMap': {'Pixelmap': prefix + 'tex_court_detail'}}
    mat['Parameter'].update(EmissiveIntensity=PEAK_EMISSION, EmissiveTint=[1.0, 1.0, 1.0], AlwaysEmit=1,
                            NormalScaleX=tiles[0], NormalScaleY=tiles[1])
    level['Material'][prefix + 'court_light'] = mat

    # occlusion lightmap through UV7 = court UV
    m = LIGHTMAP_SIZE
    ox, oz = world_grid(m, m)
    occ = AO_BASE * np.clip(_sample(ao_map(), ox, oz), AO_FLOOR, 1.0)
    lamp_tex = level['Texture'][lamp_object]
    lamp_dds = archive.read(_texture_archive_name(lamp_tex['Binary']))
    dds, size = _bc4_dds(lamp_dds[:148], occ * 255.0)
    stem = 'zgc_n18_court_occlusion.' + hashlib.sha256(dds).hexdigest()[:16]
    extra[stem + '.dds'] = dds

    name = prefix + 'court-light'
    lifted = pos + nrm * LIFT_CM
    add_emitter(level, extra, name, lifted * np.array([-1.0, 1.0, -1.0]), nrm * np.array([-1.0, 1.0, -1.0]),
                uvn, ix, uvn.copy(), prefix + 'court_light')
    spec = copy.deepcopy(lamp_tex)
    spec.update(Width=m, Height=m, PixelDataSize=size, Binary=stem + '.tld')
    level['Texture'][name] = spec
    return {'model': COURT, 'albedo': [aw, ah], 'emission_texture': [ew, eh], 'lightmap': m,
            'peak_emissive_intensity': PEAK_EMISSION, 'emission_scale_linear': scale, 'weights': weights,
            'lift_cm': LIFT_CM, 'uv': 'court-only (original atlas UV normalised to [0,1]); UV7 the same',
            'detail_tile_cm': DETAIL_TILE_CM, 'ao_base': AO_BASE}


def ao_map():
    return _blur(np.load(f'{BAKE}_ao.npy').astype(float), 1.5)
