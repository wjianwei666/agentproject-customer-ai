# 电商智能客服 Agent

> 根据输入需求，匹配对应的标签人群信息，给出具体对应的响应信息。
> 双交付路线：**Dify 低代码工作流** + **本地代码版**，共用同一套 YAML 配置与 Markdown 提示词。

---

## 一、交付清单对照

| # | 需求 | 交付物 | 位置 |
|---|---|---|---|
| 1 | 完整 PDF 项目方案文档 | 9 章合并 PDF（封面 + 目录 + 页码 + 内嵌图） | `docs/项目方案.pdf`（运行 `python scripts/build_pdf.py` 生成） |
| 2 | 架构流程图、业务时序图、节点拆解 | Mermaid 图 + 节点表 + 变量对照表 | [docs/06-Agent节点拆解与架构时序.md](docs/06-Agent节点拆解与架构时序.md) |
| 3-A | 配套提示词库 | 6 个节点提示词 + 提示词库说明章节 | `prompts/`、[docs/06b-提示词库.md](docs/06b-提示词库.md) |
| 3-B | Dify 导入配置文件 | 18 节点工作流 DSL（含脱敏/整改重试/转人工/工单） | `dify/ecommerce_cs_agent.yml` |
| 3-C | 代码版源码 | 9 个模块 + FastAPI 接口 | `src/` |
| 4 | 本地部署教程、演示截图组、测试样例 | 部署教程 + 8 张演示截图及图注 + 演示截图组 PDF + 演示脚本 + 23 条单测 | [docs/07-本地部署与演示教程.md](docs/07-本地部署与演示教程.md)、`docs/演示截图组.pdf`、`docs/assets/shots/`、`scripts/demo.py`、`tests/` |

---

## 二、方案文档目录

| 章节 | 文档 | 对应角色 |
|---|---|---|
| 第一章 | [00-项目总控评审纪要](docs/00-项目总控评审纪要.md) | CEO 统筹 |
| 第二章 | [01-需求调研报告](docs/01-需求调研报告.md) | 营销需求调研大师 |
| 第三章 | [02-产品方案](docs/02-产品方案.md) | 资深产品设计规划大师 |
| 第四章 | [03-技术方案](docs/03-技术方案.md) | 资深技术研发专家 |
| 第五章 | [04-营销方案](docs/04-营销方案.md) | 资深市场营销大师 |
| 第六章 | [05-质量保障方案](docs/05-质量保障方案.md) | 资深软件质量总监 |
| 第七章 | [06b-提示词库](docs/06b-提示词库.md) | 技术 + 产品 |
| 第八章 | [06-Agent节点拆解与架构时序](docs/06-Agent节点拆解与架构时序.md) | 技术 + 产品 |
| 第九章 | [07-本地部署与演示教程](docs/07-本地部署与演示教程.md) | 技术 |

---

## 三、快速开始

```bash
pip install -r requirements.txt

# 跑单元测试
python -m unittest discover -s tests -v

# 命令行演示（无需 API Key）
python scripts/demo.py

# 启动 HTTP 服务
uvicorn src.api:app --port 8000 --reload
```

打开 <http://127.0.0.1:8000/docs> 查看接口文档。

生成 PDF 方案文档：

```bash
python scripts/build_pdf.py
```

文档中的 Mermaid 流程图/时序图会由 `scripts/mermaid_render.py` 用 Pillow 现场绘制成 PNG
再嵌入 PDF（无需 mermaid-cli、Node、浏览器等外部依赖）；遇到不支持的语法会自动回退为代码块，
不影响 PDF 生成。只想单独导出图片时，可直接运行：

```bash
python scripts/mermaid_render.py "docs/06-Agent节点拆解与架构时序.md" docs/assets
```

生成演示截图组（第八章第九章交付用，输出 `docs/assets/shots/shot-01~08.png`）：

```bash
python scripts/build_shots.py
```

把 8 张截图 + 教程第九章打包为独立《演示截图组.pdf》（交付物 D4，与方案 PDF 一并提交）：

```bash
python scripts/build_shots_pdf.py
```

---

## 四、Agent 链路

```
入参脱敏 → 意图识别 → 标签人群匹配 → 知识检索 → 话术生成 → 合规质检 → 转人工兜底
```

| 节点 | 实现 | 策略 |
|---|---|---|
| 脱敏 | 正则 | 先 18 位证件号，再 11 位手机号 |
| 意图识别 | 关键词规则打分 | 命中即定，8 类意图，低置信度转人工 |
| 标签人群匹配 | 7 维标签加权规则 | 得分 ≥ 45 命中，否则兜底人群 |
| 知识检索 | 纯内存 BM25 | Top3 召回，零第三方依赖 |
| 话术生成 | LLM / 模板 | 按画像语气 + 事实边界约束 |
| 合规质检 | 正则 block/warn | 三重防线：拦截 → 整改 → 本地替换 |
| 转人工 | 条件判断 | 4 类触发：高危意图、低置信度、知识缺失、用户主动要求 |

**降级设计**：无 LLM API Key 时自动走模板生成，全链路不中断、不抛错。

---

## 五、可调配置（运营无需改代码）

| 文件 | 内容 | 常见调整 |
|---|---|---|
| `config/app.yaml` | LLM、检索 TopK、转人工阈值 | 换模型、调阈值 |
| `config/personas.yaml` | 7 个画像的规则、权重、语气、禁区 | 新增人群、调权重 |
| `config/intents.yaml` | 8 类意图关键词 | 补关键词 |
| `config/compliance.yaml` | 7 条合规规则 + 兜底替换文案 | 新增违规表述 |

---

## 六、双路线如何保持一致

1. **配置唯一真相源**：`config/*.yaml` 同时被代码版读取、被 Dify 代码节点内联引用；
2. **提示词唯一真相源**：`prompts/*.md` 直接粘贴进 Dify 的 LLM 节点；
3. **变量命名对齐**：`docs/06` 第五节的变量对照表，保证切换路线时前端零改造。

---

## 七、验收标准

| 项 | 标准 |
|---|---|
| 单元测试 | 23 条全部通过 |
| 离线可运行 | 不设 API Key 时 `python scripts/demo.py` 完整跑通 |
| 合规零下发 | 黄金集内 block 级违规数为 0 |
| 接口契约 | `/chat` 返回字段与 `src/models.py` 完全一致 |
| 文档完整 | 9 章文档齐全，PDF 一键生成且含目录页码与内嵌架构图 |# agentproject-customer-ai
