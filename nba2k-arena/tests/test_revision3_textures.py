"""Independent BC mip decoding and shader-channel/material-scope checks."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import struct
import tempfile
import unittest
import zipfile

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import revision3_textures as textures


class TextureCodecTests(unittest.TestCase):
    def test_bc1_and_bc3_all_mips_non_square_and_small_dimensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            for size, mode, color in (((16, 32), 'RGB', (111, 122, 133)),
                                       ((5, 9), 'RGBA', (128, 128, 240, 15)),
                                       ((2, 1), 'RGBA', (255, 255, 255, 0))):
                with self.subTest(size=size, mode=mode):
                    key, spec, raw, audit = textures.encode_texture('check', Image.new(mode, size, color), output_dir=temporary)
                    mips = textures.decode_tld_mips(raw, spec)
                    self.assertEqual([im.size for im in mips], textures.mip_sizes(*size))
                    self.assertTrue(audit['all_mips_decoded'])
                    self.assertEqual(len(raw), spec['PixelDataSize'] + 32)
                    self.assertEqual(struct.unpack_from('<H', raw, 22)[0], 1)
                    self.assertEqual(mips[-1].size, (1, 1))
                    if mode == 'RGBA':
                        for mip in mips:
                            self.assertTrue(np.all(np.asarray(mip)[:, :, 3] == color[3]))

    def test_corrupt_size_or_truncated_payload_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, spec, raw, _ = textures.encode_texture('check', Image.new('RGB', (4, 4), 'white'), output_dir=temporary)
            with self.assertRaisesRegex(ValueError, 'payload size mismatch'):
                textures.decode_tld_mips(raw[:-1], spec)
            bad = copy.deepcopy(spec)
            bad['Width'] = 8
            with self.assertRaisesRegex(ValueError, 'header/spec mismatch'):
                textures.decode_tld_mips(raw, bad)

    def test_floor_and_generic_channels_are_distinct(self):
        normal = Image.new('RGB', (4, 4), (128, 128, 255))
        rough = Image.new('L', (4, 4), 255)
        generic = np.asarray(textures.packed_normal(normal, rough))
        floor = np.asarray(textures.packed_normal(normal, rough, floor=True, reflection=.06))
        self.assertTrue(np.all(generic[:, :, 2] == 0))
        self.assertTrue(np.all(generic[:, :, 3] > 220))
        self.assertTrue(np.all(floor[:, :, 2] > 220))
        self.assertTrue(np.all(floor[:, :, 3] == 15))
        with self.assertRaisesRegex(ValueError, 'strictly positive'):
            textures.packed_normal(normal, rough, floor=True, reflection=0)

    def test_encoder_is_content_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = textures.leaf_texture((32, 64))
            first = textures.encode_texture('leaf', image, output_dir=temporary)
            second = textures.encode_texture('leaf', image, output_dir=temporary)
            self.assertEqual(first, second)

    def test_single_layer_header_matches_original_bc7_not_block_bytes(self):
        # BC7 has the same 16-byte block length as BC3, but this original
        # single-layer donor texture stores 1 at offset22, disproving V2's
        # old "block_words = 2" interpretation for alpha-bearing formats.
        with zipfile.ZipFile(ROOT / 'donor/original/arena_020_int_original.iff') as archive:
            scene = json.loads(b'{' + archive.read('baskets.SCNE') + b'}')['baskets']
            spec = scene['Texture']['NormalAndRoughMap#914a651a_1602']
            raw = archive.read(spec['Binary'])
        self.assertEqual(spec['Format'], 'BC7_UNORM')
        self.assertEqual(struct.unpack_from('<H', raw, 22)[0], spec.get('Faces', 1))
        self.assertEqual(struct.unpack_from('<H', raw, 22)[0], 1)

    def test_fan_veins_align_to_28_radial_uv_sectors(self):
        image = np.asarray(textures.leaf_texture((1120, 64)), float)
        profile = image[-1, :, 1]
        power = np.abs(np.fft.rfft(profile - profile.mean()))
        # Main ribs and fine veins run at constant U; they have strong 28/112
        # frequencies across the full fan instead of an unrelated leaflet mask.
        self.assertGreater(power[28], 100)
        self.assertGreater(power[112], 100)


class MaterialIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        with zipfile.ZipFile(ROOT / 'donor/original/arena_020_int_original.iff') as archive:
            cls.before = json.loads(b'{' + archive.read('level.SCNE') + b'}')['level']
        cls.after = copy.deepcopy(cls.before)
        cls.extra = {}
        cls.report = textures.apply_textures(cls.after, cls.extra, output_dir=cls.temp.name, max_size=64)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_complete_keys_local_resources_and_scan_hashes(self):
        keys = self.report['textures']
        for label in ('court_concrete', 'concrete', 'grass', 'bark', 'sand', 'leaf', 'leaf_light', 'leaf_dead',
                      'aluminum', 'dark_metal', 'ocean'):
            self.assertIn(label, keys)
            self.assertIn(label + '_normal', keys)
        self.assertEqual(len(self.report['source_assets']), 12)
        for source in self.report['source_assets']:
            self.assertEqual(source['license'], 'CC0-1.0')
            self.assertEqual(len(source['sha256']), 64)
        for label, key in keys.items():
            spec = self.after['Texture'][key]
            self.assertIn(spec['Binary'], self.extra)
            self.assertTrue(self.report['assets'][label]['all_mips_decoded'])
        self.assertTrue((Path(self.temp.name) / 'material_contact_sheet.png').exists())

    def test_actual_floor_packing_does_not_reintroduce_wet_gain_or_zero_division(self):
        keys = self.report['textures']
        for label in ('floor_base', 'floor_normal'):
            spec = self.after['Texture'][keys[label]]
            mips = textures.decode_tld_mips(self.extra[spec['Binary']], spec)
            for image in mips:
                rgba = np.asarray(image)
                if label == 'floor_base':
                    self.assertTrue(np.all(rgba[:, :, 0] == 0))
                else:
                    self.assertGreaterEqual(rgba[:, :, 2].min() / 255, .86)
                    self.assertGreater(rgba[:, :, 3].min() / 255, 0)
                    self.assertLessEqual(rgba[:, :, 3].max() / 255, .08)

    def test_scene_change_scope_and_line_source_for_court_copy(self):
        restored = copy.deepcopy(self.after)
        for key in list(restored['Texture']):
            if key not in self.before['Texture']:
                del restored['Texture'][key]
        expected_materials = set(textures.FLOOR_MATERIALS) | set(textures.SURFACE_MATERIALS)
        changed = {name for name in restored['Material'] if restored['Material'][name] != self.before['Material'][name]}
        self.assertEqual(changed, expected_materials)
        for name in expected_materials:
            restored['Material'][name] = copy.deepcopy(self.before['Material'][name])
        self.assertEqual(restored, self.before)
        for name in textures.FLOOR_MATERIALS[1:]:
            slot = self.after['Material'][name]['Resource']['DetailAlbedoTexture']['Pixelmap']
            self.assertEqual(slot, self.report['textures']['line_white'])
        self.assertFalse(self.report['original_binary_files_modified'])
        self.assertFalse(self.report['game_runtime_verified'])

    def test_court_and_promenade_have_distinct_grades_and_bindings(self):
        keys = self.report['textures']
        self.assertNotEqual(keys['court_concrete'], keys['concrete'])
        court_slot = self.after['Material'][textures.FLOOR_MATERIALS[0]]['Resource']['DetailAlbedoTexture']['Pixelmap']
        apron_slot = self.after['Material']['clutchtime_floor_apron:floor_mat']['Resource']['AlbedoMap']['Pixelmap']
        self.assertEqual(court_slot, keys['court_concrete'])
        self.assertEqual(apron_slot, keys['concrete'])
        dark = self.report['assets']['court_concrete']['decoded_rgba_mean'][:3]
        light = self.report['assets']['concrete']['decoded_rgba_mean'][:3]
        self.assertGreater(np.mean(light) - np.mean(dark), 45)
        self.assertEqual(self.report['concrete_color_profiles']['court_concrete']['target_rgb'], [90, 94, 96])
        self.assertEqual(self.report['concrete_color_profiles']['concrete']['target_rgb'], [158, 154, 142])

    def test_original_source_resolutions_are_available_without_production_cap(self):
        expected = {'concrete_floor_02_diff_4k.jpg': (4096, 4096),
                    'palm_tree_bark_diff_2k.jpg': (2048, 4096),
                    'palm_tree_bark_nor_dx_2k.jpg': (2048, 4096),
                    'leafy_grass_diff_2k.jpg': (2048, 2048),
                    'coast_sand_01_diff_2k.jpg': (2048, 2048)}
        for name, size in expected.items():
            with Image.open(textures.SOURCE / name) as image:
                self.assertEqual(image.size, size)
        self.assertIn('Original diffuse and normal source dimensions', self.report['scan_resolution_policy'])


if __name__ == '__main__':
    unittest.main()
