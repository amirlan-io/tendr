"""B2G API: workspace'ы заказчиков, версии ТЗ, multi-user, DOCX-экспорт."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.b2g import B2GAgent
from app.core.client_id import require_client_id
from app.db import get_db
from app.db import repo as db_repo
from app.db.models import (
    Analysis,
    B2GMember,
    B2GTzDraft,
    B2GWorkspace,
    User,
)
from app.services.doc_generator import generate_tz_docx, generate_tz_pdf

router = APIRouter(prefix="/b2g", tags=["b2g"])


# ───── Helpers ─────


async def _user_for_request(session: AsyncSession, request: Request) -> User:
    """Резолвим юзера по X-Client-Id (cookie).

    This is not a full authorization mechanism; in production a server-side
    session should be used instead.
    """
    cid = await require_client_id(request)
    stmt = select(User).where(User.web_client_id == cid)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user:
        user = User(web_client_id=cid)
        session.add(user)
        await session.flush()
    return user


async def _check_access(
    session: AsyncSession, workspace_id: int, user_id: int, required: str = "viewer"
) -> tuple[B2GWorkspace, str]:
    """Проверяет доступ юзера к workspace.

    required: viewer / editor / owner
    Возвращает (workspace, role).
    """
    ws = await session.get(B2GWorkspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace не найден")
    if ws.owner_id == user_id:
        return ws, "owner"
    stmt = select(B2GMember).where(
        B2GMember.workspace_id == workspace_id, B2GMember.user_id == user_id
    )
    member = (await session.execute(stmt)).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=403, detail="Нет доступа к workspace")
    # Проверяем уровень доступа
    role_hierarchy = {"viewer": 1, "editor": 2, "owner": 3}
    if role_hierarchy.get(member.role, 0) < role_hierarchy[required]:
        raise HTTPException(
            status_code=403,
            detail=f"Требуется роль {required}, у вас {member.role}",
        )
    return ws, member.role


# ───── Workspace endpoints ─────


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(..., description="Название workspace")
    organization: str | None = None
    organization_bin: str | None = None
    region: str | None = None


@router.post("/workspaces")
async def create_workspace(
    payload: CreateWorkspaceRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Создать новый workspace для заказчика."""
    user = await _user_for_request(session, request)
    ws = B2GWorkspace(
        owner_id=user.id,
        name=payload.name,
        organization=payload.organization,
        organization_bin=payload.organization_bin,
        region=payload.region,
    )
    session.add(ws)
    await session.flush()
    return {
        "id": ws.id,
        "name": ws.name,
        "organization": ws.organization,
        "role": "owner",
    }


@router.get("/workspaces")
async def list_workspaces(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Список workspace'ов текущего юзера (где он owner или member)."""
    user = await _user_for_request(session, request)
    # owner'ы
    owned = (
        (await session.execute(select(B2GWorkspace).where(B2GWorkspace.owner_id == user.id)))
        .scalars()
        .all()
    )
    # member'ы
    member_stmt = select(B2GWorkspace).join(B2GMember).where(B2GMember.user_id == user.id)
    member_ws = (await session.execute(member_stmt)).scalars().all()

    items = []
    for ws in list(owned) + list(member_ws):
        role = "owner" if ws.owner_id == user.id else "member"
        # Количество черновиков
        cnt = (
            await session.execute(
                select(func.count(B2GTzDraft.id)).where(B2GTzDraft.workspace_id == ws.id)
            )
        ).scalar_one() or 0
        items.append(
            {
                "id": ws.id,
                "name": ws.name,
                "organization": ws.organization,
                "region": ws.region,
                "role": role,
                "tz_drafts_count": cnt,
                "created_at": ws.created_at.isoformat(),
            }
        )
    return {"items": items}


# ───── Members endpoints ─────


class AddMemberRequest(BaseModel):
    user_id: int = Field(..., description="ID юзера (web_client_id-based)")
    role: str = Field(default="editor", pattern="^(editor|viewer)$")


@router.post("/workspaces/{ws_id}/members")
async def add_member(
    ws_id: int,
    payload: AddMemberRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Добавить участника в workspace. Только owner."""
    user = await _user_for_request(session, request)
    await _check_access(session, ws_id, user.id, "owner")

    # user_id здесь — это ID из таблицы users (можно найти по web_client_id)
    target = await session.get(User, payload.user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    existing = (
        await session.execute(
            select(B2GMember).where(
                B2GMember.workspace_id == ws_id, B2GMember.user_id == payload.user_id
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.role = payload.role
    else:
        session.add(B2GMember(workspace_id=ws_id, user_id=payload.user_id, role=payload.role))
    return {"ok": True, "user_id": payload.user_id, "role": payload.role}


@router.get("/workspaces/{ws_id}/members")
async def list_members(
    ws_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Список участников workspace."""
    user = await _user_for_request(session, request)
    await _check_access(session, ws_id, user.id, "viewer")

    ws = await session.get(B2GWorkspace, ws_id)
    owner = await session.get(User, ws.owner_id)
    members = (
        (await session.execute(select(B2GMember).where(B2GMember.workspace_id == ws_id)))
        .scalars()
        .all()
    )
    items = []
    if owner:
        items.append(
            {
                "user_id": owner.id,
                "client_id": owner.web_client_id,
                "role": "owner",
            }
        )
    for m in members:
        u = await session.get(User, m.user_id)
        items.append(
            {
                "user_id": m.user_id,
                "client_id": u.web_client_id if u else None,
                "role": m.role,
            }
        )
    return {"items": items}


# ───── TZ draft endpoints (с версионированием) ─────


class CreateTzRequest(BaseModel):
    need_description: str = Field(..., description="Описание потребности")
    category: str | None = None
    region: str | None = None
    version_note: str | None = Field(
        default=None,
        description="Комментарий к версии (например, 'с учётом пожеланий бухгалтера')",
    )


@router.post("/workspaces/{ws_id}/generate")
async def generate_tz(
    ws_id: int,
    payload: CreateTzRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Сгенерировать новую версию ТЗ в workspace."""
    user = await _user_for_request(session, request)
    await _check_access(session, ws_id, user.id, "editor")
    ws = await session.get(B2GWorkspace, ws_id)

    # Поиск похожих лотов в БД
    keywords = payload.need_description.split()[:3]
    like_pattern = f"%{keywords[0]}%" if keywords else "%%"
    stmt = (
        select(Analysis)
        .where(Analysis.title.ilike(like_pattern))
        .where(Analysis.budget_kzt.is_not(None))
        .order_by(Analysis.created_at.desc())
        .limit(5)
    )
    rows = (await session.execute(stmt)).scalars().all()
    similar_lots = [
        {"title": r.title, "budget_kzt": r.budget_kzt, "customer": r.customer} for r in rows
    ]

    # Запускаем B2G Agent
    from app.schemas.lot import B2GRequest

    agent = B2GAgent()
    b2g_req = B2GRequest(
        need_description=payload.need_description,
        category=payload.category,
        region=payload.region or ws.region,
        organization=ws.organization,
        similar_lots=similar_lots,
    )
    result = await agent.run(b2g_req, lot_id=f"ws{ws_id}")

    # Считаем номер версии
    max_version = (
        await session.execute(
            select(func.max(B2GTzDraft.version)).where(B2GTzDraft.workspace_id == ws_id)
        )
    ).scalar_one() or 0

    # Сохраняем как новую версию
    draft = B2GTzDraft(
        workspace_id=ws_id,
        version=max_version + 1,
        author_id=user.id,
        need_description=payload.need_description,
        category=payload.category,
        region=payload.region or ws.region,
        tz_data=result.model_dump(mode="json"),
        legal_compliance=result.legal_compliance,
        red_flags_count=len(result.red_flags or []),
        warnings_count=len(result.warnings or []),
        version_note=payload.version_note,
    )
    session.add(draft)
    await session.flush()
    return {
        "version": draft.version,
        "id": draft.id,
        "tz_data": result.model_dump(mode="json"),
        "created_at": draft.created_at.isoformat(),
    }


@router.get("/workspaces/{ws_id}/drafts")
async def list_drafts(
    ws_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Список черновиков (версий) ТЗ в workspace, новые сверху."""
    user = await _user_for_request(session, request)
    await _check_access(session, ws_id, user.id, "viewer")
    rows = (
        (
            await session.execute(
                select(B2GTzDraft)
                .where(B2GTzDraft.workspace_id == ws_id)
                .order_by(B2GTzDraft.version.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": d.id,
                "version": d.version,
                "title": (d.tz_data or {}).get("title", ""),
                "author_id": d.author_id,
                "legal_compliance": d.legal_compliance,
                "red_flags_count": d.red_flags_count,
                "warnings_count": d.warnings_count,
                "version_note": d.version_note,
                "created_at": d.created_at.isoformat(),
            }
            for d in rows
        ]
    }


@router.get("/workspaces/{ws_id}/drafts/{version}")
async def get_draft(
    ws_id: int,
    version: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Получить конкретную версию ТЗ."""
    user = await _user_for_request(session, request)
    await _check_access(session, ws_id, user.id, "viewer")
    draft = (
        (
            await session.execute(
                select(B2GTzDraft).where(
                    B2GTzDraft.workspace_id == ws_id,
                    B2GTzDraft.version == version,
                )
            )
        )
        .scalars()
        .first()
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Версия не найдена")
    return {
        "id": draft.id,
        "version": draft.version,
        "tz_data": draft.tz_data,
        "version_note": draft.version_note,
        "created_at": draft.created_at.isoformat(),
    }


@router.get("/workspaces/{ws_id}/drafts/{version}/download")
async def download_draft_docx(
    ws_id: int,
    version: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Скачать DOCX-версию ТЗ."""
    user = await _user_for_request(session, request)
    await _check_access(session, ws_id, user.id, "viewer")
    draft = (
        (
            await session.execute(
                select(B2GTzDraft).where(
                    B2GTzDraft.workspace_id == ws_id,
                    B2GTzDraft.version == version,
                )
            )
        )
        .scalars()
        .first()
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Версия не найдена")
    ws = await session.get(B2GWorkspace, ws_id)
    content = generate_tz_docx(
        draft.tz_data,
        organization=ws.organization,
        organization_bin=ws.organization_bin,
    )
    title = (draft.tz_data or {}).get("title", "tz").replace(" ", "_")[:40]
    # Используем ASCII-only filename + UTF-8 через filename*
    safe_filename = f"tz_v{version}.docx"
    utf8_filename = f"tz_v{version}_{title}.docx".encode("utf-8").decode(
        "latin-1", errors="replace"
    )
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{safe_filename}\"; filename*=UTF-8''{utf8_filename}"
            )
        },
    )


@router.get("/workspaces/{ws_id}/drafts/{version}/download-pdf")
async def download_draft_pdf(
    ws_id: int,
    version: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Скачать PDF-версию ТЗ."""
    user = await _user_for_request(session, request)
    await _check_access(session, ws_id, user.id, "viewer")
    draft = (
        (
            await session.execute(
                select(B2GTzDraft).where(
                    B2GTzDraft.workspace_id == ws_id,
                    B2GTzDraft.version == version,
                )
            )
        )
        .scalars()
        .first()
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Версия не найдена")
    ws = await session.get(B2GWorkspace, ws_id)
    content = generate_tz_pdf(
        draft.tz_data,
        organization=ws.organization,
        organization_bin=ws.organization_bin,
    )
    title = (draft.tz_data or {}).get("title", "tz").replace(" ", "_")[:40]
    safe_filename = f"tz_v{version}.pdf"
    utf8_filename = f"tz_v{version}_{title}.pdf".encode("utf-8").decode("latin-1", errors="replace")
    return StreamingResponse(
        iter([content]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{safe_filename}\"; filename*=UTF-8''{utf8_filename}"
            )
        },
    )
