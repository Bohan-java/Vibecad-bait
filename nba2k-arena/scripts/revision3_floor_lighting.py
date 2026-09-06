"""Replace the donor's two floor lighting textures with an explicit sky fill.

No shader, floor UV, Object.UserData or material-slot change is made. The native
auxiliary scene already names the irradiance/direction two-layer texture and
the line-light visibility texture. Their dimensions/formats/mips are preserved;
only their referenced pixels and obsolete compressed-storage metadata change.

R11G11B10 uses unsigned 5-bit exponents (bias 15), 6/6/5 fraction bits, as defined
by DXGI_FORMAT_R11G11B10_FLOAT. Native two-face TLDs and the original floor's
Segments.MemoryOffset demonstrate face-major storage with mips within each face.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import struct


AUX_SCENE = 'level_floor_lightmaps.SCNE'
LIGHTMAP = '__floor00__'
VISIBILITY = '__floor00___linelightvisibility'
DEFAULT_AMBIENT = (.8, .85, .95)
DIRECTION_AMBIENT = (.5, .5, 1.)
TLD_HEADER = struct.Struct('<4sIHBBIHHHHII')
FORMAT_CODES = {'R11G11B10_FLOAT': 26, 'R8_UNORM': 61}
DXGI_SOURCE = 'https://learn.microsoft.com/en-us/windows/win32/api/dxgiformat/ne-dxgiformat-dxgi_format'


def _encode_unsigned_float(value, fraction_bits):
    value = float(value)
    maximum = math.ldexp(2 - math.ldexp(1, -fraction_bits), 15)
    if not math.isfinite(value) or value < 0 or value > maximum:
        raise ValueError('Lighting channels must be finite nonnegative representable values')
    if value == 0:
        return 0
    # Subnormal numbers have no hidden leading one. Python round provides
    # deterministic nearest-even rounding, including the normal boundary.
    if value < math.ldexp(1, -14):
        return round(math.ldexp(value, 14 + fraction_bits))
    mantissa, exponent = math.frexp(value)
    biased = exponent - 1 + 15
    fraction = round((mantissa * 2 - 1) * (1 << fraction_bits))
    if fraction == 1 << fraction_bits:
        biased += 1
        fraction = 0
    return (biased << fraction_bits) | fraction


def _decode_unsigned_float(word, fraction_bits):
    exponent = word >> fraction_bits
    fraction = word & ((1 << fraction_bits) - 1)
    if exponent == 31:
        return math.inf if fraction == 0 else math.nan
    if exponent == 0:
        return math.ldexp(fraction, -14 - fraction_bits)
    return math.ldexp(1 + fraction / (1 << fraction_bits), exponent - 15)


def encode_r11g11b10(rgb):
    """Pack one finite positive RGB triple; R is the least-significant field."""
    if len(rgb) != 3:
        raise ValueError('Expected exactly three RGB channels')
    r, g, b = (_encode_unsigned_float(v, bits) for v, bits in zip(rgb, (6, 6, 5)))
    return r | (g << 11) | (b << 22)


def decode_r11g11b10(word):
    """Decode a packed DXGI word, including subnormals and special values."""
    if not isinstance(word, int) or not 0 <= word <= 0xffffffff:
        raise ValueError('Expected an unsigned 32-bit integer')
    return (_decode_unsigned_float(word & 0x7ff, 6),
            _decode_unsigned_float((word >> 11) & 0x7ff, 6),
            _decode_unsigned_float((word >> 22) & 0x3ff, 5))


def subresources(width, height, mips, faces, bytes_per_pixel):
    """Describe the native face-major, mip-within-face linear pixel layout."""
    if any(not isinstance(x, int) or isinstance(x, bool) or x <= 0
           for x in (width, height, mips, faces, bytes_per_pixel)):
        raise ValueError('Texture dimensions/counts must be positive integers')
    if mips > max(width, height).bit_length():
        raise ValueError('More mip levels than the texture dimensions support')
    offset, records = 0, []
    for face in range(faces):
        for mip in range(mips):
            w, h = max(1, width >> mip), max(1, height >> mip)
            size = w * h * bytes_per_pixel
            records.append({'face': face, 'mip': mip, 'width': w, 'height': h,
                            'pixel_offset': offset, 'pixel_bytes': size})
            offset += size
    return records


def _verify_original_layout(spec, records):
    by_key = {(r['face'], r['mip']): r for r in records}
    seen = set()
    for segment in spec.get('Segments', ()):
        face, mip = segment.get('MinFace', 0), segment.get('MinMip', 0)
        key = face, mip
        if key in seen or key not in by_key:
            raise ValueError('Original floor segments are not single face/mip records')
        seen.add(key)
        expected = by_key[key]
        if (segment.get('MaxFace', face) != face or segment.get('MaxMip', mip) != mip or
                segment.get('MemoryOffset', 0) != expected['pixel_offset'] or
                segment['MemorySize'] != expected['pixel_bytes']):
            raise ValueError('Original floor segment memory layout differs from audited face-major layout')
    if seen != set(by_key):
        raise ValueError('Original floor segment table does not cover every face and mip')
    if spec['PixelDataSize'] != sum(r['pixel_bytes'] for r in records):
        raise ValueError('Original floor pixel size differs from format and dimensions')


def _constant_tld(spec, encoded_faces, bytes_per_pixel):
    records = subresources(spec['Width'], spec['Height'], spec['Mips'],
                           spec.get('Faces', 1), bytes_per_pixel)
    _verify_original_layout(spec, records)
    if len(encoded_faces) != spec.get('Faces', 1) or any(len(x) != bytes_per_pixel for x in encoded_faces):
        raise ValueError('Wrong number or size of face texels')
    payload = b''.join(encoded_faces[r['face']] * (r['width'] * r['height']) for r in records)
    header = TLD_HEADER.pack(b'TLD ', 0, 4, FORMAT_CODES[spec['Format']], spec['Mips'],
                             31, spec['Width'], spec['Height'], 1, spec.get('Faces', 1),
                             len(payload), len(payload))
    return header + payload, records


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def apply_floor_lighting(donor_zip, extra, *, ambient_rgb=DEFAULT_AMBIENT):
    """Return auxiliary SCNE override text and add two uncompressed native TLDs.

    This is an explicit artistic fill, not a recovered average of inaccessible
    original pixels. ``ambient_rgb`` is configurable for later game feedback;
    the default is not a claim that game exposure has been calibrated.
    """
    original_raw = donor_zip.read(AUX_SCENE)
    raw = original_raw.strip()
    document = json.loads(raw if raw.startswith(b'{') else b'{' + raw + b'}')
    scene = document.get('level_floor_lightmaps', {})
    textures = scene.get('Texture', {})
    expected = {LIGHTMAP: ('R11G11B10_FLOAT', 2), VISIBILITY: ('R8_UNORM', 1)}
    for name, (format_name, faces) in expected.items():
        spec = textures.get(name, {})
        if (spec.get('Format') != format_name or spec.get('Faces', 1) != faces or
                spec.get('Width') != 424 or spec.get('Height') != 424 or spec.get('Mips') != 2 or
                spec.get('TexelUsage') != 'LINEAR'):
            raise ValueError('Unexpected native floor lighting specification: ' + name)
    ambient_rgb = tuple(float(v) for v in ambient_rgb)
    ambient_word, direction_word = encode_r11g11b10(ambient_rgb), encode_r11g11b10(DIRECTION_AMBIENT)
    ambient_actual, direction_actual = decode_r11g11b10(ambient_word), decode_r11g11b10(direction_word)
    pixels = {
        LIGHTMAP: ([struct.pack('<I', ambient_word), struct.pack('<I', direction_word)], 4, 'daylight'),
        VISIBILITY: ([b'\xff'], 1, 'unoccluded_linelight'),
    }
    archive_names = set(donor_zip.namelist())
    resources, entries = {}, []
    for name, (face_texels, byte_width, label) in pixels.items():
        old = deepcopy(textures[name])
        blob, layout = _constant_tld(old, face_texels, byte_width)
        filename = f'venice_v3_floor_{label}.{_sha(blob)[:16]}.tld'
        if filename in extra or filename in archive_names:
            raise ValueError('Floor-lighting output resource already exists: ' + filename)
        new = deepcopy(old)
        new['Binary'] = filename
        new.pop('CompressionMethod', None)
        new.pop('Segments', None)
        # Extrema describe the actual replacement layers, never inaccessible
        # source pixels. They remain four-channel metadata as in the donor.
        if name == LIGHTMAP:
            new['Min'] = [min(a, b) for a, b in zip(ambient_actual, direction_actual)] + [1.]
            new['Max'] = [max(a, b) for a, b in zip(ambient_actual, direction_actual)] + [1.]
        else:
            new['Min'], new['Max'] = [1., 0., 0., 1.], [1., 0., 0., 1.]
        textures[name] = new
        resources[filename] = blob
        entries.append({'texture_key': name, 'original_spec': old, 'replacement_spec': deepcopy(new),
                        'source_pixels_in_donor_archive': old['Binary'] in archive_names,
                        'replacement_file_bytes': len(blob), 'replacement_sha256': _sha(blob),
                        'header_format_code': FORMAT_CODES[new['Format']], 'subresources': layout})
    # Only this freshly parsed document has been changed; commit extra after
    # all validation so a collision/failure cannot leave half the resources.
    override = json.dumps(document, separators=(',', ':'))[1:-1]
    extra.update(resources)
    return {
        'scene_overrides': {AUX_SCENE: override}, 'source_aux_sha256': _sha(original_raw),
        'replacement_aux_sha256': _sha(override.encode()), 'textures': entries,
        'ambient_requested_rgb': list(ambient_rgb), 'ambient_quantized_rgb': list(ambient_actual),
        'ambient_packed_r11g11b10': ambient_word,
        'direction_ambient_rgb': list(direction_actual), 'direction_ambient_packed_r11g11b10': direction_word,
        'linelight_visibility': 1., 'same_dimensions_mips_faces_and_texture_keys': True,
        'original_aux_markers_preserved': True, 'original_material_slots_and_userdata_modified': False,
        'shader_binaries_modified': False, 'game_exposure_calibrated': False, 'game_runtime_verified': False,
        'evidence': {
            'format_reference': DXGI_SOURCE,
            'layout': 'Original Segments.MemoryOffset: face0 mips 0/719104, face1 mips 898880/1617984',
            'floor_pixel_shader': 'PS.0cfd5246b9c1587a.shader; face0 RGB irradiance, face1 RG direction/B ambient mix, native line-light visibility resource',
            'original_pixels': 'The two source texture binaries are external game references, not included in the handoff; no original brightness average was measured',
        },
        'limitations': [
            'Uniform sky fill is an explicit approximation. It removes old roof-shaped irradiance variation but does not rebake the original scene or reproduce physical sky transport.',
            'The chosen ambient level requires game exposure and material feedback; no game brightness result has been observed.',
            'Unoccluded line-light visibility removes the old static visibility mask; this is not proof that new real-time palm shadows or dynamic floor lighting dispatch work.',
        ],
    }
