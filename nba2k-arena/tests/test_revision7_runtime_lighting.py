"""Exercise the repair against the actual shipped R6 scene and native layouts."""
import base64
from copy import deepcopy
import io
from pathlib import Path
import struct
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_revision7 import input_member, parse_fragment, serialize_fragment, verify_resource_links
from revision7_runtime_lighting import (
    AMBIENT_BINARY, AUX_SCENE, FLOOR_VISIBILITY_BINARY, FLOOR_VISIBILITY_KEY,
    INDOOR_LIGHTS, NATIVE_EFFECT, NATIVE_MATERIAL, TLD_HEADER, VISIBILITY_BINARY,
    apply_runtime_lighting, check_scope, decode_r11g11b10,
    pack_lightmap_userdata, require_native_uv7, scenery_records,
)


class Revision7RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = zipfile.ZipFile(io.BytesIO(input_member('arena_700_int.iff')))
        cls.before = parse_fragment(cls.archive.read('level.SCNE'))['level']
        cls.floor_before = parse_fragment(cls.archive.read(AUX_SCENE))
        cls.after, cls.floor_after = deepcopy(cls.before), deepcopy(cls.floor_before)
        cls.resources = {}
        cls.report = apply_runtime_lighting(cls.after, cls.floor_after, cls.resources)

    @classmethod
    def tearDownClass(cls):
        cls.archive.close()

    def test_userdata_matches_original_apron_bytes(self):
        name = ('arena_clutchtime_int_master@GameObjects@apron@'
                'clutchtime_floor_apron:clutchtime_floor_apron_low')
        self.assertEqual(pack_lightmap_userdata(1944), self.before['Object'][name]['UserData'])

    def test_small_lightmap_userdata_matches_existing_native_instance(self):
        native = [o for name, o in self.before['Object'].items()
                  if name in self.before['Texture']
                  and self.before['Texture'][name].get('Width') == 16
                  and self.before['Texture'][name].get('Height') == 16
                  and self.before['Texture'][name].get('Faces') == 2 and 'UserData' in o]
        self.assertTrue(native)
        self.assertTrue(any(o['UserData'] == pack_lightmap_userdata(16) for o in native))

    def test_shader_atlas_transform_is_identity_and_both_faces_enabled(self):
        raw = base64.b64decode(pack_lightmap_userdata())
        flags, dimensions, offsets = struct.unpack_from('<III', raw, 16)
        # Equations read from the native Hires and Lores PS, not engine runtime execution.
        scale_u = ((flags >> 14) & 16383) / (dimensions >> 16)
        scale_v = (flags & 16383) / (dimensions & 65535)
        self.assertEqual((len(raw), flags >> 30, (flags >> 28) & 3), (48, 1, 2))
        self.assertEqual((scale_u, scale_v, offsets), (1., 1., 0))
        self.assertEqual(struct.unpack_from('<f', raw)[0], 1.)
        self.assertEqual(raw[4:16] + raw[28:], bytes(32))

    def test_userdata_rejects_unrepresentable_dimensions(self):
        for size in (0, -1, 16384, 1.5, True):
            with self.subTest(size=size), self.assertRaises(ValueError):
                pack_lightmap_userdata(size)

    def test_exact_r6_scenery_set_has_been_repaired(self):
        self.assertEqual(tuple(map(len, scenery_records(self.before))), (16, 83, 136))
        self.assertEqual(scenery_records(self.after), (set(), set(), set()))

    def test_native_static_effect_and_all_shader_definitions_preserved(self):
        self.assertEqual(self.before['Effect'], self.after['Effect'])
        native = self.before['Material'][NATIVE_MATERIAL]['Technique']
        for name in self.report['materials']:
            material = self.after['Material'][name]
            self.assertEqual(material['Effect'], NATIVE_EFFECT)
            self.assertEqual(material['Technique'], native)
            for field in ('Parameter', 'Resource', 'Script', 'ScriptParameter'):
                self.assertEqual(material.get(field), self.before['Material'][name].get(field))

    def test_real_gbuffer_and_shadow_passes_are_available_in_both_static_modes(self):
        for mode in ('HiresLightmap', 'LoresLightmap'):
            passes = self.after['Effect'][NATIVE_EFFECT]['Technique'][mode]['Pass']
            self.assertNotEqual(passes['Default']['PS']['Binary'], passes['GBuffer']['PS']['Binary'])
            self.assertEqual(passes['GBuffer']['EnableMask'], 512)
            self.assertEqual(passes['OnlyDepthCSM']['EnableMask'], 64)

    def test_every_instance_has_matching_embedded_texture_slots(self):
        for name in self.report['objects']:
            self.assertEqual(self.after['Object'][name]['UserData'], pack_lightmap_userdata())
            ambient = self.after['Texture'][name]
            visibility = self.after['Texture'][name + '_linelightvisibility']
            self.assertEqual((ambient['Width'], ambient['Height'], ambient['Faces'], ambient['Mips']),
                             (16, 16, 2, 2))
            self.assertEqual(ambient['Binary'], AMBIENT_BINARY)
            self.assertEqual(visibility['Binary'], VISIBILITY_BINARY)

    def test_native_uv7_fetch_layout_and_source_bytes_are_valid(self):
        require_native_uv7(self.before, self.archive, set(self.report['models']))
        for name in self.report['models']:
            original, candidate = deepcopy(self.before['Model'][name]), deepcopy(self.after['Model'][name])
            self.assertEqual(candidate['VertexFormat']['TEXCOORD7']['Offset'], [.5, .5, 0., 0.])
            candidate['VertexFormat']['TEXCOORD7']['Offset'] = [0., 0., 0., 0.]
            self.assertEqual(original, candidate)

    def test_rejects_uv_stream_outside_the_audited_layout(self):
        scene = deepcopy(self.before)
        name = self.report['models'][0]
        scene['Model'][name]['VertexFormat']['TEXCOORD7']['ByteOffset'] = 12
        with self.assertRaises(ValueError):
            require_native_uv7(scene, self.archive, {name})

    def test_two_face_tld_has_linear_face_major_mips(self):
        raw = self.resources[AMBIENT_BINARY]
        header = TLD_HEADER.unpack_from(raw)
        self.assertEqual(header[:10], (b'TLD ', 0, 4, 26, 2, 31, 16, 16, 1, 2))
        self.assertEqual(header[10:], (2560, 2560))
        self.assertEqual(len(raw), TLD_HEADER.size + 2560)
        pixels = raw[TLD_HEADER.size:]
        self.assertEqual(pixels[:1280], pixels[:4] * 320)
        self.assertEqual(pixels[1280:], pixels[1280:1284] * 320)
        self.assertEqual(decode_r11g11b10(struct.unpack_from('<I', pixels, 1280)[0]), (.5, .5, 1.))
        ambient = decode_r11g11b10(struct.unpack_from('<I', pixels)[0])
        self.assertEqual(ambient, (.796875, .8515625, .953125))

    def test_new_line_visibility_pixels_are_zero_for_scenery_and_floor(self):
        for name, size, pixel_bytes in ((VISIBILITY_BINARY, 16, 320),
                                        (FLOOR_VISIBILITY_BINARY, 424, 224720)):
            with self.subTest(name=name):
                raw = self.resources[name]
                header = TLD_HEADER.unpack_from(raw)
                self.assertEqual(header[:10], (b'TLD ', 0, 4, 61, 2, 31, size, size, 1, 1))
                self.assertEqual(header[10:], (pixel_bytes, pixel_bytes))
                self.assertEqual(raw[TLD_HEADER.size:], bytes(pixel_bytes))

    def test_indoor_area_lights_have_no_remaining_energy(self):
        active = []
        for name, light in self.after['Light'].items():
            if light.get('Attribute', {}).get('VC_IsActive') and light.get('Intensity', 0) > 0:
                active.append(name)
        self.assertEqual(active, ['Sun'])
        for name in INDOOR_LIGHTS:
            self.assertEqual(self.after['Light'][name]['Intensity'], 0.)
            self.assertEqual(self.after['Light'][name]['Attribute']['VC_IsActive'], 0)

    def test_daylight_exposure_is_fixed_and_native_sky_sun_preserved(self):
        old = self.before['Object']['TIME_OF_DAY']['Attribute']
        new = deepcopy(self.after['Object']['TIME_OF_DAY']['Attribute'])
        self.assertEqual((new['VC_AutomaticEV100Enabled'], new['VC_EV100']), (0, 15.))
        new['VC_AutomaticEV100Enabled'] = old['VC_AutomaticEV100Enabled']
        new['VC_EV100'] = old['VC_EV100']
        self.assertEqual(new, old)
        self.assertEqual(self.before['Light']['Sun'], self.after['Light']['Sun'])

    def test_rejects_invalid_exposure(self):
        for ev in (float('nan'), float('inf'), 0., 20.):
            with self.subTest(ev=ev), self.assertRaises(ValueError):
                apply_runtime_lighting(deepcopy(self.before), deepcopy(self.floor_before), {}, ev100=ev)

    def test_floor_irradiance_and_floor_marker_preserved(self):
        before, after = deepcopy(self.floor_before), deepcopy(self.floor_after)
        del before['level_floor_lightmaps']['Texture'][FLOOR_VISIBILITY_KEY]
        del after['level_floor_lightmaps']['Texture'][FLOOR_VISIBILITY_KEY]
        self.assertEqual(before, after)

    def test_every_object_transform_and_all_original_objects_preserved(self):
        for name, original in self.before['Object'].items():
            candidate = deepcopy(self.after['Object'][name])
            if name in self.report['objects']:
                del candidate['UserData']
            if name != 'TIME_OF_DAY':
                self.assertEqual(original, candidate)

    def test_scope_accepts_repair_and_rejects_geometry_material_or_sun_changes(self):
        check_scope(self.before, self.after, self.floor_before, self.floor_after, self.report)
        targets = [('Model', self.report['models'][0]), ('Material', self.report['materials'][0]),
                   ('Light', 'Sun'), ('Object', self.report['objects'][0])]
        for category, name in targets:
            with self.subTest(category=category):
                scene = deepcopy(self.after)
                scene[category][name]['unexpected'] = True
                with self.assertRaises(ValueError):
                    check_scope(self.before, scene, self.floor_before, self.floor_after, self.report)

    def test_scope_rejects_floor_irradiance_change(self):
        floor = deepcopy(self.floor_after)
        floor['level_floor_lightmaps']['Texture']['__floor00__']['Binary'] = 'wrong.tld'
        with self.assertRaises(ValueError):
            check_scope(self.before, self.after, self.floor_before, floor, self.report)

    def test_existing_bindings_cannot_be_silently_overwritten(self):
        scene = deepcopy(self.before)
        scene['Object'][self.report['objects'][0]]['UserData'] = pack_lightmap_userdata()
        with self.assertRaises(ValueError):
            apply_runtime_lighting(scene, deepcopy(self.floor_before), {})

    def test_resource_name_collision_rejected(self):
        with self.assertRaises(ValueError):
            apply_runtime_lighting(deepcopy(self.before), deepcopy(self.floor_before), {AMBIENT_BINARY: b'x'})

    def test_scene_fragments_roundtrip_and_do_not_claim_game_validation(self):
        self.assertEqual(parse_fragment(serialize_fragment({'level': self.after})), {'level': self.after})
        self.assertFalse(self.report['game_runtime_verified'])
        self.assertFalse(self.report['game_directory_modified'])


if __name__ == '__main__':
    unittest.main()
