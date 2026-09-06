# Checkpoint 1：黑树的可复现诊断

**状态：只读诊断完成；黑树根因尚未确认，没有生成或宣称已修复的游戏版本。**

## 已证实的事实

1. `palm_geometry.tangent_samples` 的 `prim.get('Start', 0)` 不支持连续省略 Start 的 primitive。donor 实际有 11 个非零省略段，全部属于 `CourtFloor`，位置格式为 `R32G32B32_FLOAT`。这说明通用解析时必须累积 Start；但该模型被旧切线采样器的 `R16G16B16A16_UNORM` 条件排除。
2. 旧采样器在前 10 个可读模型取得 1042 个样本后停止，实际采到的 primitive 均有显式 Start。只改成累积 Start 后，法线数组、原始 32 位 frame 数组及模型序列完全一致；直接在 V2 上采样也一致。**不能把 V2 黑树归因于这个 Start 问题。**
3. 独立重放原采样逻辑，与原 `tangent_samples` 逐值相等。按原种子和高度重新计算几何及“最近面法线选择原 frame”的步骤，三棵模型的 72648 个顶点中有 **222 个 frame 不同**。但所有已交付 frame 都属于相同的 donor 样本集合，且相应样本法线与当前最优选择的点积差最大仅 `1.11e-16`。以 `1e-12` 点积容差计，有 1076 个面存在多个不同 frame 的并列候选。这证明最近面法线不足以唯一选出 frame；微小浮点差异可能改变选择。它仍不能证明 frame 对新网格的切线方向、手性或 shader 解码是否正确，也不能据此确认黑树根因。

| 模型 | 三角面 | frame 不一致数 | 源面法线匹配误差 P95 | 最大误差 |
|---|---:|---:|---:|---:|
| venice_v2:palm_model_0 | 8072 | 57 | 16.59° | 22.92° |
| venice_v2:palm_model_1 | 8072 | 93 | 16.40° | 23.65° |
| venice_v2:palm_model_2 | 8072 | 72 | 16.44° | 23.09° |

表中的角度只比较新面的几何法线与 donor 样本的几何法线，**没有解码 TANGENTFRAME0**。以最近面法线拷贝一个 frame 并不能验证它与新三角面的 UV 梯度匹配。

frame 逐字差异数可能随 NumPy/浮点计算环境改变，原交付环境与本机的具体差异未确认；可复核的结论是 Start 修正前后样本相同，以及所有已交付 frame 均能匹配一个近乎并列最佳的源面法线。

## 材质和光照输入核查

- 五种树材质继承 apron 的同一个 effect、script 和 Technique；资源可在 V2 内解析，BC1/BC3 实际像素可解码，贴图并非全黑。每个槽的原始 RGBA 极值和哈希见 `palm_audit.json`。设置的 `NormalHeight` 均为 0。
- effect 的 `AlbedoMap` 与 `NormalAndRoughMap` 明确声明 `Texcoord: 2`。树的 TEXCOORD0/1/2 都只有 `(0,0)`、`(1,0)`、`(0,1)` 三个坐标，每个三角形重复使用；当前树颜色为 4×4 色块，仍不能从这一事实推出黑树根因。
- 三棵树的 **TEXCOORD7 全为零**；donor apron 的 TEXCOORD7 有 16 个坐标。effect 的 HiresLightmap/LoresLightmap 顶点输入确实包含 TEXCOORD7 和 TEXCOORD3。但 TEXCOORD7 的运行时语义、当前启用的 technique 和需要如何绑定光照资源均未确认。
- TEXCOORD3 在树与 apron 中均为零，不能将它单独作为异常证据。
- apron 模型包含 Duv0/1/2/7，新增树无 Duv 字段；apron 对象有 UserData，14 棵树实例均无 UserData。没有解码这些字段，也没有把它们直接称为光照索引。
- 原 donor 与 V2 的 Light、Effect 字典完全一致。缺少新增对象的经过验证的光照输入流程，仍需游戏对照确定行为。

## 下一步最小实验

先保留 donor 和失败 V2，输出独立编号测试包。在同一个已确认的游戏槽位、同一机位和同一照明下，加入一个使用已知完整 donor 对象/材质/顶点布局的对照物，与单棵树并排比较。先证实对象与 shader 输入路径，再逐项测试对象元数据、UV7 或经过验证的 tangent frame 处理；每个测试只改变一个因素，记录实际游戏截图。不要同时改树几何、照明和多个材质参数，也不要随机填 UserData 或猜测切线编码。

## 复现

在仓库根目录使用已有 Python 环境（需 NumPy、Pillow）：

```sh
python3 nba2k-arena/scripts/audit_palm_tangents.py --output-dir nba2k-arena/docs/checkpoint1
```

脚本默认只向终端打印 JSON；指定 `--output-dir` 仅写 `palm_audit.json` 与本报告。原 IFF 在诊断前后 SHA-256 一致，没有运行旧构建、没有改游戏目录、没有安装软件。

- donor SHA-256：`42865ecaf8dd923c4d901509263af3b242c00975f4284b917ba79ce8fbbced46`
- V2 主 IFF SHA-256：`5d74fdab31ee29e0fe888af10c7370efc329ecc76ceb72c2f1d3eb6aa92bd499`
