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
        self._profit_taking_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _get_prompt_hash(self, policy_prompt: str) -> str:
        return hashlib.sha256(policy_prompt.encode('utf-8')).hexdigest()[:16]

    def clear_cache(self):
        """全キャッシュをクリア（投資方針更新時などに使用）"""
        with self._lock:
            self._cache.clear()
            self._profit_taking_cache.clear()

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

        # 75日・200日移動平均線と乖離率の算定
        price_num = 0.0
        try:
            p_str = str(price).replace(',', '')
            price_num = float(p_str)
        except (ValueError, TypeError): pass

        ma75_val = stock_data.get("moving_average_75") or stock_data.get("ma75")
        ma200_val = stock_data.get("moving_average_200") or stock_data.get("ma200")

        ma75_info = "N/A"
        dev75_val = None
        if ma75_val not in [None, "N/A", "", "--"]:
            try:
                m75 = float(str(ma75_val).replace(',', ''))
                dev75 = ((price_num - m75) / m75 * 100) if (price_num > 0 and m75 > 0) else 0.0
                dev75_val = dev75
                ma75_info = f"{m75:,.1f} 円 (乖離率: {dev75:+.1f}%)"
            except (ValueError, TypeError):
                ma75_info = str(ma75_val)

        ma200_info = "N/A"
        dev200_val = None
        if ma200_val not in [None, "N/A", "", "--"]:
            try:
                m200 = float(str(ma200_val).replace(',', ''))
                dev200 = ((price_num - m200) / m200 * 100) if (price_num > 0 and m200 > 0) else 0.0
                dev200_val = dev200
                ma200_info = f"{m200:,.1f} 円 (乖離率: {dev200:+.1f}%)"
            except (ValueError, TypeError):
                ma200_info = str(ma200_val)

        # トレンド状態の判定ラベル
        trend_info = "不明 (データ不足)"
        if price_num > 0 and dev75_val is not None and dev200_val is not None:
            m75_num = float(str(ma75_val).replace(',', ''))
            m200_num = float(str(ma200_val).replace(',', ''))
            if price_num > m75_num and m75_num > m200_num:
                trend_info = "📈 上昇トレンド (パーフェクトオーダー・強気順張り)"
            elif price_num < m75_num and price_num > m200_num:
                trend_info = "⛅ 中期調整 (75日線下・200日線上: 絶好の押し目圏)"
            elif price_num > m75_num and price_num < m200_num:
                trend_info = "⚡ 戻り試す展開 (75日線上・200日線下)"
            elif dev200_val <= -5.0:
                trend_info = f"📉 長期下降トレンド (200日線乖離 {dev200_val:.1f}%: 底打ち未確認)"
            else:
                trend_info = "📉 長期調整中 (200日線割れ)"
        elif dev75_val is not None:
            if dev75_val < 0:
                trend_info = "⛅ 75日線下割れ (長期調整中)"
            else:
                trend_info = "📈 75日線上推移 (良好)"

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
- 75日移動平均線 (MA75): {ma75_info}
- 200日移動平均線 (MA200): {ma200_info}
- 移動平均トレンド状態: {trend_info}
- テクニカル材料出尽くし検知: {exhaustion_info}

---

## あなたのタスク
上記「ユーザーの基本投資方針」に照らし合わせ、対象銘柄({code} {name})の適合度を分析してください。
直近の業績動向（EPSや収益性）、配当維持能力（還元の盾）、および【75日・200日移動平均線との位置関係（上昇トレンド／押し目圏／長期下降トレンド）】と【材料出尽くし感（好材料出尽くし下落リスク / 悪材料アク抜け大底判定）やマクロ地政学・災害・米国市況ショックの影響度】を踏まえて投資判断を行ってください。
※重要: トレンドが「上昇トレンド」や「絶好の押し目圏」にある場合は、順張り・格安エントリーの観点から分析の確信度 (confidence_score) を高め(85〜95点)に算出して後押しし、長期下降トレンド下では慎重な確信度・立ち回りを提示してください。
必ず以下のJSONフォーマットのみを出力してください。Markdownや他の余計な文言は一切含めないでください。

JSONフォーマットで回答を出力してください。キーは必ず以下の通りとすること:
{{
  "fit_level": "fit" または "caution" または "unfit",
  "confidence_score": この判定結果(コア/サテライト/Avoid)に対するAIアナリスト自身の【分析の確信度・自信度】(0〜100の数値)。※注意: 適合度の割合ではありません。順張りや絶好の押し目圏にある買い候補の場合は 85〜95 の高い数値を出力してください。,
  "decision_label": "【判定ラベル】(例: 【強い買い（コア）】 / 【買い（サテライト）】 / 【中立・監視】 / 【見送り（Avoid）】)",
  "estimated_yield": "予想配当利回りの記載(例: 約4.4%)",
  "recommended_shares": "1回あたりの購入目安株数の記載(例: 約3株〜4株)",
  "shield_and_valuation": "「還元の盾」およびPBR/PER過熱感の評価詳細",
  "performance_summary": "直近のEPS・収益性・業績動向および配当原資創出力に関するAI評価解説",
  "trend_analysis": "75日・200日移動平均線を踏まえた長中期トレンドの簡潔な評価解説（※1〜2文程度のコンパクトな文章とすること）",
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
                "trend_analysis": "75日・200日移動平均線を踏まえたトレンド分析を実行中です。",
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
            "trend_analysis": str(data.get("trend_analysis", "75日・200日移動平均線との位置関係およびトレンド状態を考慮した分析を実行済みです。")),
            "material_exhaustion_eval": str(data.get("material_exhaustion_eval", "テクニカル指標およびマクロ要因に基づく材料出尽くしリスクを分析済みです。")),
            "business_10y_eval": str(data.get("business_10y_eval", "データなし")),
            "tactical_advice": str(data.get("tactical_advice", "データなし")),
            "summary": str(data.get("summary", "診断が完了しました。"))
        }

    def diagnose_profit_taking(
        self,
        holding_item: Dict[str, Any],
        force: bool = False,
        ttl_seconds: int = DEFAULT_TTL_SECONDS
    ) -> Dict[str, Any]:
        """
        利確検討銘柄データと投資方針プロンプトに基づき、Gemini APIを用いて
        今利益確定すべきか（継続保有 / 一部利確 / 全額利確・銘柄入替）を診断する (#281)。
        """
        code = holding_item.get("code", "")
        asset_type = holding_item.get("asset_type", "jp_stock")
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

        if not force and cache_key:
            with self._lock:
                cached = self._profit_taking_cache.get(cache_key)
                if cached:
                    if (now - cached["timestamp"] < ttl_seconds) and (cached.get("prompt_hash") == prompt_hash):
                        res = dict(cached["result"])
                        res["is_cached"] = True
                        res["diagnosed_at"] = cached.get("diagnosed_at", "")
                        res["model_used"] = cached.get("model_used", selected_model)
                        return res

        prompt_text = self._build_profit_taking_prompt(holding_item, policy_prompt)

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:generateContent?key={api_key}"
        payload = {
            "contents": [{
                "parts": [{"text": prompt_text}]
            }],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json"
            }
        }

        try:
            resp = requests.post(url, json=payload, timeout=20)
            if resp.status_code == 400 and "API_KEY_INVALID" in resp.text:
                return {
                    "error": True,
                    "error_code": "INVALID_API_KEY",
                    "message": "Google AI Studio の APIキーが無効です。「⚙️ 投資方針設定」で正しい APIキー を設定してください。"
                }
            resp.raise_for_status()

            res_json = resp.json()
            candidates = res_json.get("candidates", [])
            if not candidates:
                return {
                    "error": True,
                    "error_code": "EMPTY_RESPONSE",
                    "message": "AIからの応答が空でした。再度お試しください。"
                }

            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                return {
                    "error": True,
                    "error_code": "EMPTY_RESPONSE",
                    "message": "AIからの応答テキストが含まれていません。"
                }

            raw_text = parts[0].get("text", "")
            parsed = self._parse_profit_taking_llm_json(raw_text)
            parsed["error"] = False
            parsed["code"] = code
            parsed["name"] = holding_item.get("name", "")
            parsed["is_cached"] = False
            diagnosed_at_str = time.strftime("%H:%M", time.localtime(now))
            parsed["diagnosed_at"] = diagnosed_at_str
            parsed["model_used"] = selected_model

            if cache_key:
                with self._lock:
                    if len(self._profit_taking_cache) >= self.MAX_CACHE_SIZE:
                        oldest_key = min(self._profit_taking_cache.keys(), key=lambda k: self._profit_taking_cache[k]["timestamp"])
                        del self._profit_taking_cache[oldest_key]
                    self._profit_taking_cache[cache_key] = {
                        "timestamp": now,
                        "prompt_hash": prompt_hash,
                        "diagnosed_at": diagnosed_at_str,
                        "model_used": selected_model,
                        "result": parsed
                    }

            return parsed

        except requests.exceptions.Timeout:
            return {
                "error": True,
                "error_code": "TIMEOUT_ERROR",
                "message": "Gemini API との通信がタイムアウトしました (20秒)。ネットワーク環境を確認の上、再実行してください。"
            }
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else "Unknown"
            if status_code == 429:
                return {
                    "error": True,
                    "error_code": "RATE_LIMIT",
                    "message": "Gemini API の利用制限 (429) に達しました。しばらく時間をおいてから再実行してください。"
                }
            return {
                "error": True,
                "error_code": f"HTTP_{status_code}",
                "message": f"Gemini API 通信エラー (HTTP {status_code}) が発生しました。"
            }
        except Exception as e:
            return {
                "error": True,
                "error_code": "UNKNOWN_ERROR",
                "message": f"利確AI診断中に予期せぬエラーが発生しました: {str(e)}"
            }

    def _build_profit_taking_prompt(self, item: Dict[str, Any], policy_prompt: str) -> str:
        code = item.get("code", "N/A")
        name = item.get("name", "N/A")
        industry = item.get("industry", "未設定・不明")
        asset_type = item.get("asset_type", "jp_stock")
        quantity = item.get("quantity", 0)
        market_value = item.get("market_value", 0.0)
        profit_loss = item.get("profit_loss", 0.0)
        estimated_annual_dividend = item.get("estimated_annual_dividend", 0.0)
        dividend_years_ratio = item.get("dividend_years_ratio", 0.0)
        dividend_yield = item.get("dividend_yield", "N/A")

        badge = item.get("profit_taking_badge", {})
        badge_label = badge.get("label", f"配当{dividend_years_ratio}年分達成")

        per = item.get("per", "N/A")
        pbr = item.get("pbr", "N/A")
        roe = item.get("roe", "N/A")
        eps = item.get("eps", "N/A")
        market_cap = item.get("market_cap", "N/A")
        payout_ratio = item.get("payout_ratio", "N/A")
        doe = item.get("doe", "N/A")
        consecutive_years = item.get("consecutive_increase_years", "N/A")
        doe_str = f"{doe}%" if isinstance(doe, (int, float)) else str(doe)
        inc_str = f"{consecutive_years}年連続増配" if isinstance(consecutive_years, (int, float)) and consecutive_years > 0 else str(consecutive_years)

        prompt = f"""
あなたは高度なポートフォリオ管理および個別銘柄の利確・銘柄入替戦略を専門とするプロフェッショナルなAIアナリストです。
現在、ユーザーのポートフォリオに含まれる以下の「利確・銘柄入替検討銘柄」について、利益確定・元本回収・乗り換えの必要性を詳細に評価・診断してください。

### 【ユーザーの投資方針プロンプト】
{policy_prompt}

### 【対象銘柄の保有・含み益・利確指標・ファンダメンタルズデータ】
- 銘柄名: {name} (コード: {code})
- 所属業種/セクター: {industry}
- 資産タイプ: {asset_type}
- 保有数量: {quantity}
- 現在評価額: {market_value:,.0f}円
- 含み益: +{profit_loss:,.0f}円
- 年間予定配当: {estimated_annual_dividend:,.0f}円
- 配当年数到達度: {badge_label} (含み益は年間配当の {dividend_years_ratio} 年分に到達)
- 直近実効配当利回り: {dividend_yield}%
- 時価総額: {market_cap} / PER: {per} / PBR: {pbr} / ROE: {roe} / EPS: {eps} / 配当性向: {payout_ratio} / DOE: {doe_str} / 還元姿勢: {inc_str}

---

### 【重要判定規則：業種将来性・日本政府国策投資・株主還元姿勢と利確の適正バランシングルール】
1. **業種将来性・日本政府の国策投資方針の重視（安易な全額利確の抑制）**:
   - 銘柄の所属業種（{industry}）が今後も需要拡大が見込まれる成長分野（例: IT/DX、半導体、精密機器、ヘルスケア、防衛・宇宙、インフラ老朽化対策、グローバル成長分野など）であるか、または**日本政府が長期的な政策投資・予算投入を行っている国策テーマ（GX/脱炭素、デジタル基盤、経済安保・半導体支援、防衛産業等）**に該当し、かつ高ROEやEPS成長など企業の稼ぐ力が強い場合、株価高騰によって配当利回りが低下していても**安易に「FULL_SELL（全額利確）」を判定してはなりません**。
   - このような優良・国策成長銘柄に対しては「HOLD（継続保有）」、または投入元本のみを利確回収して残りをリスクフリーで育てる「PARTIAL_SELL（一部利確・恩株化）」を優先推奨してください。
2. **累進配当方針・DOE導入・株主還元姿勢の重視（減配リスク抑制）**:
   - 企業の配当方針（DOEの導入、累進配当の公表、長年の連続増配実績など）により、減配リスクが極めて低く配当の安定性・成長性が担保されている銘柄は、含み益が大きく配当利回りが一時的に低下していても、安心感のあるインカムゲイン基盤を崩す全額利確（FULL_SELL）を避け、「🟢 継続保有 (HOLD)」または投入元本のみを利確回収して残りをリスクフリーで育てる「🟡 一部利確 (PARTIAL_SELL・恩株化)」を最優先に推奨してください。
3. **「FULL_SELL（全額利確）」を適用する厳格な条件**:
   - 所属業種自体の将来性が乏しく（成熟・衰退分野）、政府の政策支援やメガトレンドの追い風もなく、減配リスクがあり、業績（純利益・EPS）も伸び悩みまたは悪化傾向にあり、かつ配当利回りも低下してインカム・キャピタルの両面で魅力が薄れた場合に限定して適用してください。

---

### 【回答のフォーマット指示】
必ず以下のキーを持つ完全な JSON フォーマットのみを出力してください。余計な解説文やマーカーは含めないでください。

```json
{{
  "action": "HOLD" または "PARTIAL_SELL" または "FULL_SELL",
  "action_label": "🟢 継続保有を推奨" または "🟡 一部利確・元本回収を推奨" または "🔴 全額利確・他銘柄へ入替を推奨",
  "target_sell_ratio": "利確の目安株数・割合 (例: 保有株数の 1/2 を利確、全額利確、売却なし等)",
  "industry_growth_evaluation": "所属業種の将来性、日本政府の国策投資・メガトレンド適合度、成長ストーリーの評価",
  "fundamentals_analysis": "直近業績・収益性指標（PER/PBR/ROE/EPS/DOE/累進配当・連続増配等の還元姿勢）の分析",
  "profit_taking_advice": "利確・恩株化・乗り換え戦略の具体的アドバイス（トータル配当原資最大化および安定インカム維持の視点を含む）",
  "summary": "判定の結論とポイントを1文で要約"
}}
```
"""
        return prompt.strip()

    def _parse_profit_taking_llm_json(self, raw_text: str) -> Dict[str, Any]:
        """利確AI診断からのテキスト応答を安全に JSON パースする"""
        cleaned = raw_text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if match:
            cleaned = match.group(1).strip()

        try:
            data = json.loads(cleaned)
        except Exception:
            return {
                "action": "PARTIAL_SELL",
                "action_label": "🟡 一部利確・元本回収を推奨",
                "target_sell_ratio": "要確認 (保有株の 1/3〜1/2 目安)",
                "industry_growth_evaluation": "所属業種の成長性と国策・メガトレンドへの適合性を総合評価しています。",
                "fundamentals_analysis": "業績データの詳細解析を実行済みです。",
                "profit_taking_advice": raw_text[:500],
                "summary": "AIのテキストに応答フォーマットを調整して提示します。"
            }

        action = str(data.get("action", "PARTIAL_SELL")).upper()
        if action not in ["HOLD", "PARTIAL_SELL", "FULL_SELL"]:
            action = "PARTIAL_SELL"

        action_label = str(data.get("action_label", ""))
        if not action_label:
            if action == "HOLD":
                action_label = "🟢 継続保有を推奨"
            elif action == "FULL_SELL":
                action_label = "🔴 全額利確・他銘柄へ入替を推奨"
            else:
                action_label = "🟡 一部利確・元本回収を推奨"

        return {
            "action": action,
            "action_label": action_label,
            "target_sell_ratio": str(data.get("target_sell_ratio", "状況に応じて調整")),
            "industry_growth_evaluation": str(data.get("industry_growth_evaluation", "")),
            "fundamentals_analysis": str(data.get("fundamentals_analysis", "直近業績・ファンダメンタルズおよび配当効率の分析を完了しました。")),
            "profit_taking_advice": str(data.get("profit_taking_advice", "配当原資の最大化とポートフォリオ最適化の観点から助言を作成しました。")),
            "summary": str(data.get("summary", "利確AI診断を完了しました。"))
        }

    def fetch_market_fibonacci_llm(self, current_n225: float = 0.0, current_topix: float = 0.0) -> Dict[str, Any]:
        """Gemini AIに問い合わせて直近3年間の日経平均・TOPIXの最高値・最安値・発生年月および相場解説を取得する (#231)"""
        api_key = self.policy_manager.get_effective_api_key()
        if not api_key:
            return {"error": True, "message": "NO_API_KEY"}

        config = self.policy_manager.load_config()
        selected_model = config.get("selected_model", "gemini-flash-latest")
        if selected_model not in ["gemini-flash-latest", "gemini-flash-lite-latest"]:
            selected_model = "gemini-flash-latest"

        n225_str = f"{current_n225:,.2f}円" if current_n225 > 0 else "現在値取得中"
        topix_str = f"{current_topix:,.2f}pt" if current_topix > 0 else "現在値取得中"

        prompt = f"""
あなたは日本の株式市場（日経平均株価およびTOPIX）のテクニカル分析およびフィボナッチリトレースメントに精通したプロのアナリストです。

直近3年間（現在時点から遡って過去3年間）における「日経平均株価 (円)」および「TOPIX (ポイント)」の正確な最高値・最安値、ならびにその発生年月を提示し、現在の市場位置を踏まえた相場見通し・節目のワンポイント解説を作成してください。

---

### 【現在値情報】
- 日経平均株価 現在値: {n225_str}
- TOPIX 現在値: {topix_str}

---

### 【要求回答フォーマット】
必ず以下の JSON 構造のみを出力してください。余計な文字列やMarkdown装飾の過剰付与は避けてください。

```json
{{
  "n225": {{
    "high_price": 最高値の数値 (float, 例: 72353.00),
    "high_date": "最高値の発生年月 (string, 例: 2026年6月)",
    "low_price": 最安値の数値 (float, 例: 30500.29),
    "low_date": "最安値の発生年月 (string, 例: 2023年10月)"
  }},
  "topix": {{
    "high_price": 最高値の数値 (float, 例: 4101.96),
    "high_date": "最高値の発生年月 (string, 例: 2026年7月)",
    "low_price": 最安値の数値 (float, 例: 2217.10),
    "low_date": "最安値の発生年月 (string, 例: 2023年10月)"
  }},
  "market_commentary": "日経平均およびTOPIXの現在のフィボナッチ戻し水準における上値抵抗線・下値サポート帯の相場見通しワンポイント解説 (2〜3文)"
}}
```
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:generateContent?key={api_key}"
        payload = {"contents": [{"parts": [{"text": prompt.strip()}]}]}

        try:
            resp = requests.post(url, json=payload, timeout=25)
            if resp.status_code != 200:
                logger.error(f"Gemini API Market Fibonacci Error ({resp.status_code}): {resp.text}")
                return {"error": True, "message": f"API Error: HTTP {resp.status_code}"}

            res_json = resp.json()
            candidates = res_json.get("candidates", [])
            if not candidates:
                return {"error": True, "message": "AIからの応答が得られませんでした"}

            raw_text = candidates[0]["content"]["parts"][0]["text"]
            cleaned = raw_text.strip()
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
            if match:
                cleaned = match.group(1).strip()

            parsed = json.loads(cleaned)

            # バリデーションチェック
            n225_h = float(parsed["n225"]["high_price"])
            n225_l = float(parsed["n225"]["low_price"])
            topix_h = float(parsed["topix"]["high_price"])
            topix_l = float(parsed["topix"]["low_price"])

            if n225_h <= n225_l or topix_h <= topix_l or n225_l <= 0 or topix_l <= 0:
                raise ValueError("Invalid High/Low relationship")

            return {
                "error": False,
                "n225": {
                    "high_price": round(n225_h, 2),
                    "high_date": str(parsed["n225"].get("high_date", "直近3年")),
                    "low_price": round(n225_l, 2),
                    "low_date": str(parsed["n225"].get("low_date", "直近3年"))
                },
                "topix": {
                    "high_price": round(topix_h, 2),
                    "high_date": str(parsed["topix"].get("high_date", "直近3年")),
                    "low_price": round(topix_l, 2),
                    "low_date": str(parsed["topix"].get("low_date", "直近3年"))
                },
                "market_commentary": str(parsed.get("market_commentary", "直近3年間の高安値を基準としたフィボナッチ水準を分析しました。"))
            }
        except Exception as e:
            logger.error(f"Failed to parse Market Fibonacci LLM response: {e}")
            return {"error": True, "message": f"AI応答の生成・パースに失敗しました: {e}"}
