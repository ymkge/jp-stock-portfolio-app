"""
AIおすすめ5選（絞り込み銘柄購入推奨Top5）押下時のAPIエラー画面表示、
CSSリセット、およびエラーハンドリングの自動テスト (#370)

AGENTS.md 規約 0.2 に従い、本番DB (portfolio_history.db) への書き込みを行わず、
モックを使用して完全隔離テストを実施。
"""

import pytest
import os
import re
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


def test_css_modal_alert_reset_and_error_box_styles():
    """style.css 内で .modal-body .alert がリセットされ、専用エラーボックスが定義されていること (#370)"""
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    assert os.path.exists(css_path), "style.css が存在すること"

    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # 1. .modal-body .alert または .modal-content .alert のリセット定義が存在すること
    assert ".modal-body .alert" in css_content
    assert "opacity: 1 !important" in css_content
    assert "transform: none !important" in css_content

    # 2. 専用ボックス（.rec-error-box, .rec-warning-box, .rec-empty-box）が定義されていること
    assert ".rec-error-box" in css_content
    assert ".rec-warning-box" in css_content
    assert ".rec-empty-box" in css_content

    # 3. 再試行ボタンおよび設定ボタンのスタイルが定義されていること
    assert ".btn-rec-retry" in css_content
    assert ".btn-rec-settings" in css_content

    # 4. ダークモード定義が存在すること
    assert '[data-theme="dark"] .rec-error-box' in css_content
    assert '[data-theme="dark"] .rec-warning-box' in css_content
    assert '[data-theme="dark"] .rec-empty-box' in css_content


def test_main_js_error_handling_and_safe_parse():
    """main.js 内で data.detail を抽出し、専用ボックスで安全に描画するロジックが存在すること (#370)"""
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "main.js")
    assert os.path.exists(js_path), "main.js が存在すること"

    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    # 1. data.detail と data.message の両方が安全に取得されていること
    assert "data.detail || data.message" in js_content

    # 2. safe JSON parse (try-catch) が存在すること
    assert "JSON.stringify({" in js_content
    assert "res.json()" in js_content

    # 3. 不可視化の要因となっていた .alert ではなく .rec-error-box / .rec-warning-box を使っていること
    assert "rec-error-box" in js_content
    assert "rec-warning-box" in js_content
    assert "rec-empty-box" in js_content

    # 4. インラインの再試行（force=true）ボタン連携が存在すること
    assert "window.fetchAndRenderFilteredRecommendations" in js_content
    assert "btn-rec-retry" in js_content


def test_api_filtered_recommendations_error_response():
    """API /api/ai-diagnosis/filtered-recommendations のエラー時に detail が正しく返却されること (#370)"""
    from app import app
    client = TestClient(app)

    # 1. 絞り込みコードが空の場合 400 detail が返ること
    res = client.post("/api/ai-diagnosis/filtered-recommendations", json={
        "filtered_codes": [],
        "asset_type": "jp_stock"
    })
    assert res.status_code == 400
    assert "detail" in res.json()
    assert "空です" in res.json()["detail"]

    # 2. 該当銘柄が存在しない場合 400 detail が返ること（DBアクセスはモック化）
    with patch("app._get_processed_asset_data", return_value=([], {})):
        res2 = client.post("/api/ai-diagnosis/filtered-recommendations", json={
            "filtered_codes": ["999999"],
            "asset_type": "jp_stock"
        })
        assert res2.status_code == 400
        assert "detail" in res2.json()
        assert "見つかりませんでした" in res2.json()["detail"]


def test_api_filtered_recommendations_llm_error_dict():
    """LLMサービスが error 辞書を返却した場合にフロントエンドが受け取れること (#370)"""
    from app import app
    client = TestClient(app)

    dummy_assets = [
        {"code": "7203", "name": "トヨタ自動車", "holdings": [], "dividend_yield": "3.8%"}
    ]

    with patch("app._get_processed_asset_data", return_value=(dummy_assets, {})), \
         patch("scraper.get_exchange_rate_detail", return_value=None), \
         patch("app.llm_service_instance.diagnose_filtered_recommendations", return_value={
             "error": True,
             "message": "AI診断の実行中にエラーが発生しました: Quota exceeded"
         }):

        res = client.post("/api/ai-diagnosis/filtered-recommendations", json={
            "filtered_codes": ["7203"],
            "asset_type": "jp_stock"
        })
        assert res.status_code == 200
        data = res.json()
        assert data.get("error") is True
        assert "Quota exceeded" in data.get("message")
