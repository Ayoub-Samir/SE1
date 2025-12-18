from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    app_name: str = "Yatırım Programı Revizyon Talebi Demo"
    app_base_url: str = "http://127.0.0.1:8000"

    data_dir: str = "./data"
    storage_dir: str = "./storage"
    output_dir: str = "./outputs"

    llm_provider: str = "mock"  # mock | openai
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    mattermost_webhook_url: str = ""


settings = Settings()
