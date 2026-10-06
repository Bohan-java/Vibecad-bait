"""Small, standard-library-only diagnostic codecs; NOT a native TLD codec.

Geometry layout follows tools/iff_codec.py at abd8643a (see REPORT_ZH.md).
BC encoders are deliberately simple diagnostic encoders, not production bakers.
No file-system writes, imports of production modules, or IFF packing happen here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import struct
import zlib

ROTATED = [-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1]
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
BLOCK_BYTES = {'BC1_UNORM': 8, 'BC3_UNORM': 16, 'BC4_UNORM': 8}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_scne(raw: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate SCNE key: ' + key)
            result[key] = value
        return result
    text = raw.decode('utf-8-sig')
    doc = json.loads(text if text.lstrip().startswith('{') else '{' + text + '}',
                     object_pairs_hook=unique,
                     parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    if not isinstance(doc, dict):
        raise ValueError('Expected a SCNE object/fragment')
    return doc


def dump_native(doc: dict) -> bytes:
    # Identical formatting to the inspected repair_iff.dump_native for finite JSON.
    return (json.dumps(doc, ensure_ascii=True, indent='\t', allow_nan=False)[1:-1].strip() + '\n').encode('utf-8')


def mip_sizes(width: int, height: int, count: int):
    if not (width > 0 and height > 0 and 1 <= count <= max(width, height).bit_length()):
        raise ValueError('Invalid texture dimensions/mipmap count')
    for _ in range(count):
        yield width, height
        width, height = max(1, width // 2), max(1, height // 2)


def payload_size(width: int, height: int, count: int, fmt: str) -> int:
    return sum(((w + 3) // 4) * ((h + 3) // 4) * BLOCK_BYTES[fmt]
               for w, h in mip_sizes(width, height, count))


def bc4_palette(a: int, b: int) -> list[float]:
    if not (0 <= a <= 255 and 0 <= b <= 255):
        raise ValueError('BC4_UNORM endpoints must be bytes')
    if a > b:
        return [float(a), float(b)] + [((7-i)*a + i*b)/7 for i in range(1, 7)]
    return [float(a), float(b)] + [((5-i)*a + i*b)/5 for i in range(1, 5)] + [0., 255.]


def encode_bc4_block(values) -> bytes:
    if len(values) != 16 or any(not math.isfinite(x) or x < 0 or x > 255 for x in values):
        raise ValueError('Expected 16 finite UNORM byte values')
    a, b = round(max(values)), round(min(values))
    palette = bc4_palette(a, b)
    selectors = sum(min(range(8), key=lambda j: abs(palette[j]-v)) << (3*i)
                    for i, v in enumerate(values))
    return bytes((a, b)) + selectors.to_bytes(6, 'little')


def decode_bc4_block(raw: bytes) -> list[float]:
    if len(raw) != 8:
        raise ValueError('BC4 block must have 8 bytes')
    palette = bc4_palette(raw[0], raw[1])
    bits = int.from_bytes(raw[2:], 'little')
    return [palette[(bits >> (3*i)) & 7] / 255 for i in range(16)]


def pack565(rgb) -> int:
    r, g, b = rgb
    return (round(r*31/255) << 11) | (round(g*63/255) << 5) | round(b*31/255)


def unpack565(value: int) -> tuple[float, float, float]:
    return (((value >> 11) & 31)*255/31, ((value >> 5) & 63)*255/63, (value & 31)*255/31)


def encode_bc1_block(pixels) -> bytes:
    if len(pixels) != 16:
        raise ValueError('BC1 block must have 16 pixels')
    colors = list(dict.fromkeys(tuple(map(int, p[:3])) for p in pixels))
    if any(len(c) != 3 or any(x < 0 or x > 255 for x in c) for c in colors):
        raise ValueError('RGB values out of range')
    # Farthest-pair endpoints, sufficient for the diagnostic's small color chart.
    ca, cb = max(((a, b) for a in colors for b in colors),
                 key=lambda pair: sum((x-y)**2 for x, y in zip(*pair)))
    a, b = sorted((pack565(ca), pack565(cb)), reverse=True)
    if a == b:
        if a < 65535:
            a += 1
        else:
            b -= 1
    pa, pb = unpack565(a), unpack565(b)
    palette = [pa, pb, tuple((2*x+y)/3 for x, y in zip(pa, pb)), tuple((x+2*y)/3 for x, y in zip(pa, pb))]
    bits = sum(min(range(4), key=lambda j: sum((v-palette[j][k])**2 for k, v in enumerate(p[:3]))) << (2*i)
               for i, p in enumerate(pixels))
    return struct.pack('<HHI', a, b, bits)


def encode_level(pixels, width: int, height: int, fmt: str) -> bytes:
    if len(pixels) != width*height:
        raise ValueError('Pixel count does not match dimensions')
    out = bytearray()
    for by in range((height + 3)//4):
        for bx in range((width + 3)//4):
            block = [pixels[min(height-1, 4*by+y)*width + min(width-1, 4*bx+x)] for y in range(4) for x in range(4)]
            if fmt == 'BC4_UNORM':
                out += encode_bc4_block(block)
            elif fmt == 'BC1_UNORM':
                out += encode_bc1_block(block)
            elif fmt == 'BC3_UNORM':
                out += encode_bc4_block([p[3] for p in block]) + encode_bc1_block(block)
            else:
                raise ValueError('Unsupported encoder format: ' + fmt)
    return bytes(out)


def downsample(pixels, w: int, h: int, scalar: bool):
    nw, nh = max(1, w//2), max(1, h//2)
    result = []
    for y in range(nh):
        for x in range(nw):
            # Integer box partition also consumes an odd last row/column.
            samples = [pixels[yy*w+xx] for yy in range(y*h//nh, (y+1)*h//nh)
                       for xx in range(x*w//nw, (x+1)*w//nw)]
            result.append(sum(samples)/len(samples) if scalar else
                          tuple(round(sum(p[c] for p in samples)/len(samples)) for c in range(len(samples[0]))))
    return result, nw, nh


def dds_header(width: int, height: int, mips: int, fmt: str, bc4_header='DX10') -> bytes:
    mip_sizes_check = list(mip_sizes(width, height, mips))
    del mip_sizes_check
    flags = 0x81007 | (0x20000 if mips > 1 else 0)
    top = ((width+3)//4)*((height+3)//4)*BLOCK_BYTES[fmt]
    fourcc = {'BC1_UNORM': b'DXT1', 'BC3_UNORM': b'DXT5', 'BC4_UNORM': bc4_header.encode('ascii')}[fmt]
    if fmt == 'BC4_UNORM' and fourcc not in (b'DX10', b'ATI1', b'BC4U'):
        raise ValueError('Unsupported BC4 DDS header')
    out = b'DDS ' + struct.pack('<7I', 124, flags, height, width, top, 0, mips)
    out += bytes(44) + struct.pack('<2I4s5I', 32, 4, fourcc, 0, 0, 0, 0, 0)
    out += struct.pack('<5I', 0x401008 if mips > 1 else 0x1000, 0, 0, 0, 0)
    if len(out) != 128:
        raise AssertionError('DDS header size')
    if fourcc == b'DX10':
        out += struct.pack('<5I', 80, 3, 0, 1, 0)  # BC4_UNORM, Texture2D, one slice.
    return out


def make_dds(pixels, width: int, height: int, fmt: str, mips: int | None = None, bc4_header='DX10') -> bytes:
    if width % 4 or height % 4:
        raise ValueError('Diagnostic top-level BC dimensions must be multiples of four')
    if mips is None:
        mips = max(width, height).bit_length()
    sizes = list(mip_sizes(width, height, mips))
    chain, current, w, h = [], pixels, width, height
    for index, size in enumerate(sizes):
        if size != (w, h):
            raise AssertionError('Mipmap dimensions')
        chain.append(encode_level(current, w, h, fmt))
        if index + 1 < mips:
            current, w, h = downsample(current, w, h, fmt == 'BC4_UNORM')
    payload = b''.join(chain)
    if len(payload) != payload_size(width, height, mips, fmt):
        raise AssertionError('BC payload length')
    return dds_header(width, height, mips, fmt, bc4_header) + payload


def inspect_dds(raw: bytes) -> dict:
    if len(raw) < 128 or raw[:4] != b'DDS ':
        raise ValueError('Not a complete DDS header')
    if struct.unpack_from('<I', raw, 4)[0] != 124 or struct.unpack_from('<I', raw, 76)[0] != 32:
        raise ValueError('Invalid DDS header structure')
    height, width = struct.unpack_from('<2I', raw, 12)
    mips = max(1, struct.unpack_from('<I', raw, 28)[0])
    fourcc = raw[84:88]
    offset, dxgi, layers, dimension = 128, None, 1, 3
    cube = bool(struct.unpack_from('<I', raw, 112)[0] & 0x200)
    fmt = {b'DXT1': 'BC1_UNORM', b'DXT5': 'BC3_UNORM', b'ATI1': 'BC4_UNORM', b'BC4U': 'BC4_UNORM'}.get(fourcc)
    if fourcc == b'DX10':
        if len(raw) < 148:
            raise ValueError('Truncated DX10 extension')
        dxgi, dimension, misc, layers, _ = struct.unpack_from('<5I', raw, 128)
        cube = bool(misc & 4)
        fmt = {71: 'BC1_UNORM', 77: 'BC3_UNORM', 80: 'BC4_UNORM'}.get(dxgi)
        offset = 148
    result = dict(width=width, height=height, mips=mips, fourcc=fourcc.decode('ascii', 'replace'),
                  dxgi=dxgi, format=fmt, data_offset=offset, payload_bytes=len(raw)-offset,
                  dimension=dimension, array_size=layers, cube=cube)
    if fmt and dimension == 3 and layers == 1 and not cube:
        expected = payload_size(width, height, mips, fmt)
        result.update(expected_payload_bytes=expected, payload_size_matches=expected == len(raw)-offset)
    return result


def decode_bc4_top(raw: bytes) -> list[float]:
    d = inspect_dds(raw)
    if d['format'] != 'BC4_UNORM' or d['dimension'] != 3 or d['array_size'] != 1 or d['cube']:
        raise ValueError('Expected one BC4_UNORM Texture2D')
    if not d.get('payload_size_matches'):
        raise ValueError('DDS mip payload size mismatch')
    w, h, start = d['width'], d['height'], d['data_offset']
    pixels = [0.]*(w*h)
    blocks_w = (w+3)//4
    for by in range((h+3)//4):
        for bx in range(blocks_w):
            off = start + (by*blocks_w+bx)*8
            block = decode_bc4_block(raw[off:off+8])
            for y in range(4):
                for x in range(4):
                    xx, yy = 4*bx+x, 4*by+y
                    if xx < w and yy < h:
                        pixels[yy*w+xx] = block[4*y+x]
    return pixels


def resource_name(stem: str, raw: bytes, suffix: str) -> str:
    return stem + '.' + sha256(raw)[:16] + suffix


def plane_model(name: str, bounds_xz, world_y: float, material: str, resources: dict,
                resource_prefix: str, uv7_flip=False):
    """Four vertices; game-centimetre Y-up, with the inspected 180-degree object matrix."""
    x0, x1, z0, z1 = map(float, bounds_xz)
    if not all(math.isfinite(v) for v in (x0, x1, z0, z1, world_y)) or min(x1-x0, z1-z0) <= 0:
        raise ValueError('Invalid plane dimensions')
    world = [(x0, world_y, z0), (x1, world_y, z0), (x1, world_y, z1), (x0, world_y, z1)]
    p = [(-x, y, -z) for x, y, z in world]
    lo = [min(v[i] for v in p) for i in range(3)]
    hi = [max(v[i] for v in p) for i in range(3)]
    center = [(a+b)/2 for a, b in zip(lo, hi)]
    span = max(b-a for a, b in zip(lo, hi))
    offset = [lo[i] if lo[i] == hi[i] else center[i]-span/2 for i in range(3)]
    quant = [[round((v[i]-offset[i])/span*65535) for i in range(3)] + [65535] for v in p]
    pos_bytes = b''.join(struct.pack('<4H', *q) for q in quant)
    uv0 = [(0., 0.), (1., 0.), (1., 1.), (0., 1.)]
    uv7 = [(1-u if uv7_flip else u, v) for u, v in [(0.03, 0.03), (0.97, 0.03), (0.97, 0.97), (0.03, 0.97)]]
    def uv_encode(values):
        low = [min(v[i] for v in values) for i in range(2)]
        high = [max(v[i] for v in values) for i in range(2)]
        off = [(a+b)/2 for a, b in zip(low, high)]
        scale = [(b-a)/2 for a, b in zip(low, high)]
        qs = [tuple(round((v[i]-off[i])/scale[i]*32767) for i in range(2)) for v in values]
        return qs, {'Format': 'R16G16_SNORM', 'Offset': off+[0., 0.], 'Scale': scale+[1., 1.]}
    uq, us = uv_encode(uv0)
    lq, ls = uv_encode(uv7)
    upper_and_up = 0xDFE00000 | 512 | (1023 << 10)
    ub = b''.join(struct.pack('<2h', *q) for q in uq)
    attrs = b''.join(struct.pack('<I4h', upper_and_up, *q, *r) for q, r in zip(uq, lq))
    indices = (0, 2, 1, 0, 3, 2)  # +Y winding in world and model coordinates.
    ib = struct.pack('<6H', *indices)
    def add(kind, raw):
        key = resource_name(resource_prefix + '_' + kind, raw, '.bin')
        if key in resources and resources[key] != raw:
            raise ValueError('Resource ID collision')
        resources[key] = raw
        return key
    radius = math.sqrt(sum(((b-a)/2)**2 for a, b in zip(lo, hi)))
    bounds = {'Min': lo, 'Max': hi, 'Center': center, 'Radius': radius}
    density = [1/(x1-x0), 1/(z1-z0)]
    duv = {f'Duv{i}': density[:] for i in (0, 1, 2)}
    duv['Duv7'] = [0.94*v for v in density]
    prim = {'Material': material, 'Mesh': name+':mesh', 'Type': 'TRIANGLE_LIST',
            'BlendIndexRange': [0, 0], 'Start': 0, 'Count': 6, 'LodList': [{'Start': 0, 'Count': 6}],
            **copy.deepcopy(bounds), **copy.deepcopy(duv)}
    vf = {'POSITION0': {'Format': 'R16G16B16A16_UNORM', 'Offset': offset+[0.], 'Scale': [span]*3+[1.]},
          'TANGENTFRAME0': {'Format': 'R10G10B10A2_UINT', 'Stream': 2},
          'TEXCOORD0': {**us, 'Stream': 1},
          'TEXCOORD2': {**copy.deepcopy(us), 'Stream': 2, 'ByteOffset': 4},
          'TEXCOORD7': {**ls, 'Stream': 2, 'ByteOffset': 8}}
    model = {'Clod': {'DataBuildMode': '2K26_FAST', 'Flag_ContinuousIndexBuffers': 1,
                      'Lods': {'Lod0': {'NumMaskBits': 0, 'NumVertices': 4, 'NumIndices': 6, 'NumTris': 2}}},
             **bounds, **duv, 'BlendIndexOffset': 1, 'BlendIndexRange': [0, 0], 'Transform': {name: None},
             'Prim': [prim], 'VertexFormat': vf,
             'IndexBuffer': {'Format': 'R16_UINT', 'Size': len(ib), 'Binary': add('IndexBuffer', ib)},
             'IndexBufferCrc32': zlib.crc32(ib),
             'VertexStream': [{'Stride': stride, 'Size': len(raw), 'Binary': add('VertexBuffer', raw)}
                              for stride, raw in ((8, pos_bytes), (4, ub), (12, attrs))]}
    obj = {'Type': 'OBJECT', 'Target': name, 'Matrix': ROTATED[:]}
    return model, obj
