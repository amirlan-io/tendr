import pytest

from app.services.lots.graphql_client import GraphQLClient


def test_graphql_item_is_mapped_as_actual_lot_not_announcement():
    client = GraphQLClient("test-token")
    item = {
        "id": 43447486,
        "lot_number": "87333454-ЗЦП2",
        "ref_lot_status_id": 110,
        "amount": 95000,
        "name_ru": "Шкаф",
        "description_ru": "деревянный, для кухни",
        "customer_bin": "001140004038",
        "trd_buy_id": 17713642,
        "trd_buy_number_anno": "17713642-1",
    }
    announcement = {
        "id": 17713642,
        "number_anno": "17713642-1",
        "ref_trade_methods_id": 3,
        "ref_subject_type_id": 1,
        "ref_buy_status_id": 240,
        "end_date": "2026-10-05T12:00:00",
    }

    lot = client._graphql_to_parsed(item, announcement, "Тестовый заказчик")

    assert lot.source_id == "87333454-ЗЦП2"
    assert lot.title == "Шкаф"
    assert lot.description == "деревянный, для кухни"
    assert lot.amount_kzt == 95000
    assert lot.category == "товар"
    assert lot.organizer == "Тестовый заказчик"
    assert lot.source_url.endswith("/17713642-1")


def test_raw_keyword_filter_rejects_unrelated_lots():
    mask = {
        "lot_number": "88089080-ЗЦП1",
        "name_ru": "Маска",
        "description_ru": "одноразовая",
        "amount": 10000,
        "customer_bin": "040640005148",
    }
    chair = {
        "lot_number": "88102915",
        "name_ru": "Кресло",
        "amount": 450000,
        "customer_bin": "000000000000",
    }

    assert GraphQLClient._raw_matches(
        mask,
        text_query="маска",
        customer_bin_like="",
        min_amount=0,
        max_amount=0,
        only_with_amount=False,
    )
    assert not GraphQLClient._raw_matches(
        chair,
        text_query="маска",
        customer_bin_like="",
        min_amount=0,
        max_amount=0,
        only_with_amount=False,
    )


def test_client_upgrades_legacy_v2_url_to_v3_for_full_text_search():
    client = GraphQLClient("test-token", "https://ows.goszakup.gov.kz/v2")

    assert client.endpoint == "https://ows.goszakup.gov.kz/v3/graphql"


@pytest.mark.asyncio
async def test_search_uses_global_v3_morphology_filter(monkeypatch):
    client = GraphQLClient("test-token")
    captured_variables = None

    async def fake_request(_http_client, _query, variables, _headers):
        nonlocal captured_variables
        captured_variables = variables
        return {
            "data": {
                "lots": [
                    {
                        "id": 123,
                        "lot_number": "59523565-ЗЦПнеГЗ1",
                        "ref_lot_status_id": 110,
                        "amount": 144000,
                        "name_ru": "Услуги по обработке сайтов в Интернете",
                        "description_ru": "Техническая поддержка веб-ресурса",
                        "customer_bin": "123456789012",
                        "customer_name_ru": "Тестовый заказчик",
                        "trd_buy_id": 99,
                        "trd_buy_number_anno": "9180737-1",
                        "announcement": {
                            "id": 99,
                            "number_anno": "9180737-1",
                            "ref_subject_type_id": 3,
                            "ref_trade_methods_id": 3,
                            "ref_buy_status_id": 240,
                        },
                    }
                ]
            },
            "extensions": {"pageInfo": {"hasNextPage": False}},
        }

    monkeypatch.setattr(client, "_request", fake_request)

    lots = await client.search_lots(query="сайт", category="услуга", limit=20)

    assert captured_variables is not None
    assert captured_variables["filter"]["nameDescriptionRu"] == "*сайт"
    assert captured_variables["filter"]["refLotStatusId"] == [220, 240]
    assert lots[0].source_id == "59523565-ЗЦПнеГЗ1"
    assert lots[0].category == "услуга"
    assert lots[0].organizer == "Тестовый заказчик"


@pytest.mark.asyncio
async def test_search_exposes_official_total_and_next_cursor(monkeypatch):
    client = GraphQLClient("test-token")

    async def fake_request(_http_client, _query, variables, _headers):
        assert variables["after"] == 900
        assert variables["filter"]["refBuyTradeMethodsId"] == [3]
        assert variables["filter"]["indexDate"] == ["2026-09-01", "2026-10-01"]
        return {
            "data": {
                "lots": [
                    {
                        "id": 899,
                        "lot_number": "899-1",
                        "ref_lot_status_id": 240,
                        "amount": 1000,
                        "name_ru": "Тестовый лот",
                        "trd_buy_id": 10,
                        "announcement": {
                            "id": 10,
                            "number_anno": "10-1",
                            "end_date": "2026-10-05T12:00:00",
                            "ref_subject_type_id": 1,
                            "ref_buy_status_id": 240,
                        },
                    }
                ]
            },
            "extensions": {
                "pageInfo": {
                    "totalCount": 321,
                    "hasNextPage": True,
                    "lastId": 899,
                }
            },
        }

    monkeypatch.setattr(client, "_request", fake_request)

    await client.search_lots(
        cursor=900,
        procurement_method_ids=[3],
        published_from="2026-09-01",
        published_to="2026-10-01",
        limit=20,
    )

    assert client.page_info.total_count == 321
    assert client.page_info.has_next_page is True
    assert client.page_info.next_cursor == 899
    assert client.page_info.total_is_exact is True
