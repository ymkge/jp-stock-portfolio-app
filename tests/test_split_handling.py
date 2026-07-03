import pytest
import sqlite3
import os
from unittest.mock import patch, MagicMock

from sync_history import round_split_ratio
import history_manager

@pytest.fixture(autouse=True)
def setup_test_db():
    """テスト用にDB_FILEを一時的に別名にする、またはテーブルを初期化する"""
    original_db = history_manager.DB_FILE
    history_manager.DB_FILE = "test_portfolio_history.db"
    history_manager.init_db()
    yield
    # テスト後にDBを削除
    if os.path.exists("test_portfolio_history.db"):
        os.remove("test_portfolio_history.db")
    history_manager.DB_FILE = original_db

def test_round_split_ratio():
    # 分割の丸め
    assert round_split_ratio(4.995) == 5.0
    assert round_split_ratio(1.989) == 2.0
    assert round_split_ratio(2.999) == 3.0
    assert round_split_ratio(0.201) == 0.2
    # 該当しない比率
    assert round_split_ratio(1.72) == 1.72
    assert round_split_ratio(1.0) == 1.0

def test_split_alert_db_operations():
    code = "9999"
    # アラート追加
    assert history_manager.add_split_alert(code, 5.0) is True
    assert history_manager.has_pending_split_alert(code) is True
    
    # アラート取得
    alerts = history_manager.get_pending_split_alerts()
    assert len(alerts) == 1
    assert alerts[0]["code"] == code
    assert alerts[0]["ratio"] == 5.0
    assert alerts[0]["status"] == "pending"

    # ステータス更新 (dismissed)
    assert history_manager.update_split_alert_status(code, "dismissed") is True
    assert history_manager.has_pending_split_alert(code) is False
    assert len(history_manager.get_pending_split_alerts()) == 0

    # ステータス更新 (invalid status)
    assert history_manager.update_split_alert_status(code, "invalid_status") is False

def test_get_latest_price_from_db():
    code = "9999"
    # 空の状態
    assert history_manager.get_latest_price_from_db(code) is None

    # データ挿入
    with sqlite3.connect("test_portfolio_history.db") as conn:
        cursor = conn.cursor()
        # 過去データ
        cursor.execute(
            "INSERT INTO stock_price_history (date, code, close_price, volume, updated_at_jst) VALUES (?, ?, ?, ?, ?)",
            ("2026-07-01", code, 1000.0, 100, "JST_TIME")
        )
        # より新しい過去データ
        cursor.execute(
            "INSERT INTO stock_price_history (date, code, close_price, volume, updated_at_jst) VALUES (?, ?, ?, ?, ?)",
            ("2026-07-02", code, 1050.0, 120, "JST_TIME")
        )
        # 当日のデータ（当日を除くため無視されるべき）
        today_str = history_manager.get_now_jst().strftime("%Y-%m-%d")
        cursor.execute(
            "INSERT INTO stock_price_history (date, code, close_price, volume, updated_at_jst) VALUES (?, ?, ?, ?, ?)",
            (today_str, code, 200.0, 50, "JST_TIME")
        )
        conn.commit()

    # 直近終値は 2026-07-02 の 1050.0 になるはず（当日データは除外）
    assert history_manager.get_latest_price_from_db(code) == 1050.0

@patch("app.history_manager")
def test_potential_split_detection(mock_history_manager):
    from app import _enrich_stock_data
    
    mock_history_manager.get_latest_price_from_db.return_value = 1000.0
    mock_history_manager.has_pending_split_alert.return_value = False
    
    # 乖離なしの場合 (1000.0 vs 980.0)
    merged_data_no_split = {
        "code": "9999",
        "asset_type": "jp_stock",
        "price": "980",
        "dividend_history": {}
    }
    with patch("app.calculate_score", return_value=(10, {})):
        with patch("app.calculate_buy_signal", return_value=None):
            with patch("app.calculate_sell_signal", return_value=None):
                with patch("app.reconcile_signals", return_value=(None, None)):
                    res = _enrich_stock_data(merged_data_no_split)
                    assert "potential_split" not in res

    # 乖離ありの場合 (1000.0 vs 200.0 = 5.0)
    merged_data_with_split = {
        "code": "9999",
        "asset_type": "jp_stock",
        "price": "200",
        "dividend_history": {}
    }
    with patch("app.calculate_score", return_value=(10, {})):
        with patch("app.calculate_buy_signal", return_value=None):
            with patch("app.calculate_sell_signal", return_value=None):
                with patch("app.reconcile_signals", return_value=(None, None)):
                    res = _enrich_stock_data(merged_data_with_split)
                    assert res.get("potential_split") is True
                    assert res.get("potential_split_ratio") == 5.0
