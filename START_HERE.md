# 开始使用

## 取得完整工程

需要 Git 与 Git LFS。执行：

```powershell
git clone --branch "大融城OG-Snippy-snoopy-Dingus-court" https://github.com/Bohan-java/Vibecad-bait.git
cd Vibecad-bait
git lfs pull
```

只玩游戏：下载 `nba2k-arena/zgc-court/output/arena_700_int.iff` 的真实 LFS 内容。文件应为 **1,685,622,410 字节**。完全退出游戏，再将它拖入用户平时使用的 `levels` 替换同名文件。不要同时装入制作底包，也不假定支持热加载。

## 继续制作

先读 [TRANSFER_GUIDE.md](nba2k-arena/zgc-court/TRANSFER_GUIDE.md)，从 `nba2k-arena/zgc-court/source/scene.blend` 继续增量修改。不要执行旧建模脚本来覆盖已接受的大体模型。

环境记录：Windows；Blender 5.2.2 LTS；Python 3.12，NumPy 2.3.5、Pillow 12.3.0；Node ≥20，Three.js 0.180.0，Sharp 0.35.4。Blender 与 Python/Node 自行安装；包内没有复制系统程序或登录数据。

在 `nba2k-arena/zgc-court/` 下按需安装本地依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install numpy==2.3.5 Pillow==12.3.0
npm ci
npm install --no-save --package-lock=false sharp@0.35.4
```

将 `config/project.json` 的 `tools.blender_path`、`tools.node_path`、`tools.sharp_module` 改为本机真实路径。Sharp 可以指向本工程的 `node_modules/sharp`。原配置中的游戏目录只用于记录，不是授权写入路径。

## 在新机器查看已交付 IFF

Git 检出会改变文件修改时间，旧清单中的时间戳可能让网页显示“预览过期”。在上述工程目录执行：

```powershell
.\.venv\Scripts\python -X utf8 tools/export_native_preview.py
.\Start_Preview.bat
```

这会从当前实际 IFF 解码预览、写入本机时间戳，不改变 IFF。打开 <http://127.0.0.1:4173/>，选择“游戏包预览”。灯牌、门框五金、雨棚、灰石和篮架均有近景按钮。

“编辑源预览”来自源 GLB；“游戏包预览”来自 IFF 内的坐标、缓冲区和 DDS。两者都不模拟实际游戏着色、回放透明通道、动态篮网或球员。

## 防止误改和黑屏回归

- 保留四个技术底包的相对位置，见 [依赖清单](nba2k-arena/BUILD_DEPENDENCIES.json)。不要把 donor 的外观当成真实中关村场景。
- 必须经过 `repair_iff.py` 完成兼容封装；不能交付未修复的 `source-base.iff`。
- 不使用普通 JSON 加载/重写来吞掉 SCNE 重复键；不凭空新增材质/光照参数；不通过全局提亮掩盖错误。
- 保留专用篮板 Presentation 通道、原生骨骼、地面零高度和已修正的半场方向。完整约束及检测覆盖范围见交接指南。
- 先离线比较容器、引用、几何与材质，再安排一轮明确游戏测试。只有用户实际测试对应文件后才能标记 `game_tested=true`。

当前源、原始照片和技术底包不是旧产物。每轮交付仍只保留一个最新游戏 IFF，清理时避免删除这些输入。
