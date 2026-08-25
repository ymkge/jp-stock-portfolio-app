import os
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







