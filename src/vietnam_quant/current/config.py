"""Validated settings shared by the CLI and desktop launchers."""

import json
import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    output_dir: str = "outputs/current-status"
    request_interval_seconds: float = 1.5
    timeout_seconds: float = 30
    max_attempts: int = 3
    backoff_seconds: float = 2
    max_retry_wait_seconds: float = 60
    dnse_batch_size: int = 100
    max_data_age_days: int = 7
    verify_exchange_directory: bool = True

    def __post_init__(self):
        if not isinstance(self.output_dir, str) or not self.output_dir.strip():
            raise ValueError("output_dir must be a nonempty path")
        for name, low, high in (
            ("request_interval_seconds", 1, 60),
            ("timeout_seconds", 1, 120),
            ("backoff_seconds", 1, 60),
            ("max_retry_wait_seconds", 1, 300),
        ):
            value = getattr(self, name)
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ValueError(f"{name} must be between {low} and {high}")
        for name, low, high in (
            ("max_attempts", 1, 5),
            ("dnse_batch_size", 1, 100),
            ("max_data_age_days", 0, 14),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer between {low} and {high}")
        if type(self.verify_exchange_directory) is not bool:
            raise ValueError("verify_exchange_directory must be a boolean")

    def as_dict(self):
        return asdict(self)


def load_settings(path=None):
    if path is None:
        return Settings()
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Settings must be a JSON object")
    extra = data.keys() - {field.name for field in fields(Settings)}
    if extra:
        raise ValueError(f"Unknown settings: {', '.join(sorted(extra))}")
    return Settings(**data)
