from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    jwt_secret: str = Field(min_length=32)
    redis_url: str = 'redis://redis:6379/0'
    secure_cookies: bool = True
    web_origin: str = 'http://localhost:8080'
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

settings = Settings()
