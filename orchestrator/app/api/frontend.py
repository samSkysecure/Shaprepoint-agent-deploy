import asyncio
import uuid
import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
from app.core.config import get_settings

router = APIRouter()
settings = get_settings()

# Global dictionary to store task state:
# tasks[task_id] = { "queue": asyncio.Queue(), "process": subprocess }
tasks = {}

class OnboardRequest(BaseModel):
    tenantId: str
    subscriptionId: str
    environmentId: str
    connectorSolutionZip: str
    solutionZip: str
    customerSlug: str
    agentSlug: str
    resourceGroupName: str
    sharePointSiteUrl: str
    botDisplayName: str

@router.post("/api/onboard")
async def start_onboarding(req: OnboardRequest):
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "queue": asyncio.Queue(),
        "process": None
    }
    
    # Run the process in the background
    asyncio.create_task(run_powershell_script(task_id, req))
    return {"task_id": task_id}

@router.get("/api/manifest/{agent_slug}/{customer_slug}")
def download_manifest(agent_slug: str, customer_slug: str):
    # Determine the path based on the orchestrator's directory structure
    cwd = os.path.abspath(os.path.join(os.getcwd(), ".."))
    manifest_dir = os.path.join(cwd, "orchestrator", "generated_manifests")
    
    # If the orchestrator is running directly from the orchestrator directory
    if not os.path.exists(manifest_dir):
        manifest_dir = os.path.join(os.getcwd(), "generated_manifests")
        
    file_path = os.path.join(manifest_dir, f"{agent_slug}-{customer_slug}-manifest.zip")
    
    if os.path.exists(file_path):
        return FileResponse(file_path, filename=f"{agent_slug}-{customer_slug}-manifest.zip", media_type="application/zip")
    
    return {"error": f"Manifest not found at {file_path}"}

async def run_powershell_script(task_id: str, req: OnboardRequest):
    q = tasks[task_id]["queue"]
    
    # We run it in the parent directory PAC-Test so it can find the zip files and the script
    cwd = os.path.abspath(os.path.join(os.getcwd(), ".."))
    ps1_path = os.path.join(cwd, "onboard_customer.ps1")

    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-File", ps1_path,
        "-TenantId", req.tenantId,
        "-CustomerSubscriptionId", req.subscriptionId,
        "-ClientId", settings.skysecure_app_id,
        "-ClientSecret", settings.skysecure_app_secret,
        "-EnvironmentId", req.environmentId,
        "-ConnectorSolutionZipPath", req.connectorSolutionZip,
        "-SolutionZipPath", req.solutionZip,
        "-CustomerSlug", req.customerSlug,
        "-AgentSlug", req.agentSlug,
        "-AgentImageTag", "v1",
        "-ResourceGroupName", req.resourceGroupName,
        "-SharePointSiteUrl", req.sharePointSiteUrl
    ]
    
    if req.botDisplayName:
        cmd.extend(["-BotDisplayName", req.botDisplayName])
    
    try:
        # Start the process
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd
        )
        tasks[task_id]["process"] = process
        
        # Read output line by line
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            
            line_str = line.decode('utf-8', errors='replace').rstrip()
            await q.put(line_str)
            
        await process.wait()
        await q.put(f"[Process Exited with code {process.returncode}]")
        
    except Exception as e:
        await q.put(f"[Error starting process: {str(e)}]")
    finally:
        await q.put(None) # EOF marker

@router.websocket("/api/onboard/logs/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    await websocket.accept()
    
    if task_id not in tasks:
        await websocket.send_text("Error: Task ID not found.")
        await websocket.close()
        return

    q = tasks[task_id]["queue"]
    
    try:
        while True:
            # We also want to allow the client to send us data (like if we needed to pass input to stdin, 
            # but currently we don't need stdin since Device Code happens in browser).
            # The client just reads.
            line = await q.get()
            if line is None:
                break
            await websocket.send_text(line)
            
    except WebSocketDisconnect:
        print(f"Client disconnected from task {task_id}")
    finally:
        pass
