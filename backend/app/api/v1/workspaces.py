"""Workspace REST endpoints conforming to Phase 3 contracts."""

from typing import Optional, List, Dict, Any
from uuid import UUID
from fastapi import APIRouter, UploadFile, File, Form, Header, HTTPException, status, Depends
from backend.app.core.auth import AuthenticatedUserContext, get_authenticated_user
from pydantic import BaseModel
from backend.app.models.workspace import Workspace, StagingWorkspace, EnvironmentMode
from backend.app.services.workspace_service import (
    WorkspaceService,
    WorkspaceNotFoundError,
    WorkspaceAccessDeniedError,
)
from backend.app.services.staging_service import StagingService
from backend.app.services.zip_import import ZipValidationError
from backend.app.analysis.service import CodebaseAnalysisService
from backend.app.analysis.types import (
    CodebaseAnalysisResult,
    DetectedTechnology,
    DependencyGraph,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
workspace_service = WorkspaceService()
staging_service = StagingService(workspace_service=workspace_service)
analysis_service = CodebaseAnalysisService(workspace_service=workspace_service)

# Default dev user fallback if no auth token/header is supplied
DEFAULT_DEV_USER_ID = UUID("00000000-0000-0000-0000-000000000001")



def resolve_user_id(x_user_id: Optional[str] = None) -> UUID:
    """Resolve legacy development identity; production requires bearer auth."""
    from backend.app.core.config import get_settings
    if get_settings().ENVIRONMENT == "production":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token authentication is required for workspace APIs.",
        )
    if x_user_id:
        try:
            return UUID(x_user_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid x-user-id header format; must be UUID.",
            )
    return DEFAULT_DEV_USER_ID


class FileContentResponse(BaseModel):
    path: str
    content: str
    size_bytes: int
    is_binary: bool = False


@router.post("", response_model=Workspace, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    name: str = Form(..., description="Workspace project name"),
    description: Optional[str] = Form(None, description="Optional description"),
    environment_mode: EnvironmentMode = Form(EnvironmentMode.SANDBOXED),
    file: Optional[UploadFile] = File(None, description="Optional project ZIP file"),
    x_user_id: Optional[str] = Header(None),
    auth: AuthenticatedUserContext = Depends(get_authenticated_user),
):
    """
    Provision a new approved workspace.
    Supports empty workspace creation or safe ZIP archive ingestion.
    """
    user_id = auth.user_id

    zip_bytes = None
    if file:
        if not file.filename or not file.filename.lower().endswith(".zip"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file type. Only .zip archives are supported.",
            )
        zip_bytes = await file.read()

    try:
        ws = await workspace_service.create_workspace(
            user_id=user_id,
            name=name,
            description=description,
            environment_mode=environment_mode,
            zip_bytes=zip_bytes,
        )
        if zip_bytes:
            # Deterministically analyze imported codebase (best-effort; import already succeeded)
            try:
                await analysis_service.analyze_workspace(ws.id, user_id)
            except Exception:
                pass
        return ws
    except ZipValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ZIP Validation Error: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workspace provisioning failed: {str(e)}",
        )


@router.get("", response_model=List[Workspace])
async def list_workspaces(x_user_id: Optional[str] = Header(None), auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    """List all workspaces owned by the authenticated user."""
    user_id = auth.user_id
    return await workspace_service.list_user_workspaces(user_id)


@router.get("/{workspace_id}", response_model=Workspace)
async def get_workspace(workspace_id: UUID, x_user_id: Optional[str] = Header(None), auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    """Fetch details of an approved workspace."""
    user_id = auth.user_id
    try:
        return await workspace_service.get_workspace(workspace_id, user_id)
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    except WorkspaceAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.get("/{workspace_id}/files", response_model=List[Dict[str, Any]])
async def list_workspace_files(workspace_id: UUID, x_user_id: Optional[str] = Header(None), auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    """List all files tracked within the approved workspace."""
    user_id = auth.user_id
    try:
        return await workspace_service.list_workspace_files(workspace_id, user_id)
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    except WorkspaceAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.get("/{workspace_id}/files/content", response_model=FileContentResponse)
async def read_workspace_file_content(
    workspace_id: UUID, path: str, x_user_id: Optional[str] = Header(None),
    auth: AuthenticatedUserContext = Depends(get_authenticated_user),
):
    """
    Read file contents from the approved canonical storage.
    Strictly read-only; browser-side direct writes are forbidden.
    """
    user_id = auth.user_id
    try:
        raw_bytes = await workspace_service.read_workspace_file(workspace_id, path, user_id)
        try:
            text_content = raw_bytes.decode("utf-8")
            is_bin = False
        except UnicodeDecodeError:
            text_content = "[Binary file content - cannot display in text viewer]"
            is_bin = True

        return FileContentResponse(
            path=path,
            content=text_content,
            size_bytes=len(raw_bytes),
            is_binary=is_bin,
        )
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    except WorkspaceAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File '{path}' not found.")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to read file: {str(e)}",
        )


@router.post("/{workspace_id}/import/zip", response_model=Workspace)
async def import_project_zip(
    workspace_id: UUID,
    file: UploadFile = File(..., description="Project ZIP archive"),
    auth: AuthenticatedUserContext = Depends(get_authenticated_user),
):
    """Import a ZIP into an empty owned workspace. Refuses non-empty approved trees."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .zip archives are supported.")
    zip_bytes = await file.read()
    try:
        ws = await workspace_service.import_project_into_empty_workspace(
            workspace_id, auth.user_id, zip_bytes=zip_bytes
        )
        try:
            await analysis_service.analyze_workspace(ws.id, auth.user_id)
        except Exception:
            pass
        return ws
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    except WorkspaceAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    except ZipValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{workspace_id}/import/files", response_model=Workspace)
async def import_project_files(
    workspace_id: UUID,
    files: List[UploadFile] = File(..., description="Project files"),
    paths: List[str] = Form(..., description="Relative paths aligned with files"),
    auth: AuthenticatedUserContext = Depends(get_authenticated_user),
):
    """Import loose files/folders into an empty owned workspace with path validation."""
    if len(files) != len(paths):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="files and paths must have the same length.")
    payload: List[Dict[str, Any]] = []
    for upload, relative_path in zip(files, paths):
        payload.append({
            "relative_path": relative_path,
            "content": await upload.read(),
        })
    try:
        ws = await workspace_service.import_project_into_empty_workspace(
            workspace_id, auth.user_id, files=payload
        )
        try:
            await analysis_service.analyze_workspace(ws.id, auth.user_id)
        except Exception:
            pass
        return ws
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    except WorkspaceAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    except ZipValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{workspace_id}/staging", response_model=StagingWorkspace, status_code=status.HTTP_201_CREATED)
async def create_staging_workspace(workspace_id: UUID, x_user_id: Optional[str] = Header(None), auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    """
    Provision an isolated ephemeral staging workspace cloned from canonical approved state.
    Infrastructure endpoint for future agent integration.
    """
    user_id = auth.user_id
    try:
        return await staging_service.create_staging_workspace(workspace_id, user_id)
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    except WorkspaceAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.delete("/{workspace_id}/staging/{staging_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_staging_workspace(
    workspace_id: UUID, staging_id: UUID, x_user_id: Optional[str] = Header(None),
    auth: AuthenticatedUserContext = Depends(get_authenticated_user),
):
    """Discard an ephemeral staging workspace."""
    user_id = auth.user_id
    try:
        await staging_service.discard_staging_workspace(staging_id, user_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staging workspace not found.")
    except WorkspaceAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.post("/{workspace_id}/analysis", response_model=CodebaseAnalysisResult)
async def trigger_workspace_analysis(
    workspace_id: UUID,
    force: bool = False,
    x_user_id: Optional[str] = Header(None),
    auth: AuthenticatedUserContext = Depends(get_authenticated_user),
):
    """
    Trigger deterministic codebase analysis on an approved workspace.
    Statically analyzes project files, languages, technologies, dependencies,
    entry points, and builds the dependency graph without code execution or LLMs.
    """
    user_id = auth.user_id
    try:
        return await analysis_service.analyze_workspace(workspace_id, user_id, force=force)
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    except WorkspaceAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {str(e)}",
        )


@router.get("/{workspace_id}/analysis", response_model=CodebaseAnalysisResult)
async def get_workspace_analysis(
    workspace_id: UUID,
    x_user_id: Optional[str] = Header(None),
    auth: AuthenticatedUserContext = Depends(get_authenticated_user),
):
    """Fetch the latest codebase analysis for an approved workspace."""
    user_id = auth.user_id
    try:
        res = await analysis_service.get_latest_analysis(workspace_id, user_id)
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No analysis found for this workspace. Trigger analysis first.",
            )
        return res
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    except WorkspaceAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.get("/{workspace_id}/analysis/summary")
async def get_workspace_analysis_summary(
    workspace_id: UUID,
    x_user_id: Optional[str] = Header(None),
    auth: AuthenticatedUserContext = Depends(get_authenticated_user),
):
    """Fetch the project architectural summary only."""
    user_id = auth.user_id
    try:
        res = await analysis_service.get_latest_analysis(workspace_id, user_id)
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No analysis found for this workspace. Trigger analysis first.",
            )
        return {
            "workspace_id": str(workspace_id),
            "status": res.status,
            "architecture_overview": res.architecture_overview,
            "summary": res.summary,
            "primary_languages": res.primary_languages,
            "frameworks_detected": res.frameworks_detected,
            "total_files": len(res.indexed_files),
            "warnings": res.warnings,
            "analysis_version": res.analysis_version,
            "created_at": res.created_at,
        }
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    except WorkspaceAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.get("/{workspace_id}/analysis/graph", response_model=DependencyGraph)
async def get_workspace_analysis_graph(
    workspace_id: UUID,
    x_user_id: Optional[str] = Header(None),
    auth: AuthenticatedUserContext = Depends(get_authenticated_user),
):
    """Fetch the internal and external dependency graph."""
    user_id = auth.user_id
    try:
        res = await analysis_service.get_latest_analysis(workspace_id, user_id)
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No analysis found for this workspace. Trigger analysis first.",
            )
        return res.dependency_graph
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    except WorkspaceAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.get("/{workspace_id}/analysis/technologies", response_model=List[DetectedTechnology])
async def get_workspace_analysis_technologies(
    workspace_id: UUID,
    x_user_id: Optional[str] = Header(None),
    auth: AuthenticatedUserContext = Depends(get_authenticated_user),
):
    """Fetch detected technologies with evidence and confidence scores."""
    user_id = auth.user_id
    try:
        res = await analysis_service.get_latest_analysis(workspace_id, user_id)
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No analysis found for this workspace. Trigger analysis first.",
            )
        return res.technologies
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    except WorkspaceAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
