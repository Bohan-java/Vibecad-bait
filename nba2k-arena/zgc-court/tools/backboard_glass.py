"""N22 backboard glass: real tempered glass instead of an invisible sheet.

The hoop lives in baskets.SCNE (not level.SCNE). Its glass uses basket_glass.fx
(premultiplied blend: SRC ONE, DEST INVSRCALPHA) with a uniform albedo of 0.054
at alpha 0.14 and roughness 0.32, so in game it reads as fully transparent with
blurry reflections.

New maps, rasterised through the glass mesh's own UVs (they are not a linear
function of position, so every triangle is painted with per-vertex attributes):
- albedo RGBA: a faint smoky green-grey body, a greener, more opaque band along
  the board edge (thick tempered glass seen at an angle), and a few faint
  smudges / ball marks around the target area above the rim
- roughness: low (crisp reflections of the lights), higher on the smudges

N30: the user wants a wooden board. WOOD = True paints the same two maps as an
opaque (alpha 255) weathered outdoor plank board: horizontal planks with grain and
per-plank tone, a white painted border and shooter's square with chipped paint,
dark end grain along the edge, matte roughness. The rasteriser carries model-space
x, y per texel, so the wood is procedural in board space, not in UV space.

Only the two Texture entries change in baskets.SCNE (exact text replacement of
their JSON objects, everything else byte-for-byte). Built from the R13
baskets.SCNE every time, so re-applying is deterministic.
"""
from __future__ import annotations

import json

import numpy as np
from PIL import Image

import native_textures
from iff_codec import decode_attribute, load_scne, resolve_binary

GLASS_MODEL = 'park_streetball_a_master@park_rucker_ext_sharedcourt@GameObjects@court_group@MAIN@basket0:glass'
ALBEDO_KEY, ROUGH_KEY = 'zgc_r10:glass_albedo', 'zgc_r10:glass_roughness'
SIZE = 512
EDGE_CM = 4.5
BODY = (34, 44, 41, 66)        # sRGB rgb + alpha (0.26)
EDGE = (52, 86, 72, 170)       # thick-glass edge
SMUDGE = (120, 122, 118)
ROUGH_BODY, ROUGH_SMUDGE = 0.06, 0.32
WOOD = False                                          # N30 wood board: the user wants glass back
# N31 dusty glass: an outdoor board that is never cleaned. Translucent but milky:
# a fine grey-beige dust film over the whole sheet (alpha ~0.55), thicker toward the
# bottom and the frame, dried rain streaks running down, palm and ball marks around
# the square, and the dust scatters reflections (high roughness).
DUSTY = True
DUST = np.array((92, 90, 82), np.float32)          # premultiplied-friendly sRGB dust film
DUST_ALPHA = 140.0
from pathlib import Path
DUST_MAP = Path(__file__).resolve().parent.parent / 'artwork' / 'backboard_dust_n32.png'
WOOD_SIZE = 1024
PLANK_CM = 13.5
WOOD_BASE = np.array((112, 80, 54), np.float32)      # sRGB, weathered brown
WOOD_GREY = np.array((128, 118, 104), np.float32)    # sun-bleached grey
PAINT = np.array((226, 224, 214), np.float32)
LINE_CM = 5.0
SQUARE = (-29.5, 29.5, 305.0, 350.0)                  # shooter's square, model x / y cm
RIM_Y = 305.0


def _noise(shape, cells, rng):
    """Smooth value noise in [-1, 1] (bilinear upsampled random grid)."""
    h, w = shape
    g = rng.uniform(-1, 1, (cells[0] + 2, cells[1] + 2)).astype(np.float32)
    yy = np.linspace(0, cells[0], h, dtype=np.float32)[:, None]
    xx = np.linspace(0, cells[1], w, dtype=np.float32)[None, :]
    y0, x0 = np.floor(yy).astype(int), np.floor(xx).astype(int)
    fy, fx = yy - y0, xx - x0
    fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
    a, b = g[y0, x0], g[y0, x0 + 1]
    c, d = g[y0 + 1, x0], g[y0 + 1, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def _dusty(x, y, edge, smudge):
    """Per-texel board-space coordinates -> (rgba, roughness) for a dusty glass sheet."""
    rng = np.random.default_rng(5150)
    h, w = x.shape
    fine = _noise((h, w), (24, 40), rng) * 0.5 + _noise((h, w), (90, 150), rng) * 0.3
    low = np.clip((330.0 - y) / 40.0, 0, 1)                         # grime settles low on the sheet
    frame = np.clip(1 - edge / 9.0, 0, 1) ** 1.3                    # and along the frame
    # rain streaks: thin vertical bands of cleaner and dirtier glass
    cols = rng.uniform(-85, 85, 46)
    widths = rng.uniform(0.4, 2.2, 46)
    strength = rng.uniform(-1, 1, 46)
    starts = rng.uniform(300, 385, 46)
    streak = np.zeros_like(x)
    for c, wd, st, y0 in zip(cols, widths, strength, starts):
        wob = c + 0.8 * np.sin(y * 0.15 + c)
        streak += st * np.exp(-((x - wob) / wd) ** 2) * np.clip((y0 - y) / 20.0, 0, 1) * np.clip((y - 290.4) / 6.0, 0, 1)
    density = 0.62 + 0.18 * fine + 0.22 * low + 0.35 * frame + 0.16 * streak + 0.35 * smudge
    if DUST_MAP.exists():
        # N32: the user's generated dust map (white = thick dust), sampled in board space
        g = np.asarray(Image.open(DUST_MAP).convert('L'), np.float32) / 255.0
        gh, gw = g.shape
        u = np.clip((x + 85.0) / 170.0, 0, 1) * (gw - 1)
        v = np.clip((385.4 - y) / 95.0, 0, 1) * (gh - 1)
        dust = g[v.astype(int), u.astype(int)]
        density = 0.95 + 1.6 * (dust - 0.465)          # mean alpha ~0.52: milky, not see-through
    density = np.clip(density, 0.35, 1.25)
    alpha = np.clip(DUST_ALPHA * density, 60, 225)
    rgb = DUST[None, None, :] * (0.9 + 0.12 * fine[..., None]) * (alpha / DUST_ALPHA)[..., None] * 0.62
    rgb = np.minimum(rgb, alpha[..., None])                          # premultiplied blend: rgb <= alpha
    rgba = np.concatenate([rgb, alpha[..., None]], 2)
    rough = np.clip(0.38 + 0.25 * (density - 0.6) + 0.1 * smudge, 0.25, 0.75)
    return rgba, rough


def _wood(x, y, edge, smudge):
    """Per-texel board-space coordinates -> (rgba uint8, roughness 0..1)."""
    rng = np.random.default_rng(4207)
    plank = np.floor((y - 290.4) / PLANK_CM).astype(int)
    planks = int(plank.max()) + 2
    tone = rng.uniform(-1, 1, planks + 2)[np.clip(plank, 0, planks)]
    shift = rng.uniform(0, 400, planks + 2)[np.clip(plank, 0, planks)]
    grey = rng.uniform(0.25, 0.75, planks + 2)[np.clip(plank, 0, planks)]
    # grain: long streaks along x, wobbling rings
    gy = (y - 290.4) % PLANK_CM
    ring = np.sin((gy * 2.3 + 1.6 * np.sin((x + shift) * 0.045) + 0.8 * np.sin((x + shift) * 0.13)) * 1.9)
    streak = np.sin((y * 9.0 + np.sin((x + shift) * 0.02) * 6.0)) * 0.5 + np.sin(y * 23.0 + x * 0.05) * 0.25
    grain = 0.55 * ring + 0.35 * streak
    base = WOOD_BASE * (1 - grey[..., None] * 0.6) + WOOD_GREY * grey[..., None] * 0.6
    knots = np.zeros_like(x)
    for kx, ky in rng.uniform((-80, 292), (80, 384), (7, 2)):
        d2 = ((x - kx) / 2.2) ** 2 + ((y - ky) / 1.1) ** 2
        knots += np.exp(-d2) * 0.5 + 0.12 * np.exp(-d2 / 9) * np.sin(np.sqrt(d2) * 3)
    rgb = base * (1 + 0.16 * tone[..., None] + 0.07 * grain[..., None] - 0.5 * knots[..., None])
    # gaps between planks
    gap = np.minimum(gy, PLANK_CM - gy)
    rgb *= (0.45 + 0.55 * np.clip(gap / 0.35, 0, 1))[..., None]
    # paint: border inside the edge and the shooter's square outline
    x0, x1, y0, y1 = SQUARE
    in_sq = np.minimum(np.minimum(x - x0, x1 - x), np.minimum(y - y0, y1 - y))
    square_line = (np.abs(in_sq) < LINE_CM / 2) | ((in_sq > -LINE_CM / 2) & (in_sq < 0))
    square_line = (in_sq > -LINE_CM) & (in_sq <= 0) & (x > x0 - LINE_CM) & (x < x1 + LINE_CM) & (y > y0 - LINE_CM) & (y < y1 + LINE_CM)
    border = (edge > 1.5) & (edge < 1.5 + LINE_CM)
    paint = (square_line | border).astype(np.float32)
    h, w = x.shape
    chip = _noise((h, w), (70, 70), rng) + 0.5 * _noise((h, w), (260, 260), rng)
    worn = np.clip((chip + 0.95) * 5, 0, 1)                       # 0 = chipped to wood (sparse)
    worn *= 1 - 0.6 * smudge                                      # ball marks wear the paint
    paint *= worn
    paint_rgb = PAINT * (0.9 + 0.08 * chip[..., None])
    rgb = rgb * (1 - paint[..., None]) + paint_rgb * paint[..., None]
    # ball marks: darker grime around the square
    rgb *= (1 - 0.35 * smudge)[..., None]
    # dark end grain / weathered edge
    rgb *= (0.55 + 0.45 * np.clip((edge - 0.3) / 1.5, 0, 1))[..., None]
    rgba = np.concatenate([np.clip(rgb, 0, 255), np.full((h, w, 1), 255, np.float32)], 2)
    rough = 0.78 - 0.12 * paint + 0.05 * grain
    return rgba, np.clip(rough, 0, 1)


def _attributes(p):
    """Per-vertex edge distance (cm) and smudge weight from model-space positions."""
    x, y = p[:, 0], p[:, 1]
    edge = np.minimum(np.minimum(85.0 - np.abs(x), y - 290.4), 385.4 - y)
    rng = np.random.default_rng(1891)
    smudge = np.zeros(len(p))
    for _ in range(14):                      # around the target square and above the rim
        cx, cy = rng.normal(0, 22), rng.normal(322, 14)
        r = rng.uniform(4, 11)
        smudge += rng.uniform(0.4, 1.0) * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (r * r)))
    return edge, np.clip(smudge, 0, 1)


def _rasterise(uv, tris, values, size):
    """Paint per-vertex values (n x k) into a size x size x k image through the UV layout."""
    out = np.zeros((size, size, values.shape[1]), np.float32)
    hit = np.zeros((size, size), bool)
    px = uv * size - 0.5
    for t in tris:
        a, b, c = px[t]
        lo = np.floor(np.minimum(np.minimum(a, b), c)).astype(int)
        hi = np.ceil(np.maximum(np.maximum(a, b), c)).astype(int)
        lo = np.clip(lo, 0, size - 1); hi = np.clip(hi, 0, size - 1)
        if (hi < lo).any():
            continue
        xs, ys = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1))
        q = np.stack([xs.ravel(), ys.ravel()], 1).astype(float)
        v0, v1 = b - a, c - a
        den = v0[0] * v1[1] - v1[0] * v0[1]
        if abs(den) < 1e-12:
            continue
        d = q - a
        s = (d[:, 0] * v1[1] - v1[0] * d[:, 1]) / den
        r = (v0[0] * d[:, 1] - d[:, 0] * v0[1]) / den
        inside = (s >= -0.02) & (r >= -0.02) & (s + r <= 1.02)
        if not inside.any():
            continue
        w = np.stack([1 - s - r, s, r], 1)[inside]
        val = w @ values[t]
        qi = q[inside].astype(int)
        out[qi[:, 1], qi[:, 0]] = val
        hit[qi[:, 1], qi[:, 0]] = True
    # bleed into unpainted texels so mips and filtering never pick up black
    for _ in range(8):
        if hit.all():
            break
        acc = np.zeros_like(out); cnt = np.zeros(hit.shape, np.float32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                h = np.roll(np.roll(hit, dy, 0), dx, 1)
                acc += np.roll(np.roll(out, dy, 0), dx, 1) * h[..., None]
                cnt += h
        fill = ~hit & (cnt > 0)
        out[fill] = acc[fill] / cnt[fill][:, None]
        hit = hit | fill
    return out


def _replace_entry(raw, key, spec):
    start = raw.index(('"' + key + '":{').encode())
    end = raw.index(b'}', start) + 1                      # texture entries hold no nested objects
    return raw[:start] + ('"' + key + '":' + json.dumps(spec, separators=(',', ':'))).encode() + raw[end:]


def build(base_raw, archive, extra):
    """base_raw: R13 baskets.SCNE bytes. Returns (new bytes, report); new DDS go into extra."""
    doc = load_scne(base_raw)['baskets']
    model = doc['Model'][GLASS_MODEL]
    p = decode_attribute(archive, model, 'POSITION0')[:, :3].astype(float)
    uv = decode_attribute(archive, model, 'TEXCOORD0')[:, :2].astype(float)
    lod0 = model['Clod']['Lods']['Lod0']
    ix = np.frombuffer(archive.read(resolve_binary(archive, model['IndexBuffer']['Binary'])), '<u2' if len(p) < 65536 else '<u4')
    tris = ix[lod0['StartIndex']:lod0['StartIndex'] + lod0['NumIndices']].astype(np.int64).reshape(-1, 3)
    edge, smudge = _attributes(p)
    edge_w = np.clip(1 - edge / EDGE_CM, 0, 1) ** 1.5
    if WOOD or DUSTY:
        maps = _rasterise(uv, tris, np.stack([p[:, 0], p[:, 1], edge, smudge], 1), WOOD_SIZE)
        rgba, rough = (_wood if WOOD else _dusty)(maps[..., 0], maps[..., 1], maps[..., 2], maps[..., 3])
        albedo_img = Image.fromarray(np.clip(rgba + 0.5, 0, 255).astype(np.uint8), 'RGBA')
        rough_img = Image.fromarray(np.repeat(np.clip(rough * 255 + 0.5, 0, 255).astype(np.uint8)[..., None], 3, 2), 'RGB')
        info = {'wood': True, 'plank_cm': PLANK_CM} if WOOD else {'dusty': True, 'dust_srgb': DUST.tolist(), 'dust_alpha': DUST_ALPHA}
        return _finish(base_raw, extra, albedo_img, rough_img, dict(info, size=WOOD_SIZE))
    maps = _rasterise(uv, tris, np.stack([edge_w, smudge], 1), SIZE)
    e, s = maps[..., 0:1], maps[..., 1:2]
    body, edge_c = np.array(BODY, np.float32), np.array(EDGE, np.float32)
    rgba = body * (1 - e) + edge_c * e
    rgba[..., :3] = rgba[..., :3] * (1 - 0.6 * s) + np.array(SMUDGE, np.float32) * 0.6 * s
    rgba[..., 3] = np.clip(rgba[..., 3] + 40 * s[..., 0], 0, 255)
    albedo_img = Image.fromarray(np.clip(rgba + 0.5, 0, 255).astype(np.uint8), 'RGBA')
    rough = (ROUGH_BODY + (ROUGH_SMUDGE - ROUGH_BODY) * s[..., 0]) * 255
    rough_img = Image.fromarray(np.repeat(np.clip(rough + 0.5, 0, 255).astype(np.uint8)[..., None], 3, 2), 'RGB')
    painted = float((maps[..., 0] > 0).mean())
    return _finish(base_raw, extra, albedo_img, rough_img, {'edge_cm': EDGE_CM, 'body_rgba': BODY, 'edge_rgba': EDGE,
                                                            'roughness_body': ROUGH_BODY, 'edge_texels_fraction': painted})


def _finish(base_raw, extra, albedo_img, rough_img, info):
    _, albedo_spec, _ = native_textures.encode(albedo_img, extra)
    _, rough_spec, _ = native_textures.encode(rough_img, extra, linear=True)
    for name in [k for k in extra if k.endswith('.tld')]:
        extra.pop(name)
    raw = _replace_entry(base_raw, ALBEDO_KEY, albedo_spec)
    raw = _replace_entry(raw, ROUGH_KEY, rough_spec)
    after = load_scne(raw)['baskets']
    before = load_scne(base_raw)['baskets']
    assert after['Texture'][ALBEDO_KEY] == albedo_spec and after['Texture'][ROUGH_KEY] == rough_spec
    for section in before:
        if section != 'Texture':
            assert after[section] == before[section], section
    assert {k: v for k, v in after['Texture'].items() if k not in (ALBEDO_KEY, ROUGH_KEY)} == \
           {k: v for k, v in before['Texture'].items() if k not in (ALBEDO_KEY, ROUGH_KEY)}
    return raw, dict(albedo=albedo_spec['Binary'], roughness=rough_spec['Binary'], **info)
