# Revision 3 材质与素材来源

`scripts/revision3_textures.py` 建立可调、可复现的水泥与海滨材质处理流程。它只写入 `build/revision3/textures` 的新资源和预览，并修改调用方提供的内存场景绑定；不会覆盖 V1/V2 或游戏文件。

## 调用与接口

```python
from revision3_textures import apply_textures

material_report = apply_textures(level, extra)
texture_keys = material_report['textures']
# 先应用本材质 pass，再 apply_court，使新标线继承正确 floor 通道。
# make_unbaked_material 可使用 texture_keys['bark'] / ['bark_normal'] 等。
```

独立生成素材预览：

```sh
python3 nba2k-arena/scripts/revision3_textures.py --preview
```

公共标签为 `court_concrete`（深灰球场）、`concrete`（浅暖步道/挡墙）、`grass`、`bark`、`sand`、`leaf`、`leaf_light`、`leaf_dead`、`aluminum`、`dark_metal`、`ocean` 及各自的 `_normal`。另外提供 `floor_base`、`floor_normal`、`line_white`、`line_white_normal`、`no_logo`。

返回的 `textures` 将标签映射到完整 Pixelmap 名称；`assets` 包含 TLD 名称、内容哈希、尺寸、实际解码颜色统计和预览路径。调用方必须把 `extra` 中的二进制数据写入最终 IFF。`max_size` 只用于缩小集成测试，正式构建不要传它。

## 扫描素材与校色

以下素材来自 Poly Haven，均为 **CC0-1.0**。下载原文件、下载 URL、文件长度和 SHA-256 存在 `textures/source/polyhaven/manifest.json`，构建逐文件核验。许可依据：[Poly Haven 资产许可](https://polyhaven.com/license)。这些素材可再分发、修改及用于商业项目；原 donor 游戏资源不因此变成 CC0。

| 用途 | 素材来源 | 当前处理 |
| --- | --- | --- |
| 场地与周边水泥 | [Concrete Floor 02](https://polyhaven.com/a/concrete_floor_02) | 两种独立色调均保留原 4096×4096 diffuse；移除大部分棕绿偏色与宽范围污渍对比，保留细粒、孔隙和磨损；normal 保留原 2048×2048 |
| 草地 | [Leafy Grass](https://polyhaven.com/a/leafy_grass) | 保留扫描植被细节，校色为偏干燥的低饱和绿；diffuse/normal 均保留原 2048×2048 |
| 棕榈树干 | [Palm Tree Bark](https://polyhaven.com/a/palm_tree_bark) | 保留扫描树皮环带与纵裂，diffuse/normal 均保留原 2048×4096，不压到 1K×2K |
| 沙地 | [Coast Sand 01](https://polyhaven.com/a/coast_sand_01) | 保留细砂扫描，减弱明暗对比并校色为灰米色；diffuse 原 2048×2048，normal 原 1024×1024 |

每类同时使用下载的 DirectX normal 和 roughness 扫描。保存在仓库中的 Clean Asphalt 是备选素材，目前正式水泥流程未使用。

球场水泥 `court_concrete` 目标 RGB 初值为 `(90,94,96)`，细节对比 `.32`；周边 `concrete` 为浅暖 `(158,154,142)`，细节对比 `.40`，使运动面与步道/挡墙有明确层次，并避免强污渍像油斑。参数位于 `SCAN_PROFILES`，便于后续根据高清参考和游戏实测调整。当前低分辨率参考不足以确认真实微表面纹理；这些数值是设计初值，不是对照片的精密测色结果。正式流程不设置纹理分辨率或 Git 单文件体积上限；所有扫描保留各自原始有效像素尺寸，测试才显式传 `max_size`。

其余纹理由项目代码生成：叶片按完整扇叶 UV 绘制，U 横跨几何的 28 扇形区，V 从中心向叶尖；28 条主放射脉与每区 4 条细脉保持恒 U，使纹理在实际曲面上沿半径展开，中心处减弱细节以避免拥挤。叶片输出 1024×1024，轮廓由真实网格决定，纹理不使用透明树叶广告牌。海面为低对比周期波纹；金属与白线为统一色。上述程序纹理未复制其他来源照片。

## 两种着色器使用不同通道

**Floor 路径**对应 donor 的 `PS.0cfd5246b9c1587a.shader`（场地）及同族 floor 标线效果，使用单独的 `floor_normal`：

- RG：弱化后的 DirectX 法线 XY。
- B：粗糙度，源值约 `.91–.98`。
- A：反射增益，源值 `.06`，严格大于零。
- `floor_base.R=0`，使 `lerp(Normal.B, DetailRoughness, Base.R)` 采用纹理粗糙度。

已核对的 floor PS IR 还把反射增益乘以 `(1+1.5*Base.R)`，并在后续表达式除以 Normal.A。因此不把 A 清零。不能沿用旧 V2 的 `[128,128,215,255]` 后只提高 `DetailRoughness`；旧 Base.R 接近 1 且 A=1，会影响反射与粗糙度混合。

**Generic layer 路径**对应 `PS.5e38eeba1e81863d.shader` 的已验证 Default pass：RG 为法线 XY，A 为粗糙度，B 在该路径未读取，写 0。B 的角色不被臆称为金属度或高度。扫描 normal 使用较弱幅度，现有可见地面 `NormalHeight=.16`；新增物体由 `make_unbaked_material` 调用方决定 NormalHeight。

不会改动 compiled shader。已核对 `VS.9e5c9b302a6a2895.shader`：原 `TEXCOORD2` 经模型 Scale/Offset 送入 PS 的 TEXCOORD1.zw，再用于 DetailAlbedo/Normal/Base 采样。PS 还应用脚本预计算的仿射变换；用户参数 `DetailMaterialScaleX/Y` 如何转换成该仿射矩阵尚未解析。因此保留原 UV 描述和 `.275` 缩放参数，暂不宣称扫描素材的 2 米物理尺寸与游戏重复率精确对应。

## 编码与验证

颜色使用 BC1；含独立 alpha 数据的通道图及透明空 logo 使用 BC3。所有纹理生成到 1×1 的完整 mip 链，采用内容哈希命名。每一层都通过 Pillow 的独立 BC 解码器打开；TLD 头、每层块长度和总长度逐一检查。

TLD 头 offset 22 的 uint16 对单层纹理写 **1**。旧 V2 编码器将其误称为 `block_words` 并对 BC3 写 2；原 `baskets.SCNE` 的 `NormalAndRoughMap#914a651a_1602` → `normalandroughmap.6f25999c8b862c25.tld` 是可复核反例：它是每块 16 字节的 BC7 单层纹理，但该字段为 1。原 donor 所有内嵌场景纹理的该字段均与 `Faces` 一致。新编码器已修正此结构问题，旧 V2 归档保持原样。

`material_contact_sheet.png` 显示最终 BC 解码颜色，不是游戏截图。`material_manifest.json` 保存实际解码的通道范围；正式初次构建的 floor B 为约 `.9686`、A 为约 `.05882`。BC 块量化可能压平很小的粗糙度差异，但仍保持高粗糙度与低、非零的反射增益。

本模块的静态测试覆盖完整 mip 链、RGBA 通道、正反射增益、实际 donor 材质修改范围及资源自包含。整体游戏的曝光、IBL、室内残留光照和运行时效果仍需结合完整场景与实际加载验证，不能以单独材质预览宣称已完成游戏验收。
