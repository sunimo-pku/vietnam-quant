> 旧版交易所证据采集说明：本文件描述 `daily` 命令，包含派生标志列。新主表采用五个原始状态字段，见 [字段字典](status-schema.md)；本次未切换已有自动任务。

# 三市场当前股票池每日详细状态

## 目标与当前边界

本阶段只采集 HOSE、HNX、UPCOM 全部当前股票，不回填历史。官方股票目录决定股票池；行情板和旧监管名单中的额外代码单独保存，防止混入基金或已退出目录的证券。2026-10-25 实取目录为 HOSE 406、HNX 299、UPCOM 814，共 1,519 只。

交付分为两层：一是完整保留各官方来源今天实际显示了什么；二是对冲突和缺失进行核对后，才能确定适合量化使用的状态。当前已实现前者及质量检查，不能把采集成功等同于全部状态已被确证。

**重要实测纠正：当前官网页面也可能保留旧标签。** HNX 的 KKC、MAS 等在监管名单/公司详情仍显示警示或受控，而当日行情板显示 NRM。已经下载并逐页查看 HNX 的 KKC、MAS、VNT 正式通知 PDF，通知明确解除警示、恢复正常。故不能给任何一个“当前”页面无条件最高优先级；也不能把所有来源的标签简单取并集后作为最终真实状态。

## 每日运行

```sh
.venv/bin/vn-status --output outputs/daily-status daily --workers 8
```

每次创建单独运行目录，原始响应和旧运行不覆盖。网络中断后可在同一运行目录续跑：

```sh
.venv/bin/vn-status --output outputs/daily-status daily \
  --resume outputs/daily-status/runs/运行目录 --workers 8
```

续跑只复用同一越南日历日内、两小时以内的成功请求。隔日运行必定重新请求。使用 `daily-report --run 路径` 可从已保存证据重新生成报告；过期数据会标记不满足本次当前采集，不会伪装成今天的新数据。

可选 `--pool pool.csv`，格式为 `market,symbol`。当前用户已选三市场全量，不需要此参数。

已在本聊天创建每日北京时间 18:00（越南时间 17:00）的自动采集任务，ID 为 `automation`，状态 ACTIVE；仅在状态变化、覆盖下降、采集失败或新冲突等需要关注时通知。依赖本机/应用可执行任务及网络可用，不是独立服务器部署，也未安装系统定时器。单次全量需读取上千个公司详情，耗时受交易所响应影响；HOSE 大响应已实测出现 HTTP 200 但正文截断的情况。程序要求完整响应与结构校验，小页抓目录，行情大响应使用保持 TLS 验证的独立传输方式。

本轮 HOSE 行情接口曾完整返回 409 个代码（其中 406 只股票、3 个基金），随后重复采集仍发生截断失败。因此本轮完整证据可用，但每日可用率尚未通过稳定性验收；任务失败会记录并提示，不宣称稳定自动获取已经被证明。

## 来源与字段

| 来源 | 获取什么 | 已发现的限制 |
| --- | --- | --- |
| HOSE 官方股票目录 | 当前股票范围、证券 ID、发行人、原始上市字段 | 大页响应不稳定，改用每页 20 条并核对总数、唯一代码 |
| HOSE 官方状态分类和名单 | 警示、受控、交易限制、暂停/停止交易，原因、发布日期、生效日期 | 某些新分类为空；不能认为覆盖每个当前状态 |
| HOSE 官方行情板接口 | WID、WFR、WOV、CTR、RES、SUS 等直接字段 | 同一接口包含 3 个基金代码；空字符串不是明确“正常”；不是并存状态全集 |
| HNX/UPCOM 官方目录 | 当前股票池、公司详情链接 | 不应以行情板代替名录 |
| HNX/UPCOM 官方监管名单 | 多个并存的监管标签 | UPCOM 名单不能覆盖所有详情页中的警示；还发现旧标签未同步撤销 |
| HNX/UPCOM 每只股票详情 | 监管状态与交易状态两个独立字段，包含组合标签和明确正常 | 个别字段为空；一些股票保留旧标签，与正式解除通知冲突 |
| HNX/UPCOM 官方行情板 | 管理类别、交易方式、交易处置、系统状态原始代码与显示文字 | UPCOM 的 admin_status 为空；部分停牌/退出股票不在板上；标签可能仅显示优先级较高项 |

HOSE 直接行情接口来自 `https://rtboard.hsx.vn` 实际前端代码：

```text
GET https://api.hsx.vn/l/api/v1/securities/load-securities-matching/1
```

HNX/UPCOM 详情按官方目录返回的链接请求，不自行猜股票存在或市场归属。解析时同时校验 StockCode、MarketCode 及两个状态字段的 HTML 结构。

## 状态维度

| 输出字段 | 含义 |
| --- | --- |
| warning | 警示，可能有更细原因 |
| warning_disclosure | 信息披露相关警示（WID） |
| warning_financial | 财务报告相关警示（WFR） |
| warning_other | 其他警示（WOV） |
| control | 受控（CTR） |
| restriction | 限制交易（RES），可与受控并存（C&R） |
| temporary_suspension | 来源明确写 tạm ngừng/tạm ngưng 等临时暂停 |
| suspension | 来源明确写 đình chỉ |
| halt_unspecified | 来源只给合并暂停/停止类别（如 SUS），不强行细分 |
| special_trading_after_inactivity | HNX 特殊交易方式 SNE |
| special_trading_after_long_halt | HNX 行情板 SLS，按其页面说明保存为停牌后特殊交易，不混同 HOSE 说明 |
| new_listing | 来源给出的新上市标记 |
| compulsory_delisting_reported / voluntary_delisting_reported | 详情页出现强制/自愿退出类别；不是自行推算退出生效日 |
| trading_cancelled / trading_stopped | 详情页明确取消/停止交易文字 |

这些字段允许同时存在。底层还保留完整监管记录、原因、原始时间、详情字段、行情字段和请求收据。

字段目前采用“来源观测”语义：`true` 代表至少一个当前抓取的来源报告这一状态，`null` 代表未确定，不是 `false`。若 `quality=conflict`，有冲突的监管维度在主列置为 null，旧标签保存在 `observed_flags` 和原始字段中，**不把有矛盾的旧警示输出为确定的当前警示**。`normal_reported` 仅记录来源是否明确报告正常；它可以与另一个来源的警示同时出现，此时必须查看冲突。

## 输出与验收

首轮输出在 `outputs/daily-status/runs/20261025T211424634068/`。重新导出后，主表 1,519 行、主键唯一，CSV 与 JSON 行数一致；九个必要批量来源和当前股票所需详情全部取得。15 只股票存在来源冲突，3 只详情的监管字段为空（其中 VNT 同时属于冲突，合计 17 只进入复核队列）。另有 96 个目录外代码放入独立复核文件，其中包含上述 3 个基金。24 项测试通过；覆盖分页完整性、重复数据、空页面、旧数据失效、组合状态、未来生效、冲突留空、基金隔离和失败不覆盖成功指针等。

- `runs/<id>/daily_status.csv`：股票池一只股票一行，详细状态与质量字段。
- `daily_status.json`：含多原因记录、来源、时间、原始字段的完整证据。
- `review_queue.json`：冲突、未知代码、空字段、缺行情/详情或缺目录等需处理行。
- `outside_universe_review.json`：不在当前股票目录的额外代码，供核对，不混入主股票池。
- `manifest.json`：市场数量、各来源结果、详情失败数、所需股票缺失数。
- `sources/*.json`、`raw/*`：逐来源解析与原始证据，可恢复、复核。
- 根目录 `latest_attempt.json`：最新尝试；`latest_success.json`：最近完成必要采集的运行。失败不会覆盖最近成功指针。

`complete_collection` 仅表示本轮必要来源和股票详情已获取且新鲜，不表示事实无矛盾。`all_status_dimensions_verified` 暂为 false，不能把这些原始观测直接接到自动下单逻辑。

`as_of_date` 是越南时区的观察日期，**不是来源交易日期**。周末采集不会被说成周末发生交易；本轮接口没有统一提供交易日期，因此 `source_trading_date` 留空。采集时间也不替代生效日期。

量化验收尚需完成：逐条处理来源冲突；对空字段确认含义；核对各市场当前警示子类覆盖；建立最新有效通知的持续校正机制。详细原因、限制时段、精确生效时间若未在直接字段提供，仍须从适用通知补充，不得编造。

## 2026-10-25 核对的官方依据

- [HOSE 状态代码说明](https://staticfile.hsx.vn/Uploads/UploadDocuments/2372207/9.Cac%20ky%20hieu%20trang%20thai%20chung%20khoan.pdf)
- [HNX 官方行情板及页面状态图例](https://banggia.hnx.vn)
- [KKC 正式状态通知，恢复正常](https://owa.hnx.vn/ftp///cims/2026/2_W1/000000015850548_Scan_5_Feb_2026_at_09.39.pdf)
- [VNT 正式状态通知，恢复正常](https://owa.hnx.vn/ftp///cims/2026/9_W2/000000016835392_Vnt_tb.pdf)
- [MAS 解除决定与状态通知，第 3 页为状态通知](https://owa.hnx.vn/ftp///cims/2026/9_W2/000000016835459_MAS_RaKhoiCB_T082026.pdf)

上述附件已保存到 `outputs/daily-status/current-conflicts/pdfs/`，保留 HTTP/TLS 回执、SHA-256、PDF 文本和人工查看的页面图像。它们用于解释当前来源冲突，不构成已经完成全市场裁定的声明。
