"""
主要市場指標の祝日明けにおける前日比欠損（-- (--)）解消、および
直前営業日終値に基づく自律計算・自己修復機能の自動テスト (#368)

AGENTS.md 規約 0.2 に従い、本番DB (portfolio_history.db) への書き込みを行わず、
一時DB環境およびモックを使用して完全隔離テストを実施。
"""

import pytest
import os
import sqlite3
import json
from datetime import datetime, date, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

from history_manager import JST
import history_manager
import scraper


@pytest.fixture
def isolated_test_db(tmp_path):
    """本番DBを汚染しない一時SQLiteテストデータベース環境"""
    test_db = str(tmp_path / "test_market_holiday.db")
    with patch.object(history_manager, "DB_FILE", test_db):
        history_manager.init_db()
        yield test_db


@pytest.mark.anyio
async def test_market_indices_holiday_change_auto_heal(isolated_test_db):
    """
    祝日（2026-11-03 文化の日）明けの翌営業日（2026-11-04）において、
    Yahoo!ファイナンスから前日比が None（未提供）で返却された場合でも、
    直前営業日（2026-11-02）終値から自律計算・補完され、DBに自己修復保存されること (#368)
    """
    import app

    # 1. 前営業日（2026-11-02）の市場指標データを一時DBにセットアップ
    with sqlite3.connect(isolated_test_db) as conn:
        cursor = conn.cursor()
        # 日経平均株価: 63,081.86
        cursor.execute(
            "INSERT INTO daily_analysis (date, code, asset_type, data_json, updated_at_jst) VALUES (?, ?, ?, ?, ?)",
            ("2026-11-02", "998407.O", "market_index", json.dumps({"code": "998407.O", "price": "63081.86"}), "2026-11-02 15:30:00")
        )
        # TOPIX: 3,930.28
        cursor.execute(
            "INSERT INTO daily_analysis (date, code, asset_type, data_json, updated_at_jst) VALUES (?, ?, ?, ?, ?)",
            ("2026-11-02", "998405.T", "market_index", json.dumps({"code": "998405.T", "price": "3930.28"}), "2026-11-02 15:30:00")
        )
        # 日経先物: 63,260.00
        cursor.execute(
            "INSERT INTO daily_analysis (date, code, asset_type, data_json, updated_at_jst) VALUES (?, ?, ?, ?, ?)",
            ("2026-11-02", "5040469.O", "market_index", json.dumps({"code": "5040469.O", "price": "63260.00"}), "2026-11-02 15:30:00")
        )
        # 為替ドル円: 前日（2026-11-03）のレート 157.94
        cursor.execute(
            "INSERT INTO daily_analysis (date, code, asset_type, data_json, updated_at_jst) VALUES (?, ?, ?, ?, ?)",
            ("2026-11-03", "USDJPY=X", "market_index", json.dumps({"code": "USDJPY=X", "price": "157.94"}), "2026-11-03 21:00:00")
        )
        conn.commit()

    # 2. 現在時刻を 2026-11-04 17:00:00 JST（祝日明けの引け後）にモック
    mock_now = datetime(2026, 11, 4, 17, 0, 0, tzinfo=JST)

    # 3. スクレイパーの返却値（祝日明けで前日比 change/change_percent が欠損した状態）
    def mock_fetch_data(code):
        if code == "998407.O":
            return {"code": "998407.O", "name": "日経平均", "price": "62188.63", "change": None, "change_percent": None}
        elif code == "998405.T":
            return {"code": "998405.T", "name": "TOPIX", "price": "3895.38", "change": None, "change_percent": None}
        elif code == "5040469.O":
            return {"code": "5040469.O", "name": "日経先物", "price": "62450.00", "change": None, "change_percent": None}
        elif code == "USDJPY=X":
            return {"code": "USDJPY=X", "name": "ドル円", "price": "158.13", "change": None, "change_percent": None}
        return {"code": code, "name": "テスト銘柄", "price": "2000", "closePrice": "2000", "histories": []}

    mock_scraper = MagicMock()
    mock_scraper.fetch_data.side_effect = mock_fetch_data
    mock_scraper.is_cached.return_value = False
    mock_scraper.cache = {}

    # 為替詳細も change なし
    mock_fx_detail = {
        "price": "158.13",
        "change": None,
        "change_percent": None,
        "high": "158.50",
        "low": "157.90",
        "high_52w": "163.98",
        "low_52w": "152.28",
        "peak_diff_percent": "-3.6%"
    }

    mock_request = MagicMock()
    mock_request.is_disconnected = AsyncMock(return_value=False)

    with patch.object(history_manager, "DB_FILE", isolated_test_db), \
         patch("history_manager.get_now_jst", return_value=mock_now), \
         patch("app.history_manager.DB_FILE", isolated_test_db), \
         patch("app.history_manager.get_now_jst", return_value=mock_now), \
         patch("scraper.get_scraper", return_value=mock_scraper), \
         patch("scraper.get_exchange_rate_detail", return_value=mock_fx_detail), \
         patch("app.get_config", side_effect=lambda key, default=None: [
             {"code": "998407.O", "name": "日経平均"},
             {"code": "998405.T", "name": "TOPIX"},
             {"code": "5040469.O", "name": "日経先物"},
             {"code": "USDJPY=X", "name": "ドル円"}
         ] if key == "market_indices" else default), \
         patch("portfolio_manager.load_portfolio", return_value=[{"code": "7203", "asset_type": "jp_stock"}]):

        # app._get_processed_asset_data を実行
        processed_data, metadata = await app._get_processed_asset_data(
            request=mock_request,
            force=True
        )

        indices = metadata.get("market_indices", [])
        assert len(indices) == 4

        # 日経平均株価: 62188.63 - 63081.86 = -893.23 (-1.42%)
        n225 = next(x for x in indices if x["code"] == "998407.O")
        assert n225["price"] == "62188.63"
        assert n225["change"] == "-893.23"
        assert n225["change_percent"] == "-1.42%"

        # TOPIX: 3895.38 - 3930.28 = -34.90 (-0.89%)
        topix = next(x for x in indices if x["code"] == "998405.T")
        assert topix["price"] == "3895.38"
        assert topix["change"] == "-34.90"
        assert topix["change_percent"] == "-0.89%"

        # 日経先物: 62450.00 - 63260.00 = -810.00 (-1.28%)
        futures = next(x for x in indices if x["code"] == "5040469.O")
        assert futures["price"] == "62450.00"
        assert futures["change"] == "-810.00"
        assert futures["change_percent"] == "-1.28%"

        # 為替ドル円: 158.13 - 157.94 = +0.19 (+0.12%)
        usdjpy = next(x for x in indices if x["code"] == "USDJPY=X")
        assert usdjpy["price"] == "158.13"
        assert usdjpy["change"] == "+0.1900" or usdjpy["change"] == "+0.19"
        assert usdjpy["change_percent"] == "+0.12%"


@pytest.mark.anyio
async def test_market_indices_normal_day_preserved(isolated_test_db):
    """通常取引日でスクレイパーから正常な前日比が提供されている場合は上書きしないこと (#368)"""
    import app

    mock_now = datetime(2026, 11, 5, 15, 0, 0, tzinfo=JST)

    def mock_fetch_data(code):
        if code == "998407.O":
            return {"code": "998407.O", "name": "日経平均", "price": "62500.00", "change": "+311.37", "change_percent": "+0.50%"}
        return {"code": code, "price": "100", "change": "+1.0", "change_percent": "+1.0%"}

    mock_scraper = MagicMock()
    mock_scraper.fetch_data.side_effect = mock_fetch_data
    mock_scraper.is_cached.return_value = False
    mock_scraper.cache = {}

    mock_request = MagicMock()
    mock_request.is_disconnected = AsyncMock(return_value=False)

    with patch.object(history_manager, "DB_FILE", isolated_test_db), \
         patch("history_manager.get_now_jst", return_value=mock_now), \
         patch("app.history_manager.DB_FILE", isolated_test_db), \
         patch("app.history_manager.get_now_jst", return_value=mock_now), \
         patch("scraper.get_scraper", return_value=mock_scraper), \
         patch("app.get_config", side_effect=lambda key, default=None: [
             {"code": "998407.O", "name": "日経平均"}
         ] if key == "market_indices" else default), \
         patch("portfolio_manager.load_portfolio", return_value=[{"code": "7203", "asset_type": "jp_stock"}]):

        processed_data, metadata = await app._get_processed_asset_data(
            request=mock_request,
            force=True
        )

        indices = metadata.get("market_indices", [])
        assert len(indices) == 1
        assert indices[0]["change"] == "+311.37"
        assert indices[0]["change_percent"] == "+0.50%"
