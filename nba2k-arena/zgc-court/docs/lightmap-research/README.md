# 静态 lightmap 研究交付

先读 **[REPORT_ZH.md](REPORT_ZH.md)**。该目录包含研究报告和可执行诊断生成器；没有游戏包、真实 shader 反编译结果或已验收的游戏补丁。

## 文件与依赖

Python 3.10+，仅使用标准库。`lightmap_diag.py` 与 `codec_stdlib.py` 必须放在同一目录。目录位置保持为：

```text
nba2k-arena/zgc-court/docs/lightmap-research/
```

所有读入文件必须位于项目的 `nba2k-arena/` 内；所有输出必须是本研究目录下的**全新子目录**。工具不遍历游戏安装目录，不覆盖输入，不写 IFF，不修改 tools/source/output/bake，不执行现有构建脚本。真正的 `.iff` 必须已在本地；LFS 指针会报错退出。

## 1. 只读清点当前包

以下命令从 `nba2k-arena/zgc-court/` 执行：

```powershell
python -B docs/lightmap-research/lightmap_diag.py inventory --iff output/arena_700_int.iff --extract-evidence --out runs/current-inventory
```

`--out` 相对于 **docs/lightmap-research/**，不要再次把该前缀写进去。重复运行请改用新的输出目录名称。

主要结果：

| 文件 | 用途 |
|---|---|
| `inventory.json` | 真正的同名纹理统计、地面候选、输入 SCNE 与中央目录指纹、native round-trip 结果。 |
| `object_texture_descriptors.json` | 所有与对象或模型同名的纹理描述。 |
| `texture_samples.json` | 按格式轮流抽样、去重资源的 DDS 头与 BC4 标量统计。默认最多 24 份，`--samples` 可选 1–128。 |
| `bc4_nonemissive_donor_candidates.json` | 最多 48 个 64×64 非发光绑定候选、材质、UV7、Technique/VS 输入信息；候选还需后续严格验证。 |
| `rgb_object_texture_candidates.json` | 同名非 BC4 资源候选；其中可能有非光照贴图，不能直接称为 RGB lightmap。 |
| `material_resource_slot_index.json` | 全部材质资源槽名称及其使用者。 |
| `selected_materials.json` / `selected_effects.json` | 杯子、路灯和壁灯的定义及相关 Effect。 |
| `binary_reference_manifest.json` | 解析到的资源、缺失项、预算跳过项。 |
| `resources/` | `--extract-evidence` 导出的预算内原始代码资源字节；单份上限 8 MiB、合计 24 MiB。没有反编译或未知压缩解码。 |

对项目内已有室内包也可执行 inventory，例如：

```powershell
python -B docs/lightmap-research/lightmap_diag.py inventory --iff ../donor/original/arena_020_int_original.iff --out runs/indoor-inventory
```

该命令不代表本轮已经取得或分析了室内包。该路径只有 LFS 指针时会被拒绝；无包内的外部共享资源会被标记为未解析。其他 SCNE 可通过 `--scene level_floor.SCNE` 等显式指定，但 `plan` 限定为 `level.SCNE`。

## 2. 优先执行彩色路线：同位置开／关

```powershell
python -B docs/lightmap-research/lightmap_diag.py plan --iff output/arena_700_int.iff --mode emission --emission-scale 0 --out runs/emission-off
python -B docs/lightmap-research/lightmap_diag.py plan --iff output/arena_700_int.iff --mode emission --out runs/emission-on
```

两份方案使用同一位置、同一几何、同一彩色图案和同一原生 BC4，仅 emission 强度不同。默认测试范围世界 X −200～200 cm、Z 500～900 cm。四面强度为 0/30/300/3000；可以用 `--emission-scale` 整体调小。

生成的是小型资源包目录：

```text
runs/emission-on/
  additions.json     # 只含新增 Texture/Material/Model/Object 键
  manifest.json      # 基线、范围、资源 hash、逐面含义与限制
  members/*.dds      # 标准 DDS；没有真实 TLD 文件
  members/*.bin      # 小型原生静态平面缓冲
```

**这些目录不能直接作为 arena_700_int.iff 放进游戏。** 工具有意不生成、复制或安装整包。

地面自动识别有歧义时，用 inventory 返回的对象键指定 `--ground-object "完整对象键"`。不要沿用旧报告的 part 编号。也可使用 `--x-cm` / `--z-cm` 调整中心，工具仍会检查范围和水平面。

默认 `--offset-cm 0.01` 是 0.1 mm 的几何抬高，尚未验证对球员指示器安全。没有 depth-bias 修改。出现 UI 遮挡／闪烁就停止该覆盖层方案。

## 3. BC4 路线：先选择配对原生 donor

从清点结果选择一个同时具备下列条件的候选：64×64 BC4、48 字节 UserData、静态非发光不透明材质、Lightmap GBuffer shader、匹配的对象与材质关系。候选列表不保证每项都会通过 `plan`；脚本会继续检查并拒绝不适用项。

下方 PowerShell 变量需填入 **inventory 实际列出的配对值**：

```powershell
$lmObject = "从清点结果复制的原生对象完整键"
$lmMaterial = "该对象实际使用的非发光材质完整键"

python -B docs/lightmap-research/lightmap_diag.py plan --iff output/arena_700_int.iff --mode bound-control --lm-object "$lmObject" --lm-material "$lmMaterial" --out runs/bc4-bound
python -B docs/lightmap-research/lightmap_diag.py plan --iff output/arena_700_int.iff --mode bc4 --lm-object "$lmObject" --lm-material "$lmMaterial" --out runs/bc4-pattern
python -B docs/lightmap-research/lightmap_diag.py plan --iff output/arena_700_int.iff --mode bc4 --invert-bc4 --lm-object "$lmObject" --lm-material "$lmMaterial" --out runs/bc4-inverted
python -B docs/lightmap-research/lightmap_diag.py plan --iff output/arena_700_int.iff --mode uv7-flip --lm-object "$lmObject" --lm-material "$lmMaterial" --out runs/bc4-uv7-flip
```

观察意义见报告 §7。关键是同位置的正／反变化及 UV7 镜像，单独出现暗色方块还不够。

Min/Max 使用独立的一对：

```powershell
python -B docs/lightmap-research/lightmap_diag.py plan --iff output/arena_700_int.iff --mode minmax --minmax-native --lm-object "$lmObject" --lm-material "$lmMaterial" --out runs/minmax-native
python -B docs/lightmap-research/lightmap_diag.py plan --iff output/arena_700_int.iff --mode minmax --lm-object "$lmObject" --lm-material "$lmMaterial" --out runs/minmax-cases
```

原生 Twiddled/CompressionMethod 默认保留。仅在单独排查描述符时，再给同一命令加 `--metadata plain` 并更换输出目录；不要混入其他变量。该开关不实现 TLD 33 解码。

## 4. 可选：合成小型 SCNE 与资源，不输出 IFF

```powershell
python -B docs/lightmap-research/lightmap_diag.py compose --iff output/arena_700_int.iff --bundle runs/emission-on --out runs/emission-on-composed
```

此命令输出新的 `level.SCNE`、小 DDS/BIN 和检查收据，只写研究目录。它核验输入身份、资源哈希、键冲突与精确反向恢复；输入 IFF 保持原状。

后续测试封装由项目现有封装阶段处理。本模块提供 `build_replacements(archive, bundle_path)`，返回唯一 `level.SCNE` 的替换内容及新增资源。应对**现行夜景包**保留所有未变成员并使用已检查的 `native_archive.write_compatible` 契约；不要执行整条旧重建流水线，避免清理实验对象或重置探针。

本交付没有调用封装器，也没有提供自动安装、推送或整包输出命令。禁止以 ZIP append 写入重复 `level.SCNE`。

撤销首选恢复测试前的原输入包。`reverse_document` 提供严格的内存逆操作；只接受恰好原样的新增条目，并验证撤销结果与 baseline SCNE 逐字节一致。后续清理资源应遵循 manifest 的精确名字，不能删宽泛前缀。

## 5. 重跑合成测试

```powershell
python -B -m unittest discover -s docs/lightmap-research -p "test_*.py" -v
```

本轮 35 项通过，日志在 `evidence/synthetic_tests.txt`。测试只使用人工场景和明显标注的 shader 占位数据；临时文件在本目录 `evidence/` 下创建并自动清理，没有真实 IFF。

本工具不声称已经解码 BC4 的光照语义、Min/Max 消费公式、Twiddled 排列或 CompressionMethod 33。它将这些未知项拆成可独立判定的实验，同时保留已工作的原生 RGB emission 入口。
