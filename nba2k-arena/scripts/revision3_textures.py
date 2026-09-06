"""Scanned matte court and coastal materials, encoded independently of V2.

Generic layer shader: RG = normal XY, A = roughness, B unused in the verified
Default PS. Floor shader has a different packing: RG normal XY, B roughness,
A reflection gain. The floor base R is zero so detail roughness is authoritative.
The floor A channel stays strictly positive because the shader later divides by
that gain. No shader binaries or archived texture files are changed.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'textures/source/polyhaven'
OUT = ROOT / 'build/revision3/textures'
TLD_HEADER = struct.Struct('<4sIHBBIHHHHII')
FLOOR_MATERIALS = ('floor_clutchtime_court:area_1_mat',
                   'floor_clutchtime_court:floor_line_mat',
                   'floor_clutchtime_court:floor_line_mat1')
SURFACE_MATERIALS = {
    'clutchtime_floor_apron:floor_mat': 'concrete',
    'clutchtime_balcony_b:balcony_mat': 'concrete',
    'clutchtime_balcony_b:balcony2_amt': 'grass',
    'clutchtime_balcony_b:balcony4_mat': 'concrete',
    'clutchtime_stair_3step:steps_mat': 'concrete',
    'clutchtime_balcony_railing:railing_mat': 'aluminum',
    'clutchtime_crowd_seating:chair': 'aluminum',
}
# Color/contrast are design controls pending high-resolution reference and game
# exposure checks. No production resolution ceiling is applied to scans.
SCAN_PROFILES = {
    'concrete': ('concrete_floor_02', (158, 154, 142), .40, .05, True, .26, .91, .98),
    'court_concrete': ('concrete_floor_02', (90, 94, 96), .32, .03, True, .26, .91, .98),
    'grass': ('leafy_grass', (77, 98, 48), .82, .50, False, .42, .87, .98),
    'bark': ('palm_tree_bark', (122, 112, 93), .93, .40, False, .55, .85, .98),
    'sand': ('coast_sand_01', (184, 178, 156), .60, .25, False, .30, .89, .98),
}


def dds_bytes(payload, width, height, fmt):
    if fmt not in ('BC1_UNORM', 'BC3_UNORM'):
        raise ValueError('Only verified BC1 / BC3 TLD formats are supported')
    fourcc, block_size = (b'DXT1', 8) if fmt == 'BC1_UNORM' else (b'DXT5', 16)
    top_size = max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * block_size
    header = b'DDS ' + struct.pack('<7I', 124, 0x81007, height, width, top_size, 0, 0)
    header += bytes(44) + struct.pack('<2I4s5I', 32, 4, fourcc, 0, 0, 0, 0, 0)
    header += struct.pack('<5I', 0x1000, 0, 0, 0, 0)
    return header + payload


def mip_sizes(width, height):
    result = []
    while True:
        result.append((width, height))
        if width == height == 1:
            return result
        width, height = max(1, width // 2), max(1, height // 2)


def decode_tld_mips(raw, spec):
    """Decode every mip with Pillow's independent native BC decoder."""
    if len(raw) < 32 or raw[:4] != b'TLD ':
        raise ValueError('Invalid TLD header')
    header = TLD_HEADER.unpack_from(raw)
    fmt = spec['Format']
    code, block = (71, 8) if fmt == 'BC1_UNORM' else (77, 16)
    sizes = mip_sizes(spec['Width'], spec['Height'])
    if header[3] != code or header[4] != len(sizes) or (header[6], header[7]) != sizes[0]:
        raise ValueError('TLD header/spec mismatch')
    if header[8] != 1 or header[9] != spec.get('Faces', 1):
        raise ValueError('TLD depth/face count mismatch')
    if header[9] != 1:
        raise ValueError('This decoder accepts one-face material textures only')
    if header[-2] != len(raw) - 32 or header[-1] != len(raw) - 32:
        raise ValueError('TLD payload size mismatch')
    result, offset = [], 32
    for width, height in sizes:
        count = max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * block
        if offset + count > len(raw):
            raise ValueError('Truncated TLD mip chain')
        image = Image.open(io.BytesIO(dds_bytes(raw[offset:offset + count], width, height, fmt)))
        image.load()
        result.append(image.convert('RGBA'))
        offset += count
    if offset != len(raw) or len(sizes) != spec['Mips']:
        raise ValueError('Unexpected trailing TLD data or mip count')
    return result


def encode_texture(label, image, *, linear=False, output_dir=OUT):
    """Return (Pixelmap key, spec, raw TLD, JSON audit), writing only new outputs."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    image = image.convert('RGBA' if image.mode == 'RGBA' else 'RGB')
    alpha = image.mode == 'RGBA'
    fmt, codec, block = ('BC3_UNORM', 'DXT5', 16) if alpha else ('BC1_UNORM', 'DXT1', 8)
    sizes = mip_sizes(*image.size)
    payloads, current = [], image
    for size in sizes:
        if current.size != size:
            current = current.resize(size, Image.Resampling.LANCZOS)
        w, h = size
        pw, ph = max(4, (w + 3) // 4 * 4), max(4, (h + 3) // 4 * 4)
        padded = np.pad(np.asarray(current), ((0, ph - h), (0, pw - w), (0, 0)), mode='edge')
        stream = io.BytesIO()
        Image.fromarray(padded).save(stream, format='DDS', pixel_format=codec)
        payload = stream.getvalue()[128:]
        expected = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block
        if len(payload) != expected:
            raise ValueError(f'Unexpected BC payload for {label} mip {size}')
        payloads.append(payload)
    payload = b''.join(payloads)
    raw = TLD_HEADER.pack(b'TLD ', 0, 4, 77 if alpha else 71, len(sizes), 31,
                          image.width, image.height, 1, 1,
                          len(payload), len(payload)) + payload
    digest = hashlib.sha256(raw).hexdigest()
    binary = f'venice_v3_{label}.{digest[:16]}.tld'
    key = f'local/venice_v3/{label}'
    rgba = np.asarray(image.convert('RGBA'))
    spec = {'Width': image.width, 'Height': image.height, 'Mips': len(sizes), 'Format': fmt,
            'Min': (rgba.min((0, 1)) / 255).tolist(), 'Max': (rgba.max((0, 1)) / 255).tolist(),
            'PixelDataSize': len(payload), 'Binary': binary}
    if linear:
        spec['TexelUsage'] = 'LINEAR'
    decoded = decode_tld_mips(raw, spec)
    decoded_rgba = np.asarray(decoded[0])
    # Bound metadata must include the real BC endpoint quantization, not just
    # source image extrema, as the runtime can inspect constant channels.
    spec['Min'] = np.minimum(np.array(spec['Min']), decoded_rgba.min((0, 1)) / 255).tolist()
    spec['Max'] = np.maximum(np.array(spec['Max']), decoded_rgba.max((0, 1)) / 255).tolist()
    (output_dir / binary).write_bytes(raw)
    image.save(output_dir / f'{label}_source.png')
    decoded[0].save(output_dir / f'{label}_decoded.png')
    audit = {'key': key, 'binary': binary, 'format': fmt, 'size': list(image.size),
             'mips': len(sizes), 'all_mips_decoded': True, 'sha256': digest,
             'source_png': str(output_dir / f'{label}_source.png'),
             'decoded_png': str(output_dir / f'{label}_decoded.png'),
             'decoded_rgba_min': decoded_rgba.min((0, 1)).tolist(),
             'decoded_rgba_max': decoded_rgba.max((0, 1)).tolist(),
             'decoded_rgba_mean': decoded_rgba.mean((0, 1)).round(5).tolist()}
    return key, spec, raw, audit


def _load_sources():
    manifest = json.loads((SOURCE / 'manifest.json').read_text())
    records = {(item['asset'], item['map']): item for item in manifest}
    needed = ('concrete_floor_02', 'leafy_grass', 'palm_tree_bark', 'coast_sand_01')
    images, used = {}, []
    for asset in needed:
        for channel in ('Diffuse', 'nor_dx', 'Rough'):
            record = records[(asset, channel)]
            raw = (SOURCE / record['file']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != record['sha256']:
                raise ValueError('Scanned source hash mismatch: ' + record['file'])
            images[(asset, channel)] = Image.open(io.BytesIO(raw)).convert('RGB')
            used.append(record)
    return images, used


def _fit(image, maximum):
    scale = min(1., maximum / max(image.size))
    return image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)


def _color_grade(image, target, contrast=.75, retain_color=.2, remove_stains=False):
    a = np.asarray(image, dtype=np.float32)
    luminance = a @ np.array([.2126, .7152, .0722], dtype=np.float32)
    if remove_stains:
        low = np.asarray(Image.fromarray(np.uint8(luminance)).filter(ImageFilter.GaussianBlur(max(image.size) / 35)), dtype=float)
        detail = luminance - low + .16 * (low - low.mean())
    else:
        detail = luminance - luminance.mean()
    chroma = a - luminance[:, :, None]
    chroma -= chroma.mean((0, 1), keepdims=True)
    result = np.array(target) + detail[:, :, None] * contrast + chroma * retain_color
    return Image.fromarray(np.uint8(np.clip(result, 0, 255)))


def packed_normal(normal_dx, roughness, *, strength=.35, rough_min=.88, rough_max=.97,
                  floor=False, reflection=.06):
    """Pack measured channels for one specific shader family; B has no generic meaning."""
    n = np.asarray(normal_dx.convert('RGB'), dtype=float) / 255
    r = np.asarray(roughness.convert('L').resize(normal_dx.size, Image.Resampling.LANCZOS), dtype=float) / 255
    xy = .5 + (n[:, :, :2] - .5) * strength
    rough = rough_min + np.clip(r, 0, 1) * (rough_max - rough_min)
    if floor:
        if not (0 < reflection <= 1):
            raise ValueError('Floor reflection gain must stay strictly positive')
        result = np.dstack((xy, rough, np.full_like(rough, reflection)))
    else:
        result = np.dstack((xy, np.zeros_like(rough), rough))
    return Image.fromarray(np.uint8(np.clip(np.rint(result * 255), 0, 255)), 'RGBA')


def _flat_normal(size, roughness):
    return Image.new('RGBA', size, (128, 128, 0, round(roughness * 255)))


def leaf_texture(size=(1024, 1024), *, variant='leaf'):
    """28 radial ribs in whole-fan UVs: U around the fan, V from hub to tip."""
    w, h = size
    y, x = np.mgrid[:h, :w]
    u, v = x / max(1, w - 1), y / max(1, h - 1)
    colors = {'leaf': (60, 94, 38), 'leaf_light': (84, 117, 48), 'leaf_dead': (132, 108, 69)}
    # Root geometry uses 28 angular sectors. Constant-U veins therefore radiate
    # physically from the hub; do not paint a single leaflet's transverse veins
    # across the entire fan. Four fine parallel fibers per sector remain aligned
    # with the 28 primary ribs. Texture detail fades near the compressed UV hub.
    ribs = 7 * np.maximum(0, np.cos(u * math_tau() * 28)) ** 14
    fibers = 2.8 * np.sin(u * math_tau() * 112)
    root_fade = .22 + .78 * np.sqrt(v)
    age = -9 * v ** 3 + 5 * np.sin(v * np.pi)
    detail = (ribs + fibers) * root_fade + age
    base = np.array(colors[variant], float)
    array = base + detail[:, :, None] * np.array([.9, 1., .6])
    return Image.fromarray(np.uint8(np.clip(array, 0, 255)))


def math_tau():
    return 2 * np.pi


def _ocean_texture(size=512):
    y, x = np.mgrid[:size, :size]
    u, v = x / size, y / size
    ripples = 3 * np.sin(math_tau() * (7 * u + 29 * v)) + 2 * np.sin(math_tau() * (3 * u - 53 * v))
    array = np.array([57, 100, 119]) + ripples[:, :, None] * np.array([.6, .8, 1.])
    return Image.fromarray(np.uint8(np.clip(array, 0, 255)))


def build_texture_set(*, output_dir=OUT, max_size=None):
    """Generate complete new assets; max_size is only for small codec smoke tests."""
    sources, provenance = _load_sources()
    images = {}
    for label, (asset, target, contrast, chroma, stains, strength, r0, r1) in SCAN_PROFILES.items():
        source_diffuse = sources[(asset, 'Diffuse')]
        diffuse = _fit(source_diffuse, max_size) if max_size else source_diffuse
        images[label] = (_color_grade(diffuse, target, contrast, chroma, stains), False)
        source_normal = sources[(asset, 'nor_dx')]
        normal = _fit(source_normal, max_size) if max_size else source_normal
        rough = sources[(asset, 'Rough')]
        images[label + '_normal'] = (packed_normal(normal, rough, strength=strength, rough_min=r0, rough_max=r1), True)
        if label == 'court_concrete':
            images['floor_normal'] = (packed_normal(normal, rough, strength=.26,
                                                    rough_min=.91, rough_max=.98,
                                                    floor=True, reflection=.06), True)
    for label in ('leaf', 'leaf_light', 'leaf_dead'):
        image = leaf_texture(variant=label)
        if max_size:
            image = _fit(image, max_size)
        images[label] = (image, False)
        # Normal fibers are subdued; leaf curvature and silhouette are mesh data.
        gray = image.convert('L')
        grad = np.asarray(gray, float)
        gy, gx = np.gradient(grad)
        n = np.dstack((128 - gx * 2, 128 - gy * 2, np.full_like(gx, 255)))
        images[label + '_normal'] = (packed_normal(Image.fromarray(np.uint8(np.clip(n, 0, 255))),
                                                   Image.new('L', image.size, 180),
                                                   strength=.45, rough_min=.78, rough_max=.92), True)
    solids = {'aluminum': (158, 164, 163), 'dark_metal': (42, 48, 48), 'line_white': (255, 255, 255)}
    for label, color in solids.items():
        images[label] = (Image.new('RGB', (4, 4), color), False)
        images[label + '_normal'] = (_flat_normal((4, 4), .78 if label == 'aluminum' else .92), True)
    ocean = _ocean_texture(min(512, max_size) if max_size else 512)
    images['ocean'] = (ocean, False)
    images['ocean_normal'] = (_flat_normal((4, 4), .56), True)
    images['floor_base'] = (Image.new('RGBA', (4, 4), (0, 0, 0, 255)), True)
    images['no_logo'] = (Image.new('RGBA', (4, 4), (255, 255, 255, 0)), False)
    textures = {}
    for label, (image, linear) in images.items():
        textures[label] = encode_texture(label, image, linear=linear, output_dir=output_dir)
    return textures, provenance


def apply_textures(level, extra, *, output_dir=OUT, max_size=None):
    """Register new textures, make the donor court matte, and expose texture keys."""
    textures, provenance = build_texture_set(output_dir=output_dir, max_size=max_size)
    keys, assets = {}, {}
    for label, (key, spec, raw, audit) in textures.items():
        if key in level['Texture'] and level['Texture'][key] != spec:
            raise ValueError('Conflicting revision 3 texture key: ' + key)
        if spec['Binary'] in extra and extra[spec['Binary']] != raw:
            raise ValueError('Conflicting revision 3 texture bytes')
        level['Texture'][key] = spec
        extra[spec['Binary']] = raw
        keys[label], assets[label] = key, audit
    floor_changes = []
    for name in FLOOR_MATERIALS:
        material = level['Material'][name]
        material['Resource']['BaseMaterialTexture']['Pixelmap'] = keys['floor_base']
        material['Resource']['DetailNormalRoughConeTexture']['Pixelmap'] = keys['floor_normal']
        material['Resource']['DetailAlbedoTexture']['Pixelmap'] = keys['court_concrete' if name == FLOOR_MATERIALS[0] else 'line_white']
        if 'Logo0Texture' in material['Resource']:
            material['Resource']['Logo0Texture']['Pixelmap'] = keys['no_logo']
        material['Parameter'].update(DetailRoughness=.94, DetailNormalHeight=.018,
                                      ModulateAlbedo=[1., 1., 1.])
        floor_changes.append(name)
    surface_changes = []
    for name, label in SURFACE_MATERIALS.items():
        material = level['Material'][name]
        material['Resource']['AlbedoMap']['Pixelmap'] = keys[label]
        material['Resource']['NormalAndRoughMap']['Pixelmap'] = keys[label + '_normal']
        material['Parameter'].update(AlbedoModulate=[1., 1., 1., 1.], NormalHeight=.16)
        surface_changes.append(name)
    floor_decoded = np.asarray(decode_tld_mips(textures['floor_normal'][2], textures['floor_normal'][1])[0])
    if floor_decoded[:, :, 3].min() <= 0 or floor_decoded[:, :, 2].min() < 220:
        raise ValueError('Packed floor loses positive reflection gain or matte roughness after BC compression')
    report = {'textures': keys, 'assets': assets, 'source_assets': provenance,
              'floor_materials_changed': floor_changes, 'surface_materials_changed': surface_changes,
              'floor_shader_channels': {'RG': 'subdued DirectX normal XY', 'B': 'roughness',
                                         'A': 'strictly positive reflection gain', 'BaseR': 0},
              'floor_decoded_roughness_range': (floor_decoded[:, :, 2].min() / 255,
                                                floor_decoded[:, :, 2].max() / 255),
              'floor_decoded_reflection_gain_range': (floor_decoded[:, :, 3].min() / 255,
                                                      floor_decoded[:, :, 3].max() / 255),
              'generic_shader_channels': {'RG': 'normal XY', 'B': 'zero; unused by verified Default PS', 'A': 'roughness'},
              'floor_uv_sampling': 'Original TEXCOORD2 through script-derived affine; donor DetailMaterialScale/Offset preserved, physical tile size not inferred',
              'scan_resolution_policy': 'Original diffuse and normal source dimensions; max_size is an explicit test-only override',
              'concrete_color_profiles': {name: {'target_rgb': list(SCAN_PROFILES[name][1]),
                                                 'detail_contrast': SCAN_PROFILES[name][2]}
                                          for name in ('court_concrete', 'concrete')},
              'original_binary_files_modified': False, 'game_runtime_verified': False,
              'output_dir': str(output_dir)}
    output_dir = Path(output_dir)
    (output_dir / 'material_manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    names = ('court_concrete', 'concrete', 'grass', 'bark', 'sand', 'leaf', 'leaf_light', 'leaf_dead', 'ocean', 'aluminum', 'dark_metal')
    sheet = Image.new('RGB', (1530, 560), (25, 34, 39))
    draw = ImageDraw.Draw(sheet)
    for i, name in enumerate(names):
        tile = Image.open(assets[name]['decoded_png']).convert('RGB').resize((240, 240), Image.Resampling.LANCZOS)
        x, y = 16 + (i % 6) * 252, 8 + (i // 6) * 276
        sheet.paste(tile, (x, y))
        draw.text((x, y + 248), name + ' / decoded BC', fill='white')
    sheet.save(output_dir / 'material_contact_sheet.png')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', action='store_true', help='Write new material previews, never a game directory')
    args = parser.parse_args()
    if not args.preview:
        parser.error('Use --preview')
    import zipfile
    with zipfile.ZipFile(ROOT / 'donor/original/arena_020_int_original.iff') as archive:
        raw = archive.read('level.SCNE')
        level = json.loads(b'{' + raw + b'}')['level']
    extra = {}
    report = apply_textures(level, extra)
    print(json.dumps({'textures': len(report['textures']), 'bytes': sum(map(len, extra.values())),
                      'floor_roughness': report['floor_decoded_roughness_range'],
                      'floor_reflection': report['floor_decoded_reflection_gain_range']}))


if __name__ == '__main__':
    main()
