# 灯光研究 V2 交付包

先读 `LIGHTING_RESEARCH_V2_ZH.md`，或用浏览器打开同名 HTML。

研究基线：Bohan-java/Vibecad-bait，`92056876b32e7f383e591cedd25494747f48fea3`。

本包包含报告、只读取证器 1.1、11 项取证测试、6 项流程契约测试，以及实际测试日志。代码只依赖 Python 3.10+ 标准库。测试为人工数据复现，不证明真实 IFF 的多灯索引已解码或游戏灯光已经成功。

从本目录执行：

```text
python -m unittest discover -s tools -p "test_*.py" -v
```

`evidence/v1_short_reference_regression.txt` 保存修复前两个新增用例失败的日志。`evidence/synthetic_tests_v2.txt` 保存修复后全部 17 项通过的日志。

工具提取命令、目录摆放方式和后续实验见报告第 7–9 节。`test_pipeline_contracts.py` 中的 cleanup 函数来自研究提交的摘录，资源遍历使用简化桩；它不会导入或运行项目构建流程。生产脚本和球场文件均未修改。

GitHub 代码写入与 Issue 发布尝试均返回 HTTP 403；本包尚未发布到仓库。需要有写入权限的协作者把本目录加入项目。建议位置为 `nba2k-arena/zgc-court/docs/light-brick-research/`，保持 `tools/` 和 `evidence/` 的相对关系。
