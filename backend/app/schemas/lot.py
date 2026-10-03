"""Pydantic схемы для лотов, заявок, маржи и партнёрств."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_serializer, model_validator

# ═════ Lot (тендер) — для каталога ═════


class LotItem(BaseModel):
    """Один лот (тендер) для отображения в каталоге."""

    id: int = Field(..., description="Внутренний ID")
    source: str = Field(..., description="Источник: zakup_gov, ets_tender, samruk, ...")
    source_id: str = Field(..., description="ID на источнике")
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    procurement_method: Optional[str] = None
    platform: Optional[str] = None
    amount_kzt: Optional[float] = None
    price_per_unit: Optional[float] = None
    region: Optional[str] = None
    delivery_address: Optional[str] = None
    publish_date: Optional[datetime] = None
    deadline_date: Optional[datetime] = None
    organizer: Optional[str] = None
    organizer_bin: Optional[str] = None
    customer_bin: Optional[str] = None
    status: str = "published"
    source_url: Optional[str] = None

    # AI-метаданные
    ai_summary: Optional[str] = None
    ai_red_flags: list[str] = []
    ai_match_score: Optional[int] = None
    ref_trade_methods_id: Optional[int] = None  # id способа закупки из API
    ref_buy_status_id: Optional[int] = None  # id статуса объявления

    # Служебное
    days_until_deadline: Optional[int] = None
    is_urgent: bool = False  # < 3 дней
    deadline_time_str: Optional[str] = None  # "сегодня 18:00", "завтра 14:00" и т.д.


class LotSearchRequest(BaseModel):
    """Запрос на поиск лотов."""

    query: str = Field(default="", description="Ключевые слова")
    region: str = Field(default="", description="Регион (пусто = все)")
    platform: str = Field(default="", description="Площадка (пусто = все)")
    category: Literal["", "товар", "работа", "услуга"] = Field(default="")
    procurement_method: str = Field(default="")
    procurement_method_ids: list[int] = Field(
        default_factory=list,
        description="Официальные ID способов закупки из V3",
    )
    customer_bin: str = Field(
        default="",
        max_length=12,
        description="БИН заказчика (12 цифр) — фильтр по конкретному заказчику",
    )
    customer_bin_like: str = Field(
        default="",
        description="Часть БИН/названия заказчика (поиск по подстроке)",
    )
    min_amount_kzt: float = Field(default=0)
    max_amount_kzt: float = Field(default=0)
    status: Literal["active", "published", "offers", "archive", "all"] = Field(
        default="active",
        description="По умолчанию только лоты, в которых ещё можно участвовать",
    )
    published_from: date | None = Field(default=None, description="Дата публикации от")
    published_to: date | None = Field(default=None, description="Дата публикации до")
    only_urgent: bool = Field(default=False, description="Только < 3 дней до дедлайна")
    only_with_amount: bool = Field(
        default=False, description="Только лоты с указанной суммой"
    )
    use_graphql: bool = Field(
        default=True,
        description="Использовать GraphQL endpoint (быстрее, гибче чем REST)",
    )
    with_ai: bool = Field(
        default=False,
        description="Запустить AI-анализ (Documenter+Legal). По умолчанию OFF — занимает 30-60 сек на лот.",
    )
    ai_limit: int = Field(
        default=3,
        ge=0,
        le=20,
        description="Сколько первых лотов анализировать через AI.",
    )
    limit: int = Field(default=50, ge=1, le=200)
    cursor: int | None = Field(default=None, ge=1, description="Курсор V3 для следующей страницы")


class LotSearchResult(BaseModel):
    """Результат поиска лотов."""

    lots: list[LotItem]
    total: int
    source: str  # "zakup.gov.kz" или "mock"
    is_mock: bool = False  # True если данные демо (пока нет реального токена)
    next_cursor: int | None = None
    has_more: bool = False
    total_is_exact: bool = True
    fetched_at: datetime | None = None
    last_updated_at: datetime | None = None
    scope: Literal["active", "published", "offers", "archive", "all"] = "active"


class PartnershipRequest(BaseModel):
    """Заявка на партнёрство (B2B matchmaking)."""

    role: Literal["supplier", "investor", "applicant", "partner"] = Field(
        ...,
        description=(
            "supplier: могу поставить товар/услугу; "
            "investor: могу профинансировать; "
            "applicant: хочу подать заявку; "
            "partner: готов к любой форме сотрудничества"
        ),
    )
    message: Optional[str] = Field(default=None, max_length=1000)
    contact: Optional[str] = Field(default=None, max_length=256, description="Email или телефон")


class PartnershipResponse(BaseModel):
    """Ответ на заявку партнёрства."""

    id: int
    lot_id: int
    role: str
    status: str
    created_at: datetime


# ═════ Legacy / Existing: Documenter, margin, application ═════


class ProductItem(BaseModel):
    """Один найденный товар (для ProductSearch)."""

    name: str
    price_kzt: float | None = None
    price_text: str = ""
    url: str = ""
    store: str = ""
    rating: float | None = None
    reviews_count: int | None = None
    match_score: int = 0  # 0-100, насколько соответствует запросу
    match_reason: str = ""
    concerns: list[str] = []

    # === Browser-Use поля ===
    browser_verified_price: float | None = Field(
        default=None, description="Цена подтверждённая через браузер"
    )
    browser_verified_at: str | None = Field(
        default=None, description="Когда проверено (ISO datetime)"
    )
    browser_session_id: str | None = Field(
        default=None, description="Session ID browser-use для отслеживания"
    )

    @field_serializer("browser_session_id")
    def _serialize_session_id(self, v):
        return str(v) if v is not None else None


class ProductSearchRequest(BaseModel):
    """Запрос на поиск товаров."""

    query: str = Field(..., description="Что ищем (свободный текст)")
    budget_kzt: float | None = Field(default=None, description="Бюджет на 1 единицу или общий")
    quantity: int | None = Field(default=None, description="Сколько нужно")
    additional_info: str | None = Field(
        default=None,
        description="Доп. требования: бренд, материал, гарантия и т.п.",
    )
    browser_action: str | None = Field(
        default=None,
        description=(
            "Действие через Browser-Use: 'verify_price' | 'book' | 'extract_contacts'. "
            "Если None — Tavily only (быстро, дёшево)."
        ),
    )
    browser_model: str | None = Field(
        default=None,
        description="Модель для browser-use: gpt-5.4-mini (дёшево) или claude-sonnet-4.6 (сложно)",
    )


class ProductSearchResult(BaseModel):
    """Результат поиска товаров."""

    lot_id: str = "search"
    query: str
    products: list[ProductItem] = []
    search_queries: list[str] = []
    summary: str = ""

    # === Метрики Browser-Use ===
    browser_actions_count: int = Field(default=0)
    browser_total_cost_usd: float = Field(default=0.0)
    browser_total_duration_sec: float = Field(default=0.0)


class DeepSearchRequest(BaseModel):
    """Глубокий поиск с извлечением характеристик."""

    lot_text: str = Field(..., description="Текст ТЗ (можно целиком или фрагмент)")
    budget_kzt: float | None = Field(default=None, description="Бюджет лота (если известен)")
    quantity: int | None = Field(default=None, description="Количество (если известно)")


class PriceComparison(BaseModel):
    """Сравнение с историей."""

    count: int = 0
    avg_price: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    median_price: float | None = None
    similar_lots: list[dict] = []
    recommendation: str = ""


# ───── Генерация заявки (Documenter/Application) ─────


class LotCreate(BaseModel):
    """Входные данные для анализатора лотов (используется orchestrator)."""

    source_url: str | None = None
    source_id: str | None = None
    customer_name: str | None = None
    customer_bin: str | None = None
    method: str | None = "tender"
    raw_text: str | None = None
    file_path: str | None = None


class ApplicationRequest(BaseModel):
    """Запрос на генерацию заявки на участие в лоте.

    Поля выровнены под `generate_application_docx` в application_generator.py:
    используются supplier_* и product_* имена.
    Старые имена (company_*, contact_*) автоматически маппятся в новые
    через model_validator(mode='before').
    """

    lot_id: str = Field(default="", description="ID лота")
    lot_title: str | None = Field(default=None, description="Название лота (опционально)")
    # Поставщик — основные имена, используемые генератором DOCX
    supplier_name: str = Field(..., description="Название компании поставщика")
    supplier_bin: str | None = Field(default=None, description="БИН компании (12 цифр)")
    supplier_address: str | None = Field(default=None, description="Юр. адрес")
    supplier_phone: str | None = Field(default=None, description="Телефон")
    supplier_email: str | None = Field(default=None, description="Email")
    supplier_iik: str | None = Field(default=None, description="ИИК")
    supplier_bank: str | None = Field(default=None, description="Банк")
    # Продукт / техническое предложение
    product_name: str | None = Field(default=None, description="Предлагаемый товар/услуга")
    product_description: str | None = Field(default=None)
    specs_compliance: list[str] = Field(default_factory=list)
    delivery_days: int | None = Field(default=None, description="Срок поставки (дней)")
    warranty_months: int | None = Field(default=None, description="Гарантия (мес)")
    # Ценовое предложение
    proposed_price_kzt: float = Field(default=0.0, description="Предлагаемая цена (тенге)")
    vat_rate: float = Field(default=12.0, description="Ставка НДС (%)")
    price_includes_delivery: bool = Field(default=False)
    payment_terms: str | None = Field(default=None)
    # Квалификации и документы
    qualifications: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, description="Дополнительные заметки")
    # Обратная совместимость со старым форматом (company_*, contact_*)
    company_name: str | None = Field(default=None)
    company_bin: str | None = Field(default=None)
    contact_name: str | None = Field(default=None)
    contact_phone: str | None = Field(default=None)
    contact_email: str | None = Field(default=None)
    experience_years: int = Field(default=0)
    similar_contracts_count: int = Field(default=0)
    has_certificates: bool = Field(default=False)
    has_materials: bool = Field(default=False)
    has_staff: bool = Field(default=False)

    @model_validator(mode="before")
    @classmethod
    def _map_legacy_fields(cls, data: Any) -> Any:
        """Если переданы старые имена (company_name/contact_*) — прокинем
        значения в новые (supplier_name/supplier_*) до валидации, чтобы
        required-поля supplier_name не падали."""
        if not isinstance(data, dict):
            return data
        data = dict(data)  # копия, чтобы не мутировать вход
        # supplier_name ← company_name
        if not data.get("supplier_name") and data.get("company_name"):
            data["supplier_name"] = data["company_name"]
        if not data.get("supplier_bin") and data.get("company_bin"):
            data["supplier_bin"] = data["company_bin"]
        if not data.get("supplier_phone") and data.get("contact_phone"):
            data["supplier_phone"] = data["contact_phone"]
        if not data.get("supplier_email") and data.get("contact_email"):
            data["supplier_email"] = data["contact_email"]
        # Если до сих пор нет supplier_name — пробуем contact_name (ФИО контактного лица)
        if not data.get("supplier_name") and data.get("contact_name"):
            data["supplier_name"] = data["contact_name"]
        return data


class ApplicationResult(BaseModel):
    """Результат генерации заявки."""

    lot_id: str
    company_name: str
    file_name: str = Field(..., description="Имя сгенерированного файла")
    file_size: int = Field(..., description="Размер в байтах")
    sections_generated: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    download_url: str | None = None


class MarginCalculationRequest(BaseModel):
    """Запрос на расчёт маржи.

    Поля выровнены под `calculate_margin` в application_generator.py.
    Старые имена (cost_price, desired_margin_percent, ...) автоматически
    маппятся в новые через model_validator(mode='before').
    """

    unit_cost_kzt: float = Field(..., description="Себестоимость единицы (тенге)")
    desired_margin_pct: float = Field(default=15, description="Желаемая маржа (%)")
    competitor_price_kzt: float | None = Field(
        default=None, description="Цена конкурента (если известна)"
    )
    vat_rate: float = Field(default=12, description="Ставка НДС (%)")
    logistics_per_unit_kzt: float = Field(default=0, description="Логистика на единицу (тенге)")
    overhead_per_unit_kzt: float = Field(default=0, description="Накладные расходы на единицу (тенге)")
    # Обратная совместимость со старым форматом
    cost_price: float | None = Field(default=None)
    desired_margin_percent: float | None = Field(default=None)
    competitor_price: float | None = Field(default=None)
    tax_rate: float | None = Field(default=None)
    logistics_cost: float | None = Field(default=None)
    other_costs: float | None = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def _map_legacy_fields(cls, data: Any) -> Any:
        """Если переданы старые имена — прокинем значения в новые поля до валидации."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if not data.get("unit_cost_kzt") and data.get("cost_price") is not None:
            data["unit_cost_kzt"] = data["cost_price"]
        if not data.get("desired_margin_pct") and data.get("desired_margin_percent") is not None:
            data["desired_margin_pct"] = data["desired_margin_percent"]
        if data.get("competitor_price_kzt") is None and data.get("competitor_price") is not None:
            data["competitor_price_kzt"] = data["competitor_price"]
        if not data.get("vat_rate") and data.get("tax_rate") is not None:
            data["vat_rate"] = data["tax_rate"]
        if not data.get("logistics_per_unit_kzt") and data.get("logistics_cost") is not None:
            data["logistics_per_unit_kzt"] = data["logistics_cost"]
        if not data.get("overhead_per_unit_kzt") and data.get("other_costs") is not None:
            data["overhead_per_unit_kzt"] = data["other_costs"]
        return data


class MarginCalculationResult(BaseModel):
    """Результат расчёта маржи.

    Поля выровнены под то, что возвращает `calculate_margin`.
    Старые имена (expected_profit, profit_margin) — alias.
    """

    min_price: float = Field(..., description="Минимальная цена (без убытка)")
    optimal_price: float = Field(..., description="Оптимальная цена (с маржой)")
    aggressive_price: float = Field(..., description="Агрессивная цена (ниже конкурента)")
    profit_at_optimal: float = Field(..., description="Ожидаемая прибыль (оптимальная)")
    profit_at_aggressive: float = Field(..., description="Ожидаемая прибыль (агрессивная)")
    margin_at_optimal_pct: float = Field(..., description="Маржа (%)")
    recommendation: str = Field(..., description="Рекомендация")
    # Обратная совместимость
    expected_profit: float | None = Field(default=None)
    profit_margin: float | None = Field(default=None)


# ═════ Documenter (анализ лота) ═════


class RequirementItem(BaseModel):
    """Одно требование из ТЗ лота."""

    name: str
    value: str
    is_critical: bool = False
    category: str = ""  # техническое, квалификационное, и т.д.


class ProcurementMethod(str):
    """Способ закупки (enum-like).

    Поддерживает как значения-строки, так и обращение через константы класса
    (ProcurementMethod.OTHER и т.п.) — раньше эти константы отсутствовали,
    из-за чего код падал с AttributeError.
    """

    TENDER = "tender"
    AUCTION = "auction"
    REQUEST_QUOTES = "request_quotes"
    SINGLE_SOURCE = "single_source"
    OTHER = "other"


class LotAnalysis(BaseModel):
    """Полный анализ лота от Documenter агента."""

    lot_id: str
    title: str
    customer: str = ""
    amount_kzt: float | None = None
    currency: str = "KZT"
    deadline: str | None = None
    delivery_address: str = ""
    delivery_days: int | None = None
    payment_terms: str = ""
    procurement_method: str = "tender"

    # Техническое задание
    technical_specification: str = ""
    requirements: list[RequirementItem] = Field(default_factory=list)

    # Квалификационные требования
    qualification_requirements: list[str] = Field(default_factory=list)

    # Документы
    documents_required: list[str] = Field(default_factory=list)

    # Оценка
    evaluation_criteria: dict[str, Any] = Field(default_factory=dict)

    # Compliance
    red_flags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    legal_compliance: str = "ok"  # ok / review / violation
    compliance_notes: str = ""

    # Расширенные поля для UI
    customer_score: "CustomerScore | None" = None
    margin_estimate: "MarginEstimate | None" = None
    recommendation: str = "review"  # participate / review / skip
    summary: str = ""


class LotAnalysisResponse(BaseModel):
    """Полный ответ анализа лота (orchestrator)."""

    lot: "LotAnalysis"
    legal: "LegalCheckResult | None" = None
    created_at: datetime
    incomplete: bool = False
    incomplete_reason: str = ""


# ═════ Legal Agent ═════


class LegalCheckItem(BaseModel):
    """Один пункт юридической проверки.

    Поля поддерживают оба варианта ответов LLM (rule_id/rule_title/status
    из старого промпта и category/title/severity из нового).
    """

    category: str = "general"  # "qualification", "document", "deadline", "price", ...
    title: str = ""
    severity: str = "info"  # ok / info / warning / violation / low / medium / high
    status: str = "info"  # ok / violation / risk / needs_review
    description: str = ""
    recommendation: str = ""
    # Совместимость со старым промптом Legal Agent:
    rule_id: str | None = None
    rule_title: str | None = None
    law_reference: str | None = None
    # Ссылки на источник нормы и цитату для прозрачной проверки
    article: str | None = None
    source: str | None = None
    quote: str | None = None
    citation_url: str | None = None
    legal_text_revision: str | None = None


class LegalCheckResult(BaseModel):
    """Результат юридической проверки лота.

    Поля `items` и `summary` поддерживаются для совместимости со старым
    промптом Legal Agent и существующими тестами.
    """

    lot_id: str
    overall_risk: str = "needs_review"  # ok / review / violation / low / medium / high / needs_review
    # Основной список проверок (новое имя)
    checks: list[LegalCheckItem] = Field(default_factory=list)
    # Alias для совместимости со старым кодом и тестами (LLM возвращает "items")
    items: list[LegalCheckItem] = Field(default_factory=list)
    critical_issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    complaint_draft: str | dict | None = None  # черновик жалобы
    summary: str = ""
    can_complain_to_counting_committee: bool = False
    corpus_revision: str | None = None


# ═════ B2G (workspace) ═════


class B2GRequest(BaseModel):
    """Запрос на генерацию ТЗ от заказчика.

    Используется B2GAgent'ом — поля соответствуют тому, что передаёт
    API endpoint /b2g/workspaces/{ws_id}/generate и что читает агент.
    """

    need_description: str = Field(..., description="Описание потребности (что нужно закупить)")
    category: str | None = Field(default=None)
    region: str | None = Field(default=None)
    organization: str | None = Field(default=None)
    # Опционально: похожие лоты из БД для калибровки бюджета
    similar_lots: list[dict[str, Any]] = Field(default_factory=list)
    # Совместимость со старым форматом (если кто-то передаёт workspace_name/description)
    workspace_name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    budget_kzt: float | None = Field(default=None)
    quantity: int | None = Field(default=None)
    additional_requirements: str | None = Field(default=None)


class B2GResult(BaseModel):
    """Результат генерации ТЗ через B2G агента."""

    # lot_id опционален — B2GAgent.run принимает lot_id как параметр и
    # кладёт его в результат для логирования.
    lot_id: str | None = None
    workspace_id: int | None = None
    title: str = ""
    description: str = ""
    technical_specification: str | dict = ""
    category: str = ""
    procurement_method: str = "tender"
    estimated_budget_kzt: float | None = None
    deadline: str | None = None
    delivery_address: str | None = None
    delivery_days: int | None = None
    qualification_requirements: list[str] = Field(default_factory=list)
    documents_required: list[str] = Field(default_factory=list)
    evaluation_criteria: dict[str, Any] = Field(default_factory=dict)
    red_flags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    legal_compliance: str = "ok"
    compliance_notes: str = ""


# ═════ Customer Score (Orchestrator) ═════


class CustomerScore(BaseModel):
    """Оценка заказчика (насколько надёжен).

    Поля выровнены под то, что возвращает `get_customer_score` в scoring.py:
    словарь с ключами customer / trust_score / trust_label / total_lots /
    avg_risk / source. Поле `customer_name` — alias для `customer`.
    """

    customer_name: str = ""
    # Альтернативное имя, которое возвращает scoring.py
    customer: str | None = None
    bin: str | None = None
    trust_score: float = 0.0  # 0-100
    trust_label: str = "unknown"
    total_lots: int = 0
    won_lots: int = 0
    cancelled_lots: int = 0
    avg_payment_days: float | None = None
    avg_risk: str | None = None
    source: str = "unknown"
    notes: str = ""
    is_estimate: bool = True
    evidence_count: int = 0
    method: str = "internal_analyses"
    disclaimer: str = "Оценка основана на внутренних анализах Tendr и не подтверждает надёжность заказчика."


class MarginEstimate(BaseModel):
    """Оценка маржинальности категории лота."""

    estimated_margin_pct: float = 0.0  # процент маржи
    category: str = ""
    confidence: str = "low"  # low / medium / high
    is_estimate: bool = True
    method: str = "category_baseline"
    assumptions: list[str] = Field(default_factory=list)
    disclaimer: str = "Ориентир по категории, а не расчёт вашей фактической прибыли."


# ═════ Deep Search Result ═════


class DeepSearchResult(BaseModel):
    """Результат глубокого поиска."""

    extracted_specs: dict[str, Any] = Field(default_factory=dict)
    product_name: str = ""
    category: str = ""
    search_queries: list[str] = Field(default_factory=list)
    products: list[ProductItem] = Field(default_factory=list)
    price_comparison: PriceComparison = Field(default_factory=PriceComparison)
    summary: str = ""
    total_found: int = 0
