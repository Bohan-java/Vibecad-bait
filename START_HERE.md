# NBA 2K26 球场项目 — 已继续开发

2026-09-06：用户已明确继续开发 NBA 2K 球场，并允许在保留场地尺寸、篮筐、碰撞和玩法锚点的前提下调整室内装饰可见性与照明，目标为室外标准篮球场外观。

**先看 [Checkpoint 1 当前状态与测试方法](nba2k-arena/docs/checkpoint1/CHECKPOINT_ZH.md)。** 此检查点恢复原标线贴图引用、关闭 donor 四分线显示，并提交标线／黑树诊断。它是待游戏验证的候选，不是最终成品。

## 历史交接背景（V1/V2 已被用户否定）

请先读 [详细交接报告](nba2k-arena/handoff/HANDOFF_ZH.md)，再看
[用户实际游戏截图](nba2k-arena/evidence/user_game_screenshot_revision2_REJECTED.png)。

当前交付的是失败现场和可继续开发的资料，不是合格成品。
交接时用户要求停止改模、整理交接并上传此仓库；当前继续开发的授权见上文。
仍不自动安装或测试到用户游戏目录。

- 原始 donor、失败的 V1/V2 IFF、全部相关脚本、5 张参考照片和本地预览均在 `nba2k-arena/`。
- 旧文档里的 PASS 只代表静态检查；用户已经提供反证，视觉目标没有达成。
- donor 原有室内屋顶/结构仍在，树在游戏中近黑色，球场包含非标准的四分线和其他标线。
- `handoff/reproduce_revision2.py` 使用附带的最小缓存，不需要完整游戏或 Oodle DLL，即可复现此失败版本及离线预览。
- 文件清单和 SHA-256 在 `handoff/FILE_MANIFEST.json`。

没有上传游戏安装包、完整资源档案、DLL、凭据或账号配置。
