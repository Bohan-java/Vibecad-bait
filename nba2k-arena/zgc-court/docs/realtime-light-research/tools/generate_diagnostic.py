#!/usr/bin/env python3
"""One-spot diagnostic payload generator. Python 3.10+, stdlib only.

READS only explicitly supplied workspace copies. WRITES only a new directory
under WORKSPACE/docs/realtime-light-research. NEVER writes an IFF or a game
installation. Unknown light-brick semantics remain explicit experiments.

Experiments:
  append       add a SPOT after Sun; old index buffer untouched.
  alias        same light; point the existing descriptor at a prefixed copy of the old buffer.
  word64-2     same SCNE as alias; change only raw uint32 word 64: 1 -> 2.
               REQUIRES --ack-unverified-word64. This is NOT a verified index rebuild.
  prepend      add the SPOT before Sun; old index bytes untouched (order/slot hypothesis).
  movable      append, changing only VC_IsMovable=1 relative to append.

Every variant starts from the SAME clean current-night workspace source.
Do not apply one variant on top of another. See README_ZH.md for the A/B sequence.
"""
from __future__ import annotations
import argparse
import copy
import json
import math
from pathlib import Path
import struct
import sys
import zipfile
from rtl_common import Bundle, GRID_KEY, GRID_MEMBER, JsonSource, PREFIX, load_scne, require, sha256

EXPECTED_GRID_SHA256 = '331ee7990a7da5e63a86c8c7b108b7d10d330dd83e4bb227bafc70d1195eb535'
LIGHT_NAME = PREFIX + 'center_spot'
NEW_BINARY = PREFIX + 'light_brick_diag.gz'
NEW_MEMBER = PREFIX + 'light_brick_diag.bin'
EXPERIMENTS = ('append','alias','word64-2','prepend','movable')


def workspace_path(root: Path, value: Path | str, must_exist=True) -> Path:
    p=Path(value)
    p=(p if p.is_absolute() else root/p).resolve()
    require(p.is_relative_to(root), 'Path outside the explicitly selected workspace: '+str(p))
    blocked={'steamapps','nba 2k26','nba2k26'}
    require(not any(part.casefold() in blocked for part in p.parts),
            'Refusing a path resembling a game installation; use a project copy')
    if must_exist:
        require(p.exists(), 'Missing workspace input: '+str(p))
    return p


def spot_from_official(subset: dict, *, height=800.0, intensity=363_000_000.0,
                       far_plane=1600.0, casts_shadows=1, normal_bias=0.5, movable=0):
    for v in (height,intensity,far_plane,normal_bias):
        require(math.isfinite(v), 'Non-finite light parameter')
    require(100.0 <= height <= 1100.0, 'Diagnostic height must remain 100..1100 world cm')
    require(0.0 <= intensity <= 1e12, 'Intensity must be 0..1e12')
    require(far_plane > height and far_plane <= 10000, 'Far plane must exceed height and be <=10000')
    require(casts_shadows in (0,1) and movable in (0,1), 'Invalid Boolean light field')
    require(0 <= normal_bias <= 10, 'Normal bias outside diagnostic range')
    source_name, template=next((k,v) for k,v in subset['Light'].items() if v['Type']=='SPOT')
    light=copy.deepcopy(template)
    light['Intensity']=float(intensity)
    light['Color']=[0.82,0.91,1.0,1.0]
    light['Translate']=[0.0,float(height),0.0]  # WORLD cm; do not apply the model 180-degree transform.
    a=light['Attribute']
    a.update(VC_AimDirection=[0.0,-1.0,0.0,0.0],
             VC_FarPlane=float(far_plane), VC_CastsShadows=int(casts_shadows),
             VC_IgnoreDynamicCasters=0, VC_IsNightOnly=0, VC_IsActive=1,
             vc_ingame_light=1, VC_IsMovable=int(movable),
             VC_LocatorName=LIGHT_NAME, VC_NormalBias=float(normal_bias))
    # Keep official cone, penumbra, falloff, NearPlane=25, PresentationLightId=0, etc.
    return light, source_name


def validate_current(doc: dict, grid: bytes, ours: dict):
    require(set(doc).issuperset({'level'}), 'A complete level.SCNE is required; a subset JSON cannot be used')
    lv=doc['level']
    require(all(s in lv and isinstance(lv[s],dict) for s in ('Light','Object','Texture','Material','Model','Effect')),
            'Missing complete level sections; do not use level_light_subset.json as level.SCNE')
    require(list(lv['Light'])==['Sun'], 'Start from the clean current-night baseline containing only Sun')
    require(lv['Light']['Sun']['Type']=='DIRECTIONAL', 'Unexpected Sun type')
    for section in lv.values():
        if isinstance(section,dict):
            require(not any(k.startswith(PREFIX) for k in section), 'Existing research prefix: use the clean baseline')
    require(lv['Object']['LIGHT_PROBE_GRID_DATA']['Attribute']['USE_RELIGHTING']==0,
            'USE_RELIGHTING must already be 0; this tool will not change it')
    for k in ('LIGHT_BRICK_MAP_BUILD','LIGHT_BRICK_MAP_DATA'):
        require(lv['Object'][k]==ours['Object_LIGHT_markers'][k], 'Unsupported marker variant: '+k)
    require(lv['Texture'][GRID_KEY]==ours['Texture_LIGHT'][GRID_KEY], 'Unsupported grid descriptor variant')
    require(sha256(grid)==EXPECTED_GRID_SHA256, 'Grid bytes differ from the specifically studied sample')
    require(len(grid)==9_643_472, 'Wrong grid size')


def prepare_payload(raw: bytes, grid: bytes, ours: dict, official: dict, *, experiment='append',
                    ack_unverified=False, height=800.0, intensity=363_000_000.0,
                    far_plane=1600.0, casts_shadows=1, normal_bias=0.5):
    require(experiment in EXPERIMENTS, 'Unknown experiment')
    require(experiment!='word64-2' or ack_unverified,
            'word64-2 is an unverified raw-word experiment. Read the report; explicitly pass --ack-unverified-word64')
    source=JsonSource(raw)
    validate_current(source.doc,grid,ours)
    light, template_name=spot_from_official(official,height=height,intensity=intensity,
                    far_plane=far_plane,casts_shadows=casts_shadows,normal_bias=normal_bias,
                    movable=int(experiment=='movable'))
    edits=[source.insert_light(LIGHT_NAME,light,prepend=experiment=='prepend')]
    additions={}
    word_change=None
    if experiment in ('alias','word64-2'):
        mutated=bytearray(grid)
        if experiment=='word64-2':
            require(struct.unpack_from('<I',grid,256)[0]==1,'Unexpected word 64')
            require(struct.unpack_from('<I',grid,260)[0]==1,'Unexpected adjacent word 65')
            struct.pack_into('<I',mutated,256,2)
            require(mutated[:256]==grid[:256] and mutated[260:]==grid[260:], 'Unexpected buffer edits')
            word_change={'byte_offset':256,'word_index':64,'before_u32':1,'after_u32':2,
                         'actual_changed_byte_offsets':[256],
                         'evidence_type':'hypothesis experiment; semantic meaning not established'}
        additions[NEW_MEMBER]=bytes(mutated)
        start,end=source.span(('level','Texture',GRID_KEY,'Binary'))
        edits.append((start,end,json.dumps(NEW_BINARY)))
    new_raw=source.patch(edits)
    new_doc=load_scne(new_raw)
    before=source.doc['level']; after=new_doc['level']
    expected=copy.deepcopy(source.doc)
    if experiment=='prepend':
        expected['level']['Light']={LIGHT_NAME:light,**expected['level']['Light']}
    else:
        expected['level']['Light'][LIGHT_NAME]=light
    if additions:
        expected['level']['Texture'][GRID_KEY]['Binary']=NEW_BINARY
    require(new_doc==expected, 'Unexpected semantic scene mutation')
    require(list(after['Light'])==list(expected['level']['Light']), 'Light order differs from plan')
    require(after['Light']['Sun']==before['Light']['Sun'],'Sun definition changed')
    require(after['Object']==before['Object'],'An Object or marker changed')
    require(source.patch([])==raw,'No-op source roundtrip failed')
    for s in before:
        if s not in ('Light','Texture'):
            require(before[s]==after[s], 'Forbidden change to section '+s)
    files={'replacements/level.SCNE':new_raw}
    added_records=[]
    # Do not create filenames containing ':' on disk (Windows ADS/invalid path issue).
    # Native archive names live only in the manifest and extra mapping.
    for i,(name,data) in enumerate(additions.items()):
        rel=f'members/{i:04d}.bin'
        files[rel]=data
        added_records.append({'archive_name':name,'payload_path':rel,'bytes':len(data),'sha256':sha256(data)})
    manifest={
        'format':'zgc_rtl_diagnostic_payload_v1','game_tested':False,
        'generic_light_brick_encoder':False,'experiment':experiment,
        'input_level_sha256':sha256(raw),'output_level_sha256':sha256(new_raw),
        'input_grid_sha256':sha256(grid),'source_light_template':template_name,
        'new_light_name':LIGHT_NAME,'new_light':light,
        'light_order_before':list(before['Light']),'light_order_after':list(after['Light']),
        'replace':[{'archive_name':'level.SCNE','payload_path':'replacements/level.SCNE',
                    'bytes':len(new_raw),'sha256':sha256(new_raw)}],
        'add':added_records,'remove':[],
        'word_change':word_change,
        'protected':{'PostEffect.FxTweakables':'never emitted/replaced',
                     'all_existing_Object_entries':'unchanged; includes all LIGHT markers',
                     'USE_RELIGHTING':0,'existing_probe_descriptors':'unchanged',
                     'existing_probe_payloads':'never emitted/replaced',
                     'Sun_definition':'unchanged; runtime effect of a candidate index remap is unverified',
                     'existing_SCNE_source':'original source text retained except new light insertion and optional Binary string'},
        'interpretation_warning':(
            'word64=2 would select candidate bit 1 only if this word is a light mask and the engine light order matches. '
            'It could instead be a count, flag, or indirection; no game success or crash safety is asserted.'
            if experiment=='word64-2' else
            'This tests registration/order/resource resolution only; it does not restore proven historical light identities.'),
        'packaging_warning':'Use the complete replacement SCNE. A dict.update delta loses the prepend order experiment. Keep every unrelated archive member.',
    }
    return files, manifest


def read_source_iff(path: Path):
    with zipfile.ZipFile(path,'r') as z:
        names=z.namelist()
        require(len(names)==len(set(names)),'Duplicate source IFF members')
        require('PostEffect.FxTweakables' in names,'Missing baseline PostEffect.FxTweakables')
        raw=z.read('level.SCNE')
        lv=load_scne(raw)['level']
        ref=lv['Texture'][GRID_KEY]['Binary']
        candidates=[ref,ref[:-3]+'.bin'] if ref.endswith('.gz') else [ref]
        present=[n for n in candidates if n in z.NameToInfo]
        require(len(present)==1,'Ambiguous or unresolved grid resource; do not guess the selected member')
        data=z.read(present[0])
        require(not data.startswith(b'\x1f\x8b'),'Actual gzip resource differs from the studied raw .bin alias')
        # Metadata-only coverage for unchanged members; not a full archive hash.
        records={i.filename:{'crc32':i.CRC,'bytes':i.file_size} for i in z.infolist() if i.filename!='level.SCNE'}
        return raw,data,{'kind':'workspace IFF copy','grid_archive_member':present[0],
                         'PostEffect_sha256':sha256(z.read('PostEffect.FxTweakables')),
                         'unchanged_member_metadata':records,
                         'metadata_warning':'CRC/size inventory is an extra packaging check, not a cryptographic byte proof for all members'}


def write_payload(out: Path, files: dict, manifest: dict):
    require(not out.exists(),'Output directory already exists; choose a new experiment directory')
    out.mkdir(parents=True)
    for rel,data in files.items():
        p=out/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    # This is a small transfer payload, never a complete game package.
    with zipfile.ZipFile(out/'payload.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for rel,data in files.items(): z.writestr(rel,data)
        z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf8'))


def load_extra(payload_dir: Path | str, source_archive=None) -> dict[str,bytes]:
    """Bridge for existing packaging code: extra = load_extra(payload_dir, current_zip).

    The caller owns packaging. This function never creates/modifies an IFF.
    The source argument is mandatory so a payload cannot silently target another base.
    """
    root=Path(payload_dir).resolve()
    m=json.loads((root/'manifest.json').read_text(encoding='utf8'))
    require(m['format']=='zgc_rtl_diagnostic_payload_v1','Unknown payload format')
    require(source_archive is not None,'Pass the clean current ZipFile to verify the payload base')
    require(sha256(source_archive.read('level.SCNE'))==m['input_level_sha256'],'Wrong packaging baseline SCNE')
    base=load_scne(source_archive.read('level.SCNE'))['level']
    grid_ref=base['Texture'][GRID_KEY]['Binary']
    grid_candidates=[grid_ref,grid_ref[:-3]+'.bin'] if grid_ref.endswith('.gz') else [grid_ref]
    grid_members=[n for n in grid_candidates if n in source_archive.NameToInfo]
    require(len(grid_members)==1,'Ambiguous or missing packaging baseline grid')
    require(sha256(source_archive.read(grid_members[0]))==m['input_grid_sha256'],'Wrong packaging baseline grid bytes')
    if m.get('source',{}).get('PostEffect_sha256'):
        require(sha256(source_archive.read('PostEffect.FxTweakables'))==m['source']['PostEffect_sha256'],
                'Wrong baseline PostEffect')
    extra={}
    for item in m['replace']+m['add']:
        name=item['archive_name']
        require(name=='level.SCNE' or name.startswith(PREFIX),'Forbidden archive mutation')
        require(name not in extra,'Duplicate payload archive name')
        p=(root/item['payload_path']).resolve()
        require(p.is_relative_to(root),'Payload path escapes directory')
        data=p.read_bytes()
        require(sha256(data)==item['sha256'] and len(data)==item['bytes'],'Payload integrity failure')
        extra[name]=data
    for item in m['add']:
        require(item['archive_name'] not in source_archive.NameToInfo,'New member already exists in baseline')
    require(not m['remove'],'Removal is forbidden in this diagnostic')
    return extra


def verify_packed(path: Path, payload: Path):
    m=json.loads((payload/'manifest.json').read_text(encoding='utf8'))
    with zipfile.ZipFile(path,'r') as z:
        require(len(z.namelist())==len(set(z.namelist())),'Duplicate final IFF members')
        for rec in m['replace']+m['add']:
            require(sha256(z.read(rec['archive_name']))==rec['sha256'],'Final payload member differs: '+rec['archive_name'])
        lv=load_scne(z.read('level.SCNE'))['level']
        require(list(lv['Light'])==m['light_order_after'],'Final light order changed')
        require(lv['Light'][LIGHT_NAME]==m['new_light'],'Final diagnostic light changed')
        require(lv['Object']['LIGHT_PROBE_GRID_DATA']['Attribute']['USE_RELIGHTING']==0,'Relighting changed')
        source=m.get('source',{})
        if source.get('unchanged_member_metadata'):
            expected_names=set(source['unchanged_member_metadata'])|{'level.SCNE'}|{r['archive_name'] for r in m['add']}
            require(set(z.namelist())==expected_names,'Unexpected added/removed final archive members')
        if source.get('PostEffect_sha256'):
            require(sha256(z.read('PostEffect.FxTweakables'))==source['PostEffect_sha256'],'PostEffect bytes changed')
        for name,meta in source.get('unchanged_member_metadata',{}).items():
            require(name in z.NameToInfo,'Unrelated source member removed: '+name)
            i=z.getinfo(name)
            require(i.CRC==meta['crc32'] and i.file_size==meta['bytes'],'Unrelated member metadata changed: '+name)
        covered=bool(source.get('PostEffect_sha256'))
    return {'payload_members_match':True,'light_order_matches':True,
            'PostEffect_and_original_member_inventory_covered':covered,
            'game_tested':False,
            'warning':None if covered else 'SCNE-only input supplied no baseline PostEffect/member inventory; verify those separately'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    g=sub.add_parser('generate',help='Generate a small payload from a clean workspace copy')
    g.add_argument('--workspace',required=True,type=Path);g.add_argument('--bundle',required=True,type=Path)
    src=g.add_mutually_exclusive_group(required=True)
    src.add_argument('--input-iff',type=Path);src.add_argument('--scene',type=Path)
    g.add_argument('--grid',type=Path,help='Required with --scene; explicit raw grid .bin copy')
    g.add_argument('--out',required=True,type=Path);g.add_argument('--experiment',choices=EXPERIMENTS,default='append')
    g.add_argument('--ack-unverified-word64',action='store_true')
    g.add_argument('--intensity',type=float,default=363_000_000.0)
    g.add_argument('--height',type=float,default=800.0)
    g.add_argument('--far-plane',type=float,default=1600.0)
    g.add_argument('--casts-shadows',type=int,choices=[0,1],default=1)
    g.add_argument('--normal-bias',type=float,default=0.5)
    v=sub.add_parser('verify',help='Read back an already packaged WORKSPACE test copy')
    v.add_argument('--workspace',required=True,type=Path);v.add_argument('--input-iff',required=True,type=Path)
    v.add_argument('--payload',required=True,type=Path)
    a=p.parse_args();root=a.workspace.resolve();require(root.is_dir(),'Workspace must exist')
    if a.command=='verify':
        result=verify_packed(workspace_path(root,a.input_iff),workspace_path(root,a.payload))
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    out=workspace_path(root,a.out,must_exist=False)
    require(out.is_relative_to((root/'docs/realtime-light-research').resolve()),
            'Outputs must stay under workspace/docs/realtime-light-research')
    require(not out.exists(),'Output directory already exists')
    bundle_path=workspace_path(root,a.bundle)
    if a.input_iff:
        require(a.grid is None,'--grid is only for --scene mode')
        raw,grid,source=read_source_iff(workspace_path(root,a.input_iff))
    else:
        require(a.grid is not None,'--scene mode also requires --grid')
        raw=workspace_path(root,a.scene).read_bytes();grid=workspace_path(root,a.grid).read_bytes()
        source={'kind':'exported full JSON SCNE plus raw grid','PostEffect_sha256':None,
                'unchanged_member_metadata':{},'warning':'No complete archive supplied: PostEffect/member inventory not covered'}
    with Bundle(bundle_path) as b:
        require(sha256(b.read('ours/'+GRID_MEMBER))==EXPECTED_GRID_SHA256,'Different research bundle')
        files,manifest=prepare_payload(raw,grid,b.json('ours/level_light_subset.json'),
                        b.json('donors/arena_020_int/level_light_subset.json'),
                        experiment=a.experiment,ack_unverified=a.ack_unverified_word64,
                        height=a.height,intensity=a.intensity,far_plane=a.far_plane,
                        casts_shadows=a.casts_shadows,normal_bias=a.normal_bias)
    manifest['source']=source
    write_payload(out,files,manifest)
    print(json.dumps({'output':str(out),'experiment':a.experiment,
                       'light_order':manifest['light_order_after'],'added_member_count':len(manifest['add']),
                       'raw_grid_changed_byte_count':1 if manifest['word_change'] else 0,
                       'game_tested':False,'complete_IFF_written':False},ensure_ascii=False,indent=2))

if __name__=='__main__':
    try: main()
    except (ValueError,KeyError,OSError,zipfile.BadZipFile,StopIteration) as e:
        raise SystemExit(str(e))
