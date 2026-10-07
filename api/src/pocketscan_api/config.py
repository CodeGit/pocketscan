from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read settings from POCKETSCAN_* variables and the .env file.

    extra="ignore" lets .env also hold keys this class does not define, such as
    LOCAL_POSTGRES_PASSWORD, which only the local database script reads.
    """

    model_config = SettingsConfigDict(env_prefix="POCKETSCAN_", env_file=".env", extra="ignore")
    database_url: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
