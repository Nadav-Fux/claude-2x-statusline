from lib import gateway


def test_gateway_host_mapping_and_predicate():
    assert gateway.provider_label_for_host("api.z.ai") == "GLM"
    assert gateway.provider_label_for_host("bigmodel.cn") == "GLM"
    assert gateway.provider_label_for_host("openrouter.ai") == "OpenRouter"
    assert gateway.provider_label_for_host("api.moonshot.cn") == "Kimi"
    assert gateway.provider_label_for_host("api.deepseek.com") == "DeepSeek"
    assert gateway.provider_label_for_host("my-proxy.example.com") == "my-proxy.example.com"

    assert gateway.is_foreign_gateway(None) is False
    assert gateway.is_foreign_gateway("https://api.anthropic.com") is False
    assert gateway.is_foreign_gateway("https://api.z.ai/api/anthropic") is True


def test_gateway_info_uses_settings_env_and_escape_hatch():
    info = gateway.gateway_info(
        env={},
        settings={"env": {"ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic"}},
        config={},
    )

    assert info["foreign"] is True
    assert info["label"] == "GLM"
    assert info["display_host"] == "z.ai"
    assert gateway.gateway_badge_text(info) == "via z.ai (GLM)"
    assert gateway.gateway_note_label(info) == "GLM"

    disabled = gateway.gateway_info(
        env={"ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic"},
        config={"gateway_awareness": False},
    )
    assert disabled["foreign"] is False
