"""Assemble R12 against the current R11 editable scene, only into staging."""
import hashlib
import json
from pathlib import Path
import sys
import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from refine_hoop_current import snapshot
from refine_streetlight_current import lighting_signature
import refine_chilis_rect_current as chilis
import refine_left_context_current as left
import r12_seating_geometry as seating
import refine_skyline_current as skyline

def main():
    stage=ROOT/'.build-staging/r12-context';stage.mkdir(parents=True,exist_ok=True)
    prefs=bpy.context.preferences.filepaths;prefs.temporary_directory=str(stage);prefs.save_version=0;prefs.file_preview_type='NONE';prefs.use_auto_save_temporary_files=False
    before=snapshot();lights=lighting_signature()
    components={}
    for key,module,fn in [('chilis',chilis,'build'),('left',left,'build'),('seating',seating,'build_bench_geometry'),('skyline',skyline,'build')]:
        print('R12_COMPONENT '+key,flush=True)
        components[key]=getattr(module,fn)()
    after=snapshot()
    authorized=set(components['chilis']['removed_old_building_objects'])|set(components['chilis']['furniture']['deleted_old_objects'])|set(components['skyline']['removed_placeholder_objects'])|{r['name'] for r in components['left']['trimmed_old_inferred_planting']}
    changed=[name for name,h in before.items() if after.get(name)!=h]
    unexpected=sorted(set(changed)-authorized)
    assert not unexpected,unexpected
    assert lights==lighting_signature(),'Protected lighting/world changed'
    bpy.context.scene['current_revision']='R12 right bench, left foreground, rectangular Chilis, photographic skyline'
    bpy.ops.wm.save_as_mainfile(filepath=str(stage/'scene.blend'))
    sha=hashlib.sha256((stage/'scene.blend').read_bytes()).hexdigest()
    components['chilis']['published_source_sha256']=sha
    report={'revision':'R12','status':'passed','published_source_sha256':sha,'stage_source':str(stage/'scene.blend'),
       'components':components,'unexpected_changes':unexpected,'changed_original_objects':changed,
       'protected_original_objects':len(before)-len(changed),'lights_world_exposure_preserved':True,'game_tested':False}
    (ROOT/'validation/context-current.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    (ROOT/'validation/chilis-building-current.json').write_text(json.dumps(components['chilis'],ensure_ascii=False,indent=2),encoding='utf8')
    print('R12_STAGE_READY '+sha,flush=True)
    scene=bpy.context.scene;camera=scene.camera
    scene.render.engine='CYCLES';scene.cycles.samples=16;scene.cycles.use_denoising=True
    scene.render.threads_mode='FIXED';scene.render.threads=10
    scene.render.resolution_x=1440;scene.render.resolution_y=960;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
    camera.data.clip_end=800
    views=[('overview',(37,-34,34),(-10,0,6),25),('left',(-1,1,2.6),(-13,-21,6),22),
           ('open',(-15,-3,3.1),(82,44,30),25),('canopy',(-5,-4,2.8),(-4,70,25),25)]
    for key,pos,target,lens in views:
        camera.location=pos;camera.data.type='PERSP';camera.data.lens=lens
        camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
        scene.render.filepath=str(ROOT/'validation'/f'r12-context-{key}.png');bpy.ops.render.render(write_still=True)

if __name__=='__main__':main()
