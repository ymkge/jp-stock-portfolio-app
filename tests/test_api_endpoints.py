import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app import app, policy_manager_instance, llm_service_instance

client = TestClient(app)

def test_api_get_investment_policy(tmp_path):
    response = client.get("/api/investment-policy")
    assert response.status_code == 200
    data = response.json()
    assert "api_key_masked" in data
    assert "has_api_key" in data
    assert "selected_model" in data
    assert "policy_prompt" in data

def test_api_save_and_reset_investment_policy():
    # 1. 設定保存
    save_payload = {
        "api_key": "test_api_key_12345678",
        "selected_model": "gemini-flash-lite-latest",
        "policy_prompt": "結合テスト用方針",
        "reset": False
    }
    response = client.post("/api/investment-policy", json=save_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["has_api_key"] is True
    assert data["selected_model"] == "gemini-flash-lite-latest"
    assert data["policy_prompt"] == "結合テスト用方針"

    # 2. リセット
    reset_payload = {"reset": True}
    response = client.post("/api/investment-policy", json=reset_payload)
    assert response.status_code == 200
    data_reset = response.json()
    assert "インカムゲイン特化型" in data_reset["policy_prompt"]

@patch("app.fetch_asset_data_smart_cached")
@patch.object(llm_service_instance, "diagnose_stock")
def test_api_llm_diagnose_success(mock_diagnose, mock_fetch):
    mock_fetch.return_value = (
        {
            "code": "7164",
            "name": "全国保証",
            "price": "4500",
            "currency": "JPY",
            "asset_type": "jp_stock"
        },
        True
    )
    mock_diagnose.return_value = {
        "error": False,
        "fit_level": "fit",
        "confidence_score": 90,
        "decision_label": "【強い買い（コア）】",
        "estimated_yield": "約4.4%",
        "recommended_shares": "約3株〜4株",
        "shield_and_valuation": "良好",
        "business_10y_eval": "安定",
        "tactical_advice": "買い推奨",
        "summary": "優秀な銘柄です。"
    }

    payload = {
        "code": "7164",
        "asset_type": "jp_stock",
        "force": True
    }
    response = client.post("/api/llm/diagnose", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["fit_level"] == "fit"
    assert data["decision_label"] == "【強い買い（コア）】"
    mock_diagnose.assert_called_once()
    assert mock_diagnose.call_args.kwargs.get("force") is True

@patch("app.fetch_asset_data_smart_cached")
def test_api_llm_diagnose_asset_not_found(mock_fetch):
    mock_fetch.return_value = (None, False)

    payload = {
        "code": "0000",
        "asset_type": "jp_stock"
    }
    response = client.post("/api/llm/diagnose", json=payload)
    assert response.status_code == 400
    assert "銘柄コード 0000 のデータが取得できませんでした。" in response.json()["detail"]


def test_monthly_dividend_chart_tooltip_rollback():
    """monthly-dividend-chart のツールチップから afterLabel (前月比表示) が削除され、予想受取額のみが表示されることを検証"""
    import os
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # monthly-dividend-chart の定義部分を抽出
    monthly_chart_section = content.split("getElementById('monthly-dividend-chart')")[1].split("updateChart")[0]
    
    # label の存在確認と afterLabel の非存在確認
    assert "label: (c) => `${c.dataset.label}:" in monthly_chart_section
    assert "afterLabel" not in monthly_chart_section


def test_dividend_history_chart_tooltip_retention():
    """dividend-history-chart のツールチップに afterLabel (前月比表示) が引き続き維持されていることを検証"""
    import os
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # dividend-history-chart の定義部分を抽出
    history_chart_section = content.split("getElementById('dividend-history-chart')")[1].split("processAnalysisData")[0]
    
    # label および afterLabel (前月比) の維持確認
    assert "label: (c) =>" in history_chart_section
    assert "afterLabel: (c) =>" in history_chart_section
    assert "前月比:" in history_chart_section


def test_disclaimer_banner_and_footer_in_html():
    """トップ画面 (/) および分析画面 (/analysis) に免責事項バナー・フッター・法的4要素・AIモーダル注記が正しく含まれていることを検証"""
    res_index = client.get("/")
    assert res_index.status_code == 200
    assert "top-disclaimer-banner" in res_index.text
    assert "免責事項:" in res_index.text
    assert "一切の責任を負いません" in res_index.text
    assert "app-disclaimer-footer" in res_index.text
    # 法的4要素の検証
    assert "投資助言等の否定" in res_index.text
    assert "データの無保証" in res_index.text
    assert "AI診断結果の性質" in res_index.text
    assert "完全免責" in res_index.text
    # 再表示ボタンおよびAI診断モーダル注記の検証
    assert "btn-restore-disclaimer" in res_index.text
    assert "llm-disclaimer-note" in res_index.text

    res_analysis = client.get("/analysis")
    assert res_analysis.status_code == 200
    assert "top-disclaimer-banner" in res_analysis.text
    assert "app-disclaimer-footer" in res_analysis.text
    assert "投資助言等の否定" in res_analysis.text
    assert "データの無保証" in res_analysis.text
    assert "AI診断結果の性質" in res_analysis.text
    assert "完全免責" in res_analysis.text
    assert "btn-restore-disclaimer" in res_analysis.text


def test_llm_modal_first_view_and_responsive_css():
    """案件 #248: AI診断モーダルのファーストVIEW完全収容、内部スクロール、グリッドレイアウト、ダークモードCSSの検証"""
    import os
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # 1. モーダル高さ制限と内部スクロール検証
    assert "#llm-diagnosis-modal .modal-dialog" in css_content
    assert "#llm-diagnosis-modal .modal-content" in css_content
    assert "#llm-diagnosis-modal .modal-body" in css_content
    assert "max-height: 88vh;" in css_content
    assert "max-height: calc(88vh - 120px);" in css_content
    assert "overflow-y: auto;" in css_content

    # 2. レスポンシブ2列レイアウトとコンパクトブロック検証
    assert ".llm-grid-container" in css_content
    assert "grid-template-columns: 1fr 1fr;" in css_content
    assert "@media (max-width: 768px)" in css_content
    assert "grid-template-columns: 1fr;" in css_content
    assert ".llm-section-block" in css_content

    # 3. ダークモード配色設計検証
    assert "body.dark-mode .llm-section-block" in css_content

    # 4. 強調スタイルの検証 (#249)
    assert ".llm-section-block.theme-highlight-summary" in css_content
    assert ".llm-section-block.theme-highlight-action" in css_content
    assert "body.dark-mode .llm-section-block.theme-highlight-summary" in css_content
    assert "body.dark-mode .llm-section-block.theme-highlight-action" in css_content

    # 5. 他モーダルへの副作用防止確認（汎用モーダルクラスを直接汚染せず#llm-diagnosis-modalでスコープしているか）
    assert "#llm-diagnosis-modal .modal-body {" in css_content

    # JS/HTML構造検証
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "main.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert "llm-grid-container" in js_content
    assert "llm-column" in js_content
    assert "llm-section-block" in js_content
    assert "theme-highlight-summary" in js_content
    assert "theme-highlight-action" in js_content
    assert "llm-section-title" in js_content
    assert "llm-text-content" in js_content




