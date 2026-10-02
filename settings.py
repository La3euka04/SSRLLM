from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Определяем путь к текущему файлу и директории
current_file = Path(__file__).resolve()
current_dir = current_file.parent
env_path = current_dir.parent / ".env"  # Путь к файлу .env

class Settings(BaseSettings):
    LANGSMITH_TRACING: str
    LANGSMITH_ENDPOINT: str
    LANGSMITH_API_KEY: str
    LANGSMITH_PROJECT: str
    PROXY_API_KEY: str
    OPENROUTER_API_KEY: str
    TAVILY_API_KEY: str

    model_config = SettingsConfigDict(env_file=env_path, env_file_encoding="utf-8")

settings = Settings()

if __name__ == "__main__":
    print(settings.model_dump())
