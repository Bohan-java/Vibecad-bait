# 中关村大融城 NBA 2K26 球场交接指南

本指南随 R13 工程交接，面向继续建模、材质制作和游戏集成的人或 AI。工程目标是依据用户提供的真实照片，还原中关村大融城、Chili’s 及周围广场，最终给用户 **一个可以替换 Blacktop 场地的 `arena_700_int.iff`**。

当前可编辑源是 `source/scene.blend`，当前游戏交付是 `output/arena_700_int.iff`。不要从旧脚本重建场景来覆盖这份源文件，也不要把网页预览当成游戏已经成功加载的证明。

## 1. 先看当前状态

| 项目 | 交接时的事实 |
|---|---|
| 当前版本 | R13：Chili’s 正对球场的主立面细节与材质、篮板透明度和粗糙度 |
| 游戏与模式 | NBA 2K26，Blacktop；用户也使用半场选项 |
| 实际替换文件 | `arena_700_int.iff`；用户直接拖入平时使用的 `levels` |
| 输出大小 | 1,685,622,410 字节 |
| 输出 SHA256 | `9e9cd0f73b1c6c2baf6d9f45cb472ac110282e7d161c20ce9d373fd968532622` |
| 源模型 SHA256 | `884f58b4d78e78d92c0bb848c67626802a9828d19c5b0a0b8bec21fbf16b208b` |
| 当前实际 IFF 预览 | `public/game-preview/current.glb`，SHA256 `40723c272b13bd33aeb71d11613eb808f3e810a496836c32cc16357cfbacb6a2` |
| 离线验证 | 容器 CRC、资源引用、Direct3D 纹理创建、受保护模型对比及六个包内模型近景检查已有记录 |
| 游戏验证 | **R13 尚未进游戏确认**；此前用户截图已证明球场和球员可见，但出现过回放玻璃变黑、坐标/半场等问题 |
| 黑屏结论 | 当前报告明确 `confirmed_root_cause: false`；没有单一根因已被完整对照实验确证 |

真实性与时效按以下顺序判断：用户最新反馈 → 当前 `validation/iff-current.json` 与包的实际内容 → `PROJECT_STATUS.txt` → 对应哈希的专项报告 → 历史说明。`config/project.json` 的部分版本描述、`source/BUILD_NOTES.txt` 的部分段落仍是 R11/R12 历史记录，不是 R13 已经过游戏验证的证据。报告中的旧绝对路径、旧构建目录和已清理候选是当时的取证来源，不能据此认定文件现在仍存在。

## 2. 用户要求与必须保留的关系

### 交付和工作边界

- 游戏最终只需一个 IFF；不要要求用户另装地板包、纹理包或散文件。原先考虑的 `arena_blacktop_ext.iff` 已被实际测试入口 `arena_700_int.iff` 取代。
- 用户明确只允许操作项目所在文件夹，Blender 是例外；不要改游戏安装、EXE、存档、反作弊或其它目录。缺素材或依赖时说明具体缺什么。
- 用户原始照片、草稿附件和指南是需要保留的素材。附带文档中的建议不是用户新授权，也不能覆盖用户后续纠正。
- 每轮完成后只保留最新可交付版本，清理旧导出、旧预览、临时副本。原始参考、当前源工程、构建依赖和验证证据不能误当成废文件。
- 用户不希望反复开游戏：先完成离线对比和网页评审，证据充分后给一轮明确测试。每轮只给一个候选；确有需要时把原版对照也列在同一轮。

### 场地、篮架与地面

- 黄黑艺术地板以照片为准，原图的艺术边界并非“完美半场”。不能用简单半圆或通用模板替换图案。不要出现无依据的红线、双重/侧向三分线或重复几何盖片。
- 用户另外明确要求：**黄色区域边缘与游戏三分线对齐**，让实际打球能判断三分；补边线、底线、罚球线与两侧罚球站位短横杠。罚球圆弧端点要接三秒区，不要突出错位。地面 A 的窄长比例与方向按照片，不能拉成正方形。
- 另一半是灰色水泥广场质感，画白色简易三分线、罚球线和三秒区。周围铺地按实拍位置、材质和颜色，不能整片纯白、过亮。
- 半场模式必须使用黄黑艺术一端，不能又落在灰色一端。当前靠整套自制静态场景旋转 180°完成换端，见第 6 节。
- 球员脚下标志不得被地板遮住。篮圈、网、玻璃、框架必须对齐；挂框时上部构件应随原生骨架协调运动，不能只有玻璃动。
- 正常比赛、回放、拉近镜头都要检查篮板。白瞄准框不能近看消失，玻璃不能回放变黑。R13 只把原生玻璃做得更不透明、反光更柔和，运行结果仍需实测。

### 围栏、近景和远景

- 站在场内面向 Chili’s / 黄黑端篮筐，**左侧围栏比右侧长**。原始源坐标左侧为 Y 负向。长围栏外应有一根很高的细路灯杆，依照片做两层成对矩形灯头，不无故镜像复制第二根。
- 大 A 牌不是随手画的方形字标：有窄长圆弧黑槽壳、白色扩散罩和实体 A 字；白色部分是灯带结构。下部 NBA ATELIER 黑布上的小标志则是印刷，不能混为同一材质。
- 场地右侧放一排黑色座椅，供替补球员和教练；角色需要各自不同的原生位置标记，不能只摆椅子。当前有 44 个角色标记，是否被 Blacktop 正确采用、坐姿是否贴合仍需游戏检查。
- 左长围栏外的低灰建筑、The boots 泥靴门店、植栽等，按连续照片的重叠关系核对。越靠近场地，细节越重要。外侧完整路线、测距和部分遮挡物仍不确定，不能把外观补充照片误当成物件紧靠围栏的证明。
- 地图边缘应由远楼和远树遮挡。新中关、新东方大厦南楼、中钢国际广场、互联网金融中心按照片视角分组放置；疑似 e 世界保持“疑似”。远景以轮廓、体量、位置关系为主，不必过度精模；不能把有剪辑的视频帧拼成实测 360°全景。

### Chili’s 与本轮精修

- Chili’s 大体为**长方形主体，长直立面配短转角**，不是椭圆建筑。
- 用户确认：**面对 Chili’s 主入口时，喷泉露台在左侧绕过转角**。源坐标是 -Y 端。主入口与露台是同一建筑的不同门面，不得叠在一处。
- LINK 大楼与 Chili’s 有距离，不是连成一个建筑；建筑间距、转角角度、照片未展示的背面不是实测值。
- R13 逐张核对 45 张独立相关照片（48 个查看路径含重复），专攻面向球场的主立面：灰紫门头、红橙厚灯牌、银色凹面柱和三道檐口、黑框门窗、金属把手/铰链/闭门器、米色布篷及关节、灰石/水泥、红褐釉砖电梯凹口等。
- Chili’s 字本身是灯牌，要做壳体、侧边、亚克力字面和细内沿的实体层次；**此阶段不加发光、不改全局光照和曝光**。其它灯带和路灯同理，灯光留到后续一起做。
- 金属、涂层金属、织物、水泥、灰石和釉砖应有各自颜色、粗糙度与尺度；不把所有灰表面都处理成水泥，不把照片光晕、强阴影烘成发光效果。
- 冬季积雪、圣诞装饰和开业临时摆设不作为永久建筑。字形、毫米结构和材质物理参数仍有据图近似，不声称“实测一模一样”。

## 3. 目录与重要文件怎么用

以下路径以 `nba2k-arena/zgc-court/` 为工程根。逐文件清单以本次交接附带的文件清单为准；本表解释其用途。

| 路径 | 是什么 / 什么时候看 |
|---|---|
| `TRANSFER_GUIDE.md` | 本指南，供接手者先读 |
| `PROJECT_STATUS.txt`、`使用说明.txt`、`排查与测试.txt` | 当前交付的简短状态与用户测试说明 |
| `source/scene.blend` | 唯一当前可编辑场景，继续增量修改的起点 |
| `source/reconstruction_notes.json`、`source/BUILD_NOTES.txt` | 建模依据和历次约束；包含历史信息，需按当前状态判读 |
| `source/geometry_validation.json` | 源场景尺度与几何检查；不证明游戏动态正确 |
| `artwork/court.svg` | 可编辑球场线条、图案源文件 |
| `artwork/paving-context.svg` | 可编辑外围铺地及衔接图案 |
| `artwork/court.png`、`paving-atlas.svg`、`paving-atlas.png` | 上述 SVG 栅格化/合成的派生文件，不要只修派生图而遗忘源 |
| `textures/r03/`、`textures/current/`、`textures/r13-chilis/` | 当前源工程仍使用的纹理；目录名有旧版本号不代表废弃 |
| `references/part1/`、`part2/`、`chilis/`、`chilis-detail/` | 实拍原图与细节依据；保持图号、文件名和来源说明 |
| `references/r12-left/`、`r12-skyline/` | 左长围栏连续帧、店外细节及远楼分方向参考 |
| `references/original-*.zip`、`*-archive.json` | 原始附件与归档记录；用于追溯，不是游戏安装包 |
| `references/reference-index.json` | 网页参考图索引及对应关系 |
| `references/guide/` | 用户提供的 DOCX 指南、提取正文和早期黑屏截图；指南内候选工具不等于本项目实测 |
| `references/feedback/` | 用户游戏问题截图，与实拍参考分开理解 |
| `output/arena_700_int.iff` | 唯一要给游戏使用的最新文件 |
| `public/manifest.json`、`public/builds/<build_id>/` | 当前保存源模型的导出 GLB、输入摘要、构建记录 |
| `public/game-preview/` | 从最终 IFF 重新解码的 GLB/清单，网页“游戏包预览”使用它 |
| `preview/` | Three.js 网页界面、相机按钮、参考图对照；不是游戏资源 |
| `config/project.json` | 路径、尺寸、坐标映射与预览设置；机器路径换机需调整，历史状态字段不可当验收结论 |
| `tools/` | 建模修订、导出、原生封装、校验和清理工具，见下节 |
| `validation/` | 有范围和哈希约束的检查结果；`current-r13-*.png` 是最终 IFF 解码离线渲染，不是游戏截图 |
| `logs/` | 当前源导出日志 |
| `.build-staging/` | 临时导出和候选，完成验证后可清理；中间 IFF 不交给游戏 |
| `.preview-runtime/` | 本机服务状态、控制令牌、纹理缓存、运行日志；不是参考资料或可发布交付 |
| `Start_Preview.bat` / `Stop_Preview.bat` | 在 Windows 启停本地网页；关闭启动窗口不会关闭后台服务 |

## 4. 环境、依赖与路径

交接时实际运行环境：Windows，Blender 5.2.2 LTS（`d13f752e3b9c`），Python 3.12.14、NumPy 2.3.5、Pillow 12.3.0，Node.js 24.19.0；`package.json` 要求 Node ≥20，Three.js 固定 0.180.0。SVG 栅格化及网页纹理缩放另用 `sharp`，当前由 `config/project.json` 的 `tools.sharp_module` 指向已有安装。

当前构建用 **Blender 自带 GLTF 导出 + 本仓库 Python 原生资源编码器**，不是某个未知 NBA Scene 插件的一键导出。不要把用户指南里提及的插件名称和商品说明写成本项目已安装、已验证的版本。

本机 Blender 位于 `D:/Blender/blender.exe`；`tools.blender_path` 或环境变量 `ZGC_BLENDER` 可指定新路径。Node/Python 原在用户缓存运行时内，接手机器必须自己提供解释器与上述依赖，不能假设 Windows 用户名和缓存路径相同。`npm ci` 只安装 package 中的 Three.js，**不会自动补 sharp**；须配置真实可用的 sharp 模块路径。

脚本目前按以下**相对父目录路径**读技术底包，交接时应保持这些相对关系（或集中改路径并重新验证）：

| 相对 `zgc-court/` 的路径 | 作用 |
|---|---|
| `../洛克公园/arena_blacktop_ext.iff` | 用户确认曾改名到同一槽位正常显示的底包；继承容器、原生资源与技术结构，不是视觉模板 |
| `../build/high_hoop/reference/arena_blacktop_ext.iff` | 专用原生户外篮板玻璃材质、Presentation 通道、shader/script 的只读模板 |
| `../build/local_game_reference/levels/arena_700_int_floor.iff` | 单独地板资源的本地参考缓存；用于原生标线别名和格式核对，不是要求用户再装的第二个包 |
| `../donor/original/arena_020_int_original.iff` | 44 个替补/教练角色标记的原生名称与结构依据；不继承其室内外观 |

部分审计脚本保留 `../build/high_hoop/deps` 的搜索路径；实际非标准库主要是 NumPy/Pillow。不要因此把整个旧实验目录都当作必须运行的入口。

游戏构建号在配置中记录为 Steam build 24237529，是之前只读观察值，**不是保证接手时游戏仍为此版本**。用户没有确认加载器名称；只知道其习惯是拖入 `levels`，不能擅自假设 Modium 或热加载。

## 5. 当前真实构建流程

### 日常编辑和看效果

1. 打开已有 `source/scene.blend`，依原图增量编辑；确认发光仍为零，保存。
2. 运行 `Start_Preview.bat`，或在工程根运行 `npm run preview`。服务地址默认 `http://127.0.0.1:4173/`。
3. 源监视器将 SVG 栅格化，调用 Blender 导出，核对输入未在导出中变化，再原子发布源 GLB。等待 `/api/status` 的 `phase` 为 `ready`。
4. 只修改外部 `textures/` 文件不一定触发源监视器，因为监视目录是 `source`、`artwork`、`config` 及部分导出工具。应保存/重新绑定源材质并确保实际导出拿到新纹理，不要看到旧 GLB 就以为修改生效。

下列命令均在 `zgc-court/` 执行；`python`、`node`、`blender` 代表已配置好的相应解释器。路径不在 PATH 时替换为本机完整路径。

```powershell
# 导出当前保存的源模型（网页已运行并完成导出时可省略）
npm run build

# 读取当前源 GLB，转为原生网格和材质中间数据
python -X utf8 tools/export_game_assets.py --output .build-staging/current-native/assets

# 写中间包：此时仍有旧材质/容器处理，禁止直接拿去游戏
python -X utf8 tools/build_source_iff.py --assets .build-staging/current-native/assets --output .build-staging/current-native/source-base.iff

# 应用已建立的原生兼容、玻璃、动态篮架、角色标记及半场方向修订
python -X utf8 tools/repair_iff.py --input .build-staging/current-native/source-base.iff --output .build-staging/current-native/arena_700_int.iff
```

`repair_iff.py` 检查 CRC、重复成员、内部二进制引用、受保护缓冲、全局光照与后处理、Direct3D 纹理创建，成功后才把 `.pending` 改为候选文件。但它同时会更新 `validation/iff-current.json` 指向候选；此时不要误认为 `output` 已更新。保留候选和旧交付的清楚对应关系，发布时把报告 `output` 路径同步到正式输出。

**检查通过后才发布**候选为 `output/arena_700_int.iff`，随后执行：

```powershell
python -X utf8 tools/finalize_current_iff.py
python -X utf8 tools/export_native_preview.py
```

已有快捷入口 `python -X utf8 tools/build_current_iff.py` 会依次调用上述步骤、直接更新正式输出并导出 IFF 预览。它检查保存源与已发布源 GLB 一致，但不会代替全部专项审计。继续开发时更适合先走临时候选流程，留好回滚点。

**源完整性门槛：** `repair_iff.py` 会要求 `chilis-building-current.json`、R13 材质报告的源哈希与保存的 `.blend` 一致。新修改触发失败时应重新做相应保护/建模检查并生成新报告，不能仅改报告哈希或删除断言来“通过”。`refine_*` 是历次有范围的修订工具，不是需要每次顺序全跑的迁移链；运行前必须读其对象筛选、输入和输出。

主要工具职责：

- `export_scene.py`：导出当前打开的 `.blend`，排除相机、灯和辅助参考；不是场景重建器。
- `export_game_assets.py`：解码源 GLB，变换到游戏厘米坐标、三角化分块、选择正确 UV/材质。
- `build_source_iff.py`：保留技术底包资源，写自制几何、纹理及中间 SCNE。
- `repair_iff.py`：最终兼容装配；必须处于完整构建链中。
- `iff_codec.py`、`native_archive.py`、`native_textures.py`：SCNE、网格属性、ZIP 记录、DDS/mip 编解码。
- `r04_materials.py`、`r04_glass.py`、`specialized_basket_glass.py`：原生材质和透明篮板管线，旧文件名不等于可跳过。
- `native_basket_rig.py`：自制篮架接入原生骨架，保留原生篮圈、运行时网和各级 LOD。
- `native_floor_overlay.py`、`shared_floor_line_override.py`、`ground_depth_policy.py`：地板外部资源、标线与脚下标志深度问题。
- `r12_seating.py`、`r12_seating_geometry.py`：替补/教练原生标记和座椅位置。
- `half_court_orientation.py`：最终静态实例及座椅角色旋转；`patch_half_court_current.py` 是已有包的专用修补入口，不要额外重复旋转。
- `export_native_preview.py`：从实际最终 IFF 回读模型/材质/纹理生成预览。
- `audit_*`、`render_*`：各项有输入条件的审计或截图工具，不是任意版本通用的一键验收。
- `cleanup_current.ps1`：核对当前输出与预览后，按项目边界清理旧导出与缓存。

## 6. 坐标、尺度和不能破坏的原生结构

源坐标以米计，X 沿球场长边、Y 沿宽边、Z 向上。中心场地 28.6512 × 15.24 m，地面 Z=0；源篮圈中心 X=±12.7254 m，上沿 3.048 m。源场景黄黑端/Chili’s 在 X 负向，灰色端在 X 正向。

原始源到游戏映射为 `(100Y, 100Z, 100X)`，单位厘米；源到预览为 `(X, Z, -Y)`。**R12.1 之后最终游戏静态实例还绕游戏竖轴旋转 180°**，即游戏 X、Z 取反，使黄黑端在游戏 +Z。原生篮架与比赛技术锚点不跟随另转；44 个座椅角色标记跟随场景移动并转向，不能落在旧椅子位置。

这不是翻转源贴图，也不是猜测某个“半场选择器”字段；目的是把已经被游戏选中的端换成黄黑实景端。预览相机也根据 IFF 的方向补偿。不要为修网页方向再把 `.blend` 转一次。

黄色三分边界按当前原生比赛参考半径 7.239 m、角线横向 6.7056 m、线宽 0.0508 m整理。它们是游戏对齐值，不是照片现场实测尺寸。源通用篮板宽高与游戏实际原生玻璃边界不是同一数据；当前可见玻璃约宽 1.701419 m、高 0.949912 m、底高 2.904345 m，以原生资产对齐报告为准，不要机械套标准尺寸重做。

源篮板透明片和静态网是制作/预览占位。最终包保留原生动态玻璃、圈和运行时球网，自制上部框架/支臂接入原生骨架、底部硬件固定。必须同时检查位置、权重、`MAIN`、所有 LOD 和玻璃 Presentation 通道；只在 Blender 里看起来重合不够。

## 7. 如何避免黑屏和其它回归

### 已知现象与证据边界

早期用户反馈：游戏声音、操作、HUD 正常，几乎所有 3D 内容全黑，只见脚下标志。用户确认原“洛克公园”包同样改名 `arena_700_int.iff` 后在同一 Blacktop 入口曾正常显示。后续用户截图确认球场、角色已可见；后来的**篮板回放黑片**与早期**全场 3D 全黑**必须分开记录。

曾真实检出 DDS 顶层尺寸不符合 Direct3D 压缩纹理创建要求；仅图像库能解码不等于 D3D 能创建。修正这一错误后的那一轮用户仍反馈全黑，因此它是必须修的缺陷，**不能据此单独认定为全部黑屏根因**。之后最终流程同时修订了材质分支、DDS 别名路径、封装等，不能从“后来能显示”倒推出每一项都是已证实原因。文件约 1.7 GB 也不是根因证据。

### 当前应保持的兼容措施

1. **容器和资源名称。** 最终 `native_archive.write_compatible` 保持底包成员顺序与元数据，未变压缩记录尽量逐字节复制；新/变成员用 DEFLATE，输出支持范围是普通可寻址 ZIP32。不要用普通资源管理器随手套一层目录、批量改大小写、产生同名成员或换成未经验证的压缩路径。中间包可能用另一种写法，不能绕过最终修订步骤。
2. **DDS 与引用。** 当前最终包沿用底包 DDS-only 别名：SCNE 的 `.tld` 引用由同 stem 的 `.dds` 满足，移除实验性直接 TLD 载荷；`.gz`/`.bin` 也有已有别名规则。保持原生 `名称.16位十六进制ID.dds` 形式、纹理描述、尺寸、格式、mip 数与载荷字节一致。顶层 BC 尺寸先规范化，再做完整 mip 链；逐 mip 解码以及 D3D 创建均通过才可接受。
3. **SCNE 重复键。** 文本资源可能是 JSON 成员片段。当前 `iff_codec.load_scne` 会补外层并使用 `object_pairs_hook`，遇重复键明确报错；它不是重复键无损编辑器。出现重复键时停下，采用真正保序/保重复结构的解析方案，不能换成普通 `json.loads` 然后重写而悄悄丢节点。二进制 SCNE 交给已验证的 `BinaryScene` 路径，不能强行当 UTF-8。
4. **外部依赖。** 区分本包必须自洽的 Buffer/Shader/新增纹理与游戏外部共享资源。游戏原生外部依赖没有包含在本包中，不等于缺失；特别是独立 floor 缓存缺顶点数据时不能从索引编造地面几何。也不能为了“零缺失”随意塞假资源。
5. **材质和法线。** 当前不透明模型用经过本项目修订的原生 `asset_CLOD` 等分支，保留必要效果、脚本和资源绑定；不要把只依赖光照贴图的分支用于没有相应 lightmap 的模型。`TANGENTFRAME0` 仅部分语义经过解码，新增静态模型用中性切线法线图、`NormalHeight=0`；不能把任意 Blender 法线节点直接套入未验证的切线布局。金属度、粗糙度和基色必须在最终 IFF 里核对，避免因 GLTF 因子与纹理通道重复相乘改变材质。
6. **篮板专用管线。** 保留 `basket_glass.fx` 效果定义、14 个原生 shader 资源与 1 个 script、原生顶点/骨骼/权重契约及 `Presentation` pass。R13 玻璃 alpha 从 10/255 调到 36/255，粗糙度 R 从 16/255 调到 82/255；基色不自行预乘 alpha。粗糙度降低的是倒影清晰度/尖锐高光，尚未确认独立“反射能量”控制，不能宣称已调整总反射强度。白框由实体几何表达，避免把不透明白像素重新混入整片透明玻璃。
7. **地面深度。** R07 曾用地面斜率深度偏移，出现脚下标志按位置消失；当前移除相机分支中的 `DEPTHBIAS`/`SLOPESCALEDEPTHBIAS`，并精确编码恒定高度轴，避免原地面量化到高于 0 的微小高度。不要为遮住原生线又抬整块地板、加覆盖平面或恢复负斜率偏移。外部原生标线另由原名透明 DDS 别名处理，不能与深度问题混为一谈。
8. **保留非目标内容。** 每轮建立明确改动范围，对其它几何、材质、实例、角色锚点、原生篮圈/网及灯光/后处理做前后对比。不要凭空增加曝光字段或批量提亮“试一试”。检查异常数值、坐标尺度、矩阵行列式、法线和镜头遮挡后再提出原因。

### 如果再次全黑，按一轮实验组织

先确认实际运行游戏版本、同一入口、文件名和本次 IFF 身份；离线比较原版与候选成员、压缩、资源引用、坐标、相机包围盒和日志。排除重复覆盖需向用户给明确查看步骤，不替用户改其游戏目录。镜头可能被几何遮挡是待查方向，不能先认定灯光问题。

只有证据需要时，再准备同一底包的“只解包再封包”与“导入零改动再导出”对照，先离线比较差异：前者失败优先查封装，只有后者失败优先查导出兼容。换工具/插件/游戏版本后也应先恢复这种最小验证。不要为每个猜测都让用户开一次游戏。

## 8. 网页预览证明什么

**编辑源预览**读取 `public/builds` 中由 `.blend` 导出的 GLB，适合快速看形体、材质和对照原图；它可能早于 IFF 更新，包含制作占位物，不能证明打包正确。

**游戏包预览**读取 `public/game-preview/current.glb`，由 `export_native_preview.py` 从当前实际 IFF 重新解码；能检查打包后的几何、材质映射、DDS 与半场方向。查看 `/api/game-preview` 应为 `ready`、`matches_current_iff: true`，且 manifest 的 IFF 哈希等于本次输出。HTTP 图片可访问不等于浏览器 GPU 已正确显示。

两者都不执行 2K 的完整原生 shader、运行时动画/布料、回放渲染或碰撞。网页和离线 Blender 截图的日光、透明度、反光是近似，不可保证游戏完全一致。R13 的浏览器自动截图当时不可用；`r13-preview-http-current.json` 仅证明 272 个纹理 HTTP 资源字节检查通过，`browser_gpu_verified` 是 false。六张 R13 截图明确来自实际 IFF 解码 GLB 的离线渲染。

## 9. 离线验收与最少游戏测试

先看这些当前报告：

| 报告 | 证明范围 / 限制 |
|---|---|
| `validation/iff-current.json` | 当前 IFF 身份、封装/CRC/引用/D3D、改动和待验证状态 |
| `validation/native-source-build.json` | 源 GLB 到原生网格/纹理的映射；不是最终修订包 |
| `validation/r13-chilis-photo-audit.json` | 逐图观察、图号与材料/空间依据 |
| `validation/r13-chilis-material-current.json` | 源模型本轮允许修改对象、保护项及材质 |
| `validation/r13-material-export-current.json` | 源 GLTF 颜色/金属/粗糙度通道检查 |
| `validation/r13-native-current.json` | 实际包内材质和非门店保护项；限定本轮基线 |
| `validation/r13-native-duv-audit.json` | 指定对象仅派生 UV 密度提示的极小浮点变化证明，不是通用放宽阈值 |
| `validation/r13-glass-final-current.json` | 原生玻璃资源、骨架/Presentation 与本轮参数 |
| `validation/native-basket-rig-current.json` | 动态篮架结构和 LOD 约束，非游戏动画验收 |
| `validation/r12-seating-native-current.json` | 座椅与 44 角色标记、方向对应，不证明模式实际调用 |
| `validation/half-court-current.json` | R12.1 换端的历史单项证据；R13 还应看 `iff-current.json` 内本轮方向字段 |
| `validation/r13-native-visual-validation.json` | 当前最终 IFF 解码渲染，照片构图/材料质量需人工看图 |
| `validation/r13-preview-http-current.json` | 网页服务资源身份与可用性，不是浏览器截图 |

专项审计有版本、基线和临时输入要求。例：`audit_r13_native.py` 读取 `native-source-build.json` 中 `source_assets_metadata` 指向的临时 `assets.json`；清理后需先重新导出中间数据。其受保护基线针对 R12.1→R13，后续修改不能冒充仍对这份基线零变化。`audit_r13_duv_metadata.py` 需要前后两份实际包和原始映射；旧包清理后不能凭报告重造比较输入。

一个仍适用于当前包的独立检查，以及当前六视角渲染命令：

```powershell
python -X utf8 tools/validate_d3d_textures.py output/arena_700_int.iff
blender --background --python tools/render_r13_material_current.py -- --views entry,sign,hardware,awning,paving,backboard --width 1600 --height 1000 --samples 24 --threads 8
```

注意 D3D 检查器按成员名前缀选择纹理；当前默认选择尚不包含 `zgc_r13_glass_*`，不能把它们算作该 D3D 报告已覆盖。R13 玻璃另有专项逐 mip 与原生资源检查。以后增加纹理家族时必须核对实际覆盖数量/前缀，必要时扩展检查再运行。渲染前须先导出与当前 IFF 对应的 native preview；不要为修图隐藏导入几何、换材质或修改输出包。

集中一次游戏检查清单：

1. 先在网页的游戏包模式确认主立面、灯牌、门窗、雨棚、灰石和篮架近景；确认只有本轮候选。
2. **完全退出游戏后**，用户将 `output/arena_700_int.iff` 放入其正常使用的 `levels` 替换同名文件，再重新进入同一 Blacktop。不要假设热加载。
3. 半场检查进入的是黄黑端；正常镜头确认地面/球员可见，三分边界、球员脚下标志、篮架对齐正确。
4. 同次运行检查近距离篮板、回放、扣篮挂框；观察黑片、白框消失、组件不同步。再看主立面材质、替补/教练是否各自坐在右侧座椅。
5. 若仍有全黑，用同次场景的 2K Camera/拉远视角观察是否解除几何遮挡，记录是“全场全黑”还是“仅篮板回放黑”。只要能提供一组明确前后视角，就先根据证据离线分析。
6. 若需正常底包对照，完全退出后再换回原“洛克公园”副本改名 `arena_700_int.iff`，同入口检查；不要一次同时启用两个覆盖相同槽位的候选。原始底包本身保持不变。

保存测试用 IFF 身份、入口、结果和截图。只有用户确实测试了对应包，才能把 `game_tested` 改为 true；不能因为网页正常或报告全绿而改这个状态。

## 10. 夜景 N1–N16（R13 之后）

用户要求做夜景和场边灯带，先只测夜景基调，再单独试 A 字牌白色灯罩发光。`tools/night_lighting.py` 只改 `level.SCNE` 已有数值：`Light.Sun` 强度降为 1/200 并改冷蓝，`TIME_OF_DAY` 的 `VC_SkyIntensity`/`VC_SunIntensity` 降低并关闭云层，48 个 `LIGHT_PROBE_GRID_*_EV100` 下调 6 EV（N2）。N2 实测地面和建筑已暗，但天空、远处白雾、玻璃反射仍亮，因此 N3 再开启原生 `TIME_OF_DAY`（22:00，`VC_NightEV100` 固定为相机 EV100 14.8）并打开两个 IBL 的 `VC_IsLitDynamically`。N1（1/25、-2.5 EV）游戏实测：整体变暗未发白，但呈阴天/雾天，证明探针标记下调确实压暗环境光。目标值按白天底包绝对计算，可在旧夜景包上重复补丁而不叠加。`repair_iff.py` 在半场换端后调用它，所以完整构建会保留夜景；已有包用 `tools/patch_night_current.py` 补丁；其他 Windows 机器可只拷贝 `tools/standalone_night_patch.py`（仅标准库）给本机 R13/N1/N2 包打补丁，结果与本仓库输出逐字节相同。PostEffect 仍强制与底包一致；`global_sun_and_postfx_unchanged` 因此改为 false，另记 `postfx_unchanged`。

参考：室内底包 `arena_020_int_original.iff` 关闭太阳、使用 18 个 SPOT 和 4 个 AREA 灯，并有 `VC_IsNightOnly` 字段，可作为后续给球场加原生灯光的结构依据。项目自制材质（`asset_CLOD`）没有发光参数；底包发光物件使用带 Lightmap 技术的 `simplepbr_CLOD`，套用到自制模型存在旧黑屏风险，必须一处一处试。

N3 游戏实测：夜空（月亮、星星）出现，玻璃反射变暗。N4 在此基础上由 `tools/night_scene.py` 新增 `zgc_n4:` 内容，不改任何已有对象：沿法线外移 0.4 cm 的发光表皮（高杆灯面、A 字牌灯罩、Chili's 字与灯条、logo、The boots 字），围栏底板顶部三段 LED 盒，以及 SPOT/线型 AREA 光源（格式取自室内底包）。发光材质克隆原生 `light_lamppost_genericb:light_mat` 并复制原生路灯 `UserData`；该材质只有 Lightmap 技术，用于自制几何的效果需游戏验证。`repair_iff.py` 在夜景基调后调用它；已有包用 `tools/patch_scene_current.py`（会先清除旧 `zgc_n4:` 内容再重建）。改动后运行 `tools/make_standalone_patch.py` 重新生成给其他 Windows 机器用的独立补丁。若游戏全黑或闪退，先在 `night_scene.py` 去掉发光表皮只保留光源，或反之，逐项排除。

N4–N6 实测失败或效果差（新增 Light 被忽略；未完整绑定的路灯发光不亮；记分牌着色器呆板；透明卡片有角度和排序问题）。ChatGPT 的 LDIAG1 诊断实测确认两条原生路线：① 路灯发光材质 `light_lamppost_genericb:light_mat` 用于新物件时，必须同时具备与物件同名的 `level.Texture`（照抄路灯 64×64 BC4 描述）、路灯 48 字节 `UserData` 和独立 UV7（0–1 内）才会发光并带泛光；② 对球场附近 `LIGHT_PROBE_GRID_*_PROBE_DATA` 每条 112 字节（28 个 float）整体乘增益，可照亮地面、静态物体和球员。N7 按此在 `tools/night_scene.py` 实现，`strip_scene` 会删除 `zgc_n4/n5/n6/probe_emit/diag_receiver/n7` 前缀内容并从 R13 恢复探针描述后重建。实时灯需要重建 `LIGHT_BRICK_MAP`，其多灯格式未破解，缺带灯样本数据；不要再往 `level.Light` 直接加灯。

N8–N16（按用户逐轮游戏截图调整）：去掉场边灯带，高灯杆调到极暗，以 Chili's 和两块 A 字牌为主光源营造午夜氛围；整体环境光由 `night_lighting.py` 的探针 EV100 标记压暗（当前 -7.6 EV，N3.5），不改相机 EV100。`night_scene.py` 的探针增益改为高斯衰减并相加（避免地面分界线），Chili's 暖光带高度淡出（招牌高度不提亮）。N14 游戏诊断确认探针记录为交错 RGB 的 9 系数球谐、L1 顺序 (Y, Z, X)，据此为每个光源加指向光源的 L1 方向光（DIRECTIONALITY 0.85），并做冷色分级 (0.70, 0.85, 1.08)。带发光贴图的原生壁灯材质 `light_lampsconce_swirls:light_lampsconce_swirls_mat`（同样需同名光照贴图绑定）用于：Chili's 檐口上的字母模糊倒影（回放才有屏幕空间反射），以及远景楼宇和 LINK 玻璃上的世界坐标亮灯窗格。夜空由 TIME_OF_DAY 的 VC_NightSkyIntensity/颜色调成深藏蓝。回放模式使用自己的曝光与后期，与比赛视角不同，无法从场景文件统一。

## 11. 留存、迁移与继续工作

当前源、SVG、引用纹理、原始附件、必要底包、构建工具、当前验证记录以及唯一当前 IFF 应保留。只在新包、对应预览和必要近景验证完成后清理旧产物；临时回滚副本必须放项目内且在游戏加载目录、IFF 容器外，完成后遵循最新版本政策删除。

`powershell -NoProfile -ExecutionPolicy Bypass -File tools/cleanup_current.ps1` 会先验证当前报告/预览、限制删除路径在项目根内再清理。迁移后，历史报告的绝对截图路径可能仍指旧机器；不要绕过其保护。先重新导出当前预览/渲染、生成本机路径，再清理。

不得提交本机服务控制令牌、用户登录数据或运行时缓存。发布只应包含项目素材和必要构建资料；浏览器状态、`.preview-runtime/server-*.json`、依赖安装缓存、游戏存档不属于用户给的参考文件。

继续处理任何细节前，先确定照片图号、具体对象、允许改动范围和检查相机。当前整体模型已获用户大体认可，不回退成旧版本重做。先改善真实可见的几何和材质，把灯光留待用户后续明确开始；一次改动要同时交付更新的可编辑源、可核对的实际 IFF 预览和一个最新游戏 IFF。
