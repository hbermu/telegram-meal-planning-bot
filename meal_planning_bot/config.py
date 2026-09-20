from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    token: str = field(repr=False)
    allowed_user_ids: frozenset[int]
    group_chat_id: int
    db_path: Path
    timezone: str
    log_level: str


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"{key} is required")
    return value


def _parse_allow_list(raw: str) -> frozenset[int]:
    parts = [p.strip() for p in raw.split(",")]
    if any(not p for p in parts):
        raise ConfigError("MEALBOT_ALLOWED_USER_IDS must be a comma-separated list of user IDs")
    try:
        return frozenset(int(p) for p in parts)
    except ValueError as exc:
        raise ConfigError("MEALBOT_ALLOWED_USER_IDS must contain integers only") from exc


def load_config(env: Mapping[str, str]) -> Config:
    token = _required(env, "TELEGRAM_BOT_TOKEN")
    allowed = _parse_allow_list(_required(env, "MEALBOT_ALLOWED_USER_IDS"))
    try:
        group_chat_id = int(_required(env, "MEALBOT_GROUP_CHAT_ID"))
    except ValueError as exc:
        raise ConfigError("MEALBOT_GROUP_CHAT_ID must be an integer") from exc

    timezone = env.get("MEALBOT_TIMEZONE", "UTC").strip() or "UTC"
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"MEALBOT_TIMEZONE is not a known zone: {timezone}") from exc

    return Config(
        token=token,
        allowed_user_ids=allowed,
        group_chat_id=group_chat_id,
        db_path=Path(env.get("MEALBOT_DB_PATH", "/data/mealbot.db")),
        timezone=timezone,
        log_level=env.get("MEALBOT_LOG_LEVEL", "INFO").upper(),
    )
