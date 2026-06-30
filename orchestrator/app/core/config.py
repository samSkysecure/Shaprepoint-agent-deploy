"""
Centralized configuration for the orchestrator.

IMPORTANT: This is the ONLY module that should read secrets directly from
the environment. Every other module receives secrets as function arguments
or via this Settings object - never via os.environ directly.
"""
from functools import lru_cache
from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Skysecure's shared App Registration - used as msaAppId/microsoftAppId
    # in every customer's Bot Service and Container App
    skysecure_app_id: str
    skysecure_app_secret: str

    # # SOP 1 ACR - holds Teams AI SDK bot images
    # acr_server: str
    # acr_username: str
    # acr_password: str

    # SOP 5 ACR - holds Copilot Studio relay bot images (separate registry)
    copilot_acr_server: str = "docintelagent.azurecr.io"
    copilot_acr_username: str = ""
    copilot_acr_password: str = ""

    # Azure OpenAI - shared across all SOP 1 customers
    # Not used by SOP 5 (Copilot Studio provides the LLM)
    azure_openai_api_key: str = ""
    azure_openai_endpoints: str = ""
    azure_openai_deployment_name: str = ""
    azure_openai_api_version: str = "2024-05-01-preview"



    default_location: str = "southindia"
    arm_templates_dir: str = "./arm-templates"
    manifest_output_dir: str = "./generated_manifests"

    # Copilot Studio region - used to build the Direct Line endpoint URL
    copilot_studio_region: str = "southindia"

    # Teams app manifest developer block
    teams_developer_name: str = "Skysecure Technologies"
    teams_developer_website_url: str = "https://www.skysecure.ai"
    teams_developer_privacy_url: str = "https://www.skysecure.ai/privacy"
    teams_developer_terms_url: str = "https://www.skysecure.ai/terms"
    
    AZURE_DOCUMENT_INTEL_KEY: str
    AZURE_DOCUMENT_INTEL_ENDPOINT: str
    AZURE_DOCUMENT_INTEL_MODEL: str

    # ── PII Compliance ───────────────────────────────────────────────────────
    PRESIDIO_NLP_ENGINE: str = "spacy"
    PRESIDIO_MODEL_NAME: str = "en_core_web_lg"

    # ── Microsoft Graph Authentication ───────────────────────────────────────
    MSTENANT_ID: str
    MSCLIENT_ID: str
    MSCLIENT_SECRET: str
    MS_AUTHORITY_BASE: str
    GRAPH_SCOPE: str
    GRAPH_URL: str
    GRAPH_BASE_URL: str

    # ── Authentication Lifespan & Token Scopes ─────────────────────────────────
    GRAPH_TOKEN_BUFFER_SECONDS: int

    # ── Graph Scopes & Extensions ────────────────────────────────────────────
    GRAPH_SCOPES: str = ""

    @property
    def GRAPH_SCOPES_LIST(self) -> list[str]:
        return [
            scope.strip()
            for scope in self.GRAPH_SCOPES.split(",")
            if scope.strip()
        ]

    # ── Redis Configuration ─────────────────────────────────────────────────
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_USERNAME: str
    REDIS_PASSWORD: str
    REDIS_SSL: bool = False
    REDIS_SESSION_TTL: int
    REDIS_DOC_TTL: int
    REDIS_CHECKPOINT_TTL: int

    # ── Cache Configuration ──────────────────────────────────────────────────
    CACHE_MAX_ENTRIES: int = 1000

    # ── Document Processing ─────────────────────────────────────────────────
    DOC_DENSITY_SAMPLE_CHARS: str | int = "1000"

    @field_validator("DOC_DENSITY_SAMPLE_CHARS", mode="before")
    @classmethod
    def parse_density_sample_chars(cls, v: str | int) -> int:
        """Parse density sample chars, handling inline comments."""
        if isinstance(v, str):
            return int(v.split("#")[0].strip())
        return int(v)

    # ── Teams Message Handling ─────────────────────────────────────────────
    MAX_TEAMS_MESSAGE: int


    # ── Rate Limiting ──────────────────────────────────────────────────────
    RATE_WINDOW_SECONDS: int
    RATE_LIMIT_REQUESTS: int

    # ── Langsmith Tracing ──────────────────────────────────────────────────
    LANGCHAIN_API_KEY: str = ""


    # ── Background Task Configuration ────────────────────────────────────────
    MAX_CONCURRENT_BG_TASKS: int
    BG_TASK_TIMEOUT_SECONDS: int
    DOC_PROCESSING_BG_TASK_TIMEOUT_SECONDS: int
    DOC_SUMMARY_TIMEOUT_SECONDS: int
    DEFAULT_FILENAME: str


    # ── File Generation ─────────────────────────────────────────────────────
    TEMP_FILE_TTL_SECONDS: int = 3600  # Default to 1 hour
    FILE_DOWNLOAD_BASE_URL: str
    FILE_GENERATION_MAX_SIZE_MB: int = 50
    FILE_GENERATION_ENABLED: bool = True

    AZURE_STORAGE_SAS_URL: str | None = None
    AZURE_STORAGE_CONNECTION_STRING: str | None = None
    AZURE_STORAGE_CONTAINER_NAME: str

    # ── Copilot Studio Power Automate Flow Integration ───────────────────────
    COPILOT_FLOW_URL: str = ""
    COPILOT_FLOW_ENABLED: bool = True

    # ── Production-grade Chunking Configuration ─────────────────────────────
    CHUNKING_MAX_SECTION_SIZE: int
    CHUNKING_OVERLAP_SIZE: int
    CHUNKING_MIN_PARAGRAPH_COUNT: int
    CHUNKING_DENSITY_SAMPLE_SIZE: int
    CHUNKING_WORKER_COUNT: int
    DOC_MAX_PARALLEL_WORKERS: int = 32

    # ── Density Validation Thresholds ────────────────────────────────────────
    DENSITY_MIN_ALPHABETIC_RATIO: float
    DENSITY_MIN_WORD_ENTROPY: float
    DENSITY_MAX_REPEATED_TOKEN_RATIO: float

    # ── Computed Properties ─────────────────────────────────────────────────
    @property
    def GRAPH_SCOPES_LIST(self) -> List[str]:
        """Return GRAPH_SCOPES as a list."""
        if isinstance(self.GRAPH_SCOPES, str):
            return self.GRAPH_SCOPES.split(",") if self.GRAPH_SCOPES else []
        return self.GRAPH_SCOPES


@lru_cache
def get_settings() -> Settings:
    """Cached so we only parse .env once per process."""
    return Settings()
