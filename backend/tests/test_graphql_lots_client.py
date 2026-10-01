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
