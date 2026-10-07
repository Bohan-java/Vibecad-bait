# 使用说明：单灯研究诊断

先读 [REPORT_ZH.md](REPORT_ZH.md) 第0、7、9节。所有灯光和索引实验均未经游戏验证；`word64-2` 是未知字段的受控扰动，可能无效或引起崩溃。交付物没有完整 IFF，也没有使用假场景代替当前夜景 SCNE。

## 1. 文件与环境

将交付 ZIP 解压到项目的 `nba2k-arena/zgc-court/`，得到 `docs/realtime-light-research/`。已有 `tools/`、`source/`、`output/`、`bake/` 均无需修改。

需要 Python 3.10 或更新版本，只使用标准库，不安装依赖。以下命令中的工作目录是 `zgc-court/`；Windows 上可将 `python` 改为实际的 `py -3`。`-S` 用于验证不依赖 site-packages。

把用户原始研究包复制到 `docs/realtime-light-research/input/realtime_light_research.zip`。输入 IFF 必须是项目工作区中**已经完成现有夜景构建**的干净副本，Light 中仅有 Sun。下面以 `output/arena_700_int.iff` 为示例，实际文件名不同时只替换参数；绝对不要指向游戏安装目录。

本次附件只有 ours 的 light subset，没有当前完整 `level.SCNE`。生成器会拒绝把 subset 当作完整场景。

## 2. 复现研究与离线测试

```bash
python -S docs/realtime-light-research/tools/test_diagnostic.py --bundle docs/realtime-light-research/input/realtime_light_research.zip
```

本轮基于原始附件通过 26 项测试；有真实缓冲测试，也有合成 SCNE/小型 archive 测试。通过测试不代表游戏效果成功。

```bash
python -S docs/realtime-light-research/tools/analyze_bundle.py --bundle docs/realtime-light-research/input/realtime_light_research.zip --out docs/realtime-light-research/reproduced-local
```

输出目录必须不存在。可与交付的 `evidence/reproduced/` 对照。`rare_record_cells.csv` 为840条特殊目录记录，世界坐标属于已标注的推断。

## 3. 首先生成 A：仅追加一盏聚光灯

```bash
python -S docs/realtime-light-research/tools/generate_diagnostic.py generate --workspace . --bundle docs/realtime-light-research/input/realtime_light_research.zip --input-iff output/arena_700_int.iff --experiment append --out docs/realtime-light-research/generated/A-append
```

灯为 `zgc_rtl:center_spot`，世界坐标 `[0,800,0]` cm，向下，冷白色，Intensity=363000000，Near/Far=25/1600，CastsShadows=1，IgnoreDynamicCasters=0。

生成结果仅有：

```text
generated/A-append/
  replacements/level.SCNE       完整当前场景的源文本保留式替换件
  manifest.json                基线哈希、灯顺序、改动与保护信息
  payload.zip                  上述文件的传输包；不能改名为 arena IFF
```

原 IFF 只读，所有其他成员仍由现有封装器从基线传递。

## 4. C：零重建顺序实验

```bash
python -S docs/realtime-light-research/tools/generate_diagnostic.py generate --workspace . --bundle docs/realtime-light-research/input/realtime_light_research.zip --input-iff output/arena_700_int.iff --experiment prepend --out docs/realtime-light-research/generated/C-prepend
```

与 A 的区别是把新灯放到 Sun 前面。原 grid 与所有标记不变。它测试可能存在的槽位0/字典顺序依赖，没有声称恢复了实际历史灯身份。

封装时必须采用完整 replacement SCNE；不要将 `Light` 用 `dict.update()` 合入旧场景，否则前置顺序可能丢失。

## 5. A′/B：资源别名控制 + 一个未知 word 的扰动

A′先新增原 grid 的完整副本，只改现有 Texture 的 Binary 引用：

```bash
python -S docs/realtime-light-research/tools/generate_diagnostic.py generate --workspace . --bundle docs/realtime-light-research/input/realtime_light_research.zip --input-iff output/arena_700_int.iff --experiment alias --out docs/realtime-light-research/generated/A-alias
```

B与A′使用同一资源名、相同SCNE，只将新 raw grid 的 byte256 从01改为02：

```bash
python -S docs/realtime-light-research/tools/generate_diagnostic.py generate --workspace . --bundle docs/realtime-light-research/input/realtime_light_research.zip --input-iff output/arena_700_int.iff --experiment word64-2 --ack-unverified-word64 --out docs/realtime-light-research/generated/B-word64-2
```

**这个开关确认的是愿意进行未验证的字节实验，不代表承认它已是灯位掩码。** word64真实含义未知；格式错误可能导致无效/异常/崩溃。仅适用于报告的精确grid SHA。禁止套用到其他场馆。

这两个输出比A多出 `members/0000.bin`，manifest 将它映射为 IFF 成员 `zgc_rtl:light_brick_diag.bin`；SCNE引用 `zgc_rtl:light_brick_diag.gz`。磁盘文件名刻意不含冒号。

A′/B每次完全退出再启动，独立从干净基线生成和封装，不能叠加，不能依赖热重载。没有观察到任何效果时，无法证明新增资源已经被引擎消费。

## 6. 备用 movable 与验收对照

仅在必要时测试独立的 movable 变体：

```bash
python -S docs/realtime-light-research/tools/generate_diagnostic.py generate --workspace . --bundle docs/realtime-light-research/input/realtime_light_research.zip --input-iff output/arena_700_int.iff --experiment movable --out docs/realtime-light-research/generated/D-movable
```

它相对A只改变新灯 `VC_IsMovable=1`，完全不动 grid。

出现直接光之后，针对**同一个有效 experiment**分别追加 `--casts-shadows 0` 和 `--intensity 0`，输出到不同的新目录。以A有效为例：

```bash
python -S docs/realtime-light-research/tools/generate_diagnostic.py generate --workspace . --bundle docs/realtime-light-research/input/realtime_light_research.zip --input-iff output/arena_700_int.iff --experiment append --casts-shadows 0 --out docs/realtime-light-research/generated/A-no-shadow
python -S docs/realtime-light-research/tools/generate_diagnostic.py generate --workspace . --bundle docs/realtime-light-research/input/realtime_light_research.zip --input-iff output/arena_700_int.iff --experiment append --intensity 0 --out docs/realtime-light-research/generated/A-zero
```

若有效变体是B，上述对照也必须使用 `--experiment word64-2 --ack-unverified-word64`，以保留同一索引实验条件。

成功标准：中圈新光斑、球员进出光区受光变化、新灯产生跟随动作的地面投影；intensity0消除新增直接光，casts0只消除新增投影。只看到 Sun 原有影子或脚底接触阴影不够。失败后的变量选择见报告第9节。

## 7. 与现有封装流程衔接

生成器不调用 `native_archive.write_compatible`，不输出完整游戏包。现有封装器可导入以下桥接函数读取 extra：

```python
import sys
import zipfile
from pathlib import Path

root = Path.cwd()  # 当前目录必须是项目 zgc-court 工作区
sys.path.insert(0, str(root / 'docs/realtime-light-research/tools'))
from generate_diagnostic import load_extra

payload = root / 'docs/realtime-light-research/generated/A-append'
with zipfile.ZipFile(root / 'output/arena_700_int.iff', 'r') as current:
    extra = load_extra(payload, current)
    # extra 的键只有 level.SCNE，以及实验需要时新增的 zgc_rtl:...bin。
    # 将 extra 交给你们已验证的最后封装入口，其他成员保持原样。
    # 此处故意没有写完整 IFF；不要在这里再跑 apply_night 或重新导出 SCNE。
```

桥接函数校验当前SCNE、原grid、以及有记录时的PostEffect哈希，并校验payload各成员。所有变体对应同一个干净基线。不要先把A封装成基线再应用B。

现有项目的 Sun-only 断言保持不动；诊断在 night 构建之后应用。不要在最终封装之后再进行排序、规范化JSON或strip_scene。

## 8. 封装完成后的工作区回读

以下例子的 `docs/realtime-light-research/packed/A/arena_700_int.iff` 指由**你们现有封装流程**产生的工作区测试副本。工具只读取它，不复制到游戏目录：

```bash
python -S docs/realtime-light-research/tools/generate_diagnostic.py verify --workspace . --input-iff docs/realtime-light-research/packed/A/arena_700_int.iff --payload docs/realtime-light-research/generated/A-append
```

应检查 `payload_members_match=true`、`light_order_matches=true`。IFF输入模式会检查PostEffect SHA及原始成员CRC/长度清单；工具不会把这项检查称为“全部1.7GB字节哈希比较”。输出 `game_tested=false` 是正常的，工具没有运行游戏。

## 9. 只有导出的完整 SCNE 时

可以用 `--scene` 与 `--grid` 代替 `--input-iff`：

```bash
python -S docs/realtime-light-research/tools/generate_diagnostic.py generate --workspace . --bundle docs/realtime-light-research/input/realtime_light_research.zip --scene docs/realtime-light-research/input/current-level.SCNE --grid docs/realtime-light-research/input/light_brick_map_grid_runtime_data.4c92381972a58bee.bin --experiment append --out docs/realtime-light-research/generated/A-scne-only
```

SCNE必须完整且为本项目使用的JSON/片段JSON。这个模式缺少完整archive，因此无法取得PostEffect和未改成员清单；manifest会注明，封装者须另行检查。不要拿官方020或第三方SCNE冒充当前夜景输入。

## 10. 下一份数据

优先导出官方020引用的 `light_brick_map_grid_runtime_data.99205f5314268fd7.gz/.bin` 实际字节，声明有效长度390388；同时提供未经修改的原始700的完整Light顺序。具体范围见报告第10节。无需发送完整游戏安装目录或大型IFF。
