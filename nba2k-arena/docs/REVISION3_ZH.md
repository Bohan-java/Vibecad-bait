# Revision 3：海边室外球场修复记录

日期：2026-09-06。项目：`Bohan-java/Vibecad-bait / nba2k-arena`。

**当前验收状态：V2 与 Checkpoint 1 已被用户游戏实测否定；完整 V3 候选已构建，通过静态检查和实际导出几何预览。预览发现的分层树冠已改为每株 60 片有独立扭转和深裂叶尖的棕榈冠层，并按原生 R16 索引限制分区导出。尚无 V3 游戏实测证据。** 最新产物状态与哈希以 [validation.json](../output/revision3/validation.json) 为准，静态通过仍只对应 `STATIC_VALIDATED_GAME_UNTESTED`。本文不能作为游戏验收通过证明。

分发文件为 [venice_court_revision3.zip](../output/revision3/venice_court_revision3.zip)。解压这一层 ZIP 可得同一轮构建的两个 700 槽 IFF、校验报告和说明；**不要再把 IFF 自身当普通压缩包解压后放入游戏**。

用户当前目标是完成 NBA 2K 的海边室外篮球场 MOD。此前提到的可 3D 打印模型不是本次 IFF 修复的交付标准。用户已允许改变屋顶、墙体、悬挂屏等装饰的可见性和照明；donor 场地尺寸、篮筐、碰撞、相机/玩法锚点及原变换仍受保护。五张参考图是同一处球场的不同视角，忽略所有人物。

## 为什么需要这一轮

历史记录见 [原交接报告](../handoff/HANDOFF_ZH.md)。用户实测图片是：

- [V2 被否定的游戏截图](../evidence/user_game_screenshot_revision2_REJECTED.png)：完整室内屋顶、梁架、悬挂屏和高墙仍在；树接近黑色；地板标线不符合目标。
- [Checkpoint 1 被否定的游戏截图](../evidence/user_game_screenshot_checkpoint1_REJECTED.png)：仅修正部分标线没有解决海边场景外观，donor 室内背景继续构成明确失败。

旧 `VALIDATION_REPORT.md` 的 PASS 属于早期静态检查，`docs/checkpoint1/CHECKPOINT_ZH.md` 中“待用户游戏实测”的状态也已过时。不能把它们当成当前成功状态。用户要求的是完整室外球场，不能交付保留巨大室内背景的下一组局部修改。

## 五张照片共同定义的空间

参考：[01](../textures/source/references/arena_reference_01.png)、[02](../textures/source/references/arena_reference_02.png)、[03](../textures/source/references/arena_reference_03.png)、[04](../textures/source/references/arena_reference_04.png)、[05](../textures/source/references/arena_reference_05.png)。

这五张原图均为 **640×480**，足以联合判断整体空间、材质类别、树木分布与看台形态，不足以精确恢复细节纹样、微小文字、表面颗粒或实体尺寸。用户正在寻找更高清参考；本轮随后重传的附件经主流程核对仍是相同的 640×480 像素内容，不算新的高清证据。真正高清资料到位后用于细节校正，当前不能假装已从低清图识别出不存在的精确信息。去掉室内背景、修正标线与树干面朝向等客观错误不需要等待高清图。

按用户要求另生成了 [五张 AI 增强参考](../textures/source/references/enhanced/README.md)，工具实际返回每张 **1448×1086**；虽然请求为 3072×2304，本轮没有再人工放大。它们仍对应同五张照片，没有新增相机视角，原图保留不变。AI 补出的叶片、颗粒、标识等细节是生成内容，不能当作恢复出的真实测量或新拍摄证据；映射、实际尺寸和哈希见 [增强图清单](../textures/source/references/enhanced/manifest.json)。

| 要素 | 多图共同可见的特征 | 建模含义 |
| --- | --- | --- |
| 场地 | 开放天空下的灰色篮球场，白线清楚，周围为浅色混凝土广场 | 保持 donor 比赛坐标；材质表现应有细微颗粒与磨损，不能用无细节的大块纯灰代替 |
| 草坪 | 一侧长边为低矮混凝土挡边和数级草坪台地 | 做连续低台地，不做高挡墙，也不要四面复制同一种背景 |
| 看台 | 对侧为独立、低矮、银色金属看台，具有横向座板、阶梯与细杆支架 | 使用新低矮看台；donor 的 8 米看台、包厢和大椅群不应保留 |
| 棕榈 | 高细树干、大小不一的树冠，沿草地和远处分簇分布 | 避免完全等间距、两侧镜像排树；树冠不能变成密实黑团或巨大球形树叶 |
| 远景 | 一座低灰色矩形公共建筑、少量路灯、广场与极低的海平线 | 保持天空和地平线开阔，海不应成为竖直蓝墙，远处建筑不能压过整个篮架 |
| 篮架 | 参考中为细金属室外篮架，与 donor 的游戏篮架外观不同 | 本轮继续保护 donor 篮筐位置、高度、层级和碰撞；不得为了照片比例擅自移动篮筐 |
| 光线 | 日光方向和曝光随拍摄时段不同；第五张地面有湿润反射 | 多图取共同空间与材质；不要把单张湿地或逆光黑影固化成所有场景材质 |

照片没有提供可用的建筑测量值。装饰台地宽度、看台排数、树高和远楼尺寸均是适配 donor 的设计选择，不是从透视图恢复的真实尺寸。donor 的比赛尺寸与篮筐仍是权威。

## 已实现的场景清理

入口：[scripts/revision3_environment.py](../scripts/revision3_environment.py)，函数 `apply_environment(level, donor_zip, extra)`。

逐项核对原 `level.SCNE` 的对象类型、对象组与模型 Target 后，显式名单覆盖 **791 个场外渲染实例、66 个原模型**。屋顶、梁架、天花板、立柱、高墙、全部壁画结构、悬挂屏、灯具、门、幕帘、场边发光板及围板、大看台、所有高低包厢、底层平台、栏杆、椅子和原 apron 均在名单内。

**清理后原 donor 唯一保留的可见模型是原比赛 floor。** 原 apron 是具有场地洞口的场外铺地，量化高度约 `y=0.1`；它会遮住放在 `y=-0.4` 的新广场，还可能继续携带室内烘焙外观，因此也明确隐藏，由新广场铺地替换。新的海边地形、植被、看台和远景由室外场景模块提供。不会把残留的底层包厢或大看台当作“已经足够室外”。

隐藏方式是给指定模型增加新的同尺寸全零索引资源，所有三角形变为 `(0, 0, 0)` 的零面积三角形，涵盖全部 LOD。同步更新索引 CRC32，并将压缩索引引用改为对应的原始 `.bin` 引用。保留原顶点、Prim、LOD、包围盒、原对象 Target、Matrix、Transform 与其他属性。原 archive 中已有的索引资源逐字节保留；原本属于游戏共享资源的索引在报告中标记为外部引用，不谎称它们已经内嵌。

不依赖猜测的 `Visible` 字段、不把不透明 shader 强行设为透明，也不删除不认识的对象。如果有未知对象共享了一个准备隐藏的模型，函数会在修改前报错；如果原模型或对象与已审计 donor 不一致，也会停止该次处理，避免误伤。

环境函数返回完整审计记录：原对象/模型、隐藏原因、原索引引用与可得的哈希、新索引资源和哈希。所有准备检查完成后才更新工作场景，失败不会留下半套已隐藏的场景。

## 观众与灯光的实际处理

原 `crowd.SCNE` 的唯一 `crowd_cards` 渲染模型位于 `y=1342.906..1611.113`，明确对应被移除的高层包厢。V3 用同尺寸退化索引隐藏这些静态卡片；保留整个 crowd 场景的 Object、Transform、材质和 shader。原 `crowd.CrowdData`、座位顶点、各 `StadiumPath` 和玩法锚点不改。

环境报告的 `scene_overrides['crowd.SCNE']` 是可 JSON 序列化的 **UTF-8 JSON fragment 字符串**。集成打包器必须编码后替换原 `crowd.SCNE` 条目，同时写入 `extra` 中的新索引资源，不能把它只保存在报告里。

对 68 个原 scene MARKER 的检查没有找到有证据支持的 crowd 可见开关；`crowd.CrowdData` 与 `crowd_lighting.FxTweakables` 是未充分解码的二进制，不能猜字段改写。用户提供的训练画面没有观众；**启用动态观众的其他模式仍有悬空观众风险，尚未验证。**

灯光使用 donor 自带字段：

- 启用原 `TIME_OF_DAY` 的 `VC_Enabled` 与 `VC_SkyEnabled`；沿用原中午 12 点、天空和曝光参数。
- 启用原方向光 `Sun.VC_IsActive` 和已存在的 `VC_CastsShadows`，保留其方向、强度、颜色和变换。
- 关闭 18 个室内包厢 SPOT 的 `VC_IsActive`，保留资源与灯光位置。
- 保留 4 个球场 AREA 光，作为动态角色照明路径；没有未经游戏验证就同时关闭全部照明。
- 将原楼梯灯材质的自发光强度设为零；原楼梯几何已经隐藏。

开启现成字段不等于实际游戏渲染管线已经按预期运行。原 IBL 和其他部分光照预计算资源仍保留；比赛 floor 的两张辅助光照纹理已按下节单独替换。不能声称整个场景已重新烘焙为自然日光。

## 地板旧室内光照的替换

入口：[revision3_floor_lighting.py](../scripts/revision3_floor_lighting.py)。没有用猜测的材质槽，也没有改 shader 或 floor Object.UserData，而是替换原 `level_floor_lightmaps.SCNE` 已存在的两条纹理绑定：

| 原 Texture key | 保留的格式/尺寸 | 新内容 |
| --- | --- | --- |
| `__floor00__` | `R11G11B10_FLOAT`，424×424、2 mip、2 face | face 0 为均匀天空环境光，face 1 为方向/环境混合数据 |
| `__floor00___linelightvisibility` | `R8_UNORM`，424×424、2 mip、1 face | 全 255，移除旧室内静态线光遮挡图案 |

原地板 pixel shader `PS.0cfd5246b9c1587a.shader` 的实际解码证明：face 0 RGB 是 irradiance；face 1 的 RG 解码方向、B 控制环境光混合。face 1 取 `[0.5,0.5,1]` 时解码为有效的 `+Z` 方向，方向贡献为零，输出直接取 face 0，不会除以零。线光 visibility 的采样与无资源时回退到 1 的代码也已核对；全 255 不会关闭四个原线光本身。

默认环境光设计值为 `[0.8,0.85,0.95]`，实际 R11G11B10 量化后为 **`[0.796875,0.8515625,0.953125]`**；可通过 `ambient_rgb` 调整。两张原图的像素是交接包未包含的游戏外部资源，本轮没有假装读出它们的平均亮度。**这是一份显式均匀补光近似，不是重新烘焙，曝光仍需游戏画面校准。**

两个新 TLD 保留原格式、尺寸、mip、face、key 和辅助场景 `FLOOR` marker，更新 Binary 与实际量化像素的 Min/Max，去掉新 raw 数据不适用的 Segments/CompressionMethod。双 face 采用原 SCNE `MemoryOffset` 明确给出的顺序：face 0 的 mip 0/1 在 `0/719104`，face 1 的 mip 0/1 在 `898880/1617984`，总像素 1,797,760 字节；不能按原压缩片段的文件存储先后顺序排列。

R11G11B10 与 R8 原头没有本地样本可逐字比对；验证依据是 donor 实际 BC6H 双 face TLD 的共同头结构、原 SCNE 内存布局、[Microsoft DXGI 格式定义](https://learn.microsoft.com/en-us/windows/win32/api/dxgiformat/ne-dxgiformat-dxgi_format) 和独立数值解码检查。没有把格式静态检查说成游戏实际加载通过。

## 标线与新模型导出采取的修复方法

标线模块 [revision3_court.py](../scripts/revision3_court.py) 从原 `baskets.SCNE` 的篮架矩阵与篮网 pivot 层级确认厘米坐标，依照脚本记录的 NBA 官方场地图构造常规可见线条。它保留原地面底层 Prim、原顶点前缀和底面索引；移除 donor 的旧标线绘制段，再增加边线、底线、中线、中圈、罚球线、三分线和限制区等新标线。新增顶点不扩展原 floor 包围盒。

新增地面顶点的 UV 从原地面三角形做重心插值，再按 donor 的 SNORM 格式量化。这样不会用随意的零 UV 替代地板原有映射。**可见标线变化不修改 NBA 2K 的比赛规则或计分逻辑**；例如游戏模式自身若有四分计分规则，隐藏旧四分弧不会自动关闭该规则。

新场景模型模块 [revision3_mesh.py](../scripts/revision3_mesh.py) 按原 `VS.3e4e8775aa14fa50.shader` 的 DXIL 解码逻辑编码 packed tangent frame：octahedral normal、参考轴、切线余弦、正弦符号和 handedness 分别有明确位定义。新实现不再使用 V2 的“找最近 donor 法线并复制其 packed frame”。切线由实际 UV 梯度生成，并对量化后数据执行往返检查。

新材质使用一份隔离 effect，保留 donor 完整 `Default` technique 的原 shader、ResourceMapping、RootConst 和 Script 绑定，不伪造新对象 lightmap UserData。另完整复用原 `OnlyDepthCSM` 深度 pass 及其原 mask 64；已核对其 VS/PS、RootConst、ResourceMapping 与现有位置专用深度路径兼容，没有混入烘焙光照的颜色 pass。该路径不要求原烘焙 UV7，但 **NBA 2K 在新对象上实际选择这些渲染路径、是否产生新树影仍未经游戏实测**。即使数学编码检查通过，也不能提前宣称黑树和阴影一定已经修好。

原 floor 还有一个名称为 `Simple` 的 technique。其实际 shader 经审查只采 albedo 与 Logo 并直接输出颜色，没有法线、粗糙度、动态灯光或烘焙光照采样；它是纯颜色路径，不能当作高质量动态照明地板的替代。隐藏屋顶也不会自动擦除原 floor 光照依赖。

材质源下载入口是 [fetch_revision3_assets.py](../scripts/fetch_revision3_assets.py)。它针对具体 Poly Haven 贴图记录来源、CC0 许可标记、文件大小、MD5 与 SHA-256；下载内容校验失败会报错。纹理质量最终还要检查实际 TLD/DDS 编码结果、通道、色彩空间、UV 重复尺度，以及游戏内正常相机下的表现。

已完成构建的材质记录包含 **27 张原生纹理**；扫描材质的 diffuse/normal 保留实际源分辨率，没有为缩小交付 IFF 强制统一降到低分辨率。原 floor TEXCOORD2 和 donor 的 DetailMaterialScale/Offset 保留，物理重复尺寸不能靠参数名称猜测。景观使用 20 个棕榈实例；每株树冠具有 60 片具独立扭转的扇叶，连续叶脉 UV、深裂叶尖、树干平滑法线和四种高矮/倾斜变体；通过分区模型保留几何细节并符合原生 R16 索引范围。最新模型数量与原型三角形数见 [revision_report.json](../build/revision3/revision_report.json)，原型三角形数不能当成乘实例后的整场渲染三角形总数。

## 本报告已经核实的检查

环境模块的 **10 项测试已通过**，见 [test_revision3_environment.py](../tests/test_revision3_environment.py)。检查范围包括：

1. 原 donor SHA-256 仍为 `42865ecaf8dd923c4d901509263af3b242c00975f4284b917ba79ce8fbbced46`。
2. 指定模型所有 LOD 的新索引均为同尺寸零面积三角形，CRC32 正确；原顶点/Prim/LOD 等字段保持一致。
3. 原 792 个 OBJECT 中仅比赛 floor 一个实例保留可见索引，其余 791 个按名单隐藏。
4. 每个原 Object、Target 与变换保持一致；仅环境 MARKER `TIME_OF_DAY` 的两个已有开关变化。
5. 原 floor 模型、Effect、Texture 不被环境函数改写；标线与材质由各自独立模块负责。
6. 只有 Sun 的已有激活/阴影字段和 18 个包厢灯的已有激活字段变化，4 个球场灯完整保留。
7. crowd override 仅替换渲染索引，crowd 场景其他内容一致；报告可 JSON 序列化。
8. 未知对象、缺少 native sky 字段等情况在写入工作场景前失败，原输入与既有 extra 数据不变。

在 `nba2k-arena` 目录，使用已有 Python 运行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_revision3_environment.py -v
```

此命令不安装建模软件、不下载依赖、不运行游戏。完整测试集合在最终树冠修改后重新运行，**75 项通过**。最终生成器还会对打包完成的真实 IFF 执行资源、场景、索引、尺寸及外层 ZIP 内容校验。

新增地板光照模块的 **11 项测试已通过**，见 [test_revision3_floor_lighting.py](../tests/test_revision3_floor_lighting.py)。除真实 donor 布局、两种 TLD 全 face/mip 像素和事务失败保护外，测试以 Python 标准库的 IEEE binary16 解码为独立参照，穷举全部有限 11/10 bit 码交叉验证编码/解码，覆盖次正规数、舍入中点、溢出和非有限值。

最终 [validation.json](../output/revision3/validation.json) 确认：主 IFF 原条目中仅 `level.SCNE`、`level_floor_lightmaps.SCNE`、`crowd.SCNE` 三项变化，**其他每个原二进制资源均逐字节相同**；除 `TIME_OF_DAY` 的两个开关外，所有原主场景 Object 内容等价；原编译 effect 保留。篮架、碰撞、CrowdData、座位数据、原顶点与索引等资源未被覆盖。新增 index 范围、stream 长度和所有隐藏模型的各级 LOD 零面积检查通过，无重复 archive 条目，未修改游戏目录。每次重新构建仍会执行这些保护检查。

## 集成入口与候选文件

完整构建入口为 [scripts/build_revision3.py](../scripts/build_revision3.py)，产物入口如下。两份 IFF 必须由同一轮构建提供；每次重新构建都会生成当前文件大小与哈希，避免复制旧版本数值。

| 路径 | 用途 |
| --- | --- |
| `output/revision3/venice_court_revision3.zip` | 主分发 ZIP，含两个 IFF、validation.json 与 README.txt |
| `output/revision3/arena_700_int.iff` | V3 主场馆候选，保留原生纹理分辨率 |
| `output/revision3/arena_700_int_floor.iff` | 700 槽的配套独立地板覆盖包 |
| `output/revision3/validation.json` | 对最终实际 IFF 的检查与哈希 |
| `build/revision3/level.SCNE` | 生成的可读主场景 |
| `build/revision3/revision_report.json` | 场景、标线、材质和几何的构建记录 |

两个实际 IFF 的 SHA-256 与大小见 [validation.json](../output/revision3/validation.json)。校验必须针对最终下载文件及同一轮报告，不能复用上一次构建的哈希。

Git 分发采用外层无损 ZIP；超过 100 MB 的原生主 IFF 在本地保留且可重建，不通过降低纹理分辨率强行缩小文件。已经核对的两份 IFF 所有条目均为 `ZIP_STORED`，外层 ZIP 的压缩不改变任何内层 IFF 字节；重新打包继续保持这一结构。

已生成的离线查看器在本地 `build/revision3/preview/`；其大体积派生几何和 PNG 不重复提交，运行 `revision3_preview.py` 可由交付 IFF 重建。它从实际 IFF 导出几何和 albedo，不运行 NBA 2K shader；每次查看前应核对 [预览审计快照](revision3_preview_audit.json) 的源哈希与本轮主 IFF 一致。已有预览记录 66 个隐藏模型/791 个隐藏实例。篮架存在 3 项仅限离线预览的缺失共享索引或未解码蒙皮/反射变换，因此以实际对象矩阵下的包围盒占位；原 IFF 篮架资源未因此修改。这些占位不能当成游戏中的篮架外观，离线光照也不能替代游戏验收。

## 游戏验收仍必须分别确认

- 游戏实际加载的是同一版本、同一槽位的主 IFF 与配套 floor；仅凭画面相似不能证明加载了指定哈希。
- 屋顶、梁架、高墙、壁画、悬挂屏、大包厢与室内发光边框在普通游戏相机和其他角度均不可见。
- 地面仅一套正确常规标线，中心与篮筐对齐；没有原四分线、重复地板、闪烁或异常反射。
- 日光下树干/叶片颜色、树冠轮廓、正反面、阴影和纹理尺度正常；不能用离线亮绿预览代替这一项。
- 草地、混凝土台地、新金属看台和远景共同接近五张照片；不是仅给封闭馆换一张海边墙纸。
- 球员、篮筐、相机、碰撞和玩法锚点仍兼容。原碰撞仍保留，在已隐藏建筑的位置可能存在场外不可见碰撞。
- 其他启用动态观众的模式未验证；不得将训练模式的空场景通过扩展为所有游戏模式通过。

本轮只应输出项目内候选文件，继续由用户自行放入游戏并提供实测画面。旧 `install_mod.py` 不属于 V3 必需流程。没有 V3 游戏截图和加载文件核验前，最终状态应保持“候选已构建/静态验证通过，游戏内待验收”，不能写“完整修好”或“游戏验收通过”。
