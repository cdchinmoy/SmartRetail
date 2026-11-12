from typing import Literal
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    jwt_secret: str = Field(min_length=32)
    redis_url: str = 'redis://redis:6379/0'
    secure_cookies: bool = True
    web_origin: str = 'http://localhost:8080'
    environment: Literal['development', 'production'] = 'development'
    billing_provider: Literal['sandbox', 'razorpay'] = 'sandbox'
    trial_days: int = Field(default=14, ge=1, le=90)
    grace_days: int = Field(default=3, ge=0, le=30)
    razorpay_key_id: str = ''
    razorpay_key_secret: str = ''
    razorpay_webhook_secret: str = ''
    razorpay_previous_webhook_secret: str = ''
    sandbox_webhook_secret: str = ''

    @model_validator(mode='after')
    def production_billing(self):
        if self.environment == 'production' and self.billing_provider == 'sandbox':
            raise ValueError('Sandbox billing is forbidden in production')
        if self.billing_provider == 'razorpay' and not all([self.razorpay_key_id, self.razorpay_key_secret, self.razorpay_webhook_secret]):
            raise ValueError('Razorpay credentials and webhook secret are required')
        return self

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

settings = Settings()
