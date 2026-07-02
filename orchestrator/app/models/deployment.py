"""
Request/response models for the deployment orchestrator.
"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class DeploymentStatus(str, Enum):
    QUEUED = "queued"
    DEPLOYING_CONTAINER_APP = "deploying_container_app"
    DEPLOYING_BOT_SERVICE = "deploying_bot_service"
    DEPLOYING_BOT_SERVICE_ONLY = "deploying_bot_service_only"
    GENERATING_MANIFEST = "generating_manifest"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PROVISIONING_SHAREPOINT = "provisioning_sharepoint"


class DeploymentRequest(BaseModel):
    deployment_type: Optional[str] = Field(
        "sop5",
        description="Deprecated/General deployment type",
    )
    agent_slug: str = Field(..., description="Short identifier for the agent e.g. 'teamsagent' or 'copilotagent'")
    customer_slug: str = Field(..., description="Short identifier for the customer e.g. 'sstlab'")
    customer_tenant_id: str = Field(..., description="Customer's Entra tenant ID")
    customer_subscription_id: str = Field(..., description="Customer's Azure subscription ID")
    resource_group_name: str = Field(..., description="Customer's pre-existing resource group e.g. 'soc-agents'")
    agent_image_tag: str = Field(..., description="Image tag to deploy e.g. 'v1'")
    bot_display_name: str = Field(..., description="Human-readable bot name shown in Teams")
    location: Optional[str] = Field(None, description="Azure region override; defaults to Settings.default_location")
    bot_sku: str = Field("F0", description="F0 for testing, S1 for production")
    sharepoint_site_url: Optional[str] = Field(
    None,
    description="Customer's SharePoint site URL e.g. https://contoso.sharepoint.com/sites/hr-docgen"
    )

    # Copilot Studio agent schema name
    # Found in agent URL: /bots/cre6d_Toolrequest/ → schema name is cre6d_Toolrequest
    copilot_schema_name: Optional[str] = Field(
        None,
        description="Copilot Studio agent schema name.",
    )

    # Persist across redeployments so Teams sees it as an update not a new app
    teams_app_id: Optional[str] = Field(
        None,
        description="Existing Teams app UUID from a prior deployment. "
                    "Omit on first deployment - generated automatically. "
                    "Pass it back on every subsequent redeploy to update the same app.",
    )


class StepResult(BaseModel):
    step: str
    status: str
    detail: Optional[str] = None
    outputs: Optional[dict] = None


class DeploymentRecord(BaseModel):
    deployment_id: str
    status: DeploymentStatus
    request: DeploymentRequest
    steps: list[StepResult] = []
    resource_group_name: Optional[str] = None
    container_app_fqdn: Optional[str] = None
    bot_service_resource_id: Optional[str] = None
    teams_app_id: Optional[str] = None
    manifest_zip_path: Optional[str] = None
    error: Optional[str] = None
    sharepoint_site_id: Optional[str] = None
    sharepoint_templates_drive_id: Optional[str] = None
    sharepoint_generated_drive_id: Optional[str] = None
    sharepoint_deployed_lists_id: Optional[str] = None