import os
import json
import time
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
        assert res.get("error") is True
        assert res.get("error_code") == "NO_API_KEY"

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
        "price": 4500
    }
    res = service.diagnose_stock(stock_data)

    assert res.get("error") is None or res.get("error") is False
    assert res["fit_level"] == "fit"
    assert res["confidence_score"] == 92
    assert res["decision_label"] == "【強い買い（コア）】"
    assert res["is_cached"] is False

@patch("requests.post")
def test_cache_hit_and_miss(mock_post, policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"fit_level": "fit", "summary": "初回"}'}]}}]
    }
    mock_post.return_value = mock_response

    stock_data = {"code": "7164", "name": "全国保証"}

    # 1回目 (Miss)
    res1 = service.diagnose_stock(stock_data)
    assert res1["is_cached"] is False
    assert mock_post.call_count == 1

    # 2回目 (Hit)
    res2 = service.diagnose_stock(stock_data)
    assert res2["is_cached"] is True
    assert mock_post.call_count == 1  # 通信は発生しない

@patch("requests.post")
def test_force_bypass_cache(mock_post, policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"fit_level": "fit", "summary": "診断結果"}'}]}}]
    }
    mock_post.return_value = mock_response

    stock_data = {"code": "7164", "name": "全国保証"}

    # 初回
    service.diagnose_stock(stock_data)
    assert mock_post.call_count == 1

    # force=True で強制再診断
    res = service.diagnose_stock(stock_data, force=True)
    assert res["is_cached"] is False
    assert mock_post.call_count == 2

@patch("requests.post")
def test_prompt_change_invalidates_cache(mock_post, policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"fit_level": "fit"}'}]}}]
    }
    mock_post.return_value = mock_response

    stock_data = {"code": "7164"}

    # 初回
    service.diagnose_stock(stock_data)
    assert mock_post.call_count == 1

    # 投資方針プロンプトを変更
    policy_manager.save_config(policy_prompt="新しい変更後のプロンプト")
    
    # 2回目 (ハッシュ変更のためキャッシュHitせず再実行)
    res = service.diagnose_stock(stock_data)
    assert res["is_cached"] is False
    assert mock_post.call_count == 2

@patch("requests.post")
def test_error_response_not_cached(mock_post, policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"error": {"message": "API key not valid"}}
    mock_post.return_value = mock_response

    stock_data = {"code": "7164"}

    # 1回目 (エラー発生)
    res1 = service.diagnose_stock(stock_data)
    assert res1.get("error") is True

    # 2回目 (エラーなのでキャッシュされず再実行される)
    res2 = service.diagnose_stock(stock_data)
    assert res2.get("error") is True
    assert mock_post.call_count == 2

@patch("requests.post")
def test_lru_eviction(mock_post, policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    service.MAX_CACHE_SIZE = 2  # テスト用に上限を2に設定

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"fit_level": "fit"}'}]}}]
    }
    mock_post.return_value = mock_response

    # 1001, 1002 をキャッシュ
    service.diagnose_stock({"code": "1001"})
    time.sleep(0.01)
    service.diagnose_stock({"code": "1002"})
    assert len(service._cache) == 2

    # 1003 を追加 ➔ 最も古い 1001 が溢れて破棄される
    time.sleep(0.01)
    service.diagnose_stock({"code": "1003"})
    assert len(service._cache) == 2
    assert "1001_jp_stock" not in service._cache
    assert "1002_jp_stock" in service._cache
    assert "1003_jp_stock" in service._cache

@patch("requests.post")
def test_clear_cache(mock_post, policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"fit_level": "fit"}'}]}}]
    }
    mock_post.return_value = mock_response

    service.diagnose_stock({"code": "7164"})
    assert len(service._cache) == 1

    service.clear_cache()
    assert len(service._cache) == 0

def test_yield_key_prompt_building(policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    # パターン1: 'yield' キーが存在するケース
    stock_data1 = {
        "code": "6200",
        "name": "インソース",
        "price": 713,
        "yield": 4.91,
        "per": 13.61,
        "pbr": 4.44,
        "roe": 36.84,
        "payout_ratio": 69.6
    }
    prompt1 = service._build_prompt(stock_data1, None, "テスト方針")
    assert "銘柄コード: 6200" in prompt1
    assert "予想配当利回り: 4.91 %" in prompt1
    assert "ROE(自己資本利益率): 36.84 %" in prompt1

    # パターン2: 'yield' が存在せず 'dividend_yield' キーをフォールバック参照するケース ('%'文字含む文字列)
    stock_data2 = {
        "code": "7164",
        "name": "全国保証",
        "dividend_yield": "3.80%",
        "roe": "12.5"
    }
    prompt2 = service._build_prompt(stock_data2, None, "テスト方針")
    assert "銘柄コード: 7164" in prompt2
    assert "予想配当利回り: 3.80 %" in prompt2

    # パターン3: 利回りデータが欠損しているケース (N/A)
    stock_data3 = {
        "code": "9999",
        "name": "サンプル",
        "yield": None,
        "dividend_yield": "N/A"
    }
    prompt3 = service._build_prompt(stock_data3, None, "テスト方針")
    assert "予想配当利回り: N/A %" in prompt3

def test_performance_summary_and_eps_building(policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    stock_data = {
        "code": "6200",
        "name": "インソース",
        "price": 713,
        "eps": 52.4,
        "market_cap": "60778000000",
        "per": 13.61,
        "pbr": 4.44,
        "roe": 36.84
    }
    prompt = service._build_prompt(stock_data, None, "テスト方針")
    assert "EPS(1株利益): 52.4 円" in prompt
    assert "時価総額: 607 億円" in prompt

    # パースの検証 (performance_summaryの抽出)
    raw_text = '{"fit_level": "fit", "performance_summary": "直近のEPSは52.4円で順調に推移しています。"}'
    parsed = service._parse_llm_json(raw_text)
    assert parsed["performance_summary"] == "直近のEPSは52.4円で順調に推移しています。"


def test_market_cap_formatting_detailed(policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    
    # 1. 兆円単位
    p1 = service._build_prompt({"code": "7203", "market_cap": 2500000000000}, None, "方針")
    assert "時価総額: 2.50 兆円" in p1

    # 2. 億円単位
    p2 = service._build_prompt({"code": "6200", "market_cap": 60778000000}, None, "方針")
    assert "時価総額: 607 億円" in p2

    # 3. 円単位 (1億円未満)
    p3 = service._build_prompt({"code": "9999", "market_cap": 85000000}, None, "方針")
    assert "時価総額: 85,000,000 円" in p3

    # 4. カンマ付き文字列
    p4 = service._build_prompt({"code": "7203", "market_cap": "1,200,000,000,000"}, None, "方針")
    assert "時価総額: 1.20 兆円" in p4

    # 5. 欠損・特殊表記 (N/A, --, None, "")
    for missing_val in ["N/A", "--", None, ""]:
        p = service._build_prompt({"code": "0000", "market_cap": missing_val}, None, "方針")
        assert "時価総額: N/A" in p

    # 6. 数値に変換できない不正文字列
    p_invalid = service._build_prompt({"code": "0000", "market_cap": "非数値データ"}, None, "方針")
    assert "時価総額: 非数値データ" in p_invalid


def test_eps_prompt_building_variations(policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)

    # float
    p1 = service._build_prompt({"code": "1111", "eps": 123.45}, None, "方針")
    assert "EPS(1株利益): 123.45 円" in p1

    # int
    p2 = service._build_prompt({"code": "2222", "eps": 200}, None, "方針")
    assert "EPS(1株利益): 200 円" in p2

    # 文字列
    p3 = service._build_prompt({"code": "3333", "eps": "350.0"}, None, "方針")
    assert "EPS(1株利益): 350.0 円" in p3

    # 欠損
    p4 = service._build_prompt({"code": "4444"}, None, "方針")
    assert "EPS(1株利益): N/A 円" in p4


def test_performance_summary_fallback_on_missing_key(policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    
    # 応答JSONに performance_summary が含まれない場合
    raw_text = '{"fit_level": "fit", "decision_label": "【判定】", "summary": "概要"}'
    parsed = service._parse_llm_json(raw_text)
    assert parsed["performance_summary"] == "直近業績（EPS・収益性）データに基づき持続可能な配当維持力を検証済みです。"


def test_material_exhaustion_eval_prompt_and_parsing(policy_manager):
    service = LLMDiagnosisService(policy_manager=policy_manager)
    stock_data = {
        "code": "6200",
        "name": "インソース",
        "price": 713,
        "exhaustion_signal": {
            "type": "sell_the_fact",
            "label": "🚨 出尽くし警戒",
            "recommended_action": "買われすぎ高値圏からの反落初動。"
        }
    }
    prompt = service._build_prompt(stock_data, None, "テスト方針")
    assert "テクニカル材料出尽くし検知: 🚨 出尽くし警戒 - 買われすぎ高値圏からの反落初動。" in prompt
    assert "【材料出尽くし感（好材料出尽くし下落リスク / 悪材料アク抜け大底判定）やマクロ地政学・災害・米国市況ショックの影響度】" in prompt

    # JSONパースの検証
    raw_text = '{"fit_level": "caution", "material_exhaustion_eval": "好材料出尽くしによる一時的な利益確定売りが発生しています。"}'
    parsed = service._parse_llm_json(raw_text)
    assert parsed["material_exhaustion_eval"] == "好材料出尽くしによる一時的な利益確定売りが発生しています。"

    # キー欠損フォールバックの検証
    raw_missing = '{"fit_level": "fit"}'
    parsed_missing = service._parse_llm_json(raw_missing)
    assert parsed_missing["material_exhaustion_eval"] == "テクニカル指標およびマクロ要因に基づく材料出尽くしリスクを分析済みです。"


def test_trend_analysis_prompt_and_parsing(policy_manager):
    """Issue #268: 移動平均線(75日/200日)・乖離率・トレンド状態のプロンプト構築とtrend_analysisパースの検証"""
    service = LLMDiagnosisService(policy_manager=policy_manager)
    stock_data = {
        "code": "7203",
        "name": "トヨタ自動車",
        "price": 2950,
        "moving_average_75": 3000,
        "moving_average_200": 2920,
    }
    prompt = service._build_prompt(stock_data, None, "テスト方針")
    assert "75日移動平均線 (MA75): 3,000.0 円 (乖離率: -1.7%)" in prompt
    assert "200日移動平均線 (MA200): 2,920.0 円 (乖離率: +1.0%)" in prompt
    assert "移動平均トレンド状態: ⛅ 中期調整 (75日線下・200日線上: 絶好の押し目圏)" in prompt
    assert "trend_analysis" in prompt

    # JSONパースの検証
    raw_text = '{"fit_level": "fit", "trend_analysis": "75日線下の中期調整圏ですが200日線の上を維持しており押し目買いチャンスです。"}'
    parsed = service._parse_llm_json(raw_text)
    assert parsed["trend_analysis"] == "75日線下の中期調整圏ですが200日線の上を維持しており押し目買いチャンスです。"


@patch("requests.post")
def test_diagnose_profit_taking_success_and_cache(mock_post, policy_manager):
    """diagnose_profit_taking の正常動作、パース、キャッシュ独立性のテスト (#281)"""
    service = LLMDiagnosisService(policy_manager=policy_manager)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{
                    "text": '{"action": "PARTIAL_SELL", "action_label": "🟡 一部利確・元本回収を推奨", "target_sell_ratio": "保有株数の1/2", "fundamentals_analysis": "業績好調ですが利回り低下", "profit_taking_advice": "元本回収して他高配当株へ乗り換えを推奨", "summary": "一部利確推奨"}'
                }]
            }
        }]
    }
    mock_post.return_value = mock_response

    item = {
        "code": "4751",
        "name": "サイバーエージェント",
        "quantity": 200,
        "market_value": 600000.0,
        "profit_loss": 300000.0,
        "estimated_annual_dividend": 10000.0,
        "dividend_years_ratio": 30.0,
        "dividend_yield": 1.67,
        "profit_taking_badge": {"level": 4, "label": "💎 配当30年分達成"}
    }

    # 1回目 (リアルタイム呼び出し)
    res1 = service.diagnose_profit_taking(item)
    assert res1["error"] is False
    assert res1["action"] == "PARTIAL_SELL"
    assert res1["action_label"] == "🟡 一部利確・元本回収を推奨"
    assert res1["is_cached"] is False
    assert mock_post.call_count == 1

    # 2回目 (キャッシュHit)
    res2 = service.diagnose_profit_taking(item)
    assert res2["error"] is False
    assert res2["is_cached"] is True
    assert mock_post.call_count == 1  # requests.post は再実行されない

    # 適合度診断のキャッシュと干渉していないこと
    assert len(service._cache) == 0
    assert len(service._profit_taking_cache) == 1


def test_build_profit_taking_prompt_override_rule(policy_manager):
    """プロンプト内に超高騰オーバーライド規則が含まれているかテスト (#281)"""
    service = LLMDiagnosisService(policy_manager=policy_manager)
    item = {
        "code": "7203",
        "name": "トヨタ自動車",
        "market_value": 600000,
        "profit_loss": 200000,
        "estimated_annual_dividend": 20000,
        "dividend_years_ratio": 10.0,
        "dividend_yield": 3.33
    }
    prompt = service._build_profit_taking_prompt(item, "長期保有・配当金重視")
    assert "【重要判定規則：業種将来性・日本政府国策投資・株主還元姿勢と利確の適正バランシングルール】" in prompt
    assert "トヨタ自動車 (コード: 7203)" in prompt
    assert "PARTIAL_SELL" in prompt


def test_diagnose_profit_taking_missing_api_key(tmp_path):
    """利確AI診断におけるAPIキー欠損テスト (#281)"""
    import requests
    test_file = os.path.join(tmp_path, "no_key_policy.json")
    pm = InvestmentPolicyManager(filepath=test_file)
    service = LLMDiagnosisService(policy_manager=pm)

    with patch.dict(os.environ, {}, clear=True):
        res = service.diagnose_profit_taking({"code": "7203", "name": "トヨタ自動車"})
        assert res.get("error") is True
        assert res.get("error_code") == "NO_API_KEY"


@patch("requests.post")
def test_diagnose_profit_taking_invalid_key_and_errors(mock_post, policy_manager):
    """利確AI診断における無効APIキー、タイムアウト、壊れたJSONフォールバックテスト (#281)"""
    import requests
    service = LLMDiagnosisService(policy_manager=policy_manager)

    # 1. 無効キー (400 API_KEY_INVALID)
    mock_resp_400 = MagicMock()
    mock_resp_400.status_code = 400
    mock_resp_400.text = "API_KEY_INVALID: Key not valid"
    mock_post.return_value = mock_resp_400

    res_inv = service.diagnose_profit_taking({"code": "7203"})
    assert res_inv.get("error") is True
    assert res_inv.get("error_code") == "INVALID_API_KEY"

    # 2. タイムアウト
    mock_post.side_effect = requests.exceptions.Timeout("Timeout")
    res_timeout = service.diagnose_profit_taking({"code": "7203"})
    assert res_timeout.get("error") is True
    assert res_timeout.get("error_code") == "TIMEOUT_ERROR"

    # 3. 壊れたJSONの安全フォールバック
    mock_post.side_effect = None
    mock_resp_invalid_json = MagicMock()
    mock_resp_invalid_json.status_code = 200
    mock_resp_invalid_json.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{
                    "text": "これは壊れたJSONテキストです。{action: invalid..."
                }]
            }
        }]
    }
    mock_post.return_value = mock_resp_invalid_json

    res_bad_json = service.diagnose_profit_taking({"code": "7203"}, force=True)
    assert res_bad_json.get("error") is False
    assert res_bad_json.get("action") == "PARTIAL_SELL"
    assert "🟡 一部利確・元本回収を推奨" in res_bad_json.get("action_label")
    assert "industry_growth_evaluation" in res_bad_json


def test_build_profit_taking_prompt_industry_and_policy(policy_manager):
    """利確AI診断プロンプトにおける業種、国策投資キーワード、および拡充ファンダメンタルズの検証 (#283)"""
    service = LLMDiagnosisService(policy_manager=policy_manager)
    holding_item = {
        "code": "7203",
        "name": "トヨタ自動車",
        "industry": "輸送用機器",
        "asset_type": "jp_stock",
        "quantity": 100,
        "market_value": 300000.0,
        "profit_loss": 100000.0,
        "estimated_annual_dividend": 9000.0,
        "dividend_years_ratio": 11.1,
        "dividend_yield": "3.00",
        "per": "10.2",
        "pbr": "1.1",
        "roe": "12.5",
        "eps": "250.0",
        "market_cap": "40兆円",
        "payout_ratio": "30.0"
    }

    prompt = service._build_profit_taking_prompt(holding_item, "国策成長投資を重視する方針")
    assert "所属業種/セクター: 輸送用機器" in prompt
    assert "時価総額: 40兆円" in prompt
    assert "EPS: 250.0" in prompt
    assert "日本政府が長期的な政策投資・予算投入を行っている国策テーマ" in prompt
    assert "安易に「FULL_SELL（全額利確）」を判定してはなりません" in prompt
    assert "industry_growth_evaluation" in prompt


def test_build_profit_taking_prompt_doe_and_dividend_policy_issue285(policy_manager):
    """Issue #285: 利確AI診断プロンプトにおけるDOE、連続増配年数、および累進配当優遇ルールの検証"""
    service = LLMDiagnosisService(policy_manager=policy_manager)
    holding_item = {
        "code": "8309",
        "name": "三井住友トラスト",
        "industry": "銀行業",
        "asset_type": "jp_stock",
        "quantity": 100,
        "market_value": 400000.0,
        "profit_loss": 150000.0,
        "estimated_annual_dividend": 16000.0,
        "dividend_years_ratio": 9.375,
        "dividend_yield": "4.00",
        "per": "11.0",
        "pbr": "0.7",
        "roe": "8.5",
        "eps": "300.0",
        "market_cap": "3兆円",
        "payout_ratio": "40.0",
        "doe": 4.5,
        "consecutive_increase_years": 5
    }

    prompt = service._build_profit_taking_prompt(holding_item, "累進配当方針・DOE採用企業重視")
    assert "DOE: 4.5%" in prompt
    assert "還元姿勢: 5年連続増配" in prompt
    assert "累進配当方針・DOE導入・株主還元姿勢の重視（減配リスク抑制）" in prompt
    assert "減配リスクが極めて低く配当の安定性・成長性が担保されている銘柄" in prompt


def test_fetch_market_fibonacci_llm_no_api_key_issue293():
    """案件 #293: API Key 未設定時に NameError が出ず安全に NO_API_KEY を返却するか検証"""
    from unittest.mock import MagicMock
    mock_policy_manager = MagicMock()
    mock_policy_manager.get_effective_api_key.return_value = ""

    service = LLMDiagnosisService(policy_manager=mock_policy_manager)
    res = service.fetch_market_fibonacci_llm(current_n225=38000, current_topix=2600)
    assert res.get("error") is True
    assert res.get("message") == "NO_API_KEY"


def test_fetch_market_fibonacci_llm_direct_issue293(policy_manager):
    """案件 #293: fetch_market_fibonacci_llm が NameError (get_effective_api_key, get_config) なく正常動作するか直接テスト"""
    from unittest.mock import patch, MagicMock

    policy_manager.save_config(api_key="test_api_key_dummy_293")
    service = LLMDiagnosisService(policy_manager=policy_manager)

    mock_gemini_json = """{
        "n225": {"high_price": 72353.0, "high_date": "2026-06", "low_price": 30500.29, "low_date": "2023-10"},
        "topix": {"high_price": 4101.96, "high_date": "2026-07", "low_price": 2217.10, "low_date": "2023-10"},
        "market_commentary": "テスト相場解説"
    }"""

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": mock_gemini_json}]
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_response):
        # 1. 現在値が高値を下回る通常のケース (繰り上がりなし)
        result = service.fetch_market_fibonacci_llm(current_n225=68308, current_topix=4000)
        assert "n225" in result
        assert result["n225"]["high_price"] == 72353.0
        assert result["topix"]["high_price"] == 4101.96
        assert result["market_commentary"] == "テスト相場解説"

        # 2. 現在値が最高値を下から突破するケース (#295: TOPIX 4176 > 4101.96)
        result_new_high = service.fetch_market_fibonacci_llm(current_n225=40000, current_topix=4176)
        assert result_new_high["topix"]["high_price"] == 4176.0


def test_diagnose_anomaly_no_api_key_issue298(tmp_path):
    """案件 #298: APIキー未設定時に diagnose_anomaly が NO_API_KEY を返却するか検証"""
    test_file = os.path.join(tmp_path, "no_key_policy_298.json")
    pm = InvestmentPolicyManager(filepath=test_file)
    service = LLMDiagnosisService(policy_manager=pm)
    
    with patch.dict(os.environ, {}, clear=True):
        res = service.diagnose_anomaly(month=5, anomaly_info={"title": "5月に売れ"})
        assert res.get("error") is True
        assert res.get("error_code") == "NO_API_KEY"


def test_diagnose_anomaly_success_and_cache_issue298(policy_manager):
    """案件 #298: diagnose_anomaly の正常レスポンスとキャッシュ動作の検証"""
    service = LLMDiagnosisService(policy_manager=policy_manager)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "5月のアノマリー解説テキスト。"}]
                }
            }
        ]
    }

    anomaly_info = {
        "title": "Sell in May",
        "summary": "5月に売れ",
        "risk_level": "high",
        "reasons": ["決算通過"],
        "actions": "ポジション調整"
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        # 初回実行（キャッシュなし）
        res1 = service.diagnose_anomaly(month=5, anomaly_info=anomaly_info)
        assert res1.get("error") is False
        assert res1.get("commentary") == "5月のアノマリー解説テキスト。"
        assert res1.get("is_cached") is False
        assert mock_post.call_count == 1

        # 2回目実行（キャッシュヒット）
        res2 = service.diagnose_anomaly(month=5, anomaly_info=anomaly_info)
        assert res2.get("error") is False
        assert res2.get("is_cached") is True
        assert mock_post.call_count == 1

        # force=True実行（キャッシュバイパス）
        res3 = service.diagnose_anomaly(month=5, anomaly_info=anomaly_info, force=True)
        assert res3.get("error") is False
        assert res3.get("is_cached") is False
        assert mock_post.call_count == 2


def test_diagnose_industry_daily_changes_no_api_key(tmp_path):
    """案件 #317: APIキー未設定時に diagnose_industry_daily_changes が NO_API_KEY を返却するか検証"""
    test_file = os.path.join(tmp_path, "no_key_policy_317.json")
    pm = InvestmentPolicyManager(filepath=test_file)
    service = LLMDiagnosisService(policy_manager=pm)
    
    with patch.dict(os.environ, {}, clear=True):
        res = service.diagnose_industry_daily_changes(daily_industry_data={})
        assert res.get("error") is True
        assert res.get("error_code") == "NO_API_KEY"


def test_diagnose_industry_daily_changes_success_and_model_fallback(policy_manager):
    """案件 #317: diagnose_industry_daily_changes の正常レスポンスとモデル取得フォールバックの検証"""
    service = LLMDiagnosisService(policy_manager=policy_manager)

    valid_json_response = json.dumps({
        "market_trend_summary": "本日の市場はハイテク主導で上昇しました。",
        "portfolio_impact_summary": "保有の情報通信株が全体を牽引しています。",
        "key_takeaway": "堅調な推移が期待されます。"
    })

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": valid_json_response}]
                }
            }
        ]
    }

    dummy_industry_data = {
        "gainers": [{"industry": "情報・通信業", "daily_change_jpy": 50000, "daily_change_rate": 1.25, "holding_count": 3}],
        "losers": [],
        "total_daily_change_jpy": 50000
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        # 1. 正常系呼び出し
        res1 = service.diagnose_industry_daily_changes(daily_industry_data=dummy_industry_data)
        assert res1.get("error") is False
        assert res1.get("market_trend_summary") == "本日の市場はハイテク主導で上昇しました。"
        assert res1.get("portfolio_impact_summary") == "保有の情報通信株が全体を牽引しています。"
        assert res1.get("key_takeaway") == "堅調な推移が期待されます。"
        assert res1.get("is_cached") is False
        assert mock_post.call_count == 1
        # モデル名がURLに含まれていることを確認
        call_url = mock_post.call_args[0][0]
        assert "gemini-flash-latest" in call_url

        # 2. キャッシュヒット
        res2 = service.diagnose_industry_daily_changes(daily_industry_data=dummy_industry_data)
        assert res2.get("error") is False
        assert res2.get("is_cached") is True
        assert mock_post.call_count == 1

        # 3. policy_manager に get_selected_model がない旧オブジェクトでも二重防衛でフォールバック動作するか
        dummy_pm = MagicMock(spec=["get_effective_api_key", "load_config"])  # get_selected_model を持たない
        dummy_pm.get_effective_api_key.return_value = "dummy_key"
        dummy_pm.load_config.return_value = {"selected_model": "invalid-model"}
        service_fallback = LLMDiagnosisService(policy_manager=dummy_pm)
        res3 = service_fallback.diagnose_industry_daily_changes(daily_industry_data=dummy_industry_data, force=True)
        assert res3.get("error") is False
        assert mock_post.call_count == 2
        call_url2 = mock_post.call_args[0][0]
        assert "gemini-flash-latest" in call_url2


def test_calculate_downside_metrics_normal():
    """案件 #303: 有配・黒字銘柄における下値参考指標の正常系算出テスト"""
    service = LLMDiagnosisService()
    stock_data = {
        "price": 2000,
        "yield": 4.0,  # 予想配当利回り 4.0% -> 予想DPS = 80円
        "pbr": 0.8,
        "bps": 2500,
        "moving_average_75": 1950,
        "moving_average_200": 1900
    }
    metrics = service._calculate_downside_metrics(stock_data)

    assert metrics["dps"] == 80.0
    assert metrics["yield_40_price"] == 2000.0
    assert metrics["yield_40_diff_pct"] == 0.0
    assert metrics["yield_45_price"] == round(80.0 / 0.045, 1)  # 1777.8
    assert metrics["yield_50_price"] == 1600.0
    assert metrics["bps"] == 2500.0
    assert metrics["bps_diff_pct"] == 25.0
    assert metrics["ma75_price"] == 1950.0
    assert metrics["ma200_price"] == 1900.0
    assert "利回り4.5%換算株価" in metrics["summary_text"]
    assert "BPS (PBR1.0倍ライン" in metrics["summary_text"]


def test_calculate_downside_metrics_zero_and_missing_data():
    """案件 #303: 無配・赤字・データ欠損時におけるゼロ除算・例外防止テスト"""
    service = LLMDiagnosisService()
    # 1. 無配・株価0円・データ欠損
    stock_empty = {
        "price": 0,
        "yield": 0,
        "pbr": None,
        "bps": None
    }
    metrics_empty = service._calculate_downside_metrics(stock_empty)
    assert metrics_empty["dps"] is None
    assert metrics_empty["yield_40_price"] is None
    assert metrics_empty["bps"] is None
    assert "算定対象外" in metrics_empty["summary_text"]

    # 2. BPSが未指定だがPBRから逆算可能な場合
    stock_pbr = {
        "price": 1000,
        "yield": "3.5%",
        "pbr": 2.0
    }
    metrics_pbr = service._calculate_downside_metrics(stock_pbr)
    assert metrics_pbr["dps"] == 35.0
    assert metrics_pbr["bps"] == 500.0  # 1000 / 2.0
    assert metrics_pbr["bps_diff_pct"] == -50.0


def test_diagnose_stock_with_dip_buying(policy_manager):
    """案件 #303: 個別銘柄診断における dip_buying_analysis のパーステスト"""
    service = LLMDiagnosisService(policy_manager=policy_manager)

    mock_llm_response = {
        "fit_level": "fit",
        "confidence_score": 90,
        "decision_label": "【強い買い（コア）】",
        "estimated_yield": "約4.2%",
        "recommended_shares": "約4株",
        "shield_and_valuation": "DOE4.0%下限、PBR0.9倍。",
        "performance_summary": "好調なEPS推移。",
        "trend_analysis": "75日線上で押し目形成中。",
        "material_exhaustion_eval": "材料出尽くし懸念なし。",
        "business_10y_eval": "安定したストックビジネス。",
        "tactical_advice": "1回あたり4株目安でナンピン買い下がり。",
        "dip_buying_analysis": {
            "level1_price": "約2,450円 (利回り4.1%)",
            "level1_rationale": "75日線サポートおよび初期押し目打診買い水準",
            "level2_price": "約2,200円 (利回り4.6%)",
            "level2_rationale": "PBR1.0倍(BPS)および利回り4.6%到達による強固な大底サポート",
            "tactical_memo": "2,450円で初期打診、2,200円でロットを倍増して買い下がり。"
        },
        "summary": "高配当かつ強固な下値支持を持つコア銘柄。"
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": json.dumps(mock_llm_response)}]}}]
    }

    with patch("requests.post", return_value=mock_resp):
        res = service.diagnose_stock({"code": "7164", "name": "全国保証", "price": 2500, "yield": 4.0}, force=True)
        assert res.get("error") is not True
        assert "dip_buying_analysis" in res
        dip = res["dip_buying_analysis"]
        assert "2,450円" in dip["level1_price"]
        assert "2,200円" in dip["level2_price"]
        assert "75日線サポート" in dip["level1_rationale"]
        assert "ロットを倍増" in dip["tactical_memo"]


def test_diagnose_stock_missing_dip_buying_fallback(policy_manager):
    """案件 #303: レスポンスに dip_buying_analysis が欠落していた場合のフォールバック補完テスト"""
    service = LLMDiagnosisService(policy_manager=policy_manager)

    # dip_buying_analysis がない旧形式レスポンス
    mock_old_response = {
        "fit_level": "fit",
        "confidence_score": 88,
        "decision_label": "【買い】",
        "summary": "旧形式の診断結果。"
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": json.dumps(mock_old_response)}]}}]
    }

    with patch("requests.post", return_value=mock_resp):
        res = service.diagnose_stock({"code": "7164", "name": "全国保証"}, force=True)
        assert res.get("error") is not True
        assert "dip_buying_analysis" in res
        dip = res["dip_buying_analysis"]
        assert dip["level1_price"] == "算出中"
        assert dip["level2_price"] == "算出中"
        assert "ナンピン" in dip["tactical_memo"]


def test_format_assets_to_pipe_lines_with_dip_metrics():
    """案件 #303: おすすめ5選用パイプフォーマットに下値目安が含まれているか検証"""
    service = LLMDiagnosisService()
    assets = [
        {
            "code": "7164",
            "name": "全国保証",
            "industry": "その他金融業",
            "price": 2500,
            "per": 12.0,
            "pbr": 0.9,
            "roe": 12.5,
            "yield": 4.0,  # DPS = 100円 -> 4.5%株価は約2,222円
            "score": 12
        }
    ]
    pipe_text = service._format_assets_to_pipe_lines(assets)
    assert "7164" in pipe_text
    assert "仕込:約2,222円" in pipe_text


# --- 案件 #304: 100銘柄分散投資ポリシーに基づく購入上限目安判定テスト ---

def test_calculate_portfolio_cap_metrics_normal():
    """総資産500万円、株価2,500円における1%, 2%, 3%の計算および株数換算検証 (#304)"""
    service = LLMDiagnosisService()
    summary = {"total_market_value": 5_000_000.0}
    metrics = service._calculate_portfolio_cap_metrics(summary, 2500.0)

    assert metrics["total_market_value"] == 5_000_000.0
    assert metrics["is_fallback"] is False
    assert metrics["cap_1pct"] == 50_000      # 500万円 × 1% = 5万円
    assert metrics["cap_2pct"] == 100_000     # 500万円 × 2% = 10万円
    assert metrics["cap_3pct"] == 150_000     # 500万円 × 3% = 15万円
    assert metrics["shares_1pct"] == 20       # 50,000 // 2500 = 20株
    assert metrics["shares_2pct"] == 40       # 100,000 // 2500 = 40株
    assert metrics["shares_3pct"] == 60       # 150,000 // 2500 = 60株
    assert "サテライト枠 (1〜2%分散目安)" in metrics["summary_text"]
    assert "コア枠 (最大3%分散目安)" in metrics["summary_text"]


def test_calculate_portfolio_cap_metrics_small_portfolio_guard():
    """総資産30万円などの小規模資産における最低エントリー下限ガード（2万・3万・5万円）検証 (#304)"""
    service = LLMDiagnosisService()
    summary = {"total_market_value": 300_000.0}
    metrics = service._calculate_portfolio_cap_metrics(summary, 1000.0)

    assert metrics["total_market_value"] == 300_000.0
    # 30万円の1%は3,000円だが最低20,000円にガード
    assert metrics["cap_1pct"] == 20_000
    # 30万円の2%は6,000円だが最低30,000円にガード
    assert metrics["cap_2pct"] == 30_000
    # 30万円の3%は9,000円だが最低50,000円にガード
    assert metrics["cap_3pct"] == 50_000
    assert metrics["shares_1pct"] == 20       # 20,000 // 1000 = 20株
    assert metrics["shares_2pct"] == 30       # 30,000 // 1000 = 30株
    assert metrics["shares_3pct"] == 50       # 50,000 // 1000 = 50株


def test_calculate_portfolio_cap_metrics_fallback():
    """総評価額が0または未設定時の安全なフォールバック（デフォルト300万円基準）検証 (#304)"""
    service = LLMDiagnosisService()
    # 空辞書かつDBにも何もないと仮定したモック
    with patch("history_manager.DB_FILE", "/non/existent/db.db"):
        metrics = service._calculate_portfolio_cap_metrics({}, 2000.0)
        assert metrics["total_market_value"] == 3_000_000.0
        assert metrics["is_fallback"] is True
        assert metrics["cap_1pct"] == 30_000  # 300万 × 1% = 3万円
        assert metrics["cap_2pct"] == 60_000  # 300万 × 2% = 6万円
        assert metrics["cap_3pct"] == 90_000  # 300万 × 3% = 9万円


def test_calculate_portfolio_cap_metrics_zero_price():
    """株価0または無効値時のゼロ除算防止・最低1株保証検証 (#304)"""
    service = LLMDiagnosisService()
    summary = {"total_market_value": 5_000_000.0}
    metrics = service._calculate_portfolio_cap_metrics(summary, 0.0)
    assert metrics["shares_1pct"] == 1
    assert metrics["shares_2pct"] == 1
    assert metrics["shares_3pct"] == 1


def test_parse_llm_json_investment_cap_compatibility():
    """旧形式やキー欠損時でもinvestment_capが自己修復・補完されるか検証 (#304)"""
    service = LLMDiagnosisService()
    # 1. 正常なinvestment_capが含まれている場合
    raw_with_cap = json.dumps({
        "fit_level": "caution",
        "decision_label": "【買い（サテライト）】",
        "investment_cap": {
            "tier": "サテライト枠 (1〜2%)",
            "cap_amount_str": "最大約10万円 (総資産の約2%)",
            "max_shares_str": "累計約40株まで",
            "allocation_plan": "1回あたり1〜2万円×最大2〜3回に限定",
            "reason": "還元ルール変更リスクがあるため上限2%に制限"
        }
    })
    parsed = service._parse_llm_json(raw_with_cap)
    assert "investment_cap" in parsed
    assert parsed["investment_cap"]["tier"] == "サテライト枠 (1〜2%)"
    assert "最大約10万円" in parsed["investment_cap"]["cap_amount_str"]

    # 2. investment_capが完全に欠落している旧キャッシュ形式の場合（fit: コア枠自己修復）
    raw_old_core = json.dumps({
        "fit_level": "fit",
        "decision_label": "【強い買い（コア）】"
    })
    parsed_old_core = service._parse_llm_json(raw_old_core)
    assert "investment_cap" in parsed_old_core
    assert "コア枠" in parsed_old_core["investment_cap"]["tier"]
    assert "最大約15万円" in parsed_old_core["investment_cap"]["cap_amount_str"]

    # 3. investment_capが完全に欠落している旧キャッシュ形式の場合（caution: サテライト枠自己修復）
    raw_old_sat = json.dumps({
        "fit_level": "caution",
        "decision_label": "【買い（サテライト）】"
    })
    parsed_old_sat = service._parse_llm_json(raw_old_sat)
    assert "investment_cap" in parsed_old_sat
    assert "サテライト枠" in parsed_old_sat["investment_cap"]["tier"]
    assert "最大約5万〜10万円" in parsed_old_sat["investment_cap"]["cap_amount_str"]


def test_diagnose_stock_prompt_contains_cap_metrics():
    """_build_prompt に100銘柄分散投資ポリシーに基づく購入上限指標が含まれるか検証 (#304)"""
    service = LLMDiagnosisService()
    stock_data = {
        "code": "7164",
        "name": "全国保証",
        "price": 2500
    }
    summary = {"total_market_value": 10_000_000.0}
    prompt = service._build_prompt(stock_data, summary, "投資方針テスト")

    assert "100銘柄分散投資ポリシーに基づく購入上限参考指標:" in prompt
    assert "ポートフォリオ総評価額: 約 10,000,000 円" in prompt
    assert "サテライト枠 (1〜2%分散目安)" in prompt
    assert "コア枠 (最大3%分散目安)" in prompt
    assert "investment_cap" in prompt


@patch("requests.post")
def test_filtered_recommendations_cap_str_and_fallback(mock_post):
    """おすすめ5選において investment_cap_str が正常にパース・補完されるか検証 (#304)"""
    service = LLMDiagnosisService()
    service.policy_manager.get_effective_api_key = MagicMock(return_value="AIzaSyDummyKey")

    assets = [
        {"code": "7164", "name": "全国保証", "industry": "その他金融業", "price": 2500, "yield": 4.0},
        {"code": "6200", "name": "インソース", "industry": "サービス業", "price": 800, "yield": 4.2}
    ]

    mock_llm_output = {
        "recommendations": [
            {
                "rank": 1,
                "code": "7164",
                "name": "全国保証",
                "industry": "その他金融業",
                "dividend_yield_str": "4.0%",
                "target_buy_price": "約2,222円 (利回り4.5%)",
                "investment_cap_str": "最大約15万円 (総資産の約3%)",
                "role_badge": "【コア枠】新規分散",
                "fit_score": 95,
                "fit_stars": "★★★★★",
                "rationale": "累進配当の盾が強力",
                "risk_factor": "特になし",
                "portfolio_advice": "上限まで買い下がり推奨"
            },
            {
                "rank": 2,
                "code": "6200",
                "name": "インソース",
                "industry": "サービス業",
                "dividend_yield_str": "4.2%",
                "target_buy_price": "約750円",
                # investment_cap_str 欠落時のフォールバックテスト
                "role_badge": "【サテライト枠】新規分散",
                "fit_score": 80,
                "fit_stars": "★★★★☆",
                "rationale": "高ROEだが還元ルール変更リスクあり",
                "risk_factor": "配当性向の戻り",
                "portfolio_advice": "上限1〜2%に限定"
            }
        ],
        "overall_summary": "100銘柄分散投資に合致した選定です。"
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": json.dumps(mock_llm_output)}]}}]
    }
    mock_post.return_value = mock_resp

    summary = {"total_market_value": 5_000_000.0}
    res = service.diagnose_filtered_recommendations(assets, portfolio_summary=summary, force=True)

    assert res.get("error") is not True
    recs = res.get("recommendations", [])
    assert len(recs) == 2
    assert recs[0]["investment_cap_str"] == "最大約15万円 (総資産の約3%)"
    # 欠落していた2件目はサテライト枠として上限約100,000円（約1〜2%）にフォールバック補完される
    assert "上限: 約100,000円 (約1〜2%)" in recs[1]["investment_cap_str"]







