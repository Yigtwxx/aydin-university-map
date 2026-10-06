"""Secrets from the environment, with the repo-root ``.env`` as a fallback.

Values are never printed or logged; errors name the variable only.
"""

import os
from pathlib import Path

from dotenv import dotenv_values

ENV_FILE = Path(".env")


def get_env(name: str, env_file: Path = ENV_FILE) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    if env_file.is_file():
        file_value = dotenv_values(env_file).get(name)
        return file_value or None
    return None


def require_env(name: str, env_file: Path = ENV_FILE) -> str:
    value = get_env(name, env_file)
    if not value:
        raise RuntimeError(f"{name} is not set (environment or {env_file})")
    return value


def set_env_value(name: str, value: str, env_file: Path = ENV_FILE) -> None:
    """Add or replace ``NAME=value`` in the env file (kept at mode 600)."""
    lines = env_file.read_text("utf-8").splitlines() if env_file.is_file() else []
    prefix = f"{name}="
    kept = [line for line in lines if not line.startswith(prefix)]
    kept.append(f"{prefix}{value}")
    env_file.write_text("\n".join(kept) + "\n", encoding="utf-8")
    env_file.chmod(0o600)
