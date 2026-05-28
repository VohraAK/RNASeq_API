from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str
    SECRET_KEY: str
    REDIS_URL: str = "redis://redis:6379/0"
    COOKIE_SECURE: bool = True
    ALLOWED_ORIGINS: str = "http://localhost:3000"
    UPLOAD_DIR: str = "/var/rnaseq/uploads"
    MAX_FILE_SIZE_BYTES: int = 100 * 1024 * 1024

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]


settings = Settings()
