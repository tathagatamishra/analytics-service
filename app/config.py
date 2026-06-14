from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    db_host: str = "127.0.0.1"
    db_port: int = 3311
    db_name: str = "costroomdb"
    db_username: str = "admin"
    db_password: str = "CostRoomDev123"

    # Cognito
    cognito_issuer_uri: str = (
        "https://cognito-idp.ap-southeast-2.amazonaws.com/ap-southeast-2_fxW1EzwhJ"
    )
    cognito_jwk_set_uri: str = (
        "https://cognito-idp.ap-southeast-2.amazonaws.com/ap-southeast-2_fxW1EzwhJ"
        "/.well-known/jwks.json"
    )

    # Service
    service_port: int = 8084
    allowed_origins: str = "http://localhost:5173"

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_username}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
            f"?charset=utf8mb4"
        )

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
