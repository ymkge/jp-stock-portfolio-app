# 国内株式ポートフォリオ管理アプリ (jp-stock-portfolio-app)

## 概要

ユーザーが管理する国内株式の銘柄リストに基づき、株価、財務指標、配当情報をYahoo!ファイナンスから取得し、Webページに一覧表示するシングルページアプリケーション（SPA）です。

主な機能は以下の通りです。
- **銘柄一覧表示**: 登録された銘柄の各種情報をリアルタイムで取得し、テーブル形式で表示します。
- **銘柄追加**: 銘柄コードを指定して、ポートフォリオに新しい銘柄を追加します。
- **銘柄削除**: ポートフォリオから不要な銘柄を削除します。
- **ソート機能**: ポートフォリオ一覧の各項目（銘柄コード、株価など）をクリックすることで、データを昇順・降順に並び替えることができます。

## 主な技術

### バックエンド
- **言語**: Python 3.10+
- **Webフレームワーク**: FastAPI
- **Webサーバー**: Uvicorn
- **データ取得**: `requests` (HTMLからページ埋め込みJSONを抽出)
- **データ永続化**: JSONファイル (`portfolio.json`)

### フロントエンド
- **HTML/CSS**: Jinja2テンプレート
- **JavaScript**: ES6+, Fetch API

## セットアップと実行方法

1. **リポジトリをクローンします。**
   ```bash
   git clone https://github.com/your-username/jp-stock-portfolio-app.git
   cd jp-stock-portfolio-app
   ```

2. **必要なPythonライブラリをインストールします。**
   ```bash
   pip install fastapi uvicorn python-multipart requests jinja2
   ```

3. **FastAPI開発サーバーを起動します。**
   ```bash
   uvicorn app:app --reload
   ```
   `--reload`オプションにより、コードを変更するとサーバーが自動的に再起動します。

4. **ブラウザでアクセスします。**
   Webブラウザを開き、 `http://127.0.0.1:8000` にアクセスしてください。

## 使い方

- **銘柄の追加**: 画面上部の入力フォームに4桁の銘柄コードを入力し、「追加」ボタンをクリックします。
- **銘柄の削除**: 一覧テーブルの各行にある「削除」ボタンをクリックします。
- **データ更新**: ページをリロードすると、全銘柄の最新情報が再取得されます。
- **ソート**: 一覧テーブルのヘッダー（「銘柄コード」や「現在株価」など）をクリックすると、その列のデータで昇順・降順にソートされます。

## 処理フロー

### データ表示フロー
```mermaid
sequenceDiagram
    participant User as ユーザー
    participant Browser as ブラウザ (JS)
    participant API as FastAPIバックエンド
    participant Scraper as Webスクレイパー
    participant Portfolio as portfolio.json

    User->>Browser: ページ読み込み
    Browser->>API: GET /api/stocks (全銘柄データ要求)
    API->>Portfolio: 銘柄コードリスト読み込み
    Portfolio-->>API: ["7203", "9432", ...]
    API->>Scraper: 各銘柄コードのデータ取得を並行依頼
    Scraper-->>API: 銘柄データ (株価, PERなど)
    API-->>Browser: JSON (銘柄データリスト)
    Browser->>User: テーブルにデータを描画・表示
```

### 銘柄追加フロー
```mermaid
sequenceDiagram
    participant User as ユーザー
    participant Browser as ブラウザ (JS)
    participant API as FastAPIバックエンド
    participant Portfolio as portfolio.json

    User->>Browser: 銘柄コード入力 & 追加ボタンクリック
    Browser->>API: POST /api/stocks ({"code": "XXXX"})
    API->>Portfolio: 銘柄コードリスト読み込み
    Portfolio-->>API: 既存コードリスト
    API->>Portfolio: 新しいコードを追加して保存
    Portfolio-->>API: 保存完了
    API-->>Browser: {"status": "success"}
    Browser->>API: GET /api/stocks (データ再取得)
    API-->>Browser: 更新された銘柄データリスト
    Browser->>User: テーブルを更新
```

### 銘柄削除フロー
```mermaid
sequenceDiagram
    participant User as ユーザー
    participant Browser as ブラウザ (JS)
    participant API as FastAPIバックエンド
    participant Portfolio as portfolio.json

    User->>Browser: 削除ボタンクリック
    Browser->>API: DELETE /api/stocks/{stock_code}
    API->>Portfolio: 銘柄コードリスト読み込み
    Portfolio-->>API: 既存コードリスト
    API->>Portfolio: 該当コードを削除して保存
    Portfolio-->>API: 保存完了
    API-->>Browser: {"status": "success"}
    Browser->>API: GET /api/stocks (データ再取得)
    API-->>Browser: 更新された銘柄データリスト
    Browser->>User: テーブルを更新
```

## 課題 (next step)

### 【調査中】配当履歴表示機能の不具合
- **目的**: ポートフォリオに過去数年分の1株あたり配当履歴を表示する。
- **現状**: `scraper.py`の配当履歴取得ロジックが、Yahoo!ファイナンスのWebサイト側の仕様変更（HTML構造の変更など）により、正しくデータを取得できていない。
- **調査状況 (2025/11/01)**:
  - 当初スクレイピング対象としていた `/history` ページから、配当情報専用の `/dividend` ページに対象を変更。
  - 新しいページのHTML構造に合わせて `BeautifulSoup` のパーサーを何度も修正したが、安定したデータ取得には至らなかった。
  - JavaScriptによる動的なHTML生成や、アクセス制限など、単純な`requests`によるHTML取得では対応できない問題が発生している可能性がある。
- **今後の対策案**:
  - `Selenium`や`Playwright`といったヘッドレスブラウザライブラリを導入し、JavaScriptがレンダリングした後の最終的なHTMLからデータを取得する方法を検討する。

### その他の課題
- UIの改善(よりリッチな表示へ)
- CSVダウンロード機能の追加
- 銘柄情報取得に失敗した際のエラーハンドリング強化

---

## 対応済みの課題

### 時価総額が「N/A」になる問題 (2025/11/01 対応済み)
- **原因**: `scraper.py`が参照していたYahoo!ファイナンスの内部APIの仕様が変更され、時価総額のデータ形式が変わっていたため。
- **対応**: 新しいデータ形式に対応するよう、`scraper.py`のデータ解析ロジックを修正した。