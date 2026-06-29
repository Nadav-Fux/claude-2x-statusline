import json
from pathlib import Path

from lib import usage_providers as providers


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_codex_fixture_maps_rate_limits():
    line = (FIXTURES / "codex_rollout_token_count.jsonl").read_text(encoding="utf-8").strip()

    record = providers.parse_codex_token_count_line(line)

    assert record["available"] is True
    assert record["five_hour"]["used_pct"] == 47
    assert record["five_hour"]["resets_at"] == 1782536836
    assert record["weekly"]["used_pct"] == 10
    assert record["weekly"]["resets_at"] == 1783029435
    assert record["plan"] == "team"


def test_glm_fixture_maps_quota_limits():
    data = json.loads((FIXTURES / "glm_quota_response.json").read_text(encoding="utf-8"))

    record = providers.parse_glm_quota_response(data)

    assert record["available"] is True
    assert record["five_hour"]["used_pct"] == 0
    assert abs(record["five_hour"]["resets_at"] - 1783532012) <= 1
    assert record["weekly"]["used_pct"] == 99
    assert abs(record["weekly"]["resets_at"] - 1782782126) <= 1
    assert record["plan"] == "lite"


def test_providers_gracefully_unavailable_without_home_data(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)

    for name in ("codex", "glm", "droid", "antigravity"):
        record = providers.get_provider_usage(name, {})
        assert record["provider"] == name
        assert record["available"] is False
