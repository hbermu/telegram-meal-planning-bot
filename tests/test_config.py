import pytest

from meal_planning_bot.config import ConfigError, load_config

BASE = {
    "TELEGRAM_BOT_TOKEN": "123:abc",
    "MEALBOT_ALLOWED_USER_IDS": "1, 2,3",
    "MEALBOT_GROUP_CHAT_ID": "-1001",
}


def test_parses_defaults() -> None:
    cfg = load_config(BASE)
    assert cfg.allowed_user_ids == frozenset({1, 2, 3})
    assert cfg.group_chat_id == -1001
    assert cfg.db_path.as_posix() == "/data/mealbot.db"
    assert cfg.timezone == "UTC"
    assert cfg.allow_partial_plan is False


@pytest.mark.parametrize("missing", list(BASE))
def test_missing_required_names_the_variable(missing: str) -> None:
    env = {k: v for k, v in BASE.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        load_config(env)


@pytest.mark.parametrize("bad", ["", " ", "1,x", "1,,2"])
def test_bad_allow_list_rejected(bad: str) -> None:
    with pytest.raises(ConfigError, match="MEALBOT_ALLOWED_USER_IDS"):
        load_config(BASE | {"MEALBOT_ALLOWED_USER_IDS": bad})


def test_unknown_timezone_rejected() -> None:
    with pytest.raises(ConfigError, match="MEALBOT_TIMEZONE"):
        load_config(BASE | {"MEALBOT_TIMEZONE": "Mars/Olympus"})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("TRUE", True), ("1", True), ("yes", True), ("false", False), ("0", False)],
)
def test_partial_plan_flag_parses(raw: str, expected: bool) -> None:
    cfg = load_config(BASE | {"MEALBOT_ALLOW_PARTIAL_PLAN": raw})
    assert cfg.allow_partial_plan is expected


@pytest.mark.parametrize("bad", ["maybe", "2", "si"])
def test_bad_partial_plan_flag_rejected(bad: str) -> None:
    with pytest.raises(ConfigError, match="MEALBOT_ALLOW_PARTIAL_PLAN"):
        load_config(BASE | {"MEALBOT_ALLOW_PARTIAL_PLAN": bad})


def test_token_not_in_repr() -> None:
    assert "123:abc" not in repr(load_config(BASE))
