from backend.core.config import Settings


def test_frontend_redirect_url_from_list() -> None:
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://nextcloud:secret@localhost:5432/nextcloud",
        FRONTEND_URL=["http://localhost:3000", "http://localhost:5173"],
    )

    assert settings.frontend_allowed_origins == [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    assert settings.frontend_redirect_url == "http://localhost:5173"


def test_frontend_redirect_url_from_string() -> None:
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://nextcloud:secret@localhost:5432/nextcloud",
        FRONTEND_URL="http://localhost:5173/",
    )

    assert settings.frontend_allowed_origins == ["http://localhost:5173"]
    assert settings.frontend_redirect_url == "http://localhost:5173"


def test_celery_runs_eagerly_by_default_in_development() -> None:
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://nextcloud:secret@localhost:5432/nextcloud",
        APP_ENV="development",
    )

    assert settings.celery_task_always_eager is True


def test_celery_can_be_forced_off_in_development() -> None:
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://nextcloud:secret@localhost:5432/nextcloud",
        APP_ENV="development",
        CELERY_TASK_ALWAYS_EAGER=False,
    )

    assert settings.celery_task_always_eager is False


def test_default_ollama_chat_model_is_trimmed() -> None:
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://nextcloud:secret@localhost:5432/nextcloud",
    )

    assert settings.OLLAMA_CHAT_MODEL == settings.OLLAMA_CHAT_MODEL.strip()
