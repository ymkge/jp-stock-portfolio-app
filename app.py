from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import asyncio

import scraper
import portfolio_manager

app = FastAPI()

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