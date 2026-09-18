"""Парсеры лотов с разных площадок РК.

Поддерживаемые источники:
- zakup_gov (zakup.gov.kz / goszakup.gov.kz) — основной, через OpenAPI токен
- ets_tender (ets-tender.kz) — коммерческие торги
- samruk (samruk-astana.kz) — закупки Самрук-Казына
- tizilim — площадка Tizilim
- erg — Евразийская Группа

Использует GraphQL endpoint (рекомендуется) или REST API v2.
"""
from .parser import LotParser, ParsedLot
from .aggregator import LotAggregator
from .analyzer import LotAnalyzer
from .graphql_client import GraphQLClient

__all__ = [
    "LotParser",
    "ParsedLot",
    "LotAggregator",
    "LotAnalyzer",
    "GraphQLClient",
]
