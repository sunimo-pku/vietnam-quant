# 架构与开发

## 模块

| 模块 | 职责 |
| --- | --- |
| 根目录 `.bat` / `.command` | 寻找 Python、传递参数、保留结果窗口 |
| `scripts/bootstrap.py` | 共用安装准备、环境检查、调用正式 CLI；配置变化才重新安装 |
| `current/config.py` | JSON 配置校验 |
| `current/transport.py` | HTTPS、统一请求间隔、有限重试、Retry-After、逐次收据 |
| `current/providers/` | 两来源纯解析，不修改原始状态值 |
| `current/contract.py` | 八列主表版本与已知代码 |
| `current/pipeline.py` | 主表连接、独立质量报告、离线回放 |
| `current/live.py` | 在线采集、交易所目录和日期核对、运行记录 |
| `current/storage.py` | 跨平台进程锁、latest 暂存发布、回滚与恢复 |

四个旧爬虫集中保存在 `legacy/`，文件内容与换行格式保持原样；原有三个数据快照仍在根目录。
快照与研究命令保留；新的 `update` 不调用旧的派生状态表。
现有桌面自动任务尚未切换，本次不额外创建系统调度器。

## 数据流程

SSI 三市场批量快照 → DNSE 每批最多 100 只 → 校验三市场来源日期与标识 →
核对官方目录 → 导出八列主表与独立报告 → 通过后更新 latest。
股票池不写死为 1519；按本轮来源确定，再与官方目录逐只对照。
缺失、未知值、市场错配、混合日期、DNSE 时间错配、监管分类冲突或目录差异不能发布。
DNSE 监管分类未指定属于提示，不覆盖 SSI 监管字段；原始值保留。

日期有效性：允许最新数据早于运行日，用可配置的日历天上限检测明显陈旧的数据。
这不是交易所节假日日历，不保证最新交易日已经发布。DNSE tradingTime 与 SSI 交易日
的匹配仅是新鲜度检查，不把该时间当作状态生效时间。

## 运行与存储

每轮在 `runs/<UTC时间>-<随机编号>/` 保存 raw、表、质量报告和 manifest。
`last_attempt.json` 记录最近运行状态；进程异常终止可能保留 running，下次可重新运行。
操作系统进程锁在进程退出时自动释放，锁文件无需删除。

仅 successful live run 可发布 latest；离线回放不能发布。
发布先准备完整临时副本，再将旧 latest 移到备份并替换新目录。替换失败则恢复旧目录；
若在切换间隙崩溃，下次运行先恢复备份。目录替换有短暂空窗，不声称多文件原子读取；
需要并发读取的程序应读取不可变的 runs 目录。成功运行目录的 manifest 记录具体路径。
latest 不复制全量 raw，原始响应在对应 runs 中，避免重复存储。

同一输出位置禁止同时更新；启动环境准备也单独加锁。失败不删除历史目录。
不清理历史，不上传结果，不保存账户或密钥。
Windows 安装会额外带上 IANA 时区数据，使既有研究模块的越南时区处理保持一致。
HTTPS 使用 [truststore 的系统证书接口](https://truststore.readthedocs.io/en/latest/)，
不全局替换 ssl，也不关闭证书或主机名校验。HOSE 目录默认每页 10 条、顺序读取，
避免实测的大响应截断；逐页检查总数与去重。

## 开发验证

```sh
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
python -m ruff check src/vietnam_quant/current tests/test_current.py tests/test_current_update.py tests/test_bootstrap.py scripts/bootstrap.py
python -m ruff format --check src/vietnam_quant/current tests/test_current.py tests/test_current_update.py tests/test_bootstrap.py scripts/bootstrap.py
```

CI 配置在 Ubuntu / macOS / Windows、Python 3.10 / 3.13 下运行，使用包含中文及空格的
工作目录，验证真实启动文件的首次环境准备与离线导出。CI 不请求真实证券接口。
配置存在不等于远端检查已执行；实际测试结果单独记录。
