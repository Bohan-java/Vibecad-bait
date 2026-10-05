"""Repair only the Rucker copy's two glass DDS assets; preserve other ZIP records.

No paths in the earlier arena_020 project or the live game are written.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import zipfile

import numpy as np
from PIL import Image, ImageFilter

WORK = Path(__file__).resolve().parent
COURT = WORK.parent
ACTIVE = COURT / "arena_blacktop_ext.iff"
BACKUP = WORK / "原始备份" / "arena_blacktop_ext.iff"
CANDIDATE = WORK / "待验证" / "arena_blacktop_ext.iff"
ASSETS = WORK / "修复贴图"
SOURCE_SHA = "458da14e8bdfd35b72cd9b9c47d691b51198a20561c17391800bd054fdab4cb1"
ALBEDO = "albedomapbc3.8195d23caeafe771.dds"
ROUGH = "glass_shader_mat_roughness.4d555f64a227659e.dds"
MASK = "glass_shader_mat_globalalpha.d6e94917d9bd7cc5.dds"


def log(message):
    print(message, flush=True)


def sha_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def scene(data):
    return json.loads(b"{" + data.strip() + b"}")


def encode_mips(im, original_header, fourcc):
    """Keep the verified DDS header, rebuild every ordinary linear BC mip."""
    assert original_header[:4] == b"DDS "
    assert original_header[84:88] == fourcc.encode("ascii")
    levels = struct.unpack_from("<I", original_header, 28)[0]
    chunks = []
    sizes = []
    current = im
    for mip in range(levels):
        w, h = current.size
        # BC encoders operate on 4 by 4 blocks even for the final 2/1 texel mips.
        array = np.asarray(current)
        array = np.pad(array, ((0, (-h) % 4), (0, (-w) % 4), (0, 0)), mode="edge")
        padded = Image.fromarray(array)
        output = io.BytesIO()
        padded.save(output, format="DDS", pixel_format=fourcc)
        payload = output.getvalue()[128:]
        expected = ((w + 3) // 4) * ((h + 3) // 4) * (16 if fourcc == "DXT5" else 8)
        assert len(payload) == expected, (mip, len(payload), expected)
        chunks.append(payload)
        sizes.append({"mip": mip, "width": w, "height": h, "bytes": len(payload)})
        current = current.resize((max(1, w // 2), max(1, h // 2)), Image.Resampling.BOX)
    return original_header + b"".join(chunks), sizes


def create_assets(source):
    ASSETS.mkdir(parents=True, exist_ok=True)
    mask_image = Image.open(io.BytesIO(source.read(MASK))).convert("RGBA").getchannel("A")
    mask = np.asarray(mask_image, dtype=np.float32) / 255.0
    # Use the original UV paint mask: clear glass, opaque white target/border.
    color = np.rint(218 + 27 * mask).astype(np.uint8)
    alpha = np.rint(10 + 245 * mask).astype(np.uint8)
    albedo = Image.fromarray(np.stack((color, color, color, alpha), axis=2))
    rough = np.rint(18 + 98 * mask).astype(np.uint8)
    roughness = Image.fromarray(np.stack((rough, rough, rough), axis=2))
    replacements = {}
    details = {}
    for name, im, fourcc in [(ALBEDO, albedo, "DXT5"), (ROUGH, roughness, "DXT1")]:
        old = source.read(name)
        new, mips = encode_mips(im, old[:128], fourcc)
        assert len(new) == len(old)
        decoded = Image.open(io.BytesIO(new)).convert("RGBA")
        decoded.load()
        assert decoded.size == (1024, 1024)
        (ASSETS / name).write_bytes(new)
        decoded.save(ASSETS / (name + ".png"))
        replacements[name] = new
        details[name] = {"format": fourcc, "mips": mips,
                         "old_sha256": hashlib.sha256(old).hexdigest(),
                         "new_sha256": hashlib.sha256(new).hexdigest()}
    decoded = np.asarray(Image.open(io.BytesIO(replacements[ALBEDO])).convert("RGBA"))
    # Exclude mixed BC blocks along paint edges when measuring glass/paint opacity.
    glass = np.asarray(mask_image.filter(ImageFilter.MaxFilter(9))) < 3
    paint = np.asarray(mask_image.filter(ImageFilter.MinFilter(9))) > 252
    assert np.quantile(decoded[:, :, 3][glass], 0.99) <= 15
    assert np.quantile(decoded[:, :, 3][paint], 0.01) >= 245
    # A neutral glass texture cannot contain the source's saturated color noise.
    spread = decoded[:, :, :3].max(axis=2).astype(int) - decoded[:, :, :3].min(axis=2).astype(int)
    assert spread.max() <= 9
    details["glass_alpha_median"] = float(np.median(decoded[:, :, 3][glass]) / 255)
    details["paint_alpha_median"] = float(np.median(decoded[:, :, 3][paint]) / 255)
    details["max_rgb_channel_spread"] = int(spread.max())
    return replacements, details


def copy_bytes(src, dst, size):
    remaining = size
    while remaining:
        data = src.read(min(8 * 1024 * 1024, remaining))
        if not data:
            raise EOFError("Unexpected end of ZIP local record")
        dst.write(data)
        remaining -= len(data)


def repack(source_path, destination, replacements):
    """Copy untouched compressed local records without decompression/recompression."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source_path) as src, source_path.open("rb") as raw, \
            zipfile.ZipFile(destination, "w", allowZip64=True) as dst:
        infos = src.infolist()
        assert [i.header_offset for i in infos] == sorted(i.header_offset for i in infos)
        assert infos[0].header_offset == 0
        assert len({i.filename for i in infos}) == len(infos)
        for idx, original in enumerate(infos):
            info = copy.copy(original)
            if info.filename in replacements:
                dst.writestr(info, replacements[info.filename])
            else:
                end = infos[idx + 1].header_offset if idx + 1 < len(infos) else src.start_dir
                raw.seek(original.header_offset)
                dst.fp.seek(dst.start_dir)
                info.header_offset = dst.fp.tell()
                copy_bytes(raw, dst.fp, end - original.header_offset)
                dst.filelist.append(info)
                dst.NameToInfo[info.filename] = info
                dst.start_dir = dst.fp.tell()
                dst._didModify = True
            if idx and idx % 4000 == 0:
                log(f"Copied {idx} / {len(infos)} archive records")
        dst.comment = src.comment


def validate(source_path, result_path, replacements):
    changes = []
    with zipfile.ZipFile(source_path) as src, zipfile.ZipFile(result_path) as dst:
        assert src.namelist() == dst.namelist(), "ZIP entry order/name mismatch"
        assert dst.comment == src.comment
        for idx, name in enumerate(src.namelist()):
            # Reading both sides verifies each entry's decompression and ZIP CRC.
            old, new = src.read(name), dst.read(name)
            if old != new:
                changes.append(name)
                assert name in replacements and new == replacements[name]
            if idx and idx % 4000 == 0:
                log(f"Verified {idx} / {len(src.namelist())} entries")
        assert set(changes) == {ALBEDO, ROUGH}
        basket = scene(dst.read("baskets.SCNE"))["baskets"]
        glass = basket["Material"]["basket_stanchiont_outdoor:glass_shader_mat"]
        assert glass["Parameter"]["AlphaStyle"] == "TRANSLUCENT"
        assert basket["Object"]["MAIN"]["Attribute"]["VC_BasketType"] == "PARK_NORMAL"
        return {"status": "PASS", "entry_count": len(src.namelist()),
                "changed_entries": changes, "all_other_entry_bytes_identical": True,
                "both_archives_crc_checked": True, "all_scenes_geometry_collision_unchanged": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="After validation, replace the workspace copy only")
    args = parser.parse_args()
    assert ACTIVE.resolve().is_relative_to(COURT.resolve())
    assert BACKUP.resolve().is_relative_to(WORK.resolve())
    assert CANDIDATE.resolve().is_relative_to(WORK.resolve())
    source_path = BACKUP if BACKUP.exists() else ACTIVE
    log("Checking the Rucker source fingerprint")
    assert sha_file(source_path) == SOURCE_SHA, "Unexpected Rucker source; refusing to patch"
    if not BACKUP.exists():
        BACKUP.parent.mkdir(parents=True, exist_ok=True)
        log("Saving the original Rucker archive")
        shutil.copy2(source_path, BACKUP)
        assert sha_file(BACKUP) == SOURCE_SHA
    with zipfile.ZipFile(BACKUP) as src:
        replacements, texture_report = create_assets(src)
    log("Glass textures encoded; rebuilding the Rucker archive")
    repack(BACKUP, CANDIDATE, replacements)
    log("Verifying all archive entries and unchanged game resources")
    report = validate(BACKUP, CANDIDATE, replacements)
    report.update({"source_sha256": SOURCE_SHA, "result_sha256": sha_file(CANDIDATE),
                   "source_path": str(BACKUP), "textures": texture_report,
                   "live_game_modified": False, "in_game_verified": False})
    if args.apply:
        # This checks for concurrent user edits before replacing the working copy.
        assert sha_file(ACTIVE) == SOURCE_SHA, "Workspace file changed during repair"
        os.replace(CANDIDATE, ACTIVE)
        report["result_path"] = str(ACTIVE)
    else:
        report["result_path"] = str(CANDIDATE)
    (WORK / "验证报告.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(json.dumps({k: report[k] for k in ("status", "changed_entries", "result_path", "result_sha256")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
