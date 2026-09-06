# Vibecad-bait

NBA 2K26 海边室外篮球场 MOD。五张照片作为同一个球场的综合参考，忽略人物；标准篮球标线、深灰哑光水泥、草坪台阶、金属看台与棕榈树共同组成一个开放场景。

当前本地候选：[Revision 5 交接与验证边界](nba2k-arena/docs/REVISION5_ZH.md)。

- [Revision 5 完整压缩包](nba2k-arena/output/revision5/venice_court_revision5.zip)：包含同编号的两份 IFF 及校验信息。
- [产物校验](nba2k-arena/output/revision5/validation.json)
- [R4 场外设施与地形记录](nba2k-arena/docs/REVISION4_ZH.md)
- [上一版 R3 修复记录与归档](nba2k-arena/docs/REVISION3_ZH.md)
- [原始五图](nba2k-arena/textures/source/references/)、[AI 增强辅助图与来源记录](nba2k-arena/textures/source/references/enhanced/README.md)
- [材料来源及原着色器通道依据](nba2k-arena/docs/revision3_materials.md)
- [Checkpoint 1 用户实测反证](nba2k-arena/evidence/user_game_screenshot_checkpoint1_REJECTED.png)
- [历史 V1/V2 交接](nba2k-arena/handoff/HANDOFF_ZH.md)

Revision 5 补齐照片中的浅灰中圈、罚球区矩形与半圆，使用同源 4K 哑光水泥扫描，并逐项检查白线覆盖及深度边界；保留 R4 的路灯、桶组、看台和草台改进。静态资源检查和导出几何预览不等于 NBA 2K 游戏画面验收；天空、树木着色、日影及完整室外篮架仍待实际验证或补齐资源。原 donor、历史输出、原场地与篮筐变换、碰撞和玩法锚点均保留。开发过程不会安装建模软件或写入游戏目录。

构建依赖 Python 3、NumPy、Pillow（支持 DDS 编码）：

```sh
python3 nba2k-arena/scripts/build_revision5.py
python3 -m unittest discover -s nba2k-arena/tests -v
python3 nba2k-arena/scripts/revision5_preview.py --three-dir /path/to/three
```

IFF 内仍使用原生 ZIP_STORED 资源结构，分发 ZIP 仅做外层无损压缩；解压分发包后使用两份 IFF，不要再解开 IFF 本身。
