"""Extract the historically visible slot-700 pair without rebuilding either IFF.

Only reads Git objects and writes output/recovery_base. No game-directory writes,
legacy build calls, or file digests. Byte comparisons protect the extracted pair.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
REVISION = "fde9489"
ARCHIVED = "nba2k-arena/output/checkpoint1/line_fix"
NAMES = ("arena_700_int.iff", "arena_700_int_floor.iff")
OUT = ROOT / "output/recovery_base"


def repository_pair():
    return {
        name: subprocess.run(
            ["git", "show", f"{REVISION}:{ARCHIVED}/{name}"],
            cwd=REPO, check=True, capture_output=True,
        ).stdout
        for name in NAMES
    }


def main():
    pair = repository_pair()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in pair.items():
        with zipfile.ZipFile(io.BytesIO(data)) as source:
            members = source.namelist()
            if not members or len(members) != len(set(members)):
                raise ValueError(f"Invalid archived member list: {name}")
        (OUT / name).write_bytes(data)
        if (OUT / name).read_bytes() != data:
            raise ValueError(f"Extracted file differs from repository: {name}")

    report = {
        "status": "HISTORICAL_VISIBLE_BASE_RESTORED_CURRENT_GAME_CONFIRMATION_PENDING",
        "source_revision": REVISION,
        "source_directory": ARCHIVED,
        "slot": "700 tutorial court",
        "source_is_011": False,
        "iff_rebuilt_or_repacked": False,
        "extracted_files_equal_repository_bytes": True,
        "changed_resources": [],
        "historical_visual_evidence": "evidence/user_game_screenshot_checkpoint1_REJECTED.png",
        "historical_limitations": [
            "Indoor enclosure, cyan border, dark palms and glossy floor remain.",
            "The screenshot establishes visibility, not a full gameplay test.",
        ],
        "current_game_verified": False,
        "files": {name: {"bytes": len(data)} for name, data in pair.items()},
    }
    (OUT / "status.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (OUT / "README.txt").write_text(
        "仓库历史可见基底：Checkpoint 1（fde9489）\n\n"
        "两份 IFF 直接从 repo 历史提取，内部没有重打包或修改。\n"
        "仍使用 700 新手教学场地，不是 011 球队场地或 blacktop 街球。\n"
        "完全退出游戏后，备份目前使用的 700 主文件和地板文件，\n"
        "再用本包同名两份 IFF 一起替换到原来使用的 700 位置。\n"
        "只解开最外层 ZIP，不要解开 IFF。\n\n"
        "预期看到：室内屋顶/悬挂屏、青色边框，地板和人物可见。\n"
        "这是恢复开发起点，仍有旧版视觉问题，不是完成的海边球场。\n"
        "本机不能运行目标游戏，本次替换后的显示与移动投篮仍待实际确认。\n"
        "后续在此基底逐项迁回资产，不叠加 R7 系列失败场景。\n",
        encoding="utf-8",
    )
    package = OUT / "repo_checkpoint1_restore_700.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name in (*NAMES, "README.txt", "status.json"):
            target.write(OUT / name, name)
    with zipfile.ZipFile(package) as result:
        for name, data in pair.items():
            if result.read(name) != data:
                raise ValueError(f"Packaged IFF differs from repository: {name}")
    print(json.dumps({"package": str(package), "bytes": package.stat().st_size,
                      "files": report["files"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
