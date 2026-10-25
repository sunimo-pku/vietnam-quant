"""Cross-platform single-writer locking and recoverable latest publication."""

import json
import os
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path


class AlreadyRunning(RuntimeError):
    pass


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def output_lock(output):
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".update.lock").open("a+b") as handle:
        if handle.seek(0, 2) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise AlreadyRunning("已有更新正在运行，请等待它结束后再试。") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_UN)


def recover_latest(output):
    latest, backup = output / "latest", output / ".latest-backup"
    if backup.exists():
        if latest.exists():
            shutil.rmtree(backup)
        else:
            backup.rename(latest)


def publish_latest(run, output):
    """Caller holds output_lock. Keep old results if a Windows file is open."""
    recover_latest(output)
    latest, backup = output / "latest", output / ".latest-backup"
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("mode") != "live" or manifest.get("status") != "success":
        raise ValueError("Only a successful live run may update latest")
    if latest.exists():
        previous = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
        if previous["trade_date"] > manifest["trade_date"]:
            raise ValueError("Refusing to replace latest with an older trading date")
    stage = output / f".latest-stage-{uuid.uuid4().hex}"
    stage.mkdir()
    try:
        for name in ("status.csv", "status.json", "quality.json", "manifest.json", "result.txt"):
            shutil.copy2(run / name, stage / name)
        if latest.exists():
            latest.rename(backup)
        try:
            stage.rename(latest)
        except BaseException:
            if backup.exists():
                backup.rename(latest)
            raise
        # A crash here is recovered next run; the published files are complete.
        if backup.exists():
            try:
                shutil.rmtree(backup)
            except OSError:
                pass  # Published successfully; recovery can retry backup cleanup.
    finally:
        if stage.exists():
            shutil.rmtree(stage)
