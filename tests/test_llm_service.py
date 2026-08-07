import os
import pytest
from unittest.mock import MagicMock, patch
from llm_service import LLMDiagnosisService
from investment_policy_manager import InvestmentPolicyManager

@pytest.fixture
def policy_manager(tmp_path):
    test_file = os.path.join(tmp_path, "test_investment_policy.json")
    pm = InvestmentPolicyManager(filepath=test_file)
    pm.save_config(api_key="mock_api_key_123")
    return pm

def test_missing_api_key(tmp_path):
    test_file = os.path.join(tmp_path, "no_key_policy.json")
    pm = InvestmentPolicyManager(filepath=test_file)
    service = LLMDiagnosisService(policy_manager=pm)
    
    with patch.dict(os.environ, {}, clear=True):
        res = service.diagnose_stock({"code": "7164", "name": "全国保証"})
        assert res["error"] is True
        assert res["error_code"] == "NO_API_KEY"

@patch("requests.post")
def test_successful_diagnosis(mock_post, policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": '''{
                                "fit_level": "fit",
                                "confidence_score": 92,
                                "decision_label": "【強い買い（コア）】",
                                "estimated_yield": "約4.4%",
                                "recommended_shares": "約3株〜4株",
                                "shield_and_valuation": "DOE4.0%下限を掲げており、PBR0.95倍と良好。",
                                "business_10y_eval": "住宅ローン保証のニッチトップ。",
                                "tactical_advice": "S株ナンピン買い下がり推奨。",
                                "summary": "高配当・低PBRかつ還元の盾を備えたコア銘柄。"
                            }'''
                        }
                    ]
                }
            }
        ]
    }
    mock_post.return_value = mock_response

    stock_data = {
        "code": "7164",
        "name": "全国保証",
        "price": 4500,
        "per": 12.5,
        "pbr": 0.95,
        "yield": 4.4,
        "payout_ratio": 45.0,
        "consecutive_increase": 10
    }
    res = service.diagnose_stock(stock_data)

    assert res["error"] is False
    assert res["fit_level"] == "fit"
    assert res["confidence_score"] == 92
    assert res["decision_label"] == "【強い買い（コア）】"
    assert "S株ナンピン" in res["tactical_advice"]
    assert res["model_used"] == "gemini-flash-latest"

@patch("requests.post")
def test_rate_limit_error(mock_post, policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_post.return_value = mock_response

    res = service.diagnose_stock({"code": "7164", "name": "全国保証"})
    assert res["error"] is True
    assert res["error_code"] == "RATE_LIMIT"

@patch("requests.post")
def test_bad_request_error(mock_post, policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"error": {"message": "Invalid API Key"}}
    mock_post.return_value = mock_response

    res = service.diagnose_stock({"code": "7164", "name": "全国保証"})
    assert res["error"] is True
    assert res["error_code"] == "BAD_REQUEST"
    assert "APIキーが無効" in res["message"]

@patch("requests.post")
def test_http_500_error(mock_post, policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_post.return_value = mock_response

    res = service.diagnose_stock({"code": "7164", "name": "全国保証"})
    assert res["error"] is True
    assert res["error_code"] == "HTTP_500"

@patch("requests.post")
def test_timeout_error(mock_post, policy_manager):
    import requests
    service = LLMDiagnosisService(policy_manager=policy_manager)
    mock_post.side_effect = requests.exceptions.Timeout("Connection timed out")

    res = service.diagnose_stock({"code": "7164", "name": "全国保証"})
    assert res["error"] is True
    assert res["error_code"] == "TIMEOUT"

@patch("requests.post")
def test_empty_candidates_error(mock_post, policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"candidates": []}
    mock_post.return_value = mock_response

    res = service.diagnose_stock({"code": "7164", "name": "全国保証"})
    assert res["error"] is True
    assert res["error_code"] == "NO_CANDIDATE"

@patch("requests.post")
def test_broken_json_response_fallback(mock_post, policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "これはJSONではありません。分析結果の文章です。"}
                    ]
                }
            }
        ]
    }
    mock_post.return_value = mock_response

    res = service.diagnose_stock({"code": "7164", "name": "全国保証"})
    assert res["error"] is False
    assert res["fit_level"] == "caution"
    assert res["confidence_score"] == 50
    assert "これはJSONではありません" in res["business_10y_eval"]

@patch("requests.post")
def test_invalid_model_fallback(mock_post, policy_manager):
    policy_manager.save_config(selected_model="invalid-model-name")
    service = LLMDiagnosisService(policy_manager=policy_manager)
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"fit_level": "fit"}'}]}}]
    }
    mock_post.return_value = mock_response

    res = service.diagnose_stock({"code": "7164"})
    assert res["model_used"] == "gemini-flash-latest"

def test_build_prompt_with_portfolio_summary(policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    stock_data = {
        "code": "9432",
        "name": "NTT",
        "price": 150,
        "evaluation_value": 150000,
        "holdings": [{"quantity": 1000}],
        "buy_signal": {"label": "買いシグナル(MA25+DOE)", "recommended_action": "押し目買い"}
    }
    portfolio_summary = {
        "total_evaluation_value": 1000000
    }
    prompt = service._build_prompt(stock_data, portfolio_summary, "テスト方針")
    assert "コード: 9432 / 銘柄名: NTT" in prompt
    assert "ポートフォリオ全体比率 15.00%" in prompt
    assert "買いシグナル(MA25+DOE)" in prompt

