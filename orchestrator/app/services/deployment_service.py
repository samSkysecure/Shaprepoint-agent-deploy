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

    token = _get_graph_token(settings)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Resolve site ID from URL
    site_id = _resolve_site_id(site_url, headers)

    # Ensure Templates and Generated libraries exist
    templates_drive_id = _get_or_create_library(site_id, "Templates", headers)
    generated_drive_id = _get_or_create_library(site_id, "Generated", headers)

    # Store on record so they can be injected into Container App env vars
    record.sharepoint_site_id = site_id
    record.sharepoint_templates_drive_id = templates_drive_id
    record.sharepoint_generated_drive_id = generated_drive_id

    record.steps.append(StepResult(
        step="provision_sharepoint",
        status="succeeded",
        outputs={
            "site_url": site_url,
            "site_id": site_id,
            "templates_drive_id": templates_drive_id,
            "generated_drive_id": generated_drive_id,
        },
        detail=_timestamp(),
    ))
    logger.info(
        "SharePoint provisioned. Site: %s | Templates: %s | Generated: %s",
        site_id, templates_drive_id, generated_drive_id,
    )


def _get_graph_token(settings: Settings) -> str:
    """Acquire a Graph API token using the SPN client credentials."""
    url = f"https://login.microsoftonline.com/{settings.MSTENANT_ID}/oauth2/v2.0/token"
    response = httpx.post(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": settings.MSCLIENT_ID,
            "client_secret": settings.MSCLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise SharePointProvisioningError(
            f"Failed to acquire Graph token. Status: {response.status_code}. "
            f"Detail: {response.text}"
        )
    return response.json()["access_token"]


def _resolve_site_id(site_url: str, headers: dict) -> str:
    """Resolve a SharePoint site URL to its Graph site ID."""
    parsed = urlparse(site_url)
    hostname = parsed.hostname
    path = quote(parsed.path, safe="/")

    url = f"{GRAPH_BASE}/sites/{hostname}:{path}"
    response = httpx.get(url, headers=headers, timeout=30)

    if response.status_code == 404:
        raise SharePointProvisioningError(
            f"SharePoint site not found: {site_url}. "
            "Verify the URL is correct and the SPN has Sites.ReadWrite.All permission."
        )
    if response.status_code != 200:
        raise SharePointProvisioningError(
            f"Failed to resolve site ID for {site_url}. "
            f"Status: {response.status_code}. Detail: {response.text}"
        )

    site_id = response.json()["id"]
    logger.debug("Resolved site ID: %s", site_id)
    return site_id


def _get_or_create_library(site_id: str, library_name: str, headers: dict) -> str:
    """
    Returns the drive ID for the named document library.
    Creates the library if it does not exist.
    """
    # Check if library already exists
    drives_response = httpx.get(
        f"{GRAPH_BASE}/sites/{site_id}/drives",
        headers=headers,
        timeout=30,
    )
    if drives_response.status_code != 200:
        raise SharePointProvisioningError(
            f"Failed to list drives on site {site_id}. "
            f"Status: {drives_response.status_code}. Detail: {drives_response.text}"
        )

    drives = drives_response.json().get("value", [])
    existing = next((d for d in drives if d["name"] == library_name), None)

    if existing:
        logger.info("Library '%s' already exists. Drive ID: %s", library_name, existing["id"])
        return existing["id"]

    # Create the document library
    logger.info("Library '%s' not found — creating it.", library_name)
    create_response = httpx.post(
        f"{GRAPH_BASE}/sites/{site_id}/lists",
        headers=headers,
        json={
            "displayName": library_name,
            "list": {"template": "documentLibrary"},
        },
        timeout=30,
    )
    if create_response.status_code not in (200, 201):
        raise SharePointProvisioningError(
            f"Failed to create library '{library_name}'. "
            f"Status: {create_response.status_code}. Detail: {create_response.text}"
        )

    # Re-fetch drives to get the drive ID of the newly created library
    # (list creation returns a list object, not a drive)
    for attempt in range(6):
        time.sleep(5)
        drives_response = httpx.get(
            f"{GRAPH_BASE}/sites/{site_id}/drives",
            headers=headers,
            timeout=30,
        )
        drives = drives_response.json().get("value", [])
        created = next((d for d in drives if d["name"] == library_name), None)
        if created:
            logger.info("Library '%s' created. Drive ID: %s", library_name, created["id"])
            return created["id"]
        logger.debug("Waiting for library '%s' to appear... attempt %d/6", library_name, attempt + 1)

    raise SharePointProvisioningError(
        f"Library '{library_name}' was created but did not appear in drives after 30s. "
        "This is a SharePoint provisioning delay — retry the deployment."
    )


class SharePointProvisioningError(Exception):
    """Raised when SharePoint library provisioning fails."""
    pass


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
        "msClientId": settings.MSCLIENT_ID,
        "msClientSecret": settings.MSCLIENT_SECRET,
        "redisHost": settings.REDIS_HOST,
        "redisPassword": settings.REDIS_PASSWORD,
        "langchainApiKey": settings.LANGCHAIN_API_KEY,
        "azureDocumentIntelKey": settings.AZURE_DOCUMENT_INTEL_KEY,
        "azureDocumentIntelEndpoint": settings.AZURE_DOCUMENT_INTEL_ENDPOINT,
        "azureOpenAiApiKey": "dummy-value-not-used",
        "azureOpenAiEndpoint": "https://dummy-endpoint.com",
        "azureOpenAiDeploymentName": "dummy-deployment",
        "azureOpenAiApiVersion": settings.azure_openai_api_version,
        "fileDownloadBaseUrl": settings.FILE_DOWNLOAD_BASE_URL,
        "azureStorageContainerName": settings.AZURE_STORAGE_CONTAINER_NAME,
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