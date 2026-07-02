document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("onboard-form");
    const terminalOutput = document.getElementById("terminal-output");
    const deployBtn = document.getElementById("deploy-btn");
    const btnText = deployBtn.querySelector(".btn-text");
    const loader = deployBtn.querySelector(".loader");
    
    // Modal Elements
    const authModal = document.getElementById("auth-modal");
    const successModal = document.getElementById("success-modal");
    const deviceCodeText = document.getElementById("device-code-text");
    const deviceCodeLink = document.getElementById("device-code-link");
    const copyBtn = document.getElementById("copy-btn");
    const downloadManifestBtn = document.getElementById("download-manifest-btn");
    const closeSuccessBtn = document.getElementById("close-success-btn");

    let currentSocket = null;
    let currentAgentSlug = "";
    let currentCustomerSlug = "";

    function appendLog(message, type = "normal") {
        const line = document.createElement("div");
        line.className = `log-line ${type}`;
        line.textContent = message;
        terminalOutput.appendChild(line);
        terminalOutput.scrollTop = terminalOutput.scrollHeight;
    }

    copyBtn.addEventListener("click", () => {
        navigator.clipboard.writeText(deviceCodeText.textContent);
        copyBtn.textContent = "Copied!";
        setTimeout(() => copyBtn.textContent = "Copy", 2000);
    });
    
    closeSuccessBtn.addEventListener("click", () => {
        successModal.classList.add("hidden");
    });

    // Discovery Elements
    let spClientId = "";
    const spClientIdSpan = document.getElementById("sp-client-id");
    const copySpBtn = document.getElementById("copy-sp-btn");
    const tenantIdInput = document.getElementById("tenantId");
    const btnFetchAzure = document.getElementById("btn-fetch-azure");
    const btnAdminConsent = document.getElementById("btn-admin-consent");
    const azureConnectAlert = document.getElementById("azure-connect-alert");
    const manualInputToggle = document.getElementById("manualInputToggle");
    
    const subscriptionIdSelect = document.getElementById("subscriptionIdSelect");
    const subscriptionIdInput = document.getElementById("subscriptionIdInput");
    
    const resourceGroupNameSelect = document.getElementById("resourceGroupNameSelect");
    const resourceGroupNameInput = document.getElementById("resourceGroupNameInput");

    // Fetch SP ID on load
    async function loadSpDetails() {
        try {
            const res = await fetch("/api/azure/sp-details");
            if (res.ok) {
                const data = await res.json();
                spClientId = data.clientId;
                spClientIdSpan.textContent = spClientId;
                updateConsentLink();
            } else {
                spClientIdSpan.textContent = "Error loading Client ID";
            }
        } catch (err) {
            spClientIdSpan.textContent = "Error loading Client ID";
        }
    }
    loadSpDetails();

    function updateConsentLink() {
        const tenantId = tenantIdInput.value.trim();
        if (tenantId && spClientId) {
            btnAdminConsent.href = `https://login.microsoftonline.com/${tenantId}/adminconsent?client_id=${spClientId}`;
            btnAdminConsent.classList.remove("disabled");
        } else {
            btnAdminConsent.removeAttribute("href");
            btnAdminConsent.classList.add("disabled");
        }
    }

    tenantIdInput.addEventListener("input", updateConsentLink);

    copySpBtn.addEventListener("click", () => {
        const id = spClientIdSpan.textContent;
        if (id && id !== "Loading..." && !id.startsWith("Error")) {
            navigator.clipboard.writeText(id);
            copySpBtn.textContent = "Copied!";
            setTimeout(() => copySpBtn.textContent = "Copy", 2000);
        }
    });

    // Toggle Manual Inputs
    function updateInputToggles() {
        const manual = manualInputToggle.checked;
        if (manual) {
            // Show manual inputs, hide select dropdowns
            subscriptionIdSelect.classList.add("hidden");
            subscriptionIdSelect.removeAttribute("required");
            subscriptionIdInput.classList.remove("hidden");
            subscriptionIdInput.setAttribute("required", "");

            resourceGroupNameSelect.classList.add("hidden");
            resourceGroupNameSelect.removeAttribute("required");
            resourceGroupNameInput.classList.remove("hidden");
            resourceGroupNameInput.setAttribute("required", "");
        } else {
            // Show select dropdowns, hide manual inputs
            subscriptionIdSelect.classList.remove("hidden");
            subscriptionIdSelect.setAttribute("required", "");
            subscriptionIdInput.classList.add("hidden");
            subscriptionIdInput.removeAttribute("required");

            resourceGroupNameSelect.classList.remove("hidden");
            resourceGroupNameSelect.setAttribute("required", "");
            resourceGroupNameInput.classList.add("hidden");
            resourceGroupNameInput.removeAttribute("required");
        }
    }
    manualInputToggle.addEventListener("change", updateInputToggles);
    // Initialize required attributes
    updateInputToggles();

    // Fetch Azure Subscriptions
    btnFetchAzure.addEventListener("click", async () => {
        const tenantId = tenantIdInput.value.trim();
        if (!tenantId) {
            showAlert("Please enter a Tenant ID first.", "error");
            return;
        }

        showAlert("Connecting to Azure...", "info");
        btnFetchAzure.disabled = true;
        
        try {
            const res = await fetch(`/api/azure/subscriptions?tenant_id=${tenantId}`);
            if (!res.ok) {
                const errorData = await res.json().catch(() => ({}));
                throw new Error(errorData.detail || "Failed to authenticate Service Principal.");
            }

            const subs = await res.json();
            if (subs.length === 0) {
                throw new Error("Connected but found 0 accessible subscriptions. Ensure the Contributor role is assigned.");
            }

            // Populate Subscriptions
            subscriptionIdSelect.innerHTML = '<option value="">-- Select Subscription --</option>';
            subs.forEach(sub => {
                const opt = document.createElement("option");
                opt.value = sub.subscriptionId;
                opt.textContent = `${sub.displayName} (${sub.subscriptionId})`;
                subscriptionIdSelect.appendChild(opt);
            });

            showAlert(`Connected successfully! Found ${subs.length} subscription(s).`, "info");
        } catch (err) {
            showAlert(err.message, "error");
            subscriptionIdSelect.innerHTML = '<option value="">-- Fetch Failed --</option>';
        } finally {
            btnFetchAzure.disabled = false;
        }
    });

    // Fetch Resource Groups on Subscription Change
    subscriptionIdSelect.addEventListener("change", async () => {
        const subId = subscriptionIdSelect.value;
        const tenantId = tenantIdInput.value.trim();
        
        if (!subId) {
            resourceGroupNameSelect.innerHTML = '<option value="">-- Select Subscription First --</option>';
            resourceGroupNameSelect.disabled = true;
            return;
        }

        resourceGroupNameSelect.disabled = true;
        resourceGroupNameSelect.innerHTML = '<option value="">Loading resource groups...</option>';

        try {
            const res = await fetch(`/api/azure/resource-groups?tenant_id=${tenantId}&subscription_id=${subId}`);
            if (!res.ok) throw new Error("Failed to retrieve resource groups.");

            const rgs = await res.json();
            resourceGroupNameSelect.innerHTML = '<option value="">-- Select Resource Group --</option>';
            rgs.forEach(rg => {
                const opt = document.createElement("option");
                opt.value = rg;
                opt.textContent = rg;
                resourceGroupNameSelect.appendChild(opt);
            });
            resourceGroupNameSelect.disabled = false;
        } catch (err) {
            showAlert(err.message, "error");
            resourceGroupNameSelect.innerHTML = '<option value="">-- Load Failed --</option>';
        }
    });

    function showAlert(msg, type) {
        azureConnectAlert.textContent = msg;
        azureConnectAlert.className = `form-alert ${type}`;
        azureConnectAlert.classList.remove("hidden");
    }

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        // UI Loading State
        btnText.classList.add("hidden");
        loader.classList.remove("hidden");
        deployBtn.disabled = true;
        terminalOutput.innerHTML = "";
        appendLog("Initializing deployment sequence...", "system");

        // Save slugs for the download link
        currentAgentSlug = "docgen";
        currentCustomerSlug = "skysecure";

        // Build Payload
        const manual = manualInputToggle.checked;
        const subId = manual ? subscriptionIdInput.value.trim() : subscriptionIdSelect.value;
        const rgName = manual ? resourceGroupNameInput.value.trim() : resourceGroupNameSelect.value;

        const kbUrlsRaw = document.getElementById("knowledgeBaseSiteUrls").value.trim();
        let kbUrlsArray = [];
        if (kbUrlsRaw) {
            kbUrlsArray = kbUrlsRaw.split(",").map(url => url.trim()).filter(url => url.length > 0);
        }
        const kbUrlsJson = JSON.stringify(kbUrlsArray);

        const payload = {
            tenantId: tenantIdInput.value.trim(),
            subscriptionId: subId,
            environmentId: document.getElementById("environmentId").value,
            sharePointSiteUrl: document.getElementById("sharePointSiteUrl").value,
            knowledgeBaseSiteUrls: kbUrlsJson,
            connectorSolutionZip: "docgenConnector_1_0_0_2.zip",
            solutionZip: "docgen_1_0_0_2.zip",
            customerSlug: currentCustomerSlug,
            agentSlug: currentAgentSlug,
            resourceGroupName: rgName,
            botDisplayName: "docgen agent"
        };

        try {
            const response = await fetch("/api/onboard", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.statusText}`);
            }

            const data = await response.json();
            const taskId = data.task_id;
            appendLog(`Deployment task initialized. ID: ${taskId}`, "system");
            
            connectWebSocket(taskId);
        } catch (err) {
            appendLog(`Failed to start deployment: ${err.message}`, "error");
            resetUI();
        }
    });

    function connectWebSocket(taskId) {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/api/onboard/logs/${taskId}`;
        
        currentSocket = new WebSocket(wsUrl);

        currentSocket.onmessage = (event) => {
            const line = event.data;
            let type = "normal";
            
            // Basic styling for PowerShell output
            if (line.includes("Error") || line.includes("Exception") || line.includes("Failed")) {
                type = "error";
            } else if (line.includes("Warning")) {
                type = "warn";
            } else if (line.includes("Success") || line.includes("DONE") || line.includes("Completed")) {
                type = "success";
            }

            // DEVICE CODE INTERCEPTION LOGIC
            if (line.includes(">>> Please open: ") || line.includes("To sign in, use a web browser to open the page")) {
                const urlMatch = line.match(/(https:\/\/[^\s]+)/);
                if (urlMatch) {
                    deviceCodeLink.href = urlMatch[1];
                }
            }
            if (line.includes(">>> Enter the code: ") || line.includes("and enter the code")) {
                let codeMatch = line.match(/code:\s*([A-Z0-9]+)/);
                if (!codeMatch) {
                    codeMatch = line.match(/code ([A-Z0-9]+) to authenticate/);
                }
                if (codeMatch) {
                    deviceCodeText.textContent = codeMatch[1];
                    // Trigger modal!
                    authModal.classList.remove("hidden");
                }
            }
            if (line.includes("Successfully authenticated!")) {
                authModal.classList.add("hidden");
                appendLog("✓ Device authentication successful!", "success");
            }
            
            // SUCCESS LOGIC
            if (line.includes("ZERO-TOUCH ONBOARDING COMPLETE!")) {
                downloadManifestBtn.href = `/api/manifest/${currentAgentSlug}/${currentCustomerSlug}`;
                setTimeout(() => {
                    successModal.classList.remove("hidden");
                }, 1000); // Small delay to let the user see the final log
            }

            appendLog(line, type);
        };

        currentSocket.onclose = () => {
            appendLog("Deployment process terminated.", "system");
            resetUI();
        };

        currentSocket.onerror = (err) => {
            appendLog("WebSocket connection error.", "error");
            resetUI();
        };
    }

    function resetUI() {
        btnText.classList.remove("hidden");
        loader.classList.add("hidden");
        deployBtn.disabled = false;
        if (currentSocket) {
            currentSocket.close();
            currentSocket = null;
        }
    }
});
