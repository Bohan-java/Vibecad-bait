"""Read local Blacktop donor and measure native codec round trips."""
from pathlib import Path
import json
import zipfile
import numpy as np
from iff_codec import load_scne, decode_attribute, decode_normals, encode_normals, unit, resolve_binary, make_static_model, hide_native_basket_visuals

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / '洛克公园/arena_blacktop_ext.iff'
REPORT = ROOT / 'zgc-court/validation/iff-codec-probe.json'


def main():
    rows = []
    normals = []
    seen = set()
    roundtrip_total = roundtrip_exact = 0
    normal_roundtrip_max = 0.
    with zipfile.ZipFile(PACKAGE) as archive:
        scene = load_scne(archive.read('level.SCNE'))['level']
        for name, model in scene['Model'].items():
            vf = model.get('VertexFormat', {})
            if vf.get('POSITION0', {}).get('Format') != 'R16G16B16A16_UNORM' or 'TANGENTFRAME0' not in vf:
                continue
            if not {'TEXCOORD0', 'TEXCOORD2', 'TEXCOORD7'} <= vf.keys():
                continue
            key = tuple(s['Binary'] for s in model['VertexStream'])
            if key in seen:
                continue
            seen.add(key)
            try:
                p = decode_attribute(archive, model, 'POSITION0')[:, :3]
                frame = decode_attribute(archive, model, 'TANGENTFRAME0')
                uv = decode_attribute(archive, model, 'TEXCOORD0')
                ib = np.frombuffer(archive.read(resolve_binary(archive, model['IndexBuffer']['Binary'])), '<u2')
            except (KeyError, ValueError):
                continue
            native_n = decode_normals(frame)
            repacked = encode_normals(native_n, frame)
            roundtrip_total += len(frame)
            roundtrip_exact += int(np.count_nonzero(frame == repacked))
            normal_roundtrip_max = max(normal_roundtrip_max, float(np.linalg.norm(decode_normals(repacked) - native_n, axis=1).max()))
            normal_alignment = []
            flat_count = 0
            for prim in model.get('Prim', []):
                ix = ib[prim.get('Start', 0):prim.get('Start', 0) + prim.get('Count', 0)]
                if len(ix) % 3 or not len(ix) or ix.max() >= len(p):
                    continue
                triangles = ix.reshape(-1, 3)
                tris_p = p[triangles]
                area_n = np.cross(tris_p[:, 1] - tris_p[:, 0], tris_p[:, 2] - tris_p[:, 0])
                fn = unit(area_n)
                vn = native_n[triangles]
                # Flat faces make an independent geometric check of the
                # interpretation, excluding unknown authored smoothing.
                flat = (np.min(np.einsum('ijk,ik->ij', vn, vn[:, 0]), axis=1) > .99999) & (np.linalg.norm(area_n, axis=1) > .1)
                alignment = np.einsum('ij,ij->i', fn[flat], vn[flat, 0])
                normal_alignment.extend(alignment.tolist())
                flat_count += len(alignment)
            normals.extend(normal_alignment)
            # Existing affine scales are independently decoded then requantized.
            ps = vf['POSITION0']; st = model['VertexStream'][ps.get('Stream', 0)]
            raw = archive.read(resolve_binary(archive, st['Binary']))
            original_pos = np.ndarray((len(p), 4), '<u2', raw, offset=ps.get('ByteOffset', 0), strides=(st['Stride'], 2))
            fullpos = decode_attribute(archive, model, 'POSITION0')
            rq = np.rint((fullpos - np.array(ps.get('Offset', [0]*4))) / np.array(ps.get('Scale', [1]*4)) * 65535).astype('<u2')
            row = {'model': name, 'vertex_count': len(p), 'positions_byte_exact_roundtrip': bool(np.array_equal(original_pos, rq)),
                   'packed_frame_byte_exact_roundtrip': int(np.count_nonzero(frame == repacked)), 'flat_faces': flat_count,
                   'flat_face_dot_median': float(np.median(normal_alignment)) if normal_alignment else None}
            us = vf['TEXCOORD0']; st = model['VertexStream'][us.get('Stream', 0)]
            raw = archive.read(resolve_binary(archive, st['Binary']))
            uq = np.ndarray((len(p), 2), '<i2', raw, offset=us.get('ByteOffset', 0), strides=(st['Stride'], 2))
            ur = np.rint((uv - np.array(us.get('Offset', [0]*4))[:2]) / np.array(us.get('Scale', [1]*4))[:2] * 32767).astype('<i2')
            row['uv_byte_exact_roundtrip'] = bool(np.array_equal(uq, ur))
            mismatch = uq != ur
            row['uv_negative_one_equivalent_aliases'] = int(np.count_nonzero(mismatch & (uq == -32768) & (ur == -32767)))
            row['uv_non_equivalent_mismatches'] = int(np.count_nonzero(mismatch & ~((uq == -32768) & (ur == -32767))))
            rows.append(row)
            if len(rows) >= 180:
                break
        # New real buffer round trip on nonaxis-aligned, split-normal geometry.
        p = np.array([[0., 0., 0.], [201.25, 19.1, 0.], [12.1, 91.2, 151.3]])
        uv = np.array([[0., 0.], [1., 0.], [.2, 1.]])
        nn = np.repeat(unit(np.cross(p[1] - p[0], p[2] - p[0]))[None, :], 3, axis=0)
        extra = {}
        m, o = make_static_model('zgc:codec_probe', p, nn, uv, [0, 1, 2], 'zgc:probe', extra)
        class MemoryArchive:
            NameToInfo = extra
            def read(self, key): return extra[key]
        mem = MemoryArchive()
        p2 = decode_attribute(mem, m, 'POSITION0')[:, :3]
        uv2 = decode_attribute(mem, m, 'TEXCOORD0')
        nn2 = decode_normals(decode_attribute(mem, m, 'TANGENTFRAME0'))
        build_check = {'position_max_error_cm': float(np.abs(p2-p).max()), 'uv_max_error': float(np.abs(uv2-uv).max()),
                       'normal_max_angle_deg': float(np.degrees(np.arccos(np.clip((nn2*nn).sum(1), -1, 1))).max()),
                       'streams_bytes': [v['Size'] for v in m['VertexStream']], 'new_native_buffers': len(extra)}
        baskets = load_scne(archive.read('baskets.SCNE'))['baskets']
        baskets_patched, basket_report = hide_native_basket_visuals(baskets, archive, extra)
    dots = np.asarray(normals)
    report = {'package': str(PACKAGE), 'models_examined': len(rows), 'vertices_examined': roundtrip_total,
              'packed_frame_exact_roundtrip_vertices': roundtrip_exact,
              'packed_frame_roundtrip_max_normal_delta': normal_roundtrip_max,
              'positions_all_byte_exact': all(r['positions_byte_exact_roundtrip'] for r in rows),
              'uv_all_byte_exact': all(r['uv_byte_exact_roundtrip'] for r in rows),
              'uv_negative_one_equivalent_aliases': sum(r['uv_negative_one_equivalent_aliases'] for r in rows),
              'uv_non_equivalent_mismatches': sum(r['uv_non_equivalent_mismatches'] for r in rows),
              'flat_face_comparison_count': len(dots), 'flat_face_dot_quantiles': np.quantile(dots, [0, .01, .5, .99, 1]).tolist(),
              'flat_face_fraction_dot_above_0_99': float(np.mean(dots > .99)),
              'new_mesh_native_roundtrip': build_check,
              'basket_visual_patch': basket_report,
              'basket_objects_main_transforms_vertex_buffers_and_lod_ranges_unchanged': baskets_patched['Object'] == baskets['Object'],
              'sources': ['https://learn.microsoft.com/en-us/windows/win32/direct3d10/d3d10-graphics-programming-guide-resources-data-conversion',
                          'https://github.com/zeux/meshoptimizer/blob/master/src/vertexfilter.cpp', 'https://jcgt.org/published/0003/02/01/'],
              'source_scope': 'Sources support standard normalized-integer and octahedral math, not undocumented 2K tangent-frame bit semantics. Native low20-bit interpretation is established empirically above.',
              'qualification': 'Low20-bit octahedral normals measured against actual decoded native geometry. Upper12 bits preserved as opaque field for original roundtrip; new neutral-normal-map geometry uses native fixed upper bits. Not an independently decoded full tangent-angle/handedness codec. In-game loading remains unverified.',
              'models': rows}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'models'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
