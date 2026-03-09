import pytest

from backend.core.config import Settings


COMMON_SETTINGS = {
    "_env_file": None,
    "DATABASE_URL": "postgresql+asyncpg://nextcloud:secret@localhost:5432/nextcloud",
    "EMBEDDING_DIM": 1024,
}


def test_frontend_redirect_url_from_list() -> None:
    settings = Settings(
        **COMMON_SETTINGS,
        FRONTEND_URL=["http://localhost:3000", "http://localhost:5173"],
    )

    assert settings.frontend_allowed_origins == [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    assert settings.frontend_redirect_url == "http://localhost:5173"


def test_frontend_redirect_url_from_string() -> None:
    settings = Settings(
        **COMMON_SETTINGS,
        FRONTEND_URL="http://localhost:5173/",
    )

    assert settings.frontend_allowed_origins == ["http://localhost:5173"]
    assert settings.frontend_redirect_url == "http://localhost:5173"


def test_celery_runs_eagerly_by_default_in_development() -> None:
    settings = Settings(
        **COMMON_SETTINGS,
        APP_ENV="development",
    )

    assert settings.celery_task_always_eager is True
    assert settings.effective_embedding_provider == "deterministic"
    assert settings.effective_llm_provider == "stub"


def test_celery_can_be_forced_off_in_development() -> None:
    settings = Settings(
        **COMMON_SETTINGS,
        APP_ENV="development",
        CELERY_TASK_ALWAYS_EAGER=False,
    )

    assert settings.celery_task_always_eager is False


def test_default_ollama_chat_model_is_trimmed() -> None:
    settings = Settings(**COMMON_SETTINGS)

    assert settings.OLLAMA_CHAT_MODEL == settings.OLLAMA_CHAT_MODEL.strip()


def test_auth_cookie_secure_defaults_off_in_development() -> None:
    settings = Settings(
        **COMMON_SETTINGS,
        APP_ENV="development",
    )

    assert settings.auth_cookie_secure is False


def test_auth_cookie_secure_defaults_on_in_production() -> None:
    settings = Settings(
        **COMMON_SETTINGS,
        APP_ENV="production",
    )

    assert settings.auth_cookie_secure is True
    assert settings.csrf_cookie_secure is True
    assert settings.effective_embedding_provider == "ollama"
    assert settings.effective_llm_provider == "ollama"
    assert settings.ollama_required is True


def test_production_rejects_insecure_cookie_override() -> None:
    with pytest.raises(ValueError):
        Settings(
            **COMMON_SETTINGS,
            APP_ENV="production",
            AUTH_COOKIE_SECURE=False,
        )


def test_explicit_provider_override_is_respected_in_production() -> None:
    settings = Settings(
        **COMMON_SETTINGS,
        APP_ENV="production",
        EMBEDDING_PROVIDER="deterministic",
        LLM_PROVIDER="stub",
    )

    assert settings.effective_embedding_provider == "deterministic"
    assert settings.effective_llm_provider == "stub"
    assert settings.ollama_required is False
