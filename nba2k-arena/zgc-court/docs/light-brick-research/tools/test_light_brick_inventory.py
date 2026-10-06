"""Synthetic fixtures only: these tests do NOT test a real NBA 2K26 IFF."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from light_brick_inventory import Pairs, collect_selections, contained, extract, parse_scne, resolve_ref, collect_refs


class CollectorTests(unittest.TestCase):
    def test_fragment_and_duplicate_keys(self):
        doc, fragment = parse_scne(b'"level":{"Light":{"Sun":{"Type":"DIRECTIONAL"}},"x":1,"x":2}')
        self.assertTrue(fragment)
        self.assertIsInstance(doc, Pairs)
        self.assertEqual([v for k, v in doc[0][1] if k == 'x'], [1, 2])
        _, duplicates, _ = collect_selections(doc)
        self.assertEqual(duplicates[0]['keys']['x'], 2)

    def test_short_named_reference_is_followed(self):
        doc, _ = parse_scne(b'"level":{"Texture":{"LIGHT_BRICK_MAP":"B0"},"Buffer":{"B0":{"Binary":"map.bin"}}}')
        selected, _, ambiguous = collect_selections(doc)
        self.assertIn('map.bin', collect_refs(selected))
        self.assertEqual(ambiguous, [])

    def test_ambiguous_short_reference_is_not_guessed(self):
        doc, _ = parse_scne(b'"level":{"Texture":{"LIGHT_BRICK_MAP":"B0"},"A":{"B0":{"Binary":"one.bin"}},"B":{"B0":{"Binary":"two.bin"}}}')
        selected, _, ambiguous = collect_selections(doc)
        self.assertTrue(any(row['token'] == 'B0' for row in ambiguous))
        self.assertNotIn('one.bin', collect_refs(selected))
        self.assertNotIn('two.bin', collect_refs(selected))

    def fixture(self, root):
        p = root / 'fixture.iff'
        text = b'''"level": {
          "Light": {"key": {"Type":"SPOT","Intensity":20,"Attribute":{"VC_IsMovable":0}}},
          "Texture": {"LIGHT_BRICK_MAP": {"Binary":"map.gz","Size":16},
                      "LIGHT_PROBE_GRID_0_0_0_TIME_0000_PROBE_DATA":{"Binary":"probe.bin"}},
          "Marker": {"LIGHT_GRID_OTHER":{"Binary":"shared/missing.gz"}},
          "Test":"opaque"
        }'''
        with zipfile.ZipFile(p, 'w') as z:
            z.writestr('level.SCNE', text)
            z.writestr('map.bin', bytes(range(16)))
            z.writestr('probe.bin', b'X' * 112)
        return p, text

    def test_alias_missing_probe_skip_and_source_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            p, raw = self.fixture(root)
            original = p.read_bytes()  # Synthetic fixture only, not a project-file hash.
            report = extract(p, root/'out', root, [])
            self.assertEqual(p.read_bytes(), original)
            self.assertEqual((root/'out/scene.raw.SCNE').read_bytes(), raw)
            rows = {r['reference']:r for r in report['resources']}
            self.assertEqual(rows['map.gz']['resolution'], 'archive_gz_to_bin_alias')
            self.assertEqual(rows['map.gz']['raw_views']['first_u32_little_endian'][0], 0x03020100)
            self.assertEqual(rows['shared/missing.gz']['resolution'], 'unresolved')
            self.assertEqual(rows['probe.bin']['extraction'], 'skipped_probe_payload_by_default')

    def test_exact_cached_gzip_preserved_and_decoded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            p, _ = self.fixture(root)
            cache = root/'cache'
            (cache/'shared').mkdir(parents=True)
            (cache/'shared/missing.gz').write_bytes(gzip.compress(b'known synthetic bytes'))
            report = extract(p, root/'out', root, [cache])
            row = next(r for r in report['resources'] if r['reference']=='shared/missing.gz')
            self.assertEqual(row['resolution'], 'explicit_cache_exact')
            self.assertEqual((root/'out'/row['gunzip_output']).read_bytes(), b'known synthetic bytes')

    def test_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            p, _ = self.fixture(root)
            (root/'out').mkdir()
            with self.assertRaisesRegex(ValueError, 'already exists'):
                extract(p, root/'out', root, [])

    def test_lfs_pointer_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            p = root/'pointer.iff'
            p.write_text('version https://git-lfs.github.com/spec/v1\noid sha256:not-real\nsize 45028875\n')
            with self.assertRaisesRegex(ValueError, 'Git LFS pointer'):
                extract(p, root/'out', root, [])
            self.assertFalse((root/'out').exists())

    def test_size_budget_does_not_mean_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            p, _ = self.fixture(root)
            r = extract(p, root/'out', root, [], max_resource=8)
            row = next(x for x in r['resources'] if x['reference']=='map.gz')
            self.assertEqual(row['resolution'], 'archive_gz_to_bin_alias')
            self.assertEqual(row['extraction'], 'skipped_explicit_size_budget')

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            with self.assertRaises(ValueError):
                contained(root/'../elsewhere', root)

    def test_unsupported_scne_retains_raw(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            p = root/'fixture.iff'
            raw = b'\x00not-a-json-scene'
            with zipfile.ZipFile(p,'w') as z:
                z.writestr('level.SCNE',raw)
            r = extract(p,root/'out',root,[])
            self.assertIn('parse_error',r)
            self.assertEqual((root/'out/scene.raw.SCNE').read_bytes(),raw)

    def test_ambiguous_same_name_archive_member(self):
        import warnings
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            p = root/'fixture.iff'
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                with zipfile.ZipFile(p,'w') as z:
                    z.writestr('x.bin',b'A')
                    z.writestr('x.bin',b'B')
            with zipfile.ZipFile(p) as z:
                status,*_ = resolve_ref('x.bin',z,[],root)
                self.assertEqual(status,'ambiguous_archive_member')


if __name__ == '__main__':
    unittest.main(verbosity=2)
