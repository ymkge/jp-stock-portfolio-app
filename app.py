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
    
    if not data:
        return StreamingResponse(io.StringIO(""), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=portfolio.csv"})

    # CSVデータをメモリ上で作成
    csv_data = portfolio_manager.create_csv_data(data)

    # StreamingResponseを使ってCSVを返す
    filename = f"portfolio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = StreamingResponse(io.StringIO(csv_data), media_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response