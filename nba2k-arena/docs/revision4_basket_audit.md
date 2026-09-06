# R4 篮架只读解码与外观改造依据

本次只增加解码、审阅数据与测试，不修改 R3 源码、IFF、碰撞、游戏文件或实时预览。原 donor 为 `donor/original/arena_020_int_original.iff`。完整逐资源、逐 Prim 清单由 `scripts/revision4_basket_decode.py` 生成，默认输出 `build/revision4/basket_audit.json`；加 `--include-geometry` 会带入实际解码的顶点、索引、UV 与玻璃权重。源 IFF 在读前、读后核对 SHA-256。

## 原图中的结构

已查看五张原图 `textures/source/references/arena_reference_01.png` 至 `05.png`，没有使用增强图片作为结构证据。01、04、05 的侧视图可确认：落地单根金属立柱、向篮板后侧伸出的开放式细管悬臂和斜撑、矩形篮板、篮圈和篮网。没有 donor 的大型可移动配重底座、软包立架、上方及后方两套电子计时器。03 是正面补充。原图分辨率不足以可靠量出管径、紧固件与支撑臂长度；尺寸应从保留的实际篮板/篮圈锚点约束，新建支架细节是设计参数，不能宣称由照片精确测量。

## 哪些真实数据已经取得

两个场地端点共引用三个共享 Model：`basket0:glass`、`basket0:basket`、`basket0:rimr`。下表省略共同前缀 `arena_clutchtime_int_master@GameObjects@MAIN@`。

| 模型 | 已取得原数据 | 结果 |
|---|---|---|
| `basket0:glass` | IB 228 B，三个 VB 384 / 192 / 384 B，权重表 4 B | 48 顶点、38 个 top-LOD 三角形；四个 Prim 的解码边界与独立原 authoring 边界最大差 0.007036 cm |
| `basket0:basket` | 100 个 Prim 与全部 12 级 LOD 范围、层级、权重表 152 B | 顶点与索引缺失，未生成替身或假装解码 |
| `basket0:rimr` | IB 27762 B，两个 VB 8008 / 12012 B | 1001 顶点、1352 个 top-LOD 三角形；边界最大差 0.001361 cm；这是反射专用模型 |

玻璃原资源：`IndexBuffer.51ed9667055f7b41.bin`，`VertexBuffer.53e22477fb59a80a.bin`，`VertexBuffer.896a75cc5eec7080.bin`，`VertexBuffer.0c64554d1de5c384.bin`，`MatrixWeightsBuffer.f4a586351e1b9f4b.bin`。

篮圈反射原资源：`IndexBuffer.2a251deade9ef00a.bin`，`VertexBuffer.8327373a27831405.bin`，`VertexBuffer.eee8b4de884f4773.bin`。主组件权重表：`MatrixWeightsBuffer.2be66feed541e8f8.bin`。

当前缺失的主组件资源如下。大小是 SCNE 声明的**解压后**字节数，不是原游戏压缩文件大小；均声明 `CompressionMethod: 33`。已检查 donor IFF、项目 `build/local_game_reference` 与交接缓存；交接缓存只含另一个 floor 顶点资源，不含这些文件。

| 精确 Binary 名 | 预期解压后大小 | 作用 |
|---|---:|---|
| `IndexBuffer.2faa94a692eecb55.gz` | 1340664 | 全 LOD R16 索引 |
| `VertexBuffer.396eff6e2f806326.gz` | 363992 | 45499 个顶点的 UNORM16 POSITION，stride 8 |
| `VertexBuffer.c7008f082a4e24dd.gz` | 181996 | UV0，stride 4 |
| `VertexBuffer.8d2e607c050161de.gz` | 1091976 | tangent frame、UV1/2/3/7、WEIGHTDATA，stride 24 |

脚本会严格保留缺失状态。以后取得用户游戏内的准确资源后，标准 Reader 可从 `build/local_game_reference` 按完整文件名读取，再次运行即可验证，不能用新增造型替代这些“原字节”。测试使用只读 donor 固定可用性，避免后续补齐本地资源改变回归测试前提。

## 权重与骨骼：已验证范围

直接分析原 `VS.7686a8a62e2bfb95.shader`（glass）和 `VS.f36b0f5e570448d9.shader`（主篮架）的 DXIL。分析副本仅为让现有 clang 读取而调整 LLVM datalayout；原 shader 字节未变。当前会话 IR 在 `/private/tmp/revision4_basket_research/glass_vs.ll` 与 `basket_vs.ll`；脚本中的布局来自两者相同运算，不依赖临时文件运行。

- `WEIGHTDATA0 & 255` 加 1 得影响数，`WEIGHTDATA0 >> 8` 得单权重 palette 索引或多权重表项起点。
- 单权重直接从原生矩阵缓冲读取对应 48 字节的 3×4 矩阵。多权重从 `MatrixWeightsBuffer` 按 uint32 表项取数，低 16 位权重除 65535，高 16 位为 palette 索引，成对加载并加权矩阵。
- glass 前 24 个顶点词为 `0x00000000`、后 24 个为 `0x00000100`，均为单权重，分别指向 palette 0、1。原主组件权重表的 19 对表项均权重和为 65535，索引在 0 至 2 之间；缺少顶点词，不能据此知道每个实际主组件顶点用了哪一对。
- `decode_weights()` 提供通用 CSR 权重解码并验证范围、权重和、奇数个影响的 shader padding。`apply_skin_palette()` 只在调用者明确提供原生 3×4 palette 时计算姿态；不会把场景节点 Translate 当成最终 skin 矩阵。

原模型层级按父链累加的 authoring 位置：basepivot `[0, 11.9270229, -349.21701]`；rimpivot `[0, 304.7640289, -0.691314]`；netpivot 约 `[0, 307.23773252, 38.1000144]` cm。这是作者层级信息；`BlendIndexOffset=1` 与运行时 palette 的分配/逆绑定矩阵未获得，脚本明确标记未验证映射。**原 POSITION 已经与作者整体空间的逐 Prim 边界吻合，直接再加这些节点 Translate 会双算位移。**

每个端点 `Object.Matrix` 的 z 平移为 ±1310.64001 cm，远端另转 180°。原 `MAIN` 引用两端的 assembly、glass、rim reflection，并声明 `VC_NetType=CLOTH`。本 SCNE 没有篮网 Prim/Model，篮网是运行时依附 netpivot 的独立布料行为，不能用静态三角片声称已经还原动画。

## 反射模型为什么不画成实体篮圈

`basket_stanchioni2_nba:rimr_mat` 使用 `basket_rim_reflection.fx#b1be57904d02fc50`。它没有普通 `Default` technique，只有 `GlassReflection` 与 ray-tracing reflection/shadow techniques；玻璃反射 pass 使用 stencil EQUAL、ZWRITE=0、ZFUNC=ALWAYS。其顶点 y 约 −16.51 至 0.01 cm，实际 VS `VS.95138f09aa9d1d31.shader` 仍从运行时 palette 取 rimpivot 矩阵。仅套 `Object.Matrix` 会把它画到地面附近；擅自抬高到 305 cm 也不是经验证的原变换。

独立审阅 JSON 保留它的实际解码几何并标 `reflection_only`，同时将两个实例 `display_in_opaque_geometry_preview=false`。它不替代实体篮圈。R3 实时预览保持严格，未将这些几何接入。

## 可执行的下一版外观改造边界

下列是**建议的后续改造范围，尚未写入任何 IFF**。主模型许多零件共用材质，不能按材质名全局删掉；应按下列原 Prim 序号与 Mesh/边界交叉核对。

| 主 `basket` Prim | 部件 | 建议 |
|---|---|---|
| 0–13 | 原室内底座、支架、轮子/金属件、软包、臂垫 | 用新静态单柱及细管悬臂外观替换 |
| 14–87 | 两套计时器及其支架、玻璃外壳以外的器件、线缆、扬声器 | 移除室内专属外观 |
| 88–90 | 篮板框、密封条/靶框线 | 保留位置，可单独换金属与白线材质 |
| 91 | 篮圈铰接密封件 | 保留原几何/权重 |
| 92 | 篮板下沿软垫 | 优先保留以维持篮板轮廓，是否改窄需实测 |
| 93–96 | 篮板计时 LED、灯框 | 户外版本可移除 |
| 97–98 | 原品牌贴花 | 可移除或独立替换 |
| 99 | 真正的实体篮圈 | 保留原几何、材质或经验证的着色、绑定、各级 LOD |

主 Prim 99 的 top-LOD `Start=666276, Count=4056`；最远 LOD `Start=4695, Count=138`。玻璃模型独立四个 Prim：0 为底座计时控制器玻璃，1 为顶部计时器玻璃，2 为后部计时器玻璃，3 才是篮板玻璃（`Start=102, Count=12`）。户外版保留玻璃 Prim 3，删除其他三个显示段。

安全实现顺序：取得主模型原 buffer 并通过解码/边界/索引审计；从 `iter_primitives()` 解析继承后的完整 Prim 记录；只保留选定显示段，**给每个保留段显式原 Start/Material/Type，所有 LodList 起点保留原绝对位置**；原 VB、权重表、层级、`MAIN`、`Object.Matrix/Transform/UserData`、玻璃反射模型与碰撞资源保持；在独立静态模型里建立新立柱/悬臂并以原篮板和篮圈锚点定位。原 `Clod` 与 conservative bounding box 不应凭想象压缩成新索引布局。需在游戏所有距离与扣篮动画下验证保留段仍正确。

若要求碰撞字节完全保留，旧大型底座的碰撞体也会仍在，新的细立柱不能自动带来新的精确碰撞：应尽量让新立柱位于旧支撑占地内，且必须实测后场通行与扣篮；不能报告“视觉和碰撞都完全匹配原照片”。要改成真正精确的新支架碰撞，是另一个明确实现/验证步骤。

## 验证结果

`python -m unittest discover -s nba2k-arena/tests -p test_revision4_basket_decode.py -v`：10 项通过。覆盖真实 donor 的两种可读模型、逐 Prim 独立边界、38 个原权重表项、完整 12 级篮圈 LOD、四个缺失资源精确名称/大小、反射 technique 分类、源文件不变；合成测试覆盖多权重 shader 数学、越界、错误 padding 与层级循环。没有宣称 NBA 2K 运行时姿态、动画、材质或最终曝光已经验证。
