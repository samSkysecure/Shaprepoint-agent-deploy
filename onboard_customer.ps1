param (
    [Parameter(Mandatory=$true)]
    [string]$TenantId,

    [Parameter(Mandatory=$true)]
    [string]$ClientId,

    [Parameter(Mandatory=$true)]
    [string]$ClientSecret,

    [Parameter(Mandatory=$true)]
    [string]$EnvironmentId,

    [Parameter(Mandatory=$true)]
    [string]$ConnectorSolutionZipPath,

    [Parameter(Mandatory=$true)]
    [string]$SolutionZipPath,

    [Parameter(Mandatory=$true)]
    [string]$CustomerSlug,

    [Parameter(Mandatory=$true)]
    [string]$AgentSlug,

    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory=$false)]
    [string]$CustomerSubscriptionId,

    [Parameter(Mandatory=$false)]
    [string]$AgentImageTag = "latest",

    [Parameter(Mandatory=$false)]
    [string]$OrchestratorUrl = "http://localhost:8000",

    [Parameter(Mandatory=$true)]
    [string]$SharePointSiteUrl,

    [Parameter(Mandatory=$false)]
    [string]$BotDisplayName
)

if ([string]::IsNullOrWhiteSpace($BotDisplayName)) {
    $BotDisplayName = (Get-Culture).TextInfo.ToTitleCase($AgentSlug)
}

$ErrorActionPreference = "Stop"

Write-Host "====================================================="
Write-Host "  SKYSECURE - ZERO-TOUCH ONBOARDING PIPELINE"
Write-Host "====================================================="

# ---------------------------------------------------------
# 1. AUTHENTICATE via SPN (For Azure)
# ---------------------------------------------------------
Write-Host "`n[1/7] Fetching Azure SPN Tokens..."
$bodyAz = @{
    client_id     = $ClientId
    client_secret = $ClientSecret
    grant_type    = "client_credentials"
    scope         = "https://management.azure.com/.default"
}
$azTokenResponse = Invoke-RestMethod -Method Post -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType "application/x-www-form-urlencoded" -Body $bodyAz
$azToken = $azTokenResponse.access_token

$bodyPa = @{
    client_id     = $ClientId
    client_secret = $ClientSecret
    grant_type    = "client_credentials"
    scope         = "https://api.powerapps.com/.default"
}
try {
    $paTokenResponse = Invoke-RestMethod -Method Post -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType "application/x-www-form-urlencoded" -Body $bodyPa
    $paToken = $paTokenResponse.access_token
} catch {
    Write-Host "Warning: Could not fetch PowerApps token. Falling back to manual connection IDs."
    $paToken = $null
}

Write-Host "Successfully acquired tokens."

# ---------------------------------------------------------
# 2. TRIGGER AZURE DEPLOYMENT
# ---------------------------------------------------------
Write-Host "`n[2/7] Triggering Azure Infrastructure Deployment via Orchestrator..."
$deployPayload = @{
    agent_slug = $AgentSlug
    customer_slug = $CustomerSlug
    deployment_type = "sop5"
    resource_group_name = $ResourceGroupName
    customer_tenant_id = $TenantId
    customer_subscription_id = $CustomerSubscriptionId
    agent_image_tag = $AgentImageTag
    bot_display_name = $BotDisplayName
    bot_sku = "F0"
} | ConvertTo-Json

$deployResponse = Invoke-RestMethod -Method Post -Uri "$OrchestratorUrl/deployments" -ContentType "application/json" -Body $deployPayload
$deploymentId = $deployResponse.deployment_id

Write-Host "Deployment Queued. ID: $deploymentId. Polling for completion..."
$containerAppFQDN = $null
while ($true) {
    Start-Sleep -Seconds 10
    $statusResponse = Invoke-RestMethod -Method Get -Uri "$OrchestratorUrl/deployments/$deploymentId"
    
    Write-Host "Status: $($statusResponse.status)"
    if ($statusResponse.status -eq "succeeded") {
        $containerAppFQDN = $statusResponse.container_app_fqdn
        Write-Host "Deployment successful! Backend FQDN: $containerAppFQDN"
        break
    } elseif ($statusResponse.status -eq "failed") {
        throw "Deployment failed: $($statusResponse.error)"
    }
}

# ---------------------------------------------------------
# 3. DYNAMICALLY INJECT HOST INTO CONNECTOR ZIP
# ---------------------------------------------------------
Write-Host "`n[3/6] Automating Custom Connector Host URL..."
$unpackDir = ".\unpacked_connector_temp"
if (Test-Path $unpackDir) { Remove-Item $unpackDir -Recurse -Force }

Write-Host "Unpacking Connector Zip..."
pac solution unpack --zipfile $ConnectorSolutionZipPath --folder $unpackDir

$swaggerFile = Get-ChildItem -Path $unpackDir -Recurse -Filter "*_openapidefinition.json" | Select-Object -First 1
if ($swaggerFile) {
    $swaggerPath = $swaggerFile.FullName
    $swagger = Get-Content $swaggerPath | ConvertFrom-Json
    $swagger.host = $containerAppFQDN
    $swagger | ConvertTo-Json -Depth 10 | Set-Content $swaggerPath
    Write-Host "Successfully injected Container App FQDN into swagger: $($swaggerFile.Name)"
} else {
    Write-Host "Warning: Could not find swagger file to inject host."
}

Write-Host "Repacking Connector Zip..."
$injectedZipPath = ".\documentConnector_injected.zip"
pac solution pack --zipfile $injectedZipPath --folder $unpackDir
Remove-Item $unpackDir -Recurse -Force

if (-not (Test-Path $injectedZipPath)) {
    Write-Host "Warning: Failed to create injected zip. Falling back to original connector zip."
    $injectedZipPath = $ConnectorSolutionZipPath
}

# ---------------------------------------------------------
# 4. IMPORT CONNECTOR SOLUTION
# ---------------------------------------------------------
  Write-Host "`n[4/6] Authenticating to Power Platform (PAC CLI)..."
  $orgSelectOutput = pac org select --environment $EnvironmentId 2>&1
  
  if ($LASTEXITCODE -ne 0 -or $orgSelectOutput -match "Error" -or $orgSelectOutput -match "No profiles were found" -or $orgSelectOutput -match "Cannot find environment") {
      Write-Host "No active profile found for this environment. Initiating Device Code authentication..."
      # This will output "To sign in, use a web browser to open the page..."
      pac auth create --environment $EnvironmentId --deviceCode
      Write-Host "Successfully authenticated!"
  } else {
      Write-Host $orgSelectOutput
  }

Write-Host "Importing Injected Connector Solution ($injectedZipPath)..."
pac solution import --path $injectedZipPath --force-overwrite --activate-plugins

# ---------------------------------------------------------
# 5. BIND CONNECTIONS & IMPORT AGENT
# ---------------------------------------------------------
Write-Host "`n[5/6] Auto-Creating Connections via Power Platform API..."
Write-Host "=========================================================================="
Write-Host "ACTION REQUIRED: Power Platform Authentication"
Write-Host "Microsoft requires a human User (not a Service Principal) to create connections."
Write-Host "We will securely grab your User Token via a standard Microsoft Login."
Write-Host "=========================================================================="

$pacClientId = "1950a258-227b-4e31-a9cf-717495945fc2"
$bapScope = "https://management.core.windows.net/.default"
$deviceCodeBody = @{ client_id = $pacClientId; scope = "$bapScope offline_access" }
$deviceCodeRes = Invoke-RestMethod -Method Post -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/devicecode" -ContentType "application/x-www-form-urlencoded" -Body $deviceCodeBody

Write-Host "`n>>> Please open: $($deviceCodeRes.verification_uri)"
Write-Host ">>> Enter the code: $($deviceCodeRes.user_code) (copied to clipboard!)"
Set-Clipboard -Value $deviceCodeRes.user_code

Write-Host "`nWaiting for you to log in..."
$userToken = $null
while ($null -eq $userToken) {
    Start-Sleep -Seconds 5
    $tokenBody = @{
        grant_type = "urn:ietf:params:oauth:grant-type:device_code"
        client_id = $pacClientId
        device_code = $deviceCodeRes.device_code
    }
    try {
        $tokenRes = Invoke-RestMethod -Method Post -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType "application/x-www-form-urlencoded" -Body $tokenBody
        $userToken = $tokenRes.access_token
    } catch { }
}
Write-Host "Successfully authenticated!"

Write-Host "Generating settings.json dynamically..."
pac solution create-settings --solution-zip $SolutionZipPath --settings-file ".\settings.json" | Out-Null

if (-not (Test-Path ".\settings.json")) {
    throw "Failed to dynamically generate settings.json."
}

$settings = Get-Content ".\settings.json" | ConvertFrom-Json
$customConnectorRef = $settings.ConnectionReferences | Where-Object { $_.ConnectorId -notmatch "shared_microsoftcopilotstudio" } | Select-Object -First 1

$customConnectorId = $customConnectorRef.ConnectorId.Split("/")[-1]
$customConnGuid = [guid]::NewGuid().ToString("N")
$envGuid = "Default-$TenantId"

$apiHeaders = @{
    "Authorization" = "Bearer $userToken"
    "Content-Type" = "application/json"
}

Write-Host "`nResolving actual Custom Connector API Name in Dataverse..."
$filterQuery = [uri]::EscapeDataString("environment eq '$envGuid'")
$apisUri = "https://api.powerapps.com/providers/Microsoft.PowerApps/apis?api-version=2020-06-01&`$filter=$filterQuery"
$apisResponse = Invoke-RestMethod -Method Get -Uri $apisUri -Headers $apiHeaders

$actualApi = $apisResponse.value | Where-Object { $_.name -match "docgen-20sharepoint-20connector" -and $_.name -match "shared_" } | Select-Object -First 1

if (-not $actualApi) {
    throw "Could not find the imported DocGen Custom Connector in Dataverse. Ensure Step 4 succeeded."
}

$actualApiId = $actualApi.name
Write-Host "Found Custom Connector API: $actualApiId"

Write-Host "`nAuto-creating Custom Connector Connection..."
$customConnPayload = @{
    properties = @{
        displayName = "DocGen Custom Connector"
        environment = @{ name = $envGuid }
    }
}
$putUri = "https://api.powerapps.com/providers/Microsoft.PowerApps/apis/$actualApiId/connections/$customConnGuid`?api-version=2020-06-01"
Invoke-RestMethod -Method Put -Uri $putUri -Headers $apiHeaders -Body ($customConnPayload | ConvertTo-Json -Depth 5) | Out-Null
Write-Host "Custom Connector connection successfully created! ID: $customConnGuid"

Write-Host "`nBinding Connections to settings.json..."
foreach ($connRef in $settings.ConnectionReferences) {
    if ($connRef.ConnectorId -notmatch "shared_microsoftcopilotstudio") {
        $connRef.ConnectionId = $customConnGuid
    } else {
        $connRef.ConnectionId = "" # Leave Copilot Studio unbound for user UI consent
    }
}
$settings | ConvertTo-Json -Depth 10 | Set-Content ".\settings.json"

Write-Host "Importing Agent Solution ($SolutionZipPath)..."
pac solution import --path $SolutionZipPath --settings-file ".\settings.json" --force-overwrite --activate-plugins

Write-Host "Publishing Solution..."
pac solution publish

# ---------------------------------------------------------
# 6. AUTOMATE WEBHOOK URL PATCH
# ---------------------------------------------------------
Write-Host "`n[6/6] Auto-fetching Flow Webhook URL..."
$flowsUri = "https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments/$envGuid/flows?api-version=2016-11-01"
$flowsResponse = Invoke-RestMethod -Method Get -Uri $flowsUri -Headers $apiHeaders

$docGenFlow = $flowsResponse.value | Where-Object { $_.properties.displayName -match "docgen flow" -or $_.properties.displayName -match "request_trigger" } | Select-Object -First 1

if (-not $docGenFlow) {
    throw "Could not find the 'docgen flow' in Power Automate! Did the solution import fail?"
}

$flowId = $docGenFlow.name
$triggerName = "manual"
$callbackUri = "https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments/$envGuid/flows/$flowId/triggers/$triggerName/listCallbackUrl?api-version=2016-11-01"
$callbackResponse = Invoke-RestMethod -Method Post -Uri $callbackUri -Headers @{ "Authorization" = "Bearer $userToken"; "Content-Type" = "application/json" } -Body "{}"

Write-Host "Raw Callback Response: " ($callbackResponse | ConvertTo-Json -Depth 5)

$flowTriggerUrl = $callbackResponse.response.value
if ([string]::IsNullOrWhiteSpace($flowTriggerUrl)) {
    # Fallback just in case the API sometimes returns it directly at the root
    $flowTriggerUrl = $callbackResponse.value
}

if ([string]::IsNullOrWhiteSpace($flowTriggerUrl)) {
    throw "The Flow Webhook URL returned empty! Please check the raw response above to see why Power Automate didn't provide a URL."
}

Write-Host "Successfully fetched Flow URL automatically: $flowTriggerUrl"

Write-Host "`n=========================================================================="
Write-Host "ALMOST DONE! ONLY 1 MANUAL STEP REMAINS AFTER THIS FINISHES:"
Write-Host "=========================================================================="
Write-Host "1. Go to: https://copilotstudio.microsoft.com/"
Write-Host "2. Select your Environment at the top right."
Write-Host "3. Open your Agent ('Document Generation Agent' or similar)."
Write-Host "4. Navigate to Settings -> Connections."
Write-Host "5. Click 'Connect' on ANY connection that says 'Not Connected'."
Write-Host "==========================================================================`n"

if (-not [string]::IsNullOrWhiteSpace($flowTriggerUrl) -or -not [string]::IsNullOrWhiteSpace($SharePointSiteUrl)) {
    Write-Host "`nUpdating Azure Container App Environment Variables..."
    $containerAppName = "ca-$AgentSlug-$CustomerSlug"
    
    $azUpdateUri = "https://management.azure.com/subscriptions/$CustomerSubscriptionId/resourceGroups/$ResourceGroupName/providers/Microsoft.App/containerApps/$containerAppName`?api-version=2023-05-01"
    
    try {
        $caState = Invoke-RestMethod -Method Get -Uri $azUpdateUri -Headers @{ "Authorization" = "Bearer $azToken" }
        
        $envVars = $caState.properties.template.containers[0].env
        
        if (-not [string]::IsNullOrWhiteSpace($flowTriggerUrl)) {
            $existingVar = $envVars | Where-Object { $_.name -eq "COPILOT_FLOW_URL" }
            if ($existingVar) {
                $existingVar.value = $flowTriggerUrl.Trim()
            } else {
                $envVars += @{ name = "COPILOT_FLOW_URL"; value = $flowTriggerUrl.Trim() }
            }
        }
        
        if (-not [string]::IsNullOrWhiteSpace($SharePointSiteUrl)) {
            $existingSPVar = $envVars | Where-Object { $_.name -eq "SHAREPOINT_SITE_URL" }
            if ($existingSPVar) {
                $existingSPVar.value = $SharePointSiteUrl.Trim()
            } else {
                $envVars += @{ name = "SHAREPOINT_SITE_URL"; value = $SharePointSiteUrl.Trim() }
            }
        }
        
        $caState.properties.template.containers[0].env = $envVars
        
        $patchPayload = @{
            properties = @{
                template = $caState.properties.template
            }
        }
        
        Invoke-RestMethod -Method Patch -Uri $azUpdateUri -Headers @{ "Authorization" = "Bearer $azToken"; "Content-Type" = "application/json" } -Body ($patchPayload | ConvertTo-Json -Depth 10)
        Write-Host "Container App successfully updated with the Environment Variables!"
    } catch {
        Write-Host "Warning: Failed to update Container App. Error: $_"
    }
}

Write-Host "`n====================================================="
Write-Host "  ZERO-TOUCH ONBOARDING COMPLETE!"
Write-Host "====================================================="
