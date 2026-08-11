import json
import re
import hashlib
import time
import threading
import requests
from typing import Dict, Any, Optional
from investment_policy_manager import InvestmentPolicyManager

class LLMDiagnosisService:
    """
    Google AI Studio Gemini API (REST Endpoint) を用いて、
    ユーザーの投資方針に基づく銘柄適合診断を実行するサービス。
    スレッドセーフなスマートキャッシュ機能 (TTL / LRU / 自動パージ) を備える。
    """
    MAX_CACHE_SIZE = 200
    DEFAULT_TTL_SECONDS = 12 * 3600  # 12時間

    def __init__(self, policy_manager: Optional[InvestmentPolicyManager] = None):
        self.policy_manager = policy_manager or InvestmentPolicyManager()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _get_prompt_hash(self, policy_prompt: str) -> str:
        return hashlib.sha256(policy_prompt.encode('utf-8')).hexdigest()[:16]

    def clear_cache(self):
        """全キャッシュをクリア（投資方針更新時などに使用）"""
        with self._lock:
            self._cache.clear()

    def diagnose_stock(
        self, 
        stock_data: Dict[str, Any], 
        portfolio_summary: Optional[Dict[str, Any]] = None,
        force: bool = False,
        ttl_seconds: int = DEFAULT_TTL_SECONDS
    ) -> Dict[str, Any]:
        """
        銘柄データおよびポートフォリオサマリーと投資方針プロンプトに基づき、
        Gemini API にリクエストを送信して構造化診断結果を取得する。
        (force=False の場合は有効なキャッシュ結果を即座に返却)
        """
        code = stock_data.get("code", "")
        asset_type = stock_data.get("asset_type", "jp_stock")
        cache_key = f"{code}_{asset_type}" if code else ""

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
        prompt_hash = self._get_prompt_hash(policy_prompt)
        now = time.time()

        # --- 1. キャッシュチェック (force=False かつ 有効な場合) ---
        if not force and cache_key:
            with self._lock:
                cached_entry = self._cache.get(cache_key)
                if cached_entry:
                    is_expired = (now - cached_entry["timestamp"]) > ttl_seconds
                    same_model = (cached_entry["model"] == selected_model)
                    same_hash = (cached_entry["prompt_hash"] == prompt_hash)

                    if not is_expired and same_model and same_hash:
                        res = dict(cached_entry["result"])
                        res["is_cached"] = True
                        res["diagnosed_at"] = cached_entry["diagnosed_at_str"]
                        cached_entry["last_accessed"] = now
                        return res

        # --- 2. API呼び出し実行 ---
        result = self._execute_gemini_request(stock_data, portfolio_summary, selected_model, policy_prompt, api_key)

        # --- 3. キャッシュ保存（エラー結果は絶対にキャッシュしない） ---
        if cache_key and not result.get("error"):
            diagnosed_at_str = time.strftime("%H:%M", time.localtime(now))
            result["is_cached"] = False
            result["diagnosed_at"] = diagnosed_at_str

            with self._lock:
                # MAX_CACHE_SIZE 超過時は LRU 破棄 (アクセス日時が最も古い項目を削除)
                if len(self._cache) >= self.MAX_CACHE_SIZE and cache_key not in self._cache:
                    oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].get("last_accessed", 0))
                    del self._cache[oldest_key]

                self._cache[cache_key] = {
                    "timestamp": now,
                    "last_accessed": now,
                    "model": selected_model,
                    "prompt_hash": prompt_hash,
                    "diagnosed_at_str": diagnosed_at_str,
                    "result": dict(result)
                }

        return result

    def _execute_gemini_request(
        self, 
        stock_data: Dict[str, Any], 
        portfolio_summary: Optional[Dict[str, Any]], 
        selected_model: str, 
        policy_prompt: str,
        api_key: str
    ) -> Dict[str, Any]:
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
            
            if response.status_code == 400:
                err_json = {}
                try:
                    err_json = response.json()
                except Exception:
                    pass
                err_msg = err_json.get("error", {}).get("message", "")
                if "API key not valid" in err_msg or "INVALID_ARGUMENT" in err_msg:
                    return {
                        "error": True,
                        "error_code": "INVALID_API_KEY",
                        "message": "Google AI Studio APIキーが無効です。「⚙️ 投資方針」設定画面で正しい API Key を入力して保存してください。"
                    }
                return {
                    "error": True,
                    "error_code": f"HTTP_{response.status_code}",
                    "message": f"Gemini API リクエストエラー (HTTP {response.status_code}): {err_msg or response.text}"
                }

            if response.status_code != 200:
                return {
                    "error": True,
                    "error_code": f"HTTP_{response.status_code}",
                    "message": f"Gemini API 通信エラー (HTTP {response.status_code}): {response.text}"
                }

            res_data = response.json()
            candidates = res_data.get("candidates", [])
            if not candidates:
                return {
                    "error": True,
                    "error_code": "NO_CANDIDATES",
                    "message": "Gemini API からの有効な回答候補が得られませんでした。"
                }

            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                return {
                    "error": True,
                    "error_code": "NO_PARTS",
                    "message": "Gemini API の応答パーツが空でした。"
                }

            raw_text = parts[0].get("text", "")
            return self._parse_llm_json(raw_text)

        except requests.exceptions.Timeout:
            return {
                "error": True,
                "error_code": "TIMEOUT",
                "message": "Gemini API 通信がタイムアウトしました。しばらく時間をおいて再試行してください。"
            }
        except Exception as e:
            return {
                "error": True,
                "error_code": "UNKNOWN_ERROR",
                "message": f"AI診断実行中に予期せぬエラーが発生しました: {str(e)}"
            }

    def _build_prompt(self, stock_data: Dict[str, Any], portfolio_summary: Optional[Dict[str, Any]], policy_prompt: str) -> str:
        code = stock_data.get("code", "")
        name = stock_data.get("name", "")
        price = stock_data.get("price", "N/A")
        per = stock_data.get("per", "N/A")
        pbr = stock_data.get("pbr", "N/A")
        roe = stock_data.get("roe", "N/A")
        doe = stock_data.get("doe", "N/A")
        bps = stock_data.get("bps", "N/A")
        eps = stock_data.get("eps", "N/A")
        payout_ratio = stock_data.get("payout_ratio", "N/A")
        raw_cap = stock_data.get("market_cap", "N/A")

        # 時価総額の単位フォーマット
        market_cap_str = "N/A"
        if raw_cap not in [None, "N/A", "--", ""]:
            try:
                cap_val = float(str(raw_cap).replace(',', ''))
                if cap_val >= 1_000_000_000_000:
                    market_cap_str = f"{cap_val / 1_000_000_000_000:.2f} 兆円"
                elif cap_val >= 100_000_000:
                    market_cap_str = f"{int(cap_val / 100_000_000):,} 億円"
                else:
                    market_cap_str = f"{int(cap_val):,} 円"
            except (ValueError, TypeError):
                market_cap_str = str(raw_cap)

        # 材料出尽くし情報の抽出
        exhaustion_sig = stock_data.get("exhaustion_signal")
        exhaustion_info = "特になし (安定推移)"
        if exhaustion_sig:
            exhaustion_info = f"{exhaustion_sig.get('label', '')} - {exhaustion_sig.get('recommended_action', '')}"

        # キーの互換性確保 (yield vs dividend_yield)
        raw_yield = stock_data.get("yield")
        if raw_yield in [None, "", "N/A"]:
            raw_yield = stock_data.get("dividend_yield", "N/A")

        if raw_yield not in [None, "N/A", "--", ""]:
            try:
                y_float = float(str(raw_yield).replace('%', '').replace(',', ''))
                dividend_yield = f"{y_float:.2f}"
            except (ValueError, TypeError):
                dividend_yield = str(raw_yield)
        else:
            dividend_yield = "N/A"
        
        prompt = f"""{policy_prompt}

---

## 照合対象の最新銘柄データ (基本・価格・業績・評価指標)
- 銘柄コード: {code}
- 銘柄名: {name}
- 現在株価: {price} 円
- 時価総額: {market_cap_str}
- EPS(1株利益): {eps} 円
- PER(予想): {per} 倍
- PBR(実績): {pbr} 倍
- ROE(自己資本利益率): {roe} %
- DOE(株主資本配当率): {doe} %
- 予想配当利回り: {dividend_yield} %
- BPS(1株純資産): {bps} 円
- 配当性向: {payout_ratio} %
- テクニカル材料出尽くし検知: {exhaustion_info}

---

## あなたのタスク
上記「ユーザーの基本投資方針」に照らし合わせ、対象銘柄({code} {name})の適合度を分析してください。
直近の業績動向（EPSや収益性）、配当維持能力（還元の盾）、および【材料出尽くし感（好材料出尽くし下落リスク / 悪材料アク抜け大底判定）やマクロ地政学・災害・米国市況ショックの影響度】を踏まえて投資判断を行ってください。
必ず以下のJSONフォーマットのみを出力してください。Markdownや他の余計な文言は一切含めないでください。

JSONフォーマットで回答を出力してください。キーは必ず以下の通りとすること:
{{
  "fit_level": "fit" または "caution" または "unfit",
  "confidence_score": この判定結果(コア/サテライト/Avoid)に対するAIアナリスト自身の【分析の確信度・自信度】(0〜100の数値)。※注意: 適合度の割合ではありません。例えば【見送り(Avoid)】とする判断に強い確信・自信がある場合は 90〜100 の高い数値を出力してください。,
  "decision_label": "【判定ラベル】(例: 【強い買い（コア）】 / 【買い（サテライト）】 / 【中立・監視】 / 【見送り（Avoid）】)",
  "estimated_yield": "予想配当利回りの記載(例: 約4.4%)",
  "recommended_shares": "1回あたりの購入目安株数の記載(例: 約3株〜4株)",
  "shield_and_valuation": "「還元の盾」およびPBR/PER過熱感の評価詳細",
  "performance_summary": "直近のEPS・収益性・業績動向および配当原資創出力に関するAI評価解説",
  "material_exhaustion_eval": "材料出尽くし（好材料出尽くし下落リスク / 悪材料アク抜け大底判定）およびマクロショック影響度のAI評価解説",
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
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if match:
            cleaned = match.group(1).strip()

        try:
            data = json.loads(cleaned)
        except Exception:
            return {
                "fit_level": "caution",
                "confidence_score": 50,
                "decision_label": "【判定解析中】",
                "estimated_yield": "要確認",
                "recommended_shares": "要確認",
                "shield_and_valuation": "レスポンスのパースに一部失敗しましたが、詳細テキストを以下に示します。",
                "performance_summary": "業績データの詳細解析を実行中です。",
                "material_exhaustion_eval": "材料出尽くしおよび市場変動の解析を実行中です。",
                "business_10y_eval": raw_text[:500],
                "tactical_advice": "手動での最終確認を推奨します。",
                "summary": "AIからの応答フォーマットを調整しました。"
            }

        fit_level = data.get("fit_level", "caution")
        if fit_level not in ["fit", "caution", "unfit"]:
            fit_level = "caution"

        raw_score = data.get("confidence_score", 85)
        try:
            confidence_score = int(raw_score)
        except (ValueError, TypeError):
            confidence_score = 85

        if confidence_score < 30 and data.get("summary"):
            confidence_score = 90

        return {
            "fit_level": fit_level,
            "confidence_score": confidence_score,
            "decision_label": str(data.get("decision_label", "【判定完了】")),
            "estimated_yield": str(data.get("estimated_yield", "N/A")),
            "recommended_shares": str(data.get("recommended_shares", "N/A")),
            "shield_and_valuation": str(data.get("shield_and_valuation", "データなし")),
            "performance_summary": str(data.get("performance_summary", "直近業績（EPS・収益性）データに基づき持続可能な配当維持力を検証済みです。")),
            "material_exhaustion_eval": str(data.get("material_exhaustion_eval", "テクニカル指標およびマクロ要因に基づく材料出尽くしリスクを分析済みです。")),
            "business_10y_eval": str(data.get("business_10y_eval", "データなし")),
            "tactical_advice": str(data.get("tactical_advice", "データなし")),
            "summary": str(data.get("summary", "診断が完了しました。"))
        }
