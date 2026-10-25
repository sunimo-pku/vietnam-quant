# 使用与配置

## 双击与终端

双击根目录 Windows `.bat` 或 macOS `.command`。两个入口共用 Python 程序。
macOS 若提示无执行权限，在项目目录终端执行一次：

```sh
chmod +x 更新股票状态.command
```

也可以在项目目录运行 `bash 更新股票状态.command`。
程序使用系统可信证书。若仍有证书错误，请检查系统日期、证书或代理配置；不关闭 TLS 验证。
Windows 下载后须先解压，确保整个项目在同一目录，安装 Python 时选择加入 PATH。

终端统一入口（虚拟环境已安装项目后）：

```sh
vn-status update
vn-status --output outputs/another-run update --config config/settings.json
```

退出码 0 表示检查通过，1 表示失败或需要检查。一次运行只更新一次，不后台循环。
输出文件使用 UTF-8；CSV 带 BOM，适合 Excel/WPS。
运行窗口包含数据日期、结果路径、错误和提示数量。

## 自定义配置

将 `config/settings.example.json` 复制为 `config/settings.json` 后修改。
不复制时使用同样的默认配置。本地 settings.json 不提交 Git。
双击入口中，相对路径基于项目根目录；直接调用 CLI 时基于当前工作目录。

| 配置 | 默认值 | 含义 |
| --- | --- | --- |
| output_dir | outputs/current-status | 结果根目录 |
| request_interval_seconds | 1.5 | 请求开始时间最小间隔，至少 1 秒 |
| timeout_seconds | 30 | 网络超时秒数 |
| max_attempts | 3 | 每个请求最多尝试次数 |
| backoff_seconds | 2 | 重试退避基数 |
| max_retry_wait_seconds | 60 | 允许本轮等待的最大秒数；服务端要求更久则结束，不提前重试 |
| dnse_batch_size | 100 | 每批股票数，1–100；不是官方上限声明 |
| max_data_age_days | 7 | 可接受的来源日期最大日历天龄；不是最新交易日保证 |
| verify_exchange_directory | true | 是否逐只核对官方目录；关闭会在结果中明确提示 |

SSI/DNSE 匿名网页接口没有已确认的每小时配额。基础两来源采集通常需要 3＋ceil(N/100)
次请求，默认官方目录核对会额外请求分页；失败重试也计请求。不要把基本 19 次说成
开启目录核对后的总请求量。

## 离线检查与回放

```sh
python scripts/bootstrap.py --check
python scripts/bootstrap.py --from-run tests/fixtures/current --output outputs/demo
vn-status --output outputs/replay current-report --from-run 某轮结果/raw
```

`--check` 只准备并检查环境。离线回放不联网采集、不更新 latest；表内仍使用原交易日。
七只股票的测试样本仅用于验证，不能当成真实全量更新。
自动执行启动文件时可设置环境变量 `VN_STATUS_NO_PAUSE=1`，避免 Windows 窗口等待按键。

## 历史与失败

- `runs/`：每轮结果和失败记录，不覆盖，不自动删除。
- `latest/`：最近通过检查的结果副本，并不一定是今天的数据。
- `last_attempt.json`：最近尝试是否失败或需要检查。
- 本轮 `quality.json`：逐项问题；缺失/未知代码不能自动当正常。

如果 Windows 的 Excel/WPS 正占用结果文件，关闭后重试。上轮成功表保留。
在极少数目录切换时崩溃的情况，旧表暂存在 `.latest-backup`；下次运行自动恢复。
当前实现尚未切换既有桌面自动任务，也不会创建重复的系统定时任务。
