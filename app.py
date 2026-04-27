from fastapi import Depends, FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
import io
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import re
import time

import scraper
import portfolio_manager
import recent_stocks_manager
import history_manager
import json
import logging

# --- ロギング設定 ---
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# --------------------

# --- クールダウン設定 ---
# 以前は過度なスクレイピングを防ぐために10分間の制限を設けていましたが、
# 現在はDBキャッシュ（スマートキャッシュ）により、必要な時のみスクレイピングを行う仕様に
# 進化したため、この制限を解除しました。
last_full_update_time: Optional[datetime] = None
UPDATE_COOLDOWN = timedelta(seconds=0) # 制限なし

async def check_update_cooldown():
    """全件更新APIのクールダウンをチェックする依存関係（現在は無効化されています）"""
    pass
# --------------------

app = FastAPI()

# --- 定数 ---
ACCOUNT_TYPES = ["特定口座", "一般口座", "新NISA", "旧NISA"]
ASSET_TYPES = ["jp_stock", "investment_trust", "us_stock"]


# --- ハイライトルールの読み込み ---
HIGHLIGHT_RULES = {}
try:
    with open("highlight_rules.json", "r", encoding="utf-8") as f:
        HIGHLIGHT_RULES = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    logger.warning(f"highlight_rules.json の読み込みに失敗しました。デフォルト値で動作します。: {e}")

def get_config(path: str, default: Any) -> Any:
    """
    ドット区切りのパスで設定を取得する。
    例: get_config("buy_signal.thresholds.rsi_oversold", 30.0)
    """
    keys = path.split(".")
    val = HIGHLIGHT_RULES
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return default
    
    # 期待される型へのキャスト
    try:
        if isinstance(default, float): return float(val)
        if isinstance(default, int): return int(val)
    except (ValueError, TypeError):
        return default
    return val

# --- 税金設定の読み込み ---
TAX_CONFIG = {}
try:
    with open("tax_config.json", "r", encoding="utf-8") as f:
        TAX_CONFIG = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    logger.warning(f"tax_config.json の読み込みに失敗しました。税金計算は行われません。: {e}")

# --- 証券会社リストの読み込み ---
SECURITY_COMPANIES = []
try:
    with open("security_companies.json", "r", encoding="utf-8") as f:
        SECURITY_COMPANIES = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    logger.warning(f"security_companies.json の読み込みに失敗しました。デフォルト値で動作します。: {e}")
    SECURITY_COMPANIES = ["その他"]

# 静的ファイルのマウント
app.mount("/static", StaticFiles(directory="static"), name="static")

# テンプレートの設定
templates = Jinja2Templates(directory="templates")

# --- Pydanticモデル ---
class Asset(BaseModel):
    code: str # asset_typeは自動判定するため不要に

class StockCodesToDelete(BaseModel):
    codes: List[str]

class HoldingData(BaseModel):
    account_type: str
    purchase_price: float
    quantity: float
    security_company: Optional[str] = None
    memo: Optional[str] = None

# --- 購入注目フラグの表示設定 ---
# --- 購入注目フラグの表示設定 ---
BUY_SIGNAL_DISPLAY = get_config("buy_signal.display", {
    "level_1": {
        "icon": "🟡",
        "icon_diamond": "💎🟡",
        "label": "注目",
        "recommended_action": "監視開始。短期的な底値圏に到達しました。",
        "current_status": "短期指標が「売られすぎ」の水準に達しており、反転の準備段階にあります。"
    },
    "level_2": {
        "icon": "🔥",
        "icon_diamond": "💎🔥",
        "label": "チャンス",
        "recommended_action": "打診買い・追撃買い。短期リバウンドの初動です。",
        "current_status": "短期的な売られすぎから、トレンドが上向き始めた兆候があります。"
    }
})

# --- 売却シグナルの表示設定 ---
SELL_SIGNAL_DISPLAY = get_config("sell_signal.display", {
    "level_1": {
        "icon": "⚠️",
        "label": "過熱気味",
        "recommended_action": "新規買い自粛・一部利確。利益確定の出口戦略を検討すべきです。",
        "current_status": "短期的な「買われすぎ」の状態です。いつ調整が入ってもおかしくない過熱感があります。"
    },
    "level_2": {
        "icon": "🚨",
        "label": "ピークアウト",
        "recommended_action": "利益確定を最優先。欲張らずに利益を確保しましょう。",
        "current_status": "上昇トレンドが折れた可能性が高いです。下落転換の初期サインと考えられます。"
    },
    "level_3": {
        "icon": "🌀",
        "label": "トレンド崩壊",
        "recommended_action": "逆張り・仕込み検討。業績が良ければ将来の仕込み場です。",
        "current_status": "75日移動平均線から大きく下方乖離しており、中長期的にトレンドが崩れた状態です。"
    }
})

def calculate_sell_signal(stock_data: dict) -> Optional[dict]:
    """
    売却シグナル（過熱・調整フラグ）を判定する。
    """
    if stock_data.get("asset_type") != "jp_stock":
        return None

    reasons = []
    is_level1 = False # 過熱気味
    is_level2 = False # ピークアウト
    is_level3 = False # 長期調整

    # --- 共通データの取得 ---
    rsi_14 = stock_data.get("rsi_14")
    rsi_14_prev = stock_data.get("rsi_14_prev")
    rci_26 = stock_data.get("rci_26")

    # 価格と移動平均
    price = 0.0
    try:
        price_val = stock_data.get("price")
        if isinstance(price_val, str): price_val = price_val.replace(',', '')
        price = float(price_val or 0)
    except (ValueError, TypeError): pass

    ma_5 = stock_data.get("moving_average_5")
    ma_25 = stock_data.get("moving_average_25")
    ma_75 = stock_data.get("moving_average_75")

    # 25日乖離率
    deviation_25 = 0.0
    if price > 0 and ma_25:
        deviation_25 = (price - ma_25) / ma_25 * 100

    # --- Level 1: 過熱気味 (買われすぎ) ---
    rsi_overbought = get_config("sell_signal.thresholds.rsi_overbought", 75.0)
    if rsi_14 is not None and rsi_14 >= rsi_overbought:
        is_level1 = True
        reasons.append(f"RSI買われすぎ({rsi_14:.1f})")

    rci_top = get_config("sell_signal.thresholds.rci_top", 85.0)
    if rci_26 is not None and rci_26 >= rci_top:
        is_level1 = True
        reasons.append(f"RCI高値圏({rci_26:.1f})")

    dev_overbought = get_config("sell_signal.thresholds.deviation_overbought", 15.0)
    if deviation_25 >= dev_overbought:
        is_level1 = True
        reasons.append(f"25日乖離過大({deviation_25:.1f}%)")

    # --- Level 2: ピークアウト (過熱からの反転) ---
    if is_level1:
        # 5日線を価格が下回る
        if price > 0 and ma_5 and price < ma_5:
            is_level2 = True
            reasons.append("5日線割れ")

        # RSIが前日比で低下
        if rsi_14 is not None and rsi_14_prev is not None and rsi_14 < rsi_14_prev:
            is_level2 = True
            reasons.append("RSIピークアウト")

    # --- Level 3: 長期調整 (トレンド崩壊) ---
    if price > 0 and ma_75 and price < ma_75:
        is_level3 = True
        reasons.append("75日線割れ(長期調整)")

    # レベルの決定 (緊急度・判断の明確さを優先)
    # 1. ピークアウト (Lv2): 反転下落の初動であり、最も売却アクションの緊急度が高い。
    # 2. 加熱気味 (Lv1): まだ上がっているが、買われすぎの状態。
    # 3. 長期調整 (Lv3): トレンドがすでに崩れている状態。
    level = 0
    if is_level2:
        level = 2
    elif is_level1:
        level = 1
    elif is_level3:
        level = 3

    if level == 0:
        return None

    config = SELL_SIGNAL_DISPLAY[f"level_{level}"]
    
    # 選択されたレベルにふさわしい理由のみをフィルタリング（混乱を防ぐため）
    # ただし、裏側の事実はすべて reasons に残す
    return {
        "level": level,
        "icon": config["icon"],
        "label": config["label"],
        "recommended_action": config.get("recommended_action", ""),
        "current_status": config.get("current_status", ""),
        "reasons": reasons
    }

def calculate_buy_signal(stock_data: dict) -> Optional[dict]:
    """
    購入シグナル（注目フラグ）を判定する。
    """
    if stock_data.get("asset_type") != "jp_stock" or "score_details" not in stock_data:
        return None

    details = stock_data["score_details"]
    is_reliable = details.get("is_reliable", True)
    missing_items = details.get("missing_items", [])

    # ファンダメンタルズスコアの合計（10点満点）
    f_score = details.get("per", 0) + details.get("pbr", 0) + details.get("roe", 0) + \
              details.get("yield", 0) + details.get("consecutive_increase", 0)

    # 閾値を設定から取得
    f_min = get_config("buy_signal.thresholds.fundamental_min", 3)
    f_diamond = get_config("buy_signal.thresholds.fundamental_diamond", 4)

    # 判定不能シグナルの早期返却 (データ欠損があり、かつスコアが低い場合)
    if not is_reliable and f_score < f_min:
        return {
            "level": 0,
            "is_diamond": False,
            "is_unreliable": True,
            "icon": "🔘",
            "label": "判定不能",
            "recommended_action": "データ不足のため判定をスキップしました。",
            "current_status": f"以下の項目が取得できなかったため、正しく評価できていない可能性があります: {', '.join(missing_items)}",
            "reasons": ["重要データ欠損"]
        }

    # 共通条件：ファンダメンタルズ最小スコア
    if f_score < f_min:
        return None

    is_diamond = f_score >= f_diamond
    reasons = []

    # --- Level 1 判定条件 (売られすぎ) ---
    is_level1 = False

    rsi_threshold = get_config("buy_signal.thresholds.rsi_oversold", 30.0)
    rsi_14 = stock_data.get("rsi_14")
    if rsi_14 is not None and rsi_14 <= rsi_threshold:
        is_level1 = True
        reasons.append(f"RSI売られすぎ({rsi_14:.1f})")

    rci_threshold = get_config("buy_signal.thresholds.rci_bottom", -80.0)
    rci_26 = stock_data.get("rci_26")
    if rci_26 is not None and rci_26 <= rci_threshold:
        is_level1 = True
        reasons.append(f"RCI底値圏({rci_26:.1f})")

    fib_min = get_config("buy_signal.thresholds.fibonacci_min", 61.8)
    fib_max = get_config("buy_signal.thresholds.fibonacci_max", 78.6)
    fib = stock_data.get("fibonacci")
    if fib and isinstance(fib, dict):
        ret = fib.get("retracement")
        if ret is not None and fib_min <= ret <= fib_max:
            is_level1 = True
            reasons.append(f"フィボナッチ押し目({ret:.1f}%)")

    if not is_level1:
        # スコアは高いがテクニカル指標が取れないためにレベル1にならない場合も「判定不能」を検討
        if not is_reliable:
            return {
                "level": 0, "is_diamond": is_diamond, "is_unreliable": True,
                "icon": "🔘", "label": "判定不能",
                "recommended_action": "テクニカル指標の一部が取得できませんでした。",
                "current_status": f"ファンダメンタルズは良好ですが、以下の指標が欠損しています: {', '.join(missing_items)}",
                "reasons": ["テクニカル欠損"]
            }
        return None

    # --- Level 2 判定条件 (反転確認) ---
    is_level2 = False
    level2_reasons = []

    # 5日線突破
    price = 0.0
    try:
        price_val = stock_data.get("price")
        if isinstance(price_val, str): price_val = price_val.replace(',', '')
        price = float(price_val or 0)
        ma_5 = stock_data.get("moving_average_5")
        if price > 0 and ma_5 and price > ma_5:
            is_level2 = True
            level2_reasons.append("5日線突破")
    except (ValueError, TypeError): pass

    # RSIのボトムアウト (当日 > 前日)
    rsi_14_prev = stock_data.get("rsi_14_prev")
    if rsi_14 is not None and rsi_14_prev is not None and rsi_14 > rsi_14_prev:
        is_level2 = True
        level2_reasons.append("RSI反転")

    level = 2 if is_level2 else 1
    config = BUY_SIGNAL_DISPLAY[f"level_{level}"]

    # ダイヤモンド判定を理由に追加
    if is_diamond:
        reasons.insert(0, f"高確信(ファンダ{f_diamond}点以上)")

    # --- 長期調整およびトレンド抑制の追加判定 ---
    label = config["label"]
    if not is_reliable:
        label += " (判定不完全)"

    recommended_action = config.get("recommended_action", "")
    current_status = config.get("current_status", "")
    if not is_reliable:
        current_status += f" 【注意】以下の項目が取得できていません: {', '.join(missing_items)}"
    
    # 200日線によるトレンド抑制判定
    is_downward_trend = False
    try:
        ma_200 = stock_data.get("ma200")
        if price > 0 and ma_200:
            deviation_200 = (price - ma_200) / ma_200 * 100
            if deviation_200 <= -5.0: # 200日線から5%以上下
                is_downward_trend = True
    except: pass

    # 長期調整判定 (75日線 または 200日線)
    is_long_adjustment = False
    max_deviation = 0.0
    try:
        ma_75 = stock_data.get("ma75") or stock_data.get("moving_average_75")
        ma_75_threshold = get_config("buy_signal.thresholds.ma_75_diff_threshold", -10.0)
        ma_200 = stock_data.get("ma200")
        
        if price > 0:
            dev_75 = (price - ma_75) / ma_75 * 100 if ma_75 else 0
            dev_200 = (price - ma_200) / ma_200 * 100 if ma_200 else 0
            
            if dev_75 <= ma_75_threshold or dev_200 <= -15.0:
                is_long_adjustment = True
                max_deviation = min(dev_75, dev_200)
    except: pass

    # ロジック統合: 下降トレンド中は慎重に、ただし優良株の長期調整はチャンス
    if is_long_adjustment:
        long_config = get_config("buy_signal.display.long_adjustment", {})
        label += long_config.get("suffix", "＋長期調整中")
        recommended_action = long_config.get("recommended_action_override", recommended_action)
        current_status += " " + long_config.get("current_status_append", "")
        reasons.append(f"長期乖離過大({max_deviation:.1f}%)")
    elif is_downward_trend and not is_diamond:
        # 優良株以外で長期下降トレンド中の場合は、シグナルを抑制（格下げ）
        label = "⚠️長期下降トレンド"
        recommended_action = "長期的な下落基調にあります。安易なリバウンド狙いは避け、底打ちを確認してください。"
        icon = "📉"

    return {
        "level": level,
        "is_diamond": is_diamond,
        "is_unreliable": not is_reliable,
        "icon": icon if 'icon' in locals() else (config["icon_diamond"] if is_diamond else config["icon"]),
        "label": label,
        "recommended_action": recommended_action,
        "current_status": current_status,
        "reasons": reasons + level2_reasons
    }

def reconcile_signals(buy_signal: Optional[dict], sell_signal: Optional[dict]) -> tuple[Optional[dict], Optional[dict]]:
    """
    購入シグナルと売却シグナルが同時に発生した場合の優先順位を調整し、
    ユーザーの混乱を避けるために適切な方を一つに絞り込む。
    """
    if not buy_signal or not sell_signal:
        return buy_signal, sell_signal

    # 1. 売却側が「ピークアウト (Lv2)」または「過熱気味 (Lv1)」の場合
    # これらはテクニカル的な買われすぎからの反転リスクを示しており、
    # たとえ押し目買いの条件（フィボナッチ等）を満たしていても、短期的には警戒が勝る。
    if sell_signal.get("level") in [1, 2]:
        # 売却側（警告）を優先し、購入側を非表示にする。
        return None, sell_signal

    # 2. 売却側が「長期調整 (Lv3: 75日線割れ)」の場合
    # 購入シグナル（注目・チャンス）が出ているなら、売却側を非表示にする。
    # ※購入シグナルのラベルに「＋長期調整」として統合されるため、情報の欠落はない。
    if sell_signal.get("level") == 3:
        return buy_signal, None

    return buy_signal, sell_signal

def _enrich_stock_data(merged_data: Dict[str, Any], scraped_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    銘柄データに分析（スコア、シグナル）を付与し、必要に応じてDBを更新する。
    """
    if "error" in merged_data:
        return merged_data

    code = merged_data.get('code')
    asset_type = merged_data.get('asset_type', 'jp_stock')

    # 1. 分析の実行 (国内株式のみ)
    if asset_type == 'jp_stock':
        merged_data["consecutive_increase_years"] = calculate_consecutive_dividend_increase(merged_data.get("dividend_history", {}))
        score, details = calculate_score(merged_data)
        merged_data["score"] = score
        merged_data["score_details"] = details

        # ダイヤモンド（優良銘柄）判定を独立して保持
        f_score = details.get("per", 0) + details.get("pbr", 0) + details.get("roe", 0) + \
                  details.get("yield", 0) + details.get("consecutive_increase", 0)
        f_diamond = get_config("buy_signal.thresholds.fundamental_diamond", 4)
        merged_data["is_diamond"] = f_score >= f_diamond

        # シグナルの判定
        merged_data["buy_signal"] = calculate_buy_signal(merged_data)
        merged_data["sell_signal"] = calculate_sell_signal(merged_data)

        # 重複・相反シグナルの抑制
        merged_data["buy_signal"], merged_data["sell_signal"] = reconcile_signals(
            merged_data.get("buy_signal"), merged_data.get("sell_signal")
        )

    # 2. スナップショットの保存 (DB更新) - 全アセットタイプ対象
    if scraped_data and "error" not in scraped_data:
        try:
            # 変更検知用のフラグ
            is_changed = False
            
            # A. 分析スナップショット (国内株のみ)
            if asset_type == 'jp_stock':
                new_analysis = {
                    "total_score": merged_data.get("score"),
                    "score_details": merged_data.get("score_details"),
                    "buy_signal": merged_data.get("buy_signal"),
                    "sell_signal": merged_data.get("sell_signal"),
                    "is_reliable": merged_data.get("score_details", {}).get("is_reliable", True)
                }
                # 既存データと比較 (なければ新規保存)
                if scraped_data.get("analysis_snapshot") != new_analysis:
                    scraped_data["analysis_snapshot"] = new_analysis
                    is_changed = True

            # B. 保有情報スナップショット (全アセット共通)
            # portfolio.json から読み込まれた保有情報のリスト（買付単価、数量、メモ等）を保存
            holdings = merged_data.get("holdings", [])
            if holdings:
                # 既存データと比較
                if scraped_data.get("holdings_snapshot") != holdings:
                    scraped_data["holdings_snapshot"] = holdings
                    is_changed = True
            
            # DB保存実行 (新規取得時、または内容に変更があった場合のみ)
            # ※新しくスクレイピングされたデータには _db_updated_at_jst がまだない
            is_newly_scraped = "_db_updated_at_jst" not in scraped_data
            
            if is_newly_scraped or is_changed:
                history_manager.save_daily_data(
                    code, 
                    asset_type, 
                    scraped_data
                )
        except Exception as e:
            logger.error(f"Failed to save snapshot for {code}: {e}")

    return merged_data

# --- 計算ヘルパー関数 ---

def calculate_consecutive_dividend_increase(dividend_history: dict) -> int:
    if not dividend_history or len(dividend_history) < 2: return 0
    sorted_years = sorted(dividend_history.keys(), reverse=True)
    consecutive_years = 0
    for i in range(len(sorted_years) - 1):
        current_year_str, previous_year_str = sorted_years[i], sorted_years[i+1]
        try:
            current_dividend = float(dividend_history[current_year_str])
            previous_dividend = float(dividend_history[previous_year_str])
        except (ValueError, TypeError): break
        if current_dividend <= previous_dividend: break
        consecutive_years += 1
    return consecutive_years

def calculate_score(stock_data: dict) -> tuple[int, dict]:
    details = {
        "per": 0, "pbr": 0, "roe": 0, "yield": 0, "consecutive_increase": 0,
        "trend_short": 0, "trend_medium": 0, "trend_long": 0, "trend_signal": 0,
        "fibonacci": 0, "rci": 0, "range_yearly": 0
    }
    missing_items = []
    is_calculable = False

    # (中略: ファンダメンタルズ評価は変更なし)
    
    # --- 既存のファンダメンタルズ評価 ---
    try:
        per_raw = stock_data.get("per", "N/A")
        if per_raw in [None, "N/A", "--", ""]:
            missing_items.append("PER")
            per = float("inf")
        else:
            per = float(str(per_raw).replace('倍', '').replace(',', ''))
            is_calculable = True
            if per <= get_config("per.undervalued", 15.0): details["per"] += 1
            if per <= 10.0: details["per"] += 1
    except (ValueError, TypeError): 
        missing_items.append("PER")

    try:
        pbr_raw = stock_data.get("pbr", "N/A")
        if pbr_raw in [None, "N/A", "--", ""]:
            missing_items.append("PBR")
            pbr = float("inf")
        else:
            pbr = float(str(pbr_raw).replace('倍', '').replace(',', ''))
            is_calculable = True
            if pbr <= get_config("pbr.undervalued", 1.0): details["pbr"] += 1
            if pbr <= 0.7: details["pbr"] += 1
    except (ValueError, TypeError):
        missing_items.append("PBR")

    try:
        roe_raw = stock_data.get("roe", "N/A")
        if roe_raw in [None, "N/A", "--", ""]:
            missing_items.append("ROE")
            roe = 0.0
        else:
            roe = float(str(roe_raw).replace('%', '').replace(',', ''))
            is_calculable = True
            if roe >= get_config("roe.undervalued", 10.0): details["roe"] += 1
            if roe >= 15.0: details["roe"] += 1
    except (ValueError, TypeError):
        missing_items.append("ROE")

    try:
        yield_raw = stock_data.get("yield", "N/A")
        if yield_raw in [None, "N/A", "--", ""]:
            missing_items.append("配当利回り")
            yield_val = 0.0
        else:
            yield_val = float(str(yield_raw).replace('%', '').replace(',', ''))
            is_calculable = True
            if yield_val >= get_config("yield.undervalued", 3.0): details["yield"] += 1
            if yield_val >= 4.0: details["yield"] += 1
    except (ValueError, TypeError):
        missing_items.append("配当利回り")

    try:
        increase_years = int(stock_data.get("consecutive_increase_years", 0))
        is_calculable = True
        if increase_years >= get_config("consecutive_increase.good", 3): details["consecutive_increase"] += 1
        if increase_years >= get_config("consecutive_increase.excellent", 7): details["consecutive_increase"] += 1
    except (ValueError, TypeError): pass

    # --- トレンド評価 ---
    if get_config("trend.enabled", False):
        try:
            price_val = stock_data.get("price")
            if isinstance(price_val, str):
                price_val = price_val.replace(',', '')
            price = float(price_val or 0)
            ma_25 = stock_data.get("ma25") or stock_data.get("moving_average_25")
            ma_75 = stock_data.get("ma75") or stock_data.get("moving_average_75")
            ma_200 = stock_data.get("ma200")

            if price > 0:
                if ma_25 and price > ma_25:
                    is_calculable = True
                    details["trend_short"] += 1
                if ma_75 and price > ma_75:
                    is_calculable = True
                    details["trend_medium"] += 1
                if ma_200 and price > ma_200:
                    is_calculable = True
                    details["trend_long"] += 1
                if ma_25 and ma_75 and ma_25 > ma_75:
                    is_calculable = True
                    details["trend_signal"] += 1

            # --- フィボナッチ判定 (全期間/52週ベース) ---
            fib = stock_data.get("range_52w") or stock_data.get("fibonacci")
            if fib and isinstance(fib, dict):
                retracement = fib.get("retracement")
                min_ret = get_config("trend.fibonacci.min_retracement", 50.0)
                max_ret = get_config("trend.fibonacci.max_retracement", 78.6)
                if retracement is not None and min_ret <= retracement <= max_ret:
                    is_calculable = True
                    details["fibonacci"] += 1

                # 年間安値圏判定 (下位25%以内)
                if retracement is not None and retracement >= 75.0:
                    is_calculable = True
                    details["range_yearly"] += 1

            elif get_config("trend.fibonacci.enabled", True):
                missing_items.append("フィボナッチ")

            # --- RCI判定 ---
            rci_val = stock_data.get("rci_26")
            if rci_val is not None:
                threshold = get_config("trend.rci.threshold", -80)
                if rci_val <= threshold:
                    is_calculable = True
                    details["rci"] += 1
            elif get_config("trend.rci.enabled", True):
                missing_items.append("RCI")

        except (ValueError, TypeError): pass

    # 重要項目 (PER, PBR, 利回り) のいずれかが欠損している場合は信頼性が低いとみなす
    important_missing = [item for item in ["PER", "PBR", "配当利回り"] if item in missing_items]
    is_reliable = len(important_missing) == 0

    total_score = sum(details.values())
    details["missing_items"] = missing_items
    details["is_reliable"] = is_reliable
    
    return total_score if is_calculable else -1, details

def get_cache_threshold_time(asset_type: str, now_jst: datetime, market_times: dict) -> datetime:
    """
    指定されたアセットタイプの、キャッシュが有効であるための「最新の基準時刻」を算出する。
    「直近の市場開始」と「直近の市場終了」の遅い方を返す。
    """
    config = market_times.get(asset_type, market_times.get("jp_stock", {}))
    
    def get_last_time(h_m_str, is_open_time=False):
        hour, minute = map(int, h_m_str.split(":"))
        t = now_jst.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now_jst < t:
            t -= timedelta(days=1)
        
        # 市場ごとの休場曜日判定
        if asset_type in ['us_stock', 'market_index']:
            if is_open_time:
                # 米国株/指標開始(JST 23:30/09:00)が発生しないのは 土(5) と 日(6)
                while t.weekday() >= 5:
                    t -= timedelta(days=1)
            else:
                # 米国株/指標終了(JST 07:00/06:00)が発生しないのは 日(6) と 月(0)
                while t.weekday() in [0, 6]:
                    t -= timedelta(days=1)
        else:
            # 日本株・投信の開始/終了が発生しないのは 土(5) と 日(6)
            while t.weekday() >= 5:
                t -= timedelta(days=1)
        return t

    last_open = get_last_time(config.get("open_time_jst", "09:00"), True)
    last_close = get_last_time(config.get("close_time_jst", "15:30"), False)

    return max(last_open, last_close)

async def _fetch_scraped_data_with_cache(code: str, asset_type: str, scraper_instance: Any, db_cache: Optional[dict] = None) -> Dict[str, Any]:
    """
    スマートキャッシュロジックを適用して単一の銘柄データを取得する。
    1. メモリキャッシュ 2. DBキャッシュ 3. スクレイピング の順で試行。
    """
    now_jst = history_manager.get_now_jst()
    market_times = get_config("system.market_times", {})

    # 1. メモリキャッシュ確認
    if scraper_instance.is_cached(code):
        return await asyncio.to_thread(scraper_instance.fetch_data, code)

    # 2. DBキャッシュ確認
    db_data = db_cache or history_manager.get_daily_data(code)
    if db_data:
        threshold_time = get_cache_threshold_time(asset_type, now_jst, market_times)
        updated_at_str = db_data.get("_db_updated_at_jst")

        is_fresh = False
        if updated_at_str:
            try:
                updated_at = datetime.fromisoformat(updated_at_str).replace(tzinfo=history_manager.JST)
                # 判定: DBの更新時刻が「最新の市場イベント」以降であれば「最新」
                # または、更新から1時間以内であれば「最新」
                if updated_at >= threshold_time or (now_jst - updated_at).total_seconds() < 3600:
                    is_fresh = True
            except ValueError: pass

        if is_fresh:
            # スクレイパーのメモリキャッシュにも同期
            scraper_instance.cache[code] = db_data
            return db_data

    # 3. スクレイピング実行
    result = await asyncio.to_thread(scraper_instance.fetch_data, code)

    # 成功データをDBに永続化
    if result and "error" not in result:
        history_manager.save_daily_data(code, asset_type, result)

    return result

async def _get_processed_asset_data() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    ポートフォリオ内の全資産のデータを並行して取得し、スコア計算などを行う。
    JST基準の市場確定時刻に基づき、DBキャッシュをインテリジェントに活用する。
    戻り値: (処理済みデータリスト, 統計メタデータ)
    """
    try:
        portfolio = portfolio_manager.load_portfolio()
    except json.JSONDecodeError as e:
        logger.error(f"portfolio.json JSON Decode Error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"portfolio.json の形式が不正です。カンマの有無や括弧の対応を確認してください。<br>エラー詳細: {str(e)}<br>ヒント: <a href='https://jsonlint.com/' target='_blank'>JSON Lint</a> などで構文チェックを行ってください。"
        )

    if not portfolio: return []

    start_time = time.perf_counter()
    now_jst = history_manager.get_now_jst()

    # 全銘柄の最新DBキャッシュを一括取得 (日付不問)
    db_cache_map = history_manager.get_latest_daily_data_all()

    # スクレイピング設定の取得
    concurrency_limit = get_config("system.scraping.concurrency_limit", 1)
    delay_min = get_config("system.scraping.delay_min", 1.5)
    delay_max = get_config("system.scraping.delay_max", 4.0)
    failure_threshold = get_config("system.scraping.failure_threshold", 3)

    # 市場時刻設定の取得
    market_times = get_config("system.market_times", {})

    # 同時実行数を制限するセマフォ
    semaphore = asyncio.Semaphore(concurrency_limit)
    import random

    # サーキットブレーカーの状態管理
    is_circuit_open = False
    consecutive_failures = 0
    lock = asyncio.Lock() # 共有変数の保護用

    async def fetch_with_smart_cache_bulk(scraper_instance, code, asset_type):
        nonlocal is_circuit_open, consecutive_failures

        # 1. データの特定 (メモリ または DB)
        cached_data = None
        is_fresh = False
        source = None

        # 1a. メモリキャッシュ確認
        if scraper_instance.is_cached(code):
            cached_data = await asyncio.to_thread(scraper_instance.fetch_data, code)
            source = "Memory"
            is_fresh = True # メモリにあるなら最新とみなす

        # 1b. DBキャッシュ確認 (メモリにない場合)
        if not cached_data:
            db_data = db_cache_map.get(code)
            if db_data:
                threshold_time = get_cache_threshold_time(asset_type, now_jst, market_times)
                updated_at_str = db_data.get("_db_updated_at_jst")
                if updated_at_str:
                    try:
                        updated_at = datetime.fromisoformat(updated_at_str).replace(tzinfo=history_manager.JST)
                        if updated_at >= threshold_time or (now_jst - updated_at).total_seconds() < 3600:
                            is_fresh = True
                            cached_data = db_data
                            source = "DB"
                    except ValueError: pass

        # 鮮度が高いキャッシュがあれば、セマフォを確保して即座に返す (待機なし)
        if is_fresh and cached_data:
            logger.info(f"Using {source} cache for {code} ({asset_type})")
            async with semaphore:
                # スクレイパーのメモリキャッシュを同期
                scraper_instance.cache[code] = cached_data
                return cached_data

        # 2. スクレイピング実行
        if is_circuit_open:
            return {"code": code, "error": "アクセス制限等により更新を中断しました", "error_details": {"status_code": 403, "type": "CircuitBreaker"}}

        async with semaphore:
            # スクレイピングが必要な場合のみ待機
            wait_time = random.uniform(delay_min, delay_max)
            await asyncio.sleep(wait_time)

            if is_circuit_open:
                return {"code": code, "error": "アクセス制限等により更新を中断しました", "error_details": {"status_code": 403, "type": "CircuitBreaker"}}

            result = await asyncio.to_thread(scraper_instance.fetch_data, code)

            async with lock:
                if not result or "error" in result:
                    consecutive_failures += 1
                    status_code = result.get("error_details", {}).get("status_code") if result else None
                    if status_code == 403:
                        is_circuit_open = True
                        logger.error(f"403エラー検知、中断: {code}")
                    if consecutive_failures >= failure_threshold:
                        is_circuit_open = True
                        logger.error(f"サーキットブレーカー発動: {code}")
                else:
                    consecutive_failures = 0
                    history_manager.save_daily_data(code, asset_type, result)

            return result

    tasks = []
    for asset_info in portfolio:
        code = asset_info['code']
        asset_type = asset_info.get('asset_type', 'jp_stock')

        try:
            scraper_instance = scraper.get_scraper(asset_type)
            tasks.append(fetch_with_smart_cache_bulk(scraper_instance, code, asset_type))
        except ValueError as e:
            logger.warning(f"銘柄 {code} のスクレイパー取得に失敗: {e}")
            async def dummy_task(c=code, at=asset_type): 
                return {"code": c, "asset_type": at, "error": "不明な資産タイプ"}
            tasks.append(dummy_task())

    scraped_results = await asyncio.gather(*tasks)
    scraped_data_map = {item['code']: item for item in scraped_results if item}

    processed_data = []
    for asset_info in portfolio:
        code = asset_info['code']
        try:
            scraped_data = scraped_data_map.get(code)
            # データが取得できていない場合でも最低限の辞書を作成
            base_scraped = scraped_data or {"error": "データ取得失敗", "code": code}
            merged_data = {**asset_info, **base_scraped}

            # 分析情報の付与とDB更新（国内株のみ）
            # ここで例外が起きやすいのでガード
            try:
                merged_data = _enrich_stock_data(merged_data, scraped_data)
            except Exception as e:
                logger.error(f"Error in _enrich_stock_data for {code}: {e}", exc_info=True)
                merged_data["error"] = f"分析計算エラー: {str(e)}"

            processed_data.append(merged_data)
        except Exception as e:
            logger.error(f"Critical error processing {code}: {e}", exc_info=True)
            # エラーが起きてもリストには追加して500エラーを回避
            processed_data.append({**asset_info, "error": f"システムエラー: {str(e)}"})

    end_time = time.perf_counter()
    duration = end_time - start_time

    total_count = len(portfolio)
    jp_count = sum(1 for a in portfolio if a.get('asset_type', 'jp_stock') == 'jp_stock')
    it_count = sum(1 for a in portfolio if a.get('asset_type') == 'investment_trust')
    us_count = sum(1 for a in portfolio if a.get('asset_type') == 'us_stock')

    # --- 市場指標の取得と過去比較の算出 ---
    market_indices_config = get_config("market_indices", [])
    market_indices_results = []
    
    if market_indices_config:
        index_tasks = []
        index_scraper = scraper.get_scraper('market_index')
        for idx_info in market_indices_config:
            code = idx_info["code"]
            index_tasks.append(fetch_with_smart_cache_bulk(index_scraper, code, 'market_index'))
        
        index_scraped_results = await asyncio.gather(*index_tasks)
        
        for i, idx_result in enumerate(index_scraped_results):
            if not idx_result or "error" in idx_result:
                market_indices_results.append({
                    "name": market_indices_config[i]["name"],
                    "code": market_indices_config[i]["code"],
                    "error": idx_result.get("error") if idx_result else "取得失敗"
                })
                continue
            
            code = idx_result["code"]
            def safe_float(val):
                if val in [None, "N/A", "--", ""]: return 0.0
                try: return float(str(val).replace(',', ''))
                except (ValueError, TypeError): return 0.0

            current_price = safe_float(idx_result.get("price"))
            
            # WoW
            date_wow = (now_jst - timedelta(days=7)).strftime("%Y-%m-%d")
            hist_wow = history_manager.get_historical_data_before(code, date_wow)
            wow_percent = "N/A"
            if hist_wow and current_price > 0:
                old_price = safe_float(hist_wow.get("price"))
                if old_price > 0:
                    wow_percent = round((current_price - old_price) / old_price * 100, 2)
                
            # MoM
            date_mom = (now_jst - timedelta(days=30)).strftime("%Y-%m-%d")
            hist_mom = history_manager.get_historical_data_before(code, date_mom)
            mom_percent = "N/A"
            if hist_mom and current_price > 0:
                old_price = safe_float(hist_mom.get("price"))
                if old_price > 0:
                    mom_percent = round((current_price - old_price) / old_price * 100, 2)

            market_indices_results.append({
                "name": idx_result.get("name", market_indices_config[i]["name"]),
                "code": code,
                "price": idx_result.get("price"),
                "change": idx_result.get("change"),
                "change_percent": idx_result.get("change_percent"),
                "wow_percent": wow_percent,
                "mom_percent": mom_percent
            })

    success_count = sum(1 for r in scraped_results if r and "error" not in r)
    fail_count = total_count - success_count

    metadata = {
        "duration": round(duration, 2),
        "total_count": total_count,
        "success_count": success_count,
        "fail_count": fail_count,
        "jp_count": jp_count,
        "it_count": it_count,
        "us_count": us_count,
        "fetched_at": history_manager.get_now_jst().isoformat(),
        "market_indices": market_indices_results # 指標データを追加
    }

    logger.info(f"[Summary] 銘柄情報の一括取得完了 | 所要時間: {duration:.2f}秒 | 対象: {total_count}件 (成功: {success_count}, 失敗: {fail_count}) | 内訳: 国内株 {jp_count}, 投信 {it_count}, 米国株 {us_count}")

    return processed_data, metadata

# --- APIエンドポイント ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/analysis", response_class=HTMLResponse)
async def read_analysis(request: Request):
    return templates.TemplateResponse("analysis.html", {"request": request})

@app.get("/api/account-types")
async def get_account_types():
    return ACCOUNT_TYPES

@app.get("/api/security-companies")
async def get_security_companies():
    return SECURITY_COMPANIES

@app.get("/api/highlight-rules")
async def get_highlight_rules():
    return HIGHLIGHT_RULES

@app.get("/api/recent-stocks")
async def get_recent_stocks():
    return recent_stocks_manager.load_recent_codes()

@app.get("/api/stocks")
async def get_stocks(cooldown_check: None = Depends(check_update_cooldown)):
    global last_full_update_time
    processed_data, metadata = await _get_processed_asset_data()
    last_full_update_time = datetime.now()
    return {"data": processed_data, "metadata": metadata}

@app.get("/api/stocks/csv")
async def download_csv(cooldown_check: None = Depends(check_update_cooldown)):
    global last_full_update_time
    data, _ = await _get_processed_asset_data()
    if not data:
        return StreamingResponse(io.StringIO(""), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=portfolio.csv"})

    csv_data = portfolio_manager.create_csv_data(data)
    filename = f"portfolio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = StreamingResponse(io.StringIO(csv_data), media_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"

    last_full_update_time = datetime.now()
    return response

def generate_error_message(scraped_data: dict) -> str:
    """スクレイピング結果のエラー情報からユーザー向けのヒント付きメッセージを生成する"""
    error_msg = scraped_data.get("error", "データ取得に失敗しました")
    details = scraped_data.get("error_details")

    if not details:
        return error_msg

    status_code = details.get("status_code")
    if status_code == 403:
        return f"{error_msg}<br><small>原因: Yahoo!ファイナンスからのアクセス制限(403)が発生しました。10分〜15分ほど時間を置いてから再度お試しください。</small>"
    elif status_code == 404:
        return f"{error_msg}<br><small>原因: 銘柄コードが正しくないか、Yahoo!ファイナンスにデータが存在しません(404)。</small>"
    elif isinstance(status_code, int) and status_code >= 500:
        return f"{error_msg}<br><small>原因: Yahoo!ファイナンス側のサーバーエラー(500系)が発生しています。しばらく待ってから再度お試しください。</small>"
    elif details.get("type") == "ParseError":
        return f"{error_msg}<br><small>原因: ページの構造が変更された可能性があります。アプリのアップデートを確認してください。</small>"

    return f"{error_msg} (Status: {status_code})"

@app.get("/api/stocks/{code}")
async def get_single_stock(code: str):
    asset_info = portfolio_manager.get_stock_info(code)
    if not asset_info:
        raise HTTPException(status_code=404, detail=f"資産コード {code} が見つかりません。")

    asset_type = asset_info.get('asset_type', 'jp_stock')

    try:
        scraper_instance = scraper.get_scraper(asset_type)
        scraped_data = await _fetch_scraped_data_with_cache(code, asset_type, scraper_instance)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not scraped_data or "error" in scraped_data:
        detail_msg = generate_error_message(scraped_data or {})
        raise HTTPException(status_code=404, detail=detail_msg)

    merged_data = {**asset_info, **scraped_data}

    # 分析情報の付与とDB更新（国内株のみ）
    merged_data = _enrich_stock_data(merged_data, scraped_data)

    return merged_data

@app.post("/api/stocks")
async def add_asset_endpoint(asset: Asset):
    code = asset.code.strip().upper()

    # 銘柄コードの形式から asset_type を自動判定
    if re.match(r'^[A-Z]{1,5}(\.[A-Z]{1,2})?$', code): # 米国株ティッカー (例: AAPL, BRK.B)
        asset_type = "us_stock"
    elif re.match(r'^\d{4}$', code): # 国内株コード
        asset_type = "jp_stock"
    elif re.match(r'^[A-Z0-9]{10}$', code): # 投資信託コード (仮)
        asset_type = "investment_trust"
    else:
        raise HTTPException(status_code=400, detail=f"無効または未対応の銘柄コード形式です: {code}")

    if asset_type not in ASSET_TYPES:
        raise HTTPException(status_code=400, detail=f"無効な資産タイプです: {asset_type}")

    is_added = portfolio_manager.add_asset(code, asset_type)
    if not is_added:
        return {"status": "exists", "message": f"資産コード {code} は既に追加されています。"}

    try:
        scraper_instance = scraper.get_scraper(asset_type)
        new_asset_data = await _fetch_scraped_data_with_cache(code, asset_type, scraper_instance)
    except ValueError as e:
        portfolio_manager.delete_stocks([code]) # 追加をロールバック
        raise HTTPException(status_code=400, detail=str(e))

    if new_asset_data and "error" not in new_asset_data:
        recent_stocks_manager.add_recent_code(code)
        
        merged_data = {**portfolio_manager.get_stock_info(code), **new_asset_data}
        # 分析情報の付与とDB更新（国内株のみ）
        merged_data = _enrich_stock_data(merged_data, new_asset_data)

        asset_name = merged_data.get("name", "")
        return {"status": "success", "message": f"資産 {code} ({asset_name}) を追加しました。", "stock": merged_data}
    else:
        portfolio_manager.delete_stocks([code]) # 追加をロールバック
        error_message = new_asset_data.get("error", "不明なエラー") if new_asset_data else "不明なエラー"
        return {"status": "error", "message": f"資産 {code} は存在しないか、データの取得に失敗しました: {error_message}", "code": code}


@app.delete("/api/stocks/bulk-delete")
async def bulk_delete_stocks(stock_codes: StockCodesToDelete):
    if not stock_codes.codes:
        raise HTTPException(status_code=400, detail="No stock codes provided for deletion.")
    portfolio_manager.delete_stocks(stock_codes.codes)
    return {"status": "success", "message": f"{len(stock_codes.codes)} stocks deleted."}

@app.post("/api/stocks/{code}/holdings", status_code=201)
async def add_holding_endpoint(code: str, holding: HoldingData):
    if holding.account_type not in ACCOUNT_TYPES:
        raise HTTPException(status_code=400, detail="無効な口座種別です。")
    if holding.purchase_price <= 0 or holding.quantity <= 0:
        raise HTTPException(status_code=400, detail="取得単価と数量は0より大きい値を指定する必要があります。")
    try:
        new_holding_id = portfolio_manager.add_holding(code, holding.dict())
        return {"status": "success", "holding_id": new_holding_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.put("/api/holdings/{holding_id}")
async def update_holding_endpoint(holding_id: str, holding: HoldingData):
    if holding.account_type not in ACCOUNT_TYPES:
        raise HTTPException(status_code=400, detail="無効な口座種別です。")
    if holding.purchase_price <= 0 or holding.quantity <= 0:
        raise HTTPException(status_code=400, detail="取得単価と数量は0より大きい値を指定する必要があります。")
    if not portfolio_manager.update_holding(holding_id, holding.dict()):
        raise HTTPException(status_code=404, detail="指定された保有情報が見つかりません。")
    return {"status": "success"}

@app.delete("/api/holdings/{holding_id}")
async def delete_holding_endpoint(holding_id: str):
    if not portfolio_manager.delete_holding(holding_id):
        raise HTTPException(status_code=404, detail="指定された保有情報が見つかりません。")
    return {"status": "success"}

@app.get("/api/portfolio/analysis")
async def get_portfolio_analysis(cooldown_check: None = Depends(check_update_cooldown)):
    """保有資産の分析データを返す"""
    global last_full_update_time
    all_assets, metadata = await _get_processed_asset_data()
    
    # 為替レートを取得
    exchange_rates = {}
    usd_jpy_rate = await asyncio.to_thread(scraper.get_exchange_rate, 'USDJPY=X')
    if usd_jpy_rate:
        exchange_rates["USD"] = usd_jpy_rate
    exchange_rates["JPY"] = 1.0 # 円は常に1.0

    holdings_list = []
    industry_breakdown = {}
    account_type_breakdown = {}
    country_breakdown = {} # 国別ポートフォリオの内訳を追加
    total_annual_dividend = 0
    total_annual_dividend_after_tax = 0

    for asset in all_assets:
        if "error" in asset or not asset.get("holdings"):
            continue

        for holding in asset["holdings"]:
            # portfolio_managerのヘルパー関数で計算
            calculated_holding_data = portfolio_manager.calculate_holding_values(
                asset, holding, exchange_rates, TAX_CONFIG
            )
            
            # 計算結果をholding_detailにマージ
            holding_detail = {**asset, **calculated_holding_data}

            # データを正規化し、フロントエンドで必要なキーを保証する
            if holding_detail.get("asset_type") == "investment_trust":
                holding_detail["industry"] = "投資信託"
            elif "industry" not in holding_detail:
                holding_detail["industry"] = "その他"

            if "market" not in holding_detail:
                holding_detail["market"] = "N/A"

            # 集計 (market_valueが計算可能な場合のみ)
            market_value_jpy = holding_detail.get("market_value")
            if market_value_jpy is not None:
                industry = holding_detail["industry"]
                industry_breakdown[industry] = industry_breakdown.get(industry, 0) + market_value_jpy
                
                account_type = holding.get("account_type", "不明")
                account_type_breakdown[account_type] = account_type_breakdown.get(account_type, 0) + market_value_jpy

                country = "日本"
                if asset.get("asset_type") == "us_stock":
                    country = "米国"
                elif asset.get("asset_type") == "investment_trust":
                    country = "投資信託"
                country_breakdown[country] = country_breakdown.get(country, 0) + market_value_jpy
            
            # 年間配当の合計を加算
            if holding_detail.get("estimated_annual_dividend") and isinstance(holding_detail.get("estimated_annual_dividend"), (int, float)):
                total_annual_dividend += holding_detail["estimated_annual_dividend"]
            if holding_detail.get("estimated_annual_dividend_after_tax") and isinstance(holding_detail.get("estimated_annual_dividend_after_tax"), (int, float)):
                total_annual_dividend_after_tax += holding_detail["estimated_annual_dividend_after_tax"]

            if "holdings" in holding_detail: del holding_detail["holdings"]
            holdings_list.append(holding_detail)

    # 配当構成比の計算
    for item in holdings_list:
        div = item.get("estimated_annual_dividend")
        if total_annual_dividend > 0 and isinstance(div, (int, float)):
            item["dividend_contribution"] = (div / total_annual_dividend) * 100
        else:
            item["dividend_contribution"] = 0

    # フロントエンド表示用に、Noneを"N/A"に変換
    # 履歴保存のために変換前のデータを保持しておく
    raw_holdings_list = [item.copy() for item in holdings_list]

    display_keys_to_convert = ["price", "market_value", "profit_loss", "profit_loss_rate", "estimated_annual_dividend", "estimated_annual_dividend_after_tax"]
    for item in holdings_list:
        for key in display_keys_to_convert:
            if item.get(key) is None:
                item[key] = "N/A"

    # --- 履歴データの保存 (半自動: 分析ページアクセス時に保存) ---
    previous_summary = None
    try:
        # 非同期で実行するのが理想だが、SQLiteへの書き込みは高速なため、
        # 簡易的に同期処理で行う（デグレリスク低減のため複雑な非同期処理は避ける）。
        # N/A変換前の生データ(raw_holdings_list)を渡す
        history_manager.save_snapshot(raw_holdings_list)
        
        # 保存後に30日前のデータを取得 (なければそれ以前の最新)
        now_jst = history_manager.get_now_jst()
        target_date = (now_jst - timedelta(days=30)).strftime("%Y-%m-%d")
        previous_summary = history_manager.get_summary_before(target_date)
    except Exception as e:
        logger.error(f"Error saving history snapshot or getting previous summary: {e}")
    # -------------------------------------------------------

    # --- ポートフォリオの統計情報(加重平均など)を計算 ---
    summary_stats = portfolio_manager.calculate_portfolio_stats(raw_holdings_list)
    # ---------------------------------------------------

    last_full_update_time = datetime.now()
    return {
        "holdings_list": holdings_list,
        "industry_breakdown": industry_breakdown,
        "account_type_breakdown": account_type_breakdown,
        "country_breakdown": country_breakdown,
        "total_annual_dividend": total_annual_dividend,
        "total_annual_dividend_after_tax": total_annual_dividend_after_tax,
        "summary_stats": summary_stats,
        "metadata": metadata,
        "previous_summary": previous_summary, # 過去サマリーを追加
    }

@app.get("/api/portfolio/analysis/csv")
async def download_analysis_csv():
    analysis_data = await get_portfolio_analysis()
    holdings_list = analysis_data.get("holdings_list", [])
    if not holdings_list:
        return StreamingResponse(io.StringIO(""), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=portfolio_analysis.csv"})
    csv_data = portfolio_manager.create_analysis_csv_data(holdings_list)
    filename = f"portfolio_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = StreamingResponse(io.StringIO(csv_data), media_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response

@app.get("/api/history/summary")
async def get_history_summary():
    """月次履歴のサマリーを取得する"""
    return history_manager.get_monthly_summary()