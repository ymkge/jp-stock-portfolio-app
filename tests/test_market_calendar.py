"""
日本市場（東証）の営業日・祝日・年末年始判定、および
祝日連休時における sync_history ターゲット日算出・history_manager 当日フォールバックの自動テスト (#323)
"""

import pytest
import os
import sqlite3
import json
from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock

import market_calendar
from market_calendar import is_jp_market_holiday, _is_holiday_fallback
from history_manager import JST
import history_manager
from sync_history import HistorySyncTool


# =====================================================================
# 1. 週末・東証特例休日・通常平日の判定テスト
# =====================================================================

def test_weekend_detection():
    """土曜日・日曜日が休場日として判定されること"""
    # 2026年9月19日（土）、9月20日（日）
    assert is_jp_market_holiday(date(2026, 9, 19)) is True
    assert is_jp_market_holiday(date(2026, 9, 20)) is True
    assert is_jp_market_holiday(datetime(2026, 9, 19, 10, 0)) is True
    assert is_jp_market_holiday("2026-09-19") is True


def test_tse_year_end_new_year():
    """東証の年末年始休業日（12/31, 1/1, 1/2, 1/3）が平日であっても休場日になること"""
    # 2026年12月31日（木）➔ 大納会翌日・休業日
    assert is_jp_market_holiday(date(2026, 12, 31)) is True
    # 2027年1月1日（金）➔ 元日
    assert is_jp_market_holiday(date(2027, 1, 1)) is True
    # 2027年1月2日（土）➔ 年始休業日
    assert is_jp_market_holiday(date(2027, 1, 2)) is True
    # 2027年1月3日（日）➔ 年始休業日
    assert is_jp_market_holiday(date(2027, 1, 3)) is True
    # 2027年1月4日（月）➔ 大発会（通常営業日）
    assert is_jp_market_holiday(date(2027, 1, 4)) is False


def test_business_days():
    """祝日でない通常の平日（火・水・木など）が誤って休場判定されないこと"""
    # 2026年9月15日（火）、9月16日（水）、9月17日（木）、9月18日（金）
    assert is_jp_market_holiday(date(2026, 9, 15)) is False
    assert is_jp_market_holiday(date(2026, 9, 16)) is False
    assert is_jp_market_holiday(date(2026, 9, 17)) is False
    assert is_jp_market_holiday(date(2026, 9, 18)) is False
    # シルバーウィーク明けの平日
    assert is_jp_market_holiday(date(2026, 9, 24)) is False
    assert is_jp_market_holiday(date(2026, 9, 25)) is False


# =====================================================================
# 2. 各種祝日・ハッピーマンデー・国民の休日・振替休日のテスト
# =====================================================================

def test_fixed_holidays():
    """固定祝日がすべて正確に判定されること"""
    year = 2026
    fixed_holidays = [
        (1, 1),   # 元日
        (2, 11),  # 建国記念の日 (水)
        (2, 23),  # 天皇誕生日 (月)
        (4, 29),  # 昭和の日 (水)
        (5, 3),   # 憲法記念日 (日)
        (5, 4),   # みどりの日 (月)
        (5, 5),   # こどもの日 (火)
        (8, 11),  # 山の日 (火)
        (11, 3),  # 文化の日 (火)
        (11, 23), # 勤労感謝の日 (月)
    ]
    for m, d in fixed_holidays:
        dt = date(year, m, d)
        assert is_jp_market_holiday(dt) is True, f"{dt} should be a holiday"


def test_happy_monday_holidays():
    """ハッピーマンデー祝日（成人の日、海の日、敬老の日、スポーツの日）が正確に判定されること"""
    # 2026年のハッピーマンデー
    assert is_jp_market_holiday(date(2026, 1, 12)) is True   # 成人の日: 1月第2月曜
    assert is_jp_market_holiday(date(2026, 7, 20)) is True   # 海の日: 7月第3月曜
    assert is_jp_market_holiday(date(2026, 9, 21)) is True   # 敬老の日: 9月第3月曜
    assert is_jp_market_holiday(date(2026, 10, 12)) is True  # スポーツの日: 10月第2月曜


def test_equinox_holidays():
    """春分の日・秋分の日が正確に判定されること"""
    # 2024年〜2028年の春分・秋分
    equinoxes = [
        (2024, 3, 20), (2024, 9, 22), # 2024年9月22日は日曜、翌23日振替
        (2025, 3, 20), (2025, 9, 23),
        (2026, 3, 20), (2026, 9, 23),
        (2027, 3, 21), (2027, 9, 23),
        (2028, 3, 20), (2028, 9, 22),
    ]
    for y, m, d in equinoxes:
        assert is_jp_market_holiday(date(y, m, d)) is True


def test_silver_week_citizens_holiday():
    """2026年シルバーウィーク（9/21敬老の日、9/22国民の休日、9/23秋分の日）の3連続平日休場日判定"""
    # 9月18日（金）平日
    assert is_jp_market_holiday(date(2026, 9, 18)) is False
    # 9月19日（土）
    assert is_jp_market_holiday(date(2026, 9, 19)) is True
    # 9月20日（日）
    assert is_jp_market_holiday(date(2026, 9, 20)) is True
    # 9月21日（月）敬老の日
    assert is_jp_market_holiday(date(2026, 9, 21)) is True
    # 9月22日（火）国民の休日（祝日に挟まれた平日）
    assert is_jp_market_holiday(date(2026, 9, 22)) is True
    # 9月23日（水）秋分の日
    assert is_jp_market_holiday(date(2026, 9, 23)) is True
    # 9月24日（木）平日
    assert is_jp_market_holiday(date(2026, 9, 24)) is False


def test_substitute_holidays_chain():
    """振替休日判定（祝日が日曜の場合の翌日振替、GW連鎖振替）"""
    # 1. 単純振替: 2024年9月22日(日)秋分の日 ➔ 2024年9月23日(月)振替休日
    assert is_jp_market_holiday(date(2024, 9, 23)) is True

    # 2. 連鎖振替: 2020年5月3日(日)憲法記念日, 5/4(月)みどりの日, 5/5(火)こどもの日
    # ➔ 5月6日(水) が振替休日！
    assert is_jp_market_holiday(date(2020, 5, 3)) is True
    assert is_jp_market_holiday(date(2020, 5, 4)) is True
    assert is_jp_market_holiday(date(2020, 5, 5)) is True
    assert is_jp_market_holiday(date(2020, 5, 6)) is True
    assert is_jp_market_holiday(date(2020, 5, 7)) is False


def test_fallback_without_jpholiday():
    """jpholiday が無効化された環境でも自律フォールバックが100%正しく動作すること"""
    with patch.object(market_calendar, "HAS_JPHOLIDAY", False):
        # 祝日・国民の休日・振替休日がすべて自律ロジックで正しく判定されること
        assert is_jp_market_holiday(date(2026, 9, 21)) is True  # 敬老の日
        assert is_jp_market_holiday(date(2026, 9, 22)) is True  # 国民の休日
        assert is_jp_market_holiday(date(2026, 9, 23)) is True  # 秋分の日
        assert is_jp_market_holiday(date(2026, 9, 24)) is False # 平日
        assert is_jp_market_holiday(date(2020, 5, 6)) is True   # GW連鎖振替休日


# =====================================================================
# 3. sync_history.py のターゲット日算出テスト
# =====================================================================

def test_sync_history_target_date_on_holiday():
    """祝日連休中に sync_history.get_target_date() が直前営業日（金曜）を正しく指すこと (#323)"""
    sync_tool = HistorySyncTool()

    # 1. 2026-09-21（月曜・敬老の日）10:00 JST に実行された場合
    # ➔ 直前の確定営業日は 2026-09-18（金曜）
    mock_now_holiday_morning = datetime(2026, 9, 21, 10, 0, 0, tzinfo=JST)
    with patch("sync_history.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now_holiday_morning
        target = sync_tool.get_target_date()
        assert target == "2026-09-18", f"Expected 2026-09-18, got {target}"

    # 2. 2026-09-21（月曜・敬老の日）17:00 JST (市場確定後) に実行された場合
    # ➔ 月曜が祝日なので、翌日や当日ではなく直前の営業日 2026-09-18（金曜）に正しく巻き戻ること
    mock_now_holiday_evening = datetime(2026, 9, 21, 17, 0, 0, tzinfo=JST)
    with patch("sync_history.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now_holiday_evening
        target = sync_tool.get_target_date()
        assert target == "2026-09-18", f"Expected 2026-09-18, got {target}"

    # 3. 2026-09-22（火曜・国民の休日）18:00 JST に実行された場合
    # ➔ 敬老の日と秋分の日に挟まれた火曜も祝日なので、2026-09-18（金曜）を指すこと
    mock_now_citizens_day = datetime(2026, 9, 22, 18, 0, 0, tzinfo=JST)
    with patch("sync_history.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now_citizens_day
        target = sync_tool.get_target_date()
        assert target == "2026-09-18", f"Expected 2026-09-18, got {target}"

    # 4. 通常平日 2026-09-24（木曜）17:00 JST (市場確定後) に実行された場合
    # ➔ 確定した本日 2026-09-24（木曜）を指すこと
    mock_now_thursday_evening = datetime(2026, 9, 24, 17, 0, 0, tzinfo=JST)
    with patch("sync_history.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now_thursday_evening
        target = sync_tool.get_target_date()
        assert target == "2026-09-24", f"Expected 2026-09-24, got {target}"


# =====================================================================
# 4. history_manager.py の単一銘柄取得＆当日フォールバックテスト
# =====================================================================

def test_history_manager_get_latest_daily_data(tmp_path):
    """get_latest_daily_data が最新日付のレコードを正しく取得すること (#323)"""
    test_db = str(tmp_path / "test_hm.db")
    with patch.object(history_manager, "DB_FILE", test_db):
        history_manager.init_db()

        # 過去データ（2026-09-17）と最新データ（2026-09-18）を保存
        with sqlite3.connect(test_db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO daily_analysis (date, code, asset_type, data_json, updated_at_jst) VALUES (?, ?, ?, ?, ?)",
                ("2026-09-17", "7203", "jp_stock", json.dumps({"code": "7203", "price": 2700}), "2026-09-17 15:30:00")
            )
            cursor.execute(
                "INSERT INTO daily_analysis (date, code, asset_type, data_json, updated_at_jst) VALUES (?, ?, ?, ?, ?)",
                ("2026-09-18", "7203", "jp_stock", json.dumps({"code": "7203", "price": 2750}), "2026-09-18 15:30:00")
            )
            conn.commit()

        # 最新データ（2026-09-18、価格2750）が取得できること
        latest = history_manager.get_latest_daily_data("7203")
        assert latest is not None
        assert latest["price"] == 2750
        assert latest["_db_updated_at_jst"] == "2026-09-18 15:30:00"

        # 存在しない銘柄コードは None
        assert history_manager.get_latest_daily_data("999999") is None


def test_history_manager_get_daily_data_fallback_on_holiday(tmp_path):
    """祝日当日（当日レコード未登録時）に get_daily_data が直前営業日の最新レコードへフォールバックすること (#323)"""
    test_db = str(tmp_path / "test_hm_fallback.db")
    with patch.object(history_manager, "DB_FILE", test_db):
        history_manager.init_db()

        # 直前営業日（2026-09-18 金曜）のデータを保存
        with sqlite3.connect(test_db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO daily_analysis (date, code, asset_type, data_json, updated_at_jst) VALUES (?, ?, ?, ?, ?)",
                ("2026-09-18", "7203", "jp_stock", json.dumps({"code": "7203", "price": 2750}), "2026-09-18 15:30:00")
            )
            conn.commit()

        # 現在時刻を 2026-09-21（月曜祝日）にモック
        mock_now_holiday = datetime(2026, 9, 21, 11, 0, 0, tzinfo=JST)
        with patch("history_manager.get_now_jst", return_value=mock_now_holiday):
            # date_str 未指定（デフォルト当日）の場合、当日データがなくても直前の 2026-09-18 データが返却されること
            res = history_manager.get_daily_data("7203")
            assert res is not None
            assert res["price"] == 2750
            assert res["_db_updated_at_jst"] == "2026-09-18 15:30:00"

            # 明示的に未来の日付（2026-09-22）を指定した場合はフォールバックせず None を返すこと
            res_explicit = history_manager.get_daily_data("7203", date_str="2026-09-22")
            assert res_explicit is None
