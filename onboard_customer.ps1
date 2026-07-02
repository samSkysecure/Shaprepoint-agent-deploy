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
    [string]$AgentImageTag = "v1",

    [Parameter(Mandatory=$false)]
    [string]$OrchestratorUrl = "http://localhost:8000",

    [Parameter(Mandatory=$true)]
    [string]$SharePointSiteUrl,

    # JSON array string of SharePoint site URLs to register as Copilot Studio
    # Knowledge Sources, e.g. '["https://contoso.sharepoint.com/sites/HR","https://contoso.sharepoint.com/sites/IT"]'
    # Distinct from -SharePointSiteUrl (which is the single Templates/Generated document library site).
    [Parameter(Mandatory=$false)]
    [string]$KnowledgeBaseSiteUrls = "[]",

    [Parameter(Mandatory=$false)]
    [string]$BotDisplayName,

    [Parameter(Mandatory=$false)]
    [string]$PowerPlatformTenantId = "d7ab1225-4649-4cb3-abd5-bc732bed3203"
)

if ([string]::IsNullOrWhiteSpace($BotDisplayName)) {
    $BotDisplayName = (Get-Culture).TextInfo.ToTitleCase($AgentSlug)
}

$ErrorActionPreference = "Stop"

function Invoke-RestMethodWithDetails {
    param (
        [Parameter(Mandatory=$true)]
        [string]$Method,
        [Parameter(Mandatory=$true)]
        [string]$Uri,
        [Parameter(Mandatory=$false)]
        [string]$ContentType,
        [Parameter(Mandatory=$false)]
        $Body,
        [Parameter(Mandatory=$false)]
        $Headers
    )
    $params = @{
        Method = $Method
        Uri = $Uri
    }
    if ($ContentType) { $params["ContentType"] = $ContentType }
    if ($Body) { $params["Body"] = $Body }
    if ($Headers) { $params["Headers"] = $Headers }

    try {
        Invoke-RestMethod @params
    } catch {
        Write-Host "HTTP Request Failed: $Method $Uri" -ForegroundColor Red
        if ($_.Exception.Response) {
            try {
                $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
                $reader.BaseStream.Position = 0
                $errorBody = $reader.ReadToEnd()
                Write-Host "HTTP Status: $($_.Exception.Response.StatusCode)" -ForegroundColor Red
                Write-Host "Error Body: $errorBody" -ForegroundColor Red
            } catch {
                Write-Host "Failed to read HTTP error response body." -ForegroundColor Yellow
            }
        } else {
            Write-Host "Exception details: $_" -ForegroundColor Red
        }
        throw
    }
}

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
$azTokenResponse = Invoke-RestMethodWithDetails -Method Post -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType "application/x-www-form-urlencoded" -Body $bodyAz
$azToken = $azTokenResponse.access_token

$bodyPa = @{
    client_id     = $ClientId
    client_secret = $ClientSecret
    grant_type    = "client_credentials"
    scope         = "https://api.powerapps.com/.default"
}
try {
    $paTokenResponse = Invoke-RestMethodWithDetails -Method Post -Uri "https://login.microsoftonline.com/$PowerPlatformTenantId/oauth2/v2.0/token" -ContentType "application/x-www-form-urlencoded" -Body $bodyPa
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
    sharepoint_site_url = $SharePointSiteUrl
} | ConvertTo-Json

$deployResponse = Invoke-RestMethodWithDetails -Method Post -Uri "$OrchestratorUrl/deployments" -ContentType "application/json" -Body $deployPayload
$deploymentId = $deployResponse.deployment_id

Write-Host "Deployment Queued. ID: $deploymentId. Polling for completion..."
$containerAppFQDN = $null
while ($true) {
    Start-Sleep -Seconds 10
    $statusResponse = Invoke-RestMethodWithDetails -Method Get -Uri "$OrchestratorUrl/deployments/$deploymentId"
    
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

# Bump the solution version to force Power Platform to update components
$solutionFile = Join-Path $unpackDir "solution.xml"
if (Test-Path $solutionFile) {
    [xml]$solXml = Get-Content $solutionFile -Raw
    $timestamp = (Get-Date).ToString("MMddHHmm")
    $newVersion = "1.0.0.$timestamp"
    $solXml.ImportExportXml.SolutionManifest.Version = $newVersion
    $solXml.Save($solutionFile)
    Write-Host "Successfully bumped connector solution version to: $newVersion"
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
# 3b. INJECT SHAREPOINT KNOWLEDGE SOURCES INTO AGENT SOLUTION
# ---------------------------------------------------------
Write-Host "`n[3b/6] Registering SharePoint Knowledge Base sources..."

function Get-KbSchemaSuffix {
    param([string]$Url)
    # Mirror Copilot Studio's own naming convention (strip scheme/punctuation)
    # but guarantee uniqueness + a safe length with a short hash suffix,
    # since two different site URLs can otherwise sanitize to near-identical strings.
    $stripped = $Url -replace '^https?://', '' -replace '[^a-zA-Z0-9]', ''
    $stripped = $stripped.Substring(0, [Math]::Min(50, $stripped.Length))

    $md5 = [System.Security.Cryptography.MD5]::Create()
    $hashBytes = $md5.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Url))
    $shortHash = -join ($hashBytes[0..3] | ForEach-Object { $_.ToString("x2") })

    return "$stripped$shortHash"
}

$kbUrls = @()
try {
    $kbUrls = $KnowledgeBaseSiteUrls | ConvertFrom-Json
} catch {
    Write-Host "Warning: -KnowledgeBaseSiteUrls was not valid JSON. Treating as empty list."
}
if ($null -eq $kbUrls) { $kbUrls = @() }
# ConvertFrom-Json on a single-element array can return a scalar, not an array - normalize.
$kbUrls = @($kbUrls)

$agentUnpackDir = ".\unpacked_agent_temp"
if (Test-Path $agentUnpackDir) { Remove-Item $agentUnpackDir -Recurse -Force }

Write-Host "Unpacking Agent Solution ($SolutionZipPath)..."
pac solution unpack --zipfile $SolutionZipPath --folder $agentUnpackDir

$botComponentsDir = Join-Path $agentUnpackDir "botcomponents"

# Discover the bot's schema name from the existing botcomponents folder
# (keeps this generic if the agent is ever re-published under a different name).
$sampleComponent = Get-ChildItem -Path $botComponentsDir -Directory | Select-Object -First 1
$botSchemaName = ($sampleComponent.Name -split '\.')[0]

if (-not $botSchemaName) {
    Write-Host "Warning: Could not resolve bot schema name from $botComponentsDir. Skipping KB step."
} else {
    Write-Host "Resolved bot schema name: $botSchemaName"

    # --- ALWAYS strip existing KB source folders first (full replace, not additive) ---
    # Detect by content (kind: KnowledgeSourceConfiguration), not just by URL, so this
    # also cleans up anything baked in from manual Copilot Studio testing/edits.
    $existingKbFolders = Get-ChildItem -Path $botComponentsDir -Directory | Where-Object {
        $dataFile = Join-Path $_.FullName "data"
        (Test-Path $dataFile) -and (Get-Content $dataFile -Raw) -match "kind:\s*KnowledgeSourceConfiguration"
    }
    foreach ($folder in $existingKbFolders) {
        Write-Host "  - Removing existing KB source folder: $($folder.Name)"
        Remove-Item $folder.FullName -Recurse -Force
    }

    # --- Write the desired list fresh ---
    foreach ($kbUrl in $kbUrls) {
        $kbUrl = $kbUrl.Trim()
        if ([string]::IsNullOrWhiteSpace($kbUrl)) { continue }

        $suffix = Get-KbSchemaSuffix -Url $kbUrl
        $componentSchemaName = "$botSchemaName.topic.$suffix"
        $componentDir = Join-Path $botComponentsDir $componentSchemaName

        New-Item -ItemType Directory -Path $componentDir -Force | Out-Null

        $botComponentXml = @"
<botcomponent schemaname="$componentSchemaName">
  <componenttype>16</componenttype>
  <description>This knowledge source provides information found in $kbUrl.</description>
  <iscustomizable>0</iscustomizable>
  <n>$kbUrl</n>
  <parentbotid>
    <schemaname>$botSchemaName</schemaname>
  </parentbotid>
  <statecode>0</statecode>
  <statuscode>1</statuscode>
</botcomponent>
"@
        $kbData = @"
kind: KnowledgeSourceConfiguration
source:
  kind: SharePointSearchSource
  site: $kbUrl
"@
        Set-Content -Path (Join-Path $componentDir "botcomponent.xml") -Value $botComponentXml
        Set-Content -Path (Join-Path $componentDir "data") -Value $kbData

        Write-Host "  + Registered KB source: $kbUrl (schema: $componentSchemaName)"
    }

    if ($kbUrls.Count -eq 0) {
        Write-Host "No Knowledge Base URLs supplied - agent will have zero KB sources."
    }

    # Bump the solution version to force Power Platform to update components
    $solutionFile2 = Join-Path $agentUnpackDir "solution.xml"
    if (Test-Path $solutionFile2) {
        [xml]$solXml2 = Get-Content $solutionFile2 -Raw
        $timestamp = (Get-Date).ToString("MMddHHmm")
        $newVersion2 = "1.0.0.$timestamp"
        $solXml2.ImportExportXml.SolutionManifest.Version = $newVersion2
        $solXml2.Save($solutionFile2)
        Write-Host "Successfully bumped agent solution version to: $newVersion2"
    }

    Write-Host "Repacking Agent Solution..."
    $injectedAgentZipPath = ".\docgen_injected.zip"
    pac solution pack --zipfile $injectedAgentZipPath --folder $agentUnpackDir

    if (Test-Path $injectedAgentZipPath) {
        # Downstream create-settings/import calls reference $SolutionZipPath,
        # so repointing it here propagates automatically.
        $SolutionZipPath = $injectedAgentZipPath
        Write-Host "Agent solution now points to: $SolutionZipPath"
    } else {
        Write-Host "Warning: Failed to create injected agent zip. Falling back to original solution zip (no KB sources)."
    }
}

Remove-Item $agentUnpackDir -Recurse -Force -ErrorAction SilentlyContinue

# ---------------------------------------------------------
# 4. IMPORT CONNECTOR SOLUTION
# ---------------------------------------------------------
  Write-Host "`n[4/6] Authenticating to Power Platform (PAC CLI)..."
  Write-Host "Initiating Device Code authentication..."
  pac auth create --environment $EnvironmentId --deviceCode
  Write-Host "Successfully authenticated!"

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
$deviceCodeRes = Invoke-RestMethodWithDetails -Method Post -Uri "https://login.microsoftonline.com/$PowerPlatformTenantId/oauth2/v2.0/devicecode" -ContentType "application/x-www-form-urlencoded" -Body $deviceCodeBody

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
        $tokenRes = Invoke-RestMethodWithDetails -Method Post -Uri "https://login.microsoftonline.com/$PowerPlatformTenantId/oauth2/v2.0/token" -ContentType "application/x-www-form-urlencoded" -Body $tokenBody
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
$envGuid = "Default-$PowerPlatformTenantId"

$apiHeaders = @{
    "Authorization" = "Bearer $userToken"
    "Content-Type" = "application/json"
}

Write-Host "`nResolving actual Custom Connector API Name in Dataverse..."
$filterQuery = [uri]::EscapeDataString("environment eq '$envGuid'")
$apisUri = "https://api.powerapps.com/providers/Microsoft.PowerApps/apis?api-version=2020-06-01&`$filter=$filterQuery"
$apisResponse = Invoke-RestMethodWithDetails -Method Get -Uri $apisUri -Headers $apiHeaders

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
Invoke-RestMethodWithDetails -Method Put -Uri $putUri -Headers $apiHeaders -Body ($customConnPayload | ConvertTo-Json -Depth 5) | Out-Null
Write-Host "Custom Connector connection successfully created! ID: $customConnGuid"

Write-Host "`nAuto-creating Microsoft Copilot Studio Connection..."
$copilotConnGuid = [guid]::NewGuid().ToString("N")
$copilotConnPayload = @{
    properties = @{
        displayName = "Microsoft Copilot Studio Connection"
        environment = @{ name = $envGuid }
    }
}
$copilotPutUri = "https://api.powerapps.com/providers/Microsoft.PowerApps/apis/shared_microsoftcopilotstudio/connections/$copilotConnGuid`?api-version=2020-06-01"
Invoke-RestMethodWithDetails -Method Put -Uri $copilotPutUri -Headers $apiHeaders -Body ($copilotConnPayload | ConvertTo-Json -Depth 5) | Out-Null
Write-Host "Microsoft Copilot Studio connection successfully created! ID: $copilotConnGuid"

Write-Host "`nBinding Connections to settings.json..."
foreach ($connRef in $settings.ConnectionReferences) {
    if ($connRef.ConnectorId -notmatch "shared_microsoftcopilotstudio") {
        $connRef.ConnectionId = $customConnGuid
    } else {
        $connRef.ConnectionId = $copilotConnGuid
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
$flowsResponse = Invoke-RestMethodWithDetails -Method Get -Uri $flowsUri -Headers $apiHeaders

$docGenFlow = $flowsResponse.value | Where-Object { $_.properties.displayName -match "docgen flow" -or $_.properties.displayName -match "request_trigger" } | Select-Object -First 1

if (-not $docGenFlow) {
    throw "Could not find the 'docgen flow' in Power Automate! Did the solution import fail?"
}

$flowId = $docGenFlow.name
$triggerName = "manual"
$callbackUri = "https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments/$envGuid/flows/$flowId/triggers/$triggerName/listCallbackUrl?api-version=2016-11-01"
$callbackResponse = Invoke-RestMethodWithDetails -Method Post -Uri $callbackUri -Headers @{ "Authorization" = "Bearer $userToken"; "Content-Type" = "application/json" } -Body "{}"

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
        $caState = Invoke-RestMethodWithDetails -Method Get -Uri $azUpdateUri -Headers @{ "Authorization" = "Bearer $azToken" }
        
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
        
        Invoke-RestMethodWithDetails -Method Patch -Uri $azUpdateUri -Headers @{ "Authorization" = "Bearer $azToken"; "Content-Type" = "application/json" } -Body ($patchPayload | ConvertTo-Json -Depth 10)
        Write-Host "Container App successfully updated with the Environment Variables!"
    } catch {
        Write-Host "Warning: Failed to update Container App. Error: $_"
    }
}

Write-Host "`n====================================================="
Write-Host "  ZERO-TOUCH ONBOARDING COMPLETE!"
Write-Host "====================================================="