"""Render review cameras from the saved scene; never generate alternate geometry."""
import argparse
import sys
from pathlib import Path
import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from create_scene import bind_ground_artwork

parser=argparse.ArgumentParser()
parser.add_argument('--prefix',default='r02')
parser.add_argument('--views',default='overview,garden,ground,hoop')
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
if not args.prefix.replace('-','').isalnum(): raise ValueError('Invalid render prefix')
runtime=ROOT/'.build-staging'/'render-runtime'
runtime.mkdir(parents=True,exist_ok=True)
bpy.context.preferences.filepaths.temporary_directory=str(runtime)
bpy.context.preferences.filepaths.file_preview_type='NONE'
bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
bind_ground_artwork()
scene=bpy.context.scene
scene.render.engine='CYCLES'
scene.cycles.samples=28
scene.cycles.use_denoising=True
scene.render.resolution_x=1600
scene.render.resolution_y=1000
scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
camera=scene.camera
views={
    'overview':((39,-45,32),(-4,3,1.5),39),
    'garden':((12,-9,4.7),(25,8.5,2.8),32),
    'ground':((3,-14,12),(-5,0,0),32),
    'hoop':((-8,-5.0,2.7),(-13.1,0,2.68),44),
    'architecture':((-4,-6.8,2.05),(-23,.8,3),27),
}
destination=ROOT/'validation'; destination.mkdir(exist_ok=True)
for name in args.views.split(','):
    if name=='top':
        camera.location=(0,0,55); camera.rotation_euler=(0,0,0)
        camera.data.type='ORTHO'; camera.data.ortho_scale=38
    else:
        position,target,lens=views[name]
        camera.data.type='PERSP'; camera.data.lens=lens
        camera.location=position
        camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=str(destination/f'{args.prefix}-{name}.png')
    bpy.ops.render.render(write_still=True)
    print('ZGC_RENDER_READY '+scene.render.filepath)
