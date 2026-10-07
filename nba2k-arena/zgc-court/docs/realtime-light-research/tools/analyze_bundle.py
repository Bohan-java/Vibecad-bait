#!/usr/bin/env python3
"""Reproduce the binary/SCNE observations. Stdlib only. Never writes game files.

Usage: python -S analyze_bundle.py --bundle realtime_light_research.zip --out NEW_DIRECTORY
No generic LIGHT_BRICK_MAP decoder/encoder is claimed. Competing address
interpretations are intentionally retained in the machine-readable evidence.
"""
from __future__ import annotations
import argparse
import array
import ast
import collections
import csv
import itertools
import json
import math
from pathlib import Path
import struct
import sys
import zipfile
from rtl_common import Bundle, GRID_KEY, GRID_MEMBER, read_donor, require, sha256, supplied_binary_reader


def words_le(raw: bytes):
    require(len(raw) % 4 == 0, 'Not an integral number of uint32 words')
    out = array.array('I')
    out.frombytes(raw)
    require(out.itemsize == 4, 'This interpreter does not use 4-byte unsigned int')
    if sys.byteorder != 'little':
        out.byteswap()
    return out


def descriptor_layout(subset: dict) -> dict:
    attrs = subset['Object_LIGHT_markers']['LIGHT_BRICK_MAP_DATA']['Attribute']
    build = subset['Object_LIGHT_markers']['LIGHT_BRICK_MAP_BUILD']['Attribute']
    tex = subset['Texture_LIGHT'][GRID_KEY]
    dims = attrs['GRID_DIMENSIONS'][:3]
    coarse = [int(x) for x in build['gridDimensions'][:3]]
    require(all(x > 0 for x in dims + coarse), 'Invalid dimensions')
    n = math.prod(coarse)
    o0, o1, o2, o3 = [attrs[f'GRID_DATA_OFFSETS_{i}'] for i in range(4)]
    rows = o0 - o3
    width = attrs['MAX_LIGHT_BITMASK_WORDS']
    return {
        'evidence_type': 'data/arithmetic; region semantics unconfirmed',
        'version': attrs['VERSION'], 'fine_dimensions': dims,
        'build_dimensions': coarse, 'dimension_ratio': [a/b for a,b in zip(dims,coarse)],
        'fine_cell_count': math.prod(dims), 'coarse_record_count_candidate': n,
        'offsets_decimal': [o0,o1,o2,o3], 'offsets_hex': [hex(x) for x in [o0,o1,o2,o3]],
        'offset2_low16': o2 & 65535, 'offset2_high16': o2 >> 16,
        'max_light_bitmask_words': width, 'grid_light_capacity': attrs['GRID_LIGHT_CAPACITY'],
        'height_words': tex['Height'], 'bytes': tex['PixelDataSize'],
        'height_times_four_matches_bytes': tex['Height'] * 4 == tex['PixelDataSize'],
        'prefix_multiple_of_64': o1 % 64 == 0, 'prefix_64_word_blocks_candidate': o1 // 64,
        'candidate_mask_rows': rows, 'mask_region_words': o3-o1,
        'row_width_equation_matches': (o3-o1) == width * rows,
        'directory_end_word_candidate': o0+2*n,
        'trailer_words_candidate': tex['Height']-(o0+2*n),
        'binary_reference': tex['Binary'],
    }


def inspect_grid(raw: bytes, subset: dict):
    meta = descriptor_layout(subset)
    attrs = subset['Object_LIGHT_markers']['LIGHT_BRICK_MAP_DATA']['Attribute']
    w = words_le(raw)
    require(len(raw) == meta['bytes'], 'Actual size differs from descriptor')
    require(len(w) == meta['height_words'], 'Height differs from uint32 count')
    o0,o1,o2,o3 = meta['offsets_decimal']
    n = meta['coarse_record_count_candidate']
    end = o0+2*n
    require(0 <= o1 <= o3 <= o0 <= end <= len(w), 'Candidate region boundaries invalid')
    require(meta['row_width_equation_matches'], 'Candidate region-width equation failed')
    record_counts = collections.Counter((w[o0+2*i],w[o0+2*i+1]) for i in range(n))
    rare = min(record_counts, key=record_counts.get)
    rare_indices = [i for i in range(n) if (w[o0+2*i],w[o0+2*i+1]) == rare]
    dims = meta['build_dimensions']
    coords = [(i % dims[0], (i//dims[0]) % dims[1], i//(dims[0]*dims[1])) for i in rare_indices]
    bounds = [(min(c[k] for c in coords), max(c[k] for c in coords)) for k in range(3)]
    rectangular = len(coords) == math.prod(hi-lo+1 for lo,hi in bounds)
    axis_candidates = []
    for permutation in itertools.permutations(range(3)):
        a,b,c = [dims[k] for k in permutation]
        xyz = [(i%a,(i//a)%b,i//(a*b)) for i in rare_indices]
        box = [(min(v[k] for v in xyz), max(v[k] for v in xyz)) for k in range(3)]
        axis_candidates.append({'fast_to_slow_axes': ''.join('xyz'[k] for k in permutation),
                                'shape': [a,b,c], 'bounds': box,
                                'fills_bounding_box': len(xyz)==math.prod(hi-lo+1 for lo,hi in box)})
    address16 = []
    tagged32 = []
    for (a,b), count in sorted(record_counts.items()):
        ok16 = 0 <= a*2 <= len(raw)-2
        ok32 = 0 <= (a >> 1)*4 <= len(raw)-4
        address16.append({'record_low32': a, 'record_high32': b, 'count': count,
                          'byte_offset': a*2, 'in_bounds': ok16,
                          'u16_at_target': struct.unpack_from('<H',raw,a*2)[0] if ok16 else None})
        tagged32.append({'record_low32': a, 'record_high32': b, 'count': count,
                         'low_bit': a&1, 'word_offset': a >> 1, 'in_bounds': ok32,
                         'u32_at_target': w[a >> 1] if ok32 else None})
    origin_offset = attrs['GRID_ORIGIN_OFFSET'][:3]
    cell = attrs['GRID_CELL_SIZE']
    # This coordinate convention is an inference, checked against the probe marker.
    origin = [origin_offset[0]-meta['fine_dimensions'][0]*cell/2,
              origin_offset[1], origin_offset[2]-meta['fine_dimensions'][2]*cell/2]
    brick_span = 4*cell
    world_bounds = [[origin[k]+bounds[k][0]*brick_span,
                     origin[k]+(bounds[k][1]+1)*brick_span] for k in range(3)]
    fine_center = [math.floor(-origin[k]/cell) for k in range(3)]
    center = [x//4 for x in fine_center]
    ci = center[0]+dims[0]*(center[1]+dims[1]*center[2])
    probe = subset['Object_LIGHT_markers'].get('LIGHT_PROBE_GRID_DATA',{}).get('Attribute',{})
    width = meta['max_light_bitmask_words']
    candidate_bits = sorted({32*(i%width)+bit for i,x in enumerate(w[o1:o3])
                             for bit in range(32) if x & (1<<bit)})
    # This reconstructs the observed byte layout; it deliberately preserves opaque data.
    rebuilt = bytearray(raw[:o0*4])
    for i in range(n):
        rebuilt += struct.pack('<II', w[o0+2*i], w[o0+2*i+1])
    rebuilt += raw[end*4:]
    result = {
        'status': 'structural observations only; generic decoder not established',
        'sha256': sha256(raw), 'layout': meta,
        'gzip_magic_present': raw.startswith(b'\x1f\x8b'), 'first_32_bytes_hex': raw[:32].hex(),
        'byte_histogram': dict(sorted(collections.Counter(raw).items())),
        'uint32_histogram': {str(k):v for k,v in sorted(collections.Counter(w).items())},
        'prefix_words': list(w[:o1]), 'candidate_mask_words': list(w[o1:o3]),
        'candidate_aux_words': list(w[o3:o0]), 'conditional_bit_positions': candidate_bits,
        'conditional_bit_positions_warning': 'Valid only if the candidate region is a uint32 light-membership bitmap; not verified runtime light IDs.',
        'record_counts': [{'low32':a,'high32':b,'count':c} for (a,b),c in sorted(record_counts.items())],
        'trailer_start_word': end, 'trailer_start_byte': end*4,
        'trailer_uint32': list(w[end:]),
        'trailer_uint16': list(struct.unpack('<'+'H'*((len(raw)-end*4)//2),raw[end*4:])),
        'competing_model_u16_offsets': address16,
        'competing_model_tagged_u32_offsets': tagged32,
        'both_address_models_fit_this_sample': all(x['in_bounds'] for x in address16+tagged32),
        'rare_record': list(rare), 'rare_record_count': len(coords),
        'rare_record_linear_index_bounds': [min(rare_indices),max(rare_indices)],
        'rare_record_coarse_bounds_xyz_inclusive': bounds, 'rare_records_fill_box': rectangular,
        'axis_order_candidates': axis_candidates,
        'world_coordinate_inference': {
            'evidence_type': 'inference, not confirmed shader coordinate transform',
            'formula': 'origin=(offset.x-D.x*h/2, offset.y, offset.z-D.z*h/2); fine=floor((p-origin)/h); brick=fine//4; linear=x+Bx*(y+By*z)',
            'fine_cell_cm_candidate': cell, 'brick_width_cm_candidate': brick_span,
            'origin_cm': origin, 'matches_probe_grid_origin': origin==probe.get('GRID_ORIGIN',[])[:3],
            'rare_record_world_bounds_cm_half_open': world_bounds,
            'center_fine_cell': fine_center, 'center_coarse_cell': center,
            'center_linear_record': ci, 'center_record_word_offset': o0+2*ci,
            'center_record': [w[o0+2*ci], w[o0+2*ci+1]],
        },
        'reassembly_byte_identical': bytes(rebuilt)==raw,
        'reassembly_warning': 'Structural reassembly retains opaque regions; this is not a semantic encode/decode roundtrip.'
    }
    return result, [(i,*c) for i,c in zip(rare_indices,coords)]


def donor_scan(doc, raw, kind, subset):
    level = doc['level']
    locators = [l.get('Attribute',{}).get('VC_LocatorName') for l in level['Light'].values()]
    locators = [s for s in locators if s]
    hits, duplicates, brick_refs, shadow_paths = [], [], [], []
    def walk(v,path=()):
        if isinstance(v,dict):
            for k,c in v.items():
                if '#dup' in k: duplicates.append(list(path+(k,)))
                if path and path[0]!='Light' and any(s in k for s in locators):
                    hits.append({'path':list(path+(k,)),'kind':'key'})
                if 'LIGHT_BRICK_MAP' in k:
                    brick_refs.append({'path':list(path+(k,)), 'kind':'key'})
                if k in ('VC_FloorShadowMultiplier','VC_NBAArenaLighting'):
                    shadow_paths.append({'path':list(path+(k,)),'value':c})
                walk(c,path+(k,))
        elif isinstance(v,list):
            for i,c in enumerate(v): walk(c,path+(i,))
        elif isinstance(v,str):
            if path and path[0]!='Light' and any(s in v for s in locators):
                hits.append({'path':list(path),'kind':'string','value':v})
            if 'light_brick_map' in v.lower():
                brick_refs.append({'path':list(path),'value':v})
    walk(level)
    sample_effect = next((k for k in level.get('Effect',{}) if k.startswith('asset_CLOD.fx')), None)
    shaders = []
    if sample_effect:
        ef=level['Effect'][sample_effect]
        for tn,tech in ef.get('Technique',{}).items():
            if tn != 'AssetHiresLightmap': continue
            for pn,p in tech.get('Pass',{}).items():
                if pn in ('Projected','UseSoftShadowMaps','UseHardShadowMaps','OnlyDepthCSM'):
                    shaders.append({'effect':sample_effect,'technique':tn,'pass':pn,
                                    'enable_mask':p.get('EnableMask'),
                                    'PS':p.get('PS',{}).get('Binary'),
                                    'VS':p.get('VS',{}).get('Binary'),
                                    'ResourceMapping':p.get('ResourceMapping')})
    return {'raw_sha256':sha256(raw),'format':kind,'light_matches_supplied_subset':level['Light']==subset['Light'],
            'light_order': [{'scene_order':i,'name':k,**v} for i,(k,v) in enumerate(level['Light'].items())],
            'locator_occurrences_outside_light':hits, 'duplicate_key_paths':duplicates,
            'light_brick_map_references':brick_refs,
            'extra_markers':{k:level['Object'].get(k) for k in ['LINELIGHTSHADOWINGSPOTS','LINELIGHTSPOTAPPROXIMATIONSCALER','TIME_OF_DAY']},
            'other_lighting_fields':shadow_paths, 'shader_candidates_not_proven_brick_consumers':shaders}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    a=p.parse_args(); require(not a.out.exists(),'Output directory must be new')
    with Bundle(a.bundle) as b:
        subsets={name:b.json(name+'/level_light_subset.json') for name in ['ours','donors/arena_020_int','donors/arena_blacktop_ext']}
        data=b.read('ours/'+GRID_MEMBER)
        grid, rows=inspect_grid(data,subsets['ours'])
        reader=supplied_binary_reader(b)
        donors={}
        for name in ['arena_020_int','arena_blacktop_ext']:
            raw=b.read('donors/'+name+'/level.SCNE.raw')
            doc,kind=read_donor(raw,reader)
            donors[name]=donor_scan(doc,raw,kind,subsets['donors/'+name])
        n4=b.read('ours/n4_light_schema.md').decode('utf8').split('```python',1)[1].split('```',1)[0]
        # The supplied excerpt ends with an incomplete _box header; only the two complete factories are needed.
        tree=ast.parse(n4.split('\ndef lights(',1)[0]); n4_keys={}
        for fun in (n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('spot','line')):
            ret=next(n for n in fun.body if isinstance(n,ast.Return)).value
            attrs=next(v for k,v in zip(ret.keys,ret.values) if isinstance(k,ast.Constant) and k.value=='Attribute')
            n4_keys[fun.name]=[k.value for k in attrs.keys]
        source_audit={}
        for typ,fun in [('SPOT','spot'),('AREA','line')]:
            native=next(v for v in subsets['donors/arena_020_int']['Light'].values() if v['Type']==typ)
            keys=set(native['Attribute'])
            source_audit[typ]={'official_attribute_keys':sorted(keys),'N4_attribute_keys':sorted(n4_keys[fun]),
                               'missing_in_N4':sorted(keys-set(n4_keys[fun])), 'extra_in_N4':sorted(set(n4_keys[fun])-keys)}
        paths=['ours/level_light_subset.json','ours/'+GRID_MEMBER,'ours/n4_light_schema.md',
               'donors/arena_020_int/level.SCNE.raw','donors/arena_020_int/level_light_subset.json',
               'donors/arena_blacktop_ext/level.SCNE.raw','donors/arena_blacktop_ext/level_light_subset.json',
               'tools/night_lighting.py','tools/night_scene.py','tools/repair_iff.py','tools/native_floor_overlay.py',
               'tools/make_light_research_bundle.py','tools/iff_codec.py','tools/native_archive.py']
        hashes={s:{'bytes':len(b.read(s)),'sha256':sha256(b.read(s))} for s in paths}
        a.out.mkdir(parents=True)
        results={'grid_analysis.json':grid,'descriptor_comparison.json':{k:descriptor_layout(v) for k,v in subsets.items()},
                 'donor_scene_analysis.json':donors,'n4_schema_comparison.json':source_audit,'input_sha256.json':hashes}
        for name,value in results.items():
            (a.out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        with (a.out/'rare_record_cells.csv').open('w',newline='',encoding='utf8') as f:
            writer=csv.writer(f);writer.writerow(['linear_index','brick_x','brick_y','brick_z']);writer.writerows(rows)
        print(json.dumps({'grid_sha256':grid['sha256'],'grid_bytes':len(data),'candidate_rows':grid['layout']['candidate_mask_rows'],
                          'rare_records':len(rows),'both_address_models_fit':grid['both_address_models_fit_this_sample'],
                          'structural_reassembly_exact':grid['reassembly_byte_identical'],
                          'official_locator_hits':len(donors['arena_020_int']['locator_occurrences_outside_light']),
                          'N4_SPOT_missing_keys':source_audit['SPOT']['missing_in_N4'],
                          'semantic_decoder_status':'NOT_ESTABLISHED','game_tested':False},indent=2))

if __name__=='__main__':
    try: main()
    except (ValueError,KeyError,OSError,zipfile.BadZipFile) as e:
        raise SystemExit(str(e))
