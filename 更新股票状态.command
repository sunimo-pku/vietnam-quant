#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
export PYTHONUTF8=1
code=1
runner=""
for candidate in "$PWD/.venv/bin/python" python3 python3.13 python3.12 python3.11 python3.10; do
    if "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        runner="$candidate"
        break
    fi
done
if [ -n "$runner" ]; then
    "$runner" -X utf8 scripts/bootstrap.py "$@"
    code=$?
else
    echo "请先安装 Python 3.10 或更高版本：https://www.python.org/downloads/"
fi
if [ "${VN_STATUS_NO_PAUSE:-}" != "1" ] && [ -t 0 ]; then
    read -r -p "按 Enter 关闭窗口…"
fi
exit "$code"
