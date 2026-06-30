const { useState, useEffect, useRef } = React;

function App() {
    const [formData, setFormData] = useState({
        tenantId: '',
        clientId: '',
        clientSecret: '',
        environmentId: '',
        connectorSolutionZipPath: '../docgenConnector_1_0_0_2.zip',
        solutionZipPath: '../docgen_1_0_0_2.zip',
        customerSlug: '',
        agentSlug: '',
        resourceGroupName: '',
        customerSubscriptionId: '',
        agentImageTag: 'latest',
        orchestratorUrl: 'http://localhost:8000',
        sharePointSiteUrl: ''
    });

    const [isRunning, setIsRunning] = useState(false);
    const [logs, setLogs] = useState([]);
    const [processId, setProcessId] = useState(null);
    const [status, setStatus] = useState('idle');
    const [error, setError] = useState(null);
    const [socket, setSocket] = useState(null);
    const logsEndRef = useRef(null);

    const scrollToBottom = () => {
        logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [logs]);

    const handleInputChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError(null);
        setLogs([]);
        setIsRunning(true);
        setStatus('starting');

        try {
            const response = await fetch('http://localhost:3001/api/onboard', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to start onboarding');
            }

            setProcessId(data.processId);
            setStatus('running');

            // Connect to socket for real-time logs
            const newSocket = io('http://localhost:3001');
            newSocket.emit('join', data.processId);

            newSocket.on('log', (log) => {
                setLogs(prev => [...prev, log]);
            });

            newSocket.on('complete', (result) => {
                setIsRunning(false);
                setStatus(result.success ? 'completed' : 'failed');
                setSocket(null);
                newSocket.disconnect();
            });

            newSocket.on('error', (err) => {
                setIsRunning(false);
                setStatus('failed');
                setError(err.message);
                setSocket(null);
                newSocket.disconnect();
            });

            setSocket(newSocket);

        } catch (err) {
            setIsRunning(false);
            setStatus('failed');
            setError(err.message);
        }
    };

    const handleStop = async () => {
        if (processId) {
            await fetch(`http://localhost:3001/api/stop/${processId}`, {
                method: 'POST'
            });
            setIsRunning(false);
            setStatus('stopped');
            if (socket) {
                socket.disconnect();
                setSocket(null);
            }
        }
    };

    const handleReset = () => {
        setLogs([]);
        setStatus('idle');
        setError(null);
        setProcessId(null);
    };

    const getStatusColor = () => {
        switch (status) {
            case 'running': return 'text-blue-400';
            case 'completed': return 'text-green-400';
            case 'failed': return 'text-red-400';
            case 'stopped': return 'text-yellow-400';
            default: return 'text-gray-400';
        }
    };

    const getStatusIcon = () => {
        switch (status) {
            case 'running': return '⏳';
            case 'completed': return '✅';
            case 'failed': return '❌';
            case 'stopped': return '⏹️';
            default: return '📋';
        }
    };

    return (
        <div className="container mx-auto px-4 py-8 max-w-7xl">
            <div className="text-center mb-8">
                <h1 className="text-4xl font-bold text-white mb-2">Customer Onboarding</h1>
                <p className="text-gray-400">SkySecure Zero-Touch Deployment Pipeline</p>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Form Section */}
                <div className="bg-gray-800 rounded-lg p-6 shadow-xl">
                    <h2 className="text-xl font-semibold mb-4 text-white flex items-center gap-2">
                        <span>🔧</span> Configuration
                    </h2>

                    <form onSubmit={handleSubmit} className="space-y-4">
                        {/* Azure Authentication */}
                        <div className="border border-gray-700 rounded-lg p-4">
                            <h3 className="text-sm font-medium text-blue-400 mb-3">Azure Authentication</h3>
                            <div className="grid grid-cols-1 gap-3">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Tenant ID *</label>
                                    <input
                                        type="text"
                                        name="tenantId"
                                        value={formData.tenantId}
                                        onChange={handleInputChange}
                                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                                        placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                                        disabled={isRunning}
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Client ID *</label>
                                    <input
                                        type="text"
                                        name="clientId"
                                        value={formData.clientId}
                                        onChange={handleInputChange}
                                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                                        placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                                        disabled={isRunning}
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Client Secret *</label>
                                    <input
                                        type="password"
                                        name="clientSecret"
                                        value={formData.clientSecret}
                                        onChange={handleInputChange}
                                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                                        placeholder="••••••••••••••••"
                                        disabled={isRunning}
                                    />
                                </div>
                            </div>
                        </div>

                        {/* Power Platform */}
                        <div className="border border-gray-700 rounded-lg p-4">
                            <h3 className="text-sm font-medium text-purple-400 mb-3">Power Platform</h3>
                            <div className="grid grid-cols-1 gap-3">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Environment ID *</label>
                                    <input
                                        type="text"
                                        name="environmentId"
                                        value={formData.environmentId}
                                        onChange={handleInputChange}
                                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                                        placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                                        disabled={isRunning}
                                    />
                                </div>
                            </div>
                        </div>

                        {/* SharePoint Configuration */}
                        <div className="border border-gray-700 rounded-lg p-4">
                            <h3 className="text-sm font-medium text-blue-400 mb-3">SharePoint Configuration</h3>
                            <div className="grid grid-cols-1 gap-3">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Customer SharePoint Site URL *</label>
                                    <input
                                        type="url"
                                        name="sharePointSiteUrl"
                                        value={formData.sharePointSiteUrl}
                                        onChange={handleInputChange}
                                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                                        placeholder="https://contoso.sharepoint.com/sites/your-site"
                                        required
                                        disabled={isRunning}
                                    />
                                    <span className="text-xs text-gray-500 mt-1 block">The SharePoint site where Templates and Generated libraries will be created.</span>
                                </div>
                            </div>
                        </div>

                        {/* Solution Files */}
                        <div className="border border-gray-700 rounded-lg p-4">
                            <h3 className="text-sm font-medium text-green-400 mb-3">Solution Files</h3>
                            <div className="grid grid-cols-1 gap-3">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Connector Solution Zip Path *</label>
                                    <input
                                        type="text"
                                        name="connectorSolutionZipPath"
                                        value={formData.connectorSolutionZipPath}
                                        onChange={handleInputChange}
                                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                                        placeholder="C:\\path\\to\\connector.zip"
                                        disabled={isRunning}
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Solution Zip Path *</label>
                                    <input
                                        type="text"
                                        name="solutionZipPath"
                                        value={formData.solutionZipPath}
                                        onChange={handleInputChange}
                                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                                        placeholder="C:\\path\\to\\solution.zip"
                                        disabled={isRunning}
                                    />
                                </div>
                            </div>
                        </div>

                        {/* Deployment Configuration */}
                        <div className="border border-gray-700 rounded-lg p-4">
                            <h3 className="text-sm font-medium text-orange-400 mb-3">Deployment Configuration</h3>
                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Customer Slug *</label>
                                    <input
                                        type="text"
                                        name="customerSlug"
                                        value={formData.customerSlug}
                                        onChange={handleInputChange}
                                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                                        placeholder="customer-name"
                                        disabled={isRunning}
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Agent Slug *</label>
                                    <input
                                        type="text"
                                        name="agentSlug"
                                        value={formData.agentSlug}
                                        onChange={handleInputChange}
                                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                                        placeholder="agent-name"
                                        disabled={isRunning}
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Resource Group *</label>
                                    <input
                                        type="text"
                                        name="resourceGroupName"
                                        value={formData.resourceGroupName}
                                        onChange={handleInputChange}
                                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                                        placeholder="rg-name"
                                        disabled={isRunning}
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Subscription ID</label>
                                    <input
                                        type="text"
                                        name="customerSubscriptionId"
                                        value={formData.customerSubscriptionId}
                                        onChange={handleInputChange}
                                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                                        placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                                        disabled={isRunning}
                                    />
                                </div>
                            </div>
                        </div>

                        {/* Optional Settings */}
                        <div className="border border-gray-700 rounded-lg p-4">
                            <h3 className="text-sm font-medium text-gray-400 mb-3">Optional Settings</h3>
                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Agent Image Tag</label>
                                    <input
                                        type="text"
                                        name="agentImageTag"
                                        value={formData.agentImageTag}
                                        onChange={handleInputChange}
                                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                                        placeholder="latest"
                                        disabled={isRunning}
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Orchestrator URL</label>
                                    <input
                                        type="text"
                                        name="orchestratorUrl"
                                        value={formData.orchestratorUrl}
                                        onChange={handleInputChange}
                                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                                        placeholder="http://localhost:8000"
                                        disabled={isRunning}
                                    />
                                </div>
                            </div>
                        </div>

                        {/* Action Buttons */}
                        <div className="flex gap-3 pt-4">
                            {!isRunning ? (
                                <button
                                    type="submit"
                                    className="flex-1 bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors flex items-center justify-center gap-2"
                                >
                                    🚀 Start Onboarding
                                </button>
                            ) : (
                                <button
                                    type="button"
                                    onClick={handleStop}
                                    className="flex-1 bg-red-600 hover:bg-red-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors flex items-center justify-center gap-2"
                                >
                                    ⏹️ Stop Deployment
                                </button>
                            )}
                            {status !== 'idle' && !isRunning && (
                                <button
                                    type="button"
                                    onClick={handleReset}
                                    className="bg-gray-600 hover:bg-gray-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors"
                                >
                                    🔄 Reset
                                </button>
                            )}
                        </div>
                    </form>
                </div>

                {/* Logs Section */}
                <div className="bg-gray-800 rounded-lg p-6 shadow-xl flex flex-col">
                    <div className="flex items-center justify-between mb-4">
                        <h2 className="text-xl font-semibold text-white flex items-center gap-2">
                            <span>📋</span> Deployment Logs
                        </h2>
                        <div className={`flex items-center gap-2 ${getStatusColor()}`}>
                            <span className="text-2xl">{getStatusIcon()}</span>
                            <span className="font-medium capitalize">{status}</span>
                        </div>
                    </div>

                    {error && (
                        <div className="bg-red-900/50 border border-red-700 rounded-lg p-4 mb-4">
                            <p className="text-red-400 font-medium">❌ Error: {error}</p>
                        </div>
                    )}

                    <div className="flex-1 bg-gray-900 rounded-lg p-4 overflow-y-auto min-h-[500px] log-container">
                        {logs.length === 0 ? (
                            <div className="text-gray-500 text-center py-20">
                                <p className="text-4xl mb-4">📭</p>
                                <p>No logs yet. Start the deployment to see real-time output.</p>
                            </div>
                        ) : (
                            <>
                                {logs.map((log, index) => (
                                    <div
                                        key={index}
                                        className={`mb-1 ${log.type === 'stderr' ? 'log-stderr' : 'log-stdout'}`}
                                    >
                                        {log.data}
                                    </div>
                                ))}
                                <div ref={logsEndRef} />
                            </>
                        )}
                    </div>

                    {status === 'running' && (
                        <div className="mt-4 flex items-center justify-center gap-2 text-blue-400">
                            <div className="animate-spin w-5 h-5 border-2 border-blue-400 border-t-transparent rounded-full"></div>
                            <span>Deployment in progress...</span>
                        </div>
                    )}

                    {status === 'completed' && (
                        <div className="mt-4 bg-green-900/50 border border-green-700 rounded-lg p-4 text-center">
                            <p className="text-green-400 font-medium text-lg">✅ Deployment completed successfully!</p>
                        </div>
                    )}

                    {status === 'failed' && (
                        <div className="mt-4 bg-red-900/50 border border-red-700 rounded-lg p-4 text-center">
                            <p className="text-red-400 font-medium text-lg">❌ Deployment failed. Check logs for details.</p>
                        </div>
                    )}
                </div>
            </div>

            {/* Deployment Steps Reference */}
            <div className="mt-8 bg-gray-800 rounded-lg p-6 shadow-xl">
                <h2 className="text-xl font-semibold mb-4 text-white flex items-center gap-2">
                    <span>📖</span> Deployment Steps Reference
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                    <div className="bg-gray-700/50 rounded-lg p-4">
                        <h3 className="font-medium text-blue-400 mb-2">Phase 1: Azure Deployment</h3>
                        <ul className="text-gray-300 space-y-1">
                            <li>• Fetch Azure SPN Tokens</li>
                            <li>• Trigger Azure Deployment</li>
                            <li>• Inject Host into Connector</li>
                        </ul>
                    </div>
                    <div className="bg-gray-700/50 rounded-lg p-4">
                        <h3 className="font-medium text-purple-400 mb-2">Phase 2: Power Platform</h3>
                        <ul className="text-gray-300 space-y-1">
                            <li>• Import Connector Solution</li>
                            <li>• Auto-create Connections</li>
                            <li>• Import Agent Solution</li>
                        </ul>
                    </div>
                    <div className="bg-gray-700/50 rounded-lg p-4">
                        <h3 className="font-medium text-green-400 mb-2">Phase 3: Finalize</h3>
                        <ul className="text-gray-300 space-y-1">
                            <li>• Publish Solution</li>
                            <li>• Update Webhook URL</li>
                            <li>• Manual: Connect in Copilot Studio</li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
