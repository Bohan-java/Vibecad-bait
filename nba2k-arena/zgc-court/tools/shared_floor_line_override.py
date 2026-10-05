"""Prepare an explicitly unverified cross-package floor-line texture candidate.

API: resources, texture_entries, report = prepare_shared_line_override(floor_level)
The caller may register texture_entries in main_level['Texture'] and add the
resources to the one main IFF. This module never opens or writes an IFF itself.
No shader, draw, vertex, index, depth state, marker or player asset is changed.
"""
from __future__ import annotations

import copy
import hashlib
import io
import struct


LINE_TEXTURES = {
    '%databuild_art_root%/material_library/_generic_textures/courts_shared/floor_line.png':
        'floor_line.71af6dc754935e49.tld',
    '%databuild_art_root%/material_library/_generic_textures/courts_shared/floor_line_thin.png':
        'floor_line_thin.b8e9b0535e40bbaf.tld',
    '%databuild_art_root%/material_library/_generic_textures/courts_shared/floor_line_double.png':
        'floor_line_double.b070a8a6acc12d69.tld',
}


def transparent_bc7_dds(width=512, height=512, mips=10):
    """Constant RGBA=(255,255,255,0), BC7 mode 5, every mip present.

    Mode 5 has independent eight-bit alpha endpoints. Its six-bit mode prefix
    is 0b100000, rotation=0, all six seven-bit RGB endpoints=127, both alpha
    endpoints=0 and all interpolation indices=0. This avoids coupling RGB and
    alpha endpoint precision through the shared p-bits of BC7 mode 6.
    """
    if (width, height, mips) != (512, 512, 10):
        raise ValueError('Only the audited native 512-square/10-mip format is supported')
    block = (0x20 | (((1 << 42) - 1) << 8)).to_bytes(16, 'little')
    levels = []
    for mip in range(mips):
        w, h = max(1, width >> mip), max(1, height >> mip)
        levels.append(block * (((w + 3) // 4) * ((h + 3) // 4)))
    header = [124, 0xA1007, height, width, len(levels[0]), 0, mips] + [0] * 11
    header += [32, 4, int.from_bytes(b'DX10', 'little'), 0, 0, 0, 0, 0]
    header += [0x401008, 0, 0, 0, 0]
    assert len(header) == 31
    # DXGI_FORMAT_BC7_UNORM=98, D3D10_RESOURCE_DIMENSION_TEXTURE2D=3, one slice.
    raw = b'DDS ' + struct.pack('<31I', *header) + struct.pack('<5I', 98, 3, 0, 1, 0) + b''.join(levels)
    if len(raw) != 148 + 349552:
        raise AssertionError('Unexpected native-size BC7 mip chain')
    return raw


def verify_transparent_dds(raw):
    """Decode each mip independently with Pillow, not the encoder's bit logic."""
    from PIL import Image
    if raw[:4] != b'DDS ' or struct.unpack_from('<I', raw, 128)[0] != 98:
        raise ValueError('Expected a DX10 BC7 DDS')
    offset = 148
    checked = []
    for mip in range(10):
        side = max(1, 512 >> mip)
        size = ((side + 3) // 4) ** 2 * 16
        header = bytearray(raw[:148])
        struct.pack_into('<I', header, 12, side)
        struct.pack_into('<I', header, 16, side)
        struct.pack_into('<I', header, 20, size)
        struct.pack_into('<I', header, 28, 1)
        with Image.open(io.BytesIO(bytes(header) + raw[offset:offset + size])) as image:
            rgba = image.convert('RGBA')
            extrema = rgba.getextrema()
            if rgba.size != (side, side) or extrema != ((255, 255), (255, 255), (255, 255), (0, 0)):
                raise AssertionError((mip, rgba.size, extrema))
        checked.append({'mip': mip, 'width': side, 'height': side, 'payload_bytes': size,
                        'decoded_rgba': [255, 255, 255, 0]})
        offset += size
    if offset != len(raw):
        raise ValueError('Unexpected trailing DDS bytes')
    return checked


def prepare_shared_line_override(floor_level):
    """Return (DDS resource bytes, exact native Texture entries, candidate report).

    Copy descriptor names/format/segments unchanged to avoid creating competing
    SCNE schemas for the same resource. Rucker already demonstrates DDS alias
    payloads with retained native TLD descriptors inside one package. That does
    NOT establish selection precedence across arena and arena_floor packages.
    """
    raw = transparent_bc7_dds()
    mip_check = verify_transparent_dds(raw)
    resources, textures = {}, {}
    for logical, binary in LINE_TEXTURES.items():
        source = floor_level['Texture'][logical]
        if (source.get('Width'), source.get('Height'), source.get('Mips'), source.get('Format'),
                source.get('PixelDataSize'), source.get('Binary')) != (512, 512, 10, 'BC7_UNORM', 349552, binary):
            raise ValueError('Native floor line descriptor differs from audited asset: ' + logical)
        textures[logical] = copy.deepcopy(source)
        resources[binary[:-4] + '.dds'] = raw
    uses = []
    for name, mat in floor_level['Material'].items():
        pixelmap = mat.get('Resource', {}).get('DetailAlbedoTexture', {}).get('Pixelmap')
        if pixelmap not in textures:
            continue
        effect = floor_level['Effect'][mat['Effect']]
        ps = effect['Technique']['Default']['Pass']['Default']
        override = mat['Technique']['Default']['Pass']['Default']
        if (ps.get('ALPHABLENDENABLE'), ps.get('SRCBLEND'), ps.get('DESTBLEND'),
                override.get('ZWRITEENABLE')) != (1, 'SRCALPHA', 'INVSRCALPHA', 0):
            raise ValueError('Unreviewed native floor line blending: ' + name)
        uses.append({'material': name, 'pixelmap': pixelmap,
                     'alpha_blend': ['SRCALPHA', 'INVSRCALPHA'], 'depth_write': 0})
    if {x['material'] for x in uses} != {f'floor_700_court:line_{i}_mat' for i in range(1, 6)}:
        raise ValueError('Unexpected native floor line consumers')
    report = {
        'strategy': 'One-main-IFF candidate overriding external shared line texture alpha',
        'cross_package_selection_verified': False, 'game_tested': False,
        'resources': list(resources), 'texture_dictionary_keys': list(textures),
        'bytes_per_resource': len(raw), 'payload_sha256': hashlib.sha256(raw).hexdigest(),
        'format': 'BC7_UNORM', 'mips': mip_check,
        'native_texture_descriptors_copied_exactly': True,
        'original_line_materials_expected_affected': uses,
        'depth_geometry_shader_and_marker_changes': False,
        'do_not_rename_native_resource_stems': True,
        'integration': 'Register returned Texture entries in level.SCNE level.Texture and add the three exact-named DDS resources. Do not add a second floor IFF, change floor SCNE or retain the R07 ground depth bias.',
        'evidence': [
            'The cached original 700 floor Texture entries point to these three shared TLD resources; its ZIP contains no corresponding TLD/DDS payloads.',
            'Native floor line materials use source-alpha blending and disable depth writes; transparent albedo alpha is a plausible way to remove color without hiding player markers.',
            'Every mip decodes to white RGB with zero alpha in an independent Pillow BC7 decoder.',
        ],
        'limitations': [
            'Main-IFF registration may not supersede a shared texture already loaded through the separate floor package; no loader code or runtime experiment establishes its priority.',
            'Native floor HLSL has not been decompiled; alpha usage is inferred from its texture range, named albedo slot and native blend states.',
            'Other simultaneously loaded courts that use these same shared texture IDs may also lose their lines if the override is global.',
            'This is a low-impact resource-selection candidate, not a claim that the single-file external-floor problem is solved.',
        ],
    }
    return resources, textures, report
