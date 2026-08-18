"""
案件 #262: バックグラウンドデータ同期・即時キャッシュ返却・ステータスAPIのテスト
"""
import pytest
import time
import asyncio
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app import app, BackgroundSyncManager, sync_manager, _get_processed_asset_data

client = TestClient(app)

def test_sync_status_api_schema():
    """GET /api/portfolio/sync_status エンドポイントのレスポンス検証"""
    response = client.get("/api/portfolio/sync_status")
    assert response.status_code == 200
    data = response.json()
    assert "is_syncing" in data
    assert "status" in data
    assert "total_count" in data
    assert "completed_count" in data
    assert "current_code" in data
    assert "current_name" in data


def test_background_sync_manager_singleton():
    """BackgroundSyncManager のシングルトン設計と辞書変換の検証"""
    mgr1 = BackgroundSyncManager.get_instance()
    mgr2 = BackgroundSyncManager.get_instance()
    assert mgr1 is mgr2
    d = mgr1.to_dict()
    assert isinstance(d, dict)
    assert d["status"] in ["idle", "syncing", "completed", "circuit_broken", "error"]


@patch("app.portfolio_manager.load_portfolio")
def test_sync_start_api(mock_load_portfolio):
    """POST /api/portfolio/sync/start の手動トリガー起動テスト"""
    mock_load_portfolio.return_value = [
        {"code": "9999", "name": "トヨタ", "asset_type": "jp_stock"}
    ]
    response = client.post("/api/portfolio/sync/start")
    assert response.status_code == 200
    data = response.json()
    assert "is_syncing" in data


@pytest.mark.anyio
async def test_instant_response_when_db_cache_exists():
    """
    検証事項1: force=False 時はDBキャッシュが存在すれば経過時間に関わらず0.1秒未満で即時返却されること
    """
    dummy_portfolio = [
        {"code": "9999", "name": "ダミー企業", "asset_type": "jp_stock", "quantity": 100, "purchase_price": 2000}
    ]
    dummy_db_cache = {
        "9999": {
            "code": "9999",
            "name": "ダミー企業",
            "price": 2500,
            "previous_close": 2480,
            "per": 10.5,
            "pbr": 1.1,
            "roe": 10.0,
            "dividend_yield": 2.8,
            "market_cap": 30000000000000,
            "high_52week": 3000,
            "low_52week": 1800,
            "asset_type": "jp_stock",
            "_db_date": "2026-01-01",
            "_db_updated_at_jst": "2026-01-01T09:00:00+09:00"
        }
    }

    def mock_get_config_side_effect(path, default=None):
        if path == "market_indices":
            return []
        return default if default is not None else 1

    with patch("app.portfolio_manager.load_portfolio", return_value=dummy_portfolio), \
         patch("app.history_manager.get_latest_daily_data_all", return_value=dummy_db_cache), \
         patch("app.history_manager.get_pending_split_alerts", return_value=[]), \
         patch("app.history_manager.save_daily_data") as mock_save_daily, \
         patch("app.get_config", side_effect=mock_get_config_side_effect), \
         patch("app.scraper.get_scraper") as mock_get_scraper:
        
        mock_scraper_inst = MagicMock()
        mock_scraper_inst.is_cached.return_value = False
        mock_scraper_inst.cache = {}
        mock_get_scraper.return_value = mock_scraper_inst

        start = time.perf_counter()
        processed_data, metadata = await _get_processed_asset_data(force=False)
        elapsed = time.perf_counter() - start

        # 0.1秒未満で返却されることを検証 (DBキャッシュ参照)
        assert elapsed < 0.1, f"Response time was {elapsed:.4f}s, expected < 0.1s"
        assert len(processed_data) == 1
        assert processed_data[0]["code"] == "9999"
        assert processed_data[0]["price"] == 2500
        # スクレイピングのネットワーク通信 (fetch_data) は実行されないこと
        mock_scraper_inst.fetch_data.assert_not_called()


@pytest.mark.anyio
async def test_background_sync_manager_concurrency_and_circuit_breaker():
    """
    検証事項2: 二重起動防止(asyncio.Lock)および 403 サーキットブレーカー安全停止が機能すること
    """
    manager = BackgroundSyncManager()
    assert manager.is_syncing is False
    assert manager.status == "idle"

    # 1. 二重起動防止テスト
    manager.is_syncing = True
    manager.status = "syncing"
    stale_items = [{"code": "9999", "asset_type": "jp_stock", "name": "トヨタ"}]
    
    # 既に is_syncing=True の状態なので start_sync_if_needed はスキップされるべき
    await manager.start_sync_if_needed(stale_items, 1)
    # create_task は実行されず、状態が維持される
    assert manager.is_syncing is True

    # リセット
    manager.is_syncing = False
    manager.status = "idle"

    # 2. 403 サーキットブレーカーテスト
    with patch("app.scraper.get_scraper") as mock_get_scraper, \
         patch("asyncio.sleep", return_value=None):
        
        mock_scraper = MagicMock()
        mock_scraper.fetch_data.return_value = {
            "code": "9999",
            "error": "Access Denied",
            "error_details": {"status_code": 403}
        }
        mock_get_scraper.return_value = mock_scraper

        # _run_sync を直接実行して動作検証
        await manager._run_sync(stale_items)

        assert manager.status == "circuit_broken"
        assert manager.is_syncing is False
        assert "403" in manager.error_message


def test_banner_elements_in_html_and_polling_in_js():
    """
    検証事項4: HTMLに進捗バナー(#sync-status-banner)が配置され、JSのポーリングが含まれていること
    """
    # 1. index.html
    res_index = client.get("/")
    assert res_index.status_code == 200
    assert 'id="sync-status-banner"' in res_index.text

    # 2. analysis.html
    res_analysis = client.get("/analysis")
    assert res_analysis.status_code == 200
    assert 'id="sync-status-banner"' in res_analysis.text

    # 3. main.js のポーリングコード確認
    with open("static/js/main.js", "r", encoding="utf-8") as f:
        main_js = f.read()
    assert "/api/portfolio/sync_status" in main_js
    assert "setInterval(" in main_js
    assert "3000" in main_js

    # 4. analysis.js のポーリングコード確認
    with open("static/js/analysis.js", "r", encoding="utf-8") as f:
        analysis_js = f.read()
    assert "/api/portfolio/sync_status" in analysis_js
    assert "setInterval(" in analysis_js
    assert "3000" in analysis_js

    # 5. Issue #264: 同期中の旧レポート非表示化ロジック (updateReportContainer hidden & isSyncing ガード) の存在を検証
    assert 'updateReportContainer.classList.add(\'hidden\')' in main_js or 'updateReportContainer.classList.add("hidden")' in main_js
    assert 'updateReportContainer.classList.add(\'hidden\')' in analysis_js or 'updateReportContainer.classList.add("hidden")' in analysis_js
    assert 'isSyncing' in main_js
    assert 'isSyncing' in analysis_js

    # 6. Issue #265: 更新完了時の表記が toLocaleString() (日時情報) でフォーマットされていることを検証
    assert 'toLocaleString()' in main_js
    assert 'toLocaleString()' in analysis_js

