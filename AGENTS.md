# Project conventions

- README.md 面向使用者写成产品描述、使用步骤、结果与失败处理；实现细节、模块结构、开发命令和 CI 放到 docs。

- 当前阶段只处理 HOSE、HNX、UPCOM 当前股票每日状态；历史重建是独立研究。
- 四个原始爬虫集中存放在 `legacy/`，三个数据快照仍在根目录；内容均保留基线 `ba64370e` 的原始字节，包括换行格式。
- 新的原始状态表代码放在 `src/vietnam_quant/current/`，旧研究代码逐步迁移。
- 主表严格遵循 `current/contract.py`：日期、市场、代码和五个原始状态字段。
  不增加派生布尔列、合并状态、中文标签列、对照结果或质量列。
- SSI 的监管状态作为主表监管字段；DNSE 的监管字段留在原始响应供核对。
- 不把空值、未指定、未知编码、请求失败或缺少名单视为正常。不丢弃受限/停牌股票。
- 数据所属交易日取来源；抓取时间、生成时间和交易时间都不是状态生效时间。
- 原始响应与请求收据不可覆盖；质量问题单独输出，禁止把旧快照伪装为实时采集。
- 公开接口不需要账户或 API Key；官方配额未知，不按其他产品的配额推断。
- 禁止把 `outputs/`、本地数据库、凭据、浏览器状态或全量行情样本加入 Git。
- 测试默认离线，使用 `tests/fixtures/current/`；CI 不请求真实证券接口。
- 验证：`python -m unittest discover -s tests -v`；新模块运行
  `python -m ruff check src/vietnam_quant/current tests/test_current.py` 与相应 format 检查。
- 不擅自修改已有自动任务命令；新流程验证完成后再显式切换。
