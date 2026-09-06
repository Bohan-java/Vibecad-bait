"""Build and audit the complete outdoor revision without installing the MOD.

All additions are made to a verified original donor, never an earlier failed
output. The original archive and all its binary resources remain untouched.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
import numpy as np

from revision3_court import apply_court
from revision3_environment import apply_environment
from revision3_floor_lighting import apply_floor_lighting
from revision3_landscape import apply_landscape
from revision3_textures import apply_textures
from scene_primitives import iter_primitives

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'donor/original/arena_020_int_original.iff'
SOURCE_SHA='42865ecaf8dd923c4d901509263af3b242c00975f4284b917ba79ce8fbbced46'
OUT=ROOT/'output/revision3'
BUILD=ROOT/'build/revision3'
SHA=lambda raw: hashlib.sha256(raw).hexdigest()


def fragment(raw):
    return json.loads(b'{'+raw.strip()+b'}')


def archive_scene(level):
    return json.dumps({'level':level},separators=(',',':')).encode()[1:-1]


def validate_scene(donor, level, original, output, report):
    for name,obj in donor['Object'].items():
        if name=='TIME_OF_DAY':
            assert obj['Type']==level['Object'][name]['Type']
        else:
            assert level['Object'][name]==obj, f'Original object changed: {name}'
    for name,effect in donor['Effect'].items():
        assert level['Effect'][name]==effect, f'Original compiled effect changed: {name}'
    for name,entry in donor['Texture'].items():
        assert level['Texture'][name]==entry, f'Original texture record changed: {name}'
    archive_names=set(output.namelist())
    for name,model in level['Model'].items():
        if not name.startswith('venice_v3:') and name!=donor['Object']['__floor00__']['Target']:
            continue
        assert all(s['Binary'] in archive_names for s in model['VertexStream'])
        assert model['IndexBuffer']['Binary'] in archive_names
        for stream in model['VertexStream']:
            assert len(output.read(stream['Binary']))==stream['Size']
        index=output.read(model['IndexBuffer']['Binary'])
        assert len(index)==model['IndexBuffer']['Size']
        count=model['VertexStream'][0]['Size']//model['VertexStream'][0]['Stride']
        indices=np.frombuffer(index,'<u2' if model['IndexBuffer']['Format']=='R16_UINT' else '<u4')
        list(iter_primitives(model,indices=indices,vertex_count=count))
        for prim in model['Prim']:
            material=level['Material'][prim['Material']]
            assert material['Effect'] in level['Effect']
    for name,material in level['Material'].items():
        if name.startswith('venice_v3:'):
            for slot in material['Resource'].values():
                assert slot['Pixelmap'] in level['Texture'], (name,slot)
    changed=[n for n in original.namelist() if original.read(n)!=output.read(n)]
    assert sorted(changed)==['crowd.SCNE','level.SCNE','level_floor_lightmaps.SCNE'],changed
    protected=[n for n in original.namelist() if
               n=='baskets.SCNE' or n.endswith(('.Coll','.CrowdData')) or n.startswith('crowd_seats_vertex.')]
    assert 'baskets.SCNE' in protected
    for name in protected:assert original.read(name)==output.read(name)
    hidden=report['environment']['hidden_models']
    for entry in hidden:
        data=output.read(entry['replacement_index_resource'])
        assert data==bytes(entry['index_byte_size'])
    crowd=report['environment']['crowd_render_change']
    assert not any(output.read(crowd['replacement_index_resource']))
    visible_original=[]
    hidden_targets={entry['target'] for entry in hidden}
    for name,obj in donor['Object'].items():
        if obj.get('Type')=='OBJECT' and obj['Target'] not in hidden_targets:
            visible_original.append(name)
    assert len(visible_original)==1,visible_original
    return {'changed_original_archive_entries':changed,
            'all_original_binary_resources_byte_identical':True,
            'original_objects_except_time_of_day_byte_equivalent':True,
            'all_original_compiled_effects_unchanged':True,
            'preserved_gameplay_archive_entries':protected,
            'visible_original_level_objects':visible_original,
            'all_hidden_geometry_zero_area_in_every_lod':True,
            'all_new_index_ranges_and_stream_sizes_valid':True,
            'duplicate_archive_names':len(output.namelist())-len(archive_names),
            'game_runtime_verified':False,'game_directory_modified':False}


def main():
    assert SHA(SOURCE.read_bytes())==SOURCE_SHA,'Protected donor changed'
    OUT.mkdir(parents=True,exist_ok=True);BUILD.mkdir(parents=True,exist_ok=True)
    extra={}
    with zipfile.ZipFile(SOURCE) as original:
        donor=fragment(original.read('level.SCNE'))['level'];level=copy.deepcopy(donor)
        print('Preparing scanned textures and verified material channels',flush=True)
        textures=apply_textures(level,extra)
        print('Rebuilding the complete standard court',flush=True)
        court=apply_court(level,original,extra)
        print('Removing original enclosure and enabling the native outdoor sky',flush=True)
        environment=apply_environment(level,original,extra)
        lighting=apply_floor_lighting(original,extra)
        print('Building one beach landscape with detailed palms and low bleachers',flush=True)
        landscape=apply_landscape(level,extra,textures['textures'])
        scene=archive_scene(level)
        (BUILD/'level.SCNE').write_bytes(scene)
        overrides={name:raw.encode() for name,raw in environment.pop('scene_overrides').items()}
        overrides.update({name:raw.encode() for name,raw in lighting.pop('scene_overrides').items()})
        overrides['level.SCNE']=scene
        if set(extra)&set(original.namelist()):raise ValueError('New resource would overwrite donor resource')
        path=OUT/'arena_700_int.iff';temporary=path.with_suffix('.iff.tmp')
        with zipfile.ZipFile(temporary,'w') as target:
            for info in original.infolist():
                target.writestr(copy.copy(info),overrides.get(info.filename,original.read(info)))
            for name,raw in sorted(extra.items()):
                info=zipfile.ZipInfo(name,(2014,1,1,17,0,0));info.compress_type=zipfile.ZIP_STORED
                target.writestr(info,raw)
        report={'status':'STATIC_VALIDATED_GAME_UNTESTED','donor_sha256':SOURCE_SHA,
                'references':['textures/source/references/arena_reference_%02d.png'%i for i in range(1,6)],
                'reference_interpretation':'one continuous outdoor court, five viewpoints, ignore all people',
                'textures':textures,'court':court,'environment':environment,'floor_lighting':lighting,'landscape':landscape}
        with zipfile.ZipFile(temporary) as built:
            assert built.testzip() is None
            validation=validate_scene(donor,level,original,built,report)
        temporary.replace(path)
    # The independently loaded 700 floor override is already known and checked.
    paired=ROOT/'output/revision2/arena_700_int_floor.iff'
    assert SHA(paired.read_bytes())=='5f23522f783614d1572dca4f904132659f0d9ad4bd266b8148cbaacd333cf2ce'
    with zipfile.ZipFile(paired) as floor:
        assert fragment(floor.read('level_floor.SCNE'))=={'level_floor':{}}
    shutil.copyfile(paired,OUT/paired.name)
    artifacts={p.name:{'bytes':p.stat().st_size,'sha256':SHA(p.read_bytes())}
               for p in (path,OUT/paired.name)}
    report['artifacts']=artifacts;report['validation']=validation
    validation.update(artifacts=artifacts,status=report['status'],
                      new_model_count=len(landscape['meshes']),palm_instances=landscape['palm_instances'],
                      hidden_original_models=environment['hidden_model_count'],
                      hidden_original_instances=environment['hidden_object_count'],
                      five_views_of_same_court=True,people_recreated=False,
                      required_game_test='Load both same-slot IFF files and compare center line, enclosure removal, lit palms and matte dry concrete against the reference set.')
    (BUILD/'revision_report.json').write_text(json.dumps(report,indent=2)+'\n')
    (OUT/'validation.json').write_text(json.dumps(validation,indent=2)+'\n')
    shipping = ('Venice court revision 3\n\n'
                'Extract both same-number IFF files together. They target slot 700.\n'
                'Do not extract the contents of the IFF files. Preserve your own\n'
                'existing MOD files before using any candidate. Nothing is installed\n'
                'by the build script. This candidate has passed static archive and\n'
                'geometry validation; NBA 2K runtime/appearance remain unverified.\n'
                'Original donor gameplay transforms, baskets and collisions remain.\n')
    (OUT/'README.txt').write_text(shipping)
    package=OUT/'venice_court_revision3.zip'
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as target:
        for p in (path,OUT/paired.name,OUT/'validation.json',OUT/'README.txt'):
            info=zipfile.ZipInfo(p.name,(2026,9,6,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            target.writestr(info,p.read_bytes())
    with zipfile.ZipFile(package) as packed:
        assert packed.testzip() is None
        for name,spec in artifacts.items():assert SHA(packed.read(name))==spec['sha256']
    print(json.dumps({'status':report['status'],'artifacts':artifacts,
                      'shipping_zip':{'bytes':package.stat().st_size,'sha256':SHA(package.read_bytes())},
                      'hidden_original_instances':environment['hidden_object_count'],
                      'palm_instances':landscape['palm_instances'],
                      'changed_original_entries':validation['changed_original_archive_entries']},indent=2),flush=True)


if __name__=='__main__':main()
