from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-secret-change-me"
    algorithm: str = "HS256"
    database_url: str = (
        "postgresql+asyncpg://subtracker:subtracker@localhost:5432/subtracker"
    )


settings = Settings()
