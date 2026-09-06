#!/usr/bin/env python3
"""Read-only donor/V2 palm audit; never decodes the proprietary tangent frame.

Run with Python + NumPy + Pillow already available on the machine. By default
prints JSON; --output-dir also writes palm_audit.json and palm_audit.md there.
No game files, IFF archives, or legacy build scripts are modified.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

import numpy as np
from PIL import Image

# Imports provide pure functions only; avoid creating __pycache__ in a read-only audit.
sys.dont_write_bytecode = True
from palm_geometry import generate_palm, tangent_samples
from revision_textures import make_dds

ROOT = Path(__file__).resolve().parents[1]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def scene(archive):
    raw = archive.read('level.SCNE').strip()
    return json.loads(raw if raw.startswith(b'{') else b'{' + raw + b'}')['level']


def primitive_ranges(model):
    """SCNE omitted Start continues after the previous primitive's range."""
    cursor = 0
    for index, prim in enumerate(model.get('Prim', [])):
        start = int(prim.get('Start', cursor))
        count = int(prim.get('Count', 0))
        if start < 0 or count < 0:
            raise ValueError('Negative primitive range')
        yield index, start, count, prim
        cursor = start + count


def implicit_starts(level):
    rows = []
    for name, model in level['Model'].items():
        for index, start, count, prim in primitive_ranges(model):
            if 'Start' not in prim and start:
                rows.append({'model': name, 'primitive': index, 'legacy_start': 0,
                             'cumulative_start': start, 'count': count,
                             'position_format': model.get('VertexFormat', {}).get('POSITION0', {}).get('Format')})
    return rows


def decode_positions(model, archive):
    spec = model['VertexFormat']['POSITION0']
    assert spec['Format'] == 'R16G16B16A16_UNORM'
    stream = model['VertexStream'][spec.get('Stream', 0)]
    raw = archive.read(stream['Binary'])
    assert len(raw) == stream['Size'] and len(raw) % stream['Stride'] == 0
    count = len(raw) // stream['Stride']
    packed = np.ndarray((count, 4), '<u2', raw, offset=spec.get('ByteOffset', 0),
                        strides=(stream['Stride'], 2))
    return packed.astype(float) / 65535 * np.array(spec.get('Scale', [1] * 4)) + np.array(spec.get('Offset', [0] * 4))


def opaque_frames(model, archive):
    spec = model['VertexFormat']['TANGENTFRAME0']
    assert spec['Format'] == 'R10G10B10A2_UINT'
    stream = model['VertexStream'][spec.get('Stream', 0)]
    raw = archive.read(stream['Binary'])
    assert len(raw) == stream['Size'] and len(raw) % stream['Stride'] == 0
    return np.ndarray((len(raw) // stream['Stride'],), '<u4', raw,
                      offset=spec.get('ByteOffset', 0), strides=(stream['Stride'],))


def collect_samples(level, archive, cumulative):
    """Match legacy selection/early cutoff, changing only omitted Start handling."""
    normals, frames, model_rows = [], [], []
    members = set(archive.namelist())
    for name, model in level['Model'].items():
        vf = model.get('VertexFormat', {})
        if vf.get('POSITION0', {}).get('Format') != 'R16G16B16A16_UNORM' or 'TANGENTFRAME0' not in vf:
            continue
        streams = model.get('VertexStream', [])
        tangent_stream = vf['TANGENTFRAME0'].get('Stream', 0)
        needed = [streams[0]['Binary'], streams[tangent_stream]['Binary'], model['IndexBuffer']['Binary']]
        if not set(needed) <= members:
            continue
        # This intentionally evaluates the legacy code's verified input subset.
        assert vf['POSITION0'].get('Stream', 0) == 0
        assert vf['POSITION0'].get('ByteOffset', 0) == 0
        assert model['IndexBuffer']['Format'] == 'R16_UINT'
        positions, packed_frames = decode_positions(model, archive), opaque_frames(model, archive)
        assert len(positions) == len(packed_frames)
        indices = np.frombuffer(archive.read(needed[2]), '<u2')
        previous_count = len(normals)
        affected_count = 0
        for _, correct_start, count, prim in primitive_ranges(model):
            old_start = prim.get('Start', 0)
            affected_count += int(old_start != correct_start)
            start = correct_start if cumulative else old_start
            assert start + count <= len(indices) and count % 3 == 0
            section = indices[start:start + count]
            for a, b, c in section.reshape(-1, 3)[::max(1, len(section) // 180)]:
                if max(a, b, c) >= len(positions):
                    continue
                cross = np.cross(positions[b, :3] - positions[a, :3], positions[c, :3] - positions[a, :3])
                length = np.linalg.norm(cross)
                if length < 1e-5:
                    continue
                normals.append(cross / max(length, 1e-10))
                frames.append(int(packed_frames[a]))
        model_rows.append({'model': name, 'samples': len(normals) - previous_count,
                           'primitives_with_different_start': affected_count})
        if len(normals) > 1000:
            break
    assert normals
    return np.asarray(normals), np.asarray(frames, dtype='<u4'), model_rows


def uv_channels(model, archive):
    rows = {}
    for name, spec in model['VertexFormat'].items():
        if not name.startswith('TEXCOORD'):
            continue
        assert spec['Format'] == 'R16G16_SNORM'
        stream = model['VertexStream'][spec.get('Stream', 0)]
        raw = archive.read(stream['Binary'])
        assert len(raw) == stream['Size']
        values = np.ndarray((len(raw) // stream['Stride'], 2), '<i2', raw,
                            offset=spec.get('ByteOffset', 0), strides=(stream['Stride'], 2))
        decoded = np.maximum(values.astype(float) / 32767, -1)
        decoded = decoded * np.array(spec.get('Scale', [1] * 4))[:2] + np.array(spec.get('Offset', [0] * 4))[:2]
        rows[name] = {'raw_min': values.min(0).tolist(), 'raw_max': values.max(0).tolist(),
                      'unique_coordinates': len(np.unique(values, axis=0)),
                      'decoded_min': decoded.min(0).tolist(), 'decoded_max': decoded.max(0).tolist(),
                      'all_raw_zero': bool(np.all(values == 0))}
    return rows


def material_audit(level, archive):
    template = level['Material']['clutchtime_floor_apron:floor_mat']
    rows = []
    for name, material in level['Material'].items():
        if not name.startswith('venice_v2:palm_'):
            continue
        effect = level['Effect'][material['Effect']]
        resources = {}
        for slot, resource in material['Resource'].items():
            texture = level['Texture'][resource['Pixelmap']]
            raw = archive.read(texture['Binary'])
            assert raw[:4] == b'TLD ' and len(raw) == texture['PixelDataSize'] + 32
            assert texture['Format'] in ('BC1_UNORM', 'BC3_UNORM')
            img = Image.open(io.BytesIO(make_dds(raw[32:], texture['Width'], texture['Height'], texture['Format']))).convert('RGBA')
            pixels = np.asarray(img).reshape(-1, 4)
            resources[slot] = {'texture': resource['Pixelmap'], 'binary': texture['Binary'],
                               'sha256': digest(raw), 'format': texture['Format'],
                               'texel_usage': texture.get('TexelUsage'),
                               'decoded_rgba_min': pixels.min(0).tolist(), 'decoded_rgba_max': pixels.max(0).tolist(),
                               'texcoord_declared_by_effect': effect.get('Resource', {}).get(slot, {}).get('Texcoord')}
        rows.append({'material': name, 'effect': material['Effect'],
                     'effect_matches_apron': material['Effect'] == template['Effect'],
                     'script_matches_apron': material['Script'] == template['Script'],
                     'script_embedded': material['Script'] in archive.namelist(),
                     'techniques_match_apron': material['Technique'] == template['Technique'],
                     'normal_height': material['Parameter'].get('NormalHeight'),
                     'alpha_style': material['Parameter'].get('AlphaStyle'), 'resources': resources})
    effect = level['Effect'][template['Effect']]
    inputs = {name: list(tech['Pass']['Default']['VS']['Input'])
              for name, tech in effect['Technique'].items()
              if 'Default' in tech.get('Pass', {}) and 'VS' in tech['Pass']['Default']}
    return {'materials': rows, 'apron_effect_default_pass_vertex_inputs': inputs}


def audit(donor_path, revision_path):
    # A meaningful parser regression: omitted Start after an explicit jump.
    probe = {'Prim': [{'Start': 12, 'Count': 6}, {'Count': 3}, {'Start': 30, 'Count': 9}, {'Count': 6}]}
    assert [(s, c) for _, s, c, _ in primitive_ranges(probe)] == [(12, 6), (18, 3), (30, 9), (39, 6)]
    before = {str(p): digest(p.read_bytes()) for p in (donor_path, revision_path)}
    with zipfile.ZipFile(donor_path) as donor_archive, zipfile.ZipFile(revision_path) as revision_archive:
        donor, revision = scene(donor_archive), scene(revision_archive)
        old_n, old_f, sampled_models = collect_samples(donor, donor_archive, False)
        new_n, new_f, new_models = collect_samples(donor, donor_archive, True)
        actual_n, actual_f = tangent_samples(donor, donor_archive)
        assert np.array_equal(old_n, actual_n) and np.array_equal(old_f, actual_f), 'Audit does not reproduce legacy sampler'
        revision_n, revision_f = tangent_samples(revision, revision_archive)
        sampling = {'sample_count': len(old_n), 'sampled_models': sampled_models,
                    'unique_opaque_frame_values': len(np.unique(old_f)),
                    'cumulative_start_sample_count': len(new_n),
                    'cumulative_start_same_normals': bool(np.array_equal(old_n, new_n)),
                    'cumulative_start_same_frames': bool(np.array_equal(old_f, new_f)),
                    'cumulative_start_same_model_sequence': sampled_models == new_models,
                    'revision2_sampler_matches_donor': bool(np.array_equal(old_n, revision_n) and np.array_equal(old_f, revision_f)),
                    'legacy_sampler_independently_reproduced': True,
                    'donor_nonzero_implicit_starts': implicit_starts(donor)}
        palms = []
        for variant, height in enumerate((1040., 1220., 920.)):
            name = f'venice_v2:palm_model_{variant}'
            model = revision['Model'][name]
            triangles = generate_palm(950 + variant, height)
            generated = np.concatenate([np.asarray(part).reshape(-1, 3) for part in triangles.values()])
            faces = generated.reshape(-1, 3, 3)
            normals = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
            normals /= np.linalg.norm(normals, axis=1)[:, None]
            built = opaque_frames(model, revision_archive)
            assert np.all(built.reshape(-1, 3) == built.reshape(-1, 3)[:, :1])
            built_per_face = built[::3]
            chosen, cosine, built_dot_gaps = [], [], []
            multiple_frame_candidates = 0
            face_cursor = 0
            for batch in np.array_split(normals, 20):
                dots = batch @ old_n.T
                best = np.argmax(dots, axis=1)
                chosen.extend(old_f[best].tolist())
                cosine.extend(dots[np.arange(len(best)), best].tolist())
                for face_index, row in enumerate(dots):
                    matching_frame = old_f == built_per_face[face_cursor + face_index]
                    assert matching_frame.any(), 'V2 contains a frame absent from the donor sample set'
                    best_dot = row.max()
                    built_dot_gaps.append(float(best_dot - row[matching_frame].max()))
                    candidates = np.unique(old_f[np.abs(row - best_dot) <= 1e-12])
                    multiple_frame_candidates += int(len(candidates) > 1)
                face_cursor += len(batch)
            reproduced = np.repeat(np.asarray(chosen, dtype='<u4'), 3)
            indices = np.frombuffer(revision_archive.read(model['IndexBuffer']['Binary']), '<u2')
            assert np.array_equal(indices, np.arange(len(generated), dtype='<u2'))
            error = np.abs(decode_positions(model, revision_archive)[:, :3] - generated)
            assert error.max() <= model['VertexFormat']['POSITION0']['Scale'][0] / 65535 / 2 + 1e-8
            angles = np.degrees(np.arccos(np.clip(cosine, -1, 1)))
            palms.append({'model': name, 'vertices': len(generated), 'triangles': len(faces),
                          'built_frames_match_legacy_generated_selection': bool(np.array_equal(built, reproduced)),
                          'frame_mismatches': int(np.count_nonzero(built != reproduced)),
                          'all_built_frames_near_best_source_normal': bool(max(built_dot_gaps) <= 1e-12),
                          'max_dot_gap_from_best': max(built_dot_gaps),
                          'faces_with_multiple_frame_candidates_near_best': multiple_frame_candidates,
                          'near_best_dot_tolerance': 1e-12,
                          'unique_opaque_frame_values': len(np.unique(built)),
                          'max_position_quantization_error': float(error.max()),
                          'source_face_normal_match_error_degrees': dict(zip(('min', 'median', 'p95', 'max'), np.percentile(angles, [0, 50, 95, 100]).tolist())),
                          'uv': uv_channels(model, revision_archive),
                          'duv_keys': [key for key in model if key.startswith('Duv')]})
        apron_name, apron = next((n, m) for n, m in donor['Model'].items() if 'floor_apron:' in n)
        apron_objects = [(n, o) for n, o in donor['Object'].items() if o.get('Target') == apron_name]
        palm_objects = [(n, o) for n, o in revision['Object'].items() if o.get('Target', '').startswith('venice_v2:palm_model_')]
        report = {'schema_version': 1, 'status': 'DIAGNOSTIC_ONLY_GAME_VISUALS_UNVERIFIED',
                  'inputs': {'donor': {'path': str(donor_path.relative_to(ROOT)), 'sha256': before[str(donor_path)]},
                             'revision2': {'path': str(revision_path.relative_to(ROOT)), 'sha256': before[str(revision_path)]}},
                  'sampling': sampling, 'palms': palms,
                  'apron_template': {'model': apron_name, 'uv': uv_channels(apron, donor_archive),
                                      'duv_keys': [k for k in apron if k.startswith('Duv')],
                                      'object_userdata_present': {n: 'UserData' in o for n, o in apron_objects}},
                  'palm_instances': len(palm_objects),
                  'palm_instances_with_userdata': sum('UserData' in o for _, o in palm_objects),
                  'original_lights_equal': donor['Light'] == revision['Light'],
                  'original_effects_equal': donor['Effect'] == revision['Effect'],
                  'materials': material_audit(revision, revision_archive),
                  'limitations': [
                      'R10G10B10A2_UINT words are treated as opaque values. No decoded normal/tangent is claimed.',
                      'Reported angular errors compare geometric face normals with source face normals, not shader-decoded frames.',
                      'TEXCOORD7 collapse and missing Object.UserData/Duv are measured differences; runtime meaning and causality are unknown.',
                      'Static input analysis cannot establish the active lightmap technique or reproduce GPU/game lighting.',
                      'No current game installation, capture, or in-game visual test was performed.']}
    assert all(digest(p.read_bytes()) == before[str(p)] for p in (donor_path, revision_path))
    report['source_archives_unchanged'] = True
    return report


def markdown(report):
    sample = report['sampling']
    rows = '\n'.join(f"| {p['model']} | {p['triangles']} | {p['frame_mismatches']} | {p['source_face_normal_match_error_degrees']['p95']:.2f}° | {p['source_face_normal_match_error_degrees']['max']:.2f}° |" for p in report['palms'])
    return f'''# Checkpoint 1：黑树的可复现诊断

**状态：只读诊断完成；黑树根因尚未确认，没有生成或宣称已修复的游戏版本。**

## 已证实的事实

1. `palm_geometry.tangent_samples` 的 `prim.get('Start', 0)` 不支持连续省略 Start 的 primitive。donor 实际有 {len(sample['donor_nonzero_implicit_starts'])} 个非零省略段，全部属于 `CourtFloor`，位置格式为 `R32G32B32_FLOAT`。这说明通用解析时必须累积 Start；但该模型被旧切线采样器的 `R16G16B16A16_UNORM` 条件排除。
2. 旧采样器在前 {len(sample['sampled_models'])} 个可读模型取得 {sample['sample_count']} 个样本后停止，实际采到的 primitive 均有显式 Start。只改成累积 Start 后，法线数组、原始 32 位 frame 数组及模型序列完全一致；直接在 V2 上采样也一致。**不能把 V2 黑树归因于这个 Start 问题。**
3. 独立重放原采样逻辑，与原 `tangent_samples` 逐值相等。按原种子和高度重新计算几何及“最近面法线选择原 frame”的步骤，三棵模型的 {sum(p['vertices'] for p in report['palms'])} 个顶点中有 **{sum(p['frame_mismatches'] for p in report['palms'])} 个 frame 不同**。但所有已交付 frame 都属于相同的 donor 样本集合，且相应样本法线与当前最优选择的点积差最大仅 `{max(p['max_dot_gap_from_best'] for p in report['palms']):.3g}`。以 `1e-12` 点积容差计，有 {sum(p['faces_with_multiple_frame_candidates_near_best'] for p in report['palms'])} 个面存在多个不同 frame 的并列候选。这证明最近面法线不足以唯一选出 frame；微小浮点差异可能改变选择。它仍不能证明 frame 对新网格的切线方向、手性或 shader 解码是否正确，也不能据此确认黑树根因。

| 模型 | 三角面 | frame 不一致数 | 源面法线匹配误差 P95 | 最大误差 |
|---|---:|---:|---:|---:|
{rows}

表中的角度只比较新面的几何法线与 donor 样本的几何法线，**没有解码 TANGENTFRAME0**。以最近面法线拷贝一个 frame 并不能验证它与新三角面的 UV 梯度匹配。

frame 逐字差异数可能随 NumPy/浮点计算环境改变，原交付环境与本机的具体差异未确认；可复核的结论是 Start 修正前后样本相同，以及所有已交付 frame 均能匹配一个近乎并列最佳的源面法线。

## 材质和光照输入核查

- 五种树材质继承 apron 的同一个 effect、script 和 Technique；资源可在 V2 内解析，BC1/BC3 实际像素可解码，贴图并非全黑。每个槽的原始 RGBA 极值和哈希见 `palm_audit.json`。设置的 `NormalHeight` 均为 0。
- effect 的 `AlbedoMap` 与 `NormalAndRoughMap` 明确声明 `Texcoord: 2`。树的 TEXCOORD0/1/2 都只有 `(0,0)`、`(1,0)`、`(0,1)` 三个坐标，每个三角形重复使用；当前树颜色为 4×4 色块，仍不能从这一事实推出黑树根因。
- 三棵树的 **TEXCOORD7 全为零**；donor apron 的 TEXCOORD7 有 16 个坐标。effect 的 HiresLightmap/LoresLightmap 顶点输入确实包含 TEXCOORD7 和 TEXCOORD3。但 TEXCOORD7 的运行时语义、当前启用的 technique 和需要如何绑定光照资源均未确认。
- TEXCOORD3 在树与 apron 中均为零，不能将它单独作为异常证据。
- apron 模型包含 Duv0/1/2/7，新增树无 Duv 字段；apron 对象有 UserData，{report['palm_instances']} 棵树实例均无 UserData。没有解码这些字段，也没有把它们直接称为光照索引。
- 原 donor 与 V2 的 Light、Effect 字典完全一致。缺少新增对象的经过验证的光照输入流程，仍需游戏对照确定行为。

## 下一步最小实验

先保留 donor 和失败 V2，输出独立编号测试包。在同一个已确认的游戏槽位、同一机位和同一照明下，加入一个使用已知完整 donor 对象/材质/顶点布局的对照物，与单棵树并排比较。先证实对象与 shader 输入路径，再逐项测试对象元数据、UV7 或经过验证的 tangent frame 处理；每个测试只改变一个因素，记录实际游戏截图。不要同时改树几何、照明和多个材质参数，也不要随机填 UserData 或猜测切线编码。

## 复现

在仓库根目录使用已有 Python 环境（需 NumPy、Pillow）：

```sh
python3 nba2k-arena/scripts/audit_palm_tangents.py --output-dir nba2k-arena/docs/checkpoint1
```

脚本默认只向终端打印 JSON；指定 `--output-dir` 仅写 `palm_audit.json` 与本报告。原 IFF 在诊断前后 SHA-256 一致，没有运行旧构建、没有改游戏目录、没有安装软件。

- donor SHA-256：`{report['inputs']['donor']['sha256']}`
- V2 主 IFF SHA-256：`{report['inputs']['revision2']['sha256']}`
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    report = audit(ROOT / 'donor/original/arena_020_int_original.iff', ROOT / 'output/revision2/arena_700_int.iff')
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / 'palm_audit.json').write_text(serialized, encoding='utf-8')
        (args.output_dir / 'palm_audit.md').write_text(markdown(report), encoding='utf-8')
        print(json.dumps({'status': report['status'], 'samples': report['sampling']['sample_count'],
                          'start_change_affects_current_samples': not report['sampling']['cumulative_start_same_frames'],
                          'palm_frame_mismatches': sum(p['frame_mismatches'] for p in report['palms']),
                          'source_archives_unchanged': report['source_archives_unchanged'],
                          'reports': [str(args.output_dir / name) for name in ('palm_audit.json', 'palm_audit.md')]}, ensure_ascii=False, indent=2))
    else:
        print(serialized, end='')


if __name__ == '__main__':
    main()
