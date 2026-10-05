"""Targeted native 700 floor-overlay inspection and in-memory patch factory.

Reads the already-cached workspace floor package. Does not read the game,
write an IFF, or change the custom scene. The offending draw is in the
separately loaded arena_700_int_floor resource, not the R06 arena main IFF.
The returned replacement map is for that FLOOR archive only.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import struct
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
FLOOR_MODEL = 'arena_700_int_master@GameObjects@CourtFloor_15:floor_700_court_low'
EXTRA_OVERLAY_MATERIALS = frozenset({
    'floor_700_court:line_3_mat',  # red full-court NBA three-point arcs
    'floor_700_court:line_4_mat',  # thin brown short-court center
    'floor_700_court:line_5_mat',  # thin brown left/right short courts
})
EXPECTED_MESHES = frozenset({
    'NBA_line_three_point_lowShape', 'short_court_center_geo_lowShape',
    'short_court_left_geo_lowShape', 'short_court_right_geo_lowShape',
})


class BinaryScene:
    """The locally verified E01FF891 v1 tree: 16-byte header, 40-byte nodes.

    Pointer values are signed offsets from their field, plus one; zero is null.
    The named tree consists of object/array/string/double/integer/null nodes.
    This decoder refuses unknown types and out-of-bounds references.
    """
    def __init__(self, raw):
        self.raw = raw
        magic, version, string_bytes, self.count = struct.unpack_from('<4I', raw)
        if (magic, version) != (0xE01FF891, 1):
            raise ValueError('Unsupported native binary SCNE')
        self.end_nodes = 16 + self.count * 40
        self.string_start = len(raw) - string_bytes
        if not 16 <= self.end_nodes <= self.string_start < len(raw):
            raise ValueError('Invalid native SCNE regions')
        self.offsets = {}
        self.visited = set()
        self.root_name = self.string(16)
        self.document = {self.root_name: self.node(16, (self.root_name,))}
        if len(self.visited) != self.count:
            raise ValueError('Not every native SCNE node was reached')

    def pointer(self, field):
        value = struct.unpack_from('<q', self.raw, field)[0]
        if value == 0:
            return None
        target = field + value - 1
        if not 0 <= target < len(self.raw):
            raise ValueError('Native pointer outside scene')
        return target

    def string(self, field):
        target = self.pointer(field)
        if target is None:
            return None
        if target < self.string_start:
            raise ValueError('String pointer outside string table')
        return self.raw[target:self.raw.index(0, target)].decode('utf8')

    def node(self, offset, path):
        if offset in self.visited or not (16 <= offset < self.end_nodes) or (offset - 16) % 40:
            raise ValueError('Invalid or repeated native tree node')
        self.visited.add(offset)
        self.offsets[path] = offset
        raw_kind = struct.unpack_from('<I', self.raw, offset + 12)[0]
        if raw_kind & ~0xff != 0x40000000:
            raise ValueError('Unverified native node flags')
        kind = raw_kind & 255
        if kind in (1, 2):
            count = struct.unpack_from('<I', self.raw, offset + 20)[0]
            table = self.pointer(offset + 24)
            if count == 0:
                return {} if kind == 1 else []
            if table is None or table < self.end_nodes or table + count * 8 > self.string_start:
                raise ValueError('Invalid native child table')
            children = [self.pointer(table + i * 8) for i in range(count)]
            if kind == 2:
                return [self.node(child, path + (i,)) for i, child in enumerate(children)]
            result = {}
            for child in children:
                name = self.string(child)
                if name in result:
                    raise ValueError('Repeated native object key')
                result[name] = self.node(child, path + (name,))
            return result
        if kind == 0:
            return None
        if kind == 3:
            return self.string(offset + 24)
        if kind == 5:
            return struct.unpack_from('<d', self.raw, offset + 24)[0]
        if kind == 6:
            return struct.unpack_from('<q', self.raw, offset + 24)[0]
        raise ValueError('Unsupported native scalar kind ' + str(kind))


def resolved_primitives(model):
    """Native floor primitives inherit omitted Material/Count; Start advances."""
    material = None
    count = None
    cursor = 0
    for index, primitive in enumerate(model['Prim']):
        material = primitive.get('Material', material)
        count = primitive.get('Count', count)
        if material is None or count is None:
            raise ValueError('No prior Material/Count to inherit')
        start = primitive.get('Start', cursor)
        if count % 3 or start < 0:
            raise ValueError('Invalid native triangle-list range')
        yield index, primitive, material, start, count
        cursor = start + count


def prepare_overlay_patch(floor_archive):
    """Return (replacements, report); mutate nothing on disk.

    Hides only red NBA and thin brown short-court line draws by degenerating
    their indices. Original scene bytes are retained except its exact index
    resource name and CRC scalar; the replacement gets a canonical fresh name.
    Native floor areas, all other line ranges, materials, shaders, Object,
    UserData, FLOOR marker, transform, bounds and vertex descriptors stay intact.
    """
    raw_scene = floor_archive.read('level_floor.SCNE')
    tree = BinaryScene(raw_scene)
    scene = tree.document['level_floor']
    model = scene['Model'][FLOOR_MODEL]
    spec = model['IndexBuffer']
    if spec['Format'] != 'R16_UINT':
        raise ValueError('Unexpected native index format')
    original_ref = spec['Binary']
    original_name = original_ref[:-3] + '.bin' if original_ref.endswith('.gz') else original_ref
    raw = floor_archive.read(original_name)
    if len(raw) != spec['Size'] or zlib.crc32(raw) != model['IndexBufferCrc32']:
        raise ValueError('Native index size/CRC mismatch')
    patched = bytearray(raw)
    selected = []
    untouched = []
    final_end = 0
    for index, prim, material, start, count in resolved_primitives(model):
        if start * 2 + count * 2 > len(raw):
            raise ValueError('Primitive outside index buffer')
        final_end = start + count
        item = {'primitive_index': index, 'mesh': prim.get('Mesh'),
                'material': material, 'start_index': start, 'index_count': count}
        if material in EXTRA_OVERLAY_MATERIALS:
            if prim.get('Mesh') not in EXPECTED_MESHES:
                raise ValueError('Unexpected overlay mesh')
            patched[start * 2:(start + count) * 2] = bytes(count * 2)
            item['ModulateAlbedo'] = scene['Material'][material]['Parameter']['ModulateAlbedo']
            selected.append(item)
        else:
            untouched.append(item)
    if {x['mesh'] for x in selected} != EXPECTED_MESHES or final_end * 2 != len(raw):
        raise ValueError('Native draw layout differs from audited floor')
    for item in untouched:
        a = item['start_index'] * 2
        b = a + item['index_count'] * 2
        if patched[a:b] != raw[a:b]:
            raise AssertionError('Non-target draw bytes changed')
    payload = bytes(patched)
    stem = 'IndexBuffer.' + hashlib.sha256(payload).hexdigest()[:16]
    new_ref = stem + '.gz'
    new_name = stem + '.bin'
    binary_path = ('level_floor', 'Model', FLOOR_MODEL, 'IndexBuffer', 'Binary')
    crc_path = ('level_floor', 'Model', FLOOR_MODEL, 'IndexBufferCrc32')
    ref_at = tree.pointer(tree.offsets[binary_path] + 24)
    if len(new_ref.encode()) != len(original_ref.encode()):
        raise AssertionError('Native string length would change')
    new_scene = bytearray(raw_scene)
    new_scene[ref_at:ref_at + len(original_ref)] = new_ref.encode()
    struct.pack_into('<q', new_scene, tree.offsets[crc_path] + 24, zlib.crc32(payload))
    expected = copy.deepcopy(tree.document)
    expected['level_floor']['Model'][FLOOR_MODEL]['IndexBuffer']['Binary'] = new_ref
    expected['level_floor']['Model'][FLOOR_MODEL]['IndexBufferCrc32'] = zlib.crc32(payload)
    if BinaryScene(bytes(new_scene)).document != expected:
        raise AssertionError('Native scene changed beyond index name and CRC')
    report = {
        'mode': 'DRY_RUN_ONLY_NO_IFF_WRITTEN',
        'owning_resource': 'arena_700_int_floor.iff (separate floor archive)',
        'not_present_in_main_R06_floor_scene': True,
        'model': FLOOR_MODEL, 'original_index_resource': original_name,
        'replacement_index_resource': new_name,
        'original_index_sha256': hashlib.sha256(raw).hexdigest(),
        'replacement_index_sha256': hashlib.sha256(payload).hexdigest(),
        'original_scene_sha256': hashlib.sha256(raw_scene).hexdigest(),
        'scene_node_count': tree.count,
        'selected_draws': selected, 'untouched_draws': untouched,
        'indices_total': len(raw) // 2,
        'indices_degenerated': sum(x['index_count'] for x in selected),
        'source_scene_min_max_cm': {'min': model['Min'], 'max': model['Max']},
        'native_scene_changes_only': ['IndexBuffer.Binary', 'IndexBufferCrc32'],
        'non_target_draw_bytes_identical': True,
        'functional_markers_objects_materials_vertices_unchanged': True,
        'custom_color_floor_untouched': True,
        'game_tested': False,
        'limitations': [
            'Cross-archive index override by putting these bytes in the main IFF is not established.',
            'Direct application requires targeting the separately loaded 700 floor resource.',
            'White native lines are intentionally retained; this factory targets only the reported red and brown overlays.',
        ],
    }
    return {'level_floor.SCNE': bytes(new_scene), new_name: payload}, report


def export_floor_reference(floor_archive, main_archive=None):
    """Return genuine cached floor descriptors for audit/preview, no file writes.

    The workspace's cached floor contains indices but references an external
    vertex payload absent from this cache. Do not reconstruct schematic arcs and
    describe them as extracted native triangles. Exact material/bounds data is
    useful even when complete geometry cannot be exported.
    """
    raw = floor_archive.read('level_floor.SCNE')
    tree = BinaryScene(raw)
    level = tree.document['level_floor']
    model = level['Model'][FLOOR_MODEL]
    vb = model.get('VertexBuffer', model.get('VertexStream'))
    streams = vb if isinstance(vb, list) else [vb]
    stream_info = []
    for stream in streams:
        name = stream['Binary']
        alias = name[:-3] + '.bin' if name.endswith('.gz') else name
        available = name if name in floor_archive.NameToInfo else alias if alias in floor_archive.NameToInfo else None
        stream_info.append({'descriptor': stream, 'available_entry': available})
    ib_name = model['IndexBuffer']['Binary']
    ib_name = ib_name[:-3] + '.bin' if ib_name.endswith('.gz') else ib_name
    ib = floor_archive.read(ib_name)
    materials = {key: value for key, value in level['Material'].items()
                 if key.startswith('floor_700_court:line_')}
    effects = {material['Effect']: level['Effect'][material['Effect']]
               for material in materials.values()}
    draw_records = []
    for index, prim, material_name, start, count in resolved_primitives(model):
        material = level['Material'][material_name]
        draw_records.append({'primitive_index': index, 'mesh': prim.get('Mesh'),
                             'material': material_name, 'start': start, 'count': count,
                             'bounds_cm': {key: prim.get(key) for key in ('Min', 'Max')},
                             'line_color': material.get('Parameter', {}).get('ModulateAlbedo'),
                             'reported_extra_overlay': material_name in EXTRA_OVERLAY_MATERIALS})
    result = {
        'schema': 'native-floor-reference-v1',
        'scope': 'Exact decoded cached native 700 floor, with explicit unavailable vertex payload',
        'scene_sha256': hashlib.sha256(raw).hexdigest(), 'scene_nodes': tree.count,
        'Model': {FLOOR_MODEL: model}, 'Object': level['Object'],
        'Material': materials, 'Effect': effects, 'Texture': level['Texture'],
        'draws': draw_records,
        'index_resource': ib_name, 'index_sha256': hashlib.sha256(ib).hexdigest(),
        'indices_uint16': list(struct.unpack('<' + str(len(ib) // 2) + 'H', ib)),
        'vertex_streams': stream_info,
        'native_triangle_preview_available': all(x['available_entry'] for x in stream_info),
        'geometry_limit': 'VertexBuffer.331bebe4f6988a02 is referenced but absent in the allowed workspace cache; native triangles cannot be truthfully rendered from indices alone.',
        'native_maximum_geometric_y_cm': model['Max'][1],
        'line_depth_policy': {'DEPTHBIAS': -4.0, 'SLOPESCALEDEPTHBIAS': -4.0, 'ZWRITEENABLE': 0},
        'single_main_iff_constraint': 'Cached floor stays untouched. Cross-package overrides are not established. Main court camera-depth policy is a separate untested candidate.',
        'millimeter_raise_not_proven': True,
        'depth_bias_reference': 'https://learn.microsoft.com/en-us/windows/win32/direct3d11/d3d10-graphics-programming-guide-output-merger-stage-depth-bias',
        'illustrative_bias_scale_only': [],
    }
    # Conditional perspective-camera examples, not measured NBA cameras. For a
    # plane seen at its look-at point, the world-height equivalent of S slope
    # units is approximately |S| * horizontal_distance / vertical_focal_pixels.
    # Show why a universal 0.2-0.5 cm lift cannot be deduced from near-zero bounds.
    for distance_cm, vfov_deg, screen_h in [(1000, 45, 2160), (3000, 45, 1080), (4000, 60, 1080)]:
        fy = screen_h / (2 * math.tan(math.radians(vfov_deg) / 2))
        result['illustrative_bias_scale_only'].append({
            'assumption': 'Direct D3D slope-bias interpretation, perspective, horizontal floor, center view; not captured game state',
            'horizontal_distance_cm': distance_cm, 'vertical_fov_deg': vfov_deg,
            'screen_height_pixels': screen_h,
            'four_slope_units_approx_world_height_cm': 4 * distance_cm / fy,
        })
    if main_archive is not None:
        from iff_codec import load_scne, decode_attribute
        from ground_depth_policy import _discover
        main = load_scne(main_archive.read('level.SCNE'))['level']
        name, mat, reason = _discover(main, None)
        court = main['Model'][name]
        positions = decode_attribute(main_archive, court, 'POSITION0')[:, :3]
        court_ib = main_archive.read(court['IndexBuffer']['Binary'])
        result['current_custom_court'] = {
            'model': name, 'material': mat, 'selection': reason,
            'positions_cm': positions.tolist(),
            'indices_uint16': list(struct.unpack('<' + str(len(court_ib) // 2) + 'H', court_ib)),
            'min_decoded_cm': positions.min(axis=0).tolist(),
            'max_decoded_cm': positions.max(axis=0).tolist(),
            'Material': main['Material'][mat],
            'Effect': main['Effect'][main['Material'][mat]['Effect']],
        }
        result['main_floor_scenes'] = {
            name: load_scne(main_archive.read(name))
            for name in ('level_floor.SCNE', 'level_floor_lightmaps.SCNE')
        }
    return result


if __name__ == '__main__':
    path = ROOT.parent / 'build/local_game_reference/levels/arena_700_int_floor.iff'
    with zipfile.ZipFile(path) as archive, zipfile.ZipFile(ROOT / 'output/arena_700_int.iff') as main:
        report = export_floor_reference(archive, main)
    report['cached_source'] = str(path)
    report['cached_source_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    destination = ROOT / 'validation/native-floor-reference.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'report': str(destination), 'native_triangle_preview_available': report['native_triangle_preview_available'],
                     'native_maximum_geometric_y_cm': report['native_maximum_geometric_y_cm'],
                     'line_depth_policy': report['line_depth_policy']}))
