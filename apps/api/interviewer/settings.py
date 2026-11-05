from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, cast

from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_APP_BASE_URL = "http://127.0.0.1:8000"


def _repository_asset_path(value: str) -> str:
    if not value or Path(value).is_absolute():
        return value
    return str((ROOT / Path(value).expanduser()).resolve())


class Settings(BaseModel):
    database_url: str = ""
    sqlite_path: str = str(ROOT / ".data" / "python" / "interviews.sqlite3")
    environment: str = "development"
    provider: str = "fake"
    demo: bool = True
    secret: str = ""
    recruiter_password: str = ""
    admin_password: str = ""
    recruiter_key: str = ""
    admin_key: str = ""
    app_base_url: str = DEFAULT_APP_BASE_URL
    llm_base_url: str = ""
    llm_model: str = ""
    llm_key: str = ""
    input_price: float | None = Field(default=None, ge=0)
    output_price: float | None = Field(default=None, ge=0)
    stt_base_url: str = ""
    stt_model: str = ""
    stt_key: str = ""
    stt_label: str = "企业配置的语音转写服务"
    stt_provider: Literal["auto", "http", "whisper"] = "auto"
    stt_model_path: str = ""
    stt_model_sha256: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    stt_device: str = "cpu"
    stt_language: str = "zh"
    stt_initial_prompt: str = ""
    stt_timeout: float = Field(default=60, gt=0, le=600)
    stt_max_concurrency: int = Field(default=1, ge=1, le=8)
    ffmpeg_path: str = ""
    tts_provider: Literal["local", "edge"] = "local"
    tts_allow_external: bool = False
    tts_voice: str = ""
    tts_rate: str = Field(default="-5%", pattern=r"^[+-]\d{1,3}%$")
    tts_timeout: int = Field(default=30, ge=1, le=120)
    tts_connect_timeout: int = Field(default=10, ge=1, le=60)
    tts_max_concurrency: int = Field(default=2, ge=1, le=8)
    operation_logs: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(ROOT / ".env", override=False)
        env = os.environ
        production = env.get("APP_ENV", env.get("NODE_ENV", "development")) == "production"
        driver = env.get("DB_DRIVER", "sqlite")
        if driver == "pglite":
            raise ValueError("Python后端不直接打开PGlite；请导出旧数据后设置DB_DRIVER=sqlite或postgres。原库未改动。")
        if driver not in {"sqlite", "postgres"} or driver == "postgres" and not env.get("DATABASE_URL"):
            raise ValueError("请配置sqlite，或postgres与DATABASE_URL")
        provider = env.get("LLM_PROVIDER", "fake")
        demo = provider == "fake" and (env.get("DEMO_MODE") == "true" or
                                       (not production and env.get("DEMO_MODE") != "false"))
        database = env.get("DATABASE_URL", "") if env.get("DB_DRIVER") != "sqlite" else ""
        return cls(database_url=database, sqlite_path=env.get("SQLITE_PATH", cls().sqlite_path),
                   environment="production" if production else "development", provider=provider, demo=demo,
                   secret=env.get("AUTH_SECRET", ""), recruiter_password=env.get("RECRUITER_PASSWORD", ""),
                   admin_password=env.get("ADMIN_PASSWORD", ""), recruiter_key=env.get("RECRUITER_API_KEY", ""),
                   admin_key=env.get("ADMIN_API_KEY", ""), app_base_url=env.get("APP_BASE_URL", DEFAULT_APP_BASE_URL),
                   llm_base_url=env.get("LLM_BASE_URL", ""), llm_model=env.get("LLM_MODEL", ""), llm_key=env.get("LLM_API_KEY", ""),
                   input_price=float(env["LLM_INPUT_COST_PER_1K"]) if env.get("LLM_INPUT_COST_PER_1K") else None,
                   output_price=float(env["LLM_OUTPUT_COST_PER_1K"]) if env.get("LLM_OUTPUT_COST_PER_1K") else None,
                   stt_base_url=env.get("STT_BASE_URL", ""), stt_model=env.get("STT_MODEL", ""),
                   stt_key=env.get("STT_API_KEY", ""), stt_label=env.get("STT_PROCESSOR_LABEL", "企业配置的语音转写服务")[:100],
                   stt_provider=cast(Literal["auto", "http", "whisper"], env.get("STT_PROVIDER", "auto")),
                   stt_model_path=_repository_asset_path(env.get("STT_MODEL_PATH", "")),
                   stt_model_sha256=env.get("STT_MODEL_SHA256", ""), stt_device=env.get("STT_DEVICE", "cpu"),
                   stt_language=env.get("STT_LANGUAGE", "zh"), stt_timeout=float(env.get("STT_TIMEOUT", "60")),
                   stt_initial_prompt=env.get("STT_INITIAL_PROMPT", ""),
                   stt_max_concurrency=int(env.get("STT_MAX_CONCURRENCY", "1")),
                   ffmpeg_path=_repository_asset_path(env.get("FFMPEG_PATH", "")),
                   tts_provider=cast(Literal["local", "edge"], env.get("TTS_PROVIDER", "local")),
                   tts_allow_external=env.get("TTS_ALLOW_EXTERNAL") == "true", tts_voice=env.get("TTS_VOICE", ""),
                   tts_rate=env.get("TTS_RATE", "-5%"), tts_timeout=int(env.get("TTS_TIMEOUT", "30")),
                   tts_connect_timeout=int(env.get("TTS_CONNECT_TIMEOUT", "10")),
                   tts_max_concurrency=int(env.get("TTS_MAX_CONCURRENCY", "2")),
                   operation_logs=env.get("OBSERVABILITY_LOGS") == "true")

    def deployment_issues(self) -> list[str]:
        issues: list[str] = []
        if self.environment == "production":
            if len(self.secret) < 32:
                issues.append("AUTH_SECRET_REQUIRED")
            if not self.demo and not self.recruiter_password:
                issues.append("RECRUITER_PASSWORD_REQUIRED")
            if not self.demo and not (self.admin_password or self.admin_key):
                issues.append("ADMIN_IDENTITY_REQUIRED")
        if self.stt_provider == "whisper" and (not self.stt_model_path or not self.stt_model):
            issues.append("LOCAL_WHISPER_CONFIGURATION_INCOMPLETE")
        if self.tts_provider == "edge" and (not self.tts_allow_external or not self.tts_voice):
            issues.append("EDGE_TTS_EXPLICIT_EXTERNAL_PERMISSION_AND_VOICE_REQUIRED")
        if self.stt_provider != "whisper" and bool(self.stt_base_url) != bool(self.stt_model):
            issues.append("STT_CONFIGURATION_INCOMPLETE")
        if (self.input_price is None) != (self.output_price is None):
            issues.append("LLM_PRICE_PAIR_REQUIRED")
        return issues
