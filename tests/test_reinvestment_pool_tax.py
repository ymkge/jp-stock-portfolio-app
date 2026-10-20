"""
売却取引履歴および待機資金モーダルにおける税金・税引後金額表示の検証テスト (#351)
AGENTS.md 0.2 に従い、本番DBを汚染しないよう一時SQLiteファイルおよびモックで完全分離して検証する。
"""

import os
import tempfile
import sqlite3
import pytest
from unittest.mock import patch, MagicMock

import history_manager
import portfolio_manager

def test_calculate_trade_tax_logic():
    """calculate_trade_tax の税計算・端数処理・非課税・損失時動作の検証"""
    # 1. 特定口座での利益売却（譲渡益税率 20.315%、円未満切り捨て math.floor）
    # 利益: 100,000円 -> 税額: floor(100,000 * 0.20315) = 20,315円
    res_tokutei = history_manager.calculate_trade_tax("特定口座", 100000.0, 300000.0)
    assert res_tokutei["is_taxable"] is True
    assert res_tokutei["tax_rate"] == 0.20315
    assert res_tokutei["tax_jpy"] == 20315.0
    assert res_tokutei["after_tax_pl_jpy"] == 79685.0
    assert res_tokutei["after_tax_sell_amount_jpy"] == 279685.0

    # 端数切り捨てテスト: 利益 1,234円 -> 1,234 * 0.20315 = 250.6871 -> floor = 250円
    res_fraction = history_manager.calculate_trade_tax("特定口座", 1234.0, 50000.0)
    assert res_fraction["tax_jpy"] == 250.0
    assert res_fraction["after_tax_pl_jpy"] == 984.0

    # 2. 新NISA口座での利益売却（非課税: 税率0%、税額0円）
    res_nisa = history_manager.calculate_trade_tax("新NISA", 100000.0, 300000.0)
    assert res_nisa["is_taxable"] is False
    assert res_nisa["tax_rate"] == 0.0
    assert res_nisa["tax_jpy"] == 0.0
    assert res_nisa["after_tax_pl_jpy"] == 100000.0
    assert res_nisa["after_tax_sell_amount_jpy"] == 300000.0

    # 旧NISA口座 / NISA(成長投資枠)などの口座名
    res_growth_nisa = history_manager.calculate_trade_tax("NISA(成長投資枠)", 50000.0, 150000.0)
    assert res_growth_nisa["is_taxable"] is False
    assert res_growth_nisa["tax_jpy"] == 0.0

    # 3. 損失時（realized_pl_jpy <= 0）: 課税口座でも税額 0円にクランプ
    res_loss = history_manager.calculate_trade_tax("特定口座", -30000.0, 70000.0)
    assert res_loss["tax_jpy"] == 0.0
    assert res_loss["after_tax_pl_jpy"] == -30000.0
    assert res_loss["after_tax_sell_amount_jpy"] == 70000.0

    # 4. 利益 0円時
    res_zero = history_manager.calculate_trade_tax("特定口座", 0.0, 100000.0)
    assert res_zero["tax_jpy"] == 0.0
    assert res_zero["after_tax_pl_jpy"] == 0.0
    assert res_zero["after_tax_sell_amount_jpy"] == 100000.0


def test_realized_trades_tax_integration_isolated():
    """一時DBを用いた realized_trades の税金・税引後金額の保存・動的補完・サマリー合算検証"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
        tmp_db_path = tmp_db.name

    try:
        with patch("history_manager.DB_FILE", tmp_db_path):
            history_manager.init_db()

            # 取引1: 特定口座で利益（売却額 300,000円, 取得額 200,000円, 利益 100,000円）
            id1 = history_manager.add_realized_trade(
                code="7203",
                name="トヨタ自動車",
                asset_type="jp_stock",
                account_type="特定口座",
                quantity=100.0,
                sell_price=3000.0,
                purchase_price=2000.0,
                sold_date="2026-10-01",
                fee_jpy=0.0
            )

            # 取引2: 新NISA口座で利益（売却額 200,000円, 取得額 150,000円, 利益 50,000円）
            id2 = history_manager.add_realized_trade(
                code="8306",
                name="三菱UFJ",
                asset_type="jp_stock",
                account_type="新NISA",
                quantity=200.0,
                sell_price=1000.0,
                purchase_price=750.0,
                sold_date="2026-10-02",
                fee_jpy=0.0
            )

            # 取引3: 特定口座で損失（売却額 70,000円, 取得額 100,000円, 損失 -30,000円）
            id3 = history_manager.add_realized_trade(
                code="9984",
                name="ソフトバンクG",
                asset_type="jp_stock",
                account_type="特定口座",
                quantity=10.0,
                sell_price=7000.0,
                purchase_price=10000.0,
                sold_date="2026-10-03",
                fee_jpy=0.0
            )

            # 1. 履歴取得の検証
            trades = history_manager.get_realized_trades()
            assert len(trades) == 3

            # 取引3（最新降順）: ソフトバンクG (損失)
            t_sb = next(t for t in trades if t["code"] == "9984")
            assert t_sb["realized_pl_jpy"] == -30000.0
            assert t_sb["tax_jpy"] == 0.0
            assert t_sb["after_tax_pl_jpy"] == -30000.0
            assert t_sb["after_tax_sell_amount_jpy"] == 70000.0

            # 取引2: 三菱UFJ (NISA非課税)
            t_mufg = next(t for t in trades if t["code"] == "8306")
            assert t_mufg["realized_pl_jpy"] == 50000.0
            assert t_mufg["tax_jpy"] == 0.0
            assert t_mufg["after_tax_pl_jpy"] == 50000.0
            assert t_mufg["after_tax_sell_amount_jpy"] == 200000.0
            assert t_mufg["is_taxable"] is False

            # 取引1: トヨタ (特定口座 利益)
            t_toyota = next(t for t in trades if t["code"] == "7203")
            assert t_toyota["realized_pl_jpy"] == 100000.0
            assert t_toyota["tax_jpy"] == 20315.0
            assert t_toyota["after_tax_pl_jpy"] == 79685.0
            assert t_toyota["after_tax_sell_amount_jpy"] == 279685.0
            assert t_toyota["is_taxable"] is True

            # 2. サマリー集計の検証
            summary = history_manager.get_realized_summary(2026)
            # total_pl = 100,000 + 50,000 - 30,000 = 120,000円
            assert summary["total_pl_jpy"] == 120000.0
            # total_tax = 20,315 + 0 + 0 = 20,315円
            assert summary["total_tax_jpy"] == 20315.0
            # total_after_tax_pl = 79,685 + 50,000 - 30,000 = 99,685円
            assert summary["total_after_tax_pl_jpy"] == 99685.0
            # total_after_tax_sell_amount = 279,685 + 200,000 + 70,000 = 549,685円
            assert summary["total_after_tax_sell_amount_jpy"] == 549685.0
            assert summary["trade_count"] == 3
            assert summary["win_count"] == 2
            assert summary["loss_count"] == 1

            # 3. 過去データ（DB内の tax_jpy が 0.0 のレコード）に対する動的補完テスト
            # 直接DBの tax_jpy, after_tax_pl_jpy を 0.0 に更新してシミュレート
            with sqlite3.connect(tmp_db_path) as conn:
                conn.execute("UPDATE realized_trades SET tax_jpy = 0.0, after_tax_pl_jpy = 0.0 WHERE code = '7203'")
                conn.commit()

            # get_realized_trades 呼び出し時に calculate_trade_tax による動的補完が発動することを確認
            recovered_trades = history_manager.get_realized_trades()
            t_toyota_rec = next(t for t in recovered_trades if t["code"] == "7203")
            assert t_toyota_rec["tax_jpy"] == 20315.0
            assert t_toyota_rec["after_tax_pl_jpy"] == 79685.0
            assert t_toyota_rec["after_tax_sell_amount_jpy"] == 279685.0

    finally:
        if os.path.exists(tmp_db_path):
            os.remove(tmp_db_path)


def test_portfolio_sell_holding_with_tax():
    """sell_holding が税金情報を正しく計算して返却・永続化することの検証"""
    mock_portfolio = [
        {
            "code": "7203",
            "name": "トヨタ自動車",
            "asset_type": "jp_stock",
            "currency": "JPY",
            "holdings": [
                {
                    "id": "h_1",
                    "quantity": 100.0,
                    "purchase_price": 2000.0,
                    "account_type": "特定口座",
                    "security_company": "SBI証券"
                }
            ]
        }
    ]

    with patch("portfolio_manager.load_portfolio", return_value=mock_portfolio), \
         patch("portfolio_manager.save_portfolio"), \
         patch("history_manager.update_reinvestment_pool_balance", return_value=299000.0) as mock_update_pool, \
         patch("history_manager.add_realized_trade", return_value=1) as mock_add_trade:

        result = portfolio_manager.sell_holding(
            holding_id="h_1",
            quantity=100.0,
            sell_price=3000.0,
            fee_jpy=1000.0,
            sold_date="2026-10-15"
        )

        assert result["code"] == "7203"
        assert result["sell_amount_jpy"] == 300000.0
        assert result["fee_jpy"] == 1000.0
        assert result["net_sell_amount_jpy"] == 299000.0
        assert result["realized_pl_jpy"] == 99000.0  # 299,000 - 200,000

        # 税金: floor(99,000 * 0.20315) = 20,111円
        assert result["tax_jpy"] == 20111.0
        assert result["after_tax_pl_jpy"] == 78889.0  # 99,000 - 20,111
        assert result["after_tax_sell_amount_jpy"] == 278889.0  # 299,000 - 20,111
        assert result["is_taxable"] is True

        # add_realized_trade への引数検証
        mock_add_trade.assert_called_once()
        call_kwargs = mock_add_trade.call_args[1]
        assert call_kwargs["tax_jpy"] == 20111.0
        assert call_kwargs["after_tax_pl_jpy"] == 78889.0


def test_api_reinvestment_pool_endpoint():
    """/api/reinvestment-pool エンドポイントが税金・税引後フィールドを正常に返却することの検証"""
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)

    mock_summary = {
        "total_pl_jpy": 120000.0,
        "total_tax_jpy": 20315.0,
        "total_after_tax_pl_jpy": 99685.0,
        "total_after_tax_sell_amount_jpy": 549685.0,
        "trade_count": 3,
        "win_count": 2,
        "loss_count": 1,
        "win_rate": 66.7
    }

    mock_trades = [
        {
            "id": 1,
            "code": "7203",
            "name": "トヨタ自動車",
            "account_type": "特定口座",
            "quantity": 100.0,
            "sell_price": 3000.0,
            "purchase_price": 2000.0,
            "sell_amount_jpy": 300000.0,
            "realized_pl_jpy": 100000.0,
            "tax_jpy": 20315.0,
            "after_tax_pl_jpy": 79685.0,
            "after_tax_sell_amount_jpy": 279685.0,
            "is_taxable": True,
            "sold_date": "2026-10-01"
        }
    ]

    with patch("history_manager.get_reinvestment_pool_balance", return_value=500000.0), \
         patch("history_manager.get_realized_summary", return_value=mock_summary), \
         patch("history_manager.get_realized_trades", return_value=mock_trades):

        res = client.get("/api/reinvestment-pool")
        assert res.status_code == 200
        data = res.json()
        assert data["balance"] == 500000.0
        assert data["realized_summary"]["total_tax_jpy"] == 20315.0
        assert data["realized_summary"]["total_after_tax_pl_jpy"] == 99685.0
        assert len(data["recent_trades"]) == 1
        t = data["recent_trades"][0]
        assert t["tax_jpy"] == 20315.0
        assert t["after_tax_pl_jpy"] == 79685.0
        assert t["after_tax_sell_amount_jpy"] == 279685.0
        assert t["is_taxable"] is True


def test_index_html_and_css_tax_elements():
    """index.html および style.css に税金・税引後関連のUI要素・スタイルが存在することの検証"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html_path = os.path.join(base_dir, "templates", "index.html")
    css_path = os.path.join(base_dir, "static", "css", "style.css")

    # index.html の検証
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    assert 'id="modal-realized-after-tax-container"' in html_content
    assert 'id="modal-realized-after-tax-val"' in html_content
    assert 'id="modal-realized-tax-total-val"' in html_content
    assert 'id="sell-preview-tax-row"' in html_content
    assert 'id="sell-preview-tax-amount"' in html_content
    assert 'id="sell-preview-after-tax-pl"' in html_content

    # style.css の検証
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    assert ".trade-history-item" in css_content
    assert ".badge-account" in css_content
    assert ".badge-account-tokutei" in css_content
    assert ".badge-account-nisa" in css_content
    assert ".trade-tax-val" in css_content
    assert ".trade-tax-nisa" in css_content
    assert ".trade-after-tax-val" in css_content
