from config import get_lm_studio_settings


def test_lm_studio_timeout_uses_fallback_for_invalid_env(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_TIMEOUT_SECONDS", "not-a-number")

    settings = get_lm_studio_settings()

    assert settings.timeout_seconds == 15.0


def test_lm_studio_timeout_uses_fallback_for_out_of_bounds_env(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_TIMEOUT_SECONDS", "0")

    settings = get_lm_studio_settings()

    assert settings.timeout_seconds == 15.0


def test_lm_studio_timeout_accepts_valid_env(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_TIMEOUT_SECONDS", "30.5")

    settings = get_lm_studio_settings()

    assert settings.timeout_seconds == 30.5


def test_lm_studio_max_tokens_accepts_valid_env(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_MAX_TOKENS", "1200")

    settings = get_lm_studio_settings()

    assert settings.max_tokens == 1200


def test_lm_studio_max_tokens_uses_fallback_for_out_of_bounds_env(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_MAX_TOKENS", "0")

    settings = get_lm_studio_settings()

    assert settings.max_tokens == 800
