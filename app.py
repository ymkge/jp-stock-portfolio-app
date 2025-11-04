from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
import io
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import asyncio
from datetime import datetime

import scraper
import portfolio_manager
import json

app = FastAPI()

# --- ハイライトルールの読み込み ---
HIGHLIGHT_RULES = {}
try:
    with open("highlight_rules.json", "r", encoding="utf-8") as f:
        HIGHLIGHT_RULES = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"Warning: Could not load highlight_rules.json. {e}")
# --------------------------------

# 静的ファイルのマウント
app.mount("/static", StaticFiles(directory="static"), name="static")

# テンプレートの設定
templates = Jinja2Templates(directory="templates")

class StockCode(BaseModel):
    code: str

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
        
        # キーが存在するか確認
        if current_year_str not in dividend_history or previous_year_str not in dividend_history:
            break

        try:
            current_dividend = float(dividend_history[current_year_str])
            previous_dividend = float(dividend_history[previous_year_str])
        except (ValueError, TypeError):
            # 数値に変換できないデータがあれば、そこで計算を打ち切る
            break

        # 減配していたらループを抜ける (配当維持はOK)
        if current_dividend < previous_dividend:
            break
        
        consecutive_years += 1
        
    return consecutive_years

def calculate_score(stock_data: dict) -> tuple[int, dict]:
    """
    銘柄データに基づいて割安度スコアと詳細を計算する (最大8点)
    スコアが計算不能な場合は-1を返す
    """
    details = {"per": 0, "pbr": 0, "roe": 0, "yield": 0}
    total_score = 0
    is_calculable = False # 少なくとも1つの指標が計算可能だったか
    rules = HIGHLIGHT_RULES

    # PER (低いほど良い) - max 2 points
    try:
        per_str = str(stock_data.get("per", "inf")).replace('倍', '')
        per = float(per_str)
        is_calculable = True
        if per <= rules.get("per", {}).get("undervalued", 15.0):
            details["per"] += 1
        if per <= 10.0:
            details["per"] += 1
    except (ValueError, TypeError):
        pass

    # PBR (低いほど良い) - max 2 points
    try:
        pbr_str = str(stock_data.get("pbr", "inf")).replace('倍', '')
        pbr = float(pbr_str)
        is_calculable = True
        if pbr <= rules.get("pbr", {}).get("undervalued", 1.0):
            details["pbr"] += 1
        if pbr <= 0.7:
            details["pbr"] += 1
    except (ValueError, TypeError):
        pass

    # ROE (高いほど良い) - max 2 points
    try:
        roe_str = str(stock_data.get("roe", "0")).replace('%', '')
        roe = float(roe_str)
        is_calculable = True
        if roe >= rules.get("roe", {}).get("undervalued", 10.0):
            details["roe"] += 1
        if roe >= 15.0:
            details["roe"] += 1
    except (ValueError, TypeError):
        pass

    # 配当利回り (高いほど良い) - max 2 points
    try:
        yield_str = str(stock_data.get("yield", "0")).replace('%', '')
        yield_val = float(yield_str)
        is_calculable = True
        if yield_val >= rules.get("yield", {}).get("undervalued", 3.0):
            details["yield"] += 1
        if yield_val >= 4.0:
            details["yield"] += 1
    except (ValueError, TypeError):
        pass
        
    total_score = sum(details.values())

    # どの指標も計算できなかった場合、スコアを-1として返す
    if not is_calculable:
        return -1, details
        
    return total_score, details

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    メインページ (index.html) をレンダリングして返す。
    """
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/highlight-rules")
async def get_highlight_rules():
    """
    指標をハイライトするためのルール設定を返す。
    """
    return HIGHLIGHT_RULES

@app.get("/api/stocks")
async def get_stocks():
    """
    登録されている全銘柄の最新データを取得する。
    """
    codes = portfolio_manager.load_codes()
    if not codes:
        return []

    # 各銘柄のデータ取得を並行して行う
    tasks = [asyncio.to_thread(scraper.fetch_stock_data, code) for code in codes]
    results = await asyncio.gather(*tasks)

    # Noneが返されたもの（エラー）を除外
    data = [res for res in results if res is not None]
    
    # 各銘柄にスコアと詳細、連続増配年数を付与
    for item in data:
        score, details = calculate_score(item)
        item["score"] = score
        item["score_details"] = details
        item["consecutive_increase_years"] = calculate_consecutive_dividend_increase(item.get("dividend_history", {}))
        
    return data

@app.post("/api/stocks")
async def add_stock(stock: StockCode):
    """
    新しい銘柄をポートフォリオに追加する。
    """
    codes = portfolio_manager.load_codes()
    if stock.code not in codes:
        codes.append(stock.code)
        portfolio_manager.save_codes(codes)
    return {"status": "success"}

@app.delete("/api/stocks/{stock_code}")
async def delete_stock(stock_code: str):
    """
    銘柄をポートフォリオから削除する。
    """
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
    codes = portfolio_manager.load_codes()
    if not codes:
        # 空のCSVを返す
        return StreamingResponse(io.StringIO(""), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=portfolio.csv"})

    # 各銘柄のデータ取得を並行して行う
    tasks = [asyncio.to_thread(scraper.fetch_stock_data, code) for code in codes]
    results = await asyncio.gather(*tasks)

    # Noneが返されたもの（エラー）を除外
    data = [res for res in results if res is not None]

    # 各銘柄にスコアと詳細、連続増配年数を付与
    for item in data:
        score, details = calculate_score(item)
        item["score"] = score
        item["score_details"] = details
        item["consecutive_increase_years"] = calculate_consecutive_dividend_increase(item.get("dividend_history", {}))
    
    if not data:
        return StreamingResponse(io.StringIO(""), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=portfolio.csv"})

    # CSVデータをメモリ上で作成
    csv_data = portfolio_manager.create_csv_data(data)

    # StreamingResponseを使ってCSVを返す
    filename = f"portfolio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = StreamingResponse(io.StringIO(csv_data), media_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response
