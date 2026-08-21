import pytest
from portfolio_manager import calculate_holding_values

def test_calculate_holding_values_jp_stock_taxable():
    """国内株式（課税口座）の計算テスト"""
    asset_data = {
        "price": "1000",
        "annual_dividend": "40",
        "currency": "JPY",
        "asset_type": "jp_stock"
    }
    holding = {
        "purchase_price": 800,
        "quantity": 100,
        "account_type": "特定口座"
    }
    exchange_rates = {"JPY": 1.0}
    tax_config = {
        "non_taxable_accounts": ["新NISA", "旧NISA"],
        "tax_info": {
            "jp_stock": {"tax_rate": 0.20315}
        }
    }
    
    result = calculate_holding_values(asset_data, holding, exchange_rates, tax_config)
    
    assert result["market_value"] == 100000
    assert result["profit_loss"] == 20000
    assert result["profit_loss_rate"] == 25.0
    assert result["estimated_annual_dividend"] == 4000
    # 4000 * (1 - 0.20315) = 4000 * 0.79685 = 3187.4
    assert pytest.approx(result["estimated_annual_dividend_after_tax"], 0.1) == 3187.4

def test_calculate_holding_values_us_stock_nontaxable():
    """米国株式（非課税口座）の計算テスト"""
    asset_data = {
        "price": "150",
        "annual_dividend": "3.5",
        "currency": "USD",
        "asset_type": "us_stock"
    }
    holding = {
        "purchase_price": 100,
        "quantity": 10,
        "account_type": "新NISA"
    }
    exchange_rates = {"USD": 150.0}
    tax_config = {
        "non_taxable_accounts": ["新NISA", "旧NISA"],
        "tax_info": {
            "us_stock": {"tax_rate": 0.20315} # 課税口座用
        }
    }
    
    result = calculate_holding_values(asset_data, holding, exchange_rates, tax_config)
    
    # 150 USD * 150 JPY/USD * 10 = 225000 JPY
    assert result["market_value"] == 225000
    # 投資額: 100 USD * 150 JPY/USD * 10 = 150000 JPY
    # 損益: 225000 - 150000 = 75000 JPY
    assert result["profit_loss"] == 75000
    assert result["estimated_annual_dividend"] == 3.5 * 10 * 150 # 5250
    # 非課税口座なので税引き後も同じ
    assert result["estimated_annual_dividend_after_tax"] == 5250

def test_calculate_holding_values_missing_price():
    """価格データ欠損時のテスト"""
    asset_data = {
        "price": "N/A",
        "annual_dividend": "40",
        "currency": "JPY"
    }
    holding = {"purchase_price": 800, "quantity": 100}
    result = calculate_holding_values(asset_data, holding, {}, {})
    assert result["market_value"] is None
    assert result["estimated_annual_dividend"] == 4000


def test_calculate_daily_change_rankings_normal():
    """案件 #261: 当日資産増減ランキング(TOP10)の計算・合算・ソートのテスト"""
    from portfolio_manager import calculate_daily_change_rankings

    raw_holdings = [
        # 銘柄A (国内株 7203): 口座1 100株 + 口座2 200株 (前日比 +50円 ➔ 50 * 300 = +15,000円)
        {"code": "7203", "name": "トヨタ", "asset_type": "jp_stock", "currency": "JPY", "quantity": 100, "change": 50.0, "change_percent": 2.0, "market_value": 250000},
        {"code": "7203", "name": "トヨタ", "asset_type": "jp_stock", "currency": "JPY", "quantity": 200, "change": 50.0, "change_percent": 2.0, "market_value": 500000},
        # 銘柄B (米国株 AAPL): 10株 (前日比 +10ドル, 為替 150円/$ ➔ 10 * 10 * 150 = +15,000円と同額だが合算動作確認)
        {"code": "AAPL", "name": "Apple", "asset_type": "us_stock", "currency": "USD", "quantity": 10, "change": 10.0, "change_percent": 4.0, "market_value": 300000},
        # 銘柄C (国内株 9432): 1000株 (前日比 -5円 ➔ -5 * 1000 = -5,000円)
        {"code": "9432", "name": "NTT", "asset_type": "jp_stock", "currency": "JPY", "quantity": 1000, "change": -5.0, "change_percent": -3.0, "market_value": 150000},
        # 銘柄D (投資信託): 100,000口 (基準価額前日比 +100円/10,000口 ➔ (100/10000) * 100000 = +1,000円)
        {"code": "IT_TEST", "name": "オルカン", "asset_type": "investment_trust", "currency": "JPY", "quantity": 100000, "change": 100.0, "change_percent": 0.5, "market_value": 200000},
    ]

    exchange_rates = {"JPY": 1.0, "USD": 150.0}

    res = calculate_daily_change_rankings(raw_holdings, exchange_rates)

    gainers = res["day_gainers_top10"]
    losers = res["day_losers_top10"]

    assert len(gainers) == 3
    assert len(losers) == 1

    # トヨタ(7203) と AAPL はともに +15,000円で上位
    gainer_codes = [g["code"] for g in gainers]
    assert "7203" in gainer_codes
    assert "AAPL" in gainer_codes
    assert "IT_TEST" in gainer_codes

    # NTT(9432) は -5,000円で減少トップ
    assert losers[0]["code"] == "9432"
    assert losers[0]["daily_change_jpy"] == -5000.0
    assert losers[0]["rank"] == 1


def test_calculate_daily_change_rankings_edge_cases():
    """案件 #261: N/A・データ欠損・前日比0の除外セーフガードテスト"""
    from portfolio_manager import calculate_daily_change_rankings

    raw_holdings = [
        {"code": "NO_CHANGE", "quantity": 100, "change": 0.0},
        {"code": "NA_CHANGE", "quantity": 100, "change": "N/A"},
        {"code": "NONE_CHANGE", "quantity": 100, "change": None},
    ]

    res = calculate_daily_change_rankings(raw_holdings, {"JPY": 1.0})
    assert len(res["day_gainers_top10"]) == 0
    assert len(res["day_losers_top10"]) == 0


def test_calculate_daily_change_rankings_string_formats_and_top10_limit():
    """案件 #261: 文字列フォーマットの前日比・10件超のTOP10制限テスト"""
    from portfolio_manager import calculate_daily_change_rankings

    raw_holdings = []
    # 25銘柄の増加データを作成 (前日比 +1円 〜 +25円, 100株)
    for i in range(1, 26):
        raw_holdings.append({
            "code": f"STOCK_{i:02d}",
            "name": f"銘柄{i}",
            "asset_type": "jp_stock",
            "currency": "JPY",
            "quantity": 100,
            "change": f"+{i}.0",
            "change_percent": f"+{i * 0.1}%",
            "market_value": 10000 * i
        })
    # 22銘柄の減少データを作成 (前日比 -1円 〜 -22円, 100株)
    for i in range(1, 23):
        raw_holdings.append({
            "code": f"LOSS_{i:02d}",
            "name": f"損失銘柄{i}",
            "asset_type": "jp_stock",
            "currency": "JPY",
            "quantity": 100,
            "change": f"-{i}.0",
            "change_percent": f"-{i * 0.1}%",
            "market_value": 10000 * i
        })

    res = calculate_daily_change_rankings(raw_holdings, {"JPY": 1.0})

    gainers = res["day_gainers_top20"]
    losers = res["day_losers_top20"]

    # 20件に制限されていること
    assert len(gainers) == 20
    assert len(losers) == 20


    # 増加1位はSTOCK_25 (25 * 100 = 2500円増)
    assert gainers[0]["code"] == "STOCK_25"
    assert gainers[0]["daily_change_jpy"] == 2500.0
    assert gainers[0]["rank"] == 1

    # 減少1位はLOSS_22 (-22 * 100 = -2200円)
    assert losers[0]["code"] == "LOSS_22"
    assert losers[0]["daily_change_jpy"] == -2200.0
    assert losers[0]["rank"] == 1


def test_calculate_monthly_change_rankings_normal():
    from portfolio_manager import calculate_monthly_change_rankings
    from unittest.mock import patch

    mock_last_month_map = {
        "9991": {"code": "9991", "name": "銘柄A", "market_value": 100000.0, "quantity": 100, "asset_type": "jp_stock"},
        "9992": {"code": "9992", "name": "銘柄B", "market_value": 200000.0, "quantity": 100, "asset_type": "jp_stock"},
        "9993": {"code": "9993", "name": "売却済銘柄", "market_value": 50000.0, "quantity": 50, "asset_type": "jp_stock"},
    }

    raw_holdings = [
        {"code": "9991", "name": "銘柄A", "asset_type": "jp_stock", "market_value": 150000.0, "quantity": 100}, # +50,000円
        {"code": "9992", "name": "銘柄B", "asset_type": "jp_stock", "market_value": 180000.0, "quantity": 100}, # -20,000円
        {"code": "9994", "name": "新規購入銘柄", "asset_type": "jp_stock", "market_value": 30000.0, "quantity": 30}, # +30,000円 (新規)
    ]

    with patch("history_manager.get_last_month_end_holdings_snapshot", return_value=("2026-07", mock_last_month_map)):
        res = calculate_monthly_change_rankings(raw_holdings, {"JPY": 1.0})

        assert res["has_last_month_data"] is True
        assert res["month_label"] == "2026年7月末比"

        gainers = res["month_gainers_top10"]
        losers = res["month_losers_top10"]

        assert len(gainers) == 2
        assert gainers[0]["code"] == "9991"
        assert gainers[0]["monthly_change_jpy"] == 50000.0
        assert gainers[1]["code"] == "9994"
        assert gainers[1]["is_newly_added"] is True

        assert len(losers) == 2
        assert losers[0]["code"] == "9993"  # 売却済 (-50,000円)
        assert losers[0]["is_sold_out"] is True
        assert losers[1]["code"] == "9992"  # -20,000円


def test_calculate_monthly_change_rankings_no_data():
    from portfolio_manager import calculate_monthly_change_rankings
    from unittest.mock import patch

    with patch("history_manager.get_last_month_end_holdings_snapshot", return_value=(None, {})):
        res = calculate_monthly_change_rankings([], {"JPY": 1.0})
        assert res["has_last_month_data"] is False
        assert len(res["month_gainers_top10"]) == 0
        assert len(res["month_losers_top10"]) == 0


def test_get_last_month_end_holdings_snapshot_db_query(tmp_path, monkeypatch):
    """history_manager.get_last_month_end_holdings_snapshot が前月MAX(snapshot_date)の複数口座データを横断集計する動作テスト"""
    import sqlite3
    from datetime import datetime
    import history_manager

    db_file = str(tmp_path / "test_portfolio.db")
    monkeypatch.setattr(history_manager, "DB_FILE", db_file)

    now_jst = history_manager.get_now_jst()
    first_day = now_jst.replace(day=1)
    last_month_date = first_day - timedelta(days=1) if 'timedelta' in globals() else first_day.replace(day=1)
    from datetime import timedelta
    last_month_end = first_day - timedelta(days=1)
    last_month_str = last_month_end.strftime("%Y-%m")
    max_date_str = last_month_end.strftime("%Y-%m-%d")
    earlier_date_str = (last_month_end - timedelta(days=5)).strftime("%Y-%m-%d")

    with sqlite3.connect(db_file) as conn:
        conn.execute("""
            CREATE TABLE portfolio_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                snapshot_month TEXT NOT NULL,
                account_id TEXT,
                code TEXT NOT NULL,
                name TEXT,
                asset_type TEXT,
                market_value REAL,
                quantity REAL
            )
        """)
        # 古い日付（同じ先月だが最新日ではない）
        conn.execute("""
            INSERT INTO portfolio_history (snapshot_date, snapshot_month, account_id, code, name, asset_type, market_value, quantity)
            VALUES (?, ?, 'acc1', '7203', 'トヨタ', 'jp_stock', 100000, 100)
        """, (earlier_date_str, last_month_str))
        
        # 最新日（MAX(snapshot_date)）: 口座1 と 口座2 で7203を分散保有 ➔ 横断集計されるべき
        conn.execute("""
            INSERT INTO portfolio_history (snapshot_date, snapshot_month, account_id, code, name, asset_type, market_value, quantity)
            VALUES (?, ?, 'acc1', '7203', 'トヨタ', 'jp_stock', 200000, 100)
        """, (max_date_str, last_month_str))
        conn.execute("""
            INSERT INTO portfolio_history (snapshot_date, snapshot_month, account_id, code, name, asset_type, market_value, quantity)
            VALUES (?, ?, 'acc2', '7203', 'トヨタ', 'jp_stock', 300000, 150)
        """, (max_date_str, last_month_str))
        # 最新日の別銘柄
        conn.execute("""
            INSERT INTO portfolio_history (snapshot_date, snapshot_month, account_id, code, name, asset_type, market_value, quantity)
            VALUES (?, ?, 'acc1', '9432', 'NTT', 'jp_stock', 50000, 300)
        """, (max_date_str, last_month_str))

    ret_month, holdings_map = history_manager.get_last_month_end_holdings_snapshot()

    assert ret_month == last_month_str
    assert "7203" in holdings_map
    assert holdings_map["7203"]["market_value"] == 500000.0  # 200,000 + 300,000
    assert holdings_map["7203"]["quantity"] == 250.0       # 100 + 150
    assert "9432" in holdings_map
    assert holdings_map["9432"]["market_value"] == 50000.0


def test_calculate_monthly_change_rankings_edge_cases_and_top10_limit():
    """案件 #270: 10件切り捨て制限・変動画0除外・新規/売却バッジ判定の追加検証"""
    from portfolio_manager import calculate_monthly_change_rankings
    from unittest.mock import patch

    mock_last_month_map = {}
    # 22銘柄の先月末データを作成
    for i in range(1, 23):
        code = f"STOCK_{i:02d}"
        mock_last_month_map[code] = {
            "code": code,
            "name": f"銘柄{i}",
            "market_value": 100000.0,
            "quantity": 100,
            "asset_type": "jp_stock"
        }

    raw_holdings = []
    # 22銘柄中、21銘柄を増額、1銘柄を変動なし(0円増減)
    for i in range(1, 22):
        code = f"STOCK_{i:02d}"
        raw_holdings.append({
            "code": code,
            "name": f"銘柄{i}",
            "asset_type": "jp_stock",
            "market_value": 100000.0 + (i * 10000.0), # +1万〜+21万
            "quantity": 100
        })
    # 変動なし
    raw_holdings.append({
        "code": "STOCK_22",
        "name": "銘柄22",
        "asset_type": "jp_stock",
        "market_value": 100000.0,
        "quantity": 100
    })

    with patch("history_manager.get_last_month_end_holdings_snapshot", return_value=("2026-07", mock_last_month_map)), \
         patch("history_manager.get_applied_split_alerts", return_value=[]):
        res = calculate_monthly_change_rankings(raw_holdings, {"JPY": 1.0})

        gainers = res["month_gainers_top20"]
        # 21件の増加銘柄のうちTOP20のみ抽出されていること
        assert len(gainers) == 20
        assert gainers[0]["code"] == "STOCK_21"
        assert gainers[0]["monthly_change_jpy"] == 210000.0
        assert gainers[0]["rank"] == 1
        # 変動なし(STOCK_22)は除外されていること
        gainer_codes = [g["code"] for g in gainers]
        assert "STOCK_22" not in gainer_codes


def test_calculate_monthly_change_rankings_with_transitional_stock_split():
    """Issue #271: 株式分割過渡期スナップショット（8309 1:4分割等）における評価額自己修復補正の検証テスト"""
    from portfolio_manager import calculate_monthly_change_rankings
    from unittest.mock import patch

    # 先月末スナップショット（40株, 旧株数 * 分割後株価 = 66,160円）
    mock_last_month_map = {
        "8309": {"code": "8309", "name": "三井住友トラスト", "market_value": 66160.0, "quantity": 40.0, "asset_type": "jp_stock"}
    }
    # 現在の保有（分割適用後: 160株, 270,160円）
    raw_holdings = [
        {"code": "8309", "name": "三井住友トラスト", "asset_type": "jp_stock", "market_value": 270160.0, "quantity": 160.0}
    ]
    mock_applied_splits = [
        {"code": "8309", "ratio": 4.0, "status": "applied"}
    ]

    with patch("history_manager.get_last_month_end_holdings_snapshot", return_value=("2026-07", mock_last_month_map)), \
         patch("history_manager.get_applied_split_alerts", return_value=mock_applied_splits):
        res = calculate_monthly_change_rankings(raw_holdings, {"JPY": 1.0})

        gainers = res["month_gainers_top10"]
        assert len(gainers) == 1
        g = gainers[0]
        assert g["code"] == "8309"
        # 66,160 * 4 = 264,640円 へ補正され、増減額が +5,520円 となること
        assert g["last_month_market_value"] == 264640.0
        assert g["monthly_change_jpy"] == 5520.0
        assert round(g["monthly_change_percent"], 1) == 2.1


def test_calculate_monthly_change_rankings_already_split_no_overcorrection():
    """既適用分割銘柄 (8053 住友商事等) が誤って二重補正されないことの検証テスト"""
    from portfolio_manager import calculate_monthly_change_rankings
    from unittest.mock import patch

    # 先月末スナップショット（既に120株、200,400円で保存済み）
    mock_last_month_map = {
        "8053": {"code": "8053", "name": "住友商事", "market_value": 200400.0, "quantity": 120.0, "asset_type": "jp_stock"}
    }
    # 現在の保有（120株, 201,360円）
    raw_holdings = [
        {"code": "8053", "name": "住友商事", "asset_type": "jp_stock", "market_value": 201360.0, "quantity": 120.0}
    ]
    mock_applied_splits = [
        {"code": "8053", "ratio": 4.0, "status": "applied"}
    ]

    with patch("history_manager.get_last_month_end_holdings_snapshot", return_value=("2026-07", mock_last_month_map)), \
         patch("history_manager.get_applied_split_alerts", return_value=mock_applied_splits):
        res = calculate_monthly_change_rankings(raw_holdings, {"JPY": 1.0})

        gainers = res["month_gainers_top10"]
        losers = res["month_losers_top10"]
        
        # 誤って 801,600円 に膨らみ巨額マイナス（減少TOP10）にならないこと
        assert len(losers) == 0
        assert len(gainers) == 1
        g = gainers[0]
        assert g["code"] == "8053"
        assert g["last_month_market_value"] == 200400.0
        assert g["monthly_change_jpy"] == 960.0


def test_calculate_monthly_change_rankings_with_purchased_quantity():
    """Issue #272: 当月追加購入株数 (purchased_quantity) および概算投資額 (approx_invested_jpy) の算出テスト"""
    from portfolio_manager import calculate_monthly_change_rankings
    from unittest.mock import patch

    # 先月末スナップショット: STOCK_A(100株, 100,000円)
    mock_last_month_map = {
        "STOCK_A": {"code": "STOCK_A", "name": "銘柄A", "market_value": 100000.0, "quantity": 100.0, "asset_type": "jp_stock"}
    }
    # 当日の保有: STOCK_A(130株, 143,000円 ➔ 買い増し+30株, 単価1,100円 ➔ 概算投資額 33,000円)
    raw_holdings = [
        {"code": "STOCK_A", "name": "銘柄A", "asset_type": "jp_stock", "market_value": 143000.0, "quantity": 130.0}
    ]

    with patch("history_manager.get_last_month_end_holdings_snapshot", return_value=("2026-07", mock_last_month_map)), \
         patch("history_manager.get_applied_split_alerts", return_value=[]):
        res = calculate_monthly_change_rankings(raw_holdings, {"JPY": 1.0})

        gainers = res["month_gainers_top10"]
        assert len(gainers) == 1
        g = gainers[0]
        assert g["code"] == "STOCK_A"
        assert g["purchased_quantity"] == 30.0
        assert g["approx_invested_jpy"] == 33000.0
        assert g["is_purchased_this_month"] is True


def test_calculate_monthly_change_rankings_purchased_quantity_with_split():
    """株式分割がある場合における当月買付株数の補正計算テスト"""
    from portfolio_manager import calculate_monthly_change_rankings
    from unittest.mock import patch

    # 先月末スナップショット（40株, 66,160円）
    mock_last_month_map = {
        "8309": {"code": "8309", "name": "三井住友トラスト", "market_value": 66160.0, "quantity": 40.0, "asset_type": "jp_stock"}
    }
    # 現在の保有（1:4分割適用で旧40株->160株 + 20株追加買い増し = 計180株, 306,000円 (単価1700円)）
    raw_holdings = [
        {"code": "8309", "name": "三井住友トラスト", "asset_type": "jp_stock", "market_value": 306000.0, "quantity": 180.0}
    ]
    mock_applied_splits = [
        {"code": "8309", "ratio": 4.0, "status": "applied"}
    ]

    with patch("history_manager.get_last_month_end_holdings_snapshot", return_value=("2026-07", mock_last_month_map)), \
         patch("history_manager.get_applied_split_alerts", return_value=mock_applied_splits):
        res = calculate_monthly_change_rankings(raw_holdings, {"JPY": 1.0})

        gainers = res["month_gainers_top10"]
        assert len(gainers) == 1
        g = gainers[0]
        assert g["code"] == "8309"
        # 40 * 4 = 160株が基準となり、180 - 160 = 20株買付
        assert g["purchased_quantity"] == 20.0
        # 概算投資額: 20株 * (306000/180 = 1700円) = 34,000円
        assert g["approx_invested_jpy"] == 34000.0
        assert g["is_purchased_this_month"] is True


def test_calculate_profit_taking_signal_issue273():
    """Issue #273: 配当年数倍率 (10年/15年/20年/30年分達成) の売り時・利確判定単体テスト"""
    from portfolio_manager import calculate_profit_taking_signal

    # 無配・含み損・ゼロ配当 ➔ None
    assert calculate_profit_taking_signal(-10000, 5000) is None
    assert calculate_profit_taking_signal(100000, 0) is None
    assert calculate_profit_taking_signal(0, 10000) is None

    # 10年分未満 (9.9年分) ➔ None
    assert calculate_profit_taking_signal(99000, 10000) is None

    # 10年分達成 (10.0〜14.9年分) ➔ Level 1 (💰 10年分)
    res10 = calculate_profit_taking_signal(100000, 10000)
    assert res10 is not None
    assert res10["level"] == 1
    assert res10["label"] == "10年分"
    assert res10["dividend_years_ratio"] == 10.0

    # 15年分達成 (15.0〜19.9年分) ➔ Level 2 (🧡 15年分)
    res15 = calculate_profit_taking_signal(154000, 10000)
    assert res15 is not None
    assert res15["level"] == 2
    assert res15["label"] == "15年分"
    assert res15["dividend_years_ratio"] == 15.4

    # 20年分達成 (20.0〜29.9年分) ➔ Level 3 (🔥 20年分)
    res20 = calculate_profit_taking_signal(220000, 10000)
    assert res20 is not None
    assert res20["level"] == 3
    assert res20["label"] == "20年分"
    assert res20["dividend_years_ratio"] == 22.0

    # 30年分達成 (30.0年分以上) ➔ Level 4 (💎 30年分)
    res30 = calculate_profit_taking_signal(350000, 10000)
    assert res30 is not None
    assert res30["level"] == 4
    assert res30["label"] == "30年分"
    assert res30["dividend_years_ratio"] == 35.0


def test_calculate_rankings_top20_issue274():
    """Issue #274: ランキング抽出枠が TOP20 へ拡大され、キーおよび最大20件が安全に取得できることを検証"""
    from portfolio_manager import calculate_daily_change_rankings, calculate_monthly_change_rankings
    from unittest.mock import patch

    # 25件のダミー保有銘柄
    raw_holdings = []
    for i in range(1, 26):
        raw_holdings.append({
            "code": f"CODE_{i}",
            "name": f"銘柄_{i}",
            "asset_type": "jp_stock",
            "quantity": 100.0,
            "change": float(i),
            "market_value": 100000.0 + i * 1000
        })

    daily_res = calculate_daily_change_rankings(raw_holdings, {"JPY": 1.0})
    assert "day_gainers_top20" in daily_res
    assert len(daily_res["day_gainers_top20"]) == 20
    assert daily_res["day_gainers_top20"][0]["code"] == "CODE_25"
    assert daily_res["day_gainers_top20"][0]["rank"] == 1
    assert daily_res["day_gainers_top20"][19]["rank"] == 20

    # 先月末スナップショット
    mock_snapshot = {
        f"CODE_{i}": {"code": f"CODE_{i}", "name": f"銘柄_{i}", "market_value": 100000.0, "quantity": 100.0, "asset_type": "jp_stock"}
        for i in range(1, 26)
    }

    with patch("history_manager.get_last_month_end_holdings_snapshot", return_value=("2026-07", mock_snapshot)), \
         patch("history_manager.get_applied_split_alerts", return_value=[]):
        monthly_res = calculate_monthly_change_rankings(raw_holdings, {"JPY": 1.0})
        assert "month_gainers_top20" in monthly_res
        assert len(monthly_res["month_gainers_top20"]) == 20
        assert monthly_res["month_gainers_top20"][0]["rank"] == 1
        assert monthly_res["month_gainers_top20"][19]["rank"] == 20



