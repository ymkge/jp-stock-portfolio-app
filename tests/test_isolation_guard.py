import sqlite3
import os
import history_manager

def test_production_db_not_polluted_by_tests():
    """本番DB (portfolio_history.db) にテストデータ (9999) が一切混入していないことを検証 (#284)"""
    prod_db = "portfolio_history.db"
    if not os.path.exists(prod_db):
        return

    conn = sqlite3.connect(prod_db)
    cursor = conn.cursor()
    
    # 1. split_alerts に 9999 が存在しないことを検証
    cursor.execute("SELECT COUNT(*) FROM split_alerts WHERE code = '9999'")
    count_split = cursor.fetchone()[0]

    # 2. portfolio_history に 9999 が存在しないことを検証
    cursor.execute("SELECT COUNT(*) FROM portfolio_history WHERE code = '9999'")
    count_history = cursor.fetchone()[0]

    conn.close()

    assert count_split == 0, "本番DBの split_alerts にテスト用銘柄9999が検出されました！"
    assert count_history == 0, "本番DBの portfolio_history にテスト用銘柄9999が検出されました！"


def test_guard_fixture_uses_tmp_db():
    """テスト実行時の DB_FILE が本番DBではなく一時DBを指していることを検証 (#284)"""
    assert history_manager.DB_FILE != "portfolio_history.db"
    assert "test_isolated_history.db" in history_manager.DB_FILE or "test_" in history_manager.DB_FILE
