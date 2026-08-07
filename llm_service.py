import json
import re
import requests
from typing import Dict, Any, Optional
from investment_policy_manager import InvestmentPolicyManager

class LLMDiagnosisService:
    """
    Google AI Studio Gemini API (REST Endpoint) を用いて、
    ユーザーの投資方針に基づく銘柄適合診断を実行するサービス。
    """
    def __init__(self, policy_manager: Optional[InvestmentPolicyManager] = None):
        self.policy_manager = policy_manager or InvestmentPolicyManager()

    def diagnose_stock(self, stock_data: Dict[str, Any], portfolio_summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        銘柄データおよびポートフォリオサマリーと投資方針プロンプトに基づき、
        Gemini API にリクエストを送信して構造化診断結果を取得する。
        """
        api_key = self.policy_manager.get_effective_api_key()
        if not api_key:
            return {
                "error": True,
                "error_code": "NO_API_KEY",
                "message": "Google AI Studio の APIキーが設定されていません。「⚙️ 投資方針設定」から APIキー を入力するか、環境変数 GEMINI_API_KEY を設定してください。"
            }

        config = self.policy_manager.load_config()
        selected_model = config.get("selected_model", "gemini-flash-latest")
        if selected_model not in ["gemini-flash-latest", "gemini-flash-lite-latest"]:
            selected_model = "gemini-flash-latest"

        policy_prompt = config.get("policy_prompt", "")
        
        # プロンプトの組み立て
        prompt_text = self._build_prompt(stock_data, portfolio_summary, policy_prompt)

        endpoint_url = f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:generateContent?key={api_key}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt_text}
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2
            }
        }

        headers = {
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(endpoint_url, json=payload, headers=headers, timeout=20.0)
            
            if response.status_code == 429:
                return {
                    "error": True,
                    "error_code": "RATE_LIMIT",
                    "message": "Google AI Studio の無料枠利用上限（レートリミット）に達しました。しばらく時間をおいてから再試行してください。"
                }
            elif response.status_code == 400:
                err_body = response.json() if response.content else {}
                msg = err_body.get("error", {}).get("message", "APIキーが無効か、リクエスト形式が不正です。")
                if "API key not valid" in msg or "API_KEY_INVALID" in msg or "key" in msg.lower():
                    display_msg = "Google AI Studio APIキーが無効です。「⚙️ 投資方針」設定画面で正しい API Key を入力して保存してください。"
                else:
                    display_msg = f"APIリクエストエラー (400): {msg}"
                return {
                    "error": True,
                    "error_code": "BAD_REQUEST",
                    "message": display_msg
                }
            elif response.status_code != 200:
                return {
                    "error": True,
                    "error_code": f"HTTP_{response.status_code}",
                    "message": f"Gemini API 通信エラー (ステータスコード: {response.status_code})"
                }

            res_json = response.json()
            candidates = res_json.get("candidates", [])
            if not candidates:
                return {
                    "error": True,
                    "error_code": "NO_CANDIDATE",
                    "message": "Gemini API から応答コンテンツが取得できませんでした。"
                }

            raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            parsed_result = self._parse_llm_json(raw_text)
            parsed_result["model_used"] = selected_model
            parsed_result["error"] = False
            return parsed_result

        except requests.exceptions.Timeout:
            return {
                "error": True,
                "error_code": "TIMEOUT",
                "message": "Gemini API との通信がタイムアウトしました（20秒）。ネットワーク環境を確認して再度お試しください。"
            }
        except Exception as e:
            return {
                "error": True,
                "error_code": "SYSTEM_ERROR",
                "message": f"AI診断実行中にエラーが発生しました: {str(e)}"
            }

    def _build_prompt(self, stock_data: Dict[str, Any], portfolio_summary: Optional[Dict[str, Any]], policy_prompt: str) -> str:
        """銘柄データと投資方針から LLM に送るプロンプトを構築"""
        code = stock_data.get("code", "")
        name = stock_data.get("name", "")
        price = stock_data.get("price", "N/A")
        change_rate = stock_data.get("change_rate", "N/A")
        per = stock_data.get("per", "N/A")
        pbr = stock_data.get("pbr", "N/A")
        roe = stock_data.get("roe", "N/A")
        dividend_yield = stock_data.get("yield", "N/A")
        payout_ratio = stock_data.get("payout_ratio", "N/A")
        consecutive_increase = stock_data.get("consecutive_increase", 0)
        industry = stock_data.get("industry", "不明")
        fiscal_month = stock_data.get("fiscal_month", "不明")
        
        # 保有情報
        holdings = stock_data.get("holdings", [])
        total_quantity = sum(h.get("quantity", 0) for h in holdings)
        eval_value = stock_data.get("evaluation_value", 0)
        
        portfolio_ratio = "0%"
        if portfolio_summary and portfolio_summary.get("total_evaluation_value", 0) > 0:
            ratio_val = (eval_value / portfolio_summary["total_evaluation_value"]) * 100
            portfolio_ratio = f"{ratio_val:.2f}%"

        # シグナル情報
        signal_info = stock_data.get("buy_signal") or stock_data.get("sell_signal") or {}
        signal_label = signal_info.get("label", "シグナルなし")
        signal_action = signal_info.get("recommended_action", "")

        prompt = f"""以下はユーザーが設定した【基本投資方針およびスクリーニングルール】です。
--------------------------------------------------
{policy_prompt}
--------------------------------------------------

上記投資方針に基づき、以下の【診断対象銘柄データ】を精査・判定してください。

【診断対象銘柄データ】
- 銘柄コード: {code} / 銘柄名: {name} / 業種: {industry} / 決算月: {fiscal_month}
- 現在株価: {price}円 (前日比: {change_rate}%)
- PER: {per}倍 / PBR: {pbr}倍 / ROE: {roe}%
- 予想配当利回り: {dividend_yield}% / 予想配当性向: {payout_ratio}% / 連続増配年数: {consecutive_increase}年
- テクニカル/テクニカル判定: {signal_label} ({signal_action})
- 現在の自ポートフォリオ内状況: 保有数 {total_quantity}株 / 評価額 {eval_value:,}円 / ポートフォリオ全体比率 {portfolio_ratio}

【要求する出力形式】
JSONフォーマットで回答を出力してください。キーは必ず以下の通りとすること:
{{
  "fit_level": "fit" または "caution" または "unfit",
  "confidence_score": この判定結果(コア/サテライト/Avoid)に対するAIアナリスト自身の【分析の確信度・自信度】(0〜100の数値)。※注意: 適合度の割合ではありません。例えば【見送り(Avoid)】とする判断に強い確信・自信がある場合は 90〜100 の高い数値を出力してください。,
  "decision_label": "【判定ラベル】(例: 【強い買い（コア）】 / 【買い（サテライト）】 / 【中立・監視】 / 【見送り（Avoid）】)",
  "estimated_yield": "予想配当利回りの記載(例: 約4.4%)",
  "recommended_shares": "1回あたりの購入目安株数の記載(例: 約3株〜4株)",
  "shield_and_valuation": "「還元の盾」およびPBR/PER過熱感の評価詳細",
  "business_10y_eval": "10年スパンでの事業評価（ポジティブ要因・ネガティブ要因）",
  "tactical_advice": "本システム/S株ナンピンにおける具体的な立ち回りアドバイス",
  "summary": "1〜2文による総合判定の簡潔な要約"
}}
fit_levelの基準:
- fit: 【コア枠】または【高利回りブースター枠】に適合する買い候補
- caution: 【サテライト枠】または条件付きでの買い・監視候補
- unfit: 【見送り（Avoid）】NGパターン該当など買付非推奨の銘柄
"""
        return prompt

    def _parse_llm_json(self, raw_text: str) -> Dict[str, Any]:
        """LLMからのテキスト応答を安全に JSON パースする"""
        cleaned = raw_text.strip()
        # ```json ``` の囲み除去
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if match:
            cleaned = match.group(1).strip()

        try:
            data = json.loads(cleaned)
        except Exception:
            # フォールバックレスポンス
            return {
                "fit_level": "caution",
                "confidence_score": 50,
                "decision_label": "【判定解析中】",
                "estimated_yield": "要確認",
                "recommended_shares": "要確認",
                "shield_and_valuation": "レスポンスのパースに一部失敗しましたが、詳細テキストを以下に示します。",
                "business_10y_eval": raw_text[:500],
                "tactical_advice": "手動での最終確認を推奨します。",
                "summary": "AIからの応答フォーマットを調整しました。"
            }

        # 必須キーの補完と確信度の補正
        fit_level = data.get("fit_level", "caution")
        if fit_level not in ["fit", "caution", "unfit"]:
            fit_level = "caution"

        raw_score = data.get("confidence_score", 85)
        try:
            confidence_score = int(raw_score)
        except (ValueError, TypeError):
            confidence_score = 85

        # LLMが「適合度の割合=0%」と「AIの分析確信度」を混同して低スコアを出力した場合の安全補正
        if confidence_score < 30 and data.get("summary"):
            confidence_score = 90

        return {
            "fit_level": fit_level,
            "confidence_score": confidence_score,
            "decision_label": str(data.get("decision_label", "【判定完了】")),
            "estimated_yield": str(data.get("estimated_yield", "N/A")),
            "recommended_shares": str(data.get("recommended_shares", "N/A")),
            "shield_and_valuation": str(data.get("shield_and_valuation", "データなし")),
            "business_10y_eval": str(data.get("business_10y_eval", "データなし")),
            "tactical_advice": str(data.get("tactical_advice", "データなし")),
            "summary": str(data.get("summary", "診断が完了しました。"))
        }
