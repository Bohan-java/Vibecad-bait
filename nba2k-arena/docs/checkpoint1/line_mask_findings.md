# Checkpoint 1：标线 alpha 通道核查

核查日期：2026-09-06。仅依据交接包的 SCNE、缓存顶点及归档 V2 实际纹理；未读取游戏安装目录、未安装软件，未作游戏内验证。

## 结论与本次修复范围

原标线使用 **RGB 为白色、alpha 有变化** 的共享纹理，原材质效果启用了 alpha 混合。归档 V2 将该纹理换成整张不透明的浅白色。因此，“只把原标线颜色改白”的表述不准确：V2 同时丢失了原标线纹理的透明度信息，可能使原本用于承载标线的较宽几何带全部显色。

Checkpoint 1 应恢复以下两个材质的 donor `Resource.DetailAlbedoTexture` 引用；粗糙度、法线等其他 V2 设置可以保持，便于隔离问题。此修复与关闭四分线 primitive 是两项分别可核验的改动。

**尚不能证实原 alpha 图案的形状、透明边缘占比、原游戏可见线宽或恢复后的游戏观感。** 原始纹理像素不在交接包内，不能依据 SCNE 的通道最小值/最大值还原 alpha 图案，也不能把几何带宽直接当作可见标线宽度。

## 已验证的原材质引用

证据来源：`donor/original/arena_020_int_original.iff` 内 `level.SCNE`，解析 JSON 片段后取根键 `level`。

以下两个路径的值相同：

- `level.Material["floor_clutchtime_court:floor_line_mat"].Resource.DetailAlbedoTexture.Pixelmap`
- `level.Material["floor_clutchtime_court:floor_line_mat1"].Resource.DetailAlbedoTexture.Pixelmap`

精确引用名：

```text
%databuild_art_root%/material_library/_generic_textures/courts_shared/floor_line.png
```

`level.Texture[上述引用名]` 的原始元数据：

```json
{
  "Width": 512,
  "Height": 512,
  "Mips": 10,
  "Format": "BC7_UNORM",
  "Min": [1.0, 1.0, 1.0, 0.0],
  "Max": [1.0, 1.0, 1.0, 1.0],
  "PixelDataSize": 349552,
  "CompressionMethod": 33,
  "Binary": "floor_line.71af6dc754935e49.tld"
}
```

这里摘录了与核查相关的字段；原记录还包含 `Segments`，恢复引用时应保留整条原纹理记录。

该 `Binary` 不在 donor IFF、归档 V1/V2 IFF、两个本地参考 floor IFF 或 handoff 缓存内，独立项目文件中也没有该文件。因此它是**本交接包缺少像素数据的外部共享资源引用**。恢复原引用会重新依赖游戏的共享资源解析；本地没有验证游戏安装中的该文件是否存在或游戏运行时是否正确解析。

## alpha 混合证据

两个标线材质均引用：

```text
Effect: floor.fx#64ea5c821566f830
Script: floor.8de24a65baa38b23.script
```

`level.Effect["floor.fx#64ea5c821566f830"].Technique.Default.Pass` 下的 `Default`、`ProjectTexture`、`StoryScene`、`StorySceneHard`，以及 `Technique.Simple.Pass.Default` 均明确包含：

```json
{
  "ALPHABLENDENABLE": 1,
  "SRCBLEND": "SRCALPHA",
  "DESTBLEND": "INVSRCALPHA"
}
```

材质自身的 Default 系列 Pass 还设置 `DEPTHBIAS=-4`、`SLOPESCALEDEPTHBIAS=-4`、`ZWRITEENABLE=0`。这些是原标线叠加绘制设置，本次不应为了恢复纹理引用而改写。

上述设置证明渲染管线使用输出 alpha 做混合；未反编译像素着色器，因此不把元数据进一步表述为已证明的逐像素 alpha 计算公式。

## V2 的实际变化

`scripts/build_revision2.py:34` 将两个标线材质的 `DetailAlbedoTexture` 换为 `line_white`。`scripts/revision_textures.py:117` 用 4×4 RGB 图创建它，源颜色为 `(228, 228, 216)`；编码路径将 RGB 图写为 BC1。

已从归档 `output/revision2/arena_700_int.iff` 读取并通过 Pillow 的 DDS BC1 解码器解码：

```text
Binary: venice_v2_line_white.3532505eab078cf9.tld
Format: BC1_UNORM
Size: 4 x 4
解码后的唯一 RGBA 值: [231, 231, 222, 255]
```

这是实际纹理解码结果，证明 V2 替换纹理的每个像素均完全不透明；颜色与源图略有差异来自块压缩量化。

## 顶点与 UV 证据

已使用 donor 的 index buffer 和 handoff 中解码后的原顶点缓存解析 `__floor00__` 对应模型：

```text
arena_clutchtime_int_master@GameObjects@CourtFloor:floor_clutchtime_court_low
```

该模型的 `TEXCOORD0` 是位于 stride 28 顶点记录中 byte offset 12 的 `R16G16_SNORM`，按 `VertexFormat.TEXCOORD0.Scale/Offset` 解码。

在 `line_midcourt_side_lowShape` 中：

| 顶点索引 | Position X | Position Z | TEXCOORD0.u | TEXCOORD0.v |
| --- | ---: | ---: | ---: | ---: |
| 800 | 295.3965149 | -10.1575565 | 约 0 | 0.410668 |
| 801 | 295.3965149 | +10.1575565 | 约 1 | 0.410668 |

两个顶点的 Y 都为 0；同一横截面的几何带宽约为 **20.3151 场景单位**，`TEXCOORD0.u` 从一侧的 0 延伸到另一侧的 1。这支持“纹理横向覆盖整个几何带”的几何解释，但没有原 alpha 像素，无法得到原可见线宽，也未独立确认场景单位对应的物理长度。

同模型的 `TEXCOORD1` 提供接近全场的 0–1 布局，材质参数 `LightmapUVSet=1`；`TEXCOORD2` 有超出 0–1 的坐标；`TEXCOORD3` 在 floor 顶点中全为 0。具体各采样坐标在着色器内的计算仍未反编译确认。

## 其他通道不能代替线宽 alpha

两个标线材质与底层场地共用以下原资源：

| Slot | Pixelmap | Binary | 已核实的通道范围 |
| --- | --- | --- | --- |
| BaseMaterialTexture | `BaseMaterialTexture#24fc4126_594` | `basematerialtexture.76e2c2675d553e76.tld` | Min `[0,0,0,1]`；Max `[0.875157356,0,0,1]` |
| DetailNormalRoughConeTexture | `DetailNormalRoughConeTexture#8943058b_2172` | `detailnormalroughconetexture.046f939495687e79.tld` | Min `[0.047223795,0.009184977,0,0.163169473]`；Max `[0.962395072,0.998802185,0.202620745,1]` |

两者均为 4096×4096、BC7_UNORM、`TexelUsage=LINEAR`，像素文件也不在交接包内。BaseMaterialTexture 的 alpha 恒为 1，不能据它解释标线透明边缘。NormalRoughCone 是多通道数据，不能仅按名称和取值把 alpha 当作标线透明度，或武断指定完整 RGBA 通道语义。

## 可追溯输入

| 文件 | SHA-256 |
| --- | --- |
| `donor/original/arena_020_int_original.iff` | `42865ecaf8dd923c4d901509263af3b242c00975f4284b917ba79ce8fbbced46` |
| `output/revision2/arena_700_int.iff` | `5d74fdab31ee29e0fe888af10c7370efc329ecc76ceb72c2f1d3eb6aa92bd499` |
| `handoff/cache/VertexBuffer.0f3b6fcaf86b59a6.decoded.bin` | `6aed1f28fdd729b52c415ba2a07245395299d0095fe7ba4b5c31216c7555af54` |

本核查不构成游戏内显示或线宽验收。候选必须通过游戏实际加载与对照截图，才能确认标线透明度、可见宽度及四分线关闭效果。
