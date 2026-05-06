"""Google Drive API wrapper — search, list, move, export."""

from __future__ import annotations

from googleapiclient.discovery import build

from .auth import get_credentials
from .utils import execute_with_retry

_service = None


def _get_service():
    global _service
    if _service is None:
        creds = get_credentials()
        _service = build("drive", "v3", credentials=creds)
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

    results = execute_with_retry(
        service.files().list(
            q=q,
            pageSize=max_results,
            fields="files(id,name,mimeType,modifiedTime,webViewLink)",
            orderBy="modifiedTime desc",
        )
    )
    return [
        {
            "id": f["id"],
            "name": f["name"],
            "mime_type": f["mimeType"],
            "modified": f.get("modifiedTime", ""),
            "url": f.get("webViewLink", ""),
        }
        for f in results.get("files", [])
    ]


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

    results = execute_with_retry(
        service.files().list(
            q=q,
            pageSize=max_results,
            fields="files(id,name,mimeType,modifiedTime,webViewLink)",
            orderBy="name",
        )
    )
    return [
        {
            "id": f["id"],
            "name": f["name"],
            "mime_type": f["mimeType"],
            "modified": f.get("modifiedTime", ""),
            "url": f.get("webViewLink", ""),
        }
        for f in results.get("files", [])
    ]


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
