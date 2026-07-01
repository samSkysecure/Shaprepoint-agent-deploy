"""
Centralized configuration for the orchestrator.

IMPORTANT: This is the ONLY module that should read secrets directly from
the environment. Every other module receives secrets as function arguments
or via this Settings object - never via os.environ directly.
"""
from functools import lru_cache
from typing import List
from pydantic import Field, AliasChoices, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

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
    azure_openai_endpoints: str = Field("", validation_alias=AliasChoices("azure_openai_endpoints", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_ENDPOINTS"))
    azure_openai_endpoint: str = Field("", validation_alias=AliasChoices("azure_openai_endpoint", "AZURE_OPENAI_ENDPOINT"))
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
    AZURE_DOCUMENT_INTEL_MODEL: str = "prebuilt-layout"

    # ── PII Compliance ───────────────────────────────────────────────────────
    PRESIDIO_NLP_ENGINE: str = "spacy"
    PRESIDIO_MODEL_NAME: str = "en_core_web_lg"

    # ── Microsoft Graph Authentication ───────────────────────────────────────
    MS_AUTHORITY_BASE: str = "https://login.microsoftonline.com"
    GRAPH_SCOPE: str = "https://graph.microsoft.com/.default"
    GRAPH_URL: str = "https://graph.microsoft.com/v1.0/shares/{share_id}/driveItem/content"
    GRAPH_BASE_URL: str = "https://graph.microsoft.com/v1.0"

    # ── Authentication Lifespan & Token Scopes ─────────────────────────────────
    GRAPH_TOKEN_BUFFER_SECONDS: int = 60

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
    REDIS_HOST: str = Field(validation_alias=AliasChoices("REDIS_HOST", "REDIS_URL"))
    REDIS_PORT: int
    REDIS_USERNAME: str
    REDIS_PASSWORD: str = Field(validation_alias=AliasChoices("REDIS_PASSWORD", "REDIS_KEY"))
    REDIS_SSL: bool = False
    REDIS_SESSION_TTL: int = 86400
    REDIS_DOC_TTL: int = 3600
    REDIS_CHECKPOINT_TTL: int = 86400

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
    MAX_TEAMS_MESSAGE: int = 3600


    # ── Rate Limiting ──────────────────────────────────────────────────────
    RATE_WINDOW_SECONDS: int = 60
    RATE_LIMIT_REQUESTS: int = 30

    # ── Langsmith Tracing ──────────────────────────────────────────────────
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "document_intel"


    # ── Background Task Configuration ────────────────────────────────────────
    MAX_CONCURRENT_BG_TASKS: int = 5
    BG_TASK_TIMEOUT_SECONDS: int = 500
    DOC_PROCESSING_BG_TASK_TIMEOUT_SECONDS: int = 3600
    DOC_SUMMARY_TIMEOUT_SECONDS: int = 800
    DEFAULT_FILENAME: str = "document"


    # ── File Generation ─────────────────────────────────────────────────────
    TEMP_FILE_TTL_SECONDS: int = 3600  # Default to 1 hour
    FILE_DOWNLOAD_BASE_URL: str = ""
    FILE_GENERATION_MAX_SIZE_MB: int = 50
    FILE_GENERATION_ENABLED: bool = True

    AZURE_STORAGE_SAS_URL: str | None = Field(None, validation_alias=AliasChoices("AZURE_STORAGE_SAS_URL", "AZURE_BLOB_SAS_URL"))
    AZURE_STORAGE_CONNECTION_STRING: str | None = None
    AZURE_STORAGE_CONTAINER_NAME: str = Field(validation_alias=AliasChoices("AZURE_STORAGE_CONTAINER_NAME", "AZURE_BLOB_CONTAINER"))

    # ── Copilot Studio Power Automate Flow Integration ───────────────────────
    COPILOT_FLOW_URL: str = ""
    COPILOT_FLOW_ENABLED: bool = True

    # ── Production-grade Chunking Configuration ─────────────────────────────
    CHUNKING_MAX_SECTION_SIZE: int = 3000
    CHUNKING_OVERLAP_SIZE: int = 200
    CHUNKING_MIN_PARAGRAPH_COUNT: int = 2
    CHUNKING_DENSITY_SAMPLE_SIZE: int = 500
    CHUNKING_WORKER_COUNT: int = 4
    DOC_MAX_PARALLEL_WORKERS: int = 32

    # ── Density Validation Thresholds ────────────────────────────────────────
    DENSITY_MIN_ALPHABETIC_RATIO: float = 0.3
    DENSITY_MIN_WORD_ENTROPY: float = 1.5
    DENSITY_MAX_REPEATED_TOKEN_RATIO: float = 0.3

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
