from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
import io
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import asyncio
from datetime import datetime
from typing import List, Dict

import scraper
import portfolio_manager
import recent_stocks_manager # 追加
import json
import logging

# --- ロギング設定 ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# --------------------

app = FastAPI()

# --- ハイライトルールの読み込み ---
HIGHLIGHT_RULES = {}
try:
    with open("highlight_rules.json", "r", encoding="utf-8") as f:
        HIGHLIGHT_RULES = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    logger.warning(f"highlight_rules.json の読み込みに失敗しました。デフォルト値で動作します。: {e}")
# --------------------------------

# 静的ファイルのマウント
app.mount("/static", StaticFiles(directory="static"), name="static")

# テンプレートの設定
templates = Jinja2Templates(directory="templates")

class StockCode(BaseModel):
    code: str

class StockCodesToDelete(BaseModel): # 追加
    codes: List[str] # 追加

def calculate_consecutive_dividend_increase(dividend_history: dict) -> int:
    """
    配当履歴から連続増配（配当維持を含む）年数を計算する。
    """
    if not dividend_history or len(dividend_history) < 2:
        return 0

    # 履歴を年で降順にソート
    sorted_years = sorted(dividend_history.keys(), reverse=True)
    
    consecutive_years = 0
    for i in range(len(sorted_years) - 1):
        current_year_str = sorted_years[i]
        previous_year_str = sorted_years[i+1]
        
        if current_year_str not in dividend_history or previous_year_str not in dividend_history:
            break

        try:
            current_dividend = float(dividend_history[current_year_str])
            previous_dividend = float(dividend_history[previous_year_str])
        except (ValueError, TypeError):
            break

        if current_dividend < previous_dividend:
            break
        
        consecutive_years += 1
        
    return consecutive_years

def calculate_score(stock_data: dict) -> tuple[int, dict]:
    """
    銘柄データに基づいて割安度スコアと詳細を計算する (最大10点)
    スコアが計算不能な場合は-1を返す
    """
    details = {"per": 0, "pbr": 0, "roe": 0, "yield": 0, "consecutive_increase": 0}
    is_calculable = False
    rules = HIGHLIGHT_RULES

    try:
        per = float(str(stock_data.get("per", "inf")).replace('倍', ''))
        is_calculable = True
        if per <= rules.get("per", {}).get("undervalued", 15.0): details["per"] += 1
        if per <= 10.0: details["per"] += 1
    except (ValueError, TypeError): pass

    try:
        pbr = float(str(stock_data.get("pbr", "inf")).replace('倍', ''))
        is_calculable = True
        if pbr <= rules.get("pbr", {}).get("undervalued", 1.0): details["pbr"] += 1
        if pbr <= 0.7: details["pbr"] += 1
    except (ValueError, TypeError): pass

    try:
        roe = float(str(stock_data.get("roe", "0")).replace('%', ''))
        is_calculable = True
        if roe >= rules.get("roe", {}).get("undervalued", 10.0): details["roe"] += 1
        if roe >= 15.0: details["roe"] += 1
    except (ValueError, TypeError): pass

    try:
        yield_val = float(str(stock_data.get("yield", "0")).replace('%', ''))
        is_calculable = True
        if yield_val >= rules.get("yield", {}).get("undervalued", 3.0): details["yield"] += 1
        if yield_val >= 4.0: details["yield"] += 1
    except (ValueError, TypeError): pass

    try:
        increase_years = int(stock_data.get("consecutive_increase_years", 0))
        is_calculable = True
        if increase_years >= rules.get("consecutive_increase", {}).get("good", 3): details["consecutive_increase"] += 1
        if increase_years >= rules.get("consecutive_increase", {}).get("excellent", 7): details["consecutive_increase"] += 1
    except (ValueError, TypeError): pass
        
    total_score = sum(details.values())
    return total_score if is_calculable else -1, details

async def _get_processed_stock_data() -> List[Dict]:
    """
    データ取得とスコア計算などの処理を共通化したヘルパー関数
    """
    codes = portfolio_manager.load_codes()
    if not codes:
        return []

    tasks = [asyncio.to_thread(scraper.fetch_stock_data, code) for code in codes]
    results = await asyncio.gather(*tasks)

    processed_data = []
    for item in results:
        if item and "error" not in item:
            item["consecutive_increase_years"] = calculate_consecutive_dividend_increase(item.get("dividend_history", {}))
            score, details = calculate_score(item)
            item["score"] = score
            item["score_details"] = details
        processed_data.append(item)
        
    return processed_data

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/highlight-rules")
async def get_highlight_rules():
    return HIGHLIGHT_RULES

@app.get("/api/recent-stocks") # 追加
async def get_recent_stocks(): # 追加
    return recent_stocks_manager.load_recent_codes() # 追加

@app.get("/api/stocks")
async def get_stocks():
    """
    登録されている全銘柄の最新データを取得する。
    """
    return await _get_processed_stock_data()

@app.post("/api/stocks")
async def add_stock(stock: StockCode):
    logger.info(f"Received add stock request for code: {stock.code}") # 追加
    codes = portfolio_manager.load_codes()
    if stock.code in codes:
        return {"status": "exists", "message": f"銘柄コード {stock.code} は既に追加されています。"}

    # 追加する銘柄のデータをすぐに取得してみる
    new_stock_data = await asyncio.to_thread(scraper.fetch_stock_data, stock.code)

    if new_stock_data and "error" not in new_stock_data:
        # 成功した場合のみポートフォリオに保存
        codes.append(stock.code)
        portfolio_manager.save_codes(codes)
        recent_stocks_manager.add_recent_code(stock.code) # 追加
        return {"status": "success", "stock": new_stock_data}
    else:
        # 失敗した場合は、エラー情報を返す
        error_message = new_stock_data.get("error", "不明なエラーが発生しました。）")
        return {"status": "error", "message": error_message, "code": stock.code}

@app.delete("/api/stocks/bulk-delete") # 追加
async def bulk_delete_stocks(stock_codes: StockCodesToDelete): # 追加
    if not stock_codes.codes:
        raise HTTPException(status_code=400, detail="No stock codes provided for deletion.")
    
    logger.info(f"Received bulk delete request for codes: {stock_codes.codes}")
    portfolio_manager.delete_multiple_codes(stock_codes.codes)
    return {"status": "success", "message": f"{len(stock_codes.codes)} stocks deleted."}

@app.delete("/api/stocks/{stock_code}")
async def delete_stock(stock_code: str):
    codes = portfolio_manager.load_codes()
    if stock_code in codes:
        codes.remove(stock_code)
        portfolio_manager.save_codes(codes)
        return {"status": "success"}
    else:
        raise HTTPException(status_code=404, detail="Stock code not found")

@app.get("/api/stocks/csv")
async def download_csv():
    """
    現在のポートフォリオをCSV形式でダウンロードする。
    """
    data = await _get_processed_stock_data()
    if not data:
        return StreamingResponse(io.StringIO(""), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=portfolio.csv"})

    csv_data = portfolio_manager.create_csv_data(data)

    filename = f"portfolio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = StreamingResponse(io.StringIO(csv_data), media_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response