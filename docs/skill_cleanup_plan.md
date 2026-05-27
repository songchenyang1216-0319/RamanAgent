# Skill Cleanup Plan

## 1. 当前 registry 真正注册了哪些 Skill

以 `backend/skills/registry.py` 里的 `skill_registry` 为准，当前真正写入 registry 的 builtin Skill 只有 3 个：

- `raman_spectroscopy_skill`
- `agent_system_skill`
- `web-search`

另外，`list_skills()` 还会把上传 Skill 追加进来。当前 `backend/data/uploaded_skills.json` 中有 1 个已加载的上传 Skill：

- `text-document-processor`

所以当前 `list_skills(include_actions=False)` 实际展示 4 项，但其中只有 3 项属于 builtin registry。

## 2. backend/skills/ 下哪些 Skill 文件没有注册

下面这些文件当前没有作为独立 Skill 注册到 `skill_registry` 中：

- [`backend/skills/experiment_report_skill.py`](../backend/skills/experiment_report_skill.py)
- [`backend/skills/methanol_analysis_skill.py`](../backend/skills/methanol_analysis_skill.py)
- [`backend/skills/model_health_check_skill.py`](../backend/skills/model_health_check_skill.py)
- [`backend/skills/raman_methanol_skill.py`](../backend/skills/raman_methanol_skill.py)
- [`backend/skills/spectral_file_skill.py`](../backend/skills/spectral_file_skill.py)
- [`backend/skills/spectral_preprocessing_skill.py`](../backend/skills/spectral_preprocessing_skill.py)
- [`backend/skills/spectral_visualization_skill.py`](../backend/skills/spectral_visualization_skill.py)
- [`backend/skills/spectrum_loader_skill.py`](../backend/skills/spectrum_loader_skill.py)

补充说明：

- [`backend/skills/upload_service.py`](../backend/skills/upload_service.py) 不是 Skill 实现文件，是上传与持久化支撑代码。
- [`backend/skills/uploaded_package_skill.py`](../backend/skills/uploaded_package_skill.py) 也不是单独业务 Skill，而是上传 Skill 的发现与运行框架。

## 3. 哪些文件是旧版重复功能

- [`backend/skills/raman_methanol_skill.py`](../backend/skills/raman_methanol_skill.py)  
  旧版甲醇预测封装，和 `raman_spectroscopy_skill` 里的甲醇预测链路重复度很高。

- [`backend/skills/spectrum_loader_skill.py`](../backend/skills/spectrum_loader_skill.py)  
  旧版 CSV 读取 Skill，和 `spectral_file_skill` 的读取/校验职责重复。

- [`backend/skills/experiment_report_skill.py`](../backend/skills/experiment_report_skill.py)  
  单独的报告 Skill，和 `raman_spectroscopy_skill` 中的报告输出能力重叠。

- [`backend/skills/model_health_check_skill.py`](../backend/skills/model_health_check_skill.py)  
  更像 `agent_system_skill` 的内部依赖，不适合继续作为独立对外 Skill。

## 4. 哪些建议合并到 raman_spectroscopy_skill

如果后续要进一步收敛对外 Skill 数量，建议把下面这些文件继续保留为内部组件，或逐步合并进 `raman_spectroscopy_skill`：

- [`backend/skills/spectral_file_skill.py`](../backend/skills/spectral_file_skill.py)
- [`backend/skills/spectral_preprocessing_skill.py`](../backend/skills/spectral_preprocessing_skill.py)
- [`backend/skills/spectral_visualization_skill.py`](../backend/skills/spectral_visualization_skill.py)
- [`backend/skills/methanol_analysis_skill.py`](../backend/skills/methanol_analysis_skill.py)
- [`backend/skills/experiment_report_skill.py`](../backend/skills/experiment_report_skill.py)
- [`backend/skills/raman_methanol_skill.py`](../backend/skills/raman_methanol_skill.py)
- [`backend/skills/spectrum_loader_skill.py`](../backend/skills/spectrum_loader_skill.py)

建议思路：

- 对外只保留一个 `raman_spectroscopy_skill`
- 内部继续拆成文件读取、预处理、预测、可视化、报告几个小模块
- 以后如果要做更严格的 Skill 管理，再决定是否把这些小模块移到更明确的私有目录

## 5. 哪些建议保留为独立 Skill

建议继续保留独立对外 Skill 的有：

- [`backend/skills/agent_system_skill.py`](../backend/skills/agent_system_skill.py)
  - 负责系统信息、模型检查、Skill 列表、会话状态等
  - 属于平台级能力，不适合并入 Raman 主链路

- [`backend/skills/web_search/web_search_skill.py`](../backend/skills/web_search/web_search_skill.py)
  - 负责联网搜索
  - 和 Raman 业务分析目标不同，建议保持独立

- `text-document-processor`（上传 Skill）
  - 当前已经作为 uploaded skill 加载
  - 适合继续保持独立，不建议并入 Raman

## 6. 暂时结论

- 当前最清晰的公开结构应该是：`raman_spectroscopy_skill`、`agent_system_skill`、`web-search`，再加上传 Skill `text-document-processor`
- 其余文件主要是内部拆分件或旧版重复实现
- 这次先不删文件，优先把路由和注册边界收紧，等下一阶段再做目录级收敛
