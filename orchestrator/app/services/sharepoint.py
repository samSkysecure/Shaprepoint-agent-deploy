"""
sharepoint.py
-------------
Standalone SharePoint client for Skysecure Container App agents.

Responsibilities:
  - Authenticate to Microsoft Graph using the SPN credentials already
    present as env vars (MSTENANT_ID, MSCLIENT_ID, MSCLIENT_SECRET).
  - On first use, ensure the customer's SharePoint site has the expected
    document library structure (Templates, Generated). Creates them if missing.
  - Download template files from the Templates library.
  - Upload generated documents to the Generated library.
  - List files in either library.
  - Delete files from either library.

Environment variables required:
  MSTENANT_ID                  - Customer tenant ID (GUID)
  MSCLIENT_ID                  - SPN client ID
  MSCLIENT_SECRET              - SPN client secret
  SHAREPOINT_SITE_URL          - Full URL of the customer SharePoint site
                                 e.g. https://contoso.sharepoint.com/sites/hr-docgen
                                 Set by the frontend onboarding flow.

Optional:
  SHAREPOINT_TEMPLATES_LIBRARY - Library name for templates (default: Templates)
  SHAREPOINT_GENERATED_LIBRARY - Library name for generated docs (default: Generated)
  GRAPH_TOKEN_BUFFER_SECONDS   - Seconds before expiry to refresh token (default: 60)
"""

import os
import time
import logging
from io import BytesIO
from typing import Optional
from urllib.parse import urlparse, quote

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

TEMPLATES_LIBRARY = os.getenv("SHAREPOINT_TEMPLATES_LIBRARY", "Templates")
GENERATED_LIBRARY = os.getenv("SHAREPOINT_GENERATED_LIBRARY", "Generated")
TOKEN_BUFFER = int(os.getenv("GRAPH_TOKEN_BUFFER_SECONDS", "60"))


# ---------------------------------------------------------------------------
# Internal token cache (module-level, per process)
# ---------------------------------------------------------------------------

_token_cache: dict = {
    "access_token": None,
    "expires_at": 0.0,
}


def _get_graph_token() -> str:
    """
    Returns a valid Graph access token, refreshing if expired or close to expiry.
    Uses client credentials flow with the SPN creds from env vars.
    """
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - TOKEN_BUFFER:
        return _token_cache["access_token"]

    tenant_id = _require_env("MSTENANT_ID")
    client_id = _require_env("MSCLIENT_ID")
    client_secret = _require_env("MSCLIENT_SECRET")

    url = TOKEN_URL_TEMPLATE.format(tenant_id=tenant_id)
    response = httpx.post(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": GRAPH_SCOPE,
        },
        timeout=30,
    )
    _raise_for_graph_error(response, context="token acquisition")

    data = response.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = now + int(data.get("expires_in", 3600))

    logger.debug("Graph token refreshed, expires in %ss", data.get("expires_in"))
    return _token_cache["access_token"]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_graph_token()}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Site resolution
# ---------------------------------------------------------------------------

def _parse_site_url(site_url: str) -> tuple[str, str]:
    """
    Parses a SharePoint site URL into (hostname, site_path).
    e.g. https://contoso.sharepoint.com/sites/hr-docgen
      -> ("contoso.sharepoint.com", "/sites/hr-docgen")
    """
    parsed = urlparse(site_url.rstrip("/"))
    return parsed.hostname, parsed.path


def _get_site_id(site_url: str) -> str:
    """
    Resolves a SharePoint site URL to its Graph site ID.
    Caches the result on the SharePointClient instance that calls this.
    """
    hostname, path = _parse_site_url(site_url)
    # Graph endpoint: /sites/{hostname}:{path}
    encoded_path = quote(path, safe="/")
    url = f"{GRAPH_BASE}/sites/{hostname}:{encoded_path}"

    response = httpx.get(url, headers=_headers(), timeout=30)
    _raise_for_graph_error(response, context=f"resolving site {site_url}")

    site_id = response.json()["id"]
    logger.debug("Resolved site ID: %s", site_id)
    return site_id


# ---------------------------------------------------------------------------
# Library helpers
# ---------------------------------------------------------------------------

def _list_drives(site_id: str) -> list[dict]:
    url = f"{GRAPH_BASE}/sites/{site_id}/drives"
    response = httpx.get(url, headers=_headers(), timeout=30)
    _raise_for_graph_error(response, context="listing drives")
    return response.json().get("value", [])


def _get_or_create_library(site_id: str, library_name: str) -> str:
    """
    Returns the drive ID for the named document library.
    Creates the library if it does not exist.
    """
    drives = _list_drives(site_id)
    existing = next((d for d in drives if d["name"] == library_name), None)

    if existing:
        logger.debug("Library '%s' found, drive ID: %s", library_name, existing["id"])
        return existing["id"]

    # Create the document library
    logger.info("Library '%s' not found — creating it.", library_name)
    url = f"{GRAPH_BASE}/sites/{site_id}/lists"
    payload = {
        "displayName": library_name,
        "list": {"template": "documentLibrary"},
    }
    response = httpx.post(url, headers=_headers(), json=payload, timeout=30)
    _raise_for_graph_error(response, context=f"creating library '{library_name}'")

    # The list creation returns a list object, not a drive.
    # Fetch drives again to get the drive ID for the new library.
    drives = _list_drives(site_id)
    created = next((d for d in drives if d["name"] == library_name), None)
    if not created:
        raise SharePointError(
            f"Library '{library_name}' was created but could not be found in drives. "
            "This can happen if SharePoint provisioning is still in progress — retry in a few seconds."
        )

    logger.info("Library '%s' created, drive ID: %s", library_name, created["id"])
    return created["id"]


# ---------------------------------------------------------------------------
# Public client class
# ---------------------------------------------------------------------------

class SharePointClient:
    """
    Stateful client for a single customer SharePoint site.
    Resolves the site and library IDs on first use and caches them
    for the lifetime of the instance.

    Usage:
        client = SharePointClient()  # reads SHAREPOINT_SITE_URL from env
        content = client.download_template("offer_letter.docx")
        client.upload_generated("john_doe_offer.docx", content)
    """

    def __init__(self, site_url: Optional[str] = None):
        self.site_url = (site_url or _require_env("SHAREPOINT_SITE_URL")).rstrip("/")
        self._site_id: Optional[str] = None
        self._template_drive_id: Optional[str] = None
        self._generated_drive_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Lazy initialisation — resolves IDs on first use
    # ------------------------------------------------------------------

    def _ensure_initialised(self):
        if self._site_id is not None:
            return
        logger.info("Initialising SharePoint client for site: %s", self.site_url)
        self._site_id = _get_site_id(self.site_url)
        self._template_drive_id = _get_or_create_library(self._site_id, TEMPLATES_LIBRARY)
        self._generated_drive_id = _get_or_create_library(self._site_id, GENERATED_LIBRARY)
        logger.info(
            "SharePoint client ready. Templates drive: %s | Generated drive: %s",
            self._template_drive_id,
            self._generated_drive_id,
        )

    @property
    def site_id(self) -> str:
        self._ensure_initialised()
        return self._site_id

    @property
    def template_drive_id(self) -> str:
        self._ensure_initialised()
        return self._template_drive_id

    @property
    def generated_drive_id(self) -> str:
        self._ensure_initialised()
        return self._generated_drive_id

    # ------------------------------------------------------------------
    # Templates library
    # ------------------------------------------------------------------

    def list_templates(self) -> list[dict]:
        """
        Lists all files in the Templates library.

        Returns a list of dicts, each with:
          - name        (str)  filename
          - id          (str)  Graph item ID
          - size        (int)  bytes
          - modified    (str)  ISO 8601 last modified datetime
          - download_url (str) pre-authenticated download URL (valid ~1hr)
        """
        url = f"{GRAPH_BASE}/drives/{self.template_drive_id}/root/children"
        response = httpx.get(url, headers=_headers(), timeout=30)
        _raise_for_graph_error(response, context="listing templates")

        return [
            {
                "name": item["name"],
                "id": item["id"],
                "size": item.get("size", 0),
                "modified": item.get("lastModifiedDateTime"),
                "download_url": item.get("@microsoft.graph.downloadUrl"),
            }
            for item in response.json().get("value", [])
            if "file" in item  # skip folders
        ]

    def download_template(self, filename: str) -> bytes:
        """
        Downloads a template file by name from the Templates library.
        Raises SharePointFileNotFoundError if the file does not exist.
        """
        self._ensure_initialised()
        encoded = quote(filename)
        url = f"{GRAPH_BASE}/drives/{self.template_drive_id}/root:/{encoded}:/content"

        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {_get_graph_token()}"},
            follow_redirects=True,
            timeout=60,
        )
        if response.status_code == 404:
            raise SharePointFileNotFoundError(
                f"Template '{filename}' not found in the Templates library."
            )
        _raise_for_graph_error(response, context=f"downloading template '{filename}'")

        logger.info("Downloaded template '%s' (%d bytes)", filename, len(response.content))
        return response.content

    def upload_template(self, filename: str, content: bytes) -> dict:
        """
        Uploads a file to the Templates library.
        Overwrites if a file with the same name already exists.

        Returns the Graph driveItem dict for the uploaded file.
        """
        return self._upload(self.template_drive_id, filename, content, context="template")

    # ------------------------------------------------------------------
    # Generated library
    # ------------------------------------------------------------------

    def list_generated(self) -> list[dict]:
        """
        Lists all files in the Generated library.
        Same return shape as list_templates().
        """
        url = f"{GRAPH_BASE}/drives/{self.generated_drive_id}/root/children"
        response = httpx.get(url, headers=_headers(), timeout=30)
        _raise_for_graph_error(response, context="listing generated docs")

        return [
            {
                "name": item["name"],
                "id": item["id"],
                "size": item.get("size", 0),
                "modified": item.get("lastModifiedDateTime"),
                "download_url": item.get("@microsoft.graph.downloadUrl"),
            }
            for item in response.json().get("value", [])
            if "file" in item
        ]

    def upload_generated(self, filename: str, content: bytes) -> dict:
        """
        Uploads a generated document to the Generated library.
        Overwrites if a file with the same name already exists.

        Returns the Graph driveItem dict for the uploaded file.
        """
        return self._upload(self.generated_drive_id, filename, content, context="generated doc")

    def download_generated(self, filename: str) -> bytes:
        """
        Downloads a previously generated document by name.
        Raises SharePointFileNotFoundError if not found.
        """
        self._ensure_initialised()
        encoded = quote(filename)
        url = f"{GRAPH_BASE}/drives/{self.generated_drive_id}/root:/{encoded}:/content"

        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {_get_graph_token()}"},
            follow_redirects=True,
            timeout=60,
        )
        if response.status_code == 404:
            raise SharePointFileNotFoundError(
                f"Generated file '{filename}' not found in the Generated library."
            )
        _raise_for_graph_error(response, context=f"downloading generated '{filename}'")
        return response.content

    # ------------------------------------------------------------------
    # Delete (works on either library)
    # ------------------------------------------------------------------

    def delete_template(self, filename: str) -> None:
        """Deletes a file from the Templates library by name."""
        self._delete(self.template_drive_id, filename)

    def delete_generated(self, filename: str) -> None:
        """Deletes a file from the Generated library by name."""
        self._delete(self.generated_drive_id, filename)

    # ------------------------------------------------------------------
    # Structure setup (called explicitly during agent bootstrap)
    # ------------------------------------------------------------------

    def ensure_structure(self) -> dict:
        """
        Ensures the Templates and Generated libraries exist on the site.
        Safe to call on every agent startup — is a no-op if already present.

        Returns a dict with the resolved IDs for logging/debugging:
          { site_id, template_drive_id, generated_drive_id, site_url }
        """
        self._ensure_initialised()
        return {
            "site_url": self.site_url,
            "site_id": self._site_id,
            "template_drive_id": self._template_drive_id,
            "generated_drive_id": self._generated_drive_id,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _upload(self, drive_id: str, filename: str, content: bytes, context: str) -> dict:
        """
        Uploads content to a drive using the Graph upload session API.
        Handles files of any size (uses simple PUT for <4MB, session for larger).
        """
        self._ensure_initialised()
        encoded = quote(filename)

        if len(content) < 4 * 1024 * 1024:
            # Simple upload for files under 4MB
            url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{encoded}:/content"
            response = httpx.put(
                url,
                headers={
                    "Authorization": f"Bearer {_get_graph_token()}",
                    "Content-Type": _mime_type(filename),
                },
                content=content,
                timeout=60,
            )
            _raise_for_graph_error(response, context=f"uploading {context} '{filename}'")
            logger.info("Uploaded %s '%s' (%d bytes)", context, filename, len(content))
            return response.json()

        else:
            # Upload session for larger files
            session_url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{encoded}:/createUploadSession"
            session_payload = {
                "item": {
                    "@microsoft.graph.conflictBehavior": "replace",
                    "name": filename,
                }
            }
            session_response = httpx.post(
                session_url,
                headers=_headers(),
                json=session_payload,
                timeout=30,
            )
            _raise_for_graph_error(session_response, context="creating upload session")
            upload_url = session_response.json()["uploadUrl"]

            # Upload in 4MB chunks
            chunk_size = 4 * 1024 * 1024
            total = len(content)
            offset = 0
            last_response = None

            while offset < total:
                chunk = content[offset: offset + chunk_size]
                end = offset + len(chunk) - 1
                upload_response = httpx.put(
                    upload_url,
                    headers={
                        "Content-Range": f"bytes {offset}-{end}/{total}",
                        "Content-Length": str(len(chunk)),
                    },
                    content=chunk,
                    timeout=60,
                )
                if upload_response.status_code not in (200, 201, 202):
                    _raise_for_graph_error(upload_response, context=f"chunk upload at offset {offset}")
                last_response = upload_response
                offset += len(chunk)
                logger.debug("Uploaded chunk %d-%d of %d", offset - len(chunk), end, total)

            logger.info("Uploaded large %s '%s' (%d bytes)", context, filename, total)
            return last_response.json()

    def _delete(self, drive_id: str, filename: str) -> None:
        self._ensure_initialised()
        encoded = quote(filename)
        url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{encoded}"
        response = httpx.delete(
            url,
            headers={"Authorization": f"Bearer {_get_graph_token()}"},
            timeout=30,
        )
        if response.status_code == 404:
            raise SharePointFileNotFoundError(f"File '{filename}' not found.")
        _raise_for_graph_error(response, context=f"deleting '{filename}'")
        logger.info("Deleted '%s' from drive %s", filename, drive_id)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SharePointError(Exception):
    """Base exception for SharePoint client errors."""
    pass


class SharePointFileNotFoundError(SharePointError):
    """Raised when a requested file does not exist in the library."""
    pass


class SharePointAuthError(SharePointError):
    """Raised when Graph authentication fails."""
    pass


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set. "
            "Ensure the Container App is configured correctly."
        )
    return value


def _raise_for_graph_error(response: httpx.Response, context: str = "") -> None:
    if response.status_code in (200, 201, 202, 204):
        return
    if response.status_code in (401, 403):
        raise SharePointAuthError(
            f"Graph authentication/permission error during {context}. "
            f"Status: {response.status_code}. "
            f"Ensure the SPN has Sites.ReadWrite.All on the customer tenant. "
            f"Detail: {response.text}"
        )
    if response.status_code == 404:
        raise SharePointFileNotFoundError(
            f"Resource not found during {context}. Detail: {response.text}"
        )
    raise SharePointError(
        f"Graph API error during {context}. "
        f"Status: {response.status_code}. Detail: {response.text}"
    )


def _mime_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pdf":  "application/pdf",
        "png":  "image/png",
        "jpg":  "image/jpeg",
        "jpeg": "image/jpeg",
        "txt":  "text/plain",
        "json": "application/json",
        "csv":  "text/csv",
    }.get(ext, "application/octet-stream")