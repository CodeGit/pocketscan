from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read settings from POCKETSCAN_* variables and the .env file.

    extra="ignore" lets .env also hold keys this class does not define, such as
    LOCAL_POSTGRES_PASSWORD, which only the local database script reads.
    """

    model_config = SettingsConfigDict(env_prefix="POCKETSCAN_", env_file=".env", extra="ignore")
    database_url: str
    # Directory that file:// structure URIs may be served from. Local development only;
    # leave unset in the cluster, where structures are gs:// objects.
    local_structure_root: Path | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
