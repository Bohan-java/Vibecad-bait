"""Codec tests against donor data, UV gradients and the preserved shader path."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
import zipfile

import numpy as np

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from palm_geometry import tangent_samples
from revision3_mesh import (DEFAULT_VS, TEMPLATE_EFFECT, TEMPLATE_MATERIAL,
                            UNBAKED_EFFECT, decode_tangent_frames,
                            encode_tangent_frames, export_mesh, make_unbaked_material)


def unit(vectors):
    return vectors / np.linalg.norm(vectors, axis=-1, keepdims=True)


def angles(a, b):
    return np.degrees(np.arccos(np.clip((a * b).sum(-1), -1, 1)))


class Revision3MeshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = zipfile.ZipFile(ROOT / 'donor/original/arena_020_int_original.iff')
        cls.donor = json.loads(b'{' + cls.archive.read('level.SCNE').strip() + b'}')['level']

    @classmethod
    def tearDownClass(cls):
        cls.archive.close()

    def setUp(self):
        self.level = copy.deepcopy(self.donor)

    def test_codec_matches_actual_donor_geometry(self):
        # Independent geometric evidence, not an encode/decode-only roundtrip.
        self.assertEqual(hashlib.sha256(self.archive.read(DEFAULT_VS)).hexdigest(),
                         '66364e949eb1f86e2052a1bac70e31f8c268f2cd5be99d5a403c0dd21cd93bc8')
        face_normals, packed = tangent_samples(self.donor, self.archive)
        decoded, tangents, handedness = decode_tangent_frames(packed)
        errors = angles(face_normals, decoded)
        self.assertLess(float(np.median(errors)), .1)
        self.assertTrue(np.all(errors < 60))  # curved donor surfaces have smooth vertex normals
        self.assertLess(float(np.max(np.abs((decoded * tangents).sum(-1)))), 1e-12)
        self.assertEqual(len(packed), 1042)
        self.assertTrue(np.all(np.isin(handedness, [-1, 1])))

    def test_donor_apron_known_frame(self):
        # Original apron: horizontal +Y surface, tangent roughly -Z.
        model = next(m for n, m in self.donor['Model'].items() if 'floor_apron:' in n)
        stream = model['VertexStream'][2]
        data = self.archive.read(stream['Binary'])
        frames = np.ndarray((16,), '<u4', data, strides=(stream['Stride'],))
        self.assertEqual(np.unique(frames).tolist(), [1609563647])
        normals, tangents, hand = decode_tangent_frames(frames)
        self.assertLess(float(angles(normals, np.tile([0, 1, 0], (16, 1))).max()), .06)
        self.assertLess(float(angles(tangents, np.tile([0, 0, -1], (16, 1))).max()), .24)
        self.assertTrue(np.all(hand == 1))

    def test_codec_random_frames_and_poles(self):
        rng = np.random.default_rng(932)
        normals = unit(rng.normal(size=(20000, 3)))
        tangents = unit(np.cross(normals, rng.normal(size=(20000, 3))))
        normals = np.concatenate((normals, np.eye(3), -np.eye(3)))
        tangents = np.concatenate((tangents, np.roll(np.eye(3), 1, axis=1), np.roll(np.eye(3), 1, axis=1)))
        hand = rng.choice([-1, 1], len(normals))
        frames = encode_tangent_frames(normals, tangents, hand)
        decoded_n, decoded_t, decoded_h = decode_tangent_frames(frames)
        self.assertLess(float(angles(normals, decoded_n).max()), .25)
        self.assertLess(float(angles(tangents, decoded_t).max()), .35)
        np.testing.assert_array_equal(decoded_h, hand)
        self.assertLess(float(np.abs((decoded_n * decoded_t).sum(-1)).max()), 1e-12)

    def prepare_material(self):
        # The exporter needs registered texture references; it never reads/writes textures.
        self.level['Texture']['test:albedo'] = {'Binary': 'test_albedo.tld'}
        self.level['Texture']['test:normal'] = {'Binary': 'test_normal.tld'}
        return make_unbaked_material(self.level, 'test:material', 'test:albedo', 'test:normal')

    def test_unbaked_technique_preserves_complete_binding(self):
        original_effect = copy.deepcopy(self.level['Effect'][TEMPLATE_EFFECT])
        original_material = copy.deepcopy(self.level['Material'][TEMPLATE_MATERIAL])
        report = self.prepare_material()
        new_effect = self.level['Effect'][UNBAKED_EFFECT]
        self.assertEqual(list(new_effect['Technique']), ['Default'])
        for name, original_pass in original_effect['Technique']['Default']['Pass'].items():
            self.assertEqual(new_effect['Technique']['Default']['Pass'][name], original_pass)
        self.assertEqual(new_effect['Technique']['Default']['Pass']['OnlyDepthCSM'],
                         original_effect['Technique']['HiresLightmap']['Pass']['OnlyDepthCSM'])
        for name in ('Parameter', 'Resource', 'VertexFormat'):
            self.assertEqual(new_effect[name], original_effect[name])
        self.assertEqual(self.level['Effect'][TEMPLATE_EFFECT], original_effect)
        self.assertEqual(self.level['Material'][TEMPLATE_MATERIAL], original_material)
        new_material = self.level['Material']['test:material']
        self.assertEqual(new_material['Technique']['Default']['Pass']['OnlyDepthCSM'],
                         original_material['Technique']['HiresLightmap']['Pass']['OnlyDepthCSM'])
        self.assertEqual(new_material['Script'], original_material['Script'])
        self.assertIn(new_material['Script'], self.archive.namelist())
        self.assertFalse(report['runtime_render_dispatch_verified'])
        for render_pass in new_effect['Technique']['Default']['Pass'].values():
            self.assertNotIn('TEXCOORD7', render_pass.get('VS', {}).get('Input', {}))
            for stage in ('VS', 'PS'):
                if stage in render_pass:
                    self.assertIn(render_pass[stage]['Binary'], self.archive.namelist())
            self.assertIn('ResourceMapping', render_pass)

    def test_export_preserves_uv_gradient_on_both_faces(self):
        self.prepare_material()
        front = np.array([[0, 0, 0], [4, 0, 0], [0, 2, 0]], dtype=float)
        faces = np.array([front, front[[0, 2, 1]]])
        uv = np.array([[[0, 0], [1, 0], [0, 1]], [[0, 0], [0, 1], [1, 0]]], dtype=float)
        extra = {}
        report = export_mesh(self.level, extra, 'test:mesh', {'test:material': faces},
                             uv_parts={'test:material': uv})
        model = self.level['Model']['test:mesh']
        # TEXCOORD0 is the separate SNORM UV stream. The packed uint frame is
        # TANGENTFRAME0 at stream 2/offset 0 and must retain donor metadata.
        template = next(m for n, m in self.donor['Model'].items() if 'floor_apron:' in n)
        self.assertEqual(model['VertexFormat']['TANGENTFRAME0'], template['VertexFormat']['TANGENTFRAME0'])
        self.assertEqual(model['VertexFormat']['TANGENTFRAME0'],
                         {'Format': 'R10G10B10A2_UINT', 'Stream': 2})
        self.assertEqual(model['VertexFormat']['TEXCOORD0']['Format'], 'R16G16_SNORM')
        self.assertEqual(model['VertexFormat']['TEXCOORD0']['Stream'], 1)
        self.assertEqual(report['vertices'], 6)
        self.assertEqual(report['handedness_mismatches'], 0)
        self.assertLess(report['max_normal_error_degrees'], .25)
        self.assertLess(report['max_tangent_error_degrees'], .35)
        self.assertEqual(report['donor_frame_samples_used'], 0)
        for stream in model['VertexStream']:
            self.assertEqual(stream['Size'], len(extra[stream['Binary']]))
        attributes = extra[model['VertexStream'][2]['Binary']]
        frames = np.ndarray((6,), '<u4', attributes, strides=(20,))
        normals, tangents, hand = decode_tangent_frames(frames)
        expected_n = np.array([[0, 0, 1]] * 3 + [[0, 0, -1]] * 3)
        self.assertLess(float(angles(normals, expected_n).max()), .25)
        self.assertLess(float(angles(tangents, np.tile([1, 0, 0], (6, 1))).max()), .35)
        np.testing.assert_array_equal(hand, [1, 1, 1, -1, -1, -1])
        packed_uv2 = np.ndarray((6, 2), '<i2', attributes, offset=8, strides=(20, 2))
        spec = model['VertexFormat']['TEXCOORD2']
        actual_uv = packed_uv2.astype(float) / 32767 * spec['Scale'][:2] + spec['Offset'][:2]
        np.testing.assert_allclose(actual_uv, uv.reshape(-1, 2), atol=1e-5)
        uv0_spec = model['VertexFormat']['TEXCOORD0']
        packed_uv0 = np.frombuffer(extra[model['VertexStream'][1]['Binary']], '<i2').reshape(-1, 2)
        actual_uv0 = packed_uv0.astype(float) / 32767 * uv0_spec['Scale'][:2] + uv0_spec['Offset'][:2]
        np.testing.assert_allclose(actual_uv0, uv.reshape(-1, 2), atol=1e-5)
        # Changing UV scale/offset alone must not change the packed N/T frame.
        export_mesh(self.level, extra, 'test:mesh_reparameterized', {'test:material': faces},
                    uv_parts={'test:material': uv * 7 + [4, -5]})
        second = self.level['Model']['test:mesh_reparameterized']
        second_attributes = extra[second['VertexStream'][2]['Binary']]
        second_frames = np.ndarray((6,), '<u4', second_attributes, strides=(20,))
        np.testing.assert_array_equal(second_frames, frames)
        self.assertNotEqual(second['VertexFormat']['TEXCOORD0']['Offset'], uv0_spec['Offset'])
        ib = np.frombuffer(extra[model['IndexBuffer']['Binary']], '<u2')
        np.testing.assert_array_equal(ib, np.arange(6))

    def test_rejects_degenerate_uv_and_index_overflow(self):
        self.prepare_material()
        triangle = np.array([[[0., 0, 0], [1, 0, 0], [0, 1, 0]]])
        extra = {}
        with self.assertRaisesRegex(ValueError, 'Degenerate UV'):
            export_mesh(self.level, extra, 'bad_uv', {'test:material': triangle},
                        uv_parts={'test:material': np.zeros((1, 3, 2))})
        with self.assertRaisesRegex(ValueError, '65,535'):
            export_mesh(self.level, extra, 'too_many', {'test:material': np.repeat(triangle, 21846, axis=0)})
        self.assertEqual(extra, {})
        self.assertNotIn('bad_uv', self.level['Model'])
        self.assertNotIn('too_many', self.level['Model'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
