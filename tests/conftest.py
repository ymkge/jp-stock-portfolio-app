import pytest
import os
import history_manager
import sync_history

@pytest.fixture(autouse=True)
def guard_production_db(tmp_path):
    """
    全自動テスト実行時の本番DB物理隔離・保護フィクスチャ (#284)。
    history_manager および sync_history の DB_FILE を tmp_path 配下の一時ファイルに切り替え、
    本番 portfolio_history.db への物理的な書き込み・読み込みを全テストで遮断する。
    """
    original_hm_db = history_manager.DB_FILE
    original_sh_db = sync_history.DB_FILE

    test_db = str(tmp_path / "test_isolated_history.db")
    history_manager.DB_FILE = test_db
    sync_history.DB_FILE = test_db

    history_manager.init_db()

    yield

    history_manager.DB_FILE = original_hm_db
    sync_history.DB_FILE = original_sh_db
