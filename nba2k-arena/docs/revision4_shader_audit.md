# Revision 4：新增景观材质的原生 shader 与调度审计

审计日期：2026-09-06。审计对象为 `revision3_mesh.make_unbaked_material()` 当前复制的原生 `layer_base_CLOD.fx#72407e286031da1b / Default`，并读取最终 IFF 核对复制结果。本次只新增此报告，没有修改模型、材质、编译 shader、游戏目录或远端仓库。

## 结论与交付边界

1. **该 Default PS 确实计算实时逐灯光照与 IBL，不是 unlit。** 已从原 DXIL 追到最终 RGB 写出，证据包括世界位置查询光照网格、方向/位置/颜色不同的灯、法线与灯方向点积、随粗糙度变化的高光、cubemap 采样、可见度乘数及最终求和。不能因为它只有一个颜色目标就说它未计算光照。
2. **它不需要该物体的 UV7 烘焙光照图；它仍需要引擎绑定的全局光照资源。** “不需要物体 lightmap”不能扩展成“无需场景 IBL、光照网格、屏幕空间遮挡或 shader 全局参数”。原室内 IBL 也不会因换成这条路径自动成为室外天空。
3. **尚无证据证明新增普通 OBJECT 一定能进入这个 Default-only effect。** 原 `Default.EnableMask=2` 和单目标 HDR 颜色输出都是真实原生配置，但原 donor 的相同材质还有 Hires/Lores 等 technique；原 level 没有只保留 Default 的材质参照。新增对象是否自动选择 mask 2、缺少请求的 technique 时是否 fallback、引擎是否生成其全局可见度输入，均不能由 IFF 静态检查证明。
4. **`OnlyDepthCSM` 的移植是 shader/资源布局兼容的深度投射候选，并非日影已验证。** 原始 CSM pass 与 Default depth prepass 的 VS/PS/ResourceMapping 完全一致，当前输出完整复制原 CSM 深度状态与 pass mask 64。其是否被调度、接收端的屏幕空间可见度是否包含这批树，仍需游戏验证。
5. 本次没有发现可凭现有数据安全修正的 mask 或 pass 别名。**保留当前隔离实现、明确运行时未验证，比扩展 mask 或把 HDR 颜色伪装成 GBuffer 更有依据。** 如果目标是“游戏里一定能显示并受到正确日照”，本报告不是通过验收；需要原生运行时证据或同类型、已运行的未烘焙静态对象 donor。

建议对外描述为：**“采用已核实的原生逐灯/IBL shader；几何、资源引用和材质复制已静态核验，2K 引擎调度与实际日影未验证。”** 不应称“黑树已在游戏修复”或“室外动态光照已经验证”。

## 证据身份与分析方法

| 项目 | 身份 |
|---|---|
| 原始 donor | `donor/original/arena_020_int_original.iff` |
| donor SHA-256 | `42865ecaf8dd923c4d901509263af3b242c00975f4284b917ba79ce8fbbced46` |
| 原始材质 | `clutchtime_floor_apron:floor_mat` |
| 原始 effect | `layer_base_CLOD.fx#72407e286031da1b` |
| 原始 Default VS | `VS.3e4e8775aa14fa50.shader` |
| VS SHA-256 | `66364e949eb1f86e2052a1bac70e31f8c268f2cd5be99d5a403c0dd21cd93bc8` |
| 原始 Default PS | `PS.5e38eeba1e81863d.shader` |
| PS SHA-256 | `11fa32b853e7d4b235352f720b2d0b0d3633611678ee843429d9bfc093d695fe` |
| 当前新增 effect | `venice_v3:unbaked_layer_base_CLOD` |
| 本次读取的最终 IFF SHA-256 | `9bdb9f341d40cbdc22d0285ce456fca8234ee32bec1854011213ea78c9f5cc99` |

PS 原 DXBC 容器有 `SFI0/ISG1/OSG1/PSV0/HASH/DXIL`，DXIL chunk 为 24,404 字节。读取原 `BC c0 de` bitcode，使用已有 Apple clang 反汇编；为使 clang 接受旧 DXIL datalayout，仅在 `/private/tmp/revision3_shader_research` 的分析副本里将 `i8:32` 改为等长 `i8:08`，未编辑归档内任意 shader。clang 只做 `-S -emit-llvm -x ir`，没有重新编译或替换游戏 shader。

下文 `%n` 指该分析副本 `default_ps.ll` 中 `VCMain` 的 SSA 值，不是作者推测的 HLSL 变量名。资源含义以实际访问方式说明；原 bitcode 的资源名称为空字符串，不能凭寄存器号编造引擎全局资源名称。DXIL 的 `sampleLevel`、`textureLoad`、资源坐标和数值运算语义按 [Microsoft DXIL specification](https://github.com/microsoft/DirectXShaderCompiler/blob/main/docs/DXIL.rst) 核对。

## 从输入到颜色的完整计算链

| SSA 范围 | 已核实的计算及后续用途 |
|---|---|
| `%1–67` | 建立固定全局资源和 bindless 材质纹理/采样器 handle；读取 pixel 输入。PS 实际读取 TEXCOORD0.xyz、1.xyz、2.xyzw、3.zw、SV_Position.xy、SV_IsFrontFace；不读取声明中的 TEXCOORD8。 |
| `%68–125` | 从切线、法线、handedness 重建副切线；根据正反面翻转几何法线；从相机参数和世界位置构造视线方向；用材质仿射参数变换真实 UV。 |
| `%126–147` | albedo 采样与线性调色，读取 albedo alpha 并决定是否执行这一层的材质属性计算。当前所有新 albedo 为不透明；PS 最终输出 alpha 恒为 1。 |
| `%148–233` | 读取 NormalAndRoughMap.RG/A；RG 经 NormalHeight 还原切线空间法线；读取材质 metalness 常量及 emissive 常量/tint，按 TintEmissiveWAlbedo/AlwaysEmit 分支计算 emissive。 |
| `%234–261` | 用几何法线屏幕导数增加粗糙度下限；切线空间法线转为世界法线并归一化。 |
| `%262–345` | 当全局 flags 的 bit 8（256）设置时，从屏幕纹理混合 albedo、roughness、normal、层遮挡量与 emissive；否则保留上述材质结果。 |
| `%346–502` | 根据几何法线、扰动法线、视线、层遮挡和屏幕遮挡计算漫反射/镜面遮挡权重；由 roughness 构造后续镜面分布参数；由 metalness、albedo 和 F0 形成 RGB Fresnel 基值。 |
| `%503–1636` | `ConstantIsolate != 0` 时，按世界位置查 IBL 网格及最多四个局部 probe，求盒/胶囊影响权重；用世界法线采 cubemap 的漫反射 mip 5，用反射向量及 roughness-dependent mip 采镜面；未被局部 probe 覆盖的权重有全局 cubemap fallback。包含 wave-uniform 与非 uniform 两条等价遍历分支。 |
| `%1637–1783` | 可按全局 flags 切换到/混合屏幕空间环境漫反射和反射输入，并可根据额外屏幕方向数据调整漫反射方向响应；不是物体 UV7 lightmap 采样。 |
| `%1784–1866` | 对环境光按世界高度调制；采视角/roughness BRDF LUT；与 metalness/Fresnel、漫反射/镜面遮挡权重相乘，得到初始 diffuse/specular RGB 累加器。 |
| `%1867–2052` | 再按世界位置查灯网格，结合全局灯位掩码、wave 位遍历选择灯；此处不读取物体 lightmap UV 或物体烘焙 lightmap 索引。 |
| `%2053–2192` | 读取每灯 type/flags、位置、方向、距离衰减及颜色相关数据，构造 L；type 0 使用负方向而非位置差，type 3 有线段/区域几何处理；按灯 flags 和全局 flag 读取逐灯屏幕可见度，并与角度/距离衰减结合。 |
| `%2193–2303` | 普通灯使用 `saturate(dot(N,L))`；线段类型积分其法线响应；乘衰减、灯 RGB 与全局强度得到该灯 diffuse。 |
| `%2304–2559` | 当每灯 flag 524288 设置时计算 specular；普通灯包含 roughness 分布/可见度和五次 Schlick Fresnel，线段类型使用 roughness/视角 LUT 和几何积分；关闭该位则此灯 specular 为零。 |
| `%2560–2627` | 按灯近范围条件剔除贡献；某类灯应用前面的 diffuse/specular 遮挡权重；分别累加逐灯 RGB。 |
| `%2628–2678` | 完成灯遍历；以 albedo、非金属比例和介电漫反射比例乘 total diffuse，再加 total specular 和 emissive；写唯一 HDR SV_Target0，alpha=1。 |

### 法线、粗糙度、metalness 不是无效中间量

材质 b12 的偏移由原 Effect.Parameter 验证：`AlbedoMap=160`、`NormalAndRoughMap=164`、`NormalHeight=44`、`MetalMap_DEFAULT=0`、`ConstantIsolate=152`。

`%165` 的采样只提取 R=`%166`、G=`%167`、A=`%168`；B 不提取。其数学式为：

```text
nx = (2*R - 1) * NormalHeight       [%170–175]
ny = (2*G - 1) * NormalHeight
nz = sqrt(saturate(1 - nx² - ny²)) [%176–181]
N  = normalize(nx*T + ny*B + nz*Ng) [%248–261]
r0 = max(texture.A, pow(saturate(max(|ddx Ng|², |ddy Ng|²)), 0.333))
                                           [%234–247]
r  = optional_screen_roughness_blend(r0)     [%284–291]
alpha = saturate(r² + 0.0055242716)          [%378–380]
alpha2 = alpha²                             [%381]
```

`r` 在 cubemap specular mip（例如 `%669=5*r`）、环境 BRDF LUT `%1804`、线段 LUT `%2394/%2489`、普通灯高光 `%2498–2544` 中均有实质使用。`MetalMap_DEFAULT.x` 经 `%183→%228`，与材质 albedo 形成 `%500–502 = lerp(F0, albedo, metalness)`；当前不透明层 F0 约 0.04。这与 floor shader 中的 BaseMaterialTexture.R 完全不同，不得跨 shader 套用通道解释。

最终输出明确为：

```text
m = %228; F0 = %229; A = (%281,%282,%283)
totalDiffuse  = (%2651,%2650,%2649)
totalSpecular = (%2648,%2647,%2646)
emissive      = (%343,%344,%345)
smallCorrection = max(A*0.00049972534 + 0.99960005283, 1)
RGB = totalSpecular + emissive
    + A * (1-m) * (1-F0) * totalDiffuse * smallCorrection
```

因此仅改变法线、roughness 或灯资源便能在本 PS 数学上改变输出；并非先计算照明再丢弃。

### IBL 证据与资源依赖

`%9` 是 t12/space0 的 TextureCubeArray。`%796` 以世界 N.xyz、probe slice `%684`、mip 5 采样 diffuse；`%988` 以反射方向（可做盒/胶囊视差修正）、同一 slice、mip `%670` 采样 specular。其 RGB 经加权求和进入 `%1631–1633` 与 `%1628–1630`，最后进入 `%1861–1866` 及输出。原保留下来的 alias metadata 也明确出现 `IBL_Sample_Multiple`、`IBL_Sample_Multiple_Internal`、`Lighting_AmbientDiffuseAndSpecular`，与实际计算吻合。

局部 probe 由 t5 结构化网格、t8 80-byte probe records 和 b9 参数共同选出。没有局部 probe 时不是直接固定白色：`%1012–1098` 仍采 cubemap array 的全局 slice（通常由参数选择为 0 或另一 slice）并乘剩余权重。**如果引擎没有绑定有效 cubemap，或仍绑定室内烘焙 cubemap，这条 shader 不会自行生成正确的室外环境光。** 原 donor 的 `IBL1` 与所有已检查 PillIbl markers 为 `VC_IsLitDynamically=0`；其运行时资源创建及更新不在本 PS 中，不能把 Default 的逐灯能力说成这些 probes 已动态重采样。

### 直接光照与阴影：确认到了哪一级

逐灯 t9 是 80-byte StructuredBuffer。可逐条验证以下链路：

- `%2063 = flags & 3`，type 0 的 L 来自负的灯方向，其余常规类型来自 `lightPosition - worldPosition`；归一化为 `%2145–2147`。
- `%2288–2289 = saturate(dot(N,L))`，随后 `%2292` 乘角度、距离和可见度乘数组合 `%2192`。
- 灯 RGB 从同一 record 的 byte 48.xyz（`%2293–2295`）读出，乘 b4 row17.x 得 `%2298–2300`，再与 diffuse/specular 权重相乘；由 `%2621–2626` 实际累加到输出。
- 当灯 flag `1048576` 设置、角度项为正，且 b6 row2.x 的 bit 0 设置时，`%2169` 从 **t6 Texture2DArray 的当前屏幕 x/y、当前灯计数 slice** 读取 R；`%2173 = min(angleTerm, sampledR)`，再进入 `%2192`，所以它是能抑制此灯照明的逐灯可见度输入。
- b4 控制的 t10 屏幕 R 值 `%450–451` 另用于 diffuse/specular 遮挡；不同灯 flag 决定是否把这些遮挡权重再次用于直接光。该资源不是 NormalAndRoughMap 的 B/A，也不能通过调整树的局部纹理填充。

**本 Default PS 没有 `sampleCmp`、`sampleCmpLevelZero` 或任何 CSM 深度矩阵投影。** 它消费已处理的屏幕空间可见度，未在这个 shader 内直接采 cascade depth texture。把 t6 解释为“逐灯屏幕可见度”有访问与乘法证据；它具体由哪个引擎 shadow/RT pass 生成、Sun 是否被放进对应灯列表及 slice，尚无运行时 capture，不能进一步断言。

`OnlyDepthCSM` 解决的是潜在 caster pass 的描述，不等于为接收方建立了上述可见度资源。`VC_CastsShadows=1` 也只是场景请求，不能证明 caster 或 receiver 被实际执行。

实际 donor 与本次最终 IFF 的 Sun 对照：`Type=DIRECTIONAL`、`Intensity=3`、原颜色/方向/Rotate 与 `vc_ingame_light=1` 均保留；只有 `VC_IsActive` 和 `VC_CastsShadows` 从 0 变为 1。TIME_OF_DAY 启用天空和时段系统，并保留原中午参数。其与直接 Sun 的运行时优先关系、灯 buffer 的实际条目与阴影 slice 没有 capture 证据。

## 原生 technique/mask 与目标格式审计

首先更正字段称谓：donor 中是 `Effect.Technique.Default.EnableMask=2` 与 `Material.Technique.Default.EnableMask=2`。原 level 的 792 个 OBJECT 和 67 个 Models 均没有 `TechniqueEnableMask` 字段；不能向新 OBJECT 凭空添加此字段。

| 原生位置 | mask 与实际格式 | 能证明的内容 |
|---|---|---|
| apron Default technique | 2 (`0x2`) | 是 donor 自带的独立 technique 位；不是新定义的常量。 |
| Default color pass | 1，SV_Target0=float4/R11G11B10_FLOAT，D32_FLOAT_S8X24_UINT | PS 已输出完成照明的 HDR 颜色，是单目标 forward-style 路径；不需要在此 pass 再输出材质 GBuffer。 |
| Default.DepthOnlyPrepass | 2048，COLORWRITEENABLE=0 | 原生位置-only depth/prepass；其原 stencil 状态及材质覆盖完整保留。 |
| Default.DepthVelocityPrepass | 128，COLORWRITEENABLE=0 | 原生位置-only depth/velocity 路径，完整保留。 |
| HiresLightmap / LoresLightmap | 67108864 (`0x4000000`) / 134217728 (`0x8000000`) | 是不同 technique 位，不能仅靠名字把它们当 Default 的自动 fallback。 |
| 原 Hires.GBuffer | pass 512；Target0 SRGB、Target1 uint4、Target2 uint2、Target3 uint2、Target5 HDR | 五个明确的编码目标；其 VS 另消费 UV3/UV7，PS 与 Default 不同。不能把单 HDR output alias 到这里。 |
| 原 Hires.OnlyDepthCSM | pass 64；D16_UNORM，COLORWRITEENABLE=0，CULLMODE=CW，CLIPPING=0 | VS/PS/ResourceMapping 与 Default.DepthOnlyPrepass 完全相同，原深度状态亦已复制。 |

Default color pass 的 `BakePso=1` 是 PSO 配置字段，不能据此把它称作“烘焙光照 shader”。PS 中真实执行的计算已如上核实。

核对本次最终 IFF：原 Default technique 除新增 CSM pass 外的所有字段、三个原 passes 的完整内容，与 donor 相同；Default VS/PS 原始字节相同；新材质保留原 Script、Parameter/Resource 定义、Default pass 覆盖，并只替换相应纹理/调色/NormalHeight。保留 opaque 的 ResourceMapping 原串（其文本 SHA-256 为 `b22ab6b840a530f5aa8a24b7edd8b1c640dfc4d62eba9b54022018c45fb0f593`）。这证明复制没有破坏原绑定描述，**不证明实际 command list 中已经把其全局 SRV/CBV 填入**。

### donor 的参照足够与不足

- 原 level 共 34 个 effects，其中 30 个 generic effects 的 Default 都是 mask 2、三个 color/depth passes；七种 `layer_base_CLOD` 均如此。当前 mask 2 及三个原 pass 的组合有广泛原生参照。
- 然而原 level 材质中，**只有 Default 一个 technique 的数量为 0**。同类 generic 还包括 Hires/Lores/Mirror/Reflection/RT 等 technique。这里没有可以直接证明“删掉其它 technique 后，新的未烘焙普通静态物体一定画入主场景”的原例。
- LED 的 IBLDynamic 使用 mask `0x100000000`，另有自己的 VS/PS；其常规 Default 还支持多个静态 mask 和完整的 GBuffer/shadow passes。它证明引擎有其它调度模式，不能证明将 mask 或名字挪给 layer shader 就兼容。
- 原 level 的 792 个 OBJECT 中有 791 个带 UserData；唯一没有的是带 `VC_IsReflection=1` 的 LED dorna。当前新增 OBJECT 是普通 `{Type,Target,Transform,Matrix}`，没有 UserData。UserData 缺失是否代表未烘焙、默认渲染分类或其它状态未解码，既不能据此断言有效，也不应把某个室内 donor 的 opaque bytes 随机复制过去。
- 由“完整 lit PS + 有效单目标格式”可以判断其 shader 数学意图；由现有 IFF 不能判断 game mode/quality/对象分类究竟请求 mask 2、Hires、Lores、GBuffer 还是其它模式。

## 目前没有可以声称完成的调度修补

不做以下无证据变更：扩 Default mask 为 Hires/Lores 位的并集；重命名/alias Default 到 GBuffer；为普通新对象复制未知 UserData；保留原 UV7=0 的 Hires/Lores color 再宣称已经获得正确 lightmap；随意把 `VC_IsLitDynamically=1` 当作已完成的 IBL 更新。

可独立执行的下一步验收是游戏内对同一简单不透明平面/立体网格进行 A/B capture：确认主视图对它实际选用的 technique/pass、绑定格式和 SRV/CBV；检查 mask 2 的 draw 是否出现；分别改变太阳方向、roughness 和 IBL 内容，观察受控结果；确认树作为 CSM caster 及 receiver 都存在。这是补齐缺失证据的方案，不是本次已执行测试。

若后续找到原生已工作的普通未烘焙静态对象，优先整体复用它的对象分类、完整 effect/material/资源布局，再按实际 shader 输入调整网格。只有在证明最终渲染目标语义和调度路径兼容后，才调整当前隔离实现。

本次没有运行 2K，没有安装建模/反编译软件，没有推送；所有“运行时未验证”标记应继续保留。
