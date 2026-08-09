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

