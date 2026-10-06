"""Checked SCNE-only night-base patch of the current package (see night_lighting)."""
from pathlib import Path
import copy
import json
import os
import time
import zipfile
from iff_codec import load_scne
from native_archive import write_compatible
from night_lighting import apply_night, REVISION
from patch_half_court_current import digest, raw_record_hash
from repair_iff import dump_native

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / 'output/arena_700_int.iff'
    report_path = ROOT / 'validation/iff-current.json'
    report = json.loads(report_path.read_text(encoding='utf8'))
    original_hash = digest(output)
    assert original_hash == report['output_sha256'], 'Current output and report disagree'
    staging = ROOT / '.build-staging'
    staging.mkdir(exist_ok=True)
    pending = staging / 'night.pending'
    with zipfile.ZipFile(output) as current:
        raw = current.read('level.SCNE')
        doc = load_scne(raw)
        assert dump_native(doc) == raw, 'level.SCNE does not round-trip byte-identically'
        level = doc['level']
        before = copy.deepcopy(level)
        night = apply_night(level)
        assert level != before, 'Night values already current; do not republish'
        changed_objects = {k for k in level['Object'] if level['Object'][k] != before['Object'][k]}
        from night_lighting import IBL_OBJECTS
        assert changed_objects <= {'TIME_OF_DAY', 'LIGHT_PROBE_GRID_DATA', *IBL_OBJECTS}, changed_objects
        for key in before:
            if key not in ('Light', 'Object'):
                assert before[key] == level[key], key
        print('Writing SCNE-only night base; retaining original until validation passes', flush=True)
        count = write_compatible(current, current, pending, {'level.SCNE': dump_native(doc)}, set())
        print('Checking archive CRC and exact preservation of all other compressed entries', flush=True)
        with zipfile.ZipFile(pending) as final:
            assert final.testzip() is None
            assert final.namelist() == current.namelist()
            assert len(set(final.namelist())) == count
            assert load_scne(final.read('level.SCNE')) == doc
            identical = 0
            for old in current.infolist():
                new = final.getinfo(old.filename)
                assert old.compress_type == new.compress_type
                if old.filename == 'level.SCNE':
                    continue
                assert (old.CRC, old.file_size, old.compress_size) == (new.CRC, new.file_size, new.compress_size)
                assert raw_record_hash(current, old) == raw_record_hash(final, new), old.filename
                identical += 1
            assert final.read('PostEffect.FxTweakables') == current.read('PostEffect.FxTweakables')
    night.update(source_iff_sha256=original_hash, unchanged_compressed_entries=identical,
                 changed_archive_members=['level.SCNE'], archive_crc_verified=True)
    report['revision'] = report['revision'].split('+')[0] + '+' + REVISION
    report['night_lighting'] = {k: v for k, v in night.items() if k not in ('before', 'after')}
    report['game_tested'] = False
    report['game_visibility'] = 'pending'
    report['global_sun_and_postfx_unchanged'] = False
    report['postfx_unchanged'] = True
    report['source_feedback'] = 'User requests a night look with court-side light strips; first test the night base only, then a single emissive A-sign diffuser.'
    report['changes'] = [c for c in report['changes'] if not c.startswith('Night base')]
    report['changes'].append(f"Night base {REVISION}: dim the native sun to cool moonlight, darken sky and clouds, lower baked probe ambient; no geometry, material, texture or post-effect change.")
    report.update(output_bytes=pending.stat().st_size, output_sha256=digest(pending),
                  archive_crc_verified=True, archive_entries=count)
    os.replace(pending, output)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    (ROOT / 'validation/night-current.json').write_text(json.dumps({
        **night, 'output_sha256': report['output_sha256'], 'output_bytes': report['output_bytes'],
        'game_tested': False, 'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())},
        ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: report[k] for k in ('revision', 'output_bytes', 'output_sha256')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
