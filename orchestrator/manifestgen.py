from app.core.config import get_settings
from app.services.teams_manifest import generate_and_zip_manifest

settings = get_settings()

zip_bytes, teams_app_id = generate_and_zip_manifest(
    bot_id=settings.skysecure_app_id,
    container_app_fqdn="ca-teamsagent-sst.niceisland-a356fcde.southindia.azurecontainerapps.io",
    agent_slug="teamsagent",
    customer_slug="sstlab",
    agent_display_name="SST Lab Tool Governance Agent",
    settings=settings,
)

with open("manifest_package.zip", "wb") as f:
    f.write(zip_bytes)

print(f"Teams App ID: {teams_app_id}")
print("Manifest package written to manifest_package.zip")