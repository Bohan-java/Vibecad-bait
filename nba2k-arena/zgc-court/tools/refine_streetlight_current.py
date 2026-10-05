"""R10 incremental, unlit photo-based left floodlight and mineral paving.

No original object geometry, transform, UV, illumination or exposure changes.
Photo21 establishes the high-pole form; absolute dimensions are inferred.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import bpy
import bmesh
from mathutils import Matrix, Vector

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import create_scene as source
import refine_architecture_r02 as primitive
import refine_details_r03 as finish
from refine_hoop_current import snapshot

REVISION='R10 photo21 left tall unlit floodlight and concrete palette'
STAGE=ROOT/'.build-staging/streetlight-current'
POSITION=(-4.2,-9.85,0.)
HEIGHT=10.8
ADDED=[]
MATERIAL_CHANGES={
    'R02 environment | ivory_wave':('ADB0A7',.94),
    'R02 architecture | terrace':('9FA399',.96),
    'R02 environment | pale_paving':('949994',.96),
    'R02 environment | stone_insert':('9BA097',.94),
}


def mesh_from_batch(name,batch,material,smooth=False,bevel=0):
    mesh=bpy.data.meshes.new(name)
    mesh.from_pydata(batch.vertices,[],batch.faces);mesh.update()
    bm=bmesh.new();bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(mesh);bm.free()
    mesh.materials.append(material)
    for face in mesh.polygons:face.use_smooth=smooth and len(face.vertices)==4
    obj=bpy.data.objects.new(name,mesh)
    bpy.data.collections['background'].objects.link(obj);obj.parent=bpy.data.objects['background']
    obj['r10_streetlight']=True;obj['layer']='background';obj['category']='streetlight'
    obj['reference_images']='21 main position and two-tier head; 23 secondary head style'
    obj['measurement_status']='Photo-supported silhouette and relative position; all metric dimensions inferred, not measured.'
    obj['emission_enabled']=False
    if bevel:
        modifier=obj.modifiers.new('Small fabricated edge radius','BEVEL');modifier.width=bevel;modifier.segments=2
        modifier.limit_method='ANGLE'
    ADDED.append(obj.name)
    return obj


def transform_add(destination,batch,matrix):
    destination.add([matrix@Vector(v) for v in batch.vertices],batch.faces)


def lamp():
    pole_mat=finish.pbr('R10 | tall floodlight coated mast','444C4B',.58,.52)
    case_mat=finish.pbr('R10 | floodlight dark metal housings','343B3B',.48,.62)
    lens_mat=finish.pbr('R10 | floodlight unlit lens faces','596563',.31,.14)
    fix_mat=finish.pbr('R10 | floodlight small fixing metal','767D79',.53,.66)
    for mat in (pole_mat,case_mat,lens_mat,fix_mat):
        shader=finish.shader_for(mat)
        shader.inputs['Emission Strength'].default_value=0
        mat['unlit_photo_reconstruction']=True
    mast=primitive.Batch('mast',pole_mat,True)
    cases=primitive.Batch('housings',case_mat)
    lenses=primitive.Batch('unlit lenses',lens_mat)
    fittings=primitive.Batch('fittings',fix_mat)
    x,y,z=POSITION
    mast.rod((x,y,.065),(x,y,HEIGHT),.08,.0475,24)
    # Thin base flange and local ground fixings are construction inferences;
    # they do not move the adjacent fence or create a raised ground plinth.
    mast.lathe((x,y,0),[(0,.004),(.135,.004),(.135,.025),(.085,.033),(.085,.092),(.08,.10)],32)
    for dx,dy in ((-.075,-.075),(-.075,.075),(.075,-.075),(.075,.075)):
        fittings.rod((x+dx,y+dy,.027),(x+dx,y+dy,.043),.011,.011,6)
    for level in (10.00,10.43):
        mast.rod((x-.385,y,level),(x+.385,y,level),.027,.027,12)
        mast.rod((x,y,level-.115),(x,y,level+.10),.058,.058,16)
        for side in (-1,1):
            center=Vector((x+side*.265,y+.10,level))
            rotation=Matrix.Rotation(math.radians(-18),4,'X')
            transform=Matrix.Translation(center)@rotation
            body=primitive.Batch('body',case_mat)
            # Recessed face and four slim lip strips, no luminous shader.
            body.box((0,-.018,0),(.34,.126,.20))
            for u in (-.159,.159):body.box((u,.051,0),(.022,.032,.20))
            for v in (-.09,.09):body.box((0,.051,v),(.30,.032,.020))
            transform_add(cases,body,transform)
            face=primitive.Batch('face',lens_mat);face.box((0,.052,0),(.296,.010,.156))
            transform_add(lenses,face,transform)
            # Compact external U bracket; both lamp tiers remain distinct.
            for dx in (-.19,.19):
                cases.rod((center.x+dx,y-.025,level-.08),(center.x+dx,y+.105,level),.012,.012,8)
                fittings.rod((center.x+dx-.005,y+.105,level),(center.x+dx+.005,y+.105,level),.017,.017,8)
            cases.rod((center.x-.19,y-.025,level-.08),(center.x+.19,y-.025,level-.08),.012,.012,8)
    # Photo21 shows a small lower attachment. Its function is not identified.
    cases.box((x+.116,y+.035,9.64),(.128,.128,.185))
    mast.rod((x,y,9.65),(x+.114,y,9.65),.018,.018,10)
    lenses.box((x+.116,y+.101,9.64),(.082,.007,.110))
    objects=[mesh_from_batch('R10 left tall floodlight tapered mast',mast,pole_mat,True),
             mesh_from_batch('R10 left tall floodlight housings and brackets',cases,case_mat,False,.0025),
             mesh_from_batch('R10 left tall floodlight non-emitting lens faces',lenses,lens_mat,False,.001),
             mesh_from_batch('R10 left tall floodlight mechanical fixings',fittings,fix_mat,False)]
    objects[0]['pole_height_m']=HEIGHT
    return {
        'position_m':list(POSITION),'height_m':HEIGHT,'mast_diameter_m':[.16,.095],
        'head_rows_z_m':[10.00,10.43],'paired_main_head_count':4,
        'head_body_width_height_depth_m':[.34,.20,.126],
        'small_lower_attachment':'Visible in photo21; purpose unassigned.',
        'side':'Chilis / negative X at top; negative Y is left, outside long fence',
        'fence_y_m':-9.17,'offset_from_fence_center_m':.68,
        'photo_evidence':{
            '21':'High slender pole outside left fence near open end; two paired rectangular tiers, small lower fitting, short top projection.',
            '23':'Secondary view corroborates flat rectangular paired heads and lower attachment, but does not survey the requested pole.',
            '16,22,24':'Other plaza poles are visually distinct; no mirrored high pole is added.',
            'chilis/01/03':'Glass reflection supplies weak silhouette corroboration, not a base position.'},
        'metric_status':'Placement, height, diameters and fabrication dimensions are editable estimates, not photogrammetric measurements.',
        'emission':False,'new_light_objects':0,
    }


def recolor():
    rows=[]
    for name,(color,roughness) in MATERIAL_CHANGES.items():
        material=bpy.data.materials[name];shader=finish.shader_for(material)
        if shader.inputs['Base Color'].is_linked:raise RuntimeError('Expected non-atlas solid material '+name)
        before=list(shader.inputs['Base Color'].default_value)
        material=finish.pbr(name,color,roughness,0)
        material['r10_paving_palette_srgb']='#'+color
        users=[]
        for obj in bpy.data.objects:
            if obj.type!='MESH' or material not in obj.data.materials[:]:continue
            slots=[i for i,m in enumerate(obj.data.materials) if m==material]
            users.append({'object':obj.name,'affected_faces':sum(p.material_index in slots for p in obj.data.polygons)})
        rows.append({'material':name,'before_linear_rgba':before,'after_srgb':'#'+color,'roughness':roughness,'users':users})
    return rows


def lighting_signature():
    scene=bpy.context.scene
    result={'lights':[],'world':[],'view':{'view_transform':scene.view_settings.view_transform,'look':scene.view_settings.look,'exposure':scene.view_settings.exposure,'gamma':scene.view_settings.gamma}}
    for o in bpy.data.objects:
        if o.type=='LIGHT':result['lights'].append((o.name,o.data.type,o.data.energy,list(o.data.color),[list(r) for r in o.matrix_world]))
    if scene.world and scene.world.use_nodes:
        for n in scene.world.node_tree.nodes:
            result['world'].append((n.name,n.type,[(i.name,list(i.default_value) if hasattr(i.default_value,'__len__') else i.default_value) for i in n.inputs if hasattr(i,'default_value')]))
    return result


def notes():
    path=ROOT/'source/BUILD_NOTES.txt';text=path.read_text(encoding='utf8')
    text=text.replace('当前 R09 继续按原图修正左右围栏、大A灯带结构和场边铺地。','当前 R10 继续按原图补左侧高杆灯，并将场外铺地修正为灰水泥色。')
    text=text.replace('照片22–24对应的独立低起伏铺面仅改为暖矿物米灰#D2D0C3、粗糙度0.94，波面形状和位置保持原样；颜色不是校准测色值。','照片22–24对应的独立低起伏铺面改为浅灰水泥#ADB0A7、粗糙度0.94；餐厅露台#9FA399、主广场板侧面#949994、小块石材#9BA097。图集表面由同一world-XY铺地图管理；波面形状、场地高度和UV不变，颜色不是校准测色值。')
    text+='\nR10：依原图21在左侧长围栏外补一根细高杆，两层成对矩形灯头及小型下挂附件；全部使用普通非发光材质，不新增灯光对象、不改曝光。杆脚推定为(-4.2,-9.85,0) m，高度推定10.8 m；照片能支持形态及相对关系，绝对尺寸和安装间距不是实测。未镜像增加第二根高杆。\n现有篮架、围栏、比赛锚点、全部原对象几何/坐标/UV均由前后指纹核对；验证详见 validation/current-streetlight-detail.json。current-streetlight-context/head.png为源模型核验图，不是游戏截图。\n'
    path.write_text(text,encoding='utf8')


def renders():
    scene=bpy.context.scene;camera=scene.camera
    scene.render.engine='CYCLES';scene.cycles.samples=28;scene.cycles.use_denoising=True
    scene.render.resolution_x=1400;scene.render.resolution_y=1200;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    for name,position,target,lens in (
        ('current-streetlight-context',(13,-27,20),(-7,-4.7,3.0),41),
        ('current-streetlight-head',(-1.7,-5.8,10.6),(-4.2,-9.82,10.12),63),
    ):
        camera.data.type='PERSP';camera.data.lens=lens;camera.location=position
        camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
        scene.render.filepath=str(ROOT/'validation'/f'{name}.png');bpy.ops.render.render(write_still=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=str(STAGE/'scene-streetlight.blend'));parser.add_argument('--render',action='store_true');parser.add_argument('--commit',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    output=(ROOT/'source/scene.blend') if args.commit else Path(args.output).resolve()
    if not output.is_relative_to(ROOT):raise ValueError('Output outside project')
    if bpy.context.scene.get('streetlight_detail_revision')==REVISION:raise RuntimeError('Already applied; export saved source directly')
    STAGE.mkdir(parents=True,exist_ok=True);backup=STAGE/'source-before.blend'
    if not backup.exists():shutil.copy2(bpy.data.filepath,backup)
    prefs=bpy.context.preferences.filepaths;prefs.temporary_directory=str(STAGE);prefs.file_preview_type='NONE';prefs.save_version=0;prefs.use_auto_save_temporary_files=False
    bpy.context.view_layer.update();before=snapshot();light_before=lighting_signature()
    detail=lamp();materials=recolor();bpy.context.view_layer.update();after=snapshot()
    unexpected=[n for n,h in before.items() if after.get(n)!=h]
    if unexpected:raise RuntimeError('Original geometry/UV changed: '+str(unexpected))
    if lighting_signature()!=light_before:raise RuntimeError('Lighting/exposure unexpectedly changed')
    validation=source.validate_scene()
    if validation['status']!='passed':raise RuntimeError(json.dumps(validation))
    if args.commit:notes()
    bpy.context.scene['streetlight_detail_revision']=REVISION
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    report={'status':'passed','revision':REVISION,'source_output':str(output),'source_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'lamp':detail,'new_objects':ADDED,'new_vertices':sum(len(bpy.data.objects[n].data.vertices) for n in ADDED),
            'original_objects_protected':len(before),'unexpected_geometry_changes':unexpected,'all_original_geometry_transforms_and_UVs_unchanged':True,
            'all_baskets_fences_anchors_unchanged':True,'light_objects_world_exposure_unchanged':True,'non_atlas_material_changes':materials,
            'atlas_ownership':'SVG/PNG and atlas shader untouched; artwork agent supplies grey paving image.',
            'validation':validation,'game_package_written':False}
    (ROOT/'validation/current-streetlight-detail.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('STREETLIGHT_CURRENT_SAVED '+str(output)+' SHA256 '+report['source_sha256'],flush=True)
    if args.render:renders()


if __name__=='__main__':main()
