"""
Deployment sequence orchestrator.

Deploys a Container App (Copilot Studio relay bot) + Bot Service + Manifest.
Optionally provisions SharePoint document library structure (Templates + Generated)
on the customer's SharePoint site if sharepoint_site_url is provided in the request.
"""
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, quote

import httpx

from app.core.config import Settings
from app.models.deployment import DeploymentRecord, DeploymentStatus, StepResult
from app.services.azure_client import ArmDeploymentError, AzureDeploymentClient
from app.services.teams_manifest import generate_and_zip_manifest
from app.services.sharepoint import SharePointClient

logger = logging.getLogger("orchestrator.deployment_service")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_deployment(record: DeploymentRecord, settings: Settings) -> None:
    req = record.request
    location = req.location or settings.default_location
    record.resource_group_name = req.resource_group_name

    client = AzureDeploymentClient(
        skysecure_app_id=settings.skysecure_app_id,
        skysecure_app_secret=settings.skysecure_app_secret,
        customer_tenant_id=req.customer_tenant_id,
        customer_subscription_id=req.customer_subscription_id,
        templates_dir=settings.arm_templates_dir,
    )

    try:
        _step_deploy_container_app(record, client, req, location, settings)
        _step_deploy_bot_service(record, client, req, settings)
        _step_generate_manifest(record, req, settings)

        if req.sharepoint_site_url:
            _step_provision_sharepoint(record, req, settings)

        record.status = DeploymentStatus.SUCCEEDED
        logger.info("Deployment %s succeeded", record.deployment_id)

    except ArmDeploymentError as exc:
        record.status = DeploymentStatus.FAILED
        record.error = str(exc)
        logger.error("Deployment %s failed: %s", record.deployment_id, exc)
    except Exception as exc:
        record.status = DeploymentStatus.FAILED
        record.error = f"Unexpected error: {exc}"
        logger.exception("Deployment %s hit an unexpected error", record.deployment_id)


# ---------------------------------------------------------------------------
# SharePoint provisioning
# ---------------------------------------------------------------------------

def _step_provision_sharepoint(
    record: DeploymentRecord,
    req,
    settings: Settings,
) -> None:
    record.status = DeploymentStatus.PROVISIONING_SHAREPOINT
    site_url = req.sharepoint_site_url.rstrip("/")

    logger.info("Provisioning SharePoint structure on site: %s", site_url)

    # Use the refactored SharePointClient to provision site structure
    client = SharePointClient(
        site_url=site_url,
        tenant_id="d7ab1225-4649-4cb3-abd5-bc732bed3203",  # Hardcoded to SST Lab tenant
        client_id=settings.skysecure_app_id,
        client_secret=settings.skysecure_app_secret,
    )
    
    structure = client.ensure_structure()
    
    site_id = structure["site_id"]
    templates_drive_id = structure["template_drive_id"]
    generated_drive_id = structure["generated_drive_id"]
    deployed_lists_id = structure["deployed_lists_id"]

    # Store on record so they can be injected into Container App env vars
    record.sharepoint_site_id = site_id
    record.sharepoint_templates_drive_id = templates_drive_id
    record.sharepoint_generated_drive_id = generated_drive_id
    record.sharepoint_deployed_lists_id = deployed_lists_id

    record.steps.append(StepResult(
        step="provision_sharepoint",
        status="succeeded",
        outputs={
            "site_url": site_url,
            "site_id": site_id,
            "templates_drive_id": templates_drive_id,
            "generated_drive_id": generated_drive_id,
            "deployed_lists_id": deployed_lists_id,
        },
        detail=_timestamp(),
    ))
    logger.info(
        "SharePoint provisioned. Site: %s | Templates: %s | Generated: %s | Deployed Lists: %s",
        site_id, templates_drive_id, generated_drive_id, deployed_lists_id,
    )


# ---------------------------------------------------------------------------
# deployment steps 
# ---------------------------------------------------------------------------

def _step_deploy_container_app(
    record: DeploymentRecord,
    client: AzureDeploymentClient,
    req,
    location: str,
    settings: Settings,
) -> None:
    record.status = DeploymentStatus.DEPLOYING_CONTAINER_APP
    deployment_name = f"deploy-containerapp-{req.agent_slug}-{req.customer_slug}"

    acr_server = settings.copilot_acr_server
    acr_username = settings.copilot_acr_username
    acr_password = settings.copilot_acr_password

    agent_image = f"{acr_server}/{req.agent_slug}:{req.agent_image_tag}"

    parameters = {
        "agentSlug": req.agent_slug,
        "customerSlug": req.customer_slug,
        "location": location,
        "agentImage": agent_image,
        "acrServer": acr_server,
        "acrUsername": acr_username,
        "acrPassword": acr_password,
        "microsoftAppId": settings.skysecure_app_id,
        "microsoftAppPassword": settings.skysecure_app_secret,
        "customerTenantId": req.customer_tenant_id,
        "sharepointTenantId": "d7ab1225-4649-4cb3-abd5-bc732bed3203",
        "msClientId": settings.skysecure_app_id,
        "msClientSecret": settings.skysecure_app_secret,
        "redisHost": settings.REDIS_HOST,
        "redisPort": str(settings.REDIS_PORT),
        "redisPassword": settings.REDIS_PASSWORD,
        "langchainApiKey": settings.LANGCHAIN_API_KEY,
        "langchainProject": settings.LANGCHAIN_PROJECT,
        "azureDocumentIntelKey": settings.AZURE_DOCUMENT_INTEL_KEY,
        "azureDocumentIntelEndpoint": settings.AZURE_DOCUMENT_INTEL_ENDPOINT,
        "azureOpenAiApiKey": settings.azure_openai_api_key,
        "azureOpenAiEndpoint": settings.azure_openai_endpoint or settings.azure_openai_endpoints,
        "azureOpenAiDeploymentName": settings.azure_openai_deployment_name,
        "azureOpenAiApiVersion": settings.azure_openai_api_version,
        "fileDownloadBaseUrl": settings.FILE_DOWNLOAD_BASE_URL,
        "azureStorageContainerName": settings.AZURE_STORAGE_CONTAINER_NAME,
        "azureBlobSasUrl": settings.AZURE_STORAGE_SAS_URL,
    }

    outputs = client.deploy_at_resource_group_scope(
        resource_group_name=req.resource_group_name,
        deployment_name=deployment_name,
        template_filename="template1-containerapp.json",
        parameters=parameters,
    )

    record.container_app_fqdn = outputs["containerAppFQDN"]
    record.steps.append(StepResult(
        step="deploy_container_app",
        status="succeeded",
        outputs=outputs,
        detail=_timestamp(),
    ))
    logger.info("Container App deployed, FQDN: %s", record.container_app_fqdn)


def _step_deploy_bot_service(
    record: DeploymentRecord,
    client: AzureDeploymentClient,
    req,
    settings: Settings,
) -> None:
    record.status = DeploymentStatus.DEPLOYING_BOT_SERVICE
    deployment_name = f"deploy-botservice-{req.agent_slug}-{req.customer_slug}"

    outputs = client.deploy_at_resource_group_scope(
        resource_group_name=req.resource_group_name,
        deployment_name=deployment_name,
        template_filename="template2-botservice.json",
        parameters={
            "agentSlug": req.agent_slug,
            "customerSlug": req.customer_slug,
            "botDisplayName": req.bot_display_name,
            "msaAppId": settings.skysecure_app_id,
            "msaAppTenantId": req.customer_tenant_id,
            "containerAppFQDN": record.container_app_fqdn,
            "sku": req.bot_sku,
        },
    )

    record.bot_service_resource_id = outputs["botServiceResourceId"]
    record.steps.append(StepResult(
        step="deploy_bot_service",
        status="succeeded",
        outputs=outputs,
        detail=_timestamp(),
    ))
    logger.info("Bot Service deployed: %s", record.bot_service_resource_id)


def _step_generate_manifest(
    record: DeploymentRecord,
    req,
    settings: Settings,
) -> None:
    record.status = DeploymentStatus.GENERATING_MANIFEST

    zip_bytes, teams_app_id = generate_and_zip_manifest(
        bot_id=settings.skysecure_app_id,
        container_app_fqdn=record.container_app_fqdn,
        agent_slug=req.agent_slug,
        customer_slug=req.customer_slug,
        settings=settings,
        teams_app_id=req.teams_app_id,
    )

    output_dir = Path(settings.manifest_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{req.agent_slug}-{req.customer_slug}-manifest.zip"
    zip_path.write_bytes(zip_bytes)

    record.teams_app_id = teams_app_id
    record.manifest_zip_path = str(zip_path)
    record.steps.append(StepResult(
        step="generate_manifest",
        status="succeeded",
        outputs={"teams_app_id": teams_app_id, "manifest_zip_path": str(zip_path)},
        detail=_timestamp(),
    ))
    logger.info(
        "Manifest generated agent=%s customer=%s teams_app_id=%s path=%s",
        req.agent_slug, req.customer_slug, teams_app_id, zip_path,
    )