# Teams Copilot Agent Deployment Architecture

## Overview
This diagram illustrates the end-to-end deployment process for a Teams Copilot Agent, spanning Azure infrastructure, Power Platform, and Teams integration.

## Architecture Diagram

```mermaid
graph TB
    subgraph "Developer Machine"
        DEV[Deployment Script]
        ORCH[FastAPI Orchestrator<br/>Port 8000]
        PAC[PAC CLI]
    end

    subgraph "Phase 1: Azure Deployment"
        AZURE[Azure Subscription]
        CA[Container App<br/>3-5 min deploy]
        BS[Azure Bot Service]
        TM[Teams Manifest Zip]
    end

    subgraph "Checkpoint 1: Manual"
        PP1[Power Platform Portal<br/>make.powerapps.com]
        CC[Custom Connector<br/>Tools API]
        URL[Update Host Field<br/>with Container App FQDN]
    end

    subgraph "Phase 2: First Import"
        AUTH1[PAC CLI Auth<br/>Browser Login]
        IMPORT1[pac solution import<br/>no settings<br/>2-4 min]
        REG[Register Connector & Agent]
    end

    subgraph "Checkpoint 2: Manual"
        CONN1[Connection 1<br/>Tools API]
        CONN2[Connection 2<br/>Microsoft Copilot Studio]
    end

    subgraph "Phase 3: Second Import & Publish"
        AUTH2[Power Platform API Auth<br/>Device Code Flow]
        API[Fetch Connection IDs]
        SETTINGS[Generate settings.json]
        IMPORT2[pac solution import<br/>with settings.json]
        PUBLISH[pac solution publish]
    end

    subgraph "Checkpoint 3: Manual"
        TAC[Teams Admin Center<br/>admin.teams.microsoft.com]
        UPLOAD[Upload Manifest Zip]
        PERM[Set Permissions & Assign Users]
    end

    subgraph "Final State"
        FQDN[Container App FQDN]
        APPID[Teams App ID]
        AGENT[Published Copilot Agent]
    end

    %% Flow
    DEV -->|Install Dependencies| ORCH
    ORCH -->|Deploy| CA
    ORCH -->|Deploy| BS
    ORCH -->|Generate| TM
    CA -->|Return FQDN| DEV
    DEV -->|Pause| PP1
    PP1 --> CC
    CC --> URL
    URL -->|Press ENTER| DEV
    DEV -->|Execute| PAC
    PAC --> AUTH1
    AUTH1 --> IMPORT1
    IMPORT1 --> REG
    REG -->|Pause| CONN1
    CONN1 --> CONN2
    CONN2 -->|Press ENTER| DEV
    DEV --> AUTH2
    AUTH2 --> API
    API --> SETTINGS
    SETTINGS --> IMPORT2
    IMPORT2 --> PUBLISH
    PUBLISH -->|Pause| TAC
    TAC --> UPLOAD
    UPLOAD --> PERM
    PERM -->|Press ENTER| DEV
    DEV -->|Output| FQDN
    DEV -->|Output| APPID
    PUBLISH --> AGENT

    %% Styling
    classDef phase fill:#e1f5ff,stroke:#01579b,stroke-width:2px
    classDef checkpoint fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef manual fill:#ffebee,stroke:#c62828,stroke-width:2px
    classDef final fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px

    class AZURE,CA,BS,TM phase
    class PP1,CC,URL checkpoint
    class CONN1,CONN2 manual
    class TAC,UPLOAD,PERM manual
    class FQDN,APPID,AGENT final
```

## Component Details

### Azure Infrastructure
- **Container App**: Hosts the FastAPI orchestrator, provides the API endpoint for the custom connector
- **Azure Bot Service**: Enables Teams bot functionality
- **Teams Manifest**: Zip file containing app configuration for Teams

### Power Platform Components
- **Custom Connector (Tools API)**: Bridges the Container App API to Power Platform
- **Copilot Agent**: The AI assistant built in Microsoft Copilot Studio
- **Connections**: Authentication links between the agent and external services

### Deployment Tools
- **FastAPI Orchestrator**: Local server that coordinates Azure deployment
- **PAC CLI**: Power Platform CLI for solution management
- **Deployment Script**: Orchestrates the entire process with pauses for manual steps

## Data Flow

1. **Phase 1**: Script deploys Azure resources, returns Container App FQDN
2. **Checkpoint 1**: User updates custom connector with the FQDN
3. **Phase 2**: PAC CLI imports solution (registers connector and agent)
4. **Checkpoint 2**: User creates two required connections
5. **Phase 3**: Script fetches connection IDs, generates settings, re-imports with bindings, publishes agent
6. **Checkpoint 3**: User uploads Teams manifest to Teams Admin Center
7. **Complete**: Agent is live with Teams app ID for future redeployments

## Error Handling

- **Phase 1 failures**: Check `orchestrator.log` and `orchestrator_err.log`
- **PAC CLI auth issues**: Run `pac auth clear` and re-authenticate
- **Missing connection IDs**: Verify connections exist in Power Platform before Phase 3

## Future Redeployments

Use the saved **Teams App ID** with the `-TeamsAppId` parameter to skip manifest creation and update the existing Teams app.
