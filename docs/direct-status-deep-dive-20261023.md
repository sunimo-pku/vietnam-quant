# 直接历史状态数据：深挖与实抓结果

核验日期：2026-10-23。目标是 HOSE、HNX、UPCOM 的逐股票、逐日监管与交易状态，历史从 2000 年起，并能持续更新。

用户明确要求量化所需的多维状态，尤其警示；只包含停牌/可交易标志的产品不合格。以下对接口的评价以警示、受控、限制交易、暂停/停牌、解除、上市/退市等状态共同覆盖为准。

## 结论

**直接的历史数据确实能获取，不需要先读公告才能开始建表。** 本轮实际补到全量接口股票名录、官方历史退市登记、结构化状态进入及解除事件。但尚未取得覆盖 2000 年以来所有股票、所有日期、所有状态的成品表。

这里的“全量”仅用于已校验总数、分页和唯一键的具体接口查询，不代表越南市场全部历史事实。警示、受控、限制交易和停牌应保存为独立维度；“限制交易＋交易系统仍为活动状态”可以同时出现。

## 已经落地的数据

本轮原始响应、HTTP/TLS 结果、请求参数及哈希在 `outputs/direct-status-research-20261023/`。旧采集结果保留在 `outputs/status-data/`，未覆盖。

| 数据 | 实际结果 | 可以解决什么 | 不能据此断言什么 |
| --- | --- | --- | --- |
| VNDIRECT 股票名录 | 1,971 条、1,971 个唯一代码；上市 1,519、已退市 452 | 补充退出市场的股票；取得上市/退市日期及公司标识 | 不是历史每日警示、停牌表；也未证明收齐所有历史股票 |
| HOSE 官方退市登记 | 2000—2026 年 27 个查询分区全部完成；2,194 个唯一事件 ID | 直接获得日期、证券代码、证券 ID、撤销上市数量 | 混有债券和权证，不能把 2,194 全算股票 |
| HOSE 退市登记与股票名录匹配 | 156 条、155 个代码 | 补充股票退出 HOSE 或转板的历史时间点 | 按代码匹配，不等于逐条完成证券类型及代码复用核验 |
| Vietstock 结构化事件合并集 | 17,334 个唯一事件；本轮新增 54 个 ID | 上市、增发、退市及监管事件 | 17,334 条不全是监管状态 |
| 其中监管状态事件 | 2,969 条、769 个代码；按供应商 Note 识别进入 2,352、解除 617 | 可用状态变更重建部分历史区间 | 不能用“未出现事件”补成正常 |
| 监管事件的明确日期字段 | 579 条有 DateHCB；42 条有 DateGDTL | 直接取得部分解除、恢复交易日期 | 其余事件日期不能未经核对全部当成生效日 |
| 本轮官方当前监管名单 | 418 条、310 个唯一代码 | 当前警示、受控、限制及停牌等标签 | 名单外股票不自动判正常 |
| 本轮 HNX/UPCOM 行情状态标志 | 1,113 个代码，HNX 299、UPCOM 814 | 补充当前交易标志，支持定期留存 | 行情板缺失不能推断停牌；不是历史快照 |

本轮当前 HOSE 股票目录的常规分页抓取因响应超时未完成，未当成全量成功；HNX/UPCOM 目录完成。VNDIRECT 的上市分类是 HOSE 406、HNX 299、UPCOM 814，是独立来源的结果。

主要导出：

- `exports/stock_master.csv`：1,971 个股票代码及质量标记。
- `exports/regulatory_transitions.csv`：2,969 条状态进入/解除事件及原始类别、日期字段。
- `exports/structured_events.json`：合并后的完整原始事件字段和正文，未把正文加工结果冒充接口字段。
- `exports/hose_delistings_stock_matches.csv`：156 条与股票名录代码匹配的 HOSE 退市登记。
- `exports/direct_profile_examples.csv`：当前股票详情的直接监管状态和交易状态样例。
- `research-audit.json`：计数、质量检查和覆盖边界。

## 真实例子

### 不读公告也能取得的历史变更

警示、受控和限制交易也有直接的结构化记录，以下均来自已保存的接口响应：

| 代码 | 接口事件日期 | 直接类别 | 直接变更方向 |
| --- | --- | --- | --- |
| PGN | 2026-10-12 | Alert，警示 | Remove out of alert，解除；DateHCB 也是 2026-10-12 |
| AME | 2026-10-12 | Supervision，受控 | Has been put under supervision，进入 |
| PLP | 2026-10-23 | Under trading restriction，限制交易 | Đưa cổ phiếu vào diện hạn chế giao dịch，进入 |

表内日期是供应商事件日期；除明确的解除/恢复字段外，尚未把所有事件日期核验为法律生效日期。类别和方向直接来自接口，记录同时附带公告标题/正文。它是供应商结构化的历史变更库，并非交易所逐日状态快照。

Vietstock 的 MHC 记录直接提供：

| 日期 | 接口给出的信息 |
| --- | --- |
| 2011-04-08 | 进入临时停牌，EventID 8594 |
| 2011-04-27 | 解除临时停牌，EventID 8596，DateGDTL 也是这一天；标题说明转入受控 |

因此，已有能配对的“开始—结束”历史记录，不只是没有结构的公告标题。将这些区间展开成日表是可行的；全市场仍需要解决缺失变更、初始状态、转板和语义冲突。

### 已退市股票及转板历史

VNDIRECT 的 BTC 当前档案为 UPCOM、delisted，listedDate 为 2009-07-28，delistedDate 为 2020-03-17。

HOSE 的历史退市登记另外保留 BTC（securityId 2181）的 2009-07-01 退出记录；该 ID 的股票详情仍可匿名获取。这说明只使用当前档案的一对上市/退市日期，会丢失更早的市场经历。

ACM 的名录同时出现 listedDate=2022-07-19、delistedDate=2022-07-08、status=listed。这些字段不能简单解释成“上市日期比退市日期晚，所以错误/已退市”；需要分开不同市场阶段。全表有 351 条 listedDate 晚于 delistedDate，已标记。

### 直接当前状态也有明确的“正常”

HNX 的 SHS 详情明确给出监管状态 Bình thường（正常）、交易状态 Hoạt động（活动）。AMV 是 Kiểm soát（受控）＋Hoạt động；ACM、FTM 是 Hạn chế giao dịch（限制交易）＋Hoạt động。

这些字段来自官方详情页，不是因为“没查到公告”而推定正常。当前只逐一核验并导出了这些代表样例，未声称全市场所有详情均已核验。

## 为什么仍不能宣布历史全量已经拿到

1. **早期有确定缺口。** 旧官方资料已核实 BTC 在 2005-04-11 停牌、2005-04-13 复牌并警示，见旧 `ssc_verified_events.json`。现代结构化事件源中，警示最早为 2009-02-16，临时停牌最早为 2011-04-08；本轮跨 2000—2008 年查询只返回 352 条上市/增发事件，没有监管事件。这是具体的缺漏证据，不是宣称早期状态不存在。
2. **各类事件的时间覆盖不一致。** 限制交易最早 2016-05-26；独立的 đình chỉ 分类最早 2023-07-12；更早是否存在同义分类或漏记，不能从现代分类起点推断。
3. **有分类冲突。** 133 条监管记录有质量标记，包括供应商标成警示但标题写受控，以及早期事件的市场标签被标为后来才成立的 UPCOM。不能原样当成可靠的历史市场状态。
4. **正常状态需要起点依据。** 769 个代码出现监管事件，不意味着其余名录股票一直正常；这两个数也不能直接相除作为历史覆盖率。

## 对历史查询入口做了哪些验证

### HOSE：历史退市能查；当前警示入口不支持本次日期写法

读取公开前端代码，当前警示页面调用 `/securities/stock-status` 时只有 `pageIndex`、`pageSize`、`statusListId`。给相同请求额外加入 `fromDate=2000-01-01&toDate=2000-12-31` 后，返回 JSON 与无日期的当前名单完全相同。

这证明**这个入口和这种日期写法不能获得历史状态**，不证明网站所有其他入口都没有历史。相反，`/securities/cancel` 明确使用 `year`，已按全部年份实抓。

还成功查询了 MHC 2011 年 4 月的官方历史成交结果。返回的是日期、价格、成交量等字段，没有警示/停牌状态字段。历史行情存在，不等于历史监管状态存在。

### Vietstock：按月基线＋增量完成；大范围类别查询有失败

保留 10 月 11 日已校验的 17,280 个事件。本轮 10 月 12—23 日增量查询得到 54 条、54 个新 ID，分页总数与唯一 ID 数一致。另有 8 个监管类别完成全日期范围的重查，并保留了发生变化的旧记录。

全范围分类查询的 17（首次上市）、18（退市）、19（警示）在不同页大小重试后仍出现超时，不能把这三个查询报成成功。合并集采用原按月基线＋完整增量，并保留原先早期 80 个空响应/失败月份的未知覆盖，不把它们改成零事件。

## 商业来源：有针对性线索，但还没有实取历史状态样例

| 来源 | 本轮核实内容 | 实际接入结果 |
| --- | --- | --- |
| FiinGroup API Datafeed | HOSE 日表明确有 Suspension、HaltResumeFlag；HNX/UPCOM 日表有 SecurityTradingStatus、ListingStatus，均带 TradingDate | 已保存官方字段文档；未取得服务的接入地址、凭证和真实历史状态响应。不能把文档样例当下载成功 |
| FiinQuant | 检查可用数据和历史函数文档；列出 OHLCV、主动买卖、资金流等 | 文档未提供目标监管历史字段，不能因为支持历史行情就当成状态历史方案 |
| SSI FastConnect | 实时 F 消息支持证券交易状态；历史 DailyStockPrice 文档没有目标监管标签 | 匿名请求返回 HTTP 200，但正文是 status=401、Missing Authorization header；是鉴权失败，不是数据成功 |
| FireAnt | 阅读公开 Swagger；历史行情模型和事件查询不构成目标监管历史表 | 实测历史行情请求 HTTP 401，需要授权；没有证据表明授权后必定提供监管历史 |
| HNX 官方数据服务 | 下载并核查 2026 服务目录 | 日终市场汇总提到警示/受控/停牌**数量**，不能等同逐只股票历史状态；尚无购买和样例验证 |
| VietstockXLS | 有定制数据服务线索 | 未收到真实交付样例；通用“多年历史”宣传不能证明所有状态覆盖到 2000 年 |

FiinGroup 暂不能判为满足需求：HOSE 日表目前只明确验证了暂停/停牌字段，没有确认警示、受控、限制交易的历史字段。不能因为带有 TradingDate 和 Suspension 就优先选定它。现阶段已实抓到多类历史监管信息的直接接口是 Vietstock `/data/eventstypedata`；官方 HOSE/HNX 接口提供对应的当前状态。

进一步核对字段说明：HOSE 日表还定义了 `Delist`（退市），但 `Notice` 是盘中要求提供重要信息及其收悉标志，不能翻译成监管“警示”；`Status` 是数据记录的锁定、开放、删除状态，也不能当作股票监管状态。

### 已实抓的多类直接历史接口

`POST https://finance.vietstock.vn/data/eventstypedata`，`eventTypeID=2`；`channelID` 是状态类别，`catID=-1`，另有 `fDate`、`tDate`、`page`、`pageSize`。使用页面正常匿名会话及防伪令牌，不需要账号密码。

| 供应商类别 | channelID | 进入 | 解除 | 合计 |
| --- | --- | ---: | ---: | ---: |
| 警示 | 19 | 1,099 | 398 | 1,497 |
| 受控 | 22 | 470 | 124 | 594 |
| 限制交易 | 50 | 309 | 44 | 353 |
| 临时停牌 | 20 | 103 | 38 | 141 |
| đình chỉ giao dịch，独立停牌类别 | 56 | 92 | 4 | 96 |
| 警示、受控、限制的组合 | 51、52、53、54 | 279 | 9 | 288 |

这些是供应商结构化类别和 Note 的方向，不是本项目从公告标题推断的分类；分类矛盾仍保留质量标记。接口返回的是历史变更事件，不是已经展开成每日一行的成品表。

## 商业样例的验收清单

若有账号、学校权限或获准申请试用，先要求可下载样例再判断是否采购：

- 三个市场，包括已退市股票、转板和代码变更；历史起点分别说明，不能把 HNX/UPCOM 开市前日期填正常。
- 股票代码＋日期，或状态＋生效日＋解除日；警示、受控、限制交易、临时停牌/暂停、复牌分别给出定义。
- 核对 BTC 2005 年 4 月、MHC 2011 年 4 月、ACM 2022 年转板附近，以及最近 20 个交易日；检查是否实际还原当日状态，而非把当前标签重复到每个历史日期。
- 明确未知值、零值、无交易日、上市前/退市后的处理；停牌日必须有解释，不能因无成交就整行消失。
- 提供状态字典、按市场的起始日期、全股票清单、批量导出/API 示例、更新延迟及授权条件。

当前可继续用已落地的直接数据构建**有证据的区间与局部日表**。要把 2000 年以来全市场的未知状态补成可靠值，需要商业历史样例验证或补充档案；在获得证据前不生成虚假的完整日表。

## 原爬虫请求路径的实时边界复测

2026-10-23 按原代码的网址、网页 JavaScript 的请求参数和翻页方式向网站重新发起请求。此次是 HTTP 请求复现，没有声称把 Windows Edge 原脚本原样完整运行；原脚本未修改。证据目录为 `outputs/direct-status-research-20261023/legacy-*`。

| 原脚本 | 实测边界 | 说明 |
| --- | --- | --- |
| `legacy/HOSE_最终1.py` | 最早返回 2006-04-05 | 实际接口为 `https://api.hsx.vn/n/api/v1/1/news/securitiesType/1`。2000—2005 六个逐年查询均 HTTP 200、success=true、totalCount=0；2006 年 totalCount=2。另按原脚本的 2006-04-01 至 2006-05-02 月切片复核，返回相同最早公告 ID 896061。 |
| `legacy/HNX.py`，原样空日期 | 尾页最早 2017-01-17 | 网页日期输入框为空；SeachArticle 传递两个空日期。总数 4929，每页 10；第 493 页 9 条，第 494 页无记录。这个结果不能当作来源全部历史。 |
| 同一个 HNX 接口，补上明确日期 | 2005-12-27 | 2000—2005 查询返回一条；2000—2004 无记录。2000—2026 全范围明确日期查询总数 5748，比空日期多 819 条。需要修改原爬虫的日期筛选才会查到这些早期记录。 |
| `legacy/爬所有公告cafeF.py`，原每页 30 条路径 | SAM：2007-09-17；REE：2008-02-21；VNL：2009-07-11 | 分别验证第 35/50/15 页有数据、下一页为空。使用原网页 LoadNext 的 `Events_RelatedNews_New.aspx` 请求。三只股票均未达到原脚本 1000 页上限；这是逐股票边界，不是全站统一起点，也未下载所有中间页。 |
| `legacy/爬公告BCG.py`，原配置实际是 VNL | tab=2 上市/状态事件最早 2022-06-10 | 原网页的 code 参数会清空默认日期限制。按其每页 20 条、日期为空请求，tab=2 返回 8 条；tab=1 分红发行共 41 条、3 页，最早排序日期 DateOrder=2009-12-23（对应记录 Time=2010-01-08）。两类均未达到 30 页限制；不是全市场 Vietstock 的历史起点。 |

CafeF 和 Vietstock 复跑脚本：`python -m scripts.probe_legacy_crawler_boundaries`。HOSE 请求的 2000—2005 合并区间曾两次超时；结论采用随后成功的六个逐年查询，不把超时当无数据。原 HNX 无日期与明确日期的差异由实时响应证明，后端为什么默认省略早期记录尚未确定。

## 来源链接

- [VNDIRECT 股票名录接口](https://api-finfo.vndirect.com.vn/v4/stocks?q=type:STOCK~floor:HOSE,HNX,UPCOM&sort=code:asc&size=10000&page=1)
- [HOSE 当前警示名单](https://api.hsx.vn/l/api/v1/1/securities/stock-status?pageIndex=1&pageSize=100&statusListId=33)
- [HOSE 2009 年退市登记](https://api.hsx.vn/l/api/v1/1/securities/cancel?pageIndex=1&pageSize=100&year=2009)
- [HOSE BTC 详情](https://api.hsx.vn/l/api/v1/1/securities/2181)
- [HNX SHS 股票详情](https://www.hnx.vn/cophieu-etfs/chi-tiet-chung-khoan-ny-shs.html)
- [Vietstock 事件日历](https://finance.vietstock.vn/lich-su-kien.htm?tab=2&languageid=2)
- [FiinGroup HOSE 日数据字段](https://datafeed.fiingroup.vn/api-datafeed-en/api-trading/stock/stock/hose-stock-v2)
- [FiinGroup HNX 日数据字段](https://datafeed.fiingroup.vn/api-datafeed-en/api-trading/stock/stock/hnx-stock-v2)
- [FiinGroup UPCOM 日数据字段](https://datafeed.fiingroup.vn/api-datafeed-en/api-trading/stock/stock/upcom-stock-v2)
- [SSI REST 文档](https://guide.ssi.com.vn/ssi-products/fastconnect-data/api-specs)
- [FireAnt Swagger](https://api.fireant.vn/swagger/docs/v1)
- [HNX 2026 信息服务目录](https://owa.hnx.vn/ftp/PORTALNEW/FileContent/HNX_Danh%20muc%20goi%20tin%20va%20bang%20gia%20dich%20vu%20CCTT%2820260105_145538_848%29.pdf)

复跑入口：`python -m scripts.collect_hose_delisting_probe`、`python -m scripts.collect_status_history_probe`、`python -m scripts.audit_status_research`。研究脚本当前查询截止日固定为 2026-10-23，不是已部署的后台更新服务。
