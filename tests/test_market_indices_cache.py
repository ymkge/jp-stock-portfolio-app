import pytest
import asyncio
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
import zoneinfo

from app import _get_processed_asset_data
import history_manager

JST = zoneinfo.ZoneInfo("Asia/Tokyo")

def test_market_indices_stale_cache_triggers_scraping():
    """古いDBキャッシュ(前日以前)が存在する場合、market_indexはスクレイピングを実行して最新データを取得すること"""
    dummy_portfolio = [
        {"code": "7203", "name": "トヨタ自動車", "asset_type": "jp_stock", "shares": 100, "purchase_price": 2000}
    ]
    
    stale_db_cache = {
        "7203": {
            "code": "7203", "name": "トヨタ自動車", "price": 2500,
            "_db_updated_at_jst": "2026-08-29T19:41:00+09:00"
        },
        "998407.O": {
            "code": "998407.O", "name": "日経平均株価", "price": "66405", "change": "273.58", "change_percent": "0.41",
            "_db_updated_at_jst": "2026-08-29T19:41:07+09:00"
        }
    }
    
    market_config = [{"code": "998407.O", "name": "日経平均株価"}]
    
    mock_scraped_index = {
        "code": "998407.O", "name": "日経平均株価", "price": "63492", "change": "-518.35", "change_percent": "-0.81",
        "asset_type": "market_index"
    }

    mock_scraper = MagicMock()
    mock_scraper.cache = {}
    mock_scraper.is_cached.return_value = False
    mock_scraper.fetch_data.return_value = mock_scraped_index

    with patch("app.portfolio_manager.load_portfolio", return_value=dummy_portfolio),          patch("app.history_manager.get_latest_daily_data_all", return_value=stale_db_cache),          patch("app.get_config") as mock_cfg,          patch("app.scraper.get_scraper", return_value=mock_scraper),          patch("app.sync_manager.start_sync_if_needed") as mock_sync:
        
        def config_side_effect(path, default=None):
            if path == "market_indices":
                return market_config
            if path == "system.scraping.concurrency_limit":
                return 5
            return default if default is not None else {}
        
        mock_cfg.side_effect = config_side_effect
        
        assets, metadata = asyncio.run(_get_processed_asset_data(force=False))
        
        assert len(assets) == 1
        assert assets[0]["price"] == 2500
        
        indices = metadata.get("market_indices", [])
        assert len(indices) == 1
        assert indices[0]["price"] == "63492"
        assert indices[0]["change"] == "-518.35"
        
        mock_scraper.fetch_data.assert_called_with("998407.O")


def test_market_indices_fresh_cache_uses_db():
    """直近(10分前)の新鮮なDBキャッシュが存在する場合、market_indexはスクレイピングを行わずDBキャッシュを使うこと"""
    dummy_portfolio = [
        {"code": "7203", "name": "トヨタ自動車", "asset_type": "jp_stock", "shares": 100, "purchase_price": 2000}
    ]
    now = datetime.now(JST)
    fresh_time_str = (now - timedelta(minutes=10)).isoformat()
    
    fresh_db_cache = {
        "7203": {
            "code": "7203", "name": "トヨタ自動車", "price": 2500,
            "_db_updated_at_jst": fresh_time_str
        },
        "998407.O": {
            "code": "998407.O", "name": "日経平均株価", "price": "63492", "change": "-518.35", "change_percent": "-0.81",
            "_db_updated_at_jst": fresh_time_str
        }
    }
    
    market_config = [{"code": "998407.O", "name": "日経平均株価"}]

    mock_scraper = MagicMock()
    mock_scraper.cache = {}
    mock_scraper.is_cached.return_value = False

    with patch("app.portfolio_manager.load_portfolio", return_value=dummy_portfolio),          patch("app.history_manager.get_latest_daily_data_all", return_value=fresh_db_cache),          patch("app.get_config") as mock_cfg,          patch("app.scraper.get_scraper", return_value=mock_scraper):
        
        def config_side_effect(path, default=None):
            if path == "market_indices":
                return market_config
            if path == "system.scraping.concurrency_limit":
                return 5
            return default if default is not None else {}
        
        mock_cfg.side_effect = config_side_effect
        
        assets, metadata = asyncio.run(_get_processed_asset_data(force=False))
        
        indices = metadata.get("market_indices", [])
        assert len(indices) == 1
        assert indices[0]["price"] == "63492"
        
        mock_scraper.fetch_data.assert_not_called()


def test_usdjpy_overwritten_by_exchange_rate_detail():
    """USDJPY=X に古いキャッシュ値があっても get_exchange_rate_detail の最新レートで確実に上書きされること"""
    dummy_portfolio = [
        {"code": "7203", "name": "トヨタ自動車", "asset_type": "jp_stock", "shares": 100, "purchase_price": 2000}
    ]
    stale_db_cache = {
        "7203": {
            "code": "7203", "name": "トヨタ自動車", "price": 2500,
            "_db_updated_at_jst": "2026-08-29T19:41:00+09:00"
        },
        "USDJPY=X": {
            "code": "USDJPY=X", "name": "アメリカ ドル / 日本 円", "price": "153.5500",
            "change": None, "change_percent": None,
            "_db_updated_at_jst": "2026-08-29T19:41:07+09:00"
        }
    }
    
    market_config = [{"code": "USDJPY=X", "name": "アメリカ ドル / 日本 円"}]
    
    mock_fx_detail = {
        "pair": "USDJPY=X",
        "name": "ドル円",
        "price": "154.5600",
        "change": "0.45",
        "change_percent": "0.29%",
        "high": "154.80",
        "low": "153.90",
        "high_52w": "163.98",
        "low_52w": "146.22",
        "peak_diff_percent": "-5.7%"
    }

    mock_scraper = MagicMock()
    mock_scraper.cache = {}
    mock_scraper.is_cached.return_value = False
    mock_scraper.fetch_data.return_value = {
        "code": "USDJPY=X", "name": "アメリカ ドル / 日本 円", "price": "153.5500"
    }

    with patch("app.portfolio_manager.load_portfolio", return_value=dummy_portfolio),          patch("app.history_manager.get_latest_daily_data_all", return_value=stale_db_cache),          patch("app.get_config") as mock_cfg,          patch("app.scraper.get_scraper", return_value=mock_scraper),          patch("app.scraper.get_exchange_rate_detail", return_value=mock_fx_detail),          patch("app.history_manager.save_daily_data") as mock_save:
        
        def config_side_effect(path, default=None):
            if path == "market_indices":
                return market_config
            if path == "system.scraping.concurrency_limit":
                return 5
            return default if default is not None else {}
        
        mock_cfg.side_effect = config_side_effect
        
        assets, metadata = asyncio.run(_get_processed_asset_data(force=False))
        
        indices = metadata.get("market_indices", [])
        assert len(indices) == 1
        assert indices[0]["price"] == "154.5600"
        assert indices[0]["change"] == "0.45"
        assert indices[0]["change_percent"] == "0.29%"
        assert indices[0]["high_52w"] == "163.98"
        
        mock_save.assert_called()
