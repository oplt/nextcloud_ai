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
