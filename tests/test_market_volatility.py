import os
import json
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

import app
import scraper
from llm_service import LLMDiagnosisService


client = TestClient(app.app)


# ==========================================
# 1. 急変動判定ロジック (evaluate_market_volatility) のテスト
# ==========================================
def test_evaluate_market_volatility_index_thresholds():
    """株式指数（日経平均・TOPIX等）の急変動閾値（±1.5%）の境界値テスト"""
    vol_cfg = {
        "enabled": True,
        "index_change_percent_threshold": 1.5,
        "fx_change_yen_threshold": 1.0,
        "fx_change_percent_threshold": 0.7,
    }

    # 1. +1.50% -> 急騰 (is_volatile=True, up)
    item_up = {"name": "日経平均", "code": "998407.O", "change": "+580.00", "change_percent": "+1.50", "is_fx": False}
    res_up = app.evaluate_market_volatility(item_up, vol_cfg)
    assert res_up["is_volatile"] is True
    assert res_up["volatility_direction"] == "up"
    assert "急騰" in res_up["volatility_label"]

    # 2. -1.85% -> 急落 (is_volatile=True, down)
    item_down = {"name": "TOPIX", "code": "998405.T", "change": "-50.2", "change_percent": "-1.85%", "is_fx": False}
    res_down = app.evaluate_market_volatility(item_down, vol_cfg)
    assert res_down["is_volatile"] is True
    assert res_down["volatility_direction"] == "down"
    assert "急落" in res_down["volatility_label"]

    # 3. +1.49% -> 平常 (is_volatile=False)
    item_normal = {"name": "日経平均", "code": "998407.O", "change": "+400", "change_percent": "1.49", "is_fx": False}
    res_normal = app.evaluate_market_volatility(item_normal, vol_cfg)
    assert res_normal["is_volatile"] is False
    assert res_normal["volatility_direction"] is None
    assert res_normal["volatility_label"] is None


def test_evaluate_market_volatility_fx_thresholds():
    """為替（ドル円）の急変動閾値（±1.0円 または ±0.7%）の境界値テスト"""
    vol_cfg = {
        "enabled": True,
        "index_change_percent_threshold": 1.5,
        "fx_change_yen_threshold": 1.0,
        "fx_change_percent_threshold": 0.7,
    }

    # 1. +1.05円 (+0.68%) -> 円幅閾値で円安急進検知
    fx_yen_up = {"name": "ドル円", "code": "USDJPY=X", "change": "+1.05", "change_percent": "+0.68", "is_fx": True}
    res1 = app.evaluate_market_volatility(fx_yen_up, vol_cfg)
    assert res1["is_volatile"] is True
    assert res1["volatility_direction"] == "up"
    assert "円安急進" in res1["volatility_label"]

    # 2. -0.85円 (-0.75%) -> 率閾値で円高急進検知
    fx_pct_down = {"name": "ドル円", "code": "USDJPY=X", "change": "-0.85", "change_percent": "-0.75%", "is_fx": True}
    res2 = app.evaluate_market_volatility(fx_pct_down, vol_cfg)
    assert res2["is_volatile"] is True
    assert res2["volatility_direction"] == "down"
    assert "円高急進" in res2["volatility_label"]

    # 3. +0.40円 (+0.26%) -> 平常
    fx_normal = {"name": "ドル円", "code": "USDJPY=X", "change": "+0.40", "change_percent": "+0.26%", "is_fx": True}
    res3 = app.evaluate_market_volatility(fx_normal, vol_cfg)
    assert res3["is_volatile"] is False
    assert res3["volatility_direction"] is None

    # 4. enabled=False の場合は常に False
    fx_disabled = {"name": "ドル円", "code": "USDJPY=X", "change": "+2.50", "change_percent": "+1.60%", "is_fx": True}
    res4 = app.evaluate_market_volatility(fx_disabled, {"enabled": False})
    assert res4["is_volatile"] is False


# ==========================================
# 2. 市況・為替ニュースRSS取得 (scraper.fetch_market_news_headlines) のテスト
# ==========================================
def test_fetch_market_news_headlines_parsing_and_security():
    """RSS XMLパース、HTMLアンエスケープ、重複排除、危険なURLスキーム除外のテスト"""
    sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>市況ニュース</title>
        <item>
          <title>日経平均が大幅続伸、半導体株に買い &amp; 円安進行 - ロイター</title>
          <link>https://example.com/news/1</link>
          <pubDate>Fri, 23 Oct 2026 06:00:00 GMT</pubDate>
          <source>ロイター</source>
        </item>
        <item>
          <title>日経平均が大幅続伸、半導体株に買い &amp; 円安進行 - ロイター</title>
          <link>https://example.com/news/1-dup</link>
          <pubDate>Fri, 23 Oct 2026 06:05:00 GMT</pubDate>
        </item>
        <item>
          <title>不正スキームテスト記事</title>
          <link>javascript:alert(1)</link>
          <pubDate>Fri, 23 Oct 2026 06:10:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = sample_xml.encode("utf-8")

    scraper._market_news_cache["items"] = []
    scraper._market_news_cache["timestamp"] = 0.0

    with patch("scraper.requests.get", return_value=mock_resp) as mock_get:
        items = scraper.fetch_market_news_headlines(limit=10, force=True)
        # 重複した記事と javascript: スキーム記事は両方除外され、安全な1件のみ残ること
        assert len(items) == 1
        assert items[0]["title"] == "日経平均が大幅続伸、半導体株に買い & 円安進行"
        assert items[0]["source"] == "ロイター"
        assert items[0]["url"] == "https://example.com/news/1"
        assert items[0]["link"] == "https://example.com/news/1"

        # キャッシュヒット確認（2回目は通信しない）
        call_count_after_first = mock_get.call_count
        cached_items = scraper.fetch_market_news_headlines(limit=10, force=False)
        assert len(cached_items) == 1
        assert mock_get.call_count == call_count_after_first


def test_fetch_market_news_headlines_network_failure_fallback():
    """RSS取得時にネットワーク例外が発生しても例外を送出せず空リストを返すテスト"""
    scraper._market_news_cache["items"] = []
    scraper._market_news_cache["timestamp"] = 0.0

    with patch("scraper.requests.get", side_effect=Exception("Network timeout")):
        items = scraper.fetch_market_news_headlines(limit=5, force=True)
        assert items == []


# ==========================================
# 3. LLM市況・為替要因分析 (diagnose_market_volatility_factors) のテスト
# ==========================================
def test_llm_diagnose_market_volatility_no_api_key():
    """APIキー未設定時にNO_API_KEY辞書を安全に返すテスト"""
    service = LLMDiagnosisService()
    with patch.object(service.policy_manager, "get_effective_api_key", return_value=None):
        res = service.diagnose_market_volatility_factors(
            market_indices=[{"name": "日経平均", "price": "39000", "change": "+600", "change_percent": "+1.56", "is_volatile": True}],
            news_headlines=[{"title": "米ハイテク株高を受け日経平均急反発", "source": "News"}],
            sector_summary={"top_gainers": [{"industry": "電気機器", "avg_change_percent": 2.3}], "top_losers": []},
            force=True,
        )
        assert res["error"] is True
        assert res["error_code"] == "NO_API_KEY"
        assert "APIキー" in res["message"]


def test_llm_diagnose_market_volatility_success_and_cache():
    """Gemini API呼び出し成功時のJSONパースとキャッシュ動作のテスト"""
    service = LLMDiagnosisService()
    mock_ai_json = {
        "headline_summary": "米長期金利上昇に伴う円安進行と半導体株の買い戻しにより日経平均は大幅続伸。",
        "key_drivers": [
            "米10年債利回り上昇を受けドル円が151円台へ円安急進",
            "外需・輸出関連セクター（輸送用機器・電気機器）への幅広い買い",
            "好決算期待による主力大型株への資金流入"
        ],
        "equity_factors": "米国市場でのハイテク株高と円安進行を好感し、輸出関連株を中心に買い優勢となりました。",
        "fx_factors": "米経済指標の堅調さを背景に日米金利差拡大が意識され、ドル買い・円売りが進行しました。",
        "portfolio_action_hint": "急騰局面での高値掴みを避け、出遅れている内需ディフェンシブ高配当株の押し目を待つのが有効です。"
    }
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": json.dumps(mock_ai_json, ensure_ascii=False)}]
                }
            }
        ]
    }

    with patch.object(service.policy_manager, "get_effective_api_key", return_value="dummy-api-key"), \
         patch.object(service.policy_manager, "load_config", return_value={"selected_model": "gemini-flash-latest"}), \
         patch("llm_service.requests.post", return_value=mock_post_resp) as mock_post:

        indices = [{"name": "日経平均", "code": "998407.O", "price": "39,100", "change": "+650", "change_percent": "+1.69", "is_volatile": True, "volatility_label": "⚡ 急騰"}]
        headlines = [{"title": "日経平均600円超高、円安が追い風", "source": "経済新聞", "pub_date": "15:00"}]
        sectors = {"top_gainers": [{"industry": "輸送用機器", "avg_change_percent": 2.45}], "top_losers": [{"industry": "小売業", "avg_change_percent": -0.5}]}

        res1 = service.diagnose_market_volatility_factors(indices, headlines, sectors, force=True)
        assert res1["error"] is False
        assert res1["headline_summary"] == mock_ai_json["headline_summary"]
        assert len(res1["key_drivers"]) == 3
        assert res1["is_cached"] is False
        assert mock_post.call_count == 1

        # 2回目はキャッシュから返却されること
        res2 = service.diagnose_market_volatility_factors(indices, headlines, sectors, force=False)
        assert res2["is_cached"] is True
        assert mock_post.call_count == 1

        # clear_cache() でクリアされること
        service.clear_cache()
        assert service._market_volatility_cache == {}


# ==========================================
# 4. APIエンドポイント (POST /api/market-volatility/summary) 統合テスト
# ==========================================
def test_api_market_volatility_summary_endpoint():
    """本番DB保護を徹底した上で /api/market-volatility/summary のレスポンス構造を検証"""
    fake_assets = [
        {"code": "7203", "name": "トヨタ自動車", "asset_type": "jp_stock", "industry": "輸送用機器", "change_percent": "+2.40%"},
        {"code": "8306", "name": "三菱UFJ", "asset_type": "jp_stock", "industry": "銀行業", "change_percent": "+1.80%"},
        {"code": "9432", "name": "NTT", "asset_type": "jp_stock", "industry": "情報・通信業", "change_percent": "-0.60%"},
    ]
    fake_metadata = {
        "market_indices": [
            {"name": "日経平均", "code": "998407.O", "price": "39,200.00", "change": "+680.00", "change_percent": "+1.76", "is_fx": False},
            {"name": "ドル円", "code": "USDJPY=X", "price": "151.20", "change": "+1.15", "change_percent": "+0.77", "is_fx": True},
        ]
    }
    fake_news = [
        {"title": "米雇用統計の上振れでドル円151円台、日経平均も大幅高", "link": "https://example.com/1", "pub_date": "10/23 15:30", "source": "Yahoo!ニュース"}
    ]
    fake_ai = {
        "headline_summary": "米雇用統計後の円安進行を受け、輸出株中心に日経平均が急騰。",
        "key_drivers": ["ドル円が151円台へ円安急進", "自動車・銀行セクターが相場を牽引"],
        "equity_factors": "外需大型株に買いが集まりました。",
        "fx_factors": "米金利上昇によりドル高・円安が進行しました。",
        "portfolio_action_hint": "急騰銘柄の追いかけ買いは控え、高配当内需株の押し目を狙いましょう。",
        "model_used": "gemini-flash-latest",
        "diagnosed_at": "2026-10-23 15:35:00",
        "is_cached": False,
    }

    with patch("history_manager.save_daily_data"), \
         patch("history_manager.save_snapshot"), \
         patch("history_manager.add_split_alert"), \
         patch("portfolio_manager.save_portfolio"), \
         patch("app._get_processed_asset_data", return_value=(fake_assets, fake_metadata)), \
         patch("scraper.fetch_market_news_headlines", return_value=fake_news), \
         patch.object(app.llm_service_instance, "diagnose_market_volatility_factors", return_value=fake_ai):

        resp = client.post("/api/market-volatility/summary", json={"force": False})
        assert resp.status_code == 200
        data = resp.json()

        assert data["has_volatile_index"] is True
        assert len(data["market_indices"]) == 2
        assert data["market_indices"][0]["is_volatile"] is True
        assert data["market_indices"][1]["is_volatile"] is True
        assert len(data["sector_summary"]["top_gainers"]) == 2
        assert data["sector_summary"]["top_gainers"][0]["industry"] == "輸送用機器"
        assert len(data["sector_summary"]["top_losers"]) == 1
        assert data["sector_summary"]["top_losers"][0]["industry"] == "情報・通信業"
        assert data["news_headlines"] == fake_news
        assert data["ai_analysis"]["headline_summary"] == fake_ai["headline_summary"]


# ==========================================
# 5. フロントエンドUI・HTML・CSS構成検証テスト
# ==========================================
def test_frontend_market_volatility_ui_elements():
    """index.html, main.js, style.css に急変動バッジ・モーダル・イベント伝播抑止が実装されているか検証"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    with open(os.path.join(base_dir, "templates", "index.html"), "r", encoding="utf-8") as f:
        html_content = f.read()
    assert 'id="market-volatility-modal"' in html_content
    assert 'id="market-volatility-content-container"' in html_content
    assert 'id="btn-refresh-market-volatility"' in html_content

    with open(os.path.join(base_dir, "static", "js", "main.js"), "r", encoding="utf-8") as f:
        js_content = f.read()
    assert "volatile-factor-badge" in js_content
    assert "btn-open-market-volatility" in js_content
    assert "market-summary-header" in js_content
    assert "market-indices-grid" in js_content
    assert "market-summary-title" in js_content
    assert "openMarketVolatilityModal" in js_content
    assert "mv-action-hint-box" in js_content
    assert "mv-action-hint-badge" in js_content
    assert "mv-action-hint-text" in js_content
    assert "/api/market-volatility/summary" in js_content
    assert "e.preventDefault()" in js_content
    assert "e.stopPropagation()" in js_content

    with open(os.path.join(base_dir, "static", "css", "style.css"), "r", encoding="utf-8") as f:
        css_content = f.read()
    assert ".market-summary-header" in css_content
    assert ".market-indices-grid" in css_content
    assert ".market-summary-title" in css_content
    assert ".market-index-card.is-volatile-up" in css_content
    assert ".market-index-card.is-volatile-down" in css_content
    assert ".volatile-factor-badge" in css_content
    assert ".btn-market-volatility" in css_content
    assert ".mv-action-hint-box" in css_content
    assert ".mv-action-hint-badge" in css_content
    assert ".mv-action-hint-text" in css_content
    assert '[data-theme="dark"] .btn-market-volatility' in css_content
    assert '[data-theme="dark"] .mv-headline-banner' in css_content
    assert '[data-theme="dark"] .mv-action-hint-box' in css_content
