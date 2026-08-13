"""Google Drive API wrapper — search, list, move, upload, export, share."""

from __future__ import annotations

import io
import mimetypes
import re
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from .auth import get_credentials
from .utils import execute_with_retry

_service = None
_service_creds = None


def _get_service():
    global _service, _service_creds
    creds = get_credentials()
    if _service is None or creds is not _service_creds:
        _service = build("drive", "v3", credentials=creds)
        _service_creds = creds
    return _service


def search_files(
    query: str,
    mime_type: str | None = None,
    max_results: int = 20,
) -> list[dict]:
    service = _get_service()
    q_parts = []
    if mime_type:
        q_parts.append(f"mimeType='{mime_type}'")
    safe_query = query.replace("\\", "\\\\").replace("'", "\\'")
    q_parts.append(f"fullText contains '{safe_query}'")
    q_parts.append("trashed=false")
    q = " and ".join(q_parts)

    max_results = min(max_results, 1000)
    all_files: list[dict] = []
    page_token = None
    prev_count = -1
    while len(all_files) < max_results:
        if len(all_files) == prev_count:
            break
        prev_count = len(all_files)
        page_size = min(max_results - len(all_files), 100)
        results = execute_with_retry(
            service.files().list(
                q=q,
                pageSize=page_size,
                pageToken=page_token,
                fields="nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink)",
                orderBy="modifiedTime desc",
            )
        )
        for f in results.get("files", []):
            all_files.append({
                "id": f["id"],
                "name": f["name"],
                "mime_type": f["mimeType"],
                "modified": f.get("modifiedTime", ""),
                "url": f.get("webViewLink", ""),
            })
        page_token = results.get("nextPageToken")
        if not page_token:
            break
    return all_files[:max_results]


def list_folder(
    folder_id: str | None = None,
    max_results: int = 50,
) -> list[dict]:
    service = _get_service()
    q_parts = ["trashed=false"]
    if folder_id:
        q_parts.append(f"'{folder_id}' in parents")
    else:
        q_parts.append("'root' in parents")
    q = " and ".join(q_parts)

    max_results = min(max_results, 1000)
    all_files: list[dict] = []
    page_token = None
    prev_count = -1
    while len(all_files) < max_results:
        if len(all_files) == prev_count:
            break
        prev_count = len(all_files)
        page_size = min(max_results - len(all_files), 100)
        results = execute_with_retry(
            service.files().list(
                q=q,
                pageSize=page_size,
                pageToken=page_token,
                fields="nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink)",
                orderBy="name",
            )
        )
        for f in results.get("files", []):
            all_files.append({
                "id": f["id"],
                "name": f["name"],
                "mime_type": f["mimeType"],
                "modified": f.get("modifiedTime", ""),
                "url": f.get("webViewLink", ""),
            })
        page_token = results.get("nextPageToken")
        if not page_token:
            break
    return all_files[:max_results]


def move_file(file_id: str, folder_id: str) -> dict:
    service = _get_service()
    file = execute_with_retry(service.files().get(fileId=file_id, fields="parents"))
    previous_parents = ",".join(file.get("parents", []))
    updated = execute_with_retry(
        service.files().update(
            fileId=file_id,
            addParents=folder_id,
            removeParents=previous_parents,
            fields="id,name,parents,webViewLink",
        )
    )
    return {
        "id": updated["id"],
        "name": updated["name"],
        "new_parent": folder_id,
        "url": updated.get("webViewLink", ""),
    }


def create_in_folder(file_id: str, folder_id: str) -> dict:
    """Move a newly created doc into a specific folder."""
    return move_file(file_id, folder_id)


def trash_file(file_id: str) -> dict:
    """Move a file to trash (recoverable — not permanent delete)."""
    service = _get_service()
    file_info = execute_with_retry(
        service.files().get(fileId=file_id, fields="id,name")
    )
    execute_with_retry(
        service.files().update(fileId=file_id, body={"trashed": True})
    )
    return {"id": file_info["id"], "name": file_info["name"], "trashed": True}


def get_file_info(file_id: str) -> dict:
    """Get file metadata — name, type, size, owner, sharing status."""
    service = _get_service()
    f = execute_with_retry(
        service.files().get(
            fileId=file_id,
            fields="id,name,mimeType,size,createdTime,modifiedTime,owners,shared,webViewLink,parents,trashed",
        )
    )
    owners = [o.get("emailAddress", o.get("displayName", "")) for o in f.get("owners", [])]
    return {
        "id": f["id"],
        "name": f["name"],
        "mime_type": f["mimeType"],
        "size": f.get("size"),
        "created": f.get("createdTime", ""),
        "modified": f.get("modifiedTime", ""),
        "owners": owners,
        "shared": f.get("shared", False),
        "trashed": f.get("trashed", False),
        "url": f.get("webViewLink", ""),
        "parents": f.get("parents", []),
    }


def create_folder(name: str, parent_id: str | None = None) -> dict:
    """Create a folder in Drive."""
    service = _get_service()
    metadata: dict = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]
    folder = execute_with_retry(
        service.files().create(body=metadata, fields="id,name,webViewLink")
    )
    return {"id": folder["id"], "name": folder["name"], "url": folder.get("webViewLink", "")}


def rename_file(file_id: str, new_name: str) -> dict:
    """Rename a file or folder."""
    service = _get_service()
    updated = execute_with_retry(
        service.files().update(
            fileId=file_id,
            body={"name": new_name},
            fields="id,name,webViewLink",
        )
    )
    return {"id": updated["id"], "name": updated["name"], "url": updated.get("webViewLink", "")}


def copy_file(file_id: str, name: str | None = None, folder_id: str | None = None) -> dict:
    """Copy a file (useful for template workflows)."""
    service = _get_service()
    body: dict = {}
    if name:
        body["name"] = name
    if folder_id:
        body["parents"] = [folder_id]
    copied = execute_with_retry(
        service.files().copy(fileId=file_id, body=body, fields="id,name,webViewLink")
    )
    return {"id": copied["id"], "name": copied["name"], "url": copied.get("webViewLink", "")}


def upload_file(
    local_path: str,
    name: str | None = None,
    folder_id: str | None = None,
    mime_type: str | None = None,
) -> dict:
    """Upload a local file to Drive."""
    service = _get_service()
    path = Path(local_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {local_path}")

    if not mime_type:
        mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"

    metadata: dict = {"name": name or path.name}
    if folder_id:
        metadata["parents"] = [folder_id]

    media = MediaFileUpload(str(path), mimetype=mime_type, resumable=True)
    uploaded = execute_with_retry(
        service.files().create(
            body=metadata,
            media_body=media,
            fields="id,name,mimeType,webViewLink",
        )
    )
    return {
        "id": uploaded["id"],
        "name": uploaded["name"],
        "mime_type": uploaded["mimeType"],
        "url": uploaded.get("webViewLink", ""),
    }


EXPORT_FORMATS = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "txt": "text/plain",
    "rtf": "application/rtf",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "epub": "application/epub+zip",
    "md": "text/markdown",
    "png": "image/png",
    "jpg": "image/jpeg",
    "svg": "image/svg+xml",
}


def export_file(file_id: str, format: str, output_path: str | None = None) -> dict:
    """Export a Google Workspace file to a local format. Max 10MB."""
    service = _get_service()
    mime_type = EXPORT_FORMATS.get(format.lower())
    if not mime_type:
        raise ValueError(f"Unknown format '{format}'. Supported: {', '.join(sorted(EXPORT_FORMATS))}")

    request = service.files().export_media(fileId=file_id, mimeType=mime_type)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    if not output_path:
        file_info = execute_with_retry(service.files().get(fileId=file_id, fields="name"))
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', Path(file_info["name"]).stem)
        output_path = f"{stem}.{format.lower()}"

    buffer.seek(0)
    Path(output_path).write_bytes(buffer.read())
    size = Path(output_path).stat().st_size

    return {"path": str(Path(output_path).resolve()), "format": format, "size": size}


def share_file(
    file_id: str,
    email: str | None = None,
    role: str = "reader",
    anyone: bool = False,
    notify: bool = True,
) -> dict:
    """Share a file with a user or make it public."""
    service = _get_service()
    if anyone:
        permission = {"type": "anyone", "role": role}
    elif email:
        permission = {"type": "user", "role": role, "emailAddress": email}
    else:
        raise ValueError("Provide either email or set anyone=True")

    result = execute_with_retry(
        service.permissions().create(
            fileId=file_id,
            body=permission,
            sendNotificationEmail=notify and bool(email),
            fields="id",
        )
    )

    file_meta = execute_with_retry(
        service.files().get(fileId=file_id, fields="webViewLink")
    )
    return {
        "permission_id": result["id"],
        "role": role,
        "shared_with": email or "anyone",
        "url": file_meta.get("webViewLink", ""),
    }


def unshare_file(file_id: str, permission_id: str) -> dict:
    """Revoke a sharing permission."""
    service = _get_service()
    execute_with_retry(
        service.permissions().delete(fileId=file_id, permissionId=permission_id)
    )
    return {"revoked": permission_id}


def list_permissions(file_id: str) -> list[dict]:
    """List all sharing permissions on a file."""
    service = _get_service()
    result = execute_with_retry(
        service.permissions().list(
            fileId=file_id,
            fields="permissions(id,type,role,emailAddress,displayName)",
        )
    )
    return [
        {
            "id": p["id"],
            "type": p.get("type", ""),
            "role": p.get("role", ""),
            "email": p.get("emailAddress", ""),
            "name": p.get("displayName", ""),
        }
        for p in result.get("permissions", [])
    ]
