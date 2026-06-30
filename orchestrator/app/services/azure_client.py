"""
Thin wrapper around azure-mgmt-resource for running ARM template deployments.

Why this file exists separately from the orchestration logic:
ARM has two distinct deployment scopes that use different SDK clients/calls:
  - Resource-group-scope (Templates 1, 2 - everything that lives inside it)

Authentication note: this uses ClientSecretCredential against
customer_tenant_id. This works today because Skysecure's SP has been
granted Contributor directly on SST Lab's subscription. If/when this
moves to Azure Lighthouse, ONLY this authentication step changes - the
deployment calls themselves are identical, because Lighthouse just changes
how the SP's token is scoped, not how ARM deployments work.
"""
import json
import logging
from pathlib import Path
from typing import Any

from azure.identity import ClientSecretCredential
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.resource.resources.models import (
    Deployment,
    DeploymentMode,
    DeploymentProperties,
)

logger = logging.getLogger("orchestrator.azure_client")


class ArmDeploymentError(Exception):
    """Raised when an ARM deployment fails, carrying the Azure error detail."""

    def __init__(self, message: str, correlation_id: str | None = None):
        super().__init__(message)
        self.correlation_id = correlation_id


def _load_template(templates_dir: str, filename: str) -> dict[str, Any]:
    path = Path(templates_dir) / filename
    if not path.exists():
        raise FileNotFoundError(f"ARM template not found: {path}")
    return json.loads(path.read_text())


class AzureDeploymentClient:
    """
    One instance per deployment job. Holds the credential scoped to the
    customer's tenant and exposes the ARM deployment scope we need.
    """

    def __init__(
        self,
        *,
        skysecure_app_id: str,
        skysecure_app_secret: str,
        customer_tenant_id: str,
        customer_subscription_id: str,
        templates_dir: str,
    ):
        self.customer_subscription_id = customer_subscription_id
        self.templates_dir = templates_dir

        # Skysecure's SP, but the TOKEN is scoped to the customer's tenant.
        # This is what makes Skysecure's identity able to act on SST Lab's
        # subscription - the SP must already have a role assignment there.
        self.credential = ClientSecretCredential(
            tenant_id=customer_tenant_id,
            client_id=skysecure_app_id,
            client_secret=skysecure_app_secret,
        )

        self.resource_client = ResourceManagementClient(
            self.credential, customer_subscription_id
        )

    def deploy_at_resource_group_scope(
        self,
        *,
        resource_group_name: str,
        deployment_name: str,
        template_filename: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """For Templates 1 and 2 - everything that lives inside the resource group."""
        template = _load_template(self.templates_dir, template_filename)
        formatted_params = {k: {"value": v} for k, v in parameters.items()}

        poller = self.resource_client.deployments.begin_create_or_update(
            resource_group_name=resource_group_name,
            deployment_name=deployment_name,
            parameters=Deployment(
                properties=DeploymentProperties(
                    mode=DeploymentMode.INCREMENTAL,
                    template=template,
                    parameters=formatted_params,
                )
            ),
        )
        return self._wait_and_extract_outputs(poller, deployment_name)

    @staticmethod
    def _wait_and_extract_outputs(poller, deployment_name: str) -> dict[str, Any]:
        """
        Blocks until the deployment finishes (this runs inside a background
        task, so blocking here is fine - it does not block the API response).
        Raises ArmDeploymentError with Azure's own error detail on failure,
        which is what actually tells you WHY a deployment failed.
        """
        try:
            result = poller.result()
        except Exception as exc:
            logger.error("ARM deployment '%s' failed: %s", deployment_name, exc)
            raise ArmDeploymentError(str(exc)) from exc

        if result.properties.provisioning_state != "Succeeded":
            raise ArmDeploymentError(
                f"Deployment '{deployment_name}' ended in state "
                f"'{result.properties.provisioning_state}'"
            )

        outputs = result.properties.outputs or {}
        # ARM returns outputs as {"key": {"type": "...", "value": ...}} - flatten it
        return {k: v["value"] for k, v in outputs.items()}
