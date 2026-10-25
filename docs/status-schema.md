# 当前状态主表 v1.0

主表固定八列，不增加派生状态、来源比较或质量列。不将多个状态合并为单一等级。
每个运行内 `(trade_date, market, symbol)` 唯一；同日不同运行保留各自快照。
尚未定义跨运行历史库的覆盖策略。

| 字段 | 来源原字段 | 类型 | 含义 |
| --- | --- | --- | --- |
| trade_date | SSI tradingDate | ISO 日期 | 来源交易日，不是抓取日或生效日 |
| market | SSI exchange | 字符串 | HOSE / HNX / UPCOM，格式转换为大写 |
| symbol | SSI stockSymbol | 字符串 | 股票代码 |
| ssi_admin_status | SSI adminStatus | 字符串/null | 监管状态 |
| ssi_trading_status | SSI tradingStatus | 字符串/null | SSI 综合交易状态 |
| dnse_trading_method_status | DNSE symbolTradingMethodStatusCode | 整数/null | 交易方式分类 |
| dnse_trading_sanction_status | DNSE symbolTradingSanctionStatusCode | 整数/null | DNSE 证券交易状态，不能简单等同 SSI 综合交易状态 |
| dnse_security_status | DNSE securityStatus | 整数/null | 停牌标志，原始数值 |

SSI 的监管字段是主表唯一监管列。DNSE `symbolAdminStatusCode`、`tradingTime`、
SSI `permaHalt` 及其他返回值保存在 raw 中。采集收据和校验信息另存；没有新增状态列。
CSV 空白无法区分缺字段、null 和空字符串；JSON 与 raw 保留相应信息。

## 代码字典与证据

本节是说明，不转换或增添主表字段。完整性以各来源、产品和版本为边界。
`contract.py` 中已知值用于发现接口变化，未知值仍原样保存并报告，不替换成正常。

### SSI 监管状态

| 原值 | 中文说明 |
| --- | --- |
| NRM | 正常 |
| WFR | 财务报告相关警告 |
| WID | 信息披露相关警告 |
| WOV | 其他违规警告 |
| CTR | 受控 |
| RES | 限制交易 |
| C&R | 受控且限制交易 |

异常代码见 [HOSE 官方说明](https://staticfile.hsx.vn/Uploads/UploadDocuments/2372216/9.Trading%20symbols.pdf)。
NRM 含义见 DNSE 官方枚举及实测对应。尚未发现 SSI 公开 `adminStatus` 接口的完整正式字典，
不据此推断不存在其他值，也不声称一个类别包含全部并存监管措施。

### SSI 综合交易状态

| 原值 | 当前官方网页标签含义 |
| --- | --- |
| N | 正常交易 |
| RT / TFR | 限制交易 |
| S | 暂停交易 |
| D | 退市 |
| NL | 新上市 |
| ST | 特殊交易 |

依据 2026-10-26 重新获取的 [SSI 官网程序](https://iboard.ssi.com.vn/build/static/js/DTteOVY6.js)
中的 `showTradingStatus_*` 和 `TRADING_STATUS`，属于官方程序证据，非稳定 API 承诺。
[FastConnect 正式文档](https://guide.ssi.com.vn/ssi-products/fastconnect-data/data-mapping/securities-trading-status)
是另一个产品，其 H、ND、SA、SP 等枚举不能直接套用到匿名接口。

### DNSE 数字状态

| 字段 | 数字 → 枚举与含义 |
| --- | --- |
| 交易方式 | 0 未指定；1 NRM 常规；2 NWE 新上市特殊涨跌幅；3 NWN 新上市常规涨跌幅；4 SLS 暂停后的特殊交易方式；5 SNE 特殊交易 |
| 证券交易状态 | 0 未指定；1 NRM 正常；2 SUS 暂停；3 DTL 因转板退市；4 TFR 因限制停止交易 |
| 停牌标志 | 实测出现 1 和 2；先保留数字，不在导出中转换成布尔值或中文。字符串 HALT/NO_HALT 有正式定义，数字映射的正式接口文档仍待补齐；0 按未明确状态处理 |

字符串枚举定义见 [DNSE 官方枚举表](https://developers.dnse.com.vn/docs/guide/enum/market_data/)
与 [官方 OpenAPI schema](https://github.com/dnse-tech/openapi-sdk/blob/main/spec/dnse-openapi-2026-09-15.yaml)。
交易方式和证券交易状态的数字枚举另有
[DNSE 官方网页程序](https://banggia.dnse.com.vn/_app/immutable/chunks/BLLjB5s6.js)依据。
文档中的字符串接口与匿名接口中的数字接口不是同一接口；不把文字说明当作数字映射证明。

HOSE 对 SLS/NWE/NWN 的说明与 DNSE 文档措辞不同；不能抹平差异，也不能由 SLS 推断已复牌。
ACM 的 SSI 限制交易与 DNSE 证券交易状态正常是可同时出现的原始值，不合成为“完全正常”。

## 主表之外

- `raw/`：各来源原始响应和已有请求收据，保留追溯依据。
- `quality.json`：缺失、未指定、未知编码、DNSE 目录外代码等。
- `manifest.json`：表版本、回放模式、来源日期、生成时间、输入哈希、行数。

缺少整市场 SSI 响应、重复代码、市场错配、混合来源交易日、无效结构或收据哈希不符会失败。
缺少个别 DNSE 股票或状态字段时保留 SSI 股票行，相应值为 null 并报告；不默认正常。
结构检查成功不是状态全面性、有效时间或全市场股票池的独立认证。
