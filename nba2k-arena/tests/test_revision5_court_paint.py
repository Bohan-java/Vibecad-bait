"""Small analytic native-record/material checks; never runs whole-court clipping."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest
import zipfile

import numpy as np

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from revision5_court_paint import (BASE_MATERIAL, DEPTH_PATHS, pack_vertices,
                                   paint_material, triangle_areas)


def changed_paths(before, after, path=()):
    if isinstance(before, dict) and isinstance(after, dict):
        result = set()
        for key in before.keys() | after.keys():
            if key not in before or key not in after:
                result.add(path + (key,))
            else:
                result.update(changed_paths(before[key], after[key], path + (key,)))
        return result
    return {path} if before != after else set()


class PaintRecordTests(unittest.TestCase):
    def setUp(self):
        # Exact analytic plane y = 2 + x/2 - z/4, with one upward native face.
        self.positions = np.array([[0., 2., 0.], [8., 6., 0.], [0., 0., 8.]])
        self.indices = np.array([0, 2, 1], dtype='<u2')
        self.format = {
            'POSITION0': {'Format': 'R32G32B32_FLOAT'},
            'TEXCOORD0': {'Format': 'R16G16_SNORM', 'ByteOffset': 12,
                          'Scale': [2., 5., 1., 1.], 'Offset': [.4, -2., 0., 0.]},
            'TEXCOORD1': {'Format': 'R16G16_SNORM', 'ByteOffset': 16,
                          'Scale': [.5, .25], 'Offset': [.5, .75]},
            'TEXCOORD2': {'Format': 'R16G16_SNORM', 'ByteOffset': 20,
                          'Scale': [20., -8.], 'Offset': [10., .5]},
            'TEXCOORD3': {'Format': 'R16G16_SNORM', 'ByteOffset': 24},
        }
        self.encoded = {
            'TEXCOORD0': np.array([[-32768, 32767], [0, 16384], [32767, -32768]], dtype='<i2'),
            'TEXCOORD1': np.array([[1200, -1400], [20000, 4096], [-20000, 12288]], dtype='<i2'),
            'TEXCOORD2': np.array([[0, 0], [32000, -16000], [-16000, 32000]], dtype='<i2'),
            'TEXCOORD3': np.array([[12345, 0], [12345, 32767], [12345, -32768]], dtype='<i2'),
        }
        self.source = bytearray(3 * 28)
        np.ndarray((3, 3), '<f4', self.source, strides=(28, 4))[:] = self.positions
        for name, encoded in self.encoded.items():
            np.ndarray((3, 2), '<i2', self.source,
                       offset=self.format[name]['ByteOffset'], strides=(28, 2))[:] = encoded

    def decode_uv(self, raw, name):
        spec = self.format[name]
        encoded = np.ndarray((len(raw)//28, 2), '<i2', raw,
                             offset=spec['ByteOffset'], strides=(28, 2))
        return (np.maximum(encoded.astype(float) / 32767, -1)
                * np.asarray(spec.get('Scale', [1, 1]))[:2]
                + np.asarray(spec.get('Offset', [0, 0]))[:2])

    def test_exact_native_record_layout_affine_height_and_all_four_uv_sets(self):
        points = np.array([[1.123456789, 2.234567891], [4., 1.], [0., 0.], [0., 8.]])
        source_before = bytes(self.source)
        position_before, format_before = self.positions.copy(), copy.deepcopy(self.format)
        packed, errors = pack_vertices(points, self.positions, self.indices,
                                        self.source, self.format)
        self.assertEqual(len(packed), len(points)*28)
        final = points.astype('<f4').astype(float)
        xyz = np.ndarray((len(points), 3), '<f4', packed, strides=(28, 4))
        np.testing.assert_array_equal(xyz[:, [0, 2]], final)
        np.testing.assert_array_equal(xyz[:, 1], (2 + final[:, 0]/2 - final[:, 1]/4).astype('<f4'))
        # Independent analytic barycentric coordinates for the chosen 8x8 face.
        weights = np.column_stack((1 - final[:, 0]/8 - final[:, 1]/8,
                                   final[:, 0]/8, final[:, 1]/8))
        self.assertEqual(set(errors), set(self.encoded))
        for name in self.encoded:
            with self.subTest(uv=name):
                expected = weights @ self.decode_uv(source_before, name)
                actual = self.decode_uv(packed, name)
                bound = np.abs(np.asarray(self.format[name].get('Scale', [1, 1]))[:2]) / 65534
                self.assertTrue(np.all(np.abs(actual-expected) <= bound + 1e-14))
                self.assertAlmostEqual(errors[name], float(np.abs(actual-expected).max()), places=13)
        self.assertEqual(bytes(self.source), source_before)
        np.testing.assert_array_equal(self.positions, position_before)
        self.assertEqual(self.format, format_before)

    def test_uv_interpolation_uses_final_float32_position_before_rounding(self):
        # This point deliberately crosses an SNORM rounding half-step when X
        # becomes float32: interpolating the original float64 X produces 1001.
        encoded = np.array([[0, 0], [32767, 0], [0, 32767]], dtype='<i2')
        np.ndarray((3, 2), '<i2', self.source, offset=12, strides=(28, 2))[:] = encoded
        point = np.array([[0.24451429548020875, .5]])
        self.assertEqual(int(np.rint(point[0, 0]/8*32767)), 1001)
        packed, _ = pack_vertices(point, self.positions, self.indices,
                                  self.source, self.format)
        result = np.ndarray((1, 2), '<i2', packed, offset=12, strides=(28, 2))
        self.assertEqual(int(result[0, 0]), 1002)

    def test_source_snorm_minus_32768_decodes_as_minus_one(self):
        packed, _ = pack_vertices(self.positions[:, [0, 2]], self.positions,
                                  self.indices, self.source, self.format)
        for name in self.encoded:
            with self.subTest(uv=name):
                np.testing.assert_allclose(self.decode_uv(packed, name),
                                           self.decode_uv(self.source, name), rtol=0, atol=2e-14)
        # Complete identical 28-byte records are stable for repeated points.
        twice, _ = pack_vertices([[1., 2.], [1., 2.]], self.positions,
                                  self.indices, self.source, self.format)
        self.assertEqual(twice[:28], twice[28:])

    def test_outside_surface_and_invalid_native_scale_fail_without_mutation(self):
        original = bytes(self.source)
        with self.assertRaisesRegex(ValueError, 'outside donor base surface'):
            pack_vertices([[8., 8.]], self.positions, self.indices, self.source, self.format)
        invalid_format = copy.deepcopy(self.format)
        invalid_format['TEXCOORD1']['Scale'][0] = 0
        with np.errstate(divide='ignore', invalid='ignore'):
            with self.assertRaisesRegex(ValueError, 'SNORM bounds'):
                pack_vertices([[1., 2.]], self.positions, self.indices, self.source, invalid_format)
        self.assertEqual(bytes(self.source), original)

    def test_positive_xz_area_reversal_has_upward_xyz_winding(self):
        ccw = np.array([[[0., 0.], [4., 0.], [1., 3.]],
                        [[-2., -3.], [2., 1.], [-1., 4.]]])
        np.testing.assert_array_equal(triangle_areas(ccw), [6., 12.])
        points = ccw[:, ::-1]
        xyz = np.zeros((2, 3, 3)); xyz[:, :, [0, 2]] = points
        cross = np.cross(xyz[:, 1]-xyz[:, 0], xyz[:, 2]-xyz[:, 0])
        np.testing.assert_array_equal(cross[:, 1], [12., 24.])


class PaintMaterialTests(unittest.TestCase):
    def test_real_donor_material_changes_only_albedo_and_existing_depth_paths(self):
        with zipfile.ZipFile(ROOT/'donor/original/arena_020_int_original.iff') as archive:
            level = json.loads(b'{' + archive.read('level.SCNE').strip() + b'}')['level']
        base = copy.deepcopy(level['Material'][BASE_MATERIAL])
        expected_paths = {
            'Default': ('Default', 'ProjectTexture', 'StoryScene', 'StorySceneHard', 'GBuffer', 'DepthNormalPrepass'),
            'Prepass': ('Default', 'DepthNormalPrepass'),
            'Mirror': ('UseHardShadowMaps',),
            'Movie': ('Default',),
        }
        self.assertEqual(DEPTH_PATHS, expected_paths)
        self.assertEqual(sum(map(len, expected_paths.values())), 10)
        allowed = {('Resource', 'DetailAlbedoTexture', 'Pixelmap')}
        for technique, passes in DEPTH_PATHS.items():
            for name in passes:
                state = base['Technique'][technique]['Pass'][name]
                for field in ('DEPTHBIAS', 'SLOPESCALEDEPTHBIAS'):
                    # Exercise explicit replacement, including pre-existing values.
                    state[field] = 37
                    allowed.add(('Technique', technique, 'Pass', name, field))
        self.assertEqual(len(allowed), 21)  # 20 depth keys and one albedo reference.
        before = copy.deepcopy(base)
        result = paint_material(base, 'test:paint_albedo')
        self.assertEqual(changed_paths(before, result), allowed)
        self.assertEqual(base, before)
        self.assertEqual(result['Effect'], before['Effect'])
        self.assertEqual(result['Script'], before['Script'])
        self.assertEqual(result['Parameter'], before['Parameter'])
        self.assertEqual(result['Resource']['DetailAlbedoTexture']['Pixelmap'], 'test:paint_albedo')
        for technique, passes in DEPTH_PATHS.items():
            for name in passes:
                for field, expected in (('DEPTHBIAS', -4), ('SLOPESCALEDEPTHBIAS', 0)):
                    self.assertEqual(result['Technique'][technique]['Pass'][name][field], expected)
        result['Parameter']['test_mutation'] = 1
        self.assertNotIn('test_mutation', base['Parameter'])


if __name__ == '__main__':
    unittest.main()
