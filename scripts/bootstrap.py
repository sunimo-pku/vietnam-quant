"""Shared macOS/Windows launcher: setup once, then call the normal CLI."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def environment_python(root):
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def prepare(root):
    executable = environment_python(root)
    if not executable.is_file():
        print("首次运行：正在准备 Python 环境…", flush=True)
        venv.EnvBuilder(with_pip=True).create(root / ".venv")
    version = subprocess.run(
        [str(executable), "-c", "import sys; sys.exit(sys.version_info < (3, 10))"], check=False
    )
    if version.returncode:
        raise RuntimeError("项目的 .venv 需要 Python 3.10 或更高版本，请重建该环境。")
    digest = hashlib.sha256((root / "pyproject.toml").read_bytes()).hexdigest()
    stamp = root / ".venv" / ".vn-status-ready.json"
    try:
        ready = json.loads(stamp.read_text(encoding="utf-8")) == {
            "project": str(root),
            "pyproject_sha256": digest,
        }
    except (OSError, ValueError):
        ready = False
    check = subprocess.run(
        [str(executable), "-c", "import bs4; import vietnam_quant.current.live"],
        capture_output=True,
        check=False,
    )
    if not ready or check.returncode:
        print("正在安装或更新所需组件（首次运行需要联网）…", flush=True)
        subprocess.run(
            [
                str(executable),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-e",
                str(root),
            ],
            check=True,
        )
        stamp.write_text(
            json.dumps({"project": str(root), "pyproject_sha256": digest}), encoding="utf-8"
        )
    return executable


def main():
    if sys.version_info < (3, 10):
        print("请安装 Python 3.10 或更高版本：https://www.python.org/downloads/")
        return 1
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="越南股票状态一键更新")
    parser.add_argument("--check", action="store_true", help="只检查运行环境，不抓取数据")
    parser.add_argument("--from-run", type=Path, help="离线回放目录，不更新 latest")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        # The setup lock uses only the standard library, before dependencies exist.
        sys.path.insert(0, str(ROOT / "src"))
        from vietnam_quant.current.storage import output_lock

        with output_lock(ROOT / ".launcher"):
            executable = prepare(ROOT)
        if args.check:
            print("运行环境已就绪。", flush=True)
            return 0
        command = [str(executable), "-X", "utf8", "-m", "vietnam_quant.cli"]
        if args.output:
            command.extend(["--output", str(args.output)])
        if args.from_run:
            command.extend(["current-report", "--from-run", str(args.from_run)])
        else:
            command.append("update")
            if args.config:
                command.extend(["--config", str(args.config)])
        return subprocess.run(command, cwd=ROOT, check=False).returncode
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(
            f"未能完成更新：{exc}\n请检查 Python 安装、网络连接及文件夹写入权限。", file=sys.stderr
        )
        return 1
    except KeyboardInterrupt:
        print("已停止。已有结果仍然保留。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
