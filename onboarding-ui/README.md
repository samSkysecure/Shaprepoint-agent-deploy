# Customer Onboarding UI

A web-based interface for the `onboard_customer.ps1` deployment script with real-time log streaming and progress tracking.

## Features

- **Modern Web Interface**: React-based UI with dark theme
- **Real-time Logs**: Live PowerShell output streaming via WebSocket
- **Form Validation**: Input validation for all required parameters
- **Progress Tracking**: Visual status indicators for deployment phases
- **Stop/Reset Controls**: Ability to stop running deployments
- **Responsive Design**: Works on desktop and tablet screens

## Prerequisites

- Node.js (v14 or higher)
- npm
- PowerShell (Windows)
- PAC CLI installed and configured
- `onboard_customer.ps1` script in the parent directory

## Installation

1. Navigate to the onboarding-ui directory:
```bash
cd onboarding-ui
```

2. Install dependencies:
```bash
npm install
```

## Usage

1. Start the server:
```bash
npm start
```

2. Open your browser and navigate to:
```
http://localhost:3001
```

3. Fill in the required configuration fields:
   - **Azure Authentication**: Tenant ID, Client ID, Client Secret
   - **Power Platform**: Environment ID
   - **Solution Files**: Paths to connector and solution zip files
   - **Deployment Configuration**: Customer slug, agent slug, resource group
   - **Optional Settings**: Agent image tag, orchestrator URL

4. Click "Start Onboarding" to begin deployment

5. Monitor real-time logs in the right panel

6. If needed, click "Stop Deployment" to halt the process

## Configuration Fields

### Required Fields

| Field | Description | Example |
|-------|-------------|---------|
| Tenant ID | Azure AD tenant ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| Client ID | Service principal client ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| Client Secret | Service principal secret | `••••••••••••••••` |
| Environment ID | Power Platform environment ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| Connector Solution Zip Path | Path to connector solution zip | `C:\\path\\to\\connector.zip` |
| Solution Zip Path | Path to agent solution zip | `C:\\path\\to\\solution.zip` |
| Customer Slug | Customer identifier | `customer-name` |
| Agent Slug | Agent identifier | `agent-name` |
| Resource Group | Azure resource group name | `rg-name` |

### Optional Fields

| Field | Description | Default |
|-------|-------------|---------|
| Subscription ID | Azure subscription ID | (empty) |
| Agent Image Tag | Docker image tag | `latest` |
| Orchestrator URL | FastAPI orchestrator endpoint | `http://localhost:8000` |

## Deployment Phases

The UI tracks the following phases:

1. **Phase 1: Azure Deployment**
   - Fetch Azure SPN Tokens
   - Trigger Azure Infrastructure Deployment
   - Inject Host into Connector

2. **Phase 2: Power Platform**
   - Import Connector Solution
   - Auto-create Connections
   - Import Agent Solution

3. **Phase 3: Finalize**
   - Publish Solution
   - Update Webhook URL
   - Manual step: Connect in Copilot Studio

## API Endpoints

### POST /api/onboard
Starts the onboarding process.

**Request Body:**
```json
{
  "tenantId": "string",
  "clientId": "string",
  "clientSecret": "string",
  "environmentId": "string",
  "connectorSolutionZipPath": "string",
  "solutionZipPath": "string",
  "customerSlug": "string",
  "agentSlug": "string",
  "resourceGroupName": "string",
  "customerSubscriptionId": "string (optional)",
  "agentImageTag": "string (optional)",
  "orchestratorUrl": "string (optional)"
}
```

**Response:**
```json
{
  "processId": "1234567890"
}
```

### POST /api/stop/:processId
Stops a running deployment process.

**Response:**
```json
{
  "success": true
}
```

## WebSocket Events

### Client → Server

- `join`: Join a process room to receive logs
  ```javascript
  socket.emit('join', processId);
  ```

### Server → Client

- `log`: Real-time log output
  ```javascript
  {
    type: "stdout" | "stderr",
    data: "log message"
  }
  ```

- `complete`: Deployment finished
  ```javascript
  {
    code: 0,
    output: "...",
    errorOutput: "...",
    success: true
  }
  ```

- `error`: Deployment error
  ```javascript
  {
    message: "error message"
  }
  ```

## Troubleshooting

### Server won't start
- Ensure Node.js is installed: `node --version`
- Check if port 3001 is already in use
- Verify all dependencies are installed: `npm install`

### PowerShell script not found
- Ensure `onboard_customer.ps1` is in the parent directory
- Check the script path in `server.js` line 44

### Logs not appearing
- Check browser console for WebSocket errors
- Verify the server is running on port 3001
- Ensure the process ID is correctly joined

### File path validation errors
- Use absolute paths for zip files
- Ensure files exist before starting deployment
- Use double backslashes for Windows paths: `C:\\path\\to\\file.zip`

## Security Notes

- The client secret is sent to the server in plain text. Consider using HTTPS in production.
- The PowerShell script runs with the permissions of the Node.js process.
- Ensure proper access controls on the server in production environments.

## Development

To run in development mode with auto-reload:
```bash
npm run dev
```

## License

Internal use only - SkySecure Technologies
