from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
import io
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional

import scraper
import portfolio_manager
import recent_stocks_manager
import json
import logging

# --- ロギング設定 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# --------------------

app = FastAPI()

# --- 定数 ---
ACCOUNT_TYPES = ["特定口座", "一般口座", "新NISA", "旧NISA"]

# --- ハイライトルールの読み込み ---
HIGHLIGHT_RULES = {}
try:
    with open("highlight_rules.json", "r", encoding="utf-8") as f:
        HIGHLIGHT_RULES = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    logger.warning(f"highlight_rules.json の読み込みに失敗しました。デフォルト値で動作します。: {e}")

# 静的ファイルのマウント
app.mount("/static", StaticFiles(directory="static"), name="static")

# テンプレートの設定
templates = Jinja2Templates(directory="templates")

# --- Pydanticモデル ---
class StockCode(BaseModel):
    code: str

class StockCodesToDelete(BaseModel):
    codes: List[str]

class HoldingData(BaseModel):
    account_type: str
    purchase_price: float
    quantity: int

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

async def _get_processed_stock_data() -> List[Dict[str, Any]]:
    portfolio = portfolio_manager.load_portfolio()
    if not portfolio: return []
    codes = [stock['code'] for stock in portfolio]
    tasks = [asyncio.to_thread(scraper.fetch_stock_data, code) for code in codes]
    scraped_results = await asyncio.gather(*tasks)
    scraped_data_map = {item['code']: item for item in scraped_results if item}
    processed_data = []
    for stock_info in portfolio:
        code = stock_info['code']
        scraped_data = scraped_data_map.get(code)
        merged_data = {**stock_info, **(scraped_data or {"error": "データ取得失敗"})}
        if "error" not in merged_data:
            merged_data["consecutive_increase_years"] = calculate_consecutive_dividend_increase(merged_data.get("dividend_history", {}))
            score, details = calculate_score(merged_data)
            merged_data["score"] = score
            merged_data["score_details"] = details
        processed_data.append(merged_data)
    return processed_data

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

@app.get("/api/highlight-rules")
async def get_highlight_rules():
    return HIGHLIGHT_RULES

@app.get("/api/recent-stocks")
async def get_recent_stocks():
    return recent_stocks_manager.load_recent_codes()

@app.get("/api/stocks")
async def get_stocks():
    return await _get_processed_stock_data()

@app.post("/api/stocks")
async def add_stock_endpoint(stock: StockCode):
    is_added = portfolio_manager.add_stock(stock.code)
    if not is_added:
        return {"status": "exists", "message": f"銘柄コード {stock.code} は既に追加されています。"}
    new_stock_data = await asyncio.to_thread(scraper.fetch_stock_data, stock.code)
    if new_stock_data and "error" not in new_stock_data:
        recent_stocks_manager.add_recent_code(stock.code)
        return {"status": "success", "stock": new_stock_data}
    else:
        portfolio_manager.delete_stocks([stock.code])
        error_message = new_stock_data.get("error", "不明なエラー")
        return {"status": "error", "message": f"銘柄 {stock.code} は存在しないか、データの取得に失敗しました: {error_message}", "code": stock.code}

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

@app.get("/api/stocks/csv")
async def download_csv():
    data = await _get_processed_stock_data()
    if not data:
        return StreamingResponse(io.StringIO(""), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=portfolio.csv"})
    csv_data = portfolio_manager.create_csv_data(data)
    filename = f"portfolio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = StreamingResponse(io.StringIO(csv_data), media_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response

@app.get("/api/portfolio/analysis")
async def get_portfolio_analysis():
    """保有銘柄の分析データを返す"""
    all_stocks = await _get_processed_stock_data()
    
    holdings_list = []
    industry_breakdown = {}
    account_type_breakdown = {}

    for stock in all_stocks:
        if "error" in stock or not stock.get("holdings"):
            continue

        for holding in stock["holdings"]:
            try:
                # 各保有情報に対して評価額などを計算
                purchase_price = float(holding["purchase_price"])
                quantity = int(holding["quantity"])
                price = float(str(stock.get("price", "0")).replace(',', ''))
                
                investment_amount = purchase_price * quantity
                market_value = price * quantity
                profit_loss = market_value - investment_amount
                profit_loss_rate = (profit_loss / investment_amount) * 100 if investment_amount != 0 else 0
                
                estimated_annual_dividend = None
                try:
                    annual_dividend = float(str(stock.get("annual_dividend", "")).replace(',', ''))
                    estimated_annual_dividend = annual_dividend * quantity
                except (ValueError, TypeError):
                    pass

                # 分析用リストに追加
                holding_detail = {
                    **stock, # 銘柄の基本情報
                    **holding, # 口座の保有情報
                    "investment_amount": investment_amount,
                    "market_value": market_value,
                    "profit_loss": profit_loss,
                    "profit_loss_rate": profit_loss_rate,
                    "estimated_annual_dividend": estimated_annual_dividend,
                }
                del holding_detail["holdings"] # 不要なネストを削除
                holdings_list.append(holding_detail)

                # 集計
                industry = stock.get("industry", "その他")
                industry_breakdown[industry] = industry_breakdown.get(industry, 0) + market_value
                
                account_type = holding.get("account_type", "不明")
                account_type_breakdown[account_type] = account_type_breakdown.get(account_type, 0) + market_value

            except (ValueError, TypeError, KeyError, ZeroDivisionError):
                continue

    return {
        "holdings_list": holdings_list,
        "industry_breakdown": industry_breakdown,
        "account_type_breakdown": account_type_breakdown,
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