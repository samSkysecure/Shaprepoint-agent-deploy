const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  cors: {
    origin: "*",
    methods: ["GET", "POST"]
  }
});

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public'), {
  setHeaders: (res, filePath) => {
    res.set('Cache-Control', 'no-store, no-cache, must-revalidate, private');
  }
}));

// Store active processes
const activeProcesses = new Map();

app.post('/api/onboard', (req, res) => {
  const {
    tenantId,
    clientId,
    clientSecret,
    environmentId,
    connectorSolutionZipPath,
    solutionZipPath,
    customerSlug,
    agentSlug,
    resourceGroupName,
    customerSubscriptionId,
    agentImageTag,
    orchestratorUrl,
    sharePointSiteUrl
  } = req.body;

  // Resolve paths to absolute paths
  const resolvedConnectorPath = path.resolve(connectorSolutionZipPath);
  const resolvedSolutionPath = path.resolve(solutionZipPath);

  // Validate required fields
  const required = [
    'tenantId', 'clientId', 'clientSecret', 'environmentId',
    'connectorSolutionZipPath', 'solutionZipPath', 'customerSlug',
    'agentSlug', 'resourceGroupName', 'sharePointSiteUrl'
  ];

  const missing = required.filter(field => !req.body[field]);
  if (missing.length > 0) {
    return res.status(400).json({ 
      error: 'Missing required fields', 
      missing 
    });
  }

  // Validate file paths exist
  if (!fs.existsSync(resolvedConnectorPath)) {
    return res.status(400).json({ 
      error: 'Connector solution zip file not found',
      path: resolvedConnectorPath
    });
  }

  if (!fs.existsSync(resolvedSolutionPath)) {
    return res.status(400).json({ 
      error: 'Solution zip file not found',
      path: resolvedSolutionPath
    });
  }

  const processId = Date.now().toString();
  const scriptPath = path.join(__dirname, '..', 'onboard_customer.ps1');

  // Build PowerShell arguments
  const args = [
    '-File', scriptPath,
    '-TenantId', tenantId,
    '-ClientId', clientId,
    '-ClientSecret', clientSecret,
    '-EnvironmentId', environmentId,
    '-ConnectorSolutionZipPath', resolvedConnectorPath,
    '-SolutionZipPath', resolvedSolutionPath,
    '-CustomerSlug', customerSlug,
    '-AgentSlug', agentSlug,
    '-ResourceGroupName', resourceGroupName,
    '-SharePointSiteUrl', sharePointSiteUrl
  ];

  // Add optional parameters
  if (customerSubscriptionId) {
    args.push('-CustomerSubscriptionId', customerSubscriptionId);
  }
  if (agentImageTag) {
    args.push('-AgentImageTag', agentImageTag);
  }
  if (orchestratorUrl) {
    args.push('-OrchestratorUrl', orchestratorUrl);
  }

  // Spawn PowerShell process
  const ps = spawn('powershell.exe', args, {
    cwd: path.join(__dirname, '..'),
    stdio: ['pipe', 'pipe', 'pipe']
  });

  activeProcesses.set(processId, ps);

  let output = '';
  let errorOutput = '';

  ps.stdout.on('data', (data) => {
    const text = data.toString();
    output += text;
    io.to(processId).emit('log', { type: 'stdout', data: text });
  });

  ps.stderr.on('data', (data) => {
    const text = data.toString();
    errorOutput += text;
    io.to(processId).emit('log', { type: 'stderr', data: text });
  });

  ps.on('close', (code) => {
    activeProcesses.delete(processId);
    io.to(processId).emit('complete', { 
      code, 
      output, 
      errorOutput,
      success: code === 0
    });
  });

  ps.on('error', (err) => {
    activeProcesses.delete(processId);
    io.to(processId).emit('error', { message: err.message });
  });

  res.json({ processId });
});

app.post('/api/stop/:processId', (req, res) => {
  const { processId } = req.params;
  const ps = activeProcesses.get(processId);
  
  if (ps) {
    ps.kill();
    activeProcesses.delete(processId);
    res.json({ success: true });
  } else {
    res.status(404).json({ error: 'Process not found' });
  }
});

io.on('connection', (socket) => {
  socket.on('join', (processId) => {
    socket.join(processId);
  });
});

const PORT = process.env.PORT || 3001;
server.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
