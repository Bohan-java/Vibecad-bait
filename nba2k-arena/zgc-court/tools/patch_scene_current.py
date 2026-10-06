"""Checked patch that adds the N4 night scene (night_scene) to the current package.

The current package must already carry the night base (night_lighting). Only
level.SCNE changes; new vertex/index buffers are appended; every other record
is copied byte-for-byte and verified.
"""
from pathlib import Path
import json
import os
import time
import zipfile
from iff_codec import load_scne
from native_archive import write_compatible
from night_lighting import is_night
from night_scene import apply_scene, strip_scene, REVISION, PREFIX
from patch_half_court_current import digest, raw_record_hash
from repair_iff import dump_native, binaries, present

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / 'output/arena_700_int.iff'
    report_path = ROOT / 'validation/iff-current.json'
    report = json.loads(report_path.read_text(encoding='utf8'))
    original_hash = digest(output)
    assert original_hash == report['output_sha256'], 'Current output and report disagree'
    staging = ROOT / '.build-staging'
    staging.mkdir(exist_ok=True)
    pending = staging / 'scene.pending'
    with zipfile.ZipFile(output) as current:
        raw = current.read('level.SCNE')
        doc = load_scne(raw)
        assert dump_native(doc) == raw
        level = doc['level']
        assert is_night(level), 'Apply the night base first'
        orphans = strip_scene(level)
        before = {k: dict(level[k]) for k in ('Light', 'Material', 'Model', 'Object')}
        extra = {}
        scene = apply_scene(level, current, extra)
        for key, old in before.items():
            for name, value in old.items():
                assert level[key][name] is value or level[key][name] == value, (key, name)
            assert all(n.startswith(PREFIX) for n in set(level[key]) - set(old)), key
        for name in set(extra) & orphans:
            orphans.discard(name)
        for name in set(extra) & set(current.namelist()):
            # Content-addressed buffers (e.g. reused UV streams) already exist.
            assert current.read(name) == extra.pop(name), name
        print(f'Writing level.SCNE plus {len(extra)} new buffers', flush=True)
        count = write_compatible(current, current, pending, {'level.SCNE': dump_native(doc), **extra}, orphans)
        print('Checking archive CRC, resource closure and exact preservation', flush=True)
        with zipfile.ZipFile(pending) as final:
            assert final.testzip() is None
            names = final.namelist()
            kept = [n for n in current.namelist() if n not in orphans]
            assert names[:len(kept)] == kept and len(set(names)) == count
            assert set(names[len(kept):]) == set(extra)
            assert load_scne(final.read('level.SCNE')) == doc
            for name in [*level['Model']]:
                if name.startswith(PREFIX):
                    for binary in binaries(level['Model'][name]):
                        present(final, binary)
            identical = 0
            for old in current.infolist():
                if old.filename == 'level.SCNE' or old.filename in orphans:
                    continue
                new = final.getinfo(old.filename)
                assert (old.CRC, old.file_size, old.compress_size) == (new.CRC, new.file_size, new.compress_size)
                assert raw_record_hash(current, old) == raw_record_hash(final, new), old.filename
                identical += 1
            assert final.read('PostEffect.FxTweakables') == current.read('PostEffect.FxTweakables')
    scene.update(source_iff_sha256=original_hash, unchanged_compressed_entries=identical,
                 added_archive_members=len(extra), removed_previous_n4_members=len(orphans), changed_archive_members=['level.SCNE'], archive_crc_verified=True)
    report['revision'] = report['revision'].split('+')[0] + '+' + report['night_lighting']['revision'] + '+' + REVISION
    report['night_scene'] = scene
    report['game_tested'] = False
    report['game_visibility'] = 'pending'
    report['source_feedback'] = 'N3 night sky confirmed in game (moon, stars, dark glass). User asks for a complete, good-looking lit night scene at Claude\'s discretion.'
    report['changes'] = [c for c in report['changes'] if not c.startswith('Night scene')]
    report['changes'].append(f'Night scene {REVISION}: add emissive overlays (floodlight lenses, A sign, Chilis letters/strips, logos, boots sign), fence LED strips, two floodlight spots, a Chilis spill spot and three fence line lights; no existing content changed.')
    report.update(output_bytes=pending.stat().st_size, output_sha256=digest(pending),
                  archive_crc_verified=True, archive_entries=count)
    os.replace(pending, output)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    (ROOT / 'validation/night-scene-current.json').write_text(json.dumps({
        **scene, 'output_sha256': report['output_sha256'], 'output_bytes': report['output_bytes'],
        'game_tested': False, 'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())},
        ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: report[k] for k in ('revision', 'output_bytes', 'output_sha256')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
