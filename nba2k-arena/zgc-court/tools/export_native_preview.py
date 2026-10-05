"""Decode the delivered IFF into a browser GLB, without reading source geometry.

Python + numpy + Pillow only. The IFF remains read-only. Runtime cloth, custom
game shaders and independently loaded game assets are not simulated.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import struct
import time
import zipfile
import numpy as np
from PIL import Image
from iff_codec import decode_attribute, decode_normals, load_scne, resolve_binary

ROOT = Path(__file__).resolve().parents[1]


def sha_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class GLB:
    def __init__(self):
        self.binary = bytearray()
        self.doc = {'asset': {'version': '2.0', 'generator': 'ZGC final IFF decoder'},
                    'scene': 0, 'scenes': [{'nodes': []}], 'nodes': [], 'meshes': [],
                    'materials': [], 'images': [], 'textures': [], 'samplers': [
                        {'magFilter': 9729, 'minFilter': 9987, 'wrapS': 10497, 'wrapT': 10497}],
                    'accessors': [], 'bufferViews': [], 'buffers': []}

    def view(self, data, target=None):
        while len(self.binary) % 4:
            self.binary.append(0)
        view = {'buffer': 0, 'byteOffset': len(self.binary), 'byteLength': len(data)}
        if target:
            view['target'] = target
        self.binary.extend(data)
        self.doc['bufferViews'].append(view)
        return len(self.doc['bufferViews']) - 1

    def accessor(self, values, kind, indices=False, bounds=False):
        values = np.asarray(values, dtype='<u4' if indices else '<f4')
        if not np.isfinite(values).all():
            raise ValueError('Nonfinite decoded geometry')
        acc = {'bufferView': self.view(values.tobytes(), 34963 if indices else 34962),
               'componentType': 5125 if indices else 5126, 'count': len(values), 'type': kind}
        if bounds:
            acc.update(min=values.min(axis=0).tolist(), max=values.max(axis=0).tolist())
        self.doc['accessors'].append(acc)
        return len(self.doc['accessors']) - 1

    def image(self, image, name):
        stream = io.BytesIO()
        image.save(stream, format='PNG', compress_level=3)
        self.doc['images'].append({'name': name, 'bufferView': self.view(stream.getvalue()), 'mimeType': 'image/png'})
        self.doc['textures'].append({'source': len(self.doc['images']) - 1, 'sampler': 0})
        return len(self.doc['textures']) - 1

    def write(self, target):
        self.doc['buffers'] = [{'byteLength': len(self.binary)}]
        meta = json.dumps(self.doc, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        meta += b' ' * (-len(meta) % 4)
        self.binary.extend(b'\0' * (-len(self.binary) % 4))
        total = 12 + 8 + len(meta) + 8 + len(self.binary)
        with target.open('wb') as out:
            out.write(struct.pack('<4sII', b'glTF', 2, total))
            out.write(struct.pack('<II', len(meta), 0x4e4f534a)); out.write(meta)
            out.write(struct.pack('<II', len(self.binary), 0x004e4942)); out.write(self.binary)


def category(name, bounds, tags=()):
    text = name.lower()
    labels = {str(tag).lower() for tag in tags}
    if 'ground' in labels:
        return 'ground', 'ground'
    if 'hoops' in labels:
        return ('open_half' if 'open_half' in labels else 'reference_half'), 'hoops'
    if 'fence' in labels:
        return 'fence', 'fence'
    if 'court_surface' in text or 'plaza ground' in text or 'paving' in text:
        return 'ground', 'ground'
    if any(key in text for key in ('fence', 'chainlink', 'chain link', 'wind screen', 'windscreen')):
        return 'fence', 'fence'
    if any(key in text for key in ('hoop', 'basket', 'backboard', 'rim', ' net ', 'r02 main reach', 'stanchion', 'support')) or '.open' in text or '.reference' in text:
        return ('open_half' if '.open' in text else 'reference_half'), 'hoops'
    if not labels and bounds[1][1] - bounds[0][1] < .03 and bounds[1][1] < .2 and min(bounds[1][axis] - bounds[0][axis] for axis in (0, 2)) > 1:
        return 'ground', 'ground'
    return 'background', 'background'


class NativeDecoder:
    def __init__(self, archive, glb, max_texture):
        self.archive = archive; self.glb = glb; self.max_texture = max_texture
        self.materials = {}; self.textures = {}; self.texture_report = []; self.mesh_report = []
        self.game_world_yaw_degrees = 0

    def dds(self, section, pixelmap):
        spec = section['Texture'][pixelmap]
        alias = str(PurePosixPath(spec['Binary']).with_suffix('.dds'))
        raw = self.archive.read(alias)
        if raw[:4] != b'DDS ':
            raise ValueError('Not a DDS: ' + alias)
        image = Image.open(io.BytesIO(raw)); image.load()
        original = image.size
        if original != (spec['Width'], spec['Height']):
            raise ValueError('DDS dimensions disagree with scene: ' + alias)
        if max(image.size) > self.max_texture:
            image.thumbnail((self.max_texture, self.max_texture), Image.Resampling.LANCZOS)
        self.texture_report.append({'resource': pixelmap, 'dds': alias, 'dds_sha256': hashlib.sha256(raw).hexdigest(),
                                    'native_dimensions': list(original), 'preview_dimensions': list(image.size)})
        return image

    def texture(self, section, pixelmap, role='albedo', alpha_mask=None, metallic=None):
        spec = section['Texture'][pixelmap]
        key = (spec['Binary'], role, alpha_mask, metallic)
        if key in self.textures:
            return self.textures[key]
        image = self.dds(section, pixelmap).convert('RGBA')
        if role == 'roughness':
            # Native normal+roughness packs roughness in A; glTF stores it in G.
            a = np.asarray(image)
            mr = np.full(a.shape[:2] + (3,), 255, dtype=np.uint8)
            mr[:, :, 1] = a[:, :, 3]
            if metallic:
                mr[:, :, 2] = np.asarray(self.dds(section, metallic).convert('L').resize(image.size))
            image = Image.fromarray(mr)
        elif role == 'metalrough':
            a = np.asarray(image)
            mr = np.full(a.shape[:2] + (3,), 255, dtype=np.uint8)
            mr[:, :, 1] = a[:, :, 0]
            if metallic:
                mr[:, :, 2] = np.asarray(self.dds(section, metallic).convert('L').resize(image.size))
            image = Image.fromarray(mr)
        elif alpha_mask:
            a = np.asarray(image).copy()
            mask = np.asarray(self.dds(section, alpha_mask).convert('L').resize(image.size))
            a[:, :, 3] = (a[:, :, 3].astype(np.uint16) * mask.astype(np.uint16) // 255).astype(np.uint8)
            image = Image.fromarray(a)
        index = self.glb.image(image, PurePosixPath(spec['Binary']).stem + '-' + role)
        self.textures[key] = index
        return index

    def material(self, section, name, ground=False):
        key = (name, ground)
        if key in self.materials:
            return self.materials[key]
        spec = section['Material'][name]
        res = spec.get('Resource', {}); params = spec.get('Parameter', {})
        dedicated_glass = spec.get('Effect', '').startswith('basket_glass.fx#')
        modulation = list(params.get('AlbedoModulate', [1, 1, 1, 1]))
        pbr = {'baseColorFactor': modulation, 'metallicFactor': float(params.get('DefaultMetalness', 0)),
               'roughnessFactor': float(params.get('DefaultRoughness', .7))}
        albedo = res.get('AlbedoMapBC3') or res.get('AlbedoMap') or res.get('Albedo')
        alpha = res.get('AlphaMaskMap', {}).get('Pixelmap')
        if params.get('AlphaStyle')=='TRANSLUCENT' and 'AlbedoMapBC3' in res:
            # Native global-alpha separates opaque paint from transmissive
            # glass; its RGB is black and is not a glTF opacity multiplier.
            # Browser approximation uses actual albedo alpha for this surface.
            alpha = None
        if albedo:
            pbr['baseColorTexture'] = {'index': self.texture(section, albedo['Pixelmap'], alpha_mask=alpha)}
        else:
            pbr['baseColorFactor'] = list(params.get('DefaultAlbedo', [1, 1, 1]))[:3] + [params.get('DefaultAlpha', 1)]
        normal = res.get('NormalAndRoughMap', {}).get('Pixelmap')
        rough = (res.get('RoughMap') or res.get('RoughnessTexture') or {}).get('Pixelmap')
        metal = res.get('MetalMap', {}).get('Pixelmap')
        if normal or rough:
            pbr['metallicRoughnessTexture'] = {'index': self.texture(section, normal or rough,
                                                'roughness' if normal else 'metalrough', metallic=metal)}
            pbr['roughnessFactor'] = 1
            if metal:
                pbr['metallicFactor'] = 1
        culls = [p.get('CULLMODE') for t in spec.get('Technique', {}).values() for p in t.get('Pass', {}).values()]
        material = {'name': name, 'pbrMetallicRoughness': pbr, 'doubleSided': 'NONE' in culls,
                    'extras': {'native_material': name, 'decoded_from_iff': True}}
        if ground:
            material['extras']['ground_artwork_mode'] = 'world-paving-atlas'
        if dedicated_glass or 'AlbedoMapBC3' in res or params.get('AlphaStyle') == 'TRANSLUCENT':
            material['alphaMode'] = 'BLEND'; material['doubleSided'] = True
        self.glb.doc['materials'].append(material)
        result = len(self.glb.doc['materials']) - 1
        self.materials[key] = result
        return result

    def mesh(self, section, name, label, matrix=None, native_basket=False, tags=()):
        spec = section['Model'][name]
        positions = decode_attribute(self.archive, spec, 'POSITION0')[:, :3]
        normals = decode_normals(decode_attribute(self.archive, spec, 'TANGENTFRAME0'))
        uv = decode_attribute(self.archive, spec, 'TEXCOORD0')[:, :2]
        if matrix is not None:
            matrix = np.asarray(matrix, float).reshape(4, 4)
            positions = (np.column_stack((positions, np.ones(len(positions)))) @ matrix)[:, :3]
            normals = normals @ np.linalg.inv(matrix[:3, :3]).T
        # Game Y-up centimetres -> the same Y-up metres as the source web view.
        positions = positions[:, [2, 1, 0]] / 100
        positions[:, 2] *= -1
        normals = normals[:, [2, 1, 0]]; normals[:, 2] *= -1
        normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
        bounds = [positions.min(0).tolist(), positions.max(0).tolist()]
        layer, group = category(label, bounds, tags)
        if native_basket:
            reference_sign = 1 if self.game_world_yaw_degrees == 180 else -1
            layer, group = ('reference_half' if positions[:, 0].mean() * reference_sign > 0 else 'open_half'), 'hoops'
        ib = spec['IndexBuffer']
        dtype = {'R16_UINT': '<u2', 'R32_UINT': '<u4'}[ib['Format']]
        source_indices = np.frombuffer(self.archive.read(resolve_binary(self.archive, ib['Binary'])), dtype)
        primitives = []; inherited = {}; triangles = 0
        attributes = None
        for prim in spec['Prim']:
            inherited.update({k: v for k, v in prim.items() if k in ('Type', 'Material')})
            if inherited.get('Type') != 'TRIANGLE_LIST':
                raise ValueError('Unsupported primitive type: ' + name)
            draw = (prim.get('LodList') or [prim])[0]
            indices = source_indices[draw['Start']:draw['Start'] + draw['Count']].astype(np.uint32).reshape(-1, 3)
            if indices.size and int(indices.max()) >= len(positions):
                raise ValueError('Native index is out of range: ' + name)
            # Disabled donor primitives are deliberately degenerated in the IFF.
            indices = indices[(indices[:, 0] != indices[:, 1]) & (indices[:, 0] != indices[:, 2]) & (indices[:, 1] != indices[:, 2])]
            if not len(indices):
                continue
            if attributes is None:
                attributes = {'POSITION': self.glb.accessor(positions, 'VEC3', bounds=True),
                              'NORMAL': self.glb.accessor(normals, 'VEC3'), 'TEXCOORD_0': self.glb.accessor(uv, 'VEC2')}
            primitives.append({'attributes': attributes, 'indices': self.glb.accessor(indices.reshape(-1), 'SCALAR', indices=True),
                               'material': self.material(section, inherited['Material'], group == 'ground'), 'mode': 4})
            triangles += len(indices)
        if not primitives:
            return
        self.glb.doc['meshes'].append({'name': name, 'primitives': primitives})
        self.glb.doc['nodes'].append({'name': label, 'mesh': len(self.glb.doc['meshes']) - 1,
                                     'extras': {'layer': layer, 'category': group, 'native_model': name,
                                                'decoded_from_native_iff': True, 'native_basket_rest_pose': native_basket}})
        self.glb.doc['scenes'][0]['nodes'].append(len(self.glb.doc['nodes']) - 1)
        self.mesh_report.append({'model': name, 'label': label, 'vertices': len(positions), 'triangles': triangles,
                                 'bounds_gltf_m': bounds, 'category': group})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--iff', default=str(ROOT / 'output/arena_700_int.iff'))
    parser.add_argument('--labels', default=str(ROOT / 'validation/native-source-build.json'))
    parser.add_argument('--max-texture', type=int, default=4096)
    args = parser.parse_args()
    path = Path(args.iff).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('IFF input must remain inside this project')
    if args.max_texture not in (2048, 4096, 8192):
        raise ValueError('Unsupported preview texture resolution')
    labels_path = Path(args.labels).resolve()
    if not labels_path.is_relative_to(ROOT):
        raise ValueError('Labels must remain inside this project')
    labels = {}
    if labels_path.exists():
        labels = {x['model']: x for x in json.loads(labels_path.read_text(encoding='utf8')).get('models', [])}
    output = ROOT / 'public/game-preview'; output.mkdir(parents=True, exist_ok=True)
    source_stat = path.stat(); source_hash = sha_file(path)
    glb = GLB()
    with zipfile.ZipFile(path) as archive:
        decoder = NativeDecoder(archive, glb, args.max_texture)
        level = load_scne(archive.read('level.SCNE'))['level']
        orientations = set()
        for name, obj in level['Object'].items():
            target = obj.get('Target', '')
            if obj.get('Type') != 'OBJECT' or not target.startswith('zgc_r03:'):
                continue
            matrix = np.asarray(obj.get('Matrix', np.eye(4).reshape(-1))).reshape(4, 4)
            if np.allclose(matrix, np.eye(4), rtol=0, atol=1e-7):
                orientations.add(0)
            elif np.allclose(matrix, np.diag([-1., 1., -1., 1.]), rtol=0, atol=1e-7):
                orientations.add(180)
            else:
                raise ValueError('Unexpected custom object transform: ' + name)
            label = labels.get(target, {})
            decoder.mesh(level, target, label.get('source_object', target), matrix, tags=label.get('tags', []))
        if len(orientations) != 1:
            raise ValueError('Custom scene has missing or mixed half-court orientations')
        decoder.game_world_yaw_degrees = orientations.pop()
        if not any(x['category'] == 'ground' for x in decoder.mesh_report):
            raise ValueError('No decoded court surface found')
        baskets = load_scne(archive.read('baskets.SCNE'))['baskets']
        for name, obj in baskets.get('Object', {}).items():
            if obj.get('Type') != 'OBJECT' or obj.get('Target', '').endswith(':rimr'):
                continue  # This is a game-specific reflection pass, not another rim.
            decoder.mesh(baskets, obj['Target'], name, obj.get('Matrix'), native_basket=True)
    if path.stat().st_mtime_ns != source_stat.st_mtime_ns or path.stat().st_size != source_stat.st_size:
        raise RuntimeError('IFF changed while preview was being decoded')
    staged = output / 'current.glb.tmp'; glb.write(staged)
    model_hash = sha_file(staged); model_bytes = staged.stat().st_size
    os.replace(staged, output / 'current.glb')
    source_manifest = ROOT / 'public/manifest.json'
    source = json.loads(source_manifest.read_text(encoding='utf8')) if source_manifest.exists() else {}
    # Include decoder output as well as IFF identity, so repaired labels/material
    # conversion invalidate browser and texture caches without changing the IFF.
    build_id = 'iff-' + source_hash[:12] + '-' + model_hash[:12]
    manifest = {'schema_version': 1, 'kind': 'native_iff', 'build_id': build_id,
                'game_world_yaw_degrees': decoder.game_world_yaw_degrees,
                'model_url': '/game-preview/current.glb', 'preview_version': 'IFF-' + source_hash[:8],
                'source_version': source.get('source_version'), 'iff_version': source.get('iff_version'),
                'game_verified_version': source.get('game_verified_version'),
                'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'iff': {'file': path.name, 'sha256': source_hash, 'bytes': source_stat.st_size, 'mtime_ns': source_stat.st_mtime_ns},
                'asset': {'sha256': model_hash, 'bytes': model_bytes},
                'decoded': {'meshes': len(decoder.mesh_report), 'triangles': sum(x['triangles'] for x in decoder.mesh_report),
                            'textures': len(decoder.textures), 'max_preview_texture_size': args.max_texture},
                'limitations': ['网页使用近似日光和材质，游戏光照、反射与曝光仍以游戏为准。',
                                '篮圈和篮板为包内静止几何；动态球网、球员与碰撞不在网页中模拟。',
                                '原生地板另行加载；本地参考缺少顶点数据，网页无法复现它的红线与两侧线条。透明线贴图能否被外部地板选中仍需游戏确认。']}
    temporary = output / 'manifest.json.tmp'
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(temporary, output / 'manifest.json')
    (ROOT / 'validation/native-preview-current.json').write_text(json.dumps({**manifest, 'meshes': decoder.mesh_report,
             'textures': decoder.texture_report, 'geometry_origin': 'final IFF native buffers only',
             'labels_origin': str(labels_path) if labels else 'geometric categories only'}, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'status': 'ready', 'build_id': build_id, 'decoded': manifest['decoded'], 'bytes': model_bytes}))


if __name__ == '__main__':
    main()
