"""Build the corrected local arena + independent-floor pair without installing."""
from __future__ import annotations
import copy
import hashlib
import json
import zipfile
from pathlib import Path
import numpy as np
from revision_textures import create_set,make_dds
from palm_geometry import add_palms
from read_game_resource import find_entries,read_entry,inflate_vcz

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'donor/original/arena_020_int_original.iff'
OUT=ROOT/'output/revision2'
BUILD=ROOT/'build/revision2'
SHA='42865ecaf8dd923c4d901509263af3b242c00975f4284b917ba79ce8fbbced46'

def fragment(raw):return json.loads(b'{'+raw.strip()+b'}')
def sha(b):return hashlib.sha256(b).hexdigest()

def set_slot(level,mat,slot,texture):
    level['Material'][mat]['Resource'][slot]['Pixelmap']=texture

def material_pass(level,textures):
    t={k:v[0] for k,v in textures.items()}
    for name,spec,raw in textures.values():level['Texture'][name]=spec
    # Separate channel responsibilities: diffuse tile, transparent logo,
    # roughness/normal packing, and the donor's existing line geometry.
    court='floor_clutchtime_court:area_1_mat'
    for mat in (court,'floor_clutchtime_court:floor_line_mat','floor_clutchtime_court:floor_line_mat1'):
        set_slot(level,mat,'BaseMaterialTexture',t['matte_base'])
        set_slot(level,mat,'DetailNormalRoughConeTexture',t['floor_normal_rough_cone'])
        set_slot(level,mat,'DetailAlbedoTexture',t['asphalt'] if mat==court else t['line_white'])
        params=level['Material'][mat]['Parameter']
        params['DetailRoughness']=.84
        params['DetailNormalHeight']=.006
        params['ModulateAlbedo']=[1.,1.,1.]
    set_slot(level,court,'Logo0Texture',t['no_logo'])
    base_surfaces={
        'clutchtime_floor_apron:floor_mat':'asphalt',
        'clutchtime_crowd_seating:chair':'aluminum',
        'clutchtime_balcony_b:balcony_mat':'concrete',
        'clutchtime_balcony_b:balcony2_amt':'grass',
        'clutchtime_balcony_b:balcony4_mat':'concrete',
        'clutchtime_balcony_railing:railing_mat':'aluminum',
        'clutchtime_mural_wall:mural_mat':'concrete',
        'clutchtime_wall_corner:wallcorner_mat':'concrete',
        'clutchtime_wall_f:wall_mat':'concrete',
        'clutchtime_stands_tunnel:tunnel_mat':'concrete',
        'clutchtime_stair_3step:steps_mat':'concrete',
        'clutchtime_ceiling_a:ceilinga_mat':'sky',
        'clutchtime_ceilingpanel_c:panelc_mat':'sky',
        'clutchtime_ceiling_ribs:ceilingribs_mat':'sky',
    }
    for mat,key in base_surfaces.items():
        set_slot(level,mat,'AlbedoMap',t[key])
        level['Material'][mat].setdefault('Parameter',{})['AlbedoModulate']=[1.,1.,1.,1.]
        if mat in ('clutchtime_floor_apron:floor_mat','clutchtime_stair_3step:steps_mat','clutchtime_balcony_b:balcony_mat'):
            set_slot(level,mat,'NormalAndRoughMap',t['surface_normal_rough'])
            level['Material'][mat]['Parameter']['NormalHeight']=0.
    for layer in ('LAYER0','LAYER1'):
        mat=level['Material']['clutchtime_wall_c:wall_mat']
        mat['Resource'][layer+'_AlbedoMap']['Pixelmap']=t['concrete']
        mat['Parameter'][layer+'_AlbedoModulate']=[1.,1.,1.,1.]
    for i in range(1,6):
        mat=f'clutchtime_mural_wall:mural{i}_mat'
        set_slot(level,mat,'AlbedoMap',t[f'palm_backdrop_{i}'])
        level['Material'][mat]['Parameter']['DefaultRoughness']=.85
        level['Material'][mat]['Parameter']['MaxRoughness']=1.
    # Functional scoreboard displays are retained from the original donor.

def main():
    assert sha(SOURCE.read_bytes())==SHA,'Original donor hash mismatch'
    OUT.mkdir(parents=True,exist_ok=True);BUILD.mkdir(parents=True,exist_ok=True)
    source_floor='shared/0f/vertexbuffer.0f3b6fcaf86b59a6.gz'
    refs=find_entries([source_floor,'levels/arena_700_int_floor.iff'])
    assert source_floor in refs and 'levels/arena_700_int_floor.iff' in refs
    vertex_vcz=read_entry(refs[source_floor]);vertex_raw=inflate_vcz(vertex_vcz)
    with zipfile.ZipFile(SOURCE) as z:
        donor=fragment(z.read('level.SCNE'))['level']
        level=copy.deepcopy(donor)
        textures=create_set()
        extra={spec['Binary']:raw for _,spec,raw in textures.values()}
        extra['VertexBuffer.0f3b6fcaf86b59a6.gz']=vertex_vcz
        material_pass(level,textures)
        placements=add_palms(level,z,textures,extra)
        # Preserve every original node and mesh exactly, allowing only named
        # decorative additions beyond the donor dictionaries.
        for section in ('Model','Object'):
            assert all(level[section].get(k)==v for k,v in donor[section].items()),section
        for section in ('Light','Effect'):
            assert level[section]==donor[section],section
        for name,mat in level['Material'].items():
            if not name.startswith('venice_v2:'):continue
            assert mat['Effect'] in level['Effect']
            assert mat['Script'] in z.namelist()
            for slot in mat['Resource'].values():
                assert slot['Pixelmap'] in level['Texture']
                assert level['Texture'][slot['Pixelmap']]['Binary'] in extra
        for name,model in level['Model'].items():
            if not name.startswith('venice_v2:'):continue
            for prim in model['Prim']:assert prim['Material'] in level['Material']
            for stream in model['VertexStream']:assert stream['Binary'] in extra
            assert model['IndexBuffer']['Binary'] in extra
        floor=level['Model'][level['Object']['__floor00__']['Target']]
        assert len(vertex_raw)==floor['VertexStream'][0]['Size']==90468
        floor_pos=np.ndarray((len(vertex_raw)//28,3),'<f4',vertex_raw,strides=(28,4))
        assert np.allclose(floor_pos.min(0),floor['Min'],atol=.001)
        assert np.allclose(floor_pos.max(0),floor['Max'],atol=.001)
        scene=json.dumps({'level':level},separators=(',',':')).encode()[1:-1]
        (BUILD/'level.SCNE').write_bytes(scene)
        main_path=OUT/'arena_700_int.iff'
        with zipfile.ZipFile(main_path,'w') as target:
            for info in z.infolist():
                target.writestr(info,scene if info.filename=='level.SCNE' else z.read(info))
            for name,raw in sorted(extra.items()):
                assert name not in z.namelist(),name
                info=zipfile.ZipInfo(name,(2014,1,1,17,0,0));info.compress_type=zipfile.ZIP_STORED
                target.writestr(info,raw)
    # 700's separately loaded stock floor would otherwise coexist with the
    # donor's __floor00__. Override its scene using the known local empty-floor
    # pattern, while preserving its compiled/dormant resources in the package.
    import io
    stock_floor_raw=inflate_vcz(read_entry(refs['levels/arena_700_int_floor.iff']))
    floor_path=OUT/'arena_700_int_floor.iff'
    with zipfile.ZipFile(io.BytesIO(stock_floor_raw)) as original_floor,zipfile.ZipFile(floor_path,'w') as target:
        for info in original_floor.infolist():
            target.writestr(info,b'"level_floor":{}' if info.filename=='level_floor.SCNE' else original_floor.read(info))

    report={'status':'STATIC_CHECKS_PASSED_GAME_UNTESTED',
        'donor_sha256':SHA,'arena_sha256':sha(main_path.read_bytes()),'floor_sha256':sha(floor_path.read_bytes()),
        'donor_model_count':len(donor['Model']),'added_palm_models':3,'added_palm_instances':len(placements),
        'all_original_models_and_objects_unchanged':True,'all_original_lights_effects_unchanged':True,
        'donor_floor_vertices_verified':len(floor_pos),'donor_floor_bounds_verified':True,
        'stock_700_floor_scene_overridden':True,'floor_origin_matrix':level['Object']['__floor00__']['Matrix'],
        'geometry_preview_is_game_capture':False,'game_directory_modified':False,'placements':placements,
        'textures':{k:spec for k,(_,spec,_) in textures.items()}}
    with zipfile.ZipFile(SOURCE) as original,zipfile.ZipFile(main_path) as result:
        assert result.testzip() is None
        changed=[n for n in original.namelist() if original.read(n)!=result.read(n)]
        assert changed==['level.SCNE'],changed
        report['changed_original_entries']=changed
        # Decode the actual built texture bytes, including transparent logo
        # and packed linear material maps, not just intermediate PNGs.
        from PIL import Image
        for key,spec in report['textures'].items():
            raw=result.read(spec['Binary'])
            assert raw[:4]==b'TLD ' and len(raw)==32+spec['PixelDataSize']
            img=Image.open(io.BytesIO(make_dds(raw[32:],spec['Width'],spec['Height'],spec['Format']))).convert('RGBA')
            img.load()
            if key=='no_logo': assert img.getchannel('A').getextrema()==(0,0)
        for placement in placements:
            m=level['Model'][placement['model']]
            lo=np.array(m['Min'])+placement['position'];hi=np.array(m['Max'])+placement['position']
            fmin=np.array(floor['Min']);fmax=np.array(floor['Max'])
            assert hi[0]<fmin[0] or lo[0]>fmax[0] or hi[2]<fmin[2] or lo[2]>fmax[2],placement
        report['all_palm_bounds_outside_donor_floor']=True
        report['archive_entry_count']=len(result.namelist())
    with zipfile.ZipFile(floor_path) as z:
        assert z.testzip() is None
        assert fragment(z.read('level_floor.SCNE'))=={'level_floor':{}}
    (BUILD/'revision_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    (ROOT/'docs/REVISION2_REPORT.md').write_text(
        '# Revision 2\n\n'
        'Static checks passed. Game loading and visual behavior have not been tested in NBA 2K.\n\n'
        '- Adds 14 non-colliding fan-palm instances using three geometry variants.\n'
        '- All added palm bounds are outside the donor court footprint.\n'
        '- Adds a reference-derived palm/ocean panorama to the existing mural surfaces.\n'
        '- Replaces the opaque asphalt Logo0Texture with a zero-alpha BC3 texture.\n'
        '- Separates matte asphalt, white line shading, and correctly packed normal/roughness maps.\n'
        '- Embeds the exact original donor floor vertex resource resolved from the local game manifest.\n'
        '- Preserves every original donor model, object, transform, light, compiled effect, collision and basket resource.\n'
        '- Supplies arena_700_int_floor.iff to override the independently loaded stock 700 floor scene; the main donor remains the only floor.\n'
        '- Game directories were only read; nothing was installed.\n\n'
        'Use both same-number IFF files together. If using another slot, both filenames must use that slot number.\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('textures','placements','floor_origin_matrix')},indent=2))

if __name__=='__main__':main()
