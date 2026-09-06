# NBA 2K26 arena 改模交接报告

记录日期：2026-09-05。目标仓库：`Bohan-java/Vibecad-bait`。
本报告优先于旧的成功措辞、安装指引和静态 PASS 报告。

## 0. 当前状态及最新授权

**状态：用户实测不合格；停止修改，仅交接。**

用户最新原话：

> 自己他妈看做的啥，线也不是标准的，不过别改了，做这个事情：目标 repo：`Bohan-java/Vibecad-bait` ，快没额度了，现在赶紧准备交接任务，上传一切所需的文件到这个repo里，并准备一篇详细，准确的交接报告，好便于下一个ai来读取，并继续你的工作，如果需要我上传什么请指示

之前用户明确要求：只给 IFF，由用户自行放进游戏；不要代理安装或进游戏测试。
曾发生的未经许可安装已经回滚。此次交接没有再次写入游戏目录。
最初请求禁止 GitHub/云上传；**本次明确要求上传此仓库，覆盖该项旧限制**。
其他 donor 尺寸、篮架、碰撞和锚点保护要求没有被取消。
下一个 AI 应先阅读本报告和截图，等待/遵守下一条具体继续开发请求。

## 1. 用户实测证据：不要粉饰失败

最新图片：`evidence/user_game_screenshot_revision2_REJECTED.png`。
它是用户提供的真实游戏画面，不是本代理生成的预览。

从截图可以直接确认：

- 仍是巨大封闭室内场馆：完整屋顶、梁架、悬挂中心屏、看台和立柱均可见。
- 周围确有树模型，但树干/叶片几乎黑色；不是参考照片的自然阳光下棕榈树效果。
- 背景墙上可见棕榈树图案，但仍只是室内墙面。
- 地板有多重弧线、局部不自然的横线/缺失的中圈等，用户明确指出“不标准”。
- 青蓝色发光边框、室内照明和原 donor 场馆身份依然非常明显。

不能仅凭这张图确认：

- 树变黑的唯一原因。可能涉及沿用的静态 lightmap shader、缺少新对象 lightmap 数据、
  tangent frame 的近似处理、顶点属性/对象渲染标记或实际场景照明。没有完成 shader 层诊断。
- 是否所有地板叠层都已消除。截图不等于加载跟踪，未确认用户是否同时安装了配套 floor IFF。
- 运行中的文件是否与仓库 V2 哈希完全一致。截图与 V2 特征吻合，但没有对该次运行加载文件验哈希。

**因此：不能把“ZIP 打开成功 / CRC 通过 / 模型解码成功”表述为游戏内视觉验收成功。**

## 2. 原始目标及参考照片

完整原始请求：`handoff/original_user_request.txt`，保留原文供查阅。
照片：`textures/source/references/arena_reference_01.png` 至 `05.png`。
五张照片是同一球场的联合参考，不是五个房间。忽略其中所有人物。

视觉目标：海边室外篮球场，灰色哑光沥青、白色标准篮球标线、高耸棕榈树、
混凝土台阶与草地、金属看台、蓝天。照片不能用于反推或改变 donor 的空间尺寸。

原始硬约束：donor 控制尺寸、场地原点、方向、篮筐位置/高度、相机兼容、碰撞、
球员/裁判/观众/替补席等锚点和场景层级。尽量做材质/贴图修改，谨慎添加装饰几何。
未知资源必须保留，不能擅自重建全场或更换 donor。

关键冲突：该 donor 本身是带特殊标线的室内 Clutch Time 场馆，而照片是室外球场。
机械地保留全部可见结构、全部 donor 标线，再把屋顶刷蓝，不会成为照片中的室外场景。
下一阶段必须把“玩法结构保持”与“可见装饰/标线表现如何改”区分开；
如果需要移除屋顶可见几何、更换 donor 或大幅改场景，须向用户说明冲突并取得相应方向，不能偷换目标。

## 3. 已发生的工作及问题

### V1（失败，存档用）

`output/legacy/arena_700_int_v1_REJECTED.iff`：
SHA-256 `89a657faaf4df2e47e47a67ed5e739facc0af467900d50582a6c9b3af3f74217`。

V1 主要换纯色/沥青贴图。错误地将整张不透明沥青也放进 `Logo0Texture`，
保留木地板法线/高光；没有棕榈树模型，背景仅蓝色。静态检查通过后交付，视觉质量没有验证。
旧 `install_mod.py --install` 曾把它写入游戏 020 槽，用户反对后恢复原文件并校验 donor 哈希。
之后项目及游戏里出现 V1 的 700 编号副本；不要推断其改名/安装操作者。

### V2（本次用户截图对应的失败方向）

从保护的原 donor 重新生成，保留全部原始对象/模型/灯光/效果；
增加 3 个棕榈树模型、14 个场外实例；使用原 apron 的 CLOD shader 和顶点格式。
更换沥青、白线、透明 Logo、法线/粗糙度贴图；增加由参考照片单棵树提取生成的墙面背景。
将 donor 原始外部 floor 顶点资源嵌入主 IFF。
另做 `arena_700_int_floor.iff`，用空 `level_floor` 场景覆盖 700 独立默认地板。
未修改任何游戏目录，没有进行代理端游戏测试。

V2 静态及离线预览检查通过，但随后用户实测截图证实目标未达成。
特别是树发黑、室内结构原样保留和不标准标线，不能视为已修好。

## 4. 文件入口与哈希

所有以下路径均相对于仓库的 `nba2k-arena/`。

| 文件 | 用途 | 字节数 / SHA-256 |
|---|---|---|
| `donor/original/arena_020_int_original.iff` | 唯一权威原 donor，禁止原地修改 | 45,028,875 / `42865ecaf8dd923c4d901509263af3b242c00975f4284b917ba79ce8fbbced46` |
| `output/revision2/arena_700_int.iff` | 已被用户否定的 V2 主场馆 | 48,674,580 / `5d74fdab31ee29e0fe888af10c7370efc329ecc76ceb72c2f1d3eb6aa92bd499` |
| `output/revision2/arena_700_int_floor.iff` | V2 的独立地板覆盖包 | 445,558 / `5f23522f783614d1572dca4f904132659f0d9ad4bd266b8148cbaacd333cf2ce` |
| `output/legacy/arena_700_int_v1_REJECTED.iff` | V1 失败对照 | 45,203,907 / `89a657faaf4df2e47e47a67ed5e739facc0af467900d50582a6c9b3af3f74217` |
| `build/revision2/level.SCNE` | V2 的可读主场景 | SHA 见文件清单 |
| `build/revision2/revision_report.json` | 静态比较、贴图描述、树位置 | 不是视觉通过证明 |
| `build/revision2/mesh_validation.json` | 三种新树的顶点数量和量化误差 | 不是 shader 正确证明 |
| `docs/*inventory.csv` | 材质、纹理、模型 prim、对象映射 | 主要对应原 donor |
| `build/revision2/textures/` | 新纹理源 PNG、BC 解码 PNG、DDS、TLD | 可检查真实编码结果 |

完整逐文件清单：`handoff/FILE_MANIFEST.json`。
未重复上传原 donor 的多个备份、完整解压目录和相同输出副本；原始 IFF 本身包含可重新提取的内容。
`donor/working`、`extracted/donor` 如旧脚本需要，必须在工作副本中自行从原 donor 重建。

## 5. IFF / donor 结构与已确认事实

原 donor 是 ZIP_STORED，2,221 个条目。V2 为 2,251 个。
原条目中只有 `level.SCNE` 内容改动；其余原条目逐字节保留。
`level.SCNE` 是 JSON fragment：以 `"level":{...}` 表示，解析需在两端加 `{}`。
不要假定所有其他 SCNE 都是文本：游戏档案里 700/020 的独立 floor SCNE 是二进制。

原主场景：69 材质、67 模型、860 对象、1,759 texture records、23 lights、34 effects。
V2 新增 5 种棕榈材质、3 个模型、14 个对象、21 种纹理记录；原字典各项保持不变。
篮架 `baskets.SCNE`、各 `.Coll`、crowd、原 shader/script 和 lightmap 资源均保留。

### 主 floor

对象：`__floor00__`，identity matrix。
目标：`arena_clutchtime_int_master@GameObjects@CourtFloor:floor_clutchtime_court_low`。
整个 floor 模型（包含周边缓冲区，不应等同于标准场内标线尺寸）的范围：

```
Min [-975.360352, 0, -1889.76001]
Max [ 975.360352, 4.76837158e-7, 1889.76001]
```

3231 顶点，交错 stride=28，POSITION0 为 float3 offset=0。
4 套 R16G16_SNORM UV 位于 offset 12/16/20/24，需套用场景 Scale/Offset。
索引：`IndexBuffer.3ebaba4dd3080a92.bin`，R16_UINT，18,252 字节。
原顶点：`VertexBuffer.0f3b6fcaf86b59a6.gz`，CompressionMethod=33，解码后 90,468 字节。
原 donor IFF 未内嵌该外部顶点，V2 已按原始压缩字节补入。

Prim 规则很重要：部分 `Start` 和 `Material` 省略；`Start` 按前一段结束累积，
`Material` 继承上一个值。不能全按 Start=0 或丢弃没有 Material 的 prim 解析。
原始主地面 prim Count=2010，其余是独立标线。包含 `line_four_point_lowShape`，
这直接解释“保留全部 donor 标线”为什么会保留非标准四分线。
还包含三分线、罚球圈、内外罚球区、冲撞区和边界；原 donor 没有在此提供完整常规中线/中圈表现。
**不要把截图的所有多重弧线都归因于两层地板：至少一部分是原 donor 的不同标线 prim。**

### 外围地板与独立 floor

`clutchtime_floor_apron` 模型仅 16 顶点/48 索引，在 donor floor 范围留有矩形洞口。
它不是覆盖全场的第二张平面。量化解码 y 大约 0.1，名义 y=0。
游戏 manifest 确认 700 槽存在单独 `levels/arena_700_int_floor.iff`，
而该 donor 主场景已经自带完整 floor；这构成潜在重复加载路径。
V2 配套 floor 包保留原 40 条资源，只把 `level_floor.SCNE` 改为 `"level_floor":{}`。
空 floor 格式参考了本机一个既有 mod。**没有完成运行时加载跟踪证明此覆盖在用户实测中一定生效。**

## 6. V2 材质与新树的技术细节 / 风险

`scripts/build_revision2.py`、`revision_textures.py`、`palm_geometry.py` 是 V2 入口。

地面：`floor_clutchtime_court:area_1_mat` 的 DetailAlbedo=沥青，Logo0=全透明 BC3；
BaseMaterial=(220,0,0,255)，DetailNormalRoughCone=(128,128,215,255)，
DetailRoughness=.84，DetailNormalHeight=.006。白线只换成白色漫反射与同类粗糙度。
这些是当前实现值，不是已经在游戏中证实正确的通道解释。
基于现有资料按 RG normal / B roughness / A cone 处理 floor normal map；
apron/新树的 NormalAndRoughMap 用 (128,128,0,215)，按 A roughness 处理。
通道/色彩空间和 shader 的实际组合效果仍须核对。

21 张纹理用 Pillow 的 DDS DXT1/DXT5 编码成 BC1/BC3，有完整 mip，再加 32 字节 TLD header。
header struct 为 `<4sIHBBIHHHHII>`；格式码 71/77；材质数据标记 LINEAR。
这套格式已静态解码通过，但 **不能推导出任何 donor shader 都适配同样的 Min/Max 或通道意义**。

新树：3 个 variant，主干高度 1040 / 1220 / 920（donor 坐标单位），
每模型 24,216 顶点、8,072 三角形，36 片扇叶；每侧 7 个实例。
x=±1445.360352；y=0；z=-1650,-1100,-550,0,550,1100,1650。
树 AABB 全在 donor floor 范围外，不新增碰撞；这不等于已经逐个验证相机/观众遮挡无影响。
树干 winding 已按外向修正，叶片显式双面。

复用 apron 的 `layer_base_CLOD.fx#72407e286031da1b`，三个 vertex streams stride=8/4/20：
POSITION R16G16B16A16_UNORM；UV0 R16G16_SNORM；TANGENTFRAME R10G10B10A2_UINT。
新模型都是 Lod0 / NumMaskBits=0。树材质复用原脚本，未引入新的 compiled shader。
**重要风险：tangent frame 并未正确数学编码，而是对 donor 三角法线采样后选“最近法线”的原 packed frame。**
其他 UV 通道部分全 0；新增 Object 没有原 donor UserData/lightmap 分配。
这只是当时兼容性尝试，不是可靠的导出方案，可能与树发黑有关，不能继续盲目调 RGB 掩盖。

离线预览 `preview_revision2.py` 仅几何展开 + 简单 CPU painter shading，
不运行 NBA 2K shader、不使用游戏照明/lightmaps，也不模拟完整背面剔除、渲染状态或 culling。
`court_and_palms_layout.png` 隐藏了其他 donor 建筑，绝不能当作最终场景效果图。

## 7. 无完整游戏的本地复现

运行环境实测为 Windows / Python 3.12.14 / Pillow 12.3.0 / NumPy 2.3.5。
原本机 Python：`C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`。
其他机器用自己的 Python，勿依赖此绝对路径。

在 `nba2k-arena` 目录运行：

```sh
python -m pip install -r handoff/requirements.txt
python handoff/reproduce_revision2.py --build --preview
```

适配器只改当前进程的读取函数，原 mod 脚本保持存档原样。
读取附带的最小缓存而不读游戏目录、网络或 DLL。
会覆盖项目内 V2 输出/预览并打印与存档 IFF 的哈希是否一致；**复现的是失败版本，不是修复它**。
不同平台/编码库可能导致纹理字节不一致，必须看打印结果，不要假定一致。
若只查看新树，可用 `--preview`。
重建脚本会重写历史 `docs/REVISION2_REPORT.md`；权威失败状态仍以本交接报告为准。

原 `scripts/build_revision2.py` 直接运行仍依赖本机游戏 manifest 与 Oodle DLL；
不要在另一台机器直接运行后误报“资料缺失”。使用上面的缓存适配器。
`scripts/install_mod.py` 仅为历史证据保留，**禁止未经用户新授权运行 --install 或 --restore**。
旧 `docs/LOCAL_WORKFLOW.md` 和 `validate_mod.py` 对应 V1，不能作为 V2 的当前构建/验收入口。

### 最小缓存来源

本机游戏路径：`D:/steam/steamapps/common/NBA 2K26`，只用于之前本地只读提取。
manifest 是 `path,archive,offset,size` CSV。选定资源：

```
shared/0f/vertexbuffer.0f3b6fcaf86b59a6.gz,0O,10660349198,26927
levels/arena_700_int_floor.iff,0B,410193446,161095
levels/arena_020_int_floor.iff,1O,67647167,143071
```

偏移只适用于这台机器该游戏安装，不应硬套其他更新版本。
`build/local_game_reference/levels/*.iff` 是解压后的 ZIP；
`build/local_game_reference/shared/0f/*.gz` 实际是已解码原始顶点（历史命名有误，非 gzip）。
`handoff/cache/` 明确区分原始 VCZ 字节与已解码 .bin。
VCZ 包装以 `1f8b...VCZ\0` 开头，数据在 16 字节头与末尾 8 字节间。
原工具先试 zlib，再用本地 `oo2core_9_win64.dll` 的 OodleLZ_Decompress。
未上传该 DLL；缓存复现路径不需要它。

## 8. 下一 AI 的建议工作顺序（须在用户要求继续后）

1. 看实测截图与全部参考图，明确当前版本失败，不以旧报告 PASS 开始。
2. 确認当前实际加载编号及两个 IFF 的哈希，确认是否仍有其他同槽 floor mod；让用户自行放置/截图。
3. 从 donor floor 逐 prim 分析标线并画出平面图，区分原 donor 四分线、其他额外标线与真正重叠地板。
   不改变场地实体大小和篮筐；优先研究材质透明/图案映射调整可见标线。
4. 用原 shader/顶点格式知识或可靠本地导出工具检查树的光照、packed tangent、UV/lightmap 和对象标记。
   不要把 CPU 预览亮绿当作游戏会亮绿的证据。
5. 解决室内 donor 与室外参考的核心外观冲突。刷蓝屋顶不是开天空；说明保护玩法结构和改变装饰可见性的边界。
6. 小步生成新的编号/版本化输出，保留 donor 和 V2 失败对照。只做项目内输出，不自动安装。
7. 用户游戏反馈到位后才能作游戏内验收；明确区分加载成功、标线正确、光照正常、视觉接近参考等标准。

## 9. 用户是否还需上传

本交接已包含原 donor、全部五张参考图、最新实测截图、V1/V2 输出、构建脚本、纹理中间资源、
最小游戏资源缓存和历史映射文档，下一 AI 不需要用户重新上传这些文件。

只有继续深度游戏验证时，才可能需要：

- 用户确认实际启用的槽位和配套 floor 文件，必要时提供相关文件哈希或单独这两个 IFF；
- 下一轮用户实际游戏截图/短视频，尤其底线、边线、树正反面和正常游戏相机；
- 若有用户熟悉的、可合法使用的 NBA 2K 本地导出工具/插件或更适合的 donor，可告知路径，不能自动假设更换。

不需要用户上传完整游戏档案、游戏 DLL、账号凭据或 GitHub Token。
