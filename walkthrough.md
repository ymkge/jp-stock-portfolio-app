# ウォークスルー資料: 株式売却モーダルのUI調整＆売却当日以外（過去日付・手数料控除）対応 (#335)

## 1. 概要と対応の背景
Issue #332 で導入した株式売却（利確・損切り）および再投資待機資金プール機能について、実運用での利便性とデザインの視認性・余白感を高めるため、以下の改善を実施しました。

1. **ダークモード視認性の根本解決**: ダークモード時に銘柄情報カード（銘柄名・コード・口座種別等）が白背景に白文字で同化し見えなくなっていた不具合の解消。
2. **モーダル幅および左右パディングの最適化**:
   - `.modal-body` にインライン指定されていた左右パディング `0`（`style="padding: 1rem 0;"`）を完全撤廃し、アプリ標準の左右パディング（`1.5rem` / `24px`）を復元。
   - モーダル最大幅を `max-width: 520px` からゆとりのある `max-width: 560px` に広げ、外枠に中身がぴったり張り付いて窮屈に見えていた違和感を解消。
   - 関連する再投資プールモーダル（`#reinvestment-pool-modal`）も同様に左右パディングを復元し、サマリーカードをダークモード両立クラス（`.pool-summary-card`）に統一。
3. **売却当日以外の過去日付対応**: 売却当日にアプリを起動できなかった場合でも、過去の約定日を選択可能に（未来日は選択不可ガード）。
4. **手数料・税金等控除額の入力対応**: 売却代金（額面）から手数料・譲渡益税を控除した手取受取額（純額）を入力・計算できるようにし、手取額を再投資待機資金プール加算および確定損益の基準に反映。
5. **フォームUIと余白（マージン）の最適化**: 詰まっていた入力フォームの余白を整理し、リアルタイムプレビューに「想定売却代金 (額面)」「手取受取額 (待機プール加算額)」「確定損益 (実現損益・控除後)」を明瞭に表示。

---

## 2. 不具合の原因と設計・対策

### 2.1 モーダルの左右幅がギリギリになっていた原因と対策
- **原因**:
  - `templates/index.html`（Line 292）において、`<div class="modal-body" style="padding: 1rem 0;">` とインライン指定されていたため、CSS共通定義（`style.css` Line 2091: `padding: 1.25rem 1.5rem;`）で本来確保されるはずの左右 `1.5rem`（`24px`）の余白が失われ、左右 `0px` に上書きされていた。
  - この結果、銘柄カード・各入力枠・プレビューカード・ボタンエリアの全要素が、モーダルの左右の外枠線にぴったり張り付いて極度に窮屈な見た目となっていた。
- **対策**:
  - `templates/index.html` から `style="padding: 1rem 0;"` を完全削除。
  - `static/css/style.css` 側で `#sell-holding-modal .modal-content { max-width: 560px; }` を定義し、モーダル幅に呼吸空間を持たせた。
  - 併せて `#reinvestment-pool-modal` の `.modal-body` からも `padding: 1rem 0;` を削除し、サマリーカードを `.pool-summary-card` で統一。

### 2.2 ダークモード時の銘柄名同化問題
- **原因**: `templates/index.html` 内の銘柄カードで `style="background-color: var(--card-bg, #f8fafc); ..."` とインラインスタイルが直書きされていた。CSSの `:root` に `--card-bg` が未定義だったため、ダークモード時でもフォールバック値 `#f8fafc`（白）が固定適用され、ダークモード用の文字色（白）と同化していた。
- **対策**: インラインスタイルを完全撤廃し、専用CSSクラス `.sell-target-stock-info` を導入。通常時は背景 `#f8fafc` / 文字 `#1e293b`、ダークモード（`:root.dark-mode`, `body.dark-mode`, `[data-theme="dark"]`）時は背景 `#1e293b` / 文字 `#f8fafc` と明瞭なコントラストを定義。

### 2.3 過去日付・売却単価・手数料控除の設計
- **日付**: `sellDateInput.max = todayStr` を設定し、過去日付の選択を可能にしつつ未来日を禁止。
- **手数料**: 日本円で一貫管理されている待機資金プール（JPY）に合わせ、「手数料・税金等控除額 (円)」入力フィールドを追加。
  - 手取売却額: `net_sell_amount_jpy = max(0.0, sell_amount_jpy - fee_jpy)`（手数料が売却額を上回ってもプール残高がマイナス加算されないよう0円クランプ防衛）。
  - 確定損益: `realized_pl_jpy = net_sell_amount_jpy - purchase_amount_jpy`（手取額基準で計算）。
  - 再投資プール: `update_reinvestment_pool_balance(net_sell_amount_jpy)`（手取額のみ加算）。
  - DBスキーマ: `realized_trades` テーブルに `fee_jpy REAL DEFAULT 0.0` を自律マイグレーションで追加し永続化。

---

## 3. 変更対象ファイル一覧

| ファイルパス | 変更内容 |
| :--- | :--- |
| `history_manager.py` | `realized_trades` に `fee_jpy` カラムの自律マイグレーション追加、`add_realized_trade` での手数料・手取額保存、`get_realized_summary` での `total_fee_jpy` 集計 |
| `portfolio_manager.py` | `sell_holding` に `fee_jpy` 引数を追加、手取額 `net_sell_amount_jpy` 計算、プール加算および確定損益への手取額適用 |
| `app.py` | `SellHoldingRequest` に `fee: Optional[float] = 0.0` 追加、`sell_holding_endpoint` での負数バリデーションと `portfolio_manager` 連携 |
| `static/css/style.css` | `.sell-target-stock-info`, `.sell-form-group`, `.sell-form-label`, `.sell-form-input`, `.sell-preview-card`, `.pool-summary-card` のスタイルおよびダークモード（トリプルセレクタ）対応を追加。<br>売却モーダル最大幅（`560px`）および再投資プールモーダル最大幅（`720px`）を定義。 |
| `templates/index.html` | 売却モーダルおよび再投資プールモーダルのインラインスタイル排除、左右標準パディング復元、手数料入力フィールド追加、プレビュー構成更新、キャッシュバスター更新（`style.css?v=4.0`, `main.js?v=4.1`） |
| `static/js/main.js` | `openSellModal` での `sellDateInput.max = todayStr` 設定、手数料リセット、`updateSellPreview` での手取額・確定損益リアルタイム計算、売却APIへの `fee` 送信 |
| `tests/test_portfolio.py` | 手数料控除ありの売却テスト、過大手数料時の0円クランプテストの追加 |
| `tests/test_api_endpoints.py` | 売却APIでの手数料パラメータ連携、負数手数料時の400バリデーションテストの追加 |
| `tests/test_history_manager.py` | 手数料あり・過去日付の売却履歴保存・取得・サマリー集計テストの追加 |

---

## 4. 自動テストおよび検証結果

### 4.1 自動テスト結果
```bash
PYTHONPATH=. pytest
====================== 210 passed, 25 warnings in 43.36s =======================
```
- 全 210 件のテストが 100% 合格。既存機能および売却・再投資プール機能へのデグレゼロを確認。

### 4.2 本番DB非汚染検証 (AGENTS.md 0.2)
- 各テーブルのレコード数を確認し、テスト用のダミーデータ（銘柄・株価・売却履歴）の混入・汚染が一切ないことを確認：
  - `portfolio_history`: 18,666 件（不変）
  - `stock_price_history`: 54,311 件（不変）
  - `realized_trades`: 0 件（本番売却履歴なし、不変）
  - `reinvestment_pool`: 1 件（初期残高 0円、不変）
