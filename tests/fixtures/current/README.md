# 离线样本

取自 2026-10-25 匿名采集的 SSI / DNSE 响应，来源交易日为 2026-10-23。
选取 AAA、HVN、VPH、AME、ECI、ACM、XMC 七只股票；不是全市场快照。
SSI 仅保留解析所需原字段，DNSE 保留选中股票的全部查询字段。
没有凭据、个人账户或交易数据。

- SSI：`GET https://iboard-query.ssi.com.vn/stock/exchange/{hose,hnx,upcom}`
- DNSE：`POST https://api.dnse.com.vn/price-api/query`，`GetKrxStockInfoBySymbols`，`board: 2`
- 本地完整来源：`outputs/anonymous-status-research-20261025/full/20261025T152057275791Z/`

所有值保持实际响应。尤其 ECI 的 SSI `adminStatus=C&R`，DNSE
`symbolAdminStatusCode=0`，不能用后者覆盖前者。测试使用副本注入缺失、未知
代码、重复股票、市场错配和混合交易日期，不改动这些固定样本。
