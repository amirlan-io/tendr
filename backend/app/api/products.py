"""Product Search API: AI-подбор товаров через Tavily."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.product_search import ProductSearchAgent
from app.core.supabase_auth import SupabaseUser, require_supabase_user
from app.db import get_db
from app.schemas.lot import (
    DeepSearchRequest,
    DeepSearchResult,
    ProductSearchRequest,
    ProductSearchResult,
)

router = APIRouter(prefix="/products", tags=["products"])


@router.post("/search", response_model=ProductSearchResult)
async def search_products(
    payload: ProductSearchRequest,
    _auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
) -> ProductSearchResult:
    """Простой поиск товаров/услуг (по названию)."""
    agent = ProductSearchAgent()
    return await agent.run(payload)


@router.post("/deep-search", response_model=DeepSearchResult)
async def deep_search_products(
    payload: DeepSearchRequest,
    _auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: AsyncSession = Depends(get_db),
) -> DeepSearchResult:
    """Глубокий поиск: извлечение характеристик из ТЗ + Tavily + история цен.

    Отличие от /search:
    - Извлекает структурированные характеристики (размеры, материал, класс)
    - Генерирует более точные поисковые запросы на основе specs
    - Сравнивает найденные товары с историческими ценами из нашей БД
    - Предупреждает если цена сильно выше рынка
    """
    agent = ProductSearchAgent()
    return await agent.run_deep(payload, session=session)
