"""N30 sky-blue rubber game ball (user reference: plain blue ball, black channels).

The level carries the gameplay ball material (ball_test_basketball:
basketball_gameplay_generic_mat, ball_CLOD.fx) with a 2048x1024 colour map: the two
hemispheres as two discs, a Wilson NBA official ball (orange leather, black
channels, Wilson / NBA / signature print). Its DDS member is stored linear (the
"Twiddled" flag does not apply to it) and range-compressed (Min/Max).

The new colour map keeps the original's layout pixel for pixel:
- channels: the black pixels connected to the black background around the discs
  (every channel runs to the disc rim; the print is not connected), kept black
- leather: blue, modulated by the original's pebble luminance
- print (Wilson, NBA, signature, badge) and its light outlines: filled with leather
The normal and roughness maps stay, so pebbles and channel grooves are unchanged.
Only the colour Texture entry changes; strip_scene restores it from R13.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import native_textures

# N30 game result: the ball did not change. No model in the level uses this material; the
# gameplay ball comes from the game's global assets. Off (strip_scene restores the R13 entry).
ENABLED = False
KEY = '%databuild_art_root%/asset_library/ball_test_basketball/texture/ball_official_color.tga'
BLUE = np.array((42, 150, 206), np.float32)          # sRGB, the reference photo's sky blue
CHANNEL = np.array((16, 17, 20), np.float32)


def _decode_bc1(data, w, h):
    bw, bh = w // 4, h // 4
    b = np.frombuffer(data[128:128 + bw * bh * 8], np.uint8).reshape(-1, 8)
    c0 = b[:, 0].astype(int) | (b[:, 1].astype(int) << 8)
    c1 = b[:, 2].astype(int) | (b[:, 3].astype(int) << 8)
    rgb = lambda c: np.stack([(c >> 11 & 31) * 255 // 31, (c >> 5 & 63) * 255 // 63, (c & 31) * 255 // 31], 1)
    r0, r1 = rgb(c0), rgb(c1)
    pal = np.stack([r0, r1, (2 * r0 + r1) // 3, (r0 + 2 * r1) // 3], 1)
    alt = np.stack([r0, r1, (r0 + r1) // 2, np.zeros_like(r0)], 1)
    pal = np.where((c0 > c1)[:, None, None], pal, alt)
    bits = np.unpackbits(b[:, 4:8], axis=1, bitorder='little').reshape(-1, 4, 4, 2)
    px = pal[np.arange(len(b))[:, None, None], bits[..., 0] + 2 * bits[..., 1]]
    return px.reshape(bh, bw, 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(h, w, 3).astype(np.uint8)


def _member(spec):
    from night_scene import _texture_archive_name
    return _texture_archive_name(spec['Binary'])


def build(level, base_spec, archive, extra):
    w, h = base_spec['Width'], base_spec['Height']
    data = archive.read(_member(base_spec))
    assert data[:4] == b'DDS ' and data[84:88] == b'DXT1'
    src = _decode_bc1(data, w, h).astype(np.float32)
    lum = src.mean(2)
    r, g, b = src[..., 0], src[..., 1], src[..., 2]
    leather = (r > 120) & (r > g + 40) & (g > b)          # orange
    dark = lum < 70
    mask = Image.fromarray(np.where(dark, 0, 255).astype(np.uint8), 'L').copy()   # writable
    # seed from every dark texel on the image border and between the two discs
    seeds = [(x, y) for x in range(0, w, 16) for y in (0, h - 1)] + [(x, y) for y in range(0, h, 16) for x in (0, w // 2 - 1, w // 2, w - 1)]
    for x, y in seeds:
        if dark[y, x] and mask.getpixel((x, y)) == 0:
            ImageDraw.floodfill(mask, (x, y), 128)
    channel = np.asarray(mask) == 128
    # pebble detail: leather luminance relative to its local leather mean
    blur = lambda a: np.asarray(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(12)), np.float32)
    wb = blur(leather * 255.0) / 255.0
    local = blur(np.where(leather, lum, 0)) / np.maximum(wb, 1e-3)
    pebble = np.where(leather & (wb > 0.2), lum / np.maximum(local, 1), 1.0)
    pebble = np.clip(pebble, 0.85, 1.15)
    # print areas: borrow pebbles from nearby leather (shifted copies) so no ghost of the print stays
    clean = leather & (wb > 0.9)
    fill = ~clean & ~channel
    for dy, dx in ((0, 61), (0, -61), (47, 0), (-47, 0), (0, 131), (0, -131), (97, 0), (-97, 0), (0, 241), (0, -241)):
        take = fill & np.roll(np.roll(clean, dy, 0), dx, 1)
        pebble[take] = np.roll(np.roll(pebble, dy, 0), dx, 1)[take]
        fill &= ~take
    pebble[fill] = 1.0
    out = BLUE[None, None, :] * pebble[..., None]
    # soften the channel edge one texel so it does not alias
    ch = np.asarray(Image.fromarray((channel * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.7)), np.float32) / 255
    out = out * (1 - ch[..., None]) + CHANNEL[None, None, :] * ch[..., None]
    img = Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), 'RGB')
    _, spec, _ = native_textures.encode(img, extra)
    for name in [k for k in extra if k.endswith('.tld')]:
        extra.pop(name)
    level['Texture'][KEY] = spec
    return {'colour_srgb': BLUE.tolist(), 'channel_texels': float(channel.mean()),
            'print_texels_filled': float((~leather & ~channel).mean()), 'size': [w, h], 'preview': img}
