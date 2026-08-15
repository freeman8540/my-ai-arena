# my-ai-arena

## 调研文件

### GitHub 开源项目库存（83 项，独立维护）

- [GitHub 开源 AI 小说、剧本与视频生成项目调研对比（83 个项目）](research/GitHub_AI_小说_剧本_视频生成项目对比_2026-08-13.md)
- [83 个项目逐一验证与置信度报告](research/GitHub_AI_项目逐一验证与置信度_2026-08-13.md)
- [83 个项目可筛选 CSV 明细（已加入置信度字段）](research/GitHub_AI_小说_剧本_视频生成项目明细_2026-08-13.csv)
- [独立验证明细 CSV](research/GitHub_AI_项目逐一验证明细_2026-08-13.csv)

> 上述 4 个文件是原有 GitHub 开源库存，数量固定为 **83 项**。商业产品不会追加到这些文件中。

### 商业工具独立目录（138 项）

商业产品、闭源 SaaS、商业桌面软件、云 API 与订阅型创作服务单独放在 [`research/commercial_tools/`](research/commercial_tools/)：

- [商业工具目录说明与交接边界](research/commercial_tools/README.md)
- [138 项商业 AI 创作工具 CSV](research/commercial_tools/商业工具明细_2026-08-15.csv)
- [CSV 源数据 JSON](research/commercial_tools/商业工具目录源数据_2026-08-15.json)
- [生成与隔离校验脚本](research/commercial_tools/generate_commercial_tools_csv.py)

> 商业目录与 83 项 GitHub 开源库存**完全分层**。生成脚本只读取原有 83 项 CSV 做名称/URL 隔离校验，不会合并、追加或重写原有库存。
