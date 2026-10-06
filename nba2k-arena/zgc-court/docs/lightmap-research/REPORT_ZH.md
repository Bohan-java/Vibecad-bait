# NBA 2K26 静态表面夜景光照：可行性与可逆诊断

**项目**：Bohan-java/Vibecad-bait / `nba2k-arena/zgc-court/`  
**分支**：`大融城OG-Snippy-snoopy-Dingus-court`  
**源码研究基线**：`abd8643af109fd93720595157b8f4792f0e14bcb`  
**日期**：2026-10-06  
**交付目录**：`docs/lightmap-research/`  
**本轮性质**：只读源码研究、格式分析、标准库诊断工具及合成测试。未执行真实游戏测试，未取得目标 IFF 内的 DDS／shader 字节，未生成游戏包。

## 1. 决策结论

**这项第二期值得做。最有把握的短期路线，是复用已经工作的原生 `EmissiveAlbedoMap`，把 Cycles 求出的局部 RGB 漫反射贡献和静态遮挡形状交给不透明接收表面。BC4 可以并行研究为局部明暗／遮挡控制，但当前证据不足以把它定义成完整光照强度，也不足以保证添加它就能控制现有地面的受光。**【推断；依据 C1、C2、C3、U1】

这里有三个直接影响实施的发现。

**第一，探针已经能影响静态面。** `night_scene.py` 保存的 LDIAG1 历史结果明确包括地面、静态灰板与球员变亮；随后代码也通过探针增益照亮球场。当前问题的重点是增加表面级空间分辨率、门洞形状和遮挡边界。该历史结果与本轮独立游戏复测需要区分。【代码中的历史记录：C1、C2】

**第二，当前自制不透明材质有一条不读取 UV7 的普通渲染路径。** `r04_materials.py` 使用 `asset_CLOD` 的杯子模板，显式检查 `AssetHires/AssetLores` 的 GBuffer VS 输入不包含 `TEXCOORD7`。因此，模型有 UV7 与当前 draw 真正采样 UV7 是两件事。添加绑定后，是否会选择模板已有的 Lightmap 分支，仍需验证；也可以用一个绑定完整的原生静态 Lightmap donor 作对照。不能据此断言整个 `asset_CLOD` effect 都不支持光照贴图。【代码：C3；推断：分支选择的影响】

**第三，发光叠加无法自动压暗已经被探针照亮的阴影。** 若现有探针把门口一整片地面都照亮，给发光图中的门框阴影位置写黑色，只会停止该位置的新增发光。原有探针亮度仍然存在。最终要达到有分量的围栏和门框阴影，需要协调接收面的基础受光与新增 RGB 贡献。【推断：加法模型；历史依据 C1、C2】

### 1.1 问题逐项回答

| 问题 | 本轮可确认的答案 | 尚需的证据 |
|---|---|---|
| BC4 存什么？ | 存一个归一化标量通道；作为同名逐物体资源参与原生绑定。【标准 W1、W2；用户验证 U1】 | 标量代表太阳可见度、天空可见度、AO、照明强度或混合量，目前无法定论。 |
| Min/Max 是否负责还原？ | 元数据存在；仓库还在浮点探针缓冲及普通颜色纹理上使用同名字段。【代码 C2、C4】 | 未取得读取这些字段的引擎代码／shader 常量，仿射还原公式只是待测假说。 |
| 自制静态面能否用同名 BC4？ | 有完整的原生绑定先例，具备值得测试的接入条件。【C1、U1】 | 要证明非发光接收面的实际分支和逐像素采样；发光物体成功不能替代此验证。 |
| Twiddled=1 的确切排列？ | 未解码；不能把数字 1 直接解释成 Morton 排列。【证据边界 E0】 | 真实原生 TLD、DDS 对照或消费端解码代码。 |
| CompressionMethod=33 是什么？ | 未解码；与外层 ZIP DEFLATE、BC4 块编码分别讨论。【C4、C5、C6】 | 方法枚举／TLD 解压器或匹配的真实字节样本。 |
| 当前能否写可测试纹理？ | 能写标准 BC4 DDS，沿已工作的 `.tld` 引用→`.dds` 成员路径测试。【C4、C5；合成测试 E1】 | 新的逐物体 BC4 DDS 被实际游戏正确采样，仍待实验。 |
| 能否有局部彩色光斑？ | 现有 sconce 原生材质提供 `EmissiveAlbedoMap`；可用 RGB 图案实现固定表面增亮。【C2、U1】 | 地面应用、边界衔接、阴影对比和动态遮挡表现需要游戏验收。 |
| 已找到第二张 RGB lightmap／室内 RGB donor？ | 本轮没有找到可证实的实例。不能把此结论扩展为引擎不存在该功能。【E0】 | 对真实包统计纹理、材质槽、Effect 资源映射及采样代码。 |

### 1.2 本轮实际访问范围

已读取指定提交中的绑定、材质修复、几何、纹理、封装、地面深度与探针烘焙代码，以及前一轮 LIGHT_BRICK_MAP 报告。GitHub 对目标游戏包返回的内容是 LFS 指针：【数据 E0】

```text
sha256:67937dec20a213047b53d895d27140bda309052426511be624e97ea4c3dcbdd9
size: 1686988259
```

上面的 SHA 是指针声明的 LFS 内容标识，本轮没有读取整包并验证这个哈希。用户给出的约 9856 个 BC4 条目、671 个自制物体和路灯 Min/Max 数值，在本报告中标为用户数据 U1。本轮没有重新统计它们。没有把旧验证报告中的物体编号直接当成当前地面编号；诊断工具从输入包重新识别和检查地面。【数据 E0、U1；代码 C9；工具 E1】

## 2. BC4、Min/Max 与 shader 组合：确定项和未知项

### 2.1 BC4 的通道数不等于光照语义

BC4_UNORM 的每个 4×4 块占 8 字节，包含两个 8 位端点和 16 个 3 位选择索引，解码后得到一个 [0,1] 标量。它本身没有独立的 R、G、B 光照通道。【标准 W1、W2】

因此，一次普通采样不能同时自由指定某位置的暖橙照明、另一位置的冷蓝照明及第三处的绿色照明。标量可以乘上已有 RGB 探针、太阳颜色或材质 tint，使最终画面带颜色；这些颜色来自其他输入。也存在空间打包、多次采样或查色表等编码可能，但本轮没有发现该项目采用这些机制的证据。【推断；依据 W1、W2】

“天空可见度”“太阳阴影”“AO”“总亮度”都可以编码成单通道图；BC4 格式、贴图尺寸和同名命名约定无法单独区分它们。Min/Max 的红通道超过 [0,1]，同样无法单独证明它就是 HDR 光照强度，因为这些字段的消费方式尚未建立。【推断；U1、C2、C4】

LDIAG1 证明完整绑定足以让指定的原生发光材质工作。它还可能同时满足了材质分支选择、对象资源登记或缺省资源避免条件。只复制一张路灯纹理并出现发光，不能证明纹理中的任意灰度会按某个乘法公式改变漫反射。【推断；实验前提 U1、C1】

### 2.2 Min/Max 的三个候选解释

| 候选 | 目前依据 | 可检验方式 |
|---|---|---|
| 仿射解码：`m = Min.r + q × (Max.r − Min.r)` | 常见量化还原形式；该项目未见消费端证据。【推断】 | 固定 DDS、UV、材质、位置，只改红通道范围，并在低动态范围、稳定曝光下测量。 |
| 资源统计／包围范围／流送信息 | `_probe_gain` 对 float4 组求 Min/Max，`native_textures.encode` 给普通纹理写固定范围。【代码 C2、C4】 | 修改范围无视觉影响只能增加该解释的可信度，不能独立证明字段完全无用途。 |
| 多用途参数，或由资源类型／材质分支决定 | 字段被多类资源复用。【推断；C2、C4】 | 对比具体运行时资源、常量绑定和不同原生 donor。 |

随附 `minmax` 实验使用相同的全 128 BC4 数据，对三个 tile 分别设置红通道范围 [0,1]、[0,2]、[0.25,1.25]，另保留一个原生范围。`--minmax-native` 生成对应的全原生范围基线，两个包在同一位置比较；G、B、A 的 Min/Max 不变。这样避免把探针的空间梯度误判成解码差异。【设计／合成验证 E1】

即使观察到大小不同的亮度变化，也应先写“Min/Max 对这条路径有影响”。只有多个 q、多个范围以及合适的线性量测同时吻合，才可进一步确认仿射公式。截图受曝光、色调映射、bloom 和截断影响，不能直接用像素比值证明 shader 乘数。【推断】

### 2.3 与探针、太阳、LIGHT_BRICK_MAP 的组合

本轮可以画出接口关系，尚不能给出 NBA 2K26 的确定渲染方程：【代码 C1–C3；未知消费端 E0】

```text
对象名、UserData、材质/Effect/Technique、UV7
                         ↓
                 同名 BC4 资源的候选采样
                         ↓
        未知的静态光照/可见度/遮挡运算
                         ↓
     可能参与探针、直接光、太阳或延迟光照的组合
                         ↓
          材质与发光贡献 → 后期 → 最终画面
```

以下三种关系都符合“单通道光照资源”这个表面描述，却会产生不同能力，不能任选其一当作事实：【研究假说】

```text
H_sun:   L = L_probe + m · L_sun + L_other + E
H_ao:    L = m · L_probe + L_sun + L_other + E
H_all:   L = m · (L_probe + L_sun + L_other) + E
```

也可能在 GBuffer 写入专用字段后由延迟光照 shader 消费。因此仅拿到某个物体 GBuffer PS，仍可能不足以定位最终组合；需追踪它输出的通道，以及后续读取该通道的光照阶段。【推断】

`LIGHT_BRICK_MAP` 与这个 BC4 标量是否存在直接联系，本轮没有确认。添加 Light 失败与 BC4 采样失败也不等价。新实验全部保持 Light、SH、brick 与 PostFX 不变。【U1、C10；设计 E1】

## 3. 写入途径：优先 DDS 别名，不伪造 TLD 解码

### 3.1 先分清三层格式

| 层次 | 本轮已知 | 本轮未知 |
|---|---|---|
| IFF 外层 ZIP32 | 现有 writer 对新／变更成员用 DEFLATE；原有压缩记录可原样复制。【C6】 | 与内部纹理元数据 33 的对应关系没有证据。 |
| DDS 内的 BC4 | 标准的块编码、mip 布局与头部可实现并测试。【W1–W4、E1】 | 新 DDS 在目标材质路径的实际加载／采样待测。 |
| 原生 TLD / Twiddled / CompressionMethod | 现有 `native_textures.py` 只写了另一种未分段头与原始块载荷，头中有常量 31。【C4】 | 不能从该 writer 推导 native 33 的解压方式、分段表或块排列。 |

**本轮不提供声称已验证的 Morton swizzler、TLD 33 压缩器或解压器。** 硬把 `.dds` 扩展名换成 `.tld`，或者在载荷前随意加一段头，都没有依据。【证据边界 E0、C4】

### 3.2 可直接实现的标准 BC4 DDS 布局

本工具写入线性、按块逐行存放的 DDS 数据。对 mip `l`：【标准 W1–W4；实现 E1】

```text
w_l = max(1, width >> l)
h_l = max(1, height >> l)
blocks_x = ceil(w_l / 4)
blocks_y = ceil(h_l / 4)
size_l = blocks_x × blocks_y × 8

mip_start(l) = DDS_header_size + sum(size_k, k < l)
block_offset(bx, by) = mip_start(l) + (by × blocks_x + bx) × 8
```

每块前 2 字节为端点，后 6 字节为 little-endian 选择位；第 `(x,y)` 个 texel 使用位移 `3 × (4y+x)`。具体两种端点插值分支及独立已知向量测试在 `codec_stdlib.py` 和 `test_lightmap_diag.py` 中。这里描述的是标准 DDS，不能外推到真实 Twiddled TLD。【W2、E1】

例如 64×64 到 1×1 共 7 级 mip，BC4 载荷为 **2744 字节**。普通 ATI1 DDS 总长 2872 字节，DX10 扩展头版本为 2892 字节。脚本写 `PixelDataSize` 为载荷长度，不包含头；对 donor 的声明 mip 数进行一致性检查并沿用，不强制把所有 donor 改成 7 级。【计算／合成验证 E1；头部标准 W3、W4】

### 3.3 本项目可复用的引用关系

```text
level.Texture[诊断对象名].Binary = "zgc_lmresearch_v1_texture.<16hex>.tld"
IFF 中新增成员                  = "zgc_lmresearch_v1_texture.<16hex>.dds"

Model 中 Binary 为 *.gz 时       → 现有解析器允许 *.bin 别名
本诊断新增几何直接引用 *.bin     → 保持 iff_codec 的写法
```

`repair_iff.py` 明确移除实验性的直接 `.tld` 成员，并沿 donor 的 DDS-only 路径封装；已有彩色发光纹理也走这个路径。这给出了绕开直接 TLD 编码的实际依据。能写标准 DDS 与已经确认新 BC4 资源受游戏支持，仍需分开标注。【代码 C2、C4、C5】

BC4 实验首轮采用 `--metadata clone`：复制 donor 的非尺寸元数据，保留 Twiddled、CompressionMethod、Min/Max，生成新的 DDS 别名。只有在后续单变量排查时才使用 `--metadata plain`，单独移除 Twiddled 和 CompressionMethod；不能同时换格式、换 UV、换光照范围，否则无法判断失败原因。【设计 E1】

即使 clone 或 plain 获得成功，也只能证明相应 DDS 加载路径可用，不能宣称 native TLD 的排列或 33 号压缩格式已被破解。【推断】

### 3.4 真正反解 Twiddled/33 所需的最小证据

应取得同一资源的原生 TLD 与 DDS 对照、至少一个非方形样本和多个 mip；先检查头、载荷长度、分段边界及逐块对应关系，再比较线性、块级 Morton、分块 tiled 等候选。必须在独立样本上建立可逆重建，并解释填充／mip tail／层布局。对于方法 33，要寻找实际枚举或解压消费端；不能仅凭可压缩性、文件后缀或开头两个字节选算法。【研究设计】

当前工具若遇到真实 TLD，记录头部十六进制并报告 DDS 解码不适用；不会尝试未经证实的解压。后续如需原生 TLD 字节，应作为明确指定的小资源追加到本研究目录，禁止扫描游戏安装路径。【工具 E1】

## 4. 给自制地面、墙、围栏接入 BC4 的条件

发光绑定示例使用路灯 UserData，但非发光接收面应优先选择一个**原生非发光物体与其实际材质配对**：该物体有同名 BC4、48 字节 UserData、匹配的静态顶点契约，并存在可用 Lightmap graphics 分支。脚本从输入包列出候选，不凭名称猜一个地砖材质。【设计；C1、C3、C7】

在诊断副本中需要追加的内容为：【代码契约 C1、C7；设计 E1】

| 条目 | 应满足的条件 |
|---|---|
| Object | 新名称、新 Target；与几何一致的 Matrix；复制所选 donor 的 UserData。 |
| Model / Prim | 保持静态原生布局；合法边界、索引、LOD；材质指向新增克隆；Duv7 对应独立 UV7。 |
| UV7 | 独立无歧义 chart；诊断面使用 [0.03,0.97]；与 UV0 分开控制。 |
| Texture[ObjectName] | 与新增对象同名；有效 BC4 描述；新 DDS 别名或完整原生对照资源。 |
| Material / Effect | 只克隆已存在并匹配的材质；保留原生 Effect/Script/Technique 绑定，不生成猜测参数。 |

**需要验证的关键开关是实际选中的 shader 分支。** 即便 Effect 同时声明了 AssetHires 和 AssetHiresLightmap，也不能仅看名称确认运行时用了后者。诊断保留 donor 整套材质及对象绑定；成功后再尝试对当前地面材质的最小接入。【C3；推断】

`_planar_uv7` 对 4 米平面足够。墙体多个朝向、围栏正反面与细杆叠在一张平面投影里会发生 UV 重叠；成品需真正展开独立表面，并按 mip 需求留出扩边。Duv7 是仓库按 UV 梯度计算的密度提示，现有代码无法证明它单独决定 lightmap 采样开关。【代码 C1、C7；推断】

原始场地坐标应先用当前包验证。旧 `ground-depth-current.json` 保存的 `part-0772` 只是历史数据，本工具没有使用这个编号。工具自动选择候选后还解码实际顶点、检查 Matrix、平面高度及 4 米区域的九个覆盖点；这对预期矩形球场足够作为诊断门槛，但九点检查不构成任意有洞网格的连续覆盖证明。【数据 C9；工具 E1】

## 5. 彩色路线与其他原生通道

### 5.1 第一选择：不透明 RGB 发光接收面

`_cornice_reflections` 已经克隆 sconce 材质并绑定四个资源槽：【代码 C2】

```text
AlbedoMap           保留接收面的颜色／纹理
NormalAndRoughMap   保留或匹配粗糙度与正常的法线输入
MetalMap            与表面材质一致；橡胶球场不能照抄金属檐口
EmissiveAlbedoMap   局部彩色光照贡献，未照到的位置为零
```

`AlwaysEmit`、`EmissiveTint`、`EmissiveIntensity` 也是已存在的参数。BC1/BC3 RGB 贴图写入已经有代码路径，因此这条路线不依赖先找到 RGB 的同名 lightmap。【C2、C4；U1】

成品应保留普通接收面的 albedo，只把需要添加的彩色漫反射贡献写入 emission。将完整“地面颜色 × 全部烘焙光照”再同时叠在已受光的 albedo 上，会重复加入已有照明。另一种方案是用整张烘焙结果承担全部可见表面颜色，但那需要验证普通 PBR 项如何关闭，且更容易削弱球员阴影与材质响应。【推断】

全黑 emission texel 不会使不透明几何透明；它只代表这条发光输入为零。实验中的灰色 tile 故意与原地面不同，用于识别覆盖位置。生产贴图若未匹配地面纹理、UV0、粗糙度与边缘亮度，会出现明显的方块接缝。【推断；材质结构 C2】

### 5.2 一张 emission 图无法解决的底光问题

用示意式表示静态接收面的目标：【设计模型，非引擎反编译结果】

```text
L_current(x) = B(x) + P_lamps(x)
L_target(x)  = B(x) + S_lamps(x)
E_add(x)     = max(S_lamps(x) − P_lamps(x), 0)
```

`P_lamps` 表示现有探针形成的粗粒度灯光，`S_lamps` 表示高分辨率烘焙结果。门框影中可能满足 `S_lamps < P_lamps`；正值 emission 无法补偿这个负差。应优先把“是否能让阴影区足够暗”列为验收条件，不要只看亮区够不够亮。【推断】

后续生产路线可以检验：BC4 是否衰减相关静态受光；当前材质 AO 槽能否压低相应分量；或原生 lightmapped 分支能否提供更可控的静态基础项。任何一个都需要实际测量，不能为了压暗静态地面直接削弱全局探针，否则会同时改变已经完成的球员照明。【设计；C1–C3】

静态烘焙可以让真实门框、围栏等几何在纹理里留下形状正确的阴影。移动球员不会自动对这张贴图产生新增灯光的动态投影；已有引擎阴影可能仍作用于普通 PBR 项，是否影响 emission 项也要单独观察。发光纹理不能证明新增实时灯、真实局部高光或动态投影已经接入。【推断】

### 5.3 已存在的其他参数与 RGB donor 搜索

当前杯子模板的 `ConeAngleMap` 在代码中被描述为原生 `cup_mat_ao.png` 的 LINEAR AO 图，修复代码用白图替代。它是一个值得研究的局部衰减入口，但白色中性端点仍被源码标为推断；其影响直接光、间接光还是更特定的遮蔽项尚未确证。该槽不能直接视为 RGB 发光输入。【代码 C3】

本轮没有确认 `LightMap2`、`RGBLightMap` 等额外材质参数。脚本会枚举输入包所有 Material.Resource 槽，导出相关 Effect、Technique、VS/PS 引用，并列出与对象／模型同名的非 BC4 纹理候选。不要因为资源格式是 BC6H、BC7、RGBA16F 就宣布找到彩色 lightmap；它可能是反射 cubemap、普通颜色图或探针 BYTEADDRESSBUFFER。【工具 E1；推断】

原生 RGB 路线的确认条件应同时包括：二维 RGB 资源、明确的对象或材质绑定、表面 UV 采样关系、消费端颜色运算、局部彩色图案在该接收面上的可重复游戏响应。只有格式和命名匹配，证据强度不够。【研究设计】

仓库中的室内 donor 路径可作为后续只读输入，例如 `nba2k-arena/donor/original/arena_020_int_original.iff`。本轮没有读取其真实载荷并确认 RGB lightmap；若本地只有 LFS 指针，工具会明确拒绝。外部共享资源缺失要记录为未解析，不应记录为不存在。【E0；工具 E1】

## 6. 三条候选路线的工程排序

评分表示在当前证据下的工程优先级，范围 0–10，属于研究判断，不是成功概率或已验证程度。【推断】

| 路线 | 可行性评分 | 需要新增／后续生产可能修改什么 | 主要风险 | 预计游戏画面 |
|---|---:|---|---|---|
| A. 原生不透明 RGB emission + 接收面底光协调 | **8/10**（彩色固定光斑）；完整动态光照能力不在此评分内 | 新材质克隆、RGB emission DDS、接收面 UV／小范围几何与完整绑定；后续成品优先整合原地面 draw，避免永久覆盖层 | 探针重复照明、阴影压不暗、bloom、粗糙度或边界不匹配；动态球员影不自动作用于新增光 | Chili’s 门口暖色光池、门框／栏杆固定影纹、表面纹理仍可见。 |
| B. 原生非发光 Lightmap 分支 + 同名 BC4 | **6/10**（局部明暗）；独立彩色目标 **2/10** | 新的配对 donor 材质、UserData、同名 BC4 DDS、独立 UV7、Duv7；后续可能接入现有材质的 Lightmap 分支 | 标量语义、分支选择、DDS 元数据处理未知；可能只影响太阳或天空，夜间无明显效果 | 成功时有可控制的明暗／遮挡图案；颜色主要依赖现有光照或材质。 |
| C. 当前 PBR 的 AlbedoMap 预调色／光照比值烘焙 | **7/10**（固定视感保底）；物理一致性较低 | 小范围材质副本与独立颜色图，保留现有非 lightmapped PBR；生产阶段需独立 UV 或 atlas | 灯光相乘两次、暗区没有足够基础光、颜色和曝光适应漂移；真实表面颜色被混入照明 | 可以有门口暖色区域和固定影纹，但暗场中不能靠 albedo 从零创造光，容易像画上去的颜色。 |

路线 C 可用 `A' = A × L_target / max(L_base, ε)` 作为调色起点，但 L_base 接近零、纹理色域饱和与引擎照明变化都会使该比值失效。它适合作为受限夜景的保底美术方案，难以替代独立加光。`ConeAngleMap` 可作为它的单独衰减实验，不能先假定其运算与 albedo 相同。【推断；C3】

**推荐顺序：先做 A 的同位置发光开／关实验，确认可控彩色采样；再用 B 测局部衰减及 UV7；只有 A 的深度、阴影或底光协调达不到要求时，才用 C 作保底。原生 RGB lightmap donor 搜索并行进行，未找到之前不让它阻塞可见成果。**【工程建议；C1–C5、U1】

## 7. 最小游戏内诊断设计

### 7.1 范围与控制变量

默认测试矩形位于世界 X=[−200,200] cm、Z=[500,900] cm，中心 (0,700) cm。四个 1.98×1.98 米不透明 tile，中间留下 4 cm 间隙，整体包围范围恰为 4×4 米。tile 0 位于低 X／低 Z，tile 1 高 X／低 Z，tile 2 低 X／高 Z，tile 3 高 X／高 Z；不要用摄像机画面“左／右”代替世界位置。【设计／测试 E1】

只追加四个模型、四个对象、四个克隆材质及少量纹理和缓冲。所有现有 SCNE 字段、Light、探针、brick、太阳和后期保持不变。每个实验都从同一份未含诊断的现行夜景包生成；不能把 B 实验叠到 A 实验结果上。【工具 E1】

默认几何抬高 `0.01 cm = 0.1 mm`，只用于避免严格共面。**这不是已验证的安全高度。** 仓库曾记录约 0.28 mm 的地面偏差及 depth bias 导致球员指示器被遮盖，所以即便更小的偏移也必须实测。工具不会写 DEPTHBIAS 或 SLOPESCALEDEPTHBIAS。出现指示器消失、闪烁或异常遮挡时，先停止覆盖层路线，不能把深度问题解释成贴图失败。【代码 C7、C8；设计 E1】

相机位置、比赛／回放模式、时间点和设置在配对实验中保持一致。优先观察 tile 内的图案与同位置变化，避免用全屏曝光变亮作为采样成功的证据。需要在比赛和回放分别验收，但每次配对比较应在同一种模式进行。【设计】

### 7.2 实验矩阵：看到什么，能证明到哪一步

| 阶段 | 两份对照的差异 | 观察及解释 |
|---|---|---|
| P0：只读 inventory | 不产生游戏修改 | 确认真实 IFF、donor、地面和资源别名；发现 LFS 指针、歧义或 round-trip 不一致就停止生成。 |
| E0/E1：RGB 关／开 | 同一组四面；`--emission-scale 0` 对比 1，其他新增数据相同 | 对应位置出现带红绿蓝角标、暖色光池和暗条的纹理，且随 intensity 改变，证明该 RGB emission 路径在地面诊断几何上可控。不能证明 BC4 灰度控制或动态投影。 |
| B0：原生绑定对照 | `bound-control`：四面都复制原生 BC4 描述及引用 | 先确认非发光 donor 的接收面能被看见；仅出现灰面不证明逐像素 BC4 已采样。 |
| B1/B2：BC4 正／反 | `bc4` 与 `bc4 --invert-bc4`；同位置 q→1−q | 常量面明暗在同位置交换，非对称图案也取反，支持 BC4 标量影响输出；比“出现一块暗面”证据更强。 |
| B3：UV7 单独翻转 | `bc4` 与 `uv7-flip`；纹理、UV0、材质相同，仅 UV7 水平翻转 | 第四面图案按预期镜像，强力支持图案按 UV7 采样。若只是整体变暗，不能确认 UV7。 |
| M0/M1：范围测试 | `minmax --minmax-native` 对比 `minmax`；相同 DDS，只改三面 Min.r/Max.r | 同位置稳定变化说明范围字段影响此路径；量测进一步吻合才支持仿射解码。完全无变化不能证明字段永远无用。 |
| T0/T1：描述符排查 | 上述同一模式的 `--metadata clone` 对比 plain | 若一种可用，说明其 DDS 元数据组合可行；无法由此推出真实 TLD 解码算法。 |

BC4 默认四面的内容为 q=0、q=128/255、q=1 和非对称三段加暗缺口图案。纹理尺寸沿用 64×64，按 donor 声明的 mip 数生成。独立 UV 翻转时不会同时翻转 DDS，从而保留明确的单变量检验。【工具 E1】

RGB 模式四面的原生 `EmissiveIntensity` 分别为 0、30、300、3000，可整体乘 `--emission-scale`。这些值仅用于寻找可见响应范围，不是流明、照度或既有灯具强度的物理换算。高强度 tile 过曝时只观察较低档；整个场景的自动曝光变化不构成局部采样证据。【设计 E1】

**测试中仍可能看不到 BC4 差异。** 可能原因包括分支未选择、绑定不完整、DDS 元数据不被接纳、q 被截断、受影响的太阳项在午夜接近零、材质项压过差异等。因此空结果应写成“此组合未观察到可辨识响应”，不能直接写“引擎不支持 BC4 lightmap”。【推断】

### 7.3 “只追加、可逆”具体指什么

`plan` 只输出 `additions.json`、`manifest.json` 和小型 `members/*.dds/*.bin`，不写 IFF。新增键全部位于 `zgc_lmresearch_v1:`；不会调用生产 `strip_scene`、`apply_scene` 或重新烘焙探针。【工具 E1】

`compose` 可选地把新增键并入内存文档，输出一份新的 `level.SCNE` 和小资源到另一个全新研究子目录。它要求原 SCNE 经 native 格式化后逐字节一致，并核验“移除恰好这些新增键”能逐字节恢复原 SCNE。诊断条目被改动或原场景有其他变化时，撤销函数拒绝大范围删除。【工具 E1】

最终如由项目原有封装流程执行游戏测试，逻辑上仍需**替换唯一的 level.SCNE 成员**并追加新资源。不能用 ZIP append 加入第二个同名 level.SCNE；不同加载器对重复项的选择不可靠。`native_archive.write_compatible` 的现有签名及字节保留能力已经核对，但本交付不调用它生成游戏包。【代码 C6；设计 E1】

应从现行 N17.2 夜景包保留所有原有压缩成员，额外替换 SCNE，加入新 DDS/BIN；不得以旧日景 donor 重新覆盖现有夜景数据。若后续协作者接入封装器，可调用本模块的 `build_replacements()` 取得小型 replacements 字典。本轮没有执行这一步封装。【设计】

实际撤销首选恢复测试前保留的输入包；输入包从未被本工具覆盖。需要逻辑撤销时，按 manifest 列出的精确键和精确资源名删除本次新增内容，并核对 baseline SCNE。不能按宽泛的 `zgc_` 前缀清理。【设计／合成测试 E1】

## 8. 成品烘焙的建议契约

本节是后续生产方案，不是本轮已完成的 Cycles 烘焙。【研究设计】

### 8.1 复用灯光定义，改变采样目标

现有 `bake_probes.py` 每个探针渲染全景并投影成 SH9；表面 lightmap 应沿接收面的 UV texel 求解光照。不能把 probe panorama 或 SH 缓冲直接当成地面 RGB lightmap。可复用灯组、只开指定夜灯、关闭额外世界光和旧 emission、修复缺失图像等准备逻辑，新增独立的表面烘焙入口放入本研究目录，不改原有 bake 文件。【代码 C11；设计】

两套坐标关系要分别保留：【C1、C11、C12】

```text
自制模型 cm → 游戏世界 cm: (x,y,z) → (-x,y,-z)
游戏世界 cm → Blender m: (X,Y,Z) = (-world_z/100, -world_x/100, world_y/100)
```

读取 `source/scene.blend` 后的材质与 UV 试验只在内存或研究目录副本中进行，不保存覆盖原场景。烘焙输出按 a_signs、chilis、boots、floodlight 分组，保持与现有灯组相同的相对色彩和遮挡几何。探针导入时采用的增益也要记录，避免表面烘焙与球员照明使用无法解释的比例。【C11、C12；设计】

### 8.2 保存什么量

建议输出 scene-linear、未套用游戏后期的漫反射贡献，区分直接／间接贡献与颜色是否已乘入。可以采用去除表面颜色的照明 bake 后乘一次 albedo，或直接保存已包含接收面颜色的漫反射结果；两者不能再次叠乘。理想 Lambert 接收面的示意关系为 `L_diffuse = A_linear × E_irradiance / π`，但具体 Blender pass 的归一化要通过白色参考面校准，不能机械地再除一次 π。【渲染模型／研究设计；烘焙基础 C11】

不把相机相关镜面高光、已有后期 bloom、球员或 UI 烘焙进固定贴图。阴影必须来自与游戏几何一致的墙、门框和围栏，而非在整块地面上随意涂暗。透明门窗和细网格的遮挡设置需要与最终游戏表现一致，否则会出现烘焙遮光、游戏看起来透光的冲突。【设计】

RGB 贡献存在 HDR 范围时，先选一个记录在 manifest 的曝光／比例，把纹理规范化到可存储范围，再用原生强度参数校准。不要依靠修改全局 PostEffect 弥补单块地面的色彩错误。仓库颜色 DDS 与 `TexelUsage='LINEAR'` 的惯例可以复用，但最终 emission SRV／shader 的色彩空间仍需通过灰阶和彩色角标确认。【代码 C4；设计】

本交付的 RGB mip 使用简单 box 平均，仅服务于诊断图案；它不是高质量生产纹理管线。成品颜色 mip 应在线性空间处理，带 UV 岛扩边，并控制暗边、泄漏和远距离闪烁。【工具 E1；设计】

### 8.3 分辨率和几何接入

4 米面用 64 texel 时，每 texel 约 6.25 cm；512 texel 时约 7.8 mm；1024 texel 时约 3.9 mm。这些数值未扣除 UV padding。诊断每个 1.98 米 tile 使用 64 图及 94% UV 跨度，实际约 3.3 cm/texel。薄围栏影和细门框边界通常需要比原生小图更高的局部分辨率，或为受光区域拆分独立 chart。【计算／设计】

较大 BC4 是否被原生逐物体路径接受尚未验证。应先通过 64×64，再单独测试尺寸和 mip 改变。RGB emission 的扩大同样需要实际检查流送、远距离 mip 与比赛／回放差异。【设计】

墙面和实心围栏部件可考虑紧贴原几何的接收层；网孔不能被完整不透明矩形封住。地面生产版最好整合进原有地面 draw 或对原模型进行明确的小区分割，减少永久重叠层和指示器深度风险。这类生产修改不在本轮只读交付范围中。【C8；设计】

## 9. 工具交付、测试与验收边界

| 文件 | 作用 |
|---|---|
| `lightmap_diag.py` | inventory；生成 additive plan；可选 compose；内存内精确撤销；从不输出 IFF。 |
| `codec_stdlib.py` | 标准 BC4 DDS 编解码、诊断级 BC1/BC3 写入、原生静态平面缓冲；没有 TLD 33 编解码器。 |
| `test_lightmap_diag.py` | 人工合成场景、已知编码向量、控制变量、只追加与撤销、CLI 串联及路径保护测试。 |
| `README.md` | 可直接执行的命令、输入限制、实验次序与输出说明。 |
| `evidence/synthetic_tests.txt` | 本轮真实执行的测试日志。 |
| `evidence/PROVENANCE.json` | 固定提交、源文件 blob 标识、访问范围与用户数据边界。 |
| `evidence/diagnostic_contracts.json` | 合成输入的各实验新增条目与小资源体积；明确不代表真实 IFF。 |

**本轮 35 项合成测试全部通过。** 测试覆盖 BC4 两种端点模式的独立已知向量、完整 mip 长度、矩形图尺寸、BC1/BC3 头部和载荷、地面坐标／UV7／三角绕序、所有实验的精确可逆性、UV7 与 Min/Max 的单变量对照、RGB 开关、输入 LFS 指针拒绝、路径逃逸与覆盖拒绝，以及 inventory→plan→compose 全流程。合成 shader 只是显式标注的占位字节，不被执行。【数据 E1】

输入只读，必须位于项目 `nba2k-arena/` 内；不会递归寻找游戏目录。输出只能是本研究目录下的全新子目录；已有目录不会被覆盖。不会导入生产 tools，不创建生产模块的 pycache，不依赖 numpy、Pillow 或 Blender Python。工具仅记录 SCNE 与中央目录指纹，不读取全包计算 SHA；指纹不能当作全包密码学身份验证。【工具 E1】

真实样本验收仍需完成：有效 donor 识别；真实材质资源与 shader 依赖闭合；新增 DDS 被加载；实际 Lightmap 分支；UV7 图案采样；RGB emission 地面表现；阴影对比；球员指示器；比赛和回放两个入口。离线 CRC、字节格式或合成测试通过不能替代这些验收。【证据边界】

## 10. 来源与证据索引

### 代码、仓库记录

所有 C 编号固定到同一研究提交；“代码里的历史记录”不等同于本轮重新运行游戏。

- **C1**：[`tools/night_scene.py` L1–214](https://github.com/Bohan-java/Vibecad-bait/blob/abd8643af109fd93720595157b8f4792f0e14bcb/nba2k-arena/zgc-court/tools/night_scene.py#L1-L214)：LDIAG1 历史、同名纹理、UserData、UV7、Duv7、坐标及清理前缀。
- **C2**：[`tools/night_scene.py` L215–550](https://github.com/Bohan-java/Vibecad-bait/blob/abd8643af109fd93720595157b8f4792f0e14bcb/nba2k-arena/zgc-court/tools/night_scene.py#L215-L550)：probe Min/Max、彩色 sconce 资源槽、发光与檐口反射。
- **C3**：[`tools/r04_materials.py`](https://github.com/Bohan-java/Vibecad-bait/blob/abd8643af109fd93720595157b8f4792f0e14bcb/nba2k-arena/zgc-court/tools/r04_materials.py)：AssetHires/AssetLores 输入、native AO 槽、非 lightmapped 路径。
- **C4**：[`tools/native_textures.py`](https://github.com/Bohan-java/Vibecad-bait/blob/abd8643af109fd93720595157b8f4792f0e14bcb/nba2k-arena/zgc-court/tools/native_textures.py)：BC1/BC3 DDS、mip、TLD 头、固定范围及 LINEAR 标签。
- **C5**：[`tools/repair_iff.py` L1–185](https://github.com/Bohan-java/Vibecad-bait/blob/abd8643af109fd93720595157b8f4792f0e14bcb/nba2k-arena/zgc-court/tools/repair_iff.py#L1-L185)：native dump、别名、移除直接 TLD、PostFX 检查。
- **C6**：[`tools/native_archive.py`](https://github.com/Bohan-java/Vibecad-bait/blob/abd8643af109fd93720595157b8f4792f0e14bcb/nba2k-arena/zgc-court/tools/native_archive.py)：ZIP32 writer、原压缩记录保留、新／变更成员处理。
- **C7**：[`tools/iff_codec.py` L1–210](https://github.com/Bohan-java/Vibecad-bait/blob/abd8643af109fd93720595157b8f4792f0e14bcb/nba2k-arena/zgc-court/tools/iff_codec.py#L1-L210)：SCNE、8/4/12 静态几何布局、UV7、平面量化与 Duv。
- **C8**：[`tools/ground_depth_policy.py`](https://github.com/Bohan-java/Vibecad-bait/blob/abd8643af109fd93720595157b8f4792f0e14bcb/nba2k-arena/zgc-court/tools/ground_depth_policy.py)：指示器与深度偏差历史、地面识别条件。
- **C9**：[`validation/ground-depth-current.json`](https://github.com/Bohan-java/Vibecad-bait/blob/abd8643af109fd93720595157b8f4792f0e14bcb/nba2k-arena/zgc-court/validation/ground-depth-current.json)：旧地面编号与未复验状态。
- **C10**：[`docs/light-brick-research/LIGHTING_RESEARCH_V2_ZH.md`](https://github.com/Bohan-java/Vibecad-bait/blob/abd8643af109fd93720595157b8f4792f0e14bcb/nba2k-arena/zgc-court/docs/light-brick-research/LIGHTING_RESEARCH_V2_ZH.md)：前期研究边界、清理风险与静态／动态验证区分。
- **C11**：[`bake/bake_probes.py` L1–180](https://github.com/Bohan-java/Vibecad-bait/blob/abd8643af109fd93720595157b8f4792f0e14bcb/nba2k-arena/zgc-court/bake/bake_probes.py#L1-L180)：全景 SH 烘焙、关闭环境光、重链图像、坐标及不保存 blend 的约定。
- **C12**：[`bake/bake_lights.json`](https://github.com/Bohan-java/Vibecad-bait/blob/abd8643af109fd93720595157b8f4792f0e14bcb/nba2k-arena/zgc-court/bake/bake_lights.json)：灯组、颜色、功率与 Blender 坐标。

### 标准与本轮数据

- **W1**：[Microsoft：Texture Block Compression in Direct3D 11](https://learn.microsoft.com/en-us/windows/win32/direct3d11/texture-block-compression-in-direct3d-11)：通道数、块尺寸、ATI1 对应关系。
- **W2**：[Microsoft：Block Compression (Direct3D 10)](https://learn.microsoft.com/en-us/windows/win32/direct3d10/d3d10-graphics-programming-guide-resources-block-compression)：BC4 编码、端点插值、mip 填充。
- **W3**：[Microsoft：DDS_HEADER](https://learn.microsoft.com/en-us/windows/win32/direct3ddds/dds-header)：124 字节主头、尺寸、mip 与 flags。
- **W4**：[Microsoft：DDS_HEADER_DXT10](https://learn.microsoft.com/en-us/windows/win32/direct3ddds/dds-header-dxt10)：格式与 Texture2D／array 描述。
- **U1**：本次用户任务中明确给出的原生贴图统计、Min/Max 示例、LDIAG1 游戏验证、sconce 绑定经验及约束；未作为本轮独立取证结果。
- **E0**：GitHub 分支 API 与目标 IFF 的 LFS 指针读取。详情见 `evidence/PROVENANCE.json`；实际 IFF/DDS/shader 字节未取得。
- **E1**：本目录工具与实际合成测试日志 `evidence/synthetic_tests.txt`。测试输入完全人工构造，不代表原生游戏包。

**最终建议：先通过 4×4 米区域的同位置彩色开／关与 UV7 图案实验，再决定生产接收材质。彩色烘焙路线具备现成原生入口；BC4 的语义与静态底光协调是需要继续解决的两个关键问题。**【推断；C1–C5、U1、E1】
