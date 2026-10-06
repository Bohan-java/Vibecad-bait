"""Current compatibility repair: keep source art and validate engine resources.

This is an engine-oriented candidate, not an assertion of a successful game run.
Only the project directory is modified. The user's actual Blacktop slot is 700.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import zipfile
import zlib
from iff_codec import load_scne
from native_archive import write_compatible
from r04_materials import add_neutral_resources,repair_materials

ROOT=Path(__file__).resolve().parents[1]
DONOR=ROOT.parent/'洛克公园/arena_blacktop_ext.iff'

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def dump_native(doc):
    return (json.dumps(doc,ensure_ascii=True,indent='\t')[1:-1].strip()+'\n').encode('utf8')

def binaries(value):
    if isinstance(value,dict):
        for k,v in value.items():
            if k=='Binary' and isinstance(v,str):yield v
            else:yield from binaries(v)
    elif isinstance(value,list):
        for v in value:yield from binaries(v)

def present(z,name):
    if name in z.NameToInfo:return name
    if name.endswith('.tld') and name[:-4]+'.dds' in z.NameToInfo:return name[:-4]+'.dds'
    if name.endswith('.gz') and name[:-3]+'.bin' in z.NameToInfo:return name[:-3]+'.bin'
    raise KeyError(name)

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',default=str(ROOT/'output/arena_700_int.iff'))
    p.add_argument('--output',default=str(ROOT/'output/arena_700_int.iff'));args=p.parse_args()
    source=Path(args.input).resolve();output=Path(args.output).resolve()
    if not source.is_relative_to(ROOT) or not output.is_relative_to(ROOT):raise ValueError('Outside project')
    source_hash=digest(source);extra={}
    pending=output.with_suffix('.iff.pending')
    source_manifest=json.loads((ROOT/'public/manifest.json').read_text(encoding='utf8'))
    report={'revision':'R12','target':'Blacktop / arena_700_int.iff','source_iff_sha256':source_hash,
            'source_version':source_manifest['source_version'],'source_glb_sha256':source_manifest['asset']['sha256'],
            'source_feedback':'User supplied R11 gameplay screenshots: substitute players overlap and sit without benches, left context is empty, distant map edge is visible, and Chilis should have a generally rectangular footprint. R12 adds native-schema bench markers and black seating, photo-grounded left context, distant skyline screening and the corrected restaurant footprint. Replay glass remains unconfirmed.',
            'last_game_confirmed':{'revision':'R11','visibility':'gameplay_visible_context_and_bench_defects','replay_glass':'not_confirmed_by_latest_screenshots'},
            'game_tested':False,'game_visibility':'pending','confirmed_root_cause':False,
            'preserve_existing_art':True,'changes':[]}
    with zipfile.ZipFile(DONOR) as donor,zipfile.ZipFile(source) as current:
        original=load_scne(donor.read('level.SCNE'))['level']
        document=load_scne(current.read('level.SCNE'));level=document['level']
        original_custom_models=copy.deepcopy({k:v for k,v in level['Model'].items() if k.startswith('zgc_r03:')})
        neutral=add_neutral_resources(level,extra)
        report['material_repair']=repair_materials(level,original)
        # R07's ground bias wrote a camera-dependent virtual height and covered
        # player indicators. Reuse the proven unmodified opaque depth pipeline.
        from ground_depth_policy import restore_ground_depth
        labels_path=ROOT/'validation/native-source-build.json'
        labels=json.loads(labels_path.read_text(encoding='utf8')) if labels_path.exists() else None
        report['ground_depth_candidate']=restore_ground_depth(level,source_models=labels)
        report['changes'].append('Remove R07 ground depth bias from every camera pass; restore the R06 native depth pipeline so ground does not get projected over the player indicator.')
        report['changes'].append('Encode constant position axes exactly; the source ground at Y=0 no longer decodes 0.027963 cm above native zero-height player indicators.')
        from native_floor_overlay import BinaryScene
        from shared_floor_line_override import prepare_shared_line_override
        floor_path=ROOT.parent/'build/local_game_reference/levels/arena_700_int_floor.iff'
        with zipfile.ZipFile(floor_path) as floor_archive:
            floor=BinaryScene(floor_archive.read('level_floor.SCNE')).document['level_floor']
        line_resources,line_textures,line_report=prepare_shared_line_override(floor)
        for key,value in line_textures.items():
            if key in level['Texture'] and level['Texture'][key]!=value:
                raise ValueError('Conflicting native shared line texture descriptor: '+key)
        level['Texture'].update(line_textures)
        extra.update(line_resources)
        report['shared_line_candidate']=line_report
        report['changes'].append('Add native-name transparent shared line DDS aliases without modifying player resources or depth. Selection across the separate floor package remains unverified until one game check.')
        report['neutral_ao']=neutral
        report['changes'].append('Replace lightmap-only opaque shader variants with native AssetHires/AssetLores static variants; retain the original albedo and normal/roughness resources.')
        removed_transforms=0
        for name,obj in level['Object'].items():
            if name.startswith('zgc_r03:') and 'Transform' in obj:
                obj.pop('Transform');removed_transforms+=1
        report['optional_static_object_transform_removed']=removed_transforms
        # The native material helper does not invent vertex weights. A separate
        # native-schema adapter handles glass after its layout has been proven.
        from r04_glass import repair_glass
        construction=json.loads((ROOT/'validation/chilis-building-current.json').read_text(encoding='utf8'))
        guard='R02 architecture Chilis terrace side-walk glass guard'
        assert construction['status']=='passed' and construction['revision']=='R12'
        assert construction['published_source_sha256']==digest(ROOT/'source/scene.blend')
        assert guard in construction['furniture']['historical_removed_source_objects']
        assert labels['source_glb_sha256']==source_manifest['asset']['sha256']
        assert guard not in {r['source_object'] for r in labels['models']}
        replacement_frames={'R12 Chilis building terrace five wide weather screen edge strips',
                            'R12 Chilis building terrace slender ivory weather screen mullions'}
        assert replacement_frames.issubset({r['source_object'] for r in labels['models']})
        report['glass_repair']=repair_glass(level,original,current,donor,extra,source_models=labels,
                                           omitted_source_objects=(guard,))
        from native_basket_rig import attach_custom_basket
        report['basket_rig']=attach_custom_basket(level,current,donor,extra,source_models=labels)
        from r12_seating import apply_native_markers
        report['bench_seating']=apply_native_markers(level)
        report['changes'].append('Add the 44 role markers from an untouched native arena schema at distinct positions along a black right-side seating row. Whether Blacktop uses these markers remains unverified until the next in-game check.')
        report['changes'].append('Use the local original outdoor basket_glass material, including its dedicated Presentation pass, shader/script resources and native vertex/skin contract. Replay and close-view outline visibility remain unverified in game.')
        report['changes'].append('Attach the custom upper basket and weighted column to the existing native basket skeleton; retain fixed foot hardware, original rim positions/weights and all twelve native rim LOD index sequences.')
        report['changes'].append('Rebuild photo-guided narrow fence light-channel signs without emission; put the longer fence on the left when facing Chilis. Extend painted court edging and use warm gray outer paving.')
        report['changes'].append('Align free-throw arc endpoints to the painted key, add native-coordinate lane ticks and gameplay boundary lines, and turn the floor A toward the basket. Keep the calibrated yellow three-point edge.')
        report['changes'].append('Darken open-half and surrounding paving to photo-guided gray concrete, preserving low-contrast paving curves; add simple white three-point, free-throw and key lines on the open half.')
        report['changes'].append('Add the tall two-tier floodlight pole outside the left long fence using photo-relative proportions; no light emission or global lighting adjustment.')
        report['changes'].append('Rebuild Chilis as a rectangular body with long straight facade and short rounded corner returns, preserving detailed entrance, awnings, left-return terrace and furniture.')
        report['changes'].append('Add photo-grounded left-side storefront, forecourt details and planting, and distant skyline and tree screening with explicit photographic placement uncertainty; preserve court, baskets, fence, tall light pole and global lighting.')
        for name,model in original_custom_models.items():
            if name in level['Model']:
                # Opaque source position, UV and indices remain unchanged.
                after=level['Model'][name]
                for key in ('Min','Max','Center','Radius','IndexBuffer','IndexBufferCrc32'):
                    assert after[key]==model[key],(name,key)
        assert level['Light']==original['Light'] and level['Attribute']==original['Attribute']
        from half_court_orientation import apply_orientation, update_report
        update_report(report, level, apply_orientation(level))
        from night_lighting import apply_night
        report['night_lighting']={k:v for k,v in apply_night(level).items() if k not in ('before','after')}
        from night_scene import apply_scene
        report['night_scene']=apply_scene(level,current,extra)
        facade_path=ROOT/'validation/r13-chilis-material-current.json'
        if any('R13 Chili' in row.get('source_material','') for row in labels.get('textures',[])):
            facade=json.loads(facade_path.read_text(encoding='utf8'))
            assert facade['status']=='passed'
            assert facade['source_sha256']==digest(ROOT/'source/scene.blend')
            report['revision']='R13'
            report['chilis_frontage']=facade
            report['source_feedback']='User accepts the overall model and requests photo-by-photo refinement of the court-facing Chilis facade, non-emissive lightbox lettering, metal and concrete/stone material differentiation, plus less transparent and less mirror-sharp basketball glass.'
            report['changes'].append('Refine the court-facing Chilis facade from individually inspected photographs with layered non-emissive channel letters, differentiated metal/acrylic/coated surfaces, fabric, stone and concrete textures, door hardware and awning construction. Keep the rectangular site layout and corrected half-court orientation.')
            report['changes'].append('Increase native basket glass alpha and roughness using its existing dedicated render path; preserve geometry, skin weights and Presentation shaders.')
        extra['level.SCNE']=dump_native(document)
        for name in ('baskets.SCNE','speedtree.SCNE'):
            if name not in extra:extra[name]=dump_native(load_scne(current.read(name)))
        omitted={name for name in current.namelist() if name.endswith('.tld') and name not in donor.NameToInfo}
        omitted.update(name for name in extra if name.endswith('.tld') and name not in donor.NameToInfo)
        # The donor ships only DDS aliases for texture Binary .tld resources.
        # Supplying real experimental TLD bytes previously bypassed that path.
        for name in list(extra):
            if name in omitted:extra.pop(name)
        report['removed_experimental_tld_entries']=len(omitted)
        report['changes'].append('Use donor-style DDS-only texture override resources; remove the experimental direct TLD path.')
        report['changes'].append('Preserve donor entry order and metadata; use DEFLATE for all changed or new entries and formatted SCNE fragments.')
        print('Writing repaired IFF with original native archive layout',flush=True)
        count=write_compatible(donor,current,pending,extra,omitted)
        print('Checking final resource closure, shader branches and unchanged mesh payloads',flush=True)
        with zipfile.ZipFile(pending) as final:
            assert final.testzip() is None
            assert len(final.namelist())==len(set(final.namelist()))==count
            assert all(i.compress_type==zipfile.ZIP_DEFLATED for i in final.infolist())
            assert not any(n.endswith('.tld') for n in final.namelist())
            assert final.namelist()[:len(donor.namelist())]==donor.namelist()
            missing=[]
            for name in final.namelist():
                if name.endswith('.SCNE'):
                    scne=load_scne(final.read(name))
                    for binary in binaries(scne):
                        try:present(final,binary)
                        except KeyError:missing.append((name,binary))
            assert not missing,missing[:10]
            verified_buffers=set()
            for name,before in original_custom_models.items():
                if name not in level['Model']:continue
                for resource in [before['IndexBuffer'],*before['VertexStream']]:
                    key=resource['Binary']
                    if key not in verified_buffers:
                        assert final.read(present(final,key))==current.read(present(current,key)),key
                        verified_buffers.add(key)
            assert final.read('PostEffect.FxTweakables')==donor.read('PostEffect.FxTweakables')
            report.update(archive_entries=count,archive_crc_verified=True,resource_closure_missing=missing,
                          original_geometry_buffers_byte_identical=len(verified_buffers),
                          global_sun_and_postfx_unchanged=False,postfx_unchanged=True,output_bytes=pending.stat().st_size)
        from validate_d3d_textures import validate
        d3d=validate(pending)
        if d3d['failed']:raise RuntimeError('Native Direct3D texture resource creation failed: '+str(d3d['failed']))
        report['after_d3d']=d3d
    pending.replace(output)
    report.update(output=str(output),output_sha256=digest(output))
    (ROOT/'validation/iff-current.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:report[k] for k in ('output','output_bytes','output_sha256','archive_crc_verified')},ensure_ascii=True),flush=True)

if __name__=='__main__':main()
