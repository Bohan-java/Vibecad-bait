# 夜景探针烘焙（第一期）

这份目录是给负责烘焙的人用的。目标：用 Blender Cycles 在游戏的光照探针位置，计算夜间灯光（A 字牌、Chili's、boots、高灯杆）的真实光照，包括墙、围栏、门框的遮挡和光的反弹。算完后把结果传回 GitHub，再由项目这边写进游戏包。

**不需要改模型，不需要保存 .blend，也不需要碰游戏。**

## 需要准备

- Blender **5.2.2**（项目原版本；4.x 一般也能跑）
- 最好有独立显卡（NVIDIA/AMD/Apple Silicon 都可以），没有也能用 CPU，只是慢很多
- 拉取仓库并下载大文件：

```bash
git pull
git lfs pull
```

确认 `nba2k-arena/zgc-court/source/scene.blend` 是真实文件（约 65 MB），不是几百字节的指针文件。

## 目录里有什么

| 文件 | 作用 |
|---|---|
| `bake_probes.py` | Blender 脚本，负责全部烘焙 |
| `probes_3_0_2.json` | 568 个要烘焙的探针（游戏坐标和 Blender 坐标都写好了） |
| `bake_lights.json` | 灯光设定：哪些物件发光、颜色、强度，以及两盏补充灯（Chili's 店内面光、高灯杆聚光） |

## 第一步：先跑 3 个探针试一下

在 `nba2k-arena/zgc-court` 目录下打开终端：

```bash
blender -b source/scene.blend -P bake/bake_probes.py -- --out bake/output/test.ndjson --limit 3
```

（Windows 上 `blender` 换成 Blender 的完整路径，例如 `"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"`。）

正常会看到类似：

```text
[bake] relinked 11 images
[bake] hidden 4 lights/cameras/helpers
[bake] device OPTIX: NVIDIA ...; 3 probes, 0 already done; groups ['a_signs', 'chilis', 'boots', 'floodlight']
[bake] probe 1/3 id 2248 done (0.4 min)
...
[bake] finished
```

记下每个探针大概用了多久，乘以 568 就是总时长。如果报 `Light source objects not found in the .blend`，把报错截图发回来，不要自己改名。

`.blend` 里的贴图存的是原作者 Windows 电脑上的绝对路径，脚本会自动改到仓库里的对应文件（`relinked N images`）。如果报 `images still missing`，说明 `git lfs pull` 没拉全，先重新拉取。参考速度：Apple M5 GPU 每个探针约 3 秒，568 个约半小时（第一次运行要额外编译着色器约 1 分钟）。

## 第二步：正式烘焙

```bash
blender -b source/scene.blend -P bake/bake_probes.py -- --out bake/output/probe_sh.ndjson
```

- 预计半小时到 1 小时（GPU），CPU 会更久。
- **中途断了没关系**：用同一条命令重新运行，已经算完的探针会自动跳过。
- 想先只算一组灯，可以加 `--groups chilis`（组名见 `bake_lights.json`）。
- 画质参数：`--res`（全景图高度，宽度为两倍，默认 128）、`--samples`（默认 128）。默认值已经够用，一般不用改。

## 第三步：上传结果

完成后会生成两个文件：

- `bake/output/probe_sh.ndjson`（每行一个探针，约 1–2 MB）
- `bake/output/probe_sh.ndjson.meta.json`（Blender 版本、设备、参数）

只提交这两个文件，**不要提交 .blend 或游戏包**：

```bash
git add nba2k-arena/zgc-court/bake/output/probe_sh.ndjson nba2k-arena/zgc-court/bake/output/probe_sh.ndjson.meta.json
git commit -m "Probe bake results"
git push
```

## 技术说明（给后续开发者）

- 世界背景是纯黑，原有灯光、辅助物件和材质自带的发光全部关闭，只有 `bake_lights.json` 里的灯参与计算；游戏原有的月光环境光保留，烘焙结果是叠加上去的那部分。
- 每个探针按灯组分别渲染一张 360° 等距柱状全景图（256×128），投影到 9 个实数球谐系数 × RGB，坐标轴换算成游戏世界轴（x = −Blender Y，y = Blender Z 向上，z = −Blender X），顺序与游戏一致：L1 为 (Y, Z, X)。存的是辐射度球谐，未做余弦卷积。
- 各组分开存，导入时可以分别调亮度和颜色，不用重新烘焙。绝对亮度在导入时用当前 N16 的观感做校准。
- 第一期只烘探针（影响球员和动态物体）。地面、墙面的高精度光照贴图是第二期，要先在一小块地面上验证格式。
