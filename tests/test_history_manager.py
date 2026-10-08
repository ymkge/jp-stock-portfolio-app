"""
history_manager の売却履歴・待機資金プール・スナップショット集計テスト (#332)
AGENTS.md 0.2 に従い、本番DBを汚染しないよう一時SQLiteファイルで完全分離して検証する。
"""

import os
import tempfile
import sqlite3
import pytest
from unittest.mock import patch

def test_realized_trades_and_reinvestment_pool_isolated():
    """一時DBを用いた realized_trades および reinvestment_pool のCRUD動作検証"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
        tmp_db_path = tmp_db.name

    try:
        with patch("history_manager.DB_FILE", tmp_db_path):
            import history_manager
            # テーブル初期化
            history_manager.init_db()

            # 1. reinvestment_pool の初期値
            balance0 = history_manager.get_reinvestment_pool_balance("JPY")
            assert balance0 == 0.0

            # 2. update_reinvestment_pool_balance
            new_bal = history_manager.update_reinvestment_pool_balance(100000.0, "JPY")
            assert new_bal == 100000.0
            assert history_manager.get_reinvestment_pool_balance("JPY") == 100000.0

            # 3. 減額（0円未満にはならないクランプ機能）
            bal_reduced = history_manager.update_reinvestment_pool_balance(-40000.0, "JPY")
            assert bal_reduced == 60000.0

            # 4. 超過減額時の下限ガード
            bal_clamped = history_manager.update_reinvestment_pool_balance(-100000.0, "JPY")
            assert bal_clamped == 0.0

            # 5. set_reinvestment_pool_balance（直接設定）
            bal_set = history_manager.set_reinvestment_pool_balance(50000.0, "JPY")
            assert bal_set == 50000.0
            assert history_manager.get_reinvestment_pool_balance("JPY") == 50000.0

            # 6. realized_trades への売却履歴追加
            trade_id = history_manager.add_realized_trade(
                code="7203",
                name="トヨタ自動車",
                asset_type="jp_stock",
                account_type="特定口座",
                quantity=100.0,
                sell_price=3000.0,
                purchase_price=2000.0,
                sold_date="2026-10-08",
                security_company="SBI証券",
                currency="JPY",
                exchange_rate=1.0
            )
            assert trade_id > 0

            # 7. 履歴取得
            trades = history_manager.get_realized_trades()
            assert len(trades) == 1
            t = trades[0]
            assert t["code"] == "7203"
            assert t["sell_amount_jpy"] == 300000.0
            assert t["purchase_amount_jpy"] == 200000.0
            assert t["realized_pl_jpy"] == 100000.0
            assert t["realized_pl_rate"] == 50.0

            # 8. サマリー集計
            summary = history_manager.get_realized_summary(2026)
            assert summary["total_pl_jpy"] == 100000.0
            assert summary["trade_count"] == 1
            assert summary["win_count"] == 1
            assert summary["loss_count"] == 0
            assert summary["win_rate"] == 100.0

    finally:
        if os.path.exists(tmp_db_path):
            os.remove(tmp_db_path)
