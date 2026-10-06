"""Synthetic reproduction of selected N16 contracts; no real IFF is opened.

Source: Bohan-java/Vibecad-bait@92056876b32e7f383e591cedd25494747f48fea3
nba2k-arena/zgc-court/tools/night_scene.py, OLD_PREFIXES and strip_scene.
The cleanup body is transcribed. repair_iff.binaries is replaced by a
fixture-only walker. Passing these tests proves the illustrated Python
behavior, not the complete project pipeline or NBA 2K26 runtime.
"""
import copy
import re
import unittest

PREFIX = 'zgc_n16:'
OLD_PREFIXES = ('zgc_n4:', 'zgc_n5:', 'zgc_n6:', 'zgc_probe_emit:',
                'zgc_diag_receiver:', 'zgc_n7:', 'zgc_n8:', 'zgc_n9:',
                'zgc_n10:', 'zgc_n11:', 'zgc_n12:', 'zgc_n13:',
                'zgc_n14:', 'zgc_n15:', PREFIX)
PROBE_DATA_KEY = re.compile(r'^LIGHT_PROBE_GRID_(\d+)_(\d+)_(\d+)_TIME_0000_PROBE_DATA$')


def binaries(value):
    """Fixture walker, not a complete native dependency resolver."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'Binary' and isinstance(child, str):
                yield child
            else:
                yield from binaries(child)
    elif isinstance(value, list):
        for child in value:
            yield from binaries(child)


def _texture_archive_name(binary):
    if binary.endswith('.tld'):
        return binary[:-4] + '.dds'
    if binary.endswith('.gz'):
        return binary[:-3] + '.bin'
    return binary


def strip_scene(level, base_level):
    old = lambda k: k.startswith(OLD_PREFIXES)
    removed = [level['Model'].pop(n) for n in [k for k in level['Model'] if old(k)]]
    removed += [level['Texture'].pop(n) for n in [k for k in level['Texture'] if old(k)]]
    for section in ('Object', 'Material', 'Light'):
        for name in [k for k in level[section] if old(k)]:
            del level[section][name]
    for key in [k for k in level['Texture'] if PROBE_DATA_KEY.fullmatch(k)]:
        if level['Texture'][key] != base_level['Texture'][key]:
            removed.append(level['Texture'][key])
            level['Texture'][key] = copy.deepcopy(base_level['Texture'][key])
    kept = {_texture_archive_name(b) for section in ('Model', 'Texture') for v in level[section].values() for b in binaries(v)}
    return {_texture_archive_name(b) for v in removed for b in binaries(v)} - kept


def empty_level():
    return {key: {} for key in ('Model', 'Texture', 'Object', 'Material', 'Light')}


class PipelineContractTests(unittest.TestCase):
    def test_all_legacy_light_prefixes_are_removed(self):
        level, base = empty_level(), empty_level()
        level['Light'] = {prefix + 'test': {'Type': 'SPOT'} for prefix in OLD_PREFIXES}
        strip_scene(level, base)
        self.assertEqual(level['Light'], {})

    def test_distinct_namespace_and_native_light_survive_cleanup(self):
        level, base = empty_level(), empty_level()
        expected = {'native_spot': {'Type': 'SPOT'},
                    'zgc_lbdiag_v1:test': {'Type': 'SPOT'}}
        level['Light'] = copy.deepcopy(expected)
        strip_scene(level, base)
        self.assertEqual(level['Light'], expected)

    def test_old_content_removed_from_all_five_sections(self):
        level, base = empty_level(), empty_level()
        for section in level:
            level[section] = {'zgc_n4:old': {}, 'native_kept': {}}
        strip_scene(level, base)
        for section in level:
            self.assertEqual(level[section], {'native_kept': {}})

    def test_probe_data_restored_but_spatial_indices_retained(self):
        level, base = empty_level(), empty_level()
        key = 'LIGHT_PROBE_GRID_3_0_2_TIME_0000_PROBE_DATA'
        index_key = 'LIGHT_PROBE_GRID_3_0_2_CELL_PROBE_INDICES'
        base['Texture'][key] = {'Binary': 'day.gz'}
        level['Texture'][key] = {'Binary': 'experiment.gz'}
        level['Texture'][index_key] = {'Binary': 'indices.gz'}
        removed = strip_scene(level, base)
        self.assertEqual(level['Texture'][key], {'Binary': 'day.gz'})
        self.assertEqual(level['Texture'][index_key], {'Binary': 'indices.gz'})
        self.assertIn('experiment.bin', removed)
        self.assertIsNot(level['Texture'][key], base['Texture'][key])

    def test_shared_resource_is_not_marked_orphaned(self):
        level, base = empty_level(), empty_level()
        level['Model'] = {'zgc_n4:old': {'Binary': 'shared.gz'},
                          'native': {'Binary': 'shared.gz'}}
        self.assertEqual(strip_scene(level, base), set())

    def test_relighting_one_violates_current_probe_gate(self):
        def probe_gate(grid):
            assert grid['VERSION'] == 4 and grid['USE_RELIGHTING'] == 0
        probe_gate({'VERSION': 4, 'USE_RELIGHTING': 0})
        with self.assertRaises(AssertionError):
            probe_gate({'VERSION': 4, 'USE_RELIGHTING': 1})


if __name__ == '__main__':
    unittest.main(verbosity=2)
