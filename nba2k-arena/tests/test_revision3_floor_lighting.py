"""Independent mini-float conversion and real donor floor-lighting checks."""
from copy import deepcopy
import io
import json
import math
from pathlib import Path
import struct
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from revision3_floor_lighting import (AUX_SCENE, LIGHTMAP, VISIBILITY, apply_floor_lighting,
                                      decode_r11g11b10, encode_r11g11b10, subresources)


class MiniFloatTests(unittest.TestCase):
    def test_fixed_dxgi_bit_layout_vectors(self):
        self.assertEqual(encode_r11g11b10((0, 0, 0)), 0x00000000)
        self.assertEqual(encode_r11g11b10((1, 1, 1)), 0x781e03c0)
        self.assertEqual(encode_r11g11b10((.5, .5, .5)), 0x701c0380)
        self.assertEqual(encode_r11g11b10((.5, .5, 1)), 0x781c0380)
        self.assertEqual(decode_r11g11b10(0x781e03c0), (1., 1., 1.))
        self.assertEqual(decode_r11g11b10(0x00000400), (2., 0., 0.))

    def test_every_finite_channel_matches_independent_ieee_half_decoder(self):
        # Unsigned 11-bit floats are exactly representable in IEEE binary16
        # after shifting the fraction/exponent word left four bits; 10-bit
        # floats shift five. struct's independent half implementation is the
        # reference, rather than reusing our encoder/decoder's exponent math.
        for channel, bits, shift, field_shift in ((0, 6, 4, 0), (1, 6, 4, 11), (2, 5, 5, 22)):
            for mini_word in range(31 << bits):
                reference = struct.unpack('<e', struct.pack('<H', mini_word << shift))[0]
                packed = mini_word << field_shift
                self.assertEqual(decode_r11g11b10(packed)[channel], reference)
                values = [0., 0., 0.]
                values[channel] = reference
                self.assertEqual(encode_r11g11b10(values), packed)

    def test_rounding_ties_and_smallest_subnormals(self):
        self.assertEqual(encode_r11g11b10((1 + 1 / 128, 0, 0)), 0x3c0)
        self.assertEqual(encode_r11g11b10((1 + 3 / 128, 0, 0)), 0x3c2)
        self.assertEqual(encode_r11g11b10((0, 0, 1 + 1 / 64)), 0x1e0 << 22)
        self.assertEqual(encode_r11g11b10((2 ** -20, 2 ** -20, 2 ** -19)), 1 | (1 << 11) | (1 << 22))
        self.assertEqual(encode_r11g11b10((2 ** -21, 2 ** -21, 2 ** -20)), 0)

    def test_nonfinite_negative_and_overflow_inputs_are_rejected(self):
        for value in (-1., math.inf, math.nan, 70000.):
            with self.subTest(value=value), self.assertRaises(ValueError):
                encode_r11g11b10((value, 0., 0.))
        with self.assertRaises(ValueError):
            encode_r11g11b10((1., 1.))
        self.assertTrue(math.isinf(decode_r11g11b10(0x7c0)[0]))
        self.assertTrue(math.isnan(decode_r11g11b10(0x7c1)[0]))


class FloorLightingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = zipfile.ZipFile(ROOT / 'donor/original/arena_020_int_original.iff')
        cls.original = json.loads(b'{' + cls.archive.read(AUX_SCENE).strip() + b'}')
        cls.extra = {}
        cls.report = apply_floor_lighting(cls.archive, cls.extra)
        cls.changed = json.loads('{' + cls.report['scene_overrides'][AUX_SCENE] + '}')

    @classmethod
    def tearDownClass(cls):
        cls.archive.close()

    def test_donor_segment_memory_offsets_define_face_major_mips(self):
        records = subresources(424, 424, 2, 2, 4)
        self.assertEqual([(r['face'], r['mip'], r['pixel_offset'], r['pixel_bytes']) for r in records],
                         [(0, 0, 0, 719104), (0, 1, 719104, 179776),
                          (1, 0, 898880, 719104), (1, 1, 1617984, 179776)])
        spec = self.original['level_floor_lightmaps']['Texture'][LIGHTMAP]
        by_key = {(s.get('MinFace', 0), s.get('MinMip', 0)): s for s in spec['Segments']}
        for r in records:
            source = by_key[(r['face'], r['mip'])]
            self.assertEqual(source.get('MemoryOffset', 0), r['pixel_offset'])
            self.assertEqual(source['MemorySize'], r['pixel_bytes'])

    def test_raw_tld_header_agrees_with_native_array_header_structure(self):
        native = self.archive.read('chair_arenacrowd_seatbackcushion_low.c2e1e24da31d7710.tld')
        native_header = struct.unpack('<4sIHBBIHHHHII', native[:32])
        self.assertEqual(native_header[3], 95)  # actual native BC6H floating array
        self.assertEqual(native_header[9], 2)
        for entry in self.report['textures']:
            blob = self.extra[entry['replacement_spec']['Binary']]
            header = struct.unpack('<4sIHBBIHHHHII', blob[:32])
            for index in (0, 1, 2, 4, 5, 8):
                self.assertEqual(header[index], native_header[index])
            self.assertEqual(header[6:8], (424, 424))
            self.assertEqual(header[3], 26 if entry['texture_key'] == LIGHTMAP else 61)
            self.assertEqual(header[9], 2 if entry['texture_key'] == LIGHTMAP else 1)
            self.assertEqual(header[10], len(blob) - 32)
            self.assertEqual(header[11], len(blob) - 32)

    def test_every_texel_in_every_face_and_mip_has_the_expected_value(self):
        self.assertEqual(self.report['ambient_quantized_rgb'], [.796875, .8515625, .953125])
        by_name = {entry['texture_key']: entry for entry in self.report['textures']}
        light_entry = by_name[LIGHTMAP]
        light = self.extra[light_entry['replacement_spec']['Binary']]
        self.assertEqual(len(light), 1797760 + 32)
        for r in light_entry['subresources']:
            start, length = 32 + r['pixel_offset'], r['pixel_bytes']
            word = struct.unpack_from('<I', light, start)[0]
            expected = (.796875, .8515625, .953125) if r['face'] == 0 else (.5, .5, 1.)
            self.assertEqual(decode_r11g11b10(word), expected)
            self.assertEqual(light[start:start + length], struct.pack('<I', word) * (length // 4))
        visibility_entry = by_name[VISIBILITY]
        visibility = self.extra[visibility_entry['replacement_spec']['Binary']]
        self.assertEqual(len(visibility), 224720 + 32)
        self.assertEqual(visibility[32:], b'\xff' * 224720)

    def test_only_aux_texture_bindings_storage_metadata_and_extrema_change(self):
        restored = deepcopy(self.changed)
        old_textures = self.original['level_floor_lightmaps']['Texture']
        textures = restored['level_floor_lightmaps']['Texture']
        self.assertEqual(set(textures), set(old_textures))
        for name in (LIGHTMAP, VISIBILITY):
            new, old = textures[name], old_textures[name]
            self.assertNotIn('CompressionMethod', new)
            self.assertNotIn('Segments', new)
            for key in ('Binary', 'Min', 'Max', 'Segments', 'CompressionMethod'):
                if key in old:
                    new[key] = deepcopy(old[key])
                else:
                    new.pop(key, None)
            self.assertEqual(new, old)
        self.assertEqual(restored, self.original)
        self.assertEqual(set(self.report['scene_overrides']), {AUX_SCENE})
        self.assertFalse(any(n in self.archive.namelist() for n in self.extra))
        json.dumps(self.report)

    def test_new_statistics_match_quantized_pixels_not_old_external_metadata(self):
        textures = self.changed['level_floor_lightmaps']['Texture']
        self.assertEqual(textures[LIGHTMAP]['Min'], [.5, .5, .953125, 1.])
        self.assertEqual(textures[LIGHTMAP]['Max'], [.796875, .8515625, 1., 1.])
        self.assertEqual(textures[VISIBILITY]['Min'], [1., 0., 0., 1.])
        self.assertEqual(textures[VISIBILITY]['Max'], [1., 0., 0., 1.])
        self.assertTrue(all(not e['source_pixels_in_donor_archive'] for e in self.report['textures']))
        self.assertFalse(self.report['game_exposure_calibrated'])

    def test_custom_ambient_is_encoded_and_does_not_change_lightmap_layout(self):
        extra = {}
        report = apply_floor_lighting(self.archive, extra, ambient_rgb=(.25, .5, .75))
        self.assertEqual(report['ambient_quantized_rgb'], [.25, .5, .75])
        self.assertEqual([e['subresources'] for e in report['textures']],
                         [e['subresources'] for e in self.report['textures']])

    def test_output_collision_and_invalid_source_are_atomic(self):
        filename = self.report['textures'][1]['replacement_spec']['Binary']
        extra = {filename: b'existing output must survive'}
        with self.assertRaisesRegex(ValueError, 'already exists'):
            apply_floor_lighting(self.archive, extra)
        self.assertEqual(extra, {filename: b'existing output must survive'})
        bad = deepcopy(self.original)
        bad['level_floor_lightmaps']['Texture'][LIGHTMAP]['Segments'][0]['MemoryOffset'] += 4
        storage = io.BytesIO()
        with zipfile.ZipFile(storage, 'w') as z:
            z.writestr(AUX_SCENE, json.dumps(bad)[1:-1])
        extra = {}
        with zipfile.ZipFile(io.BytesIO(storage.getvalue())) as z:
            with self.assertRaisesRegex(ValueError, 'segment memory layout differs'):
                apply_floor_lighting(z, extra)
        self.assertEqual(extra, {})


if __name__ == '__main__':
    unittest.main()
