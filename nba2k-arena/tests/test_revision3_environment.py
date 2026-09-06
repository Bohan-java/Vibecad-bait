"""Verify real donor render cleanup and protection of gameplay/crowd data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from revision3_environment import apply_environment

DONOR = ROOT / 'donor/original/arena_020_int_original.iff'


def scene(archive, filename):
    return json.loads(b'{' + archive.read(filename).strip() + b'}')


class Revision3EnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = zipfile.ZipFile(DONOR)
        cls.donor = scene(cls.archive, 'level.SCNE')['level']
        cls.candidate = deepcopy(cls.donor)
        cls.extra = {}
        cls.report = apply_environment(cls.candidate, cls.archive, cls.extra)

    @classmethod
    def tearDownClass(cls):
        cls.archive.close()

    def test_original_donor_hash_is_still_the_protected_handoff(self):
        self.assertEqual(hashlib.sha256(DONOR.read_bytes()).hexdigest(),
                         '42865ecaf8dd923c4d901509263af3b242c00975f4284b917ba79ce8fbbced46')

    def test_every_removed_model_has_zero_area_indices_at_every_lod(self):
        self.assertGreater(self.report['hidden_object_count'], 700)
        for entry in self.report['hidden_models']:
            with self.subTest(target=entry['target']):
                model = self.candidate['Model'][entry['target']]
                source = self.donor['Model'][entry['original_target']]
                data = self.extra[model['IndexBuffer']['Binary']]
                self.assertEqual(len(data), source['IndexBuffer']['Size'])
                self.assertFalse(any(data))
                self.assertNotIn('CompressionMethod', model['IndexBuffer'])
                self.assertEqual(model['IndexBufferCrc32'], zlib.crc32(data) & 0xffffffff)
                # Keeping all LOD index ranges with the same byte count makes
                # every indexed triangle (0,0,0), including coarse distance LODs.
                for key in set(source) | set(model):
                    if key not in ('IndexBuffer', 'IndexBufferCrc32'):
                        self.assertEqual(model[key], source[key], key)
                if source['IndexBuffer']['Binary'] in self.archive.namelist():
                    self.assertEqual(entry['original_resource_location'], 'donor_archive')
                    self.assertEqual(entry['original_resource_sha256'],
                                     hashlib.sha256(self.archive.read(source['IndexBuffer']['Binary'])).hexdigest())
                else:
                    self.assertEqual(entry['original_resource_location'], 'external_game_reference')
                    self.assertIsNone(entry['original_resource_sha256'])

    def test_required_indoor_render_categories_are_all_hidden(self):
        categories = self.report['hidden_categories']
        for group in ('ceiling', 'ceiling_panels', 'ceiling_panelslights', 'walls',
                      'scorecube', 'mural', 'mural_enclosure', 'stands',
                      'mural_lights', 'balcony_lights', 'balcony_chairs'):
            self.assertGreater(categories[group], 0, group)
        reasons = {item['name']: item['reason'] for item in self.report['hidden_objects']}
        for name in self.donor['Object']:
            if any(token in name for token in (':clutchtime_balcony_column_low',
                                                ':clutchtime_stands_tiers_low',
                                                ':clutchtime_crowd_seating_low',
                                                ':clutchtime_mural_wall_low')):
                self.assertIn(name, reasons)
        self.assertEqual(categories['stands'], 27)
        self.assertEqual(sum(v for k, v in categories.items() if k.startswith('court_')), 27)

    def test_only_original_gameplay_floor_remains_visible(self):
        visible = []
        for name, obj in self.donor['Object'].items():
            if obj.get('Type') != 'OBJECT':
                continue
            candidate_obj = self.candidate['Object'][name]
            self.assertEqual(candidate_obj, obj)
            model = self.candidate['Model'][obj['Target']]
            binary = model['IndexBuffer']['Binary']
            if binary in self.extra:
                self.assertFalse(any(self.extra[binary]), name)
            else:
                visible.append(obj['Target'].rsplit(':', 1)[-1])
        self.assertCountEqual(visible, ['floor_clutchtime_court_low'])
        self.assertEqual(self.report['hidden_object_count'], 791)
        self.assertEqual(self.report['hidden_model_count'], 66)
        self.assertEqual(self.report['seating_and_support_objects_preserved'], [])

    def test_all_original_objects_and_transforms_are_preserved(self):
        self.assertEqual(set(self.candidate['Object']), set(self.donor['Object']))
        for name, original in self.donor['Object'].items():
            actual = deepcopy(self.candidate['Object'][name])
            if name == 'TIME_OF_DAY':
                self.assertEqual(actual['Attribute']['VC_Enabled'], 1)
                self.assertEqual(actual['Attribute']['VC_SkyEnabled'], 1)
                actual['Attribute']['VC_Enabled'] = original['Attribute']['VC_Enabled']
                actual['Attribute']['VC_SkyEnabled'] = original['Attribute']['VC_SkyEnabled']
            self.assertEqual(actual, original, name)
        floor_target = self.donor['Object']['__floor00__']['Target']
        self.assertEqual(self.candidate['Model'][floor_target], self.donor['Model'][floor_target])
        self.assertEqual(self.candidate['Effect'], self.donor['Effect'])
        self.assertEqual(self.candidate['Texture'], self.donor['Texture'])

    def test_native_sky_lighting_only_changes_existing_activation_fields(self):
        changes = []
        for name, original in self.donor['Light'].items():
            actual = deepcopy(self.candidate['Light'][name])
            if actual != original:
                changes.append(name)
                self.assertEqual(actual['Attribute']['VC_IsActive'], 1 if name == 'Sun' else 0)
                actual['Attribute']['VC_IsActive'] = original['Attribute']['VC_IsActive']
                if name == 'Sun':
                    self.assertEqual(actual['Attribute']['VC_CastsShadows'], 1)
                    actual['Attribute']['VC_CastsShadows'] = original['Attribute']['VC_CastsShadows']
            self.assertEqual(actual, original, name)
        self.assertEqual(len(changes), 19)
        self.assertEqual(self.report['disabled_box_spotlights'], 18)
        self.assertEqual(len(self.report['court_area_lights_retained']), 4)
        for name in self.report['court_area_lights_retained']:
            self.assertEqual(self.candidate['Light'][name], self.donor['Light'][name])

    def test_crowd_override_hides_only_render_indices_and_is_json_serializable(self):
        json.dumps(self.report)
        original = scene(self.archive, 'crowd.SCNE')['crowd']
        changed = json.loads('{' + self.report['scene_overrides']['crowd.SCNE'] + '}')['crowd']
        source_model = original['Model']['crowd_cards']
        changed_model = changed['Model']['crowd_cards']
        data = self.extra[changed_model['IndexBuffer']['Binary']]
        self.assertEqual(len(data), 648)
        self.assertFalse(any(data))
        changed_model['IndexBuffer'] = source_model['IndexBuffer']
        changed_model['IndexBufferCrc32'] = source_model['IndexBufferCrc32']
        self.assertEqual(changed, original)
        self.assertEqual(set(self.report['scene_overrides']), {'crowd.SCNE'})
        self.assertFalse(any(n in self.extra for n in self.archive.namelist()))

    def test_unknown_instance_sharing_hidden_model_fails_before_mutation(self):
        candidate = deepcopy(self.donor)
        target = next(n for n in candidate['Model'] if ':clutchtime_wall_a_low' in n)
        candidate['Object']['user_created_unknown_gameplay_attachment'] = {
            'Type': 'OBJECT', 'Target': target,
        }
        before, extra = deepcopy(candidate), {'unrelated_resource.bin': b'keep'}
        with self.assertRaisesRegex(ValueError, 'Unknown object shares'):
            apply_environment(candidate, self.archive, extra)
        self.assertEqual(candidate, before)
        self.assertEqual(extra, {'unrelated_resource.bin': b'keep'})

    def test_missing_native_sky_field_fails_without_partially_cleaning_scene(self):
        candidate = deepcopy(self.donor)
        del candidate['Object']['TIME_OF_DAY']['Attribute']['VC_SkyEnabled']
        before, extra = deepcopy(candidate), {}
        with self.assertRaisesRegex(ValueError, 'Missing existing time-of-day field'):
            apply_environment(candidate, self.archive, extra)
        self.assertEqual(candidate, before)
        self.assertEqual(extra, {})

    def test_unrecognized_marker_and_model_remain_unchanged(self):
        candidate = deepcopy(self.donor)
        candidate['Object']['unknown_camera_anchor'] = {'Type': 'MARKER', 'Translate': [1, 2, 3]}
        candidate['Model']['unknown_future_mesh'] = {'custom_unparsed_data': [4, 5, 6]}
        extra = {}
        apply_environment(candidate, self.archive, extra)
        self.assertEqual(candidate['Object']['unknown_camera_anchor'], {'Type': 'MARKER', 'Translate': [1, 2, 3]})
        self.assertEqual(candidate['Model']['unknown_future_mesh'], {'custom_unparsed_data': [4, 5, 6]})


if __name__ == '__main__':
    unittest.main()
