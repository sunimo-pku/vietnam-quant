# 2000—2009 年警示与受控记录补源实测

核查日期：2026-10-23。目标是查到实际可获取的历史警示（cảnh báo）、受控（kiểm soát）证据，不以停牌记录代替这些状态。

## 结论与证据层次

已证明可以从越南证监会旧资料、HNX 历史监管公告、券商保留的交易所通知与日报补充早期记录。本次保存并核对 16 条逐股票警示/受控事件证据，涉及 15 个代码；15 条来自官方站点，1 条 BBT 来自报纸与券商日报。这是定向核验样本，不是全量事件，也不是相对于 Vietstock 已去重的净新增数量。尚未找到覆盖 2000—2009 全市场、逐股票逐日的直接状态接口。

### 已下载并核对的来源

| 来源 | 实际记录 | 日期的含义 | 仍缺什么 |
| --- | --- | --- | --- |
| 越南证监会 SSC，2005-04-18《Thông tin thị trường》 | BTC 被标记 cảnh báo | 正文明确生效 2005-04-13 | 解除日期与期间完整性 |
| 富雄证券 PHS 保存的交易中心通知 | BTC 同一警示事件，全文有代码、复牌日、警示起点 | 同样明确 2005-04-13；网站展示刊发日 2005-04-16 | 与 SSC 为同一事件，不能重复计数 |
| Nhân Dân 2008-07-10 报道；EuroCapital 2008-06-17 日报第 7 页 | BBT 被列为 kiểm soát，理由是逾期提交财报 | 报道给决定日 2008-06-16；日报确认已受控 | 原始决定的生效日、解除记录；日报注明转载 DTCK-online，不是独立官方决定 |
| HNX 官方正文，ID 132337 | VE1 被列为 kiểm soát | 官方索引发布日期 2009-03-27 | 正文未另列生效日 |
| HNX 官方正文，ID 136248 | TLT、SRA、NVC、CMC、HNM、KLS、BVS、VE1、HPC 被列为 cảnh báo | 官方索引发布日期 2009-04-17 | 正文未另列生效日，也未给解除日 |
| HNX 官方正文，ID 131979 / 137916 / 139873 / 136776 | BLF、AGC、TKU、TLC 被列为 cảnh báo | 发布日期依次 2009-04-25、04-27、05-06、05-29 | 同上 |

HNX 真实请求：

```text
POST https://www.hnx.vn/ModuleArticles/ArticlesCPEtfs/PopupTinCongBoDetail
Content-Type: application/x-www-form-urlencoded
pArticlesID=136248&pFileAttach=0
```

返回公告 HTML 正文，包含股票列表与监管措施，并不是现成的逐日 status 表。该公告没有正文中单独说明的生效日，因此导出将 effective_date 留空，没有直接拿发布日期顶替。

证据目录：`outputs/direct-status-research-20261023/`。`early-regulatory/verified-warning-control-cases.json` 保留请求参数、证据路径和日期限制；同名 CSV 便于查看。原始 HTML/PDF 与 HTTP 状态、TLS 校验结果、时间戳、SHA-256 另存于各 `early-*` 目录。BTC 官方 HTML 在 `early-regulatory/raw-ssc/`，其解析结果和回执在 `early-regulatory/btc-2005-warning.json`。

### 2001 年线索，尚未达到同等验证标准

VnExpress《10 sự kiện nổi bật trên TTCK Việt Nam năm 2001》被搜索引擎收录的正文明确提及：HAP 在 2001-05-21 被列入 cảnh báo，持续三个交易日，2001-05-28 恢复交易。本轮直接下载普通页面和两个变体分别失败（404/504），也尚未取得交易中心原始决定。

因此只列入 `early-regulatory/unverified-leads.json`，不混入上述 16 条已保存正文的事件。还需核对当年的 cảnh báo 定义；“恢复交易”不能自动当作“解除警示”。这是值得继续追查的具体早期线索，不是 2001 年完整覆盖的证明。

## 重要发现：2009 年制度变化与媒体标签错误

实际下载了 PHS 保留的 HOSE 第 269/SGDHCM-NY 号纠错函，页面日期 2009-02-11。交易所指出报纸把“受控”写成“特别受控”；当时适用的上市规则并没有文中所谓“特别受控”这一类别。该函明确要求以交易所网站和交易所市场日报为准。

另下载《Tuổi Trẻ》2009-04-21 报道，记载 4 月 20 日 HOSE 将 15 只受控股票（不含 BBT）改列为警示，与修订规则有关。HNX 4 月的官方警示正文亦引用 2009-04-14 第 137/QĐ-TTGDCKHN 号修订决定；VE1 在 3 月官方原文是受控，4 月官方原文是警示。HOSE 的具体逐股票转换清单和生效日尚需原始决定，未把报纸这句话批量转成已确认事件。

所以历史处理必须保存原始越南语类别、适用规则版本和证据来源。不能仅用“cảnh báo”关键词判断是否正式警示，也不能把 2009 年前后的标签直接按现代严重程度解释。以前识别出的结构化分类/标题冲突仍需逐项核对，不能因此整批判错或整批消除质量标记。

## 覆盖缺口

本次完整翻查 HNX 该监管栏目逐年查询结果：2005 / 2006 / 2007 / 2008 / 2009 年分别返回 1 / 3 / 10 / 33 / 32 条索引记录，2009 年有 6 条警示/受控候选，现均下载正文。其中一条聚合公告可拆为 9 个代码。早年索引稀疏，不能声称栏目完整，更不能把零匹配解释为全市场正常。

SSC 的 cảnh báo、kiểm soát、HAP 搜索各保存第一页 20 条，返回总数分别 205、829、53；尚未完整翻页，不能以此作完整档案检索。搜索既有正式监管记录，也有泛指风险警告、公司监事会等误匹配。

| 时段 | 目前能说什么 |
| --- | --- |
| 2000、2002—2004 | 本轮未确认可用于入库的具体警示/受控原文；未知，不等于无事件 |
| 2001 | HAP 的具体媒体线索；原始决定和类别定义待核实 |
| 2005 | BTC 官方警示起点可确认，已有独立站点保存同一通知 |
| 2006—2007 | 本轮未补齐年度状态清单。2009 年新闻回溯 BTC 警示延续，可作线索，尚未逐年取得官方核验 |
| 2008 | BBT 受控证据已经下载；不是当年全部股票清单 |
| 2009 | HNX 官方批量警示与受控事件可抓；HOSE 有规则变更与通知转载可补 |

## 后续全量补齐工作的具体入口

1. 按当年上市股票名录（包含后来退市、改名、转板的股票）而非今天仍在交易的股票建检索范围。
2. SSC 历史市场报告、HNX 监管栏目按日期与代码抓取；HNX 一条公告可能列多只股票，不能只保留索引的一格股票代码。
3. 对 HOSE 旧接口缺失部分，查 PHS 等券商保存的交易所通知，及 EuroCapital 等券商日报 PDF 中的通知副本；目前这些路径已有成功下载样例，但其完整性尚未验证。
4. 新闻用于定位决定编号、时间与补充交叉核对。进入、继续维持、退出、转类需要分别收集；只有起点不能无限向后填充为同一状态。
5. 若这些公开档案仍不能覆盖早期区间，进一步需要交易所历史日报/监管清单或商业库的实际样本验证。目前未取得这类完整档案，未联系或购买任何数据。

## 来源链接

- [SSC：BTC 2005 年警示记录](https://ssc.gov.vn/webcenter/portal/ubck/pages_r/l/chitit?dDocName=APPSSCGOVVN162065431)
- [PHS：转载 BTC 复牌及警示通知](https://www.phs.vn/tin-tuc/canh-bao-doi-voi-co-phieu-btc-khi-giao-dich-tro-lai/272484)
- [Nhân Dân：BBT 2008 年受控决定背景](https://nhandan.vn/hose-ngung-giao-dich-co-phieu-bbt-post508534.html)
- [EuroCapital：2008-06-17 日报，第 7 页](https://www.ecsc.vn/Modules/BusinessInformation/Uploads/115/Nam_2008/ECC%20DAILY%20REPORT%20%2817.06.2008%29.pdf)
- [VnExpress：HAP 2001 年警示线索](https://vnexpress.net/10-su-kien-noi-bat-tren-ttck-viet-nam-nam-2001-2667155.html)
- [PHS：HOSE 对“特别受控”错误报道的纠正函](https://www.phs.vn/tin-tuc/hose-de-nghi-bao-tuoi-tre-dinh-chinh-thong-tin/96756)
- [Tuổi Trẻ：2009 年受控改列警示](https://tuoitre.vn/chung-khoan-giam-gia-san-312163.htm)
- [VnExpress：2009 年回溯 BTC 警示延续](https://vnexpress.net/co-phieu-dau-tien-bi-huy-niem-yet-2699130.html)
