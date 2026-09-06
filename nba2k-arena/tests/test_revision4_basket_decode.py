"""Native basket readback and verified shader skin-layout regression checks."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import unittest
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import revision4_basket_decode as basket
from revision3_preview import Reader


class SkinDecoderTests(unittest.TestCase):
    def test_rigid_and_two_influence_palette_math(self):
        table = struct.pack('<II', 0x00017fff, 0x00028000)
        skin = basket.decode_weights(np.array([0x300, 0x1], dtype=np.uint32), table, palette_size=4)
        self.assertEqual(skin['offsets'].tolist(), [0, 1, 3])
        self.assertEqual(skin['palette_indices'].tolist(), [3, 1, 2])
        matrices = np.tile(np.eye(4)[:3], (4, 1, 1))
        matrices[1, 0, 3] = 10
        matrices[2, 1, 3] = 20
        matrices[3, 2, 3] = 30
        actual = basket.apply_skin_palette(np.array([[1, 2, 3], [4, 5, 6]]), skin, matrices)
        expected = [[1, 2, 33], [4 + 10 * 32767 / 65535, 5 + 20 * 32768 / 65535, 6]]
        np.testing.assert_allclose(actual, expected)

    def test_four_influences_use_address_in_uint32_entries(self):
        table = struct.pack('<6I', 0, 0, 0x00003fff, 0x00014000, 0x00024000, 0x00034000)
        skin = basket.decode_weights(np.array([0x203]), table)
        self.assertEqual(skin['palette_indices'].tolist(), [0, 1, 2, 3])
        self.assertAlmostEqual(float(skin['weights'].sum()), 1)

    def test_bad_weights_ranges_and_odd_padding_fail_closed(self):
        bad = [
            (np.array([1]), b'\0' * 4, 'exceeds'),
            (np.array([1]), b'\0' * 8, 'sum'),
            (np.array([2]), struct.pack('<4I', 65535, 0, 0, 1), 'padding'),
            (np.array([-1]), b'', 'uint32'),
            (np.array([0]), b'123', 'uint32'),
        ]
        for words, table, message in bad:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                basket.decode_weights(words, table)
        with self.assertRaisesRegex(ValueError, 'palette'):
            basket.decode_weights(np.array([0x300]), b'', palette_size=3)

    def test_hierarchy_parent_order_cycle_and_unsupported_fields(self):
        model = {'Transform': {'child': {'Parent': 1, 'Translate': [1, 0, 0]},
                               'root': {'Translate': [0, 2, 0]}}}
        result = basket.hierarchy_bind_transforms(model)
        self.assertEqual(result[0]['translation_cm'], [1, 2, 0])
        model['Transform']['root']['Parent'] = 0
        with self.assertRaisesRegex(ValueError, 'Cycle'):
            basket.hierarchy_bind_transforms(model)
        with self.assertRaisesRegex(ValueError, 'Unverified'):
            basket.hierarchy_bind_transforms({'Transform': {'root': {'Rotate': [0, 0, 0]}}})


class NativeBasketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / 'donor/original/arena_020_int_original.iff'
        cls.hash_before = hashlib.sha256(cls.path.read_bytes()).hexdigest()
        cls.archive = zipfile.ZipFile(cls.path)
        cls.scene = basket.fragment(cls.archive.read('baskets.SCNE'))['baskets']
        cls.source_copy = copy.deepcopy(cls.scene)
        # Fixture availability must remain deterministic after a user later
        # supplies the missing game resources to the normal runtime cache.
        fixture_reader = Reader(cls.archive)
        fixture_reader.cache = {}
        cls.report = basket.audit_baskets(cls.archive, fixture_reader, include_geometry=True)

    @classmethod
    def tearDownClass(cls):
        cls.archive.close()

    def test_original_archive_and_scene_unchanged(self):
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.hash_before)
        self.assertEqual(self.scene, self.source_copy)
        json.dumps(self.report)

    def test_exact_four_missing_main_buffers_and_no_fabrication(self):
        expected = {'IndexBuffer.2faa94a692eecb55.gz': 1340664,
                    'VertexBuffer.396eff6e2f806326.gz': 363992,
                    'VertexBuffer.c7008f082a4e24dd.gz': 181996,
                    'VertexBuffer.8d2e607c050161de.gz': 1091976}
        actual = {r['binary']: r['expected_uncompressed_bytes'] for r in self.report['missing_geometry_resources']}
        self.assertEqual(actual, expected)
        main = self.report['models'][basket.PREFIX + 'basket']
        self.assertFalse(main['decoded'])
        self.assertNotIn('geometry', main)

    def test_glass_bind_geometry_real_indices_and_rigid_weights(self):
        result = self.report['models'][basket.PREFIX + 'glass']
        self.assertTrue(result['decoded'])
        self.assertEqual(result['vertices'], 48)
        self.assertEqual(result['top_lod_triangles'], 38)
        self.assertEqual(result['skin_summary']['weight_words'], [0, 256])
        self.assertEqual(result['skin_summary']['palette_indices'], [0, 1])
        self.assertLess(max(p['max_authoring_bounds_error_cm'] for p in result['bound_checks']), .008)
        # Incorrectly adding the rimpivot's authoring translation would move
        # this original glass hundreds of centimeters and violate the bounds.
        self.assertGreater(result['geometry']['positions'][36][1], 280)
        self.assertEqual(result['primitives'][3]['category'], 'backboard_glass')
        self.assertEqual(result['primitives'][3]['start'], 102)
        self.assertEqual(result['primitives'][3]['count'], 12)

    def test_reflection_mesh_is_decoded_but_never_claimed_physical_rim(self):
        result = self.report['models'][basket.PREFIX + 'rimr']
        self.assertTrue(result['decoded'])
        self.assertEqual((result['vertices'], result['top_lod_triangles']), (1001, 1352))
        self.assertEqual(result['classification'], 'reflection_only')
        reflected = [o for o in self.report['objects'] if o['model'].endswith(':rimr')]
        self.assertEqual(len(reflected), 2)
        self.assertTrue(all(not o['display_in_opaque_geometry_preview'] for o in reflected))
        mat = self.scene['Material']['basket_stanchioni2_nba:rimr_mat']
        techniques = self.scene['Effect'][mat['Effect']]['Technique']
        self.assertNotIn('Default', techniques)
        self.assertIn('GlassReflection', techniques)

    def test_original_table_all_nineteen_blended_pairs_and_transform_anchors(self):
        model = self.scene['Model'][basket.PREFIX + 'basket']
        table = self.archive.read(model['MatrixWeightsBuffer']['Binary'])
        self.assertEqual(len(table), 152)
        words = np.array([(i << 8) | 1 for i in range(0, 38, 2)], dtype=np.uint32)
        skin = basket.decode_weights(words, table, palette_size=4)
        np.testing.assert_allclose(skin['weights'].reshape(-1, 2).sum(1), 1)
        transforms = basket.hierarchy_bind_transforms(model)
        np.testing.assert_allclose(transforms[2]['translation_cm'], [0, 304.7640289, -.691314], atol=1e-7)
        np.testing.assert_allclose(transforms[3]['translation_cm'], [0, 307.23773252, 38.1000144], atol=1e-7)
        self.assertFalse(self.report['runtime_skin_palette_available'])

    def test_exact_primitives_preserve_rim_backboard_and_every_lod_start(self):
        result = self.report['models'][basket.PREFIX + 'basket']
        self.assertEqual(len(result['primitives']), 100)
        rim = result['primitives'][99]
        self.assertEqual((rim['start'], rim['count'], rim['category']), (666276, 4056, 'physical_rim'))
        self.assertEqual(len(rim['lod_ranges']), 12)
        self.assertEqual(rim['lod_ranges'][-1], {'start': 4695, 'count': 138})
        self.assertEqual(result['primitives'][88]['category'], 'backboard_frame_and_target')
        self.assertEqual(result['primitives'][91]['category'], 'rim_hinge_gasket')
        self.assertEqual(result['primitives'][92]['category'], 'backboard_padding')
        self.assertEqual(result['primitives'][96]['category'], 'backboard_led_lights')
        self.assertEqual(self.report['main_marker']['Attribute']['VC_NetType'], 'CLOTH')
        self.assertFalse(self.report['cloth_net_geometry_embedded'])


if __name__ == '__main__':
    unittest.main()
