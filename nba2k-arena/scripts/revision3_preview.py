"""Build an honest WebGL preview directly from the final IFF's actual resources.

The viewer includes every mesh object in level.SCNE and baskets.SCNE. Unsupported
compression, skinning and missing resources become named magenta bounding boxes;
they are never silently hidden. This is not a reproduction of NBA 2K's shaders.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import sys
import zipfile
import zlib

import numpy as np
from PIL import Image

sys.dont_write_bytecode = True
from revision3_mesh import _decode_normal

ROOT = Path(__file__).resolve().parents[1]
THREE_CANDIDATES = (ROOT.parents[1] / 'model/node_modules/three', ROOT.parent / 'node_modules/three')
IDENTITY = np.eye(4).reshape(-1).tolist()


def _json_fragment(raw):
    raw = raw.strip()
    return json.loads(raw if raw.startswith(b'{') else b'{' + raw + b'}')


def _dds(payload, width, height, fmt):
    fourccs = {'BC1_UNORM': b'DXT1', 'BC1_UNORM_SRGB': b'DXT1', 'BC2_UNORM': b'DXT3',
               'BC3_UNORM': b'DXT5', 'BC3_UNORM_SRGB': b'DXT5'}
    dxgi = {'BC4_UNORM': 80, 'BC5_UNORM': 83, 'BC7_UNORM': 98, 'BC7_UNORM_SRGB': 99}
    if fmt not in fourccs and fmt not in dxgi:
        raise ValueError(f'Unsupported texture format {fmt}')
    code = fourccs.get(fmt, b'DX10')
    size = max(1, (width + 3) // 4) * (8 if fmt.startswith(('BC1', 'BC4')) else 16)
    header = b'DDS ' + struct.pack('<7I', 124, 0x81007, height, width, size, 0, 0)
    header += bytes(44) + struct.pack('<2I4s5I', 32, 4, code, 0, 0, 0, 0, 0)
    header += struct.pack('<5I', 0x1000, 0, 0, 0, 0)
    if code == b'DX10':
        header += struct.pack('<5I', dxgi[fmt], 3, 0, 1, 0)
    return header + payload


class Reader:
    def __init__(self, archive):
        self.archive = archive
        self.names = {n.lower(): n for n in archive.namelist()}
        cache = ROOT / 'build/local_game_reference'
        self.cache = {p.name.lower(): p for p in cache.rglob('*') if p.is_file()}
        self.cached_resources_used = set()

    def raw(self, binary, expected=None):
        key = binary.lower()
        if key in self.names:
            raw = self.archive.read(self.names[key])
        elif key in self.cache:
            raw = self.cache[key].read_bytes()
            self.cached_resources_used.add(str(self.cache[key].relative_to(ROOT)))
        else:
            raise ValueError(f'Missing resource: {binary}')
        if raw[:2] == b'\x1f\x8b':
            if raw[12:16] == b'VCZ\x00':
                try:
                    raw = zlib.decompress(raw[16:-8])
                except zlib.error as exc:
                    cached = self.cache.get(key)
                    if cached is not None:
                        decoded = cached.read_bytes()
                        if decoded[:2] != b'\x1f\x8b' and (expected is None or len(decoded) == expected):
                            self.cached_resources_used.add(str(cached.relative_to(ROOT)))
                            raw = decoded
                        else:
                            raise ValueError(f'Oodle/unsupported VCZ: {binary}') from exc
                    else:
                        raise ValueError(f'Oodle/unsupported VCZ: {binary}') from exc
            else:
                try:
                    raw = gzip.decompress(raw)
                except (OSError, zlib.error) as exc:
                    raise ValueError(f'Unsupported compression: {binary}') from exc
        if expected is not None and len(raw) != expected:
            raise ValueError(f'Resource length mismatch: {binary} ({len(raw)} != {expected})')
        return raw

    def attribute(self, model, semantic):
        f = model['VertexFormat'][semantic]
        formats = {'R16G16B16A16_UNORM': ('<u2', 4, 65535), 'R32G32B32_FLOAT': ('<f4', 3, None),
                   'R32G32_FLOAT': ('<f4', 2, None), 'R16G16_SNORM': ('<i2', 2, 32767),
                   'R16G16B16A16_SNORM': ('<i2', 4, 32767)}
        if f['Format'] not in formats:
            raise ValueError(f'Unsupported {semantic} format {f["Format"]}')
        dtype, width, divisor = formats[f['Format']]
        stream = model['VertexStream'][f.get('Stream', 0)]
        raw = self.raw(stream['Binary'], stream['Size'])
        if len(raw) % stream['Stride']:
            raise ValueError('Unaligned vertex stream')
        values = np.ndarray((len(raw) // stream['Stride'], width), dtype, raw,
                            offset=f.get('ByteOffset', 0), strides=(stream['Stride'], np.dtype(dtype).itemsize)).astype(float)
        if divisor:
            values /= divisor
            if dtype == '<i2':
                values = np.maximum(values, -1)
        return values * np.array(f.get('Scale', [1] * width))[:width] + np.array(f.get('Offset', [0] * width))[:width]


class HiddenDegenerate(Exception):
    """All declared primitive/LOD triangles are provably index-degenerate."""


def all_index_triangles_degenerate(model, indices):
    """Sufficient geometric proof using indices alone, including every LOD.

    A triangle with any repeated vertex index has zero area for every possible
    position buffer. Missing/invalid ranges are errors, never evidence of hiding.
    """
    ranges, cursor = [], 0
    for prim in model.get('Prim', []):
        start, count = int(prim.get('Start', cursor)), int(prim.get('Count', 0))
        cursor = start + count
        if prim.get('Type', 'TRIANGLE_LIST') != 'TRIANGLE_LIST':
            raise ValueError('Unsupported primitive type during visibility audit')
        ranges.append((start, count))
        for lod in prim.get('LodList', []):
            ranges.append((int(lod.get('Start', start)), int(lod.get('Count', count))))
    nonempty = False
    for start, count in ranges:
        if start < 0 or count < 0 or start + count > len(indices) or count % 3:
            raise ValueError('Invalid primitive/LOD range during visibility audit')
        if not count:
            continue
        nonempty = True
        triangles = indices[start:start + count].reshape(-1, 3)
        repeated = ((triangles[:, 0] == triangles[:, 1]) | (triangles[:, 1] == triangles[:, 2])
                    | (triangles[:, 2] == triangles[:, 0]))
        if not np.all(repeated):
            return False
    return nonempty


def build_preview(iff_path, output_dir, *, three_dir=None):
    iff_path, output_dir = Path(iff_path), Path(output_dir)
    if three_dir is None:
        three_dir = next((p for p in THREE_CANDIDATES if (p / 'build/three.module.js').exists()), None)
    if three_dir is None:
        raise ValueError('Pass --three-dir pointing to an existing Three.js package; this script installs nothing')
    three_dir = Path(three_dir)
    for relative in ('build/three.module.js', 'build/three.core.js', 'examples/jsm/controls/OrbitControls.js', 'LICENSE'):
        if not (three_dir / relative).is_file():
            raise ValueError(f'Missing existing Three.js file: {relative}')
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'textures').mkdir(exist_ok=True)
    (output_dir / 'vendor').mkdir(exist_ok=True)
    for source, target in [('build/three.module.js', 'three.module.js'), ('build/three.core.js', 'three.core.js'),
                           ('examples/jsm/controls/OrbitControls.js', 'OrbitControls.js'), ('LICENSE', 'THREE-LICENSE.txt')]:
        shutil.copyfile(three_dir / source, output_dir / 'vendor' / target)
    blob = bytearray()

    def buffer(array, dtype):
        while len(blob) % 4:
            blob.append(0)
        array = np.ascontiguousarray(array, dtype=dtype)
        info = {'offset': len(blob), 'length': int(array.size), 'dtype': dtype}
        blob.extend(array.tobytes())
        return info

    scene = {'models': {}, 'objects': [], 'materials': {}, 'issues': [], 'source': str(iff_path),
             'source_sha256': hashlib.sha256(iff_path.read_bytes()).hexdigest(),
             'preview_kind': 'EXPORTED_GEOMETRY_AND_ALBEDO_NOT_NBA2K_RENDER',
             'lighting': 'Neutral daylight approximation; actual NBA 2K lighting/shaders are not executed',
             'cameras': [
                 {'name': '全场', 'position': [0, 850, 2200], 'target': [0, 200, -200]},
                 {'name': '底线', 'position': [1100, 250, 1650], 'target': [0, 350, -500]},
                 {'name': '边线', 'position': [-1300, 250, 600], 'target': [500, 420, 0]},
                 {'name': '俯瞰', 'position': [2400, 2900, 2900], 'target': [0, 100, 0]}]}
    texture_cache = {}

    def material(scope, name, document, reader):
        key = f'{scope}:{name}'
        if key in scene['materials']:
            return key
        source = document.get('Material', {}).get(name, {})
        resources = source.get('Resource', {})
        effect = document.get('Effect', {}).get(source.get('Effect'), {})
        native_pass = dict(effect.get('Technique', {}).get('Default', {}).get('Pass', {}).get('Default', {}))
        native_pass.update(source.get('Technique', {}).get('Default', {}).get('Pass', {}).get('Default', {}))
        chosen = next((slot for slot in ('AlbedoMap', 'DetailAlbedoTexture', 'DiffuseTexture', 'BaseColorMap', 'AlbedoTexture', 'BaseTexture') if slot in resources), None)
        entry = {'name': name, 'color': [1., 1., 1.], 'roughness': .88, 'metalness': 0.,
                 'texture': None, 'uv_channel': 0, 'source_effect': source.get('Effect'), 'texture_verified': False,
                 'depth_bias': float(native_pass.get('DEPTHBIAS', 0)),
                 'slope_depth_bias': float(native_pass.get('SLOPESCALEDEPTHBIAS', 0)),
                 'depth_bias_clamp': native_pass.get('DEPTHBIASCLAMP'),
                 'depth_write': bool(native_pass.get('ZWRITEENABLE', 1)),
                 'depth_comparison': native_pass.get('ZFUNC', 'LESSEQUAL')}
        if chosen:
            try:
                texname = resources[chosen]['Pixelmap']
                spec = document['Texture'][texname]
                raw = reader.raw(spec['Binary'])
                if raw[:4] != b'TLD ':
                    raise ValueError('Only actual TLD texture resources are supported')
                texture_hash = hashlib.sha256(raw).hexdigest()
                if texture_hash not in texture_cache:
                    png = f'textures/{texture_hash[:20]}.png'
                    decoded = Image.open(io.BytesIO(_dds(raw[32:], spec['Width'], spec['Height'], spec['Format']))).convert('RGBA')
                    decoded.save(output_dir / png)
                    texture_cache[texture_hash] = png
                entry['texture'] = texture_cache[texture_hash]
                entry['texture_verified'] = True
                entry['uv_channel'] = effect.get('Resource', {}).get(chosen, {}).get('Texcoord', 0)
                params = source.get('Parameter', {})
                tint = params.get('AlbedoModulate', params.get('ModulateAlbedo', [1, 1, 1]))
                entry['color'] = list(tint[:3])
                entry['sky'] = 'sky' in name.lower()
            except (ValueError, KeyError, OSError) as exc:
                entry['color'] = [.75, .22, .7]
                scene['issues'].append({'kind': 'texture', 'name': key, 'reason': str(exc)})
        else:
            entry['color'] = [.75, .22, .7]
            scene['issues'].append({'kind': 'texture', 'name': key, 'reason': 'No supported albedo slot; shown magenta'})
        scene['materials'][key] = entry
        return key

    with zipfile.ZipFile(iff_path) as archive:
        reader = Reader(archive)
        for scene_file in ('level.SCNE', 'baskets.SCNE'):
            if scene_file not in archive.namelist():
                scene['issues'].append({'kind': 'scene', 'name': scene_file, 'reason': 'Scene file absent'})
                continue
            roots = _json_fragment(archive.read(scene_file))
            for scope, document in roots.items():
                objects = [(name, obj) for name, obj in document.get('Object', {}).items() if obj.get('Type') == 'OBJECT']
                for name, obj in objects:
                    target = obj.get('Target')
                    model_key = f'{scope}:{target}'
                    model = document.get('Model', {}).get(target)
                    instance = {'name': name, 'model': model_key, 'matrix': obj.get('Matrix', IDENTITY),
                                'scope': scope, 'transform_reference': obj.get('Transform')}
                    if not model:
                        instance['unavailable'] = True
                        scene['issues'].append({'kind': 'object', 'name': name, 'reason': f'Target model unavailable: {target}'})
                        scene['objects'].append(instance)
                        continue
                    if model_key not in scene['models']:
                        result = {'name': target, 'bounds_min': model.get('Min'), 'bounds_max': model.get('Max'), 'placeholder': False}
                        try:
                            # Audit visibility before unavailable vertex/skin data.
                            # This skips only actual zero-area exported primitives,
                            # never an object merely named roof/wall/hidden.
                            index_format = model['IndexBuffer']['Format']
                            if index_format not in ('R16_UINT', 'R32_UINT'):
                                raise ValueError(f'Unsupported index format {index_format}')
                            indices = np.frombuffer(reader.raw(model['IndexBuffer']['Binary'], model['IndexBuffer']['Size']), '<u2' if index_format == 'R16_UINT' else '<u4')
                            if all_index_triangles_degenerate(model, indices):
                                raise HiddenDegenerate('Every declared Prim/Lod triangle repeats a vertex index; actual exported surface area is zero')
                            if 'WEIGHTDATA0' in model.get('VertexFormat', {}):
                                raise ValueError('Native skinned basket: bone weights/pose not decoded; showing authoring bounds under actual Object.Matrix')
                            if scope == 'baskets' and obj.get('Transform'):
                                raise ValueError('Native basket rig/reflection transform unresolved; showing authoring bounds under actual Object.Matrix')
                            positions = reader.attribute(model, 'POSITION0')[:, :3]
                            groups, used_indices, cursor, current_material = [], [], 0, None
                            for prim in model.get('Prim', []):
                                start, count = int(prim.get('Start', cursor)), int(prim.get('Count', 0))
                                cursor = start + count
                                current_material = prim.get('Material', current_material)
                                if not count:
                                    continue
                                if prim.get('Type', 'TRIANGLE_LIST') != 'TRIANGLE_LIST' or count % 3 or cursor > len(indices):
                                    raise ValueError('Unsupported or out-of-range primitive')
                                selected = indices[start:cursor]
                                if selected.max() >= len(positions):
                                    raise ValueError('Vertex index outside position stream')
                                groups.append({'start': sum(len(v) for v in used_indices), 'count': count,
                                               'material': material(scope, current_material, document, reader)})
                                used_indices.append(selected)
                            if not used_indices:
                                raise ValueError('Model has no nonempty triangle primitives')
                            result['position'] = buffer(positions, '<f4')
                            result['index'] = buffer(np.concatenate(used_indices), '<u4')
                            result['groups'] = groups
                            result['vertices'] = len(positions)
                            result['triangles'] = sum(len(v) for v in used_indices) // 3
                            result['uvs'] = {}
                            for channel in range(3):
                                if f'TEXCOORD{channel}' in model['VertexFormat']:
                                    uv = reader.attribute(model, f'TEXCOORD{channel}')[:, :2]
                                    result['uvs'][str(channel)] = buffer(uv, '<f4')
                            normal_spec = model['VertexFormat'].get('TANGENTFRAME0')
                            if normal_spec and normal_spec['Format'] == 'R10G10B10A2_UINT':
                                stream = model['VertexStream'][normal_spec.get('Stream', 0)]
                                raw = reader.raw(stream['Binary'], stream['Size'])
                                packed = np.ndarray((len(positions),), '<u4', raw,
                                                    offset=normal_spec.get('ByteOffset', 0), strides=(stream['Stride'],))
                                result['normal'] = buffer(_decode_normal(packed), '<f4')
                            elif 'NORMAL0' in model['VertexFormat']:
                                result['normal'] = buffer(reader.attribute(model, 'NORMAL0')[:, :3], '<f4')
                            else:
                                result['normal_source'] = 'geometric_vertex_normal_fallback'
                        except HiddenDegenerate as exc:
                            result = {'name': target, 'bounds_min': model.get('Min'), 'bounds_max': model.get('Max'),
                                      'placeholder': False, 'hidden_degenerate': True, 'reason': str(exc)}
                        except (ValueError, KeyError, OSError) as exc:
                            result = {'name': target, 'bounds_min': model.get('Min'), 'bounds_max': model.get('Max'),
                                      'placeholder': True, 'reason': str(exc)}
                            scene['issues'].append({'kind': 'geometry', 'name': model_key, 'reason': str(exc)})
                        scene['models'][model_key] = result
                    scene['objects'].append(instance)
        scene['cached_resources_used'] = sorted(reader.cached_resources_used)
    scene['stats'] = {'objects': len(scene['objects']),
                      'decoded_models': sum(not m['placeholder'] and not m.get('hidden_degenerate') for m in scene['models'].values()),
                      'placeholder_models': sum(m['placeholder'] for m in scene['models'].values()),
                      'hidden_degenerate_models': sum(bool(m.get('hidden_degenerate')) for m in scene['models'].values()),
                      'hidden_degenerate_objects': sum(bool(scene['models'].get(o['model'], {}).get('hidden_degenerate')) for o in scene['objects']),
                      'decoded_triangles_per_prototype': sum(m.get('triangles', 0) for m in scene['models'].values()),
                      'texture_files': len(texture_cache), 'issues': len(scene['issues'])}
    (output_dir / 'mesh.bin').write_bytes(blob)
    (output_dir / 'scene.json').write_text(json.dumps(scene, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    (output_dir / 'index.html').write_text(HTML, encoding='utf-8')
    (output_dir / 'viewer.js').write_text(JS, encoding='utf-8')
    report = {'source': str(iff_path), 'source_sha256': scene['source_sha256'], 'output': str(output_dir),
              'stats': scene['stats'], 'cached_resources_used': scene['cached_resources_used'],
              'three_version': json.loads((three_dir / 'package.json').read_text())['version'],
              'kind': scene['preview_kind'], 'source_archives_modified': False, 'issues': scene['issues']}
    (output_dir / 'preview_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


HTML = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>球场 V3 · 实际导出模型检查</title><style>
*{box-sizing:border-box}body{margin:0;overflow:hidden;background:#b9d6e4;font:14px -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;color:#f5f6f7}canvas{display:block}aside{position:fixed;left:18px;top:18px;max-width:560px;padding:14px 18px;background:#14212be8;border:1px solid #ffffff29;border-radius:10px}strong{font-size:18px}p{line-height:1.6;margin:7px 0;color:#cad5df}nav{display:flex;gap:6px;flex-wrap:wrap;margin-top:12px}button{background:#ffffff15;color:#eef4f9;border:1px solid #ffffff35;border-radius:6px;padding:7px 14px;cursor:pointer}button:hover,button.active{background:#3b7188}#details{position:fixed;bottom:16px;left:18px;max-width:640px;max-height:220px;overflow:auto;background:#14212be8;border-radius:8px;padding:10px 15px;font-size:12px;color:#d0dae4}#details li{margin:5px 0}summary{cursor:pointer}#progress{font-weight:600;color:#f1cf8a}footer{position:fixed;right:16px;bottom:16px;padding:8px 12px;background:#14212bd9;border-radius:8px;font-size:12px;color:#d9e4ec}
</style><script type="importmap">{"imports":{"three":"./vendor/three.module.js","three/addons/":"./vendor/"}}</script>
<aside><strong>球场 V3 · 实际导出模型检查</strong><p>直接解码交付 IFF 的几何、实例矩阵与颜色贴图。<br>这是中性日光预览，<b>并非 2K 游戏画面或 shader 验收</b>。</p><div id="progress">正在读取模型…</div><nav id="cameras"></nav></aside>
<details id="details"><summary id="summary">资源检查结果</summary><ul id="issues"></ul></details>
<footer>拖动旋转 · 滚轮缩放 · 右键平移 · 1–4 切换机位 · W 线框</footer><script type="module" src="./viewer.js"></script></html>'''

JS = r'''import * as THREE from 'three';
import {OrbitControls} from 'three/addons/OrbitControls.js';
const [data, binary] = await Promise.all([fetch('./scene.json').then(r=>r.json()),fetch('./mesh.bin').then(r=>r.arrayBuffer())]);
const renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setSize(innerWidth,innerHeight);renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.0;renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;document.body.prepend(renderer.domElement);
const scene=new THREE.Scene();scene.background=new THREE.Color('#acd2e7');
const camera=new THREE.PerspectiveCamera(52,innerWidth/innerHeight,3,80000);
const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.12;controls.maxDistance=30000;controls.minDistance=20;
scene.add(new THREE.HemisphereLight('#e5f4ff','#696e56',2.0));const sun=new THREE.DirectionalLight('#fff7e5',2.5);sun.position.set(-3500,5500,2500);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);sun.shadow.camera.left=-4500;sun.shadow.camera.right=4500;sun.shadow.camera.top=4500;sun.shadow.camera.bottom=-4500;sun.shadow.camera.near=300;sun.shadow.camera.far=12000;sun.shadow.bias=-.0001;sun.shadow.normalBias=1;scene.add(sun);
const manager=new THREE.LoadingManager(),loader=new THREE.TextureLoader(manager);let textureCount=0;const materials={};
for(const[key,m]of Object.entries(data.materials)){const texture=m.texture?loader.load(m.texture):null;if(texture){texture.flipY=false;texture.colorSpace=THREE.SRGBColorSpace;texture.wrapS=texture.wrapT=THREE.RepeatWrapping;texture.anisotropy=Math.min(8,renderer.capabilities.getMaxAnisotropy());texture.channel=m.uv_channel;textureCount++;}
 const settings={color:new THREE.Color(...m.color),map:texture,side:THREE.FrontSide,roughness:m.roughness,metalness:m.metalness};const material=m.sky?new THREE.MeshBasicMaterial({color:settings.color,map:texture,side:THREE.FrontSide}):new THREE.MeshStandardMaterial(settings);material.depthWrite=m.depth_write;if(m.depth_bias||m.slope_depth_bias){material.polygonOffset=true;material.polygonOffsetFactor=m.slope_depth_bias;material.polygonOffsetUnits=m.depth_bias;}const depthModes={LESS:THREE.LessDepth,LESSEQUAL:THREE.LessEqualDepth,EQUAL:THREE.EqualDepth,GREATER:THREE.GreaterDepth,GREATEREQUAL:THREE.GreaterEqualDepth,ALWAYS:THREE.AlwaysDepth};if(depthModes[m.depth_comparison]!==undefined)material.depthFunc=depthModes[m.depth_comparison];material.name=m.name;materials[key]=material;}
const array=info=>info.dtype==='<u4'?new Uint32Array(binary,info.offset,info.length):new Float32Array(binary,info.offset,info.length);
const prototypes={};for(const[key,m]of Object.entries(data.models)){if(m.placeholder||m.hidden_degenerate)continue;const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(array(m.position),3));geometry.setIndex(new THREE.BufferAttribute(array(m.index),1));if(m.normal)geometry.setAttribute('normal',new THREE.BufferAttribute(array(m.normal),3));else geometry.computeVertexNormals();for(const[channel,info]of Object.entries(m.uvs))geometry.setAttribute(channel==='0'?'uv':`uv${channel}`,new THREE.BufferAttribute(array(info),2));const mats=m.groups.map(g=>materials[g.material]);for(let i=0;i<m.groups.length;i++)geometry.addGroup(m.groups[i].start,m.groups[i].count,i);geometry.computeBoundingSphere();prototypes[key]={geometry,materials:mats};}
let rendered=0,placeholders=0,unbounded=0,hidden=0;const meshes=[];
for(const obj of data.objects){const m=data.models[obj.model];if(!m){unbounded++;continue;}if(m.hidden_degenerate){hidden++;continue;}const group=new THREE.Group();group.name=obj.name;group.matrix.fromArray(obj.matrix);group.matrixAutoUpdate=false;if(m.placeholder){if(m.bounds_min&&m.bounds_max){const min=new THREE.Vector3(...m.bounds_min),max=new THREE.Vector3(...m.bounds_max),bounds=new THREE.Box3(min,max),helper=new THREE.Box3Helper(bounds,0xee58db);group.add(helper);placeholders++;}else unbounded++;}else{const p=prototypes[obj.model],mesh=new THREE.Mesh(p.geometry,p.materials);mesh.name=obj.name;mesh.castShadow=true;mesh.receiveShadow=true;group.add(mesh);meshes.push(mesh);rendered++;}scene.add(group);}
function setCamera(index){const preset=data.cameras[index];camera.position.fromArray(preset.position);controls.target.fromArray(preset.target);controls.update();document.querySelectorAll('#cameras button').forEach((b,i)=>b.classList.toggle('active',i===index));window.previewCamera=index;}
data.cameras.forEach((c,i)=>{const b=document.createElement('button');b.textContent=`${i+1} ${c.name}`;b.onclick=()=>setCamera(i);document.querySelector('#cameras').append(b);});setCamera(0);
window.addEventListener('keydown',e=>{if('1234'.includes(e.key))setCamera(Number(e.key)-1);if(e.key.toLowerCase()==='w')for(const m of Object.values(materials))m.wireframe=!m.wireframe;});
const progress=document.querySelector('#progress');const status=()=>{progress.textContent=`${rendered} 个实体 · ${placeholders} 个未解码边界框 · ${hidden} 个实际索引退化隐藏`;window.previewReady=true;};manager.onLoad=status;if(!textureCount)status();manager.onError=url=>{data.issues.push({kind:'browser-texture',name:url,reason:'浏览器贴图加载失败'});progress.textContent='部分纹理加载失败，请查看控制台';};
document.querySelector('#summary').textContent=`完整性：${data.issues.length} 项提示 · 品红边界框代表未解码资源${unbounded?` · ${unbounded} 个对象无可用边界`:''}`;
for(const issue of data.issues){const li=document.createElement('li');li.textContent=`[${issue.kind}] ${issue.name} — ${issue.reason}`;document.querySelector('#issues').append(li);}
window.previewAudit={...data.stats,rendered_objects:rendered,placeholder_objects:placeholders,hidden_degenerate_objects:hidden,unbounded_objects:unbounded,source_sha256:data.source_sha256,kind:data.preview_kind};window.previewSetCamera=setCamera;window.previewScene=scene;window.previewRenderer=renderer;
addEventListener('resize',()=>{camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);});
renderer.setAnimationLoop(()=>{controls.update();renderer.render(scene,camera);});
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iff', type=Path, default=ROOT / 'output/revision3/arena_700_int.iff')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/revision3/preview')
    parser.add_argument('--three-dir', type=Path)
    args = parser.parse_args()
    report = build_preview(args.iff, args.output_dir, three_dir=args.three_dir)
    print(json.dumps({key: value for key, value in report.items() if key != 'issues'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
