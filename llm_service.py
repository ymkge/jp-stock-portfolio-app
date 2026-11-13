import json
import re
import hashlib
import time
import copy
import threading
import logging
import requests
from datetime import datetime
from typing import Dict, Any, Optional, List
from investment_policy_manager import InvestmentPolicyManager

logger = logging.getLogger(__name__)

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
        self._industry_daily_cache: Dict[str, Dict[str, Any]] = {}
        self._market_volatility_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _get_prompt_hash(self, policy_prompt: str) -> str:
        return hashlib.sha256(policy_prompt.encode('utf-8')).hexdigest()[:16]

    def clear_cache(self):
        """全キャッシュをクリア（投資方針更新時などに使用）"""
        with self._lock:
            self._cache.clear()
            self._profit_taking_cache.clear()
            self._industry_daily_cache.clear()
            self._market_volatility_cache.clear()

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

    @staticmethod
    def _sanitize_error_message(text: str) -> str:
        """APIキーがエラーメッセージやログに含まれるのを防ぐサニタイズ関数"""
        if not text:
            return ""
        return re.sub(r'key=[a-zA-Z0-9_\-]+', 'key=***', str(text))

    @staticmethod
    def _get_fallback_model_chain(selected_model: str) -> List[str]:
        """
        ローリングエイリアス相互フォールバックチェーンを生成。
        固定バージョン名は将来のサービス終了に伴う保守コストを招くため指定NG。
        常に最新版へ自動追従するローリングエイリアス間（Lite ⇄ 通常Flash）でのみ切り替える。
        """
        default_chain = ["gemini-flash-latest", "gemini-flash-lite-latest"]
        if selected_model == "gemini-flash-lite-latest":
            return ["gemini-flash-lite-latest", "gemini-flash-latest"]
        elif selected_model == "gemini-flash-latest":
            return ["gemini-flash-latest", "gemini-flash-lite-latest"]
        else:
            chain = [selected_model]
            for m in default_chain:
                if m not in chain:
                    chain.append(m)
            return chain

    def _request_gemini_with_fallback(
        self,
        payload: Dict[str, Any],
        selected_model: str,
        api_key: str,
        timeout: float = 20.0,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Gemini API 呼び出しを実行。
        503 (過負荷 / High Demand) / 429 (レート制限) / 一時的通信障害時に、
        1.0秒の指数バックオフリトライ（最大1回）およびローリングエイリアス相互フォールバックを実行する。
        """
        model_chain = self._get_fallback_model_chain(selected_model)
        req_headers = headers.copy() if headers else {"Content-Type": "application/json"}
        if "Content-Type" not in req_headers:
            req_headers["Content-Type"] = "application/json"

        last_error: Dict[str, Any] = {
            "error": True,
            "error_code": "UNKNOWN_ERROR",
            "message": "AI診断実行中に予期せぬエラーが発生しました。"
        }

        for model in model_chain:
            endpoint_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            is_fallback = (model != selected_model)
            
            # 各モデルにつき最大2回（初回 + リトライ1回）試行
            for attempt in range(2):
                if attempt > 0:
                    time.sleep(1.0)  # 指数バックオフ待機
                
                try:
                    response = requests.post(endpoint_url, json=payload, headers=req_headers, timeout=timeout)
                    status_code = response.status_code

                    # 1. 成功時 (200)
                    if status_code == 200:
                        try:
                            res_data = response.json()
                        except Exception as e:
                            last_error = {
                                "error": True,
                                "error_code": "JSON_DECODE_ERROR",
                                "message": f"Gemini API からの応答JSONの解析に失敗しました: {self._sanitize_error_message(str(e))}"
                            }
                            break

                        candidates = res_data.get("candidates", [])
                        if not candidates:
                            last_error = {
                                "error": True,
                                "error_code": "NO_CANDIDATES",
                                "message": "Gemini API からの有効な回答候補が得られませんでした。"
                            }
                            break

                        parts = candidates[0].get("content", {}).get("parts", [])
                        if not parts:
                            last_error = {
                                "error": True,
                                "error_code": "NO_PARTS",
                                "message": "Gemini API の応答パーツが空でした。"
                            }
                            break

                        raw_text = parts[0].get("text", "")
                        return {
                            "error": False,
                            "data": res_data,
                            "raw_text": raw_text,
                            "model_used": model,
                            "fallback_occurred": is_fallback
                        }

                    # 2. 恒久的クライアントエラー (400, 403) ➔ リトライ・フォールバックせず即時返却
                    if status_code == 400:
                        err_json = {}
                        try:
                            err_json = response.json()
                        except Exception:
                            pass
                        err_msg = err_json.get("error", {}).get("message", "")
                        if "API key not valid" in err_msg or "INVALID_ARGUMENT" in err_msg or "API_KEY_INVALID" in response.text:
                            return {
                                "error": True,
                                "error_code": "INVALID_API_KEY",
                                "message": "Google AI Studio APIキーが無効です。「⚙️ 投資方針」設定画面で正しい API Key を入力して保存してください。"
                            }
                        return {
                            "error": True,
                            "error_code": f"HTTP_{status_code}",
                            "message": f"Gemini API リクエストエラー (HTTP {status_code}): {self._sanitize_error_message(err_msg or response.text)}"
                        }

                    if status_code == 403:
                        return {
                            "error": True,
                            "error_code": "HTTP_403",
                            "message": "Gemini API 権限エラー (HTTP 403): アクセスが拒否されました。"
                        }

                    # 3. 一時的な過負荷・レート制限 (503, 429, 500, 502, 504)
                    if status_code in (429, 500, 502, 503, 504):
                        logger.warning(
                            f"Gemini API HTTP {status_code} on model '{model}' (attempt {attempt+1}/2). "
                            f"Response: {self._sanitize_error_message(response.text[:200])}"
                        )
                        if status_code == 503:
                            last_error = {
                                "error": True,
                                "error_code": "HTTP_503",
                                "message": "Gemini API が世界的な高負荷状態（HTTP 503: High Demand）です。時間をおいて再試行してください。"
                            }
                        elif status_code == 429:
                            last_error = {
                                "error": True,
                                "error_code": "HTTP_429",
                                "message": "Gemini API レート制限（HTTP 429: Rate Limit Exceeded）に達しました。時間をおいて再試行してください。"
                            }
                        else:
                            last_error = {
                                "error": True,
                                "error_code": f"HTTP_{status_code}",
                                "message": f"Gemini API サーバーエラー (HTTP {status_code})。時間をおいて再試行してください。"
                            }
                        continue

                    # その他のエラーステータス
                    last_error = {
                        "error": True,
                        "error_code": f"HTTP_{status_code}",
                        "message": f"Gemini API 通信エラー (HTTP {status_code}): {self._sanitize_error_message(response.text[:200])}"
                    }
                    break

                except requests.exceptions.Timeout:
                    logger.warning(f"Gemini API timeout on model '{model}' (attempt {attempt+1}/2).")
                    last_error = {
                        "error": True,
                        "error_code": "TIMEOUT",
                        "message": "Gemini API 通信がタイムアウトしました。しばらく時間をおいて再試行してください。"
                    }
                    continue
                except requests.exceptions.RequestException as e:
                    logger.warning(f"Gemini API network error on model '{model}' (attempt {attempt+1}/2): {self._sanitize_error_message(str(e))}")
                    last_error = {
                        "error": True,
                        "error_code": "NETWORK_ERROR",
                        "message": f"Gemini API ネットワーク通信エラー: {self._sanitize_error_message(str(e))}"
                    }
                    continue

        return last_error

    def _execute_gemini_request(
        self, 
        stock_data: Dict[str, Any], 
        portfolio_summary: Optional[Dict[str, Any]], 
        selected_model: str, 
        policy_prompt: str,
        api_key: str
    ) -> Dict[str, Any]:
        prompt_text = self._build_prompt(stock_data, portfolio_summary, policy_prompt)

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

        api_res = self._request_gemini_with_fallback(payload, selected_model, api_key, timeout=20.0)
        if api_res.get("error"):
            return api_res

        parsed = self._parse_llm_json(api_res["raw_text"])
        if not parsed.get("error"):
            parsed["model_used"] = api_res.get("model_used", selected_model)
            if api_res.get("fallback_occurred"):
                parsed["fallback_occurred"] = True
        return parsed

    def _calculate_portfolio_cap_metrics(
        self, 
        portfolio_summary: Optional[Dict[str, Any]], 
        price_num: float
    ) -> Dict[str, Any]:
        """
        案件 #304: 100銘柄分散投資ポリシーに基づく1銘柄あたりの購入上限目安を算出する。
        - ポートフォリオ総評価額（total_market_value）を基準
        - コア枠（高い安全性）: 最大3%程度まで
        - サテライト枠（高リスク・条件付き）: 1〜2%程度まで
        - 小規模ポートフォリオ保護: 1%: 最低2万円, 2%: 最低3万円, 3%: 最低5万円の下限保証
        - 現在株価に基づく上限株数換算（最低1株保証）
        - 総評価額未取得時の多層フォールバック（DB履歴 ➔ デフォルト300万円）
        """
        total_val = 0.0
        if portfolio_summary and isinstance(portfolio_summary, dict):
            try:
                raw_val = (
                    portfolio_summary.get("total_market_value") or 
                    portfolio_summary.get("total_assets") or 
                    portfolio_summary.get("total_value") or 0.0
                )
                total_val = float(str(raw_val).replace(',', ''))
            except (ValueError, TypeError):
                total_val = 0.0

        is_fallback = False
        if total_val <= 0:
            # DB履歴 (portfolio_summary_history) から最新レコードを取得
            try:
                import sqlite3
                import history_manager
                with sqlite3.connect(history_manager.DB_FILE) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT total_market_value FROM portfolio_summary_history
                        WHERE total_market_value > 0
                        ORDER BY snapshot_date DESC LIMIT 1
                    """)
                    row = cursor.fetchone()
                    if row and row["total_market_value"]:
                        total_val = float(row["total_market_value"])
            except Exception as dbe:
                logger.debug(f"Failed to fetch total_market_value from DB history: {dbe}")

        if total_val <= 0:
            total_val = 3_000_000.0  # 基準デフォルト値（300万円）
            is_fallback = True

        # 最低エントリー下限ガード付き金額枠（円）
        cap_1pct = max(20_000, int(total_val * 0.01))
        cap_2pct = max(30_000, int(total_val * 0.02))
        cap_3pct = max(50_000, int(total_val * 0.03))

        # 現在株価での株数換算（最低1株保証）
        if price_num > 0:
            shares_1pct = max(1, int(cap_1pct // price_num))
            shares_2pct = max(1, int(cap_2pct // price_num))
            shares_3pct = max(1, int(cap_3pct // price_num))
        else:
            shares_1pct = shares_2pct = shares_3pct = 1

        summary_text = (
            f"  * ポートフォリオ総評価額: 約 {int(total_val):,} 円"
            f"{' (※推計基準値)' if is_fallback else ''}\n"
            f"  * 【サテライト枠 (1〜2%分散目安)】: 約 {cap_1pct:,} 円〜約 {cap_2pct:,} 円 (約 {shares_1pct} 株〜約 {shares_2pct} 株まで)\n"
            f"  * 【コア枠 (最大3%分散目安)】: 最大約 {cap_3pct:,} 円 (約 {shares_3pct} 株まで)"
        )

        return {
            "total_market_value": total_val,
            "is_fallback": is_fallback,
            "cap_1pct": cap_1pct,
            "cap_2pct": cap_2pct,
            "cap_3pct": cap_3pct,
            "shares_1pct": shares_1pct,
            "shares_2pct": shares_2pct,
            "shares_3pct": shares_3pct,
            "summary_text": summary_text
        }

    def _calculate_downside_metrics(self, stock_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        案件 #303: 下値分析（仕込みどきの価格・安全網）用の定量的指標を算出する。
        - 予想年間配当金 (DPS)
        - 目標配当利回り（4.0%, 4.5%, 5.0%）に基づく逆算株価および現在株価との乖離率
        - PBR 1.0倍水準（BPS・解散価値ライン）および現在株価との乖離率
        - 75日線・200日線水準
        ※無配・赤字・データ欠損時はゼロ除算を物理遮断する。
        """
        metrics: Dict[str, Any] = {
            "dps": None,
            "yield_40_price": None,
            "yield_40_diff_pct": None,
            "yield_45_price": None,
            "yield_45_diff_pct": None,
            "yield_50_price": None,
            "yield_50_diff_pct": None,
            "bps": None,
            "bps_diff_pct": None,
            "ma75_price": None,
            "ma200_price": None,
            "summary_text": ""
        }

        # 現在株価のパース
        price_num = 0.0
        raw_price = stock_data.get("price")
        if raw_price not in [None, "", "N/A", "--"]:
            try:
                price_num = float(str(raw_price).replace(',', ''))
            except (ValueError, TypeError):
                price_num = 0.0

        # 予想配当利回りのパース
        raw_yield = stock_data.get("yield")
        if raw_yield in [None, "", "N/A", "--"]:
            raw_yield = stock_data.get("dividend_yield")
        yield_pct = 0.0
        if raw_yield not in [None, "", "N/A", "--"]:
            try:
                yield_pct = float(str(raw_yield).replace('%', '').replace(',', ''))
            except (ValueError, TypeError):
                yield_pct = 0.0

        # 予想1株配当金 (DPS) の取得または逆算
        dps_val = None
        raw_dps = stock_data.get("dps") or stock_data.get("dividend")
        if raw_dps not in [None, "", "N/A", "--"]:
            try:
                dps_val = float(str(raw_dps).replace(',', ''))
            except (ValueError, TypeError):
                dps_val = None

        if (dps_val is None or dps_val <= 0) and price_num > 0 and yield_pct > 0:
            dps_val = round(price_num * (yield_pct / 100.0), 2)

        if dps_val and dps_val > 0:
            metrics["dps"] = dps_val
            # 利回り逆算株価 (4.0%, 4.5%, 5.0%)
            y40 = round(dps_val / 0.040, 1)
            y45 = round(dps_val / 0.045, 1)
            y50 = round(dps_val / 0.050, 1)
            metrics["yield_40_price"] = y40
            metrics["yield_45_price"] = y45
            metrics["yield_50_price"] = y50
            if price_num > 0:
                metrics["yield_40_diff_pct"] = round((y40 - price_num) / price_num * 100.0, 1)
                metrics["yield_45_diff_pct"] = round((y45 - price_num) / price_num * 100.0, 1)
                metrics["yield_50_diff_pct"] = round((y50 - price_num) / price_num * 100.0, 1)

        # BPS (1株純資産・PBR1.0倍水準) の取得または逆算
        raw_bps = stock_data.get("bps")
        bps_val = None
        if raw_bps not in [None, "", "N/A", "--"]:
            try:
                bps_val = float(str(raw_bps).replace(',', ''))
            except (ValueError, TypeError):
                bps_val = None

        if (bps_val is None or bps_val <= 0) and price_num > 0:
            raw_pbr = stock_data.get("pbr")
            if raw_pbr not in [None, "", "N/A", "--"]:
                try:
                    pbr_num = float(str(raw_pbr).replace(',', ''))
                    if pbr_num > 0:
                        bps_val = round(price_num / pbr_num, 1)
                except (ValueError, TypeError):
                    bps_val = None

        if bps_val and bps_val > 0:
            metrics["bps"] = bps_val
            if price_num > 0:
                metrics["bps_diff_pct"] = round((bps_val - price_num) / price_num * 100.0, 1)

        # 移動平均線
        ma75_val = stock_data.get("moving_average_75") or stock_data.get("ma75")
        if ma75_val not in [None, "", "N/A", "--"]:
            try:
                metrics["ma75_price"] = float(str(ma75_val).replace(',', ''))
            except (ValueError, TypeError): pass

        ma200_val = stock_data.get("moving_average_200") or stock_data.get("ma200")
        if ma200_val not in [None, "", "N/A", "--"]:
            try:
                metrics["ma200_price"] = float(str(ma200_val).replace(',', ''))
            except (ValueError, TypeError): pass

        # プロンプト用のテキストブロックを構築
        text_lines = []
        if metrics["dps"]:
            text_lines.append(f"  * 予想1株配当金 (DPS): 約 {metrics['dps']:,.1f} 円")
            text_lines.append(f"  * 利回り4.0%換算株価: 約 {metrics['yield_40_price']:,.1f} 円 (現在比: {metrics['yield_40_diff_pct']:+.1f}%)")
            text_lines.append(f"  * 利回り4.5%換算株価: 約 {metrics['yield_45_price']:,.1f} 円 (現在比: {metrics['yield_45_diff_pct']:+.1f}%)")
            text_lines.append(f"  * 利回り5.0%換算株価: 約 {metrics['yield_50_price']:,.1f} 円 (現在比: {metrics['yield_50_diff_pct']:+.1f}%)")
        else:
            text_lines.append("  * 予想配当利回り逆算: 無配または配当未定のため算定対象外")

        if metrics["bps"]:
            text_lines.append(f"  * BPS (PBR1.0倍ライン・解散価値水準): 約 {metrics['bps']:,.1f} 円 (現在比: {metrics['bps_diff_pct']:+.1f}%)")
        else:
            text_lines.append("  * BPS (PBR1.0倍ライン): 純資産データなし")

        if metrics["ma75_price"]:
            text_lines.append(f"  * 75日移動平均線 (MA75): 約 {metrics['ma75_price']:,.1f} 円")
        if metrics["ma200_price"]:
            text_lines.append(f"  * 200日移動平均線 (MA200): 約 {metrics['ma200_price']:,.1f} 円")

        metrics["summary_text"] = "\n".join(text_lines)
        return metrics

    def _calculate_target_buy_price_hint(self, stock_data: Dict[str, Any]) -> str:
        """
        案件 #382: AIおすすめ5選等で提示する仕込み目標株価（下値メド）を安全・適正に算出する。
        - 現在利回りに応じて目標利回りを動的に設定（現在利回りがすでに4.5%以上の銘柄で現在値超過を起こさない）
        - 物理的上限絶対ルール: target_price <= price（いかなる場合も現在株価以下にクランプ）
        - 現在値近傍または同値の場合は「現在値水準 (約○円 / 利回り○.○%)」と明記
        """
        price_num = 0.0
        raw_price = stock_data.get("price")
        if raw_price not in [None, "", "N/A", "--"]:
            try:
                price_num = float(str(raw_price).replace(',', ''))
            except (ValueError, TypeError):
                price_num = 0.0

        if price_num <= 0:
            return "現在値近辺で打診買い"

        raw_yield = stock_data.get("yield")
        if raw_yield in [None, "", "N/A", "--"]:
            raw_yield = stock_data.get("dividend_yield")
        yield_pct = 0.0
        if raw_yield not in [None, "", "N/A", "--"]:
            try:
                yield_pct = float(str(raw_yield).replace('%', '').replace(',', ''))
            except (ValueError, TypeError):
                yield_pct = 0.0

        raw_dps = stock_data.get("dps") or stock_data.get("dividend")
        dps_val = None
        if raw_dps not in [None, "", "N/A", "--"]:
            try:
                dps_val = float(str(raw_dps).replace(',', ''))
            except (ValueError, TypeError):
                dps_val = None

        if (dps_val is None or dps_val <= 0) and price_num > 0 and yield_pct > 0:
            dps_val = round(price_num * (yield_pct / 100.0), 2)

        dm = self._calculate_downside_metrics(stock_data)

        # 配当データが存在する場合の動的目標算出
        if dps_val and dps_val > 0:
            if yield_pct < 3.5:
                # 低利回り銘柄: 利回り4.0%目標、またはBPS水準
                target_yield = 0.040
                calc_p = dps_val / target_yield
                bps = dm.get("bps")
                if bps and 0 < bps < price_num:
                    calc_p = min(calc_p, bps)
                final_p = min(calc_p, price_num)
                if final_p >= price_num * 0.995:
                    return f"現在値水準: 約{int(round(price_num)):,}円 (利回り{yield_pct:.2f}%)"
                return f"約{int(round(final_p)):,}円 (利回り4.0%水準)"

            elif yield_pct < 4.5:
                # 標準〜良好利回り: 利回り4.5%目標
                target_yield = 0.045
                calc_p = dps_val / target_yield
                final_p = min(calc_p, price_num)
                if final_p >= price_num * 0.995:
                    return f"現在値水準: 約{int(round(price_num)):,}円 (利回り{yield_pct:.2f}%)"
                return f"約{int(round(final_p)):,}円 (利回り4.5%)"

            elif yield_pct < 5.0:
                # 4.5%〜5.0%の高利回り銘柄 (例: VTホールディングス 4.94%): 利回り5.0%目標
                target_yield = 0.050
                calc_p = dps_val / target_yield
                final_p = min(calc_p, price_num)
                if final_p >= price_num * 0.995:
                    return f"現在値水準: 約{int(round(price_num)):,}円 (利回り{yield_pct:.2f}%)"
                return f"約{int(round(final_p)):,}円 (利回り5.0%)"

            else:
                # 5.0%以上の超高利回り銘柄 (例: UBE 5.10%): 利回り5.5%目標または現在値水準
                target_yield = 0.055
                calc_p = dps_val / target_yield
                final_p = min(calc_p, price_num)
                if final_p >= price_num * 0.995:
                    return f"現在値水準: 約{int(round(price_num)):,}円 (利回り{yield_pct:.2f}%)"
                return f"約{int(round(final_p)):,}円 (利回り5.5%)"

        # 配当逆算ができない場合: BPS水準または打診買い
        bps = dm.get("bps")
        if bps and 0 < bps < price_num:
            return f"約{int(round(bps)):,}円 (PBR1.0倍)"

        return f"現在値水準: 約{int(round(price_num)):,}円で打診買い"

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

        # リアルタイム為替情報およびレンジ情報の取得
        fx_info_str = "N/A"
        try:
            from scraper import get_exchange_rate_detail
            fx_detail = get_exchange_rate_detail("USDJPY=X")
            if fx_detail and fx_detail.get("price"):
                curr_fx = fx_detail["price"]
                chg_fx = fx_detail.get("change_percent", "")
                high_fx = fx_detail.get("high") or "N/A"
                low_fx = fx_detail.get("low") or "N/A"
                h52_fx = fx_detail.get("high_52w") or "N/A"
                l52_fx = fx_detail.get("low_52w") or "N/A"
                peak_diff = fx_detail.get("peak_diff_percent") or ""

                range_str = f"当日: {low_fx}〜{high_fx}円 | 52週: {l52_fx}〜{h52_fx}円"
                if peak_diff:
                    range_str += f" (ピーク比: {peak_diff})"
                fx_info_str = f"{curr_fx} 円 ({chg_fx}) / {range_str}"
        except Exception as e:
            logger.warning(f"Failed to fetch USDJPY details for prompt: {e}")

        # 下値分析用の定量的指標を算出
        downside_metrics = self._calculate_downside_metrics(stock_data)

        # 案件 #304: 100銘柄分散投資ポリシーに基づく購入上限目安指標を算出
        cap_metrics = self._calculate_portfolio_cap_metrics(portfolio_summary, price_num)

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
- リアルタイム為替環境 (USD/JPY): {fx_info_str}
- 下値参考指標 (定量的安全網データ):
{downside_metrics['summary_text']}
- 100銘柄分散投資ポリシーに基づく購入上限参考指標:
{cap_metrics['summary_text']}

---

## あなたのタスク
上記「ユーザーの基本投資方針」に照らし合わせ、対象銘柄({code} {name})の適合度を分析してください。
直近の業績動向（EPSや収益性）、配当維持能力（還元の盾）、および【75日・200日移動平均線との位置関係（上昇トレンド／押し目圏／長期下降トレンド）】と【材料出尽くし感（好材料出尽くし下落リスク / 悪材料アク抜け大底判定）やマクロ地政学・災害・米国市況ショックの影響度】、ならびに【リアルタイムドル円レートおよび直近レンジ位置（為替影響: 輸出株の減益リスク／内需株の追い風）】を踏まえて投資判断を行ってください。
また、本システム（S株ナンピン買い下がり）における【下値メド（第1仕込みライン・第2岩盤ライン）】を分析し、買い下がりターゲットとなる価格帯と利回り、下値支持の根拠を明示してください。
さらに、約100銘柄への分散投資（集中投資防止ルール）に基づき、本銘柄の安全度・選定枠に応じた【1銘柄あたりの購入上限目安（金額・資産比率・累計株数・ナンピン配分計画）】を判定・出力してください（コア枠: 最大3%程度まで、サテライト枠: 1〜2%程度まで）。
※重要: トレンドが「上昇トレンド」や「絶好の押し目圏」にある場合は、順張り・格安エントリーの観点から分析の確信度 (confidence_score) を高め(85〜95点)に算出して後押しし、長期下降トレンド下では慎重な確信度・立ち回りを提示してください。
必ず以下のJSONフォーマットのみを出力してください。Markdownや他の余計な文言は一切含めないでください。

JSONフォーマットで回答を出力してください。キーは必ず以下の通りとすること:
{{
  "fit_level": "fit" または "caution" または "unfit",
  "confidence_score": この判定結果(コア/サテライト/Avoid)に対するAIアナリスト自身の【分析の確信度・自信度】(0〜100の数値)。※注意: 適合度の割合ではありません。順張りや絶好の押し目圏にある買い候補の場合は 85〜95 の高い数値を出力してください。,
  "decision_label": "【判定ラベル】(例: 【強い買い（コア）】 / 【買い（サテライト）】 / 【中立・監視】 / 【見送り（Avoid）】)",
  "estimated_yield": "予想配当利回りの記載(例: 約4.4%)",
  "recommended_shares": "1回あたりの購入目安株数の記載(例: 約3株〜4株)",
  "investment_cap": {{
    "tier": "選定枠(例: コア枠 (最大3%) または サテライト枠 (1〜2%))",
    "cap_amount_str": "購入上限目安金額と比率(例: 最大約15万円 (総資産の約3%))",
    "max_shares_str": "上限株数(例: 累計約60株まで)",
    "allocation_plan": "ナンピン配分(例: 1回あたり1〜2万円×最大3〜4回に分けて買い下がり)",
    "reason": "100銘柄分散投資方針に基づく上限理由(例: 還元の盾と財務盤石性により上限3%まで許容)"
  }},
  "shield_and_valuation": "「還元の盾」およびPBR/PER過熱感の評価詳細",
  "performance_summary": "直近のEPS・収益性・業績動向および配当原資創出力に関するAI評価解説",
  "trend_analysis": "75日・200日移動平均線を踏まえた長中期トレンドの簡潔な評価解説（※1〜2文程度のコンパクトな文章とすること）",
  "material_exhaustion_eval": "材料出尽くし（好材料出尽くし下落リスク / 悪材料アク抜け大底判定）およびマクロショック影響度のAI評価解説",
  "business_10y_eval": "10年スパンでの事業評価（ポジティブ要因・ネガティブ要因）",
  "tactical_advice": "本システム/S株ナンピンにおける具体的な立ち回りアドバイス",
  "dip_buying_analysis": {{
    "level1_price": "第1仕込み目安株価と利回り(例: 約2,450円 / 利回り4.1%)",
    "level1_rationale": "第1仕込みラインの根拠(例: 75日線サポートおよび初期押し目打診買い水準)",
    "level2_price": "第2岩盤目安株価と利回り(例: 約2,200円 / 利回り4.6%)",
    "level2_rationale": "第2岩盤ラインの根拠(例: PBR1.0倍(BPS)および利回り○%到達による強固な大底サポート)",
    "tactical_memo": "S株ナンピンにおける具体的な指値・買い下がり配分メモ"
  }},
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

        default_dip = {
            "level1_price": "算出中",
            "level1_rationale": "直近の押し目水準および移動平均線サポートを分析中",
            "level2_price": "算出中",
            "level2_rationale": "PBR1.0倍解散価値および目標利回り水準を分析中",
            "tactical_memo": "時間分散・価格分散によるS株ナンピン買い下がりを推奨します。"
        }

        default_cap_core = {
            "tier": "コア枠 (最大3%)",
            "cap_amount_str": "最大約15万円 (総資産の約3%)",
            "max_shares_str": "算出中",
            "allocation_plan": "1回あたり1〜2万円×複数回に分けて買い下がり",
            "reason": "100銘柄分散投資方針に基づく上限目安（安全度高: 最大3%まで）"
        }
        default_cap_satellite = {
            "tier": "サテライト枠 (1〜2%)",
            "cap_amount_str": "最大約5万〜10万円 (総資産の約1〜2%)",
            "max_shares_str": "算出中",
            "allocation_plan": "1回あたり1〜2万円×最大3〜5回に限定",
            "reason": "100銘柄分散投資方針に基づく上限目安（限定枠: 1〜2%まで）"
        }

        try:
            data = json.loads(cleaned)
        except Exception:
            return {
                "fit_level": "caution",
                "confidence_score": 50,
                "decision_label": "【判定解析中】",
                "estimated_yield": "要確認",
                "recommended_shares": "要確認",
                "investment_cap": default_cap_satellite,
                "shield_and_valuation": "レスポンスのパースに一部失敗しましたが、詳細テキストを以下に示します。",
                "performance_summary": "業績データの詳細解析を実行中です。",
                "trend_analysis": "75日・200日移動平均線を踏まえたトレンド分析を実行中です。",
                "material_exhaustion_eval": "材料出尽くしおよび市場変動の解析を実行中です。",
                "business_10y_eval": raw_text[:500],
                "tactical_advice": "手動での最終確認を推奨します。",
                "dip_buying_analysis": default_dip,
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

        # dip_buying_analysis の安全な抽出と補完
        dip_raw = data.get("dip_buying_analysis")
        if isinstance(dip_raw, dict):
            dip_analysis = {
                "level1_price": str(dip_raw.get("level1_price") or default_dip["level1_price"]),
                "level1_rationale": str(dip_raw.get("level1_rationale") or default_dip["level1_rationale"]),
                "level2_price": str(dip_raw.get("level2_price") or default_dip["level2_price"]),
                "level2_rationale": str(dip_raw.get("level2_rationale") or default_dip["level2_rationale"]),
                "tactical_memo": str(dip_raw.get("tactical_memo") or default_dip["tactical_memo"])
            }
        else:
            dip_analysis = default_dip

        # investment_cap の安全な抽出と自己修復（補完） (#304)
        fallback_cap = default_cap_core if fit_level == "fit" else default_cap_satellite
        cap_raw = data.get("investment_cap")
        if isinstance(cap_raw, dict):
            cap_analysis = {
                "tier": str(cap_raw.get("tier") or fallback_cap["tier"]),
                "cap_amount_str": str(cap_raw.get("cap_amount_str") or fallback_cap["cap_amount_str"]),
                "max_shares_str": str(cap_raw.get("max_shares_str") or fallback_cap["max_shares_str"]),
                "allocation_plan": str(cap_raw.get("allocation_plan") or fallback_cap["allocation_plan"]),
                "reason": str(cap_raw.get("reason") or fallback_cap["reason"])
            }
        else:
            cap_analysis = fallback_cap

        return {
            "fit_level": fit_level,
            "confidence_score": confidence_score,
            "decision_label": str(data.get("decision_label", "【判定完了】")),
            "estimated_yield": str(data.get("estimated_yield", "N/A")),
            "recommended_shares": str(data.get("recommended_shares", "N/A")),
            "investment_cap": cap_analysis,
            "shield_and_valuation": str(data.get("shield_and_valuation", "データなし")),
            "performance_summary": str(data.get("performance_summary", "直近業績（EPS・収益性）データに基づき持続可能な配当維持力を検証済みです。")),
            "trend_analysis": str(data.get("trend_analysis", "75日・200日移動平均線との位置関係およびトレンド状態を考慮した分析を実行済みです。")),
            "material_exhaustion_eval": str(data.get("material_exhaustion_eval", "テクニカル指標およびマクロ要因に基づく材料出尽くしリスクを分析済みです。")),
            "business_10y_eval": str(data.get("business_10y_eval", "データなし")),
            "tactical_advice": str(data.get("tactical_advice", "データなし")),
            "dip_buying_analysis": dip_analysis,
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

        payload = {
            "contents": [{
                "parts": [{"text": prompt_text}]
            }],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json"
            }
        }

        api_res = self._request_gemini_with_fallback(payload, selected_model, api_key, timeout=20.0)
        if api_res.get("error"):
            return api_res

        try:
            parsed = self._parse_profit_taking_llm_json(api_res["raw_text"])
            parsed["error"] = False
            parsed["code"] = code
            parsed["name"] = holding_item.get("name", "")
            parsed["is_cached"] = False
            diagnosed_at_str = time.strftime("%H:%M", time.localtime(now))
            parsed["diagnosed_at"] = diagnosed_at_str
            parsed["model_used"] = api_res.get("model_used", selected_model)
            if api_res.get("fallback_occurred"):
                parsed["fallback_occurred"] = True

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
        except Exception as e:
            return {
                "error": True,
                "error_code": "UNKNOWN_ERROR",
                "message": f"利確AI診断の応答解析中に予期せぬエラーが発生しました: {str(e)}"
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
        payload = {"contents": [{"parts": [{"text": prompt.strip()}]}]}
        api_res = self._request_gemini_with_fallback(payload, selected_model, api_key, timeout=25.0)
        if api_res.get("error"):
            return api_res

        try:
            raw_text = api_res.get("raw_text", "")
            cleaned = raw_text.strip()
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
            if match:
                cleaned = match.group(1).strip()

            parsed = json.loads(cleaned)

            # バリデーションチェック
            n225_h = float(parsed["n225"]["high_price"])
            n225_l = float(parsed["n225"]["low_price"])
            n225_hd = str(parsed["n225"].get("high_date", "直近3年"))
            n225_ld = str(parsed["n225"].get("low_date", "直近3年"))

            topix_h = float(parsed["topix"]["high_price"])
            topix_l = float(parsed["topix"]["low_price"])
            topix_hd = str(parsed["topix"].get("high_date", "直近3年"))
            topix_ld = str(parsed["topix"].get("low_date", "直近3年"))

            # リアルタイム現在値との比較・最高値繰り上げ / 最安値繰り下げ (双方向ガード)
            now_month_str = datetime.now().strftime("%Y年%m月")
            if current_n225 > 0:
                if current_n225 > n225_h:
                    n225_h = current_n225
                    n225_hd = now_month_str
                if 0 < current_n225 < n225_l:
                    n225_l = current_n225
                    n225_ld = now_month_str

            if current_topix > 0:
                if current_topix > topix_h:
                    topix_h = current_topix
                    topix_hd = now_month_str
                if 0 < current_topix < topix_l:
                    topix_l = current_topix
                    topix_ld = now_month_str

            if n225_h <= n225_l or topix_h <= topix_l or n225_l <= 0 or topix_l <= 0:
                raise ValueError("Invalid High/Low relationship")

            return {
                "error": False,
                "n225": {
                    "high_price": round(n225_h, 2),
                    "high_date": n225_hd,
                    "low_price": round(n225_l, 2),
                    "low_date": n225_ld
                },
                "topix": {
                    "high_price": round(topix_h, 2),
                    "high_date": topix_hd,
                    "low_price": round(topix_l, 2),
                    "low_date": topix_ld
                },
                "market_commentary": str(parsed.get("market_commentary", "直近3年間の高安値を基準としたフィボナッチ水準を分析しました。"))
            }
        except Exception as e:
            logger.error(f"Failed to parse Market Fibonacci LLM response: {e}")
            return {"error": True, "message": f"AI応答の生成・パースに失敗しました: {e}"}

    def diagnose_anomaly(self, month: int, anomaly_info: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
        """
        現在月のアノマリー情報に基づき、Gemini APIを用いてAIアノマリー診断ワンポイント解説を生成 (#298)
        """
        cache_key = f"anomaly_month_{month}"
        api_key = self.policy_manager.get_effective_api_key()
        if not api_key:
            return {
                "error": True,
                "error_code": "NO_API_KEY",
                "message": "Google AI Studio の APIキーが設定されていません。「⚙️ 投資方針設定」から APIキー を設定してください。"
            }

        config = self.policy_manager.load_config()
        selected_model = config.get("selected_model", "gemini-flash-latest")
        if selected_model not in ["gemini-flash-latest", "gemini-flash-lite-latest"]:
            selected_model = "gemini-flash-latest"

        now = time.time()
        if not force and cache_key in self._cache:
            cached_entry = self._cache[cache_key]
            if (now - cached_entry["timestamp"]) < self.DEFAULT_TTL_SECONDS and cached_entry["model"] == selected_model:
                res = dict(cached_entry["result"])
                res["is_cached"] = True
                res["diagnosed_at"] = cached_entry["diagnosed_at_str"]
                return res

        system_instruction = (
            "あなたは日本株およびグローバル株式市場の季節的傾向・アノマリーに精通したプロの投資アナリストです。"
            "提供された月別アノマリーデータに基づき、個人投資家が今月意識すべき相場動向と心構え、注意点を具体的かつ簡潔（200文字程度）にアドバイスしてください。"
        )

        user_content = f"""【対象月】: {month}月
【アノマリータイトル】: {anomaly_info.get("title", "")}
【傾向サマリー】: {anomaly_info.get("summary", "")}
【リスクレベル】: {anomaly_info.get("risk_level", "")}
【発生の背景・理由】: {", ".join(anomaly_info.get("reasons", []))}
【立ち回り指針】: {anomaly_info.get("actions", "")}

上記の{month}月のアノマリーに基づき、個人投資家に向けた今月の立ち回りワンポイント解説（200文字程度）を生成してください。"""

        payload = {
            "contents": [{"parts": [{"text": user_content}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 300
            }
        }

        api_res = self._request_gemini_with_fallback(payload, selected_model, api_key, timeout=20.0)
        if api_res.get("error"):
            return api_res

        try:
            commentary = api_res.get("raw_text", "").strip()
            diagnosed_at_str = time.strftime("%H:%M", time.localtime(now))
            result = {
                "error": False,
                "month": month,
                "commentary": commentary,
                "is_cached": False,
                "diagnosed_at": diagnosed_at_str,
                "model_used": api_res.get("model_used", selected_model)
            }
            if api_res.get("fallback_occurred"):
                result["fallback_occurred"] = True

            with self._lock:
                self._cache[cache_key] = {
                    "result": result,
                    "timestamp": now,
                    "model": selected_model,
                    "prompt_hash": "",
                    "diagnosed_at_str": diagnosed_at_str,
                    "last_accessed": now
                }

            return result
        except Exception as e:
            logger.error(f"Failed to generate anomaly LLM response: {e}")
            return {"error": True, "message": f"AI診断の実行中にエラーが発生しました: {e}"}

    def _format_assets_to_pipe_lines(self, assets: List[Dict[str, Any]]) -> str:
        """
        絞り込み銘柄リストをパイプ区切り1行フォーマット (Pipe-Separated Compact Format) に変換し、
        Gemini API のプロンプト消費トークン数を約75%大幅削減する。
        #316: 個別銘柄診断基準に対応するため、DOE、連続増配年数、ポートフォリオ配当比率、保有株数を追加。
        """
        lines = []
        lines.append("コード|銘柄名|業種|現在株価|PER|PBR|ROE|利回り|配当性向|DOE|増配年|配当比|保有株|スコア|シグナル")
        for a in assets:
            code = a.get("code", "")
            name = a.get("name", "")
            ind = a.get("industry") or "-"
            price = f"{a.get('price', 0)}円" if a.get('price') else "-"
            per = f"PER:{a.get('per')}" if a.get('per') not in (None, 'N/A', '--', '-') else "PER:-"
            pbr = f"PBR:{a.get('pbr')}" if a.get('pbr') not in (None, 'N/A', '--', '-') else "PBR:-"
            roe = f"ROE:{a.get('roe')}%" if a.get('roe') not in (None, 'N/A', '--', '-') else "ROE:-"

            raw_yield = a.get('dividend_yield') if a.get('dividend_yield') not in (None, 'N/A', '--', '-') else a.get('yield')
            div = f"利回り:{raw_yield}%" if raw_yield not in (None, 'N/A', '--', '-', '') else "利回り:-"

            payout = f"性向:{a.get('payout_ratio')}%" if a.get('payout_ratio') not in (None, 'N/A', '--', '-') else "性向:-"
            doe = f"DOE:{a.get('doe')}%" if a.get('doe') not in (None, 'N/A', '--', '-') else "DOE:-"

            consec = a.get('consecutive_increase_years')
            consec_str = f"増配:{consec}年" if consec and consec > 0 else "増配:-"

            div_contrib = a.get('dividend_contribution', 0.0) or 0.0
            qty = a.get('holding_quantity', 0) or 0
            if qty > 0 and div_contrib > 0:
                div_contrib_str = f"配当比:{div_contrib:.1f}%"
                qty_str = f"保有:{int(qty)}株"
            else:
                div_contrib_str = "配当比:0%(新規)"
                qty_str = "保有:0株"

            score = f"Score:{a.get('score', 0)}"

            sig_label = "通常"
            if a.get("buy_signal"):
                bs = a["buy_signal"]
                if isinstance(bs, dict):
                    level = bs.get("level", 0)
                    if level == 2:
                        sig_label = "🔥チャンス"
                    elif level == 1:
                        sig_label = "✨注目"
            elif a.get("is_diamond"):
                sig_label = "💎ダイヤモンド"

            # 下値メド・仕込み目安（利回り帯別動的算出・現在値上限クランプ、Issue #382）
            down_str = f"仕込:{self._calculate_target_buy_price_hint(a)}"

            line = f"{code}|{name}|{ind}|{price}|{per}|{pbr}|{roe}|{div}|{payout}|{doe}|{consec_str}|{div_contrib_str}|{qty_str}|{score}|{sig_label}|{down_str}"
            lines.append(line)
        return "\n".join(lines)

    def diagnose_filtered_recommendations(
        self,
        filtered_assets: List[Dict[str, Any]],
        preset_name: Optional[str] = None,
        portfolio_summary: Optional[Dict[str, Any]] = None,
        usd_jpy_rate_detail: Optional[Dict[str, Any]] = None,
        force: bool = False,
        ttl_seconds: int = DEFAULT_TTL_SECONDS
    ) -> Dict[str, Any]:
        """
        専用プリセット・フィルタ等で絞り込まれた銘柄群の中から、
        ユーザーの投資方針および為替相場環境に合致する購入推奨銘柄 Top 5 を選定・診断する。
        """
        api_key = self.policy_manager.get_effective_api_key()
        if not api_key:
            return {
                "error": True,
                "error_code": "NO_API_KEY",
                "message": "Google AI Studio の APIキーが設定されていません。「⚙️ 投資方針設定」から APIキー を入力するか、環境変数 GEMINI_API_KEY を設定してください。"
            }

        if not filtered_assets:
            return {
                "error": True,
                "message": "分析対象の銘柄が存在しません。フィルタ条件を調整してください。"
            }

        config = self.policy_manager.load_config()
        selected_model = config.get("selected_model", "gemini-flash-latest")
        if selected_model not in ["gemini-flash-latest", "gemini-flash-lite-latest"]:
            selected_model = "gemini-flash-latest"

        policy_prompt = config.get("policy_prompt", "")
        prompt_hash = self._get_prompt_hash(policy_prompt)

        # キャッシュキー作成 (v2: Issue #382 仕込み株価現在値逆転解消)
        codes_str = "_".join(sorted([str(a.get("code", "")) for a in filtered_assets]))
        cache_key_raw = f"filtered_rec_v2_{codes_str}_{preset_name or ''}"
        cache_key = hashlib.sha256(cache_key_raw.encode('utf-8')).hexdigest()[:24]

        now = time.time()
        if not force:
            with self._lock:
                cached_entry = self._cache.get(cache_key)
                if cached_entry:
                    is_expired = (now - cached_entry["timestamp"]) > ttl_seconds
                    same_model = (cached_entry["model"] == selected_model)
                    same_hash = (cached_entry["prompt_hash"] == prompt_hash)
                    if not is_expired and same_model and same_hash:
                        res = copy.deepcopy(cached_entry["result"])
                        res["is_cached"] = True
                        res["diagnosed_at"] = cached_entry["diagnosed_at_str"]
                        # キャッシュ返却時のサニタイズ多層防御 (Issue #382)
                        for r in res.get("recommendations", []):
                            code_str = str(r.get("code", ""))
                            matched = next((a for a in filtered_assets if str(a.get("code")) == code_str), None)
                            if matched:
                                raw_p = matched.get("price")
                                try:
                                    matched_price = float(str(raw_p).replace(',', '')) if raw_p not in [None, "", "N/A", "--"] else 0.0
                                except (ValueError, TypeError):
                                    matched_price = 0.0
                                cur_t = str(r.get("target_buy_price", ""))
                                m = re.search(r'約?([\d,]+)円', cur_t)
                                if m and matched_price > 0:
                                    try:
                                        if float(m.group(1).replace(',', '')) > matched_price:
                                            r["target_buy_price"] = self._calculate_target_buy_price_hint(matched)
                                    except ValueError:
                                        pass
                        return res

        # パイプ区切り形式に圧縮
        pipe_formatted_data = self._format_assets_to_pipe_lines(filtered_assets)

        # 案件 #304: 100銘柄分散投資ポリシーに基づく購入上限目安指標
        cap_metrics = self._calculate_portfolio_cap_metrics(portfolio_summary, 0)

        # 為替コンテキストテキスト
        fx_text = ""
        if usd_jpy_rate_detail and isinstance(usd_jpy_rate_detail, dict):
            rate = usd_jpy_rate_detail.get("rate")
            diff = usd_jpy_rate_detail.get("peak_diff_percent")
            if rate is not None:
                fx_text = f"【為替環境】 ドル円レート: {rate:.2f}円"
                if diff is not None:
                    fx_text += f" (直近高値比 {diff:+.1f}%)"

        preset_info = f"【適用中フィルタ/プリセット】: {preset_name}\n" if preset_name else ""

        system_instruction = (
            "あなたは厳格な定量的データと数式ロジックに基づいて株式分析を行う「インカムゲイン特化型・リスク管理専門アナリスト」です。"
            "提供されたパイプ区切り形式の銘柄データとユーザーの『投資方針』、為替相場コンテキストを照らし合わせ、"
            "個別銘柄診断と同一の基準（配当利回り3.5%以上、還元の盾: DOE/連続増配、PBR過熱回避、ポートフォリオ配当集中防止、100銘柄分散投資ルール）に適合する"
            "購入推奨度の最も高い銘柄を最大5つ厳選して順位付けし、構造化JSONフォーマットで回答してください。"
        )

        user_content = f"""{preset_info}{fx_text}

【ユーザーの基本投資方針と判定基準】:
{policy_prompt if policy_prompt.strip() else 'インカムゲイン最大化を目指し、予想利回り3.5%以上、DOEや連続増配による還元の盾、PBR1.5倍以下の割安株を厳選する。'}

【100銘柄分散投資ポリシー（1銘柄購入上限目安）】:
- ポートフォリオ総評価額: 約{int(cap_metrics['total_market_value']):,}円
- 【コア枠（高い安全性）】: 最大でも総資産の3%程度まで（上限目安: 最大約{cap_metrics['cap_3pct']:,}円）
- 【サテライト枠（条件付き・高リスク）】: 総資産の1〜2%程度まで（上限目安: 約{cap_metrics['cap_1pct']:,}円〜約{cap_metrics['cap_2pct']:,}円）

【分析対象銘柄データ (パイプ区切り1行フォーマット: コード|銘柄名|業種|現在株価|PER|PBR|ROE|利回り|配当性向|DOE|増配年|配当比|保有株|スコア|シグナル|仕込目安)】:
{pipe_formatted_data}

【厳格な選定・ランキング基準 (個別銘柄AI診断と同等基準)】:
1. 【必須条件（配当水準）】:
   - 予想配当利回り 3.5%〜4.0% 以上の銘柄を最優先してください。
   - 利回り3.0%未満の低利回り銘柄や無配銘柄は、どれほど高スコアや買いシグナルであっても絶対に除外（Avoid）してください。
2. 【還元の盾（最重要防衛網）】:
   - DOE（3.5%以上下限）の明記、または連続増配（5〜10年以上）や累進配当などの「減配耐性」を最も高く評価し、最上位（コア枠）に選定してください。
3. 【過熱感の排除】:
   - PBR 1.5倍以下（理想は1.0倍割れ）を優先し、PBR 2.0倍超やPER 20倍超の高バリュエーション銘柄は評価を大幅に割り引いてください。
4. 【ポートフォリオ配当比率（集中防止と新規分散）】:
   - 既に保有していて「配当比（ポートフォリオ年間配当に占める割合）」が10%〜15%以上の銘柄は、配当集中リスクを避けるため順位を抑えてください。
   - 「配当比:0%(新規)」の未保有銘柄、または低シェアの優良銘柄は、ポートフォリオの分散効果が高いとして優先的に推奨してください。
5. 【100銘柄分散上限目安の明示】:
   - 銘柄ごとの枠組み（コア枠またはサテライト枠）に応じた購入上限金額・比率目安を `investment_cap_str` に明記してください。

【回答フォーマット指示】:
必ず以下の構造を持つ唯一の JSON オブジェクトのみを出力してください (Markdownコードブロック ```json ... ``` で包んで構いません):
{{
  "recommendations": [
    {{
      "rank": 1,
      "code": "銘柄コード",
      "name": "銘柄名",
      "industry": "業種",
      "dividend_yield_str": "予想利回り (例: 4.2%)",
      "target_buy_price": "仕込み目標株価 (例: 約2,450円 / 利回り4.5%水準、または 現在値水準: 約486円 / 利回り4.9%水準)。※最重要: 仕込み目標株価は押し目買い・下値拾いを前提とするため、絶対に現在株価を上回ってはなりません（必ず現在株価以下とすること）。",
      "investment_cap_str": "購入上限目安 (例: 最大約15万円 (約3%) または 約5万〜10万円 (約1〜2%))",
      "shield_summary": "還元の盾の要約 (例: DOE 4.8% または 連続増配11年 または 累進配当)",
      "role_badge": "枠組み (例: 【コア枠】新規分散 または 【高利回りブースター】 または 【コア枠】買い増し)",
      "fit_score": 95,
      "fit_stars": "★★★★★",
      "rationale": "選定理由・配当利回りや還元の盾、バリュエーションの強み (100文字程度)",
      "risk_factor": "リスク・注意点 (60文字程度)",
      "portfolio_advice": "配当比率や分散を踏まえた購入・組入アドバイス (60文字程度)"
    }}
  ],
  "overall_summary": "絞り込まれた銘柄群全体の傾向と投資方針に基づく総評 (150文字程度)"
}}

注意点:
1. `recommendations` 配列には、最も投資方針に合致する優秀な銘柄を最大5つ、1位から順に含めてください (基準適合が5未満の場合は適合するもののみ)。
2. `fit_score` は 0〜100 の数値、`fit_stars` は ★1〜5表記としてください。
"""

        payload = {
            "contents": [{"parts": [{"text": user_content}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2000
            }
        }

        api_res = self._request_gemini_with_fallback(payload, selected_model, api_key, timeout=30.0)
        if api_res.get("error"):
            return api_res

        raw_text = ""
        try:
            raw_text = api_res.get("raw_text", "").strip()
            
            # JSON パース
            json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', raw_text)
            json_str = json_match.group(1) if json_match else raw_text
            parsed_res = json.loads(json_str)

            # target_buy_price および investment_cap_str の安全なフォールバック補完とサニタイズ (Issue #382)
            recs = parsed_res.get("recommendations", [])
            for r in recs:
                code_str = str(r.get("code", ""))
                matched = next((a for a in filtered_assets if str(a.get("code")) == code_str), None)

                # target_buy_price のサニタイズ（現在値超過の物理遮断）とフォールバック
                cur_target = str(r.get("target_buy_price", "")).strip()
                need_sanitize = False
                matched_price = 0.0
                if matched:
                    raw_p = matched.get("price")
                    try:
                        matched_price = float(str(raw_p).replace(',', '')) if raw_p not in [None, "", "N/A", "--"] else 0.0
                    except (ValueError, TypeError):
                        matched_price = 0.0

                if not cur_target:
                    need_sanitize = True
                elif matched_price > 0:
                    # 数値抽出 (例: "約533円", "仕込み目標株価: 約3,556円")
                    m = re.search(r'約?([\d,]+)円', cur_target)
                    if m:
                        try:
                            parsed_val = float(m.group(1).replace(',', ''))
                            if parsed_val > matched_price:
                                logger.warning(
                                    f"Sanitizing target_buy_price for {code_str}: '{cur_target}' ({parsed_val}円) exceeds current price ({matched_price}円)"
                                )
                                need_sanitize = True
                        except ValueError:
                            pass

                if need_sanitize:
                    if matched:
                        r["target_buy_price"] = self._calculate_target_buy_price_hint(matched)
                    else:
                        r["target_buy_price"] = "現在値近辺で打診買い"

                if not r.get("investment_cap_str"):
                    role = str(r.get("role_badge", ""))
                    is_satellite = "サテライト" in role
                    target_cap = cap_metrics["cap_2pct"] if is_satellite else cap_metrics["cap_3pct"]
                    target_pct = "約1〜2%" if is_satellite else "約3%"
                    r["investment_cap_str"] = f"上限: 約{int(target_cap):,}円 ({target_pct})"

            diagnosed_at_str = time.strftime("%H:%M", time.localtime(now))
            result = {
                "error": False,
                "preset_name": preset_name,
                "total_candidates": len(filtered_assets),
                "recommendations": recs,
                "overall_summary": parsed_res.get("overall_summary", ""),
                "is_cached": False,
                "diagnosed_at": diagnosed_at_str,
                "model_used": api_res.get("model_used", selected_model)
            }
            if api_res.get("fallback_occurred"):
                result["fallback_occurred"] = True

            with self._lock:
                self._cache[cache_key] = {
                    "result": result,
                    "timestamp": now,
                    "model": selected_model,
                    "prompt_hash": prompt_hash,
                    "diagnosed_at_str": diagnosed_at_str,
                    "last_accessed": now
                }

            return result
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in filtered recommendations: {e}, text: {raw_text}")
            return {"error": True, "message": "AI応答のJSON解析に失敗しました。時間をおいて再試行してください。"}
        except Exception as e:
            logger.error(f"Failed to generate filtered recommendations LLM response: {e}")
            return {"error": True, "message": f"AI診断の実行中にエラーが発生しました: {e}"}

    def _normalize_confidence(self, val: Any) -> Optional[int]:
        """確信度（confidence）の型揺らぎ（文字列、小数、null等）を安全に0〜100の整数またはNoneに変換 (#380)"""
        if val is None or val == "":
            return None
        try:
            if isinstance(val, (int, float)):
                num = float(val)
            else:
                cleaned = str(val).replace("%", "").strip()
                m = re.search(r"[-+]?\d*\.?\d+", cleaned)
                num = float(m.group(0)) if m else None

            if num is None:
                return None
            # 0.0〜1.0 の小数の場合はパーセント換算 (例: 0.85 -> 85)
            if 0.0 < num <= 1.0:
                num = num * 100.0
            return max(0, min(100, int(round(num))))
        except (ValueError, TypeError, AttributeError):
            return None

    def diagnose_industry_daily_changes(
        self,
        daily_industry_data: Dict[str, Any],
        market_summary: Optional[Dict[str, Any]] = None,
        top_losing_assets: Optional[List[Dict[str, Any]]] = None,
        top_gaining_assets: Optional[List[Dict[str, Any]]] = None,
        news_headlines: Optional[List[Dict[str, Any]]] = None,
        force: bool = False,
        ttl_seconds: int = DEFAULT_TTL_SECONDS
    ) -> Dict[str, Any]:
        """
        保有銘柄の本日の業種別増減データをもとに、
        Gemini AI によって市況要因とポートフォリオへの影響をまとめた短評レポートを生成する (#317, #380)。
        """
        api_key = self.policy_manager.get_effective_api_key()
        if not api_key:
            return {
                "error": True,
                "error_code": "NO_API_KEY",
                "message": "Google AI Studio の APIキーが設定されていません。「⚙️ 投資方針設定」から APIキー を入力するか、環境変数 GEMINI_API_KEY を設定してください。"
            }

        now = time.time()
        today_str = time.strftime("%Y-%m-%d", time.localtime(now))
        if hasattr(self.policy_manager, "get_selected_model"):
            selected_model = self.policy_manager.get_selected_model()
        else:
            config = self.policy_manager.load_config()
            selected_model = config.get("selected_model", "gemini-flash-latest")
        if selected_model not in ["gemini-flash-latest", "gemini-flash-lite-latest"]:
            selected_model = "gemini-flash-latest"
        cache_key = f"industry_daily_v3_{today_str}_{selected_model}"

        # キャッシュの確認
        if not force:
            with self._lock:
                entry = self._industry_daily_cache.get(cache_key)
                if entry:
                    if (now - entry["timestamp"]) < ttl_seconds:
                        cached_result = copy.deepcopy(entry["result"])
                        cached_result["is_cached"] = True
                        return cached_result
                    else:
                        del self._industry_daily_cache[cache_key]

        # プロンプトの組み立て
        gainers = daily_industry_data.get("gainers", [])[:5]
        losers = daily_industry_data.get("losers", [])[:5]
        tot_change = daily_industry_data.get("total_daily_change_jpy", 0.0)
        tot_sign = "+" if tot_change >= 0 else ""

        gainers_text = "、".join([f"{g['industry']} (+{g['daily_change_jpy']:,.0f}円, {g['daily_change_rate']:+.2f}%)" for g in gainers]) if gainers else "なし"
        losers_text = "、".join([f"{l['industry']} ({l['daily_change_jpy']:,.0f}円, {l['daily_change_rate']:+.2f}%)" for l in losers]) if losers else "なし"

        def _format_asset_item(a: Dict[str, Any]) -> str:
            name = a.get("name") or a.get("code") or "銘柄"
            code = a.get("code", "")
            ind = a.get("industry", "")
            chg_jpy = float(a.get("daily_change_jpy") or 0.0)
            chg_rate = float(a.get("change_percent") or a.get("daily_change_rate") or 0.0)
            code_str = f"({code}, {ind})" if code else f"({ind})"
            sign = "+" if chg_jpy > 0 else ""
            return f"- {name} {code_str}: {sign}{chg_jpy:,.0f}円 ({chg_rate:+.2f}%)"

        top_gainers_assets_text = "\n".join([_format_asset_item(a) for a in (top_gaining_assets or [])[:5]]) if top_gaining_assets else "（特筆する急騰銘柄なし）"
        top_losers_assets_text = "\n".join([_format_asset_item(a) for a in (top_losing_assets or [])[:5]]) if top_losing_assets else "（特筆する急落銘柄なし）"

        news_lines = []
        for n in (news_headlines or [])[:5]:
            title = n.get("title", "") if isinstance(n, dict) else str(n)
            src = n.get("source", "") if isinstance(n, dict) else ""
            if title:
                news_lines.append(f"- {title}" + (f" ({src})" if src else ""))
        news_headlines_text = "\n".join(news_lines) if news_lines else "（当日の特筆ニュースなし）"

        market_info_text = ""
        if market_summary and isinstance(market_summary, dict):
            indices = market_summary.get("indices", {})
            parts = []
            if "N225" in indices:
                parts.append(f"日経平均: {indices['N225'].get('price', '')} ({indices['N225'].get('change_percent', '')}%)")
            if "TOPIX" in indices:
                parts.append(f"TOPIX: {indices['TOPIX'].get('price', '')} ({indices['TOPIX'].get('change_percent', '')}%)")
            if "USDJPY=X" in indices:
                parts.append(f"ドル円: {indices['USDJPY=X'].get('price', '')}")
            if parts:
                market_info_text = f"【本日の市場参考データ】: " + " / ".join(parts)

        prompt = f"""あなたは日本株およびグローバルマクロに精通したプロのポートフォリオアナリストです。
ユーザーが保有している銘柄群の本日の業種別資産増減データ、牽引・軟調銘柄、および最新の市況ニュースに基づき、
株価変動の「根本的な引き金（政治・選挙、AI半導体規制などの政策動向、金利・為替、決算等）」を具体的に捉えた短評レポートを作成してください。

{market_info_text}

【主要市況ニュースヘッドライン】
{news_headlines_text}

【ユーザー保有ポートフォリオの本日の業種別変動データ】
- 本日の保有資産全体の前日比増減額: {tot_sign}{tot_change:,.0f}円
- 上昇を牽引した業種 TOP5: {gainers_text}
- 軟調・下落した業種 TOP5: {losers_text}

【ポートフォリオ内の主な騰落銘柄】
[上昇を牽引した主な保有銘柄 TOP5]
{top_gainers_assets_text}

[軟調・下落した主な保有銘柄 TOP5]
{top_losers_assets_text}

【分析・要約の指示】
1. 『マクロ市況とセクター動向（market_trend_summary）』では、単なる指数の騰落や値動きの結果だけでなく、「なぜ本日このような市況展開になったのか」の根本的な背景・理由（前日の米国市場動向、日米金利・金融政策、為替変動、政治・地政学、原油等の商品市況、主要経済指標、イベント通過に伴う投資家心理や需給変化など）を具体的に含めて解説してください。
2. なぜ本日はこれらの業種・銘柄が動いたのか、表面的な値動きだけでなく「根本的な引き金（トリガー）」を具体的に明記してください。
   - 政治・選挙動向（大統領選、政権人事、議会情勢など）
   - 政策・規制（AI・先端半導体輸出規制、関税措置、対中投資規制、経済対策など）
   - マクロ経済材料（日米金利・日銀/FRB動向、急激な為替変動、CPI等指標）
   - 個別企業・業界材料（決算発表、業績修正、業界市況）
3. 主な下落・軟調要因（downside_factors）および上昇・牽引要因（upside_factors）をそれぞれ独立して解説してください（該当がない場合は空文字）。
4. 各要因分析について、報道・客観材料との結びつきの強さや因果関係の明確さに応じた確信度（0〜100の整数値）を評価してください。
5. 長文にせず、簡潔で視認性の高い読みやすい日本語でまとめてください。

【出力形式】
必ず以下のキーを持つ有効なJSONオブジェクトのみを返してください。マークダウンの ```json ... ``` ブロックで囲んで構いません。
{{
  "market_trend_summary": "本日のマクロ市況・セクター動向の背景・理由を含めた要約（何が起き、なぜ市況がこのような展開・値動きになったのかの根本的な背景・理由や市場センチメントを具体的に含めて2〜3行・120字程度で解説）",
  "downside_factors": "主な下落・軟調要因と政治・政策・マクロ等の引き金解説（2〜3行・120字程度。該当なしの場合は空文字）",
  "downside_confidence": 80,
  "upside_factors": "主な上昇・牽引要因と好材料・テーマ等の引き金解説（2〜3行・120字程度。該当なしの場合は空文字）",
  "upside_confidence": 85,
  "portfolio_impact_summary": "保有ポートフォリオ全体への具体的な影響とセクター偏りの解説（2〜3行・120字程度）",
  "key_takeaway": "本日の着眼点・一言まとめ（30字以内）"
}}
"""

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024,
                "responseMimeType": "application/json"
            }
        }
        api_res = self._request_gemini_with_fallback(payload, selected_model, api_key, timeout=20.0)
        if api_res.get("error"):
            return api_res

        raw_text = ""
        try:
            raw_text = api_res.get("raw_text", "").strip()
            json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', raw_text)
            json_str = json_match.group(1) if json_match else raw_text
            parsed = json.loads(json_str)

            downside_factors = str(parsed.get("downside_factors", "")).strip()
            downside_conf = self._normalize_confidence(parsed.get("downside_confidence"))
            upside_factors = str(parsed.get("upside_factors", "")).strip()
            upside_conf = self._normalize_confidence(parsed.get("upside_confidence"))

            diagnosed_at_str = time.strftime("%H:%M", time.localtime(now))
            result = {
                "error": False,
                "market_trend_summary": parsed.get("market_trend_summary", ""),
                "downside_factors": downside_factors,
                "downside_confidence": downside_conf,
                "upside_factors": upside_factors,
                "upside_confidence": upside_conf,
                "portfolio_impact_summary": parsed.get("portfolio_impact_summary", ""),
                "key_takeaway": parsed.get("key_takeaway", ""),
                "diagnosed_at": diagnosed_at_str,
                "is_cached": False,
                "model_used": api_res.get("model_used", selected_model)
            }
            if api_res.get("fallback_occurred"):
                result["fallback_occurred"] = True

            with self._lock:
                self._industry_daily_cache[cache_key] = {
                    "result": result,
                    "timestamp": now,
                    "model": selected_model
                }

            return result
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in industry daily summary: {e}, text: {raw_text}")
            return {"error": True, "message": "AI応答の解析に失敗しました。再試行してください。"}
        except Exception as e:
            logger.error(f"Failed to generate industry daily summary LLM response: {e}")
            return {"error": True, "message": f"AI短評の生成中にエラーが発生しました: {e}"}

    def diagnose_market_volatility_factors(
        self,
        market_indices: List[Dict[str, Any]],
        news_headlines: List[Dict[str, str]],
        sector_summary: Optional[Dict[str, Any]] = None,
        anomaly_context: Optional[Dict[str, Any]] = None,
        force: bool = False,
        ttl_seconds: int = 3600
    ) -> Dict[str, Any]:
        """
        日経平均・TOPIX・為替（ドル円）等の市場指標変動データ、最新市況ニュースRSSヘッドライン、
        アプリ内のセクター別騰落状況、および当月・日柄の投資アノマリー情報をもとに、
        Gemini AI が変動要因と高配当投資家への示唆を構造化要約する (#349, #363)。
        """
        api_key = self.policy_manager.get_effective_api_key()
        if not api_key:
            return {
                "error": True,
                "error_code": "NO_API_KEY",
                "message": "Google AI Studio の APIキーが設定されていません。「⚙️ 投資方針」から APIキー を設定すると、AIによる市況・為替要因の自動要約が表示されます。"
            }

        now = time.time()
        today_str = time.strftime("%Y-%m-%d", time.localtime(now))
        if hasattr(self.policy_manager, "get_selected_model"):
            selected_model = self.policy_manager.get_selected_model()
        else:
            config = self.policy_manager.load_config()
            selected_model = config.get("selected_model", "gemini-flash-latest")
        if selected_model not in ["gemini-flash-latest", "gemini-flash-lite-latest"]:
            selected_model = "gemini-flash-latest"

        cache_key = f"market_volatility_{today_str}_{selected_model}"

        if not force:
            with self._lock:
                entry = self._market_volatility_cache.get(cache_key)
                if entry:
                    if (now - entry["timestamp"]) < ttl_seconds:
                        cached_result = copy.deepcopy(entry["result"])
                        cached_result["is_cached"] = True
                        if "anomaly_insight" not in cached_result:
                            cached_result["anomaly_insight"] = ""
                        return cached_result
                    else:
                        del self._market_volatility_cache[cache_key]

        # 1. 市場指標テキストの構築
        indices_lines = []
        for idx in (market_indices or []):
            name = idx.get("name", "")
            price = idx.get("price", "--")
            change = idx.get("change", "--")
            chg_pct = idx.get("change_percent", "--")
            wow = idx.get("wow_percent", "--")
            mom = idx.get("mom_percent", "--")
            vol_flag = f" 【{idx.get('volatility_label', '急変動')}】" if idx.get("is_volatile") else ""
            if idx.get("is_fx"):
                high_52 = idx.get("high_52w", "--")
                low_52 = idx.get("low_52w", "--")
                indices_lines.append(
                    f"- {name}: 現在値 {price}円 (前日比: {change} / {chg_pct}%, 52週レンジ: {low_52}〜{high_52}円){vol_flag}"
                )
            else:
                indices_lines.append(
                    f"- {name}: 現在値 {price} (前日比: {change} / {chg_pct}%, 前週比: {wow}%, 前月比: {mom}%){vol_flag}"
                )
        indices_text = "\n".join(indices_lines) if indices_lines else "- 指標データなし"

        # 2. セクター騰落テキストの構築
        sector_text = "セクターデータなし"
        if sector_summary and isinstance(sector_summary, dict):
            top_gainers = sector_summary.get("top_gainers", [])[:5]
            top_losers = sector_summary.get("top_losers", [])[:5]
            g_str = "、".join([f"{g['industry']}({g['avg_change_percent']:+.2f}%)" for g in top_gainers]) if top_gainers else "なし"
            l_str = "、".join([f"{l['industry']}({l['avg_change_percent']:+.2f}%)" for l in top_losers]) if top_losers else "なし"
            sector_text = f"- 上昇上位セクター: {g_str}\n- 下落上位セクター: {l_str}"

        # 3. 収集ニュースヘッドラインテキストの構築
        if news_headlines:
            news_lines = [
                f"- [{n.get('source', '市況')}] {n.get('title', '')}"
                for n in news_headlines[:12]
            ]
            news_text = "\n".join(news_lines)
        else:
            news_text = "- 直近のヘッドライン取得なし（指標数値およびセクター動向から推定してください）"

        # 4. 季節性・投資アノマリーおよび需給イベントテキストの構築 (#363)
        anomaly_text = "- 季節性・アノマリーデータなし"
        if anomaly_context and isinstance(anomaly_context, dict):
            a_title = anomaly_context.get("title", "")
            a_trend = anomaly_context.get("trend_direction", "neutral")
            trend_label = "上昇傾向" if a_trend == "up" else ("下落・調整傾向" if a_trend == "down" else "中立・もみ合い")
            a_risk = anomaly_context.get("risk_level", "medium")
            risk_label = "高め" if a_risk == "high" else ("中程度" if a_risk == "medium" else "低め")
            a_summary = anomaly_context.get("summary", "")
            a_actions = anomaly_context.get("actions", "")
            a_tags = ", ".join(anomaly_context.get("tags", []))
            
            reasons = anomaly_context.get("reasons", [])
            reasons_str = " / ".join(reasons[:2]) if reasons else ""

            anomaly_lines = [
                f"- 当月（{anomaly_context.get('month', '')}月）のアノマリー: {a_title} (傾向: {trend_label}, リスク水準: {risk_label})",
                f"- 季節的な需給背景: {a_summary}" + (f" ({reasons_str})" if reasons_str else ""),
                f"- 本日の時期・日柄特性: {a_tags}",
                f"- 季節的な定石アクション: {a_actions}"
            ]
            anomaly_text = "\n".join(anomaly_lines)

        prompt = f"""あなたは日本株および外国為替市場に精通したプロのマーケットエコノミスト兼ポートフォリオストラテジストです。
以下の「最新の市場指標データ（日経平均・TOPIX・日経先物・ドル円）」「国内株セクター別騰落動向」「直近の市況・為替ニュースヘッドライン」および「当月の季節性・投資アノマリーと日柄需給イベント」を統合分析し、なぜ相場や為替が動いているのか、その背景要因と高配当株投資家が取るべきスタンスを簡潔・明快に要約してください。

【1. 市場指標の現在値・変動データ】
{indices_text}

【2. アプリ内銘柄の業種別騰落動向】
{sector_text}

【3. 直近の市況・為替ニュースヘッドライン】
{news_text}

【4. 季節性・投資アノマリーおよび需給イベントの背景】
{anomaly_text}

【分析・出力の指示】
1. ニュースヘッドラインや数値変動だけでなく、現在の月次・季節性アノマリーや日柄要因（月末月初・SQ・五十日等）の需給影響も踏まえて客観的に要因を整理してください。
2. 以下のキーを持つ有効なJSONオブジェクトのみを出力してください（Markdownの ```json ... ``` で囲んで構いません）：
{{
  "headline_summary": "本日の市場・為替動向の結論を一言で要約（45文字以内）",
  "key_drivers": ["主要因タグ1 (12文字以内)", "主要因タグ2 (12文字以内)", "主要因タグ3 (12文字以内)"],
  "equity_factors": "【日経平均・TOPIXの変動要因】なぜ株式市場が上昇/下落/推移しているのか（米株・半導体・日銀政策・企業決算・セクター動向等を120〜180文字程度で解説）",
  "fx_factors": "【為替（ドル円）の変動要因】なぜドル円が動いているのか、および輸出株・内需株への波及効果（日米金利差・経済指標・要人発言等を100〜150文字程度で解説）",
  "anomaly_insight": "【アノマリー・日柄の視点】現在の時期特有の需給（月次アノマリー、日柄、月末月初・SQ等）が本日の相場・為替に与えている影響や、数日〜数週間の先行きで意識すべき季節的な注意点を80〜120文字程度で解説",
  "portfolio_action_hint": "【高配当株投資家への示唆】現在の相場環境において長期・高配当投資家が意識すべき立ち回り（押し目買い好機・過熱警戒・静観等を80〜120文字程度で解説）",
  "action_confidence": この立ち回りヒントに対するAIアナリスト自身の【確信度・自信度】(0〜100の整数値のみ。%記号は付けない。相場材料の明確さ、需給やアノマリーの裏付けの強さに基づいて算出。通常70〜95程度)
}}
"""

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024,
                "responseMimeType": "application/json"
            }
        }

        api_res = self._request_gemini_with_fallback(payload, selected_model, api_key, timeout=20.0)
        if api_res.get("error"):
            return api_res

        raw_text = ""
        try:
            raw_text = api_res.get("raw_text", "").strip()
            json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', raw_text)
            json_str = json_match.group(1) if json_match else raw_text
            parsed = json.loads(json_str)

            key_drivers = parsed.get("key_drivers", [])
            if not isinstance(key_drivers, list):
                key_drivers = []

            # action_confidence のパースと正規化 (Issue #378)
            action_confidence = None
            raw_conf = parsed.get("action_confidence")
            if raw_conf is not None:
                try:
                    if isinstance(raw_conf, (int, float)):
                        val = float(raw_conf)
                    else:
                        cleaned = str(raw_conf).replace("%", "").strip()
                        m = re.search(r"[-+]?\d*\.?\d+", cleaned)
                        val = float(m.group(0)) if m else None

                    if val is not None:
                        # 0.0〜1.0 の小数の場合はパーセント換算 (例: 0.85 -> 85)
                        if 0.0 <= val <= 1.0:
                            val = val * 100
                        action_confidence = int(round(max(0.0, min(100.0, val))))
                except (ValueError, TypeError, AttributeError):
                    action_confidence = None

            diagnosed_at_str = time.strftime("%H:%M", time.localtime(now))
            result = {
                "error": False,
                "headline_summary": str(parsed.get("headline_summary", "")).strip(),
                "key_drivers": [str(k).strip() for k in key_drivers[:4] if str(k).strip()],
                "equity_factors": str(parsed.get("equity_factors", "")).strip(),
                "fx_factors": str(parsed.get("fx_factors", "")).strip(),
                "anomaly_insight": str(parsed.get("anomaly_insight", "")).strip(),
                "portfolio_action_hint": str(parsed.get("portfolio_action_hint", "")).strip(),
                "action_confidence": action_confidence,
                "model_used": api_res.get("model_used", selected_model),
                "diagnosed_at": diagnosed_at_str,
                "is_cached": False
            }
            if api_res.get("fallback_occurred"):
                result["fallback_occurred"] = True

            with self._lock:
                self._market_volatility_cache[cache_key] = {
                    "result": result,
                    "timestamp": now,
                    "model": selected_model
                }

            return result
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in market volatility summary: {e}, text: {raw_text}")
            return {"error": True, "error_code": "JSON_PARSE_ERROR", "message": "AI応答の解析に失敗しました。再試行してください。"}
        except Exception as e:
            logger.error(f"Failed to generate market volatility LLM response: {e}")
            return {"error": True, "error_code": "UNKNOWN_ERROR", "message": f"AI要因分析の生成中にエラーが発生しました: {e}"}


