"""Checked patch that (re)applies the night scene (night_scene) to the current package.

The current package must already carry the night base (night_lighting). Only
level.SCNE changes; new buffers and probe data are appended; earlier night-scene
members are dropped; every other record is copied byte-for-byte and verified.
"""
from pathlib import Path
import json
import os
import time
import zipfile
from iff_codec import load_scne
from native_archive import write_compatible
from night_lighting import is_night
from night_scene import apply_scene, strip_scene, REVISION, PREFIX, PROBE_DATA_KEY, FOLIAGE_PALETTE
from patch_half_court_current import digest, raw_record_hash
from repair_iff import dump_native, binaries, present

ROOT = Path(__file__).resolve().parents[1]
R13_SHA256 = '9e9cd0f73b1c6c2baf6d9f45cb472ac110282e7d161c20ce9d373fd968532622'
R13 = ROOT.parents[1] / '.git/lfs/objects' / R13_SHA256[:2] / R13_SHA256[2:4] / R13_SHA256


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
        with zipfile.ZipFile(R13) as day:
            base_level = load_scne(day.read('level.SCNE'))['level']
            base_baskets = day.read('baskets.SCNE')
        from repair_iff import binaries
        from night_scene import _texture_archive_name
        others = set()
        for name in current.namelist():
            if name.endswith('.SCNE') and name != 'level.SCNE':
                try:
                    others |= {_texture_archive_name(b) for b in binaries(load_scne(current.read(name)))}
                except Exception:
                    pass                                   # binary-format scenes carry no zgc members
        orphans = strip_scene(level, base_level, others)
        before = {k: dict(level[k]) for k in ('Light', 'Material', 'Model', 'Object', 'Texture')}
        extra = {}
        scene = apply_scene(level, current, extra)
        import backboard_glass
        baskets_raw, scene['backboard_glass'] = backboard_glass.build(base_baskets, current, extra)
        replaced = {'level.SCNE': dump_native(doc)}
        if baskets_raw != current.read('baskets.SCNE'):
            replaced['baskets.SCNE'] = baskets_raw
        for key, old in before.items():
            for name, value in old.items():
                if key == 'Texture' and name == 'LIGHT_BRICK_MAP_GRID_RUNTIME_DATA':
                    continue   # N23 RTL variant B points it at a patched copy
                if key == 'Texture' and PROBE_DATA_KEY.fullmatch(name):
                    continue   # probe gain replaces these descriptors on purpose
                if key == 'Texture' and name.endswith('ball_test_basketball/texture/ball_official_color.tga'):
                    continue   # N30 blue game ball (ball_skin.py)
                if key == 'Material' and name in FOLIAGE_PALETTE:
                    continue   # N39 foliage palette (night_scene.FOLIAGE_PALETTE)
                if key == 'Light' and name == 'Sun':
                    continue   # N22 key light (night_scene.SUN_KEY)
                if key == 'Object' and name == 'TIME_OF_DAY':
                    continue   # N23 moonlight (night_scene.MOON_KEY)
                assert level[key][name] is value or level[key][name] == value, (key, name)
            assert all(n.startswith(PREFIX) for n in set(level[key]) - set(old)), key
        for name in set(extra) & orphans:
            orphans.discard(name)
        for name in set(extra) & set(current.namelist()):
            # Content-addressed buffers (e.g. reused UV streams) already exist.
            assert current.read(name) == extra.pop(name), name
        print(f'Writing level.SCNE plus {len(extra)} new buffers', flush=True)
        count = write_compatible(current, current, pending, {**replaced, **extra}, orphans)
        print('Checking archive CRC, resource closure and exact preservation', flush=True)
        with zipfile.ZipFile(pending) as final:
            assert final.testzip() is None
            names = final.namelist()
            kept = [n for n in current.namelist() if n not in orphans]
            assert names[:len(kept)] == kept and len(set(names)) == count
            assert set(names[len(kept):]) == set(extra)
            assert load_scne(final.read('level.SCNE')) == doc
            assert final.read('baskets.SCNE') == baskets_raw
            for section in ('Model', 'Texture'):
                for name, value in level[section].items():
                    if name.startswith(PREFIX):
                        for binary in binaries(value):
                            present(final, binary)
            identical = 0
            for old in current.infolist():
                if old.filename in ('level.SCNE', 'baskets.SCNE') or old.filename in orphans:
                    continue
                new = final.getinfo(old.filename)
                assert (old.CRC, old.file_size, old.compress_size) == (new.CRC, new.file_size, new.compress_size)
                assert raw_record_hash(current, old) == raw_record_hash(final, new), old.filename
                identical += 1
            assert final.read('PostEffect.FxTweakables') == current.read('PostEffect.FxTweakables')
    scene.update(source_iff_sha256=original_hash, unchanged_compressed_entries=identical,
                 added_archive_members=len(extra), removed_previous_scene_members=len(orphans), changed_archive_members=['level.SCNE', 'baskets.SCNE'], archive_crc_verified=True)
    report['revision'] = report['revision'].split('+')[0] + '+' + report['night_lighting']['revision'] + '+' + REVISION
    report['night_scene'] = scene
    report['game_tested'] = False
    report['game_visibility'] = 'pending'
    report['source_feedback'] = 'LDIAG1 confirmed in game: same-name-texture-bound lamp emitters glow with bloom and probe gain lights the court and players; build the full night scene with these native paths.'
    report['changes'] = [c for c in report['changes'] if not c.startswith('Night scene')]
    report['changes'].append(f'Night scene {REVISION}: native lightmap-bound emitters (floodlight lenses, A signs, Chilis letters/strips/logos, boots sign, fence LED strips) and scalar baked probe light over the court; no added lights; no existing model or material changed.')
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
