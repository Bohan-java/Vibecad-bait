"""Fast, checked SCNE-only correction of the current package's selected end."""
from pathlib import Path
import copy
import hashlib
import json
import os
import time
import zipfile
from iff_codec import load_scne
from native_archive import write_compatible
from half_court_orientation import apply_orientation, update_report, orientation_degrees

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def raw_record_hash(archive, info):
    # ZIP local headers and their exact compressed payload are the preservation
    # unit. Central directory offsets necessarily change after level.SCNE.
    archive.fp.seek(info.header_offset)
    header = archive.fp.read(30)
    name_length = int.from_bytes(header[26:28], 'little')
    extra_length = int.from_bytes(header[28:30], 'little')
    remaining = name_length + extra_length + info.compress_size
    hashed = hashlib.sha256(header)
    while remaining:
        chunk = archive.fp.read(min(8 * 1024 * 1024, remaining))
        assert chunk
        hashed.update(chunk)
        remaining -= len(chunk)
    return hashed.hexdigest()


def main():
    output = ROOT / 'output/arena_700_int.iff'
    report_path = ROOT / 'validation/iff-current.json'
    report = json.loads(report_path.read_text(encoding='utf8'))
    original_hash = digest(output)
    assert original_hash == report['output_sha256'], 'Current output and report disagree'
    staging = ROOT / '.build-staging'
    staging.mkdir(exist_ok=True)
    pending = staging / 'half-court.pending'
    with zipfile.ZipFile(output) as current:
        doc = load_scne(current.read('level.SCNE'))
        level = doc['level']
        assert orientation_degrees(level) == 0, 'Already corrected; do not republish'
        before = copy.deepcopy(doc)
        orientation = apply_orientation(level)
        after = copy.deepcopy(level)
        apply_orientation(level)
        assert level == after, 'Rotation must be idempotent'
        raw = (json.dumps(doc, ensure_ascii=True, indent='\t')[1:-1].strip() + '\n').encode('utf8')
        print('Writing SCNE-only half-court correction; retaining original until validation passes', flush=True)
        count = write_compatible(current, current, pending, {'level.SCNE': raw}, set())
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
        # All scene dictionaries except instance transforms/role positions must
        # remain byte-semantically identical, including local culling bounds.
        for key in before['level']:
            if key != 'Object':
                assert before['level'][key] == level[key], key
    from r12_seating import audit_archive
    seats = audit_archive(pending)
    assert seats['status'] == 'passed'
    orientation.update(unchanged_compressed_entries=identical, changed_archive_members=['level.SCNE'],
                       source_iff_sha256=original_hash, archive_crc_verified=True,
                       chair_role_alignment_verified=True, source_geometry_and_local_bounds_unchanged=True)
    update_report(report, level, orientation)
    report.update(output_bytes=pending.stat().st_size, output_sha256=digest(pending),
                  archive_crc_verified=True, archive_entries=count)
    report['after_d3d']['inherited_validation'] = 'All DDS, shader and material bytes are unchanged from the previously checked R12 package.'
    os.replace(pending, output)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    (ROOT / 'validation/half-court-current.json').write_text(json.dumps({
        **orientation, 'output_sha256': report['output_sha256'], 'output_bytes': report['output_bytes'],
        'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: report[k] for k in ('revision', 'output_bytes', 'output_sha256')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
