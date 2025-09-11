import time

from hexbytes import HexBytes

from closeout.service import CloseoutService
from subquery.client import ProductInfo


def test_closeable_products_empty(w3_mock, autsubquery_mock, clearing_mock):
    autsubquery_mock.return_value.products_with_fsp_passed.return_value = []
    cs = CloseoutService(w3_mock, autsubquery_mock)
    products = cs.closeable_products()
    assert products == []
    autsubquery_mock.products_with_fsp_passed.assert_called_once()


def test_closeable_products_empty_when_no_open_interest(
    w3_mock, autsubquery_mock, clearing_mock
):
    autsubquery_mock.products_with_fsp_passed.return_value = [
        ProductInfo(
            id="0x" + "01" * 32,
            name="Product 1",
            state="3",
            earliest_fsp_submission_time=int(time.time()) - 2000,
            tradeout_interval=600,
            fsp=1,
        )
    ]
    w3_mock.eth.get_block.return_value = {"timestamp": int(time.time())}
    clearing_mock.return_value.open_interest.return_value = 0
    cs = CloseoutService(w3_mock, autsubquery_mock)
    products = cs.closeable_products()
    assert products == []
    autsubquery_mock.products_with_fsp_passed.assert_called_once()
    clearing_mock.return_value.open_interest.assert_called_once_with(b"\x01" * 32)


def test_closeable_products_filters_tradeouts(
    w3_mock, autsubquery_mock, clearing_mock
):
    autsubquery_mock.products_with_fsp_passed.return_value = [
        ProductInfo(
            id="0x" + "01" * 32,
            name="Product 1",
            state="3",
            earliest_fsp_submission_time=int(time.time()) - 500,
            tradeout_interval=600,
            fsp=1,
        ),
        ProductInfo(
            id="0x" + "02" * 32,
            name="Product 2",
            state="3",
            earliest_fsp_submission_time=int(time.time()) - 2000,
            tradeout_interval=1000,
            fsp=1,
        ),
    ]
    clearing_mock.return_value.open_interest.return_value = 100
    clearing_mock.return_value.get_fsp.return_value = (1, True)
    w3_mock.eth.get_block.return_value = {"timestamp": int(time.time())}
    cs = CloseoutService(w3_mock, autsubquery_mock)
    products = cs.closeable_products()
    assert len(products) == 1
    assert products[0].product_id == HexBytes("0x" + "02" * 32)
    autsubquery_mock.products_with_fsp_passed.assert_called_once()

