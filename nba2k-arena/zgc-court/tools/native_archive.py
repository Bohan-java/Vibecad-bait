"""Preserve donor local ZIP records and order while replacing selected entries.

Only ordinary seekable ZIP32 packages are supported. Unchanged compressed
records are copied byte-for-byte; Python's zip writer creates the final central
directory and compresses only changed/new entries. No external archive program.
"""
from __future__ import annotations
import copy
import shutil
import zipfile

def copy_record(source,target,info,end):
    if info.flag_bits & 1:raise ValueError('Encrypted native entry unsupported')
    cloned=copy.copy(info)
    target._writecheck(cloned)
    target._didModify=True
    target.fp.seek(target.start_dir)
    cloned.header_offset=target.fp.tell()
    source.fp.seek(info.header_offset)
    remaining=end-info.header_offset
    if remaining<30+info.compress_size:raise ValueError('Native ZIP record truncated')
    while remaining:
        block=source.fp.read(min(8*1024*1024,remaining))
        if not block:raise ValueError('Unexpected native archive end')
        target.fp.write(block);remaining-=len(block)
    target.start_dir=target.fp.tell()
    target.filelist.append(cloned);target.NameToInfo[cloned.filename]=cloned

def write_compatible(donor,current,output,replacements,omitted):
    """Use donor order/metadata, then current custom resources, then additions."""
    def records(z):
        ordered=sorted(z.infolist(),key=lambda i:i.header_offset)
        return {i.filename:(ordered[j+1].header_offset if j+1<len(ordered) else z.start_dir) for j,i in enumerate(ordered)}
    donor_end=records(donor);current_end=records(current);seen=set()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=False) as target:
        target.comment=donor.comment
        for info in donor.infolist():
            name=info.filename
            if name in omitted:continue
            if name in replacements:
                item=copy.copy(info);item.compress_type=zipfile.ZIP_DEFLATED
                target.writestr(item,replacements[name],compress_type=zipfile.ZIP_DEFLATED,compresslevel=6)
            elif name in current.NameToInfo:
                # Most entries are unchanged donor bytes; for a modified
                # existing entry without explicit replacement retain current.
                ci=current.getinfo(name)
                if (ci.CRC,ci.file_size)==(info.CRC,info.file_size):copy_record(donor,target,info,donor_end[name])
                else:
                    item=copy.copy(info);item.compress_type=zipfile.ZIP_DEFLATED
                    target.writestr(item,current.read(name),compress_type=zipfile.ZIP_DEFLATED,compresslevel=6)
            else:copy_record(donor,target,info,donor_end[name])
            seen.add(name)
        for info in current.infolist():
            name=info.filename
            if name in seen or name in omitted:continue
            data=replacements.get(name)
            if data is None:data=current.read(name)
            item=copy.copy(info);item.compress_type=zipfile.ZIP_DEFLATED
            target.writestr(item,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=6)
            seen.add(name)
        for name,data in replacements.items():
            if name in seen or name in omitted:continue
            info=zipfile.ZipInfo(name,(2014,1,1,17,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            target.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=6)
            seen.add(name)
    return len(seen)
