from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class Settings(BaseSettings):

    # ========================================================
    # APPLICATION
    # ========================================================

    app_name: str = "Agentic AI Travel Planner"
    app_env: str = "development"
    debug: bool = True

    # ========================================================
    # JWT
    # ========================================================

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # ========================================================
    # DATABASE
    # ========================================================

    database_url: str = "postgresql://postgres:admin123@localhost:5432/travel_planner"

    # ========================================================
    # TEST LOGIN (Configurable via .env)
    # ========================================================

    enable_test_login: bool = True
    test_user_email: str = "test@example.com"
    test_user_password: str = "testpassword123"
    test_user_id: str = "test_user_123"
    test_user_role: str = "USER"

    # ========================================================
    # TRAIN APIs
    # ========================================================

    railcore_api_key: str
    railradar_api_key: str

    # ========================================================
    # FLIGHT APIs
    # ========================================================

    serp_api_key: str
    booking_rapidapi_key: str

    # ========================================================
    # HOTEL APIs
    # ========================================================

    liteapi_api_key: str

    # ========================================================
    # LOCATION / GEOCODING
    # ========================================================

    geoapify_api_key: str

    # ========================================================
    # TAVILY
    # ========================================================

    tavily_api_key: str

    # ========================================================
    # LLM / GROQ
    # ========================================================

    groq_api_key: str

    llm_model: str = "openai/gpt-oss-20b"

    # ========================================================
    # SETTINGS
    # ========================================================

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()