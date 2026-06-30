import logging
from fastapi import APIRouter, HTTPException, Depends
from azure.identity import ClientSecretCredential
from azure.mgmt.resource import SubscriptionClient, ResourceManagementClient
from app.core.config import get_settings, Settings

logger = logging.getLogger("orchestrator.azure_discovery")

router = APIRouter(prefix="/api/azure", tags=["azure-discovery"])

@router.get("/sp-details")
async def get_sp_details(settings: Settings = Depends(get_settings)):
    """Return the client ID of Skysecure's Service Principal."""
    return {"clientId": settings.skysecure_app_id}

@router.get("/subscriptions")
async def list_subscriptions(tenant_id: str, settings: Settings = Depends(get_settings)):
    """List subscriptions the Service Principal has access to in the given tenant."""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id query parameter is required")
    
    try:
        credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=settings.skysecure_app_id,
            client_secret=settings.skysecure_app_secret
        )
        sub_client = SubscriptionClient(credential)
        subscriptions = []
        for sub in sub_client.subscriptions.list():
            subscriptions.append({
                "subscriptionId": sub.subscription_id,
                "displayName": sub.display_name
            })
        return subscriptions
    except Exception as e:
        logger.error("Failed to list Azure subscriptions: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Could not connect to Azure. Please verify Tenant ID and SP role assignment. Error: {str(e)}"
        )

@router.get("/resource-groups")
async def list_resource_groups(
    tenant_id: str,
    subscription_id: str,
    settings: Settings = Depends(get_settings)
):
    """List resource groups in the specified subscription."""
    if not tenant_id or not subscription_id:
        raise HTTPException(status_code=400, detail="tenant_id and subscription_id are required")
    
    try:
        credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=settings.skysecure_app_id,
            client_secret=settings.skysecure_app_secret
        )
        rg_client = ResourceManagementClient(credential, subscription_id)
        resource_groups = []
        for rg in rg_client.resource_groups.list():
            resource_groups.append(rg.name)
        return resource_groups
    except Exception as e:
        logger.error("Failed to list Azure resource groups: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list resource groups. Error: {str(e)}"
        )
