> 这是 2026-10-26 整理工程结构前的研究入口说明。原命令保留；其中派生状态表不是新的主表约定。命令均从仓库根目录运行。

# Vietnam Quant

越南证券公告与事件数据采集项目。当前仓库保存原有采集脚本及数据快照，作为后续工程化重构的初始基线。

## 当前重点：每日详细状态

当前阶段只处理 HOSE、HNX、UPCOM 全部当前股票的每日详细状态。运行：

```sh
.venv/bin/vn-status --output outputs/daily-status daily --workers 8
```

输出一只股票一行的警示及警示子类、受控、限制、暂停/停止交易等多维证据，同时保留组合状态、来源冲突和未知值。股票池取官方股票目录；基金及旧名单中目录外代码另列。首次实查发现官网名单/详情可能保留已解除的旧标签，因此“请求成功”不等于“状态已确证”。操作、字段语义和未解决问题见 [每日状态说明](current-daily-status.md)。

## 采集脚本

四个原始脚本现统一存放在 `legacy/`，仅调整位置，内容及原有路径配置保持不变。

| 文件 | 当前用途 |
| --- | --- |
| `legacy/HOSE_最终1.py` | 使用 Selenium 驱动 Edge，拦截 HOSE 公告接口响应，按月抓取并合并去重。 |
| `legacy/HNX.py` | 抓取 HNX 历史公告表，解析分页表格并分批保存。 |
| `legacy/爬公告BCG.py` | 抓取 Vietstock 单只股票的分红发行、上市退市等事件；当前代码中指定的股票为 VNL。 |
| `legacy/爬所有公告cafeF.py` | 读取股票代码列表，从 CafeF 批量抓取公告日期、标题和链接。 |

## 数据快照

| 文件 | 内容 |
| --- | --- |
| `hnx_market_supervision_history_full.csv` | HNX 历史公告表快照。 |
| `hose_co_phieu_20260901_20261003.csv` | HOSE 公告快照，包含公告标识、标题、代码、日期时间及详情链接等字段。 |
| `hose_announcements.zip` | 按股票代码保存的 CSV，包含原始版与填充 `status` 字段的 updated 版；状态编码定义尚未记录。 |

## 当前状态

原有四个脚本相互独立，包含 Windows 本地路径和外部输入依赖。它们作为初始基线保留；新的采集入口已有依赖管理、原始响应存档、分页校验和状态变化记录，见下文。

## 新的状态数据采集入口

`src/vietnam_quant/` 提供独立于原 Selenium 脚本的公开接口采集入口：

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/vn-status history --start-year 2000
.venv/bin/vn-status calendar --start-year 2000
.venv/bin/vn-status snapshot --quotes --universe
.venv/bin/vn-status audit
.venv/bin/vn-status watch --interval 300 --quotes --universe
```

`watch` 每轮完成后等待 300 秒，再重新读取当前名单；Ctrl-C 停止。它需要在运行中的电脑/服务器上保持进程，本项目没有自动安装后台任务。允许设置 `--cycles 2` 做有限轮次验证。这里的间隔是本地查询间隔，交易所自身的信息发布延迟还没有量化。

开发环境也可运行 `PYTHONPATH=src python3 -m vietnam_quant.cli ...`。需要系统 `curl` 和正常 TLS 验证，HNX 在当前 macOS 上使用系统证书链访问成功；程序不会关闭证书校验。

默认输出在 `outputs/status-data/`，可用 `--output` 修改（放在子命令之前）：

| 输出 | 含义 |
| --- | --- |
| `historical_announcements.csv` | HNX、UPCOM 监管公告索引，带稳定公告 ID；发布日期不是状态生效日。 |
| `history_manifest.json` | 按年份下载的实际条数、分页收据与失败清单。 |
| `vietstock/events.json` | 上市、退市、警示、控制、限制、停牌等历史事件，保留原字段、正文和附件链接。 |
| `vietstock/manifest.json` | 按月下载的覆盖、失败及跨月重复清单。 |
| `current_statuses.csv` | HOSE、HNX、UPCOM 当前监管名单；保留每条原因及采集时间。 |
| `statuses.sqlite` | 历次监管名单、名单变化与采集失败记录。 |
| `current_quote_flags.json` / `quote_flags.sqlite` | HNX、UPCOM 行情板的补充交易状态；运行时加 `--quotes` 获取。 |
| `current_stock_directory.json` / `stock_directory.sqlite` | 三市场股票目录及变化；运行时加 `--universe` 获取，目录中的上市状态原始字段与监管标签分开保留。 |
| `ssc/articles.json` / `ssc/manifest.json` | 证监会旧档案正文、来源、日期待核验标记及检索覆盖。 |
| `raw/` | 原始响应及请求参数、HTTP 状态、采集时间、内容哈希；用于回溯和复核。 |

历史采集可利用原始响应恢复，`--refresh` 强制重新请求。每个历史分区校验总数、每页条数和去重；失败分区会记录为失败，不会当成零条或完整覆盖。某些 Vietstock 空查询返回 HTTP 200 空正文，没有总数，因此保留为未知覆盖。

旧证监会档案可以用关键词下载，或使用已逐页导出的检索索引：

```sh
.venv/bin/vn-status archive --query 'tạm ngưng'
# 本次已导出的 2004 年索引保存在本地输出目录。
.venv/bin/vn-status archive --query 'tạm ngưng' --index outputs/status-data/ssc_2004_index.json
```

URL 关键词检索只返回第一页，程序明确记录总数与已获取条数；未取全则返回失败状态。网页多页索引使用 `reported_total` 与 `pages[].links[]` 校验。旧档案正文包含未来日期会标记待复核：它可能是提前公告，也可能是日期/正文错配，不能自动视为错误或生效日。

当前名单保留多种状态和同一状态的多个原因。程序记录 `added` / `removed` / `changed` 名单变化，**名单移除不等于已确认恢复正常交易**。某个市场失败时保留其上一份有效快照，CSV 的 `observed_at` 可判断各市场新鲜度；超过 50% 的名单突然消失会进入人工复核。

**历史事件和监管公告尚不能直接作为自 2000 年起无缺口的逐日状态表。** 还需要核验历史市场归属、生效/解除日期、状态语义和早期档案覆盖，缺失部分不得填为正常。行情板也不是完整股票池：一些停牌股票不会出现在行情接口中，因此监管名单必须独立采集。

股票目录、监管名单和行情板各自保留来源及观察时间。某股票不在目录/行情板中可能涉及退出市场或其他来源差异，不能仅据此认定停牌；不在监管名单中也不会自动输出“正常”。

验证：`PYTHONPATH=src python3 -m unittest discover -s tests -v`。

实际下载结果、覆盖缺口和来源见 [数据可获取性报告](data-feasibility.md)。
