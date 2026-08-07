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
        "asset_type": "jp_stock"
    }
    response = client.post("/api/llm/diagnose", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["fit_level"] == "fit"
    assert data["decision_label"] == "【強い買い（コア）】"

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
