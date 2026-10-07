"""LDIAG2: combined in-game test of the two surface-lighting routes
(docs/lightmap-research/REPORT_ZH.md, reimplemented with the project tools).

Five 1.2 m floor tiles in a row across the middle of the -Z half court
(world z = -700, x = -264 .. 264, left to right as +X), 0.3 cm above the floor:

  A1  sconce textured-emission material, EmissiveAlbedoMap = warm pool, dark
      diagonal bar and R/G/B corner marks (route A: coloured light on the floor)
  B0  lamp material with emission off, grey albedo, the lamp's own BC4 lightmap
      (control: what a lightmapped receiver looks like)
  B1  same receiver, our own BC4 lightmap: a big "F" and a gradient strip
  B2  same as B1 with the BC4 values inverted (q -> 1 - q)
  B3  same BC4 as B1, only UV7 mirrored in U

Every tile is bound like the LDIAG1 emitters (lamp UserData, same-name
level.Texture, independent UV7, Duv7). The BC4 tiles use a standard DX10 BC4
DDS with the lamp DDS header (64x64, 2 mips, linear block order: the lamp's own
DDS decodes to a coherent lightmap in that order) and the lamp descriptor's
Min/Max/Twiddled/CompressionMethod.

LDIAG2 game result (2026-10-06): B1/B2 show the F with opposite contrast and
B3 is mirrored, so the game samples our BC4 through UV7; the dark strokes are
nearly black, so the lightmap scales the surface lighting and CAN darken it.
The player indicator stays visible on the tiles. A1 showed no pattern: emission
intensity 8 is far below the thousands other emitters use.

LDIAG3 (this version) answers the two open questions with one row of six tiles:
  E1 E2 E3   the A1 emission pattern at EmissiveIntensity 200 / 2000 / 20000
  M1 M2 M3   the B1 "F" lightmap with Max.r = native 1.13 / 3.0 / 8.0
             (same DDS; brighter M2/M3 means Min/Max rescale the lightmap and
             it can brighten the floor, not only darken it)

Reading the LDIAG2 result: B1 and B2 showing the F with opposite contrast proves the
game samples our BC4; B3 mirrored proves it is read through UV7. A1 showing the
pattern proves route A works on the floor. Standing on a tile shows whether a
0.3 cm floor overlay hides the player indicator.
"""
from __future__ import annotations

import copy
import hashlib

import numpy as np
from PIL import Image, ImageDraw

import native_textures

TILE_CM = 120.0
PITCH_CM = 132.0
ROW_Z_CM = -700.0
LIFT_CM = 0.3
TILES = ['E1', 'E2', 'E3', 'M1', 'M2', 'M3']
EMISSION = {'E1': 200.0, 'E2': 2000.0, 'E3': 20000.0}
MAX_R = {'M1': None, 'M2': 3.0, 'M3': 8.0}   # None keeps the lamp descriptor's Max.r
GREY = [0.5, 0.5, 0.5]


def _bc4_block(values):
    """values: 16 floats in 0..255 (row-major 4x4) -> 8-byte BC4 block (8-value mode)."""
    hi, lo = int(round(values.max())), int(round(values.min()))
    if hi == lo:
        return bytes([hi, lo]) + bytes(6)
    palette = np.array([hi, lo] + [((7 - i) * hi + i * lo) / 7 for i in range(1, 7)])
    index = np.abs(values[:, None] - palette[None, :]).argmin(1)
    bits = 0
    for t, k in enumerate(index):
        bits |= int(k) << (3 * t)
    return bytes([hi, lo]) + bits.to_bytes(6, 'little')


def bc4_encode(image):
    """image: (h, w) float 0..255 -> linear BC4 blocks, row by row."""
    h, w = image.shape
    out = bytearray()
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            out += _bc4_block(image[by:by + 4, bx:bx + 4].reshape(16))
    return bytes(out)


def bc4_decode(data, w, h):
    out = np.zeros((h, w))
    for k in range(len(data) // 8):
        block = data[k * 8:k * 8 + 8]
        e0, e1 = block[0], block[1]
        if e0 > e1:
            palette = [e0, e1] + [((7 - i) * e0 + i * e1) / 7 for i in range(1, 7)]
        else:
            palette = [e0, e1] + [((5 - i) * e0 + i * e1) / 5 for i in range(1, 5)] + [0, 255]
        bits = int.from_bytes(block[2:8], 'little')
        by, bx = divmod(k, w // 4)
        for t in range(16):
            out[by * 4 + t // 4, bx * 4 + t % 4] = palette[(bits >> (3 * t)) & 7]
    return out


def lightmap_pattern():
    """64x64 asymmetric test lightmap: light background, dark "F", gradient strip at the bottom rows."""
    img = Image.new('L', (64, 64), 215)
    draw = ImageDraw.Draw(img)
    draw.rectangle([14, 8, 22, 46], fill=20)      # F stem
    draw.rectangle([14, 8, 46, 15], fill=20)      # top bar
    draw.rectangle([14, 24, 38, 30], fill=20)     # middle bar
    a = np.asarray(img, float).copy()
    a[52:62, 4:60] = np.linspace(0, 255, 56)[None, :]   # 0 -> 1 ramp along U
    return a


def emission_pattern(size=256):
    """RGB pattern: warm pool off-centre, dark diagonal bar, R/G/B corner marks (no mark in the 4th corner)."""
    y, x = np.mgrid[0:size, 0:size] / (size - 1)
    pool = np.exp(-(((x - 0.38) / 0.26) ** 2 + ((y - 0.42) / 0.3) ** 2))
    rgb = np.stack([pool * 1.0, pool * 0.55, pool * 0.2], -1)
    bar = np.abs((x - y) - 0.12) < 0.05
    rgb[bar] = 0.0
    m = int(size * 0.14)
    rgb[:m, :m] = (1.0, 0.0, 0.0)
    rgb[:m, -m:] = (0.0, 1.0, 0.0)
    rgb[-m:, :m] = (0.0, 0.0, 1.0)
    return Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), 'RGB')


def _quad(cx):
    """World-space tile, normal up, CCW seen from above; returns positions, normals, uv0, indices."""
    h = TILE_CM / 2
    p = np.array([[cx - h, LIFT_CM, ROW_Z_CM - h], [cx + h, LIFT_CM, ROW_Z_CM - h],
                  [cx + h, LIFT_CM, ROW_Z_CM + h], [cx - h, LIFT_CM, ROW_Z_CM + h]])
    n = np.tile([0.0, 1.0, 0.0], (4, 1))
    uv = np.array([[0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]])
    tri = [(0, 2, 1), (0, 3, 2)]
    if np.dot(np.cross(p[tri[0][1]] - p[tri[0][0]], p[tri[0][2]] - p[tri[0][0]]), n[0]) < 0:
        tri = [(0, 1, 2), (0, 2, 3)]
    return p, n, uv, np.array([i for t in tri for i in t])


def add_tiles(level, archive, extra, prefix, add_emitter, lamp_material, lamp_object, sconce_material):
    world = lambda a: a * np.array([-1.0, 1.0, -1.0])   # world <-> model (180 degree object matrix)
    lamp_tex = level['Texture'][lamp_object]
    from night_scene import _texture_archive_name
    lamp_dds = archive.read(_texture_archive_name(lamp_tex['Binary']))
    assert lamp_dds[:4] == b'DDS ' and lamp_dds[84:88] == b'DX10' and len(lamp_dds) == 148 + 2560
    header = lamp_dds[:148]

    receiver = copy.deepcopy(level['Material'][lamp_material])
    receiver['Parameter'].update(DefaultAlbedo=GREY, EmissiveDefaultAlbedo=[0.0, 0.0, 0.0], EmissiveIntensity=0.0)
    level['Material'][prefix + 'ldiag2_receiver'] = receiver

    _, pattern_tex, _ = native_textures.encode(emission_pattern(), extra)
    _, grey_tex, _ = native_textures.encode(Image.new('RGB', (8, 8), (128, 128, 128)), extra)
    _, metal_tex, _ = native_textures.encode(Image.new('RGB', (8, 8), (10, 10, 10)), extra, linear=True)
    for name in [k for k in extra if k.endswith('.tld')]:
        extra.pop(name)
    level['Texture'][prefix + 'ldiag2_tex_pattern'] = pattern_tex
    level['Texture'][prefix + 'ldiag2_tex_grey'] = grey_tex
    level['Texture'][prefix + 'ldiag2_tex_metal'] = metal_tex
    for tile, intensity in EMISSION.items():
        glow = copy.deepcopy(level['Material'][sconce_material])
        glow['Resource'] = {'AlbedoMap': {'Pixelmap': prefix + 'ldiag2_tex_grey'},
                            'EmissiveAlbedoMap': {'Pixelmap': prefix + 'ldiag2_tex_pattern'},
                            'MetalMap': {'Pixelmap': prefix + 'ldiag2_tex_metal'},
                            'NormalAndRoughMap': copy.deepcopy(glow['Resource']['NormalAndRoughMap'])}
        glow['Parameter'].update(EmissiveIntensity=intensity, EmissiveTint=[1.0, 1.0, 1.0], AlwaysEmit=1)
        level['Material'][prefix + 'ldiag3_glow_' + tile.lower()] = glow

    pattern = lightmap_pattern()
    report = {}
    for k, tile in enumerate(TILES):
        cx = (k - (len(TILES) - 1) / 2) * PITCH_CM
        p, n, uv0, ix = _quad(cx)
        uv7 = 0.03 + 0.94 * uv0
        name = prefix + 'ldiag3-' + tile
        material = prefix + ('ldiag3_glow_' + tile.lower() if tile in EMISSION else 'ldiag2_receiver')
        add_emitter(level, extra, name, world(p), world(n), uv0, ix, uv7, material)
        entry = {'world_centre_cm': [cx, LIFT_CM, ROW_Z_CM], 'material': material}
        if tile in MAX_R:
            img = pattern
            mip1 = img.reshape(32, 2, 32, 2).mean((1, 3))
            payload = bc4_encode(img) + bc4_encode(mip1)
            assert len(payload) == lamp_tex['PixelDataSize'] == 2560
            assert np.abs(bc4_decode(payload[:2048], 64, 64) - img).max() <= 20
            dds = header + payload
            stem = 'zgc_ldiag3_f.' + hashlib.sha256(dds).hexdigest()[:16]
            extra[stem + '.dds'] = dds
            spec = copy.deepcopy(lamp_tex)
            spec['Binary'] = stem + '.tld'
            if MAX_R[tile] is not None:
                spec['Max'] = [MAX_R[tile]] + spec['Max'][1:]
            level['Texture'][name] = spec
            entry['bc4'] = {'member': stem + '.dds', 'max_r': spec['Max'][0]}
        if tile in EMISSION:
            entry['emissive_intensity'] = EMISSION[tile]
        report[tile] = entry
    return {'row': 'world z -700, tiles left to right along +X: ' + ' '.join(TILES), 'tile_cm': TILE_CM,
            'lift_cm': LIFT_CM, 'tiles': report}
