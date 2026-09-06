# R5 地面填充层审计：只读结论

审计输入为当前 `output/revision4/arena_700_int.iff`，SHA-256：

`a080b341e194a8f670ad0d26e524e64dbd6ac6d88e51173e32be54d803ea96bd`

本次仅新增本文；未改代码、场景、材质或候选包。结论基于该 IFF 内 `level.SCNE` 的实际 Material/Effect、实际 floor VB/IB，以及先前从原 shader 解出的 DXIL 分析副本。

**推荐组合：完整复制原 base floor 材质，换正常浅灰扫描漫反射；填充几何从区域轮廓中扣除全部现有标线投影；以独立材质的有限深度偏移避免与原底面闪烁。仅把填充 bias 放在底面和白线之间，不足以保证不盖白线。**

## 1. 当前实际材质与有效 pass 状态

合并方式为 `Effect.Technique[tech].Pass[pass]` 加该 Material 同路径覆盖。下表的偏移与 ZWRITE 均为合并后的值。所有列出的 floor pass 在 Effect 和 Material 中都**没有 `ZFUNC` 字段**；不应把本项目 WebGL 预览的 `LESSEQUAL` 默认值说成已确认的 NBA 2K 原生状态。

| 材质 | Effect | Default 像素 shader | ZWRITE | DEPTHBIAS / SLOPESCALEDEPTHBIAS | Default 混合 |
|---|---|---|---:|---|---|
| `floor_clutchtime_court:area_1_mat` | `floor.fx#1e7aabcf0cf28f1c` | `PS.0cfd5246b9c1587a.shader` | 1 | 0 / 0 | ALPHABLEND=1，SRC=ONE，DEST=ZERO |
| `floor_clutchtime_court:floor_line_mat` | `floor.fx#64ea5c821566f830` | `PS.008c1d91c7e3d2a9.shader` | 0 | −4 / −4 | ALPHABLEND=1，SRC=SRCALPHA，DEST=INVSRCALPHA |
| `floor_clutchtime_court:floor_line_mat1` | 同上 | 同上 | 0 | −4 / −4 | 同上 |
| `venice_v3:court_white_lines` | 同上 | 同上 | 0 | −4 / −4 | 同上 |
| `venice_v3:court_lane_space_marks` | 同上 | 同上 | 0 | −4 / −4 | 同上 |

前三种原生材质的 `Effect` 和对应覆写继承自 donor；R3 白线材质是 `floor_line_mat1` 的完整复制，只换了漫反射引用与颜色调制。Effect 本身 Default 的 ZWRITE=1、bias=0；**线的 ZWRITE=0、bias=−4 是 Material 覆写，不能只读 Effect 就判定线会写 depth。**

完整相关路径如下：

| Technique / Pass | base floor 有效状态 | 线材质有效状态 | 说明 |
|---|---|---|---|
| `Default / Default` | ZWRITE=1，bias/slope=0/0 | ZWRITE=0，−4/−4 | 原生日常颜色路径，共用 `VS.9e5c9b302a6a2895.shader` |
| `Default / ProjectTexture` | 同上 | 同上 | 不同 PS；base `PS.3afec467924f4612.shader`，line `PS.b6935f6989057a28.shader` |
| `Default / StoryScene` | 同上 | 同上 | 与各自 Default 相同 PS |
| `Default / StorySceneHard` | 同上 | 同上 | base `PS.e106e7dc6075ea15.shader`，line `PS.b8d84f8c8248fe8e.shader` |
| `Default / GBuffer` | ZWRITE=1，0/0 | ZWRITE=0，−4/−4 | 只有 `VS.4b621292e78f8f1a.shader`；无 PS，COLORWRITE=0、MASTERCOLORWRITE=0 |
| `Default / DepthNormalPrepass` | 同上 | 同上 | 同一 position-only VS；无 PS，禁颜色写入 |
| `Prepass / Default` | ZWRITE=1，0/0 | ZWRITE=0，−4/−4 | EnableMask=2177，position-only，无颜色输出 |
| `Prepass / DepthNormalPrepass` | 同上 | 同上 | EnableMask=16 |
| `Mirror / UseHardShadowMaps` | ZWRITE=1，0/0 | ZWRITE=0，−4/−4 | 另有反射 stencil 配置，不能任意删掉 |
| `Movie / Default` | ZWRITE=1，0/0 | ZWRITE=0，−4/−4 | 独立电影 PS |
| `Simple / Default` | ZWRITE=0，bias/slope 未显式声明 | 同左 | 不是推荐的受光区域填充路径 |

深度/预通过程中的 stencil 原字段为 ENABLE=1、FUNC=ALWAYS、PASS=REPLACE、MASK=128、WRITEMASK=63、REF=1。它们不是“最后画白线”的颜色优先级指令。当前这两个 `floor.fx` **没有 `HiresLightmap` 或名为 `Hires` 的 technique**；不要从另一个通用材质的 Hires 路径借配置，也不要把 `Default/GBuffer` 当作有漫反射 PS 的着色通道。RayTracing reflection/shadow 路径存在，继续保留原绑定，但本次未验证它们的运行时分派。

微软标准的 D3D12 depth-state 默认值确实列出 LESS，但 SCNE 缺字段仍可能由 NBA 2K 的状态构建层、当前 PSO 或脚本补全；没有游戏运行时状态捕获，不能把两者等同。[D3D12_DEPTH_STENCIL_DESC 官方说明](https://learn.microsoft.com/en-us/windows/win32/api/d3d12/ns-d3d12-d3d12_depth_stencil_desc)

## 2. 为什么 bias −2 并不自动保护白线

即使假定原生深度采用普通较近通过比较，底面 bias=0、填充 bias=−2、白线 bias=−4，也只解决它们相对**已存深度**的位置。

一种仍会出错的顺序是：底面写 depth → 白线通过并写颜色，但 ZWRITE=0 → 填充相对底面也通过并覆盖颜色。白线更“近”的偏移没有存入 depth buffer，因此后画填充不会自动被白线挡住。相反，底面 → 填充 → 白线通常成立，但当前 SCNE 的 Prim 顺序不等于已验证的材质批次/多 pass 排序保证。不能靠把填充 Prim 加到最后来宣称线绝不会被覆盖。

在保留所有既有白线材质、所有既有索引前缀的约束下，最可靠的独立措施是：对浅灰区域做几何差集，**扣除实际原白线及暗色 lane-space 标记三角形在 XZ 上的并集**。中心填充必须避开中线及内外中圈；罚球区填充必须避开罚球线、圈/虚线、限制区和进入区域的其他现有标记。不要只扣外轮廓一条线。差集应使用 R4 已导出 VB/IB 的实际 float32 顶点，之后在最终 float32 填充顶点上复核交叠面积；数值保护边距可按 float32 ULP 量级设置，不能留下肉眼可见黑边。

这样颜色不相交的主要区域不依赖绘制顺序。若最终只靠渲染排序而省略差集，则必须报告为依赖尚未验证的原生绘制顺序，不能宣称静态检查已经保证完整白线。

## 3. 扫描材质与 UV 的关键差别

原 base 与线材质虽然都来自 `floor.fx` 家族，但不能只互换一张贴图就认为采样完全相同。

| 项目 | base floor | 线材质 |
|---|---|---|
| Script | `floor.2143c31560ecaec1.script` | `floor.8de24a65baa38b23.script` |
| `DetailAlbedoTexture` 的 Effect `Texcoord` | **2** | **0** |
| albedo TexcoordScale | `DetailAlbedoUVScale` | 1.0 |
| `DetailNormalRoughConeTexture` Texcoord | 2 | 2 |
| `BaseMaterialTexture` Texcoord | 2 | 2 |
| Logo 路径 | `Logo0Texture`，UV0 | 无此原资源槽 |

当前线纹理为恒定白，UV0 和 UV2 的差异看不出来。若复制白线材质后直接换为扫描水泥，albedo 却仍按线的 UV0 映射，而 normal/base 继续按 UV2，会造成图案缩放/方向与法线不一致。新浅灰材质应完整复制 `area_1_mat`，包括 `Effect`、`Script`、`ScriptParameter`、`Parameter`、`Technique`，继续用受光的 `floor.fx#1e7aabcf0cf28f1c`；只换 `Resource.DetailAlbedoTexture.Pixelmap` 并添加必要的独立深度覆写，不移植线的 ResourceMapping、root constants 或 PS。

保留当前正确资源：

- `BaseMaterialTexture` → `local/venice_v3/floor_base` → `venice_v3_floor_base.fdf1b35c3593ca8a.tld`。R=0，维持 matte packing。
- `DetailNormalRoughConeTexture` → `local/venice_v3/floor_normal` → `venice_v3_floor_normal.453b8be67bfb3597.tld`。2048²/12 mips，BC3/LINEAR；实际 B≈0.9373…0.9686，A≈0.05882。
- `Logo0Texture` → `local/venice_v3/no_logo` → `venice_v3_no_logo.560ac3bbecbf53bf.tld`，透明空 logo。
- `DetailNormalHeight=.018`、`DetailRoughness=.94`、`LightmapUVSet=1`、`ModulateAlbedo=[1,1,1]` 与原 DetailMaterial 仿射参数都保留。

浅灰 diffuse 最好来自相同 4096² 水泥扫描的独立校色版本，保留颗粒细节、尺度、完整 mip 和原 albedo 的色彩解释。当前深灰 diffuse 为 `local/venice_v3/court_concrete`，4096²/13 mips/BC1；步道 `local/venice_v3/concrete` 也是同源 4096²，但调色偏浅暖，不能把它当作照片精确采色结论。不要用白线 4×4 纯色、不要将 generic `NormalAndRoughMap` 的 A=roughness 纹理错接入 floor。

原 floor PS 分析副本 `/private/tmp/revision3_shader_research/floor_ps.ll` 中 `%101` 取 BaseMaterial.R，`%103` 取 normal RGBA，`%110…121` 生成法线，`%122…133` 采样并调制 diffuse；原 VS 的 TEXCOORD2 输入经模型 Scale/Offset 后输出到 PS 对应分量，再经材质仿射采样。floor 粗糙度为 `lerp(normal.B, DetailRoughness, BaseR)`，反射增益为 `normal.A * (1 + 1.5*BaseR)`；后续存在以该增益为除数的路径，因此不能把 A 归零。这里继续原资源即可，不需要再猜一次通道。

同一个 floor Object 的 UV1 与 `UserData` 继续连接 `level_floor_lightmaps.SCNE` 的原命名双 face lightmap；R3/R4 已换成明确报告过、曝光仍待游戏验证的均匀室外 irradiance。区域新增顶点应在原 670 个底面三角形上做 barycentric UV1 插值；UV0/2/3 同样沿原映射插值。不能重新归一化整个填充到 0…1，也不能重新绑定另一份无关 lightmap。

## 4. 可执行候选深度方案与边界

在已经做过标线差集的前提下，建议的新材质候选状态为：

1. 完整复制 base floor 材质；保持其不透明混合 ONE/ZERO、ZWRITE=1、原 `AssetOpaqueDepth=1`、floor stencil 与受光 shaders。
2. 在新材质自己的 `Default` 六个现有 pass、`Prepass` 两个 pass、`Mirror/UseHardShadowMaps`、`Movie/Default` 上一致设置有限负 `DEPTHBIAS` / `SLOPESCALEDEPTHBIAS`，**−2 / −2 可作初始候选**，数值介于原底面 0/0 与原线 −4/−4 之间。已有材质保持字节/记录不变。不要只改颜色 pass 而让 depth prepass 写另一层。
3. 不把 ZFUNC 设成 ALWAYS，不关闭深度测试，不增加随意的 stencil 优先级，不绕过到 Simple。初始候选保持原缺省 ZFUNC 的继承方式；若后续原生验证需要显式值，应依据实际 PSO 比较函数再定。
4. y 使用原底面插值结果，不抬高几何充当偏移。当前受保护 bounds.y 为 0…`4.76837158e-7` cm；任何常见毫米级抬高都违反 bounds/定位约束。

−2 是按原资产现有分层惯例提出的**待游戏检查候选值**，不是已测出的精确物理高度。浮点 depth bias 与当前 primitive 深度指数、屏幕深度斜率有关，不能换算成固定毫米；近乎掠射角时 slope bias 可能被放大。应检查俯视、低角度、近远镜头和角色脚下；不声称这个数值已经解决 NBA 2K 所有路径。[微软 Depth Bias 说明](https://learn.microsoft.com/en-us/windows/win32/direct3d11/d3d10-graphics-programming-guide-output-merger-stage-depth-bias)

## 5. 交付验证应针对整个 R4 前缀

当前 floor 单流 stride=28，POSITION 为 `R32G32B32_FLOAT`，四组 UV 为 SNORM16：UV0 offset12，UV1 offset16，UV2 offset20，UV3 offset24。当前真实资源：

- VB `venice_v3_court_vertices.bbe0a4f4e2d86711.bin`：**785148 B / 28041 vertices**。
- IB `venice_v3_court_indices.1522708c3f60c5e3.bin`：**53640 B / 26820 R16 indices**。
- 第一个原底面 Prim 为 Start0/Count2010；后面的 R3 白线都已是本次必须保护的内容。

新增 fill 必须保留**完整上述两段前缀**，不只是 donor 的旧 3231 顶点或最前 2010 个底面索引。新增 IB 段从 index 26820 后追加，新增顶点索引从 28041 起；重新检查 R16 容量。原全部 Prim 的 Material/Start/Count 与边界、全部白线三角形与 y=0 顶点、Object/UserData/Matrix、顶点格式 Scale/Offset、模型 Min/Max/Center/Radius、篮筐锚点保持。

至少验证：原 VB/IB 完整前缀逐字相同；旧 Prim 记录相同；新增三角形朝上且不退化；实际 float32 新 fill 与全部已有标线二维交叠面积在严格数值容差内为零；三个区域连通/面积符合设定；UV 插值误差和范围通过；浅灰纹理全 mip 解码、引用可达；clone 的完整状态除了新 albedo 引用和有说明的 depth bias 外相同。最后再用游戏截图验证受光、白线完整与所有相机下无闪烁，WebGL 几何预览不能替代这一步。
