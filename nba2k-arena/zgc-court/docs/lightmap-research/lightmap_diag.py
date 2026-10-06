#!/usr/bin/env python3
"""Read-only IFF inventory and additive 4 m x 4 m diagnostic bundle generator.

Python 3.10+, standard library only. Does not write IFFs, install mods, run game
code, load Blender, import tools/, or touch production output/source/bake files.
All writes are exclusive, inside a NEW subdirectory of this research directory.
See REPORT_ZH.md and README.md for limitations and in-game interpretation.
"""
from __future__ import annotations

import argparse
import base64
import collections
import copy
import csv
import io
import json
import math
from pathlib import Path
import re
import struct
import sys
sys.dont_write_bytecode = True
import zipfile

from codec_stdlib import (IDENTITY, ROTATED, decode_bc4_top, dump_native,
                          inspect_dds, load_scne, make_dds, plane_model,
                          resource_name, sha256)

HERE = Path(__file__).resolve().parent
# Deployment: nba2k-arena/zgc-court/docs/lightmap-research/.
WORKSPACE = HERE.parents[2]  # nba2k-arena; existing local donor copies allowed.
BASELINE_COMMIT = 'abd8643af109fd93720595157b8f4792f0e14bcb'
PREFIX = 'zgc_lmresearch_v1:'
LAMP_OBJECT = ('park_streetball_a_master@park_rucker_ext_shared@GameObjects@'
               'GameObjectGroup_121@light_lamppost_genericb_19:light_lamppost_genericb_low')
SCONCE_MATERIAL = 'light_lampsconce_swirls:light_lampsconce_swirls_mat'
CUP_MATERIAL = 'cup_coffee_papercrumpled:cup_mat'
MAX_SCNE = 128*1024*1024
MAX_MEMBER = 8*1024*1024
MAX_EXTRACTION = 24*1024*1024
SECTION_NAMES = ('Texture', 'Material', 'Model', 'Object')


def read_path(value, *, inside=WORKSPACE) -> Path:
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_relative_to(inside.resolve()) or not path.is_file():
        raise ValueError('Input must be a regular file inside the project workspace: ' + str(inside))
    return path


def new_output(relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or not rel.parts:
        raise ValueError('Output must be a new relative directory below docs/lightmap-research')
    target = HERE / rel
    if not target.resolve().is_relative_to(HERE) or target.exists() or target.is_symlink():
        raise ValueError('Refusing existing output or path escape: ' + str(target))
    # Reject symlinks in all existing parent components, including internal aliases.
    current = HERE
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Output symlink is not allowed')
    target.mkdir(parents=True, exist_ok=False)
    return target


def write_new(path: Path, raw: bytes):
    if not path.parent.resolve().is_relative_to(HERE):
        raise ValueError('Output is outside the research directory')
    with path.open('xb') as f:
        f.write(raw)


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')


def member_name(z, ref: str) -> str:
    # Match tools/repair_iff.present, including preference when both entries exist.
    if ref in z.NameToInfo:
        return ref
    alternate = ref[:-4]+'.dds' if ref.endswith('.tld') else ref[:-3]+'.bin' if ref.endswith('.gz') else None
    if alternate in z.NameToInfo:
        return alternate
    raise KeyError(ref)


def read_member(z, name: str, limit=MAX_MEMBER) -> bytes:
    info = z.getinfo(name)
    if info.flag_bits & 1 or info.file_size > limit:
        raise ValueError('Encrypted member or member exceeds read budget: ' + name)
    return z.read(info)


def open_archive(path: Path):
    with path.open('rb') as f:
        head = f.read(200)
    if head.startswith(b'version https://git-lfs.github.com/spec/v1'):
        raise ValueError('Git LFS POINTER only; real IFF bytes have not been retrieved')
    z = zipfile.ZipFile(path, mode='r')
    names = z.namelist()
    if len(names) != len(set(names)):
        z.close()
        raise ValueError('Duplicate archive members; refusing ambiguous interpretation')
    return z


def archive_identity(z) -> str:
    # A central-directory fingerprint, NOT a whole-IFF cryptographic digest.
    rows = [(i.filename, i.CRC, i.file_size, i.compress_size, i.compress_type) for i in z.infolist()]
    return sha256(json_bytes(rows))


def iter_binaries(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if k == 'Binary' and isinstance(v, str):
                yield v
            else:
                yield from iter_binaries(v)
    elif isinstance(value, list):
        for v in value:
            yield from iter_binaries(v)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def references(level, roots):
    """Follow exact unique resource names, including short names. No guessing."""
    index = collections.defaultdict(list)
    for section, values in level.items():
        if isinstance(values, dict):
            for key in values:
                index[key].append((section, key))
    queue, seen, ambiguous = list(roots), set(), {}
    while queue:
        section, key = queue.pop()
        if (section, key) in seen:
            continue
        if len(seen) >= 10000:
            raise ValueError('Reference traversal budget exceeded')
        if key not in level.get(section, {}):
            continue
        seen.add((section, key))
        for token in strings(level[section][key]):
            choices = index.get(token, [])
            if len(choices) == 1:
                queue.append(choices[0])
            elif len(choices) > 1:
                ambiguous[token] = choices
    return sorted(seen), ambiguous


def material_passes(level, material: dict):
    effect = level.get('Effect', {}).get(material.get('Effect'), {})
    rows = []
    for source, value in [('Effect', effect), ('Material', material)]:
        for technique, t in value.get('Technique', {}).items():
            for pname, p in t.get('Pass', {}).items():
                rows.append({'source': source, 'technique': technique, 'pass': pname,
                             'enable_mask': t.get('EnableMask'),
                             'VS_input': p.get('VS', {}).get('Input'),
                             'VS_binary': p.get('VS', {}).get('Binary'),
                             'PS_binary': p.get('PS', {}).get('Binary')})
    return rows


def model_materials(model):
    current, found = None, []
    for prim in model.get('Prim', []):
        current = prim.get('Material', current)
        if current and current not in found:
            found.append(current)
    return found


def ground_candidates(level):
    found = []
    for key, obj in level.get('Object', {}).items():
        model = level.get('Model', {}).get(obj.get('Target'), {})
        low, high = model.get('Min'), model.get('Max')
        if not key.startswith('zgc_r03:') or obj.get('Type') != 'OBJECT' or not low or not high:
            continue
        if (len(low) == len(high) == 3 and abs(high[1]-low[1]) < .01
                and 1500 < high[0]-low[0] < 3000 and 2500 < high[2]-low[2] < 4500):
            found.append({'object': key, 'target': obj['Target'], 'bounds': [low, high],
                          'matrix': obj.get('Matrix'), 'materials': model_materials(model)})
    return found


def texture_scan(level, z):
    rows = []
    textures, objects, models = (level.get(k, {}) for k in ('Texture', 'Object', 'Model'))
    for key, spec in textures.items():
        if not isinstance(spec, dict) or (key not in objects and key not in models):
            continue
        row = {'key': key, 'matches_object': key in objects, 'matches_model': key in models,
               **{k: spec.get(k) for k in ('Format', 'Width', 'Height', 'Mips', 'Dimension', 'Min', 'Max',
                                           'Twiddled', 'CompressionMethod', 'PixelDataSize', 'Binary')}}
        try:
            resolved = member_name(z, spec['Binary'])
            row.update(member=resolved, archive_bytes=z.getinfo(resolved).file_size)
        except (KeyError, TypeError) as e:
            row['unresolved'] = str(e)
        rows.append(row)
    return rows


def inventory(args):
    path = read_path(args.iff)
    with open_archive(path) as z:
        raw = read_member(z, args.scene, MAX_SCNE)
        doc = load_scne(raw)
        section = args.scene.rsplit('.', 1)[0]
        if section not in doc:
            raise ValueError('SCNE root does not match scene name: ' + section)
        level = doc[section]
        rows = texture_scan(level, z)
        sample_rows = []
        used = set()
        # Round-robin formats so RGB candidates cannot crowd out all BC4 samples.
        groups = collections.defaultdict(list)
        for row in rows:
            groups[str(row.get('Format'))].append(row)
        queues = [collections.deque(groups[k]) for k in sorted(groups, key=lambda k: (k != 'BC4_UNORM', k))]
        ordered = []
        while any(queues):
            for queue in queues:
                if queue:
                    ordered.append(queue.popleft())
        for row in ordered:
            if len(sample_rows) >= args.samples:
                break
            member = row.get('member')
            if not member or member in used:
                continue
            used.add(member)
            result = {'key': row['key'], 'member': member}
            try:
                binary = read_member(z, member)
                result['sha256'] = sha256(binary)
                result['first_32_hex'] = binary[:32].hex()
                d = inspect_dds(binary)
                result['dds'] = d
                if d['format'] == 'BC4_UNORM':
                    pixels = decode_bc4_top(binary)
                    result['decoded_top_red'] = {'min': min(pixels), 'max': max(pixels),
                                                 'mean': sum(pixels)/len(pixels)}
                    result['descriptor_range_is_decode_proof'] = False
            except (ValueError, KeyError, struct.error) as e:
                result['error'] = str(e)
            sample_rows.append(result)
        mats = level.get('Material', {})
        selected_names = [n for n in (CUP_MATERIAL, SCONCE_MATERIAL, 'light_lamppost_genericb:light_mat') if n in mats]
        material_info = {name: {'definition': mats[name], 'passes': material_passes(level, mats[name])}
                         for name in selected_names}
        slots = collections.defaultdict(list)
        for name, mat in mats.items():
            for slot in mat.get('Resource', {}):
                slots[slot].append(name)
        shader_roots = [('Material', n) for n in selected_names]
        closure, ambiguous = references(level, shader_roots)
        effects = {key: level['Effect'][key] for sec, key in closure if sec == 'Effect'}
        binaries = sorted({b for sec, key in closure for b in iter_binaries(level[sec][key])})
        # All object-matched non-BC4 images are candidates, not verified RGB lightmaps.
        rgb_candidates = [r for r in rows if r.get('Format') != 'BC4_UNORM']
        bind_candidates = []
        for row in rows:
            obj = level.get('Object', {}).get(row['key'], {})
            model = level.get('Model', {}).get(obj.get('Target'), {})
            if (row.get('Format') == 'BC4_UNORM' and obj.get('UserData') and model
                    and (row.get('Width'), row.get('Height')) == (64, 64)):
                for matname in model_materials(model):
                    mat = mats.get(matname, {})
                    param = mat.get('Parameter', {})
                    if param.get('EmissiveIntensity', 0) or param.get('AlwaysEmit', 0):
                        continue
                    bind_candidates.append({'object': row['key'], 'material': matname, 'effect': mat.get('Effect'),
                                            'texture_size': [row.get('Width'), row.get('Height')],
                                            'UV7_present': 'TEXCOORD7' in model.get('VertexFormat', {}),
                                            'passes': material_passes(level, mat)})
                    if len(bind_candidates) >= 48:
                        break
            if len(bind_candidates) >= 48:
                break
        output = new_output(args.out)
        summary = {'input': str(path.relative_to(WORKSPACE)), 'iff_bytes': path.stat().st_size,
                   'scene': args.scene, 'scene_sha256': sha256(raw),
                   'central_directory_sha256': archive_identity(z),
                   'native_scne_roundtrip_identical': dump_native(doc) == raw,
                   'same_name_total': len(rows), 'formats': dict(collections.Counter(r.get('Format') for r in rows)),
                   'object_match_count': sum(r['matches_object'] for r in rows),
                   'model_match_count': sum(r['matches_model'] for r in rows),
                   'custom_object_count': sum(k.startswith('zgc_r03:') for k in level.get('Object', {})),
                   'custom_with_same_name_texture': sum(k.startswith('zgc_r03:') and k in level.get('Texture', {}) for k in level.get('Object', {})),
                   'ground_candidates': ground_candidates(level), 'sample_limit': args.samples,
                   'game_tested': False, 'shader_semantics_decoded': False}
        write_new(output/'inventory.json', json_bytes(summary))
        write_new(output/'object_texture_descriptors.json', json_bytes(rows))
        write_new(output/'texture_samples.json', json_bytes(sample_rows))
        write_new(output/'rgb_object_texture_candidates.json', json_bytes(rgb_candidates))
        write_new(output/'material_resource_slot_index.json', json_bytes(dict(slots)))
        write_new(output/'selected_materials.json', json_bytes(material_info))
        write_new(output/'selected_effects.json', json_bytes(effects))
        write_new(output/'bc4_nonemissive_donor_candidates.json', json_bytes(bind_candidates))
        write_new(output/'ambiguous_name_references.json', json_bytes(ambiguous))
        exports = []
        total = 0
        if args.extract_evidence:
            (output/'resources').mkdir()
        for ref in binaries:
            entry = {'reference': ref}
            try:
                member = member_name(z, ref)
                info = z.getinfo(member)
                entry.update(member=member, bytes=info.file_size)
                # Extract shader/code references only; full material closure remains in metadata.
                if member.lower().endswith('.dds'):
                    entry['status'] = 'texture_metadata_only'
                elif not args.extract_evidence:
                    entry['status'] = 'not_requested'
                elif info.file_size > MAX_MEMBER or total+info.file_size > MAX_EXTRACTION:
                    entry['status'] = 'budget_skipped'
                else:
                    blob = read_member(z, member)
                    total += len(blob)
                    filename = sha256(blob)+'.bin'
                    target = output/'resources'/filename
                    if not target.exists():
                        write_new(target, blob)
                    entry.update(status='extracted', sha256=sha256(blob), evidence_file='resources/'+filename,
                                 magic_hex=blob[:16].hex(),
                                 ascii_tokens=[s.decode('ascii') for s in re.findall(rb'[ -~]{5,}', blob)[:200]],
                                 note='Raw payload only; string matches do not establish shader behavior')
            except (KeyError, ValueError) as e:
                entry.update(status='unresolved_or_unreadable', reason=str(e))
            exports.append(entry)
        write_new(output/'binary_reference_manifest.json', json_bytes(exports))
    print(json.dumps({'output': str(output), 'same_name_total': len(rows), 'formats': summary['formats']}, ensure_ascii=False))


def decode_positions(z, model):
    spec = model['VertexFormat']['POSITION0']
    stream = model['VertexStream'][spec.get('Stream', 0)]
    binary = read_member(z, member_name(z, stream['Binary']))
    stride, start = stream['Stride'], spec.get('ByteOffset', 0)
    if stride <= 0 or len(binary) % stride or stream.get('Size', len(binary)) != len(binary):
        raise ValueError('Position stream size mismatch')
    fmt = spec['Format']
    code, denom = ('<4H', 65535.) if fmt == 'R16G16B16A16_UNORM' else ('<3f', 1.) if fmt == 'R32G32B32_FLOAT' else (None, None)
    if not code or start+struct.calcsize(code) > stride:
        raise ValueError('Unsupported position layout')
    scale, offset = spec.get('Scale', [1]*4), spec.get('Offset', [0]*4)
    values = [tuple(struct.unpack_from(code, binary, i+start)[j]/denom*scale[j]+offset[j] for j in range(3))
              for i in range(0, len(binary), stride)]
    if not values or any(not math.isfinite(x) for v in values for x in v):
        raise ValueError('Invalid positions')
    return values


def inside_triangle_xz(point, tri, eps=1e-4):
    x, z = point
    signs = [(b[0]-a[0])*(z-a[2])-(b[2]-a[2])*(x-a[0]) for a, b in zip(tri, tri[1:]+tri[:1])]
    area = (tri[1][0]-tri[0][0])*(tri[2][2]-tri[0][2])-(tri[1][2]-tri[0][2])*(tri[2][0]-tri[0][0])
    return abs(area) > eps and (min(signs) >= -eps or max(signs) <= eps)


def validate_ground(level, z, name, cx, cz):
    if name is None:
        candidates = ground_candidates(level)
        if len(candidates) != 1:
            raise ValueError('Ground object is ambiguous; select --ground-object from inventory.json')
        name = candidates[0]['object']
    obj = level.get('Object', {}).get(name)
    if not obj or not name.startswith('zgc_r03:') or obj.get('Type') != 'OBJECT':
        raise ValueError('Select one existing zgc_r03 ground OBJECT')
    model = level['Model'][obj['Target']]
    matrix = obj.get('Matrix', IDENTITY)
    if matrix not in (IDENTITY, ROTATED):
        raise ValueError('Ground matrix must be the inspected identity or 180-degree rotation')
    p = decode_positions(z, model)
    if matrix == ROTATED:
        p = [(-x, y, -zz) for x, y, zz in p]
    if max(v[1] for v in p)-min(v[1] for v in p) > 1e-3:
        raise ValueError('Selected ground is not a single horizontal plane')
    if model['IndexBuffer']['Format'] != 'R16_UINT':
        raise ValueError('Unsupported ground index format')
    ib = read_member(z, member_name(z, model['IndexBuffer']['Binary']))
    if len(ib) % 2:
        raise ValueError('Invalid ground index buffer')
    ix = struct.unpack('<'+'H'*(len(ib)//2), ib)
    triangles = []
    for prim in model['Prim']:
        if prim.get('Type') != 'TRIANGLE_LIST':
            raise ValueError('Ground primitive type is not supported')
        start, count = prim.get('Start', 0), prim['Count']
        if start < 0 or count % 3 or start+count > len(ix):
            raise ValueError('Ground primitive range invalid')
        for i in range(start, start+count, 3):
            ids = ix[i:i+3]
            if max(ids) >= len(p):
                raise ValueError('Ground index out of range')
            triangles.append([p[j] for j in ids])
    if len(triangles) > 100000:
        raise ValueError('Ground validation triangle budget exceeded')
    # Nine coverage samples, including patch corners and center. The intended ground is rectangular.
    for x in (cx-200, cx, cx+200):
        for zz in (cz-200, cz, cz+200):
            if not any(inside_triangle_xz((x, zz), tri) for tri in triangles):
                raise ValueError('4m test region extends beyond the selected ground')
    return {'object': name, 'model': obj['Target'], 'world_y_cm': p[0][1],
            'matrix': matrix, 'nine_coverage_samples_passed': True}


def lightmap_binding(level, z, object_name):
    obj = level.get('Object', {}).get(object_name)
    spec = level.get('Texture', {}).get(object_name)
    if not obj or not spec or obj.get('Target') not in level.get('Model', {}):
        raise ValueError('Donor must have Object, target Model and same-name Texture')
    userdata = obj.get('UserData')
    if not isinstance(userdata, str) or len(base64.b64decode(userdata, validate=True)) != 48:
        raise ValueError('Expected donor 48-byte UserData; do not invent it')
    if spec.get('Format') != 'BC4_UNORM' or spec.get('Dimension', 'TEXTURE2D') not in ('TEXTURE2D', '2D'):
        raise ValueError('Donor is not a supported BC4 Texture2D')
    native_member = member_name(z, spec['Binary'])
    raw = read_member(z, native_member)
    d = inspect_dds(raw)
    if d['format'] != 'BC4_UNORM' or not d.get('payload_size_matches'):
        raise ValueError('Donor DDS must contain a complete BC4 mip chain')
    if d['width'] != spec['Width'] or d['height'] != spec['Height'] or d['mips'] != spec.get('Mips', 1):
        raise ValueError('Donor SCNE and DDS dimensions/mips disagree')
    if (d['width'], d['height']) != (64, 64):
        raise ValueError('This minimal diagnostic intentionally requires a 64x64 donor')
    return copy.deepcopy(spec), userdata, d


def compatible_material(level, name, *, lightmapped=False, nonemissive=False):
    if name not in level.get('Material', {}):
        raise ValueError('Missing material: ' + str(name))
    mat = copy.deepcopy(level['Material'][name])
    if mat.get('Parameter', {}).get('AlphaStyle', 'OPAQUE') != 'OPAQUE':
        raise ValueError('Diagnostic requires an opaque donor')
    effect = level.get('Effect', {}).get(mat.get('Effect'))
    if not effect:
        raise ValueError('Cannot verify donor Effect metadata')
    inputs = set(effect.get('VertexFormat', {}))
    if 'WEIGHTDATA0' in inputs:
        raise ValueError('Skinned donor cannot be used on the diagnostic static plane')
    passes = material_passes(level, mat)
    if lightmapped and not any('Lightmap' in p['technique'] and p['pass'] == 'GBuffer' and p['VS_binary'] and p['PS_binary'] for p in passes):
        raise ValueError('No complete native Lightmap GBuffer shader pair was found')
    if nonemissive and (mat.get('Parameter', {}).get('EmissiveIntensity', 0) or mat.get('Parameter', {}).get('AlwaysEmit', 0)):
        raise ValueError('Choose a non-emissive lightmapped material for the BC4 experiment')
    for technique in mat.get('Technique', {}).values():
        for state in technique.get('Pass', {}).values():
            if state.get('DEPTHBIAS', 0) or state.get('SLOPESCALEDEPTHBIAS', 0):
                raise ValueError('Donor has a depth bias; select an unbiased opaque donor')
    return mat


def add_texture(additions, resources, name, pixels, fmt, width=64, height=64,
                mips=None, linear=False, template=None, header='DX10', resource_prefix='zgc_lmresearch_v1'):
    raw = make_dds(pixels, width, height, fmt, mips, header)
    d = inspect_dds(raw)
    member = resource_name(resource_prefix+'_texture', raw, '.dds')
    resources[member] = raw
    spec = copy.deepcopy(template) if template else {}
    spec.update(Width=width, Height=height, Mips=d['mips'], Format=fmt,
                PixelDataSize=d['payload_bytes'], Binary=member[:-4]+'.tld')
    if template is None:
        spec.update(Min=[0., 0., 0., 0. if fmt == 'BC3_UNORM' else 1.], Max=[1., 1., 1., 1.])
    if linear:
        spec['TexelUsage'] = 'LINEAR'
    additions['Texture'][name] = spec
    return name


def chart_scalar(w=64, flip=False):
    # Left quarter bright, right half mid-gray, plus a dark horizontal notch.
    pixels = []
    for y in range(w):
        for x in range(w):
            xx = w-1-x if flip else x
            value = 230 if xx < w//4 else 100 if xx >= w//2 else 26
            if w//2 <= y < 3*w//4 and xx < 3*w//4:
                value = 0
            pixels.append(value)
    return pixels


def chart_rgb(w=64):
    # Warm pool and a simulated occluder stripe; corner RGB tags detect channel/UV mistakes.
    pixels = []
    for y in range(w):
        for x in range(w):
            u, v = (x+.5)/w, (y+.5)/w
            pool = max(0., 1-((u-.48)/.46)**2-((v-.48)/.43)**2)
            if .36 <= u <= .45 and v > .3:
                pool = 0.
            pixel = tuple(round(c*pool) for c in (180, 92, 32))
            if x < 8 and y < 8:
                pixel = (180, 0, 0)
            elif x >= w-8 and y < 8:
                pixel = (0, 180, 0)
            elif x < 8 and y >= w-8:
                pixel = (0, 0, 180)
            pixels.append(pixel)
    return pixels


def check_additive(base_doc, additions):
    if set(additions) != set(SECTION_NAMES):
        raise ValueError('Only Texture/Material/Model/Object additions are allowed')
    changed = copy.deepcopy(base_doc)
    level = changed['level']
    for section, values in additions.items():
        if not isinstance(values, dict) or section not in level:
            raise ValueError('Invalid addition section')
        for name, value in values.items():
            if not name.startswith(PREFIX) or name in level[section]:
                raise ValueError('Pre-existing key or wrong diagnostic namespace: ' + name)
            level[section][name] = copy.deepcopy(value)
    # Full document equality after removing exactly the inserted keys.
    restored = copy.deepcopy(changed)
    for section, values in additions.items():
        for key in values:
            del restored['level'][section][key]
    if restored != base_doc:
        raise AssertionError('Unrelated SCNE data changed')
    return changed


def make_plan(z, args):
    raw = read_member(z, 'level.SCNE', MAX_SCNE)
    doc = load_scne(raw)
    if dump_native(doc) != raw:
        raise ValueError('SCNE does not round-trip byte-identically through native serializer; inventory only')
    level = doc['level']
    if any(k.startswith(PREFIX) for s in SECTION_NAMES for k in level.get(s, {})):
        raise ValueError('Input already contains this diagnostic; start from the untouched baseline')
    ground = validate_ground(level, z, args.ground_object, args.x_cm, args.z_cm)
    if args.minmax_native and args.mode != 'minmax':
        raise ValueError('--minmax-native applies only to minmax')
    if args.invert_bc4 and args.mode not in ('bc4', 'uv7-flip'):
        raise ValueError('--invert-bc4 applies only to bc4 / uv7-flip')
    if not math.isfinite(args.emission_scale) or not 0 <= args.emission_scale <= 10:
        raise ValueError('--emission-scale must be finite and in [0,10]')
    if not (0 < args.offset_cm <= .1):
        raise ValueError('Diagnostic geometric offset must be positive and <= 0.1 cm')
    if not (math.isfinite(args.x_cm) and math.isfinite(args.z_cm)):
        raise ValueError('Invalid world position')
    additions = {k: {} for k in SECTION_NAMES}
    resources, tiles = {}, []
    stem = 'zgc_lmresearch_v1'  # Same IDs across A/B runs when bytes are identical.
    owner = LAMP_OBJECT if args.mode == 'emission' else args.lm_object
    if not owner:
        raise ValueError('BC4 tests require --lm-object and --lm-material from the inventory')
    lm_spec, userdata, native_dds = lightmap_binding(level, z, owner)
    if args.metadata == 'plain':
        for key in ('Twiddled', 'CompressionMethod'):
            lm_spec.pop(key, None)
    mat_name = SCONCE_MATERIAL if args.mode == 'emission' else args.lm_material
    mat_template = compatible_material(level, mat_name, lightmapped=True, nonemissive=args.mode != 'emission')
    if args.mode != 'emission' and mat_name not in model_materials(level['Model'][level['Object'][owner]['Target']]):
        raise ValueError('Selected BC4 material does not belong to the selected native donor')
    if 'AlbedoMap' not in mat_template.get('Resource', {}):
        raise ValueError('Selected donor has no confirmed AlbedoMap slot')
    common_albedo = PREFIX+'neutral-albedo'
    common_normal = PREFIX+'neutral-normal-rough'
    common_metal = PREFIX+'neutral-metal'
    add_texture(additions, resources, common_albedo, [(80, 80, 80)]*16, 'BC1_UNORM', 4, 4, resource_prefix=stem)
    add_texture(additions, resources, common_normal, [(128, 128, 0, 240)]*16, 'BC3_UNORM', 4, 4, linear=True, resource_prefix=stem)
    add_texture(additions, resources, common_metal, [(0, 0, 0)]*16, 'BC1_UNORM', 4, 4, linear=True, resource_prefix=stem)
    if args.mode == 'emission':
        for key in ('EmissiveIntensity', 'EmissiveTint', 'AlwaysEmit'):
            if key not in mat_template.get('Parameter', {}):
                raise ValueError('Missing verified sconce parameter: '+key)
        if 'EmissiveAlbedoMap' not in mat_template.get('Resource', {}):
            raise ValueError('Missing verified EmissiveAlbedoMap slot')
        emission_key = PREFIX+'emission-chart'
        add_texture(additions, resources, emission_key, chart_rgb(), 'BC1_UNORM', resource_prefix=stem)
    for index in range(4):
        row, col = divmod(index, 2)
        x0 = args.x_cm-200+col*202
        z0 = args.z_cm-200+row*202
        bounds = (x0, x0+198, z0, z0+198)
        name, matkey = PREFIX+f'tile-{index}', PREFIX+f'mat-{index}'
        mat = copy.deepcopy(mat_template)
        mat['Resource']['AlbedoMap'] = {'Pixelmap': common_albedo}
        if 'NormalAndRoughMap' in mat['Resource']:
            mat['Resource']['NormalAndRoughMap'] = {'Pixelmap': common_normal}
        if 'MetalMap' in mat['Resource']:
            mat['Resource']['MetalMap'] = {'Pixelmap': common_metal}
        if 'AlbedoModulate' in mat.get('Parameter', {}):
            mat['Parameter']['AlbedoModulate'] = [1., 1., 1., 1.]
        if args.mode == 'emission':
            gain = (0., 30., 300., 3000.)[index] * args.emission_scale
            mat['Resource']['EmissiveAlbedoMap'] = {'Pixelmap': emission_key}
            mat['Parameter'].update(EmissiveIntensity=gain, EmissiveTint=[1., 1., 1.], AlwaysEmit=1)
            additions['Texture'][name] = copy.deepcopy(lm_spec)  # exact native DDS reference, never rewritten.
            meaning = f'emission gain {gain:g}; same RGB chart, same donor BC4'
        else:
            if args.mode in ('bc4', 'uv7-flip'):
                pixels = ([0]*4096, [128]*4096, [255]*4096, chart_scalar())[index]
                if args.invert_bc4:
                    pixels = [255-v for v in pixels]
                meaning = ('BC4 q=0', 'BC4 q=128/255', 'BC4 q=1', 'asymmetric BC4 pattern')[index]
            elif args.mode == 'minmax':
                pixels = [128]*4096
                meaning = 'native range' if args.minmax_native else ('native range', 'range [0,1]', 'range [0,2]', 'range [0.25,1.25]')[index]
            elif args.mode == 'bound-control':
                pixels, meaning = None, 'unmodified native same-name DDS descriptor'
            else:
                raise ValueError('Unknown experiment mode')
            if pixels is None:
                additions['Texture'][name] = copy.deepcopy(lm_spec)
            else:
                add_texture(additions, resources, name, pixels, 'BC4_UNORM',
                            mips=native_dds['mips'], template=lm_spec,
                            header=native_dds['fourcc'], resource_prefix=stem)
            if args.mode == 'minmax' and index and not args.minmax_native:
                a, b = ((0., 1.), (0., 2.), (.25, 1.25))[index-1]
                additions['Texture'][name]['Min'][0] = a
                additions['Texture'][name]['Max'][0] = b
        additions['Material'][matkey] = mat
        model, obj = plane_model(name, bounds, ground['world_y_cm']+args.offset_cm, matkey,
                                 resources, stem, uv7_flip=args.mode == 'uv7-flip')
        obj['UserData'] = userdata
        additions['Model'][name], additions['Object'][name] = model, obj
        tiles.append({'index': index, 'object': name, 'world_bounds_xz_cm': list(bounds),
                      'meaning': meaning, 'UV7_horizontal_flipped': args.mode == 'uv7-flip'})
    changed = check_additive(doc, additions)
    for name in resources:
        if name in z.NameToInfo:
            raise ValueError('New binary collides with an existing archive name: '+name)
    # Closure of every Binary reference in the added definitions.
    unresolved = []
    for ref in set(iter_binaries(additions)):
        resolved = ref[:-4]+'.dds' if ref.endswith('.tld') else ref[:-3]+'.bin' if ref.endswith('.gz') else ref
        if ref not in resources and resolved not in resources:
            try:
                member_name(z, ref)
            except KeyError:
                unresolved.append(ref)
    if unresolved:
        raise ValueError('Unresolved added binary references: '+repr(unresolved))
    if sha256(dump_native(doc)) != sha256(raw):
        raise AssertionError('Original scene changed')
    manifest = {'schema': 1, 'base_commit_for_code_review': BASELINE_COMMIT,
                'experiment': args.mode, 'metadata_policy': args.metadata,
                'invert_bc4': args.invert_bc4, 'emission_scale': args.emission_scale,
                'minmax_native': args.minmax_native,
                'base_scene_sha256': sha256(raw), 'base_central_directory_sha256': archive_identity(z),
                'base_postfx_sha256': sha256(read_member(z, 'PostEffect.FxTweakables')) if 'PostEffect.FxTweakables' in z.NameToInfo else None,
                'planned_scene_sha256': sha256(dump_native(changed)), 'namespace': PREFIX,
                'ground': ground, 'patch_bounds_world_cm': [args.x_cm-200, args.x_cm+200, args.z_cm-200, args.z_cm+200],
                'offset_cm': args.offset_cm, 'tiles': tiles, 'binding_donor_object': owner,
                'material_donor': mat_name, 'preserved_native_bc4_header': native_dds['fourcc'],
                'added_keys': {s: list(v) for s, v in additions.items()},
                'members': [{'name': n, 'bytes': len(b), 'sha256': sha256(b)} for n, b in sorted(resources.items())],
                'untouched': ['All pre-existing SCNE values', 'Light', 'LIGHT_PROBE_GRID_*', 'LIGHT_BRICK_MAP', 'PostEffect.FxTweakables', 'all existing archive payloads except the planned level.SCNE replacement'],
                'artifact_type': 'logical additions plus small DDS/BIN payloads; not a game-loadable IFF',
                'game_tested': False,
                'warnings': ['Positive geometric offset can still cover player indicators. No safe offset is asserted.',
                             'Visibility of these four tiles is not proof of the shader lighting equation.',
                             'This generated chart is a diagnostic, not a Cycles bake.']}
    return additions, resources, manifest


def plan(args):
    source = read_path(args.iff)
    with open_archive(source) as z:
        additions, resources, manifest = make_plan(z, args)
    output = new_output(args.out)
    (output/'members').mkdir()
    write_new(output/'additions.json', json_bytes(additions))
    manifest['additions_sha256'] = sha256(json_bytes(additions))
    write_new(output/'manifest.json', json_bytes(manifest))
    for name, raw in resources.items():
        write_new(output/'members'/name, raw)
    print(json.dumps({'output': str(output), 'new_member_bytes': sum(map(len, resources.values())),
                      'new_members': len(resources), 'iff_written': False}, ensure_ascii=False))


def load_bundle(bundle: Path):
    bundle = bundle.resolve(strict=True)
    if not bundle.is_relative_to(HERE) or not bundle.is_dir():
        raise ValueError('Bundle must reside inside docs/lightmap-research')
    manifest = json.loads(read_path(bundle/'manifest.json', inside=HERE).read_text('utf-8'))
    add_raw = read_path(bundle/'additions.json', inside=HERE).read_bytes()
    if sha256(add_raw) != manifest['additions_sha256']:
        raise ValueError('Additions manifest digest mismatch')
    additions = json.loads(add_raw)
    resources = {}
    total = 0
    for row in manifest['members']:
        name = row['name']
        if Path(name).name != name or '/' in name or '\\' in name or not name.endswith(('.dds', '.bin')):
            raise ValueError('Unsafe or unexpected bundle member name')
        path = read_path(bundle/'members'/name, inside=bundle)
        if row['bytes'] > MAX_MEMBER or path.stat().st_size != row['bytes']:
            raise ValueError('Bundle member size mismatch')
        raw = path.read_bytes()
        total += len(raw)
        if total > MAX_EXTRACTION or sha256(raw) != row['sha256'] or name in resources:
            raise ValueError('Bundle digest, size or uniqueness check failed')
        resources[name] = raw
    return additions, resources, manifest


def build_replacements(z, bundle: Path) -> dict[str, bytes]:
    """Return extra/replacements for an existing packer. NEVER writes an archive."""
    additions, resources, manifest = load_bundle(bundle)
    raw = read_member(z, 'level.SCNE', MAX_SCNE)
    if sha256(raw) != manifest['base_scene_sha256'] or archive_identity(z) != manifest['base_central_directory_sha256']:
        raise ValueError('Baseline has changed; regenerate the diagnostic from that baseline')
    if any(name in z.NameToInfo for name in resources):
        raise ValueError('Binary name collision')
    post = sha256(read_member(z, 'PostEffect.FxTweakables')) if 'PostEffect.FxTweakables' in z.NameToInfo else None
    if post != manifest['base_postfx_sha256']:
        raise ValueError('PostFX mismatch')
    doc = load_scne(raw)
    changed = check_additive(doc, additions)
    out = dump_native(changed)
    if sha256(out) != manifest['planned_scene_sha256']:
        raise ValueError('Planned scene digest mismatch')
    return {'level.SCNE': out, **resources}


def reverse_document(patched_raw: bytes, base_raw: bytes, additions: dict) -> bytes:
    """In-memory inverse; refuses unrelated edits and altered diagnostic entries."""
    doc = load_scne(patched_raw)
    for section, values in additions.items():
        for name, value in values.items():
            if doc['level'][section].get(name) != value:
                raise ValueError('Diagnostic entry has changed; refusing broad deletion')
            del doc['level'][section][name]
    result = dump_native(doc)
    if result != base_raw:
        raise ValueError('Rollback would not reproduce the exact baseline SCNE')
    return result


def compose(args):
    source = read_path(args.iff)
    bundle = Path(args.bundle)
    if not bundle.is_absolute():
        bundle = HERE / bundle
    with open_archive(source) as z:
        replacements = build_replacements(z, bundle)
        additions, _, manifest = load_bundle(bundle)
        reverse_document(replacements['level.SCNE'], read_member(z, 'level.SCNE', MAX_SCNE), additions)
    output = new_output(args.out)
    for name, raw in replacements.items():
        write_new(output/name, raw)
    write_new(output/'compose_receipt.json', json_bytes({'scene_sha256': manifest['planned_scene_sha256'],
              'exact_rollback_verified': True, 'iff_written': False, 'entries': len(replacements)}))
    print(json.dumps({'output': str(output), 'iff_written': False, 'exact_rollback_verified': True}, ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    scan = sub.add_parser('inventory', help='Read explicit IFF only; report texture/material/binary evidence')
    scan.add_argument('--iff', required=True)
    scan.add_argument('--scene', default='level.SCNE')
    scan.add_argument('--samples', type=int, default=24)
    scan.add_argument('--extract-evidence', action='store_true')
    scan.add_argument('--out', required=True, help='New directory relative to docs/lightmap-research')
    scan.set_defaults(func=inventory)
    make = sub.add_parser('plan', help='Generate logical additions + small resources; never a full IFF')
    make.add_argument('--iff', required=True)
    make.add_argument('--mode', choices=('bound-control', 'bc4', 'uv7-flip', 'minmax', 'emission'), required=True)
    make.add_argument('--ground-object')
    make.add_argument('--lm-object')
    make.add_argument('--lm-material')
    make.add_argument('--x-cm', type=float, default=0.)
    make.add_argument('--z-cm', type=float, default=700.)
    make.add_argument('--offset-cm', type=float, default=.01)
    make.add_argument('--metadata', choices=('clone', 'plain'), default='clone')
    make.add_argument('--invert-bc4', action='store_true', help='Swap q and 1-q at identical world positions')
    make.add_argument('--minmax-native', action='store_true', help='Keep native ranges on all four q=128 tiles for a same-position baseline')
    make.add_argument('--emission-scale', type=float, default=1., help='Use 0 for the exact-position emission-off control')
    make.add_argument('--out', required=True)
    make.set_defaults(func=plan)
    comp = sub.add_parser('compose', help='Optional small SCNE/member output and exact inverse check; no IFF')
    comp.add_argument('--iff', required=True)
    comp.add_argument('--bundle', required=True, help='Relative to research directory, or an absolute path within it')
    comp.add_argument('--out', required=True)
    comp.set_defaults(func=compose)
    args = parser.parse_args(argv)
    if args.command == 'inventory' and not 1 <= args.samples <= 128:
        parser.error('--samples must be 1..128')
    try:
        args.func(args)
    except (ValueError, KeyError, FileNotFoundError, zipfile.BadZipFile, PermissionError,
            struct.error, UnicodeError, TypeError, OverflowError) as e:
        print('ERROR: '+str(e), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
