document.addEventListener('DOMContentLoaded', () => {
    const stockTableBody = document.querySelector('#stock-table tbody');
    const loadingIndicator = document.getElementById('loading-indicator');
    const addStockForm = document.getElementById('add-stock-form');
    const stockCodeInput = document.getElementById('stock-code-input');
    const tableHeaderRow = document.getElementById('table-header-row');
    const downloadCsvButton = document.getElementById('download-csv-button');
    const alertContainer = document.getElementById('alert-container');
    const selectAllStocksCheckbox = document.getElementById('select-all-stocks'); // 追加
    const deleteSelectedStocksButton = document.getElementById('delete-selected-stocks-button'); // 追加
    const recentStocksList = document.getElementById('recent-stocks-list'); // 追加
    const filterInput = document.getElementById('filter-input'); // 追加

    let tableHeaders = document.querySelectorAll('#stock-table .sortable');

    let stocksData = [];
    let highlightRules = {}; // ハイライトルールを保持

    let currentSort = {
        key: 'code',
        order: 'asc'
    };

    /**
     * メッセージボックス（アラート）を表示する
     * @param {string} message - 表示するメッセージ
     * @param {string} type - アラートの種類 ('success', 'danger', 'warning')
     */
    function showAlert(message, type = 'danger') {
        const alert = document.createElement('div');
        alert.className = `alert alert-${type}`;
        alert.textContent = message;

        alertContainer.appendChild(alert);

        // 表示アニメーション
        requestAnimationFrame(() => {
            alert.classList.add('show');
        });

        // 5秒後に非表示アニメーションを開始
        setTimeout(() => {
            alert.classList.remove('show');
            alert.classList.add('hide');
        }, 5000);

        // アニメーション終了後に要素を削除
        alert.addEventListener('transitionend', () => {
            if (alert.classList.contains('hide')) {
                alert.remove();
            }
        });
    }

    /**
     * ページの初期化処理
     */
    async function initialize() {
        showLoading(true);
        try {
            const [stocksResponse, rulesResponse, recentStocksResponse] = await Promise.all([ // recentStocksResponseを追加
                fetch('/api/stocks'),
                fetch('/api/highlight-rules'),
                fetch('/api/recent-stocks') // 追加
            ]);

            if (!stocksResponse.ok) throw new Error(`Failed to fetch stocks: ${stocksResponse.status}`);
            if (!rulesResponse.ok) throw new Error(`Failed to fetch highlight rules: ${rulesResponse.status}`);
            if (!recentStocksResponse.ok) throw new Error(`Failed to fetch recent stocks: ${recentStocksResponse.status}`); // 追加

            stocksData = await stocksResponse.json();
            highlightRules = await rulesResponse.json();
            const recentStocks = await recentStocksResponse.json(); // 追加
            renderRecentStocksList(recentStocks); // 追加

            filterAndRender(); // フィルタリングとレンダリングを実行
        } catch (error) {
            console.error('Initialization error:', error);
            showAlert('データの読み込みに失敗しました。サーバーが起動しているか確認してください。', 'danger');
        } finally {
            showLoading(false);
        }
    }

    /**
     * 直近追加銘柄リストを描画する
     */
    function renderRecentStocksList(codes) {
        if (!recentStocksList) return; // 要素がない場合は何もしない

        recentStocksList.innerHTML = '';
        if (codes.length === 0) {
            recentStocksList.innerHTML = '<li>最近追加した銘柄はありません。</li>';
            return;
        }

        codes.forEach(code => {
            const li = document.createElement('li');
            li.className = 'recent-stock-item';
            li.textContent = code;
            li.dataset.code = code;
            li.addEventListener('click', () => {
                stockCodeInput.value = code;
            });
            recentStocksList.appendChild(li);
        });
    }

    /**
     * 銘柄データをフィルタリングし、テーブルを再描画する
     */
    function filterAndRender() {
        const filterText = filterInput ? filterInput.value.toLowerCase() : '';
        let filteredStocks = stocksData;

        if (filterText) {
            filteredStocks = stocksData.filter(stock => {
                const codeMatch = String(stock.code).toLowerCase().includes(filterText);
                const nameMatch = String(stock.name || '').toLowerCase().includes(filterText);
                return codeMatch || nameMatch;
            });
        }
        sortStocks(filteredStocks); // フィルタリングされたデータをソート
        renderStockTable(filteredStocks);
        updateSortHeaders();
        updateDeleteSelectedButtonState(); // フィルタリング後もボタンの状態を更新
    }

    /**
     * 指標の値に基づいてハイライト用のCSSクラスを返す
     */
    function getHighlightClass(key, value) {
        const rules = highlightRules[key];
        if (!rules || value === 'N/A' || value === null || value === undefined || value === '--') {
            return '';
        }
        const numericValue = parseFloat(String(value).replace(/[^0-9.-]/g, ''));
        if (isNaN(numericValue)) return '';

        if (key === 'yield' || key === 'roe') {
            if (rules.undervalued !== undefined && numericValue >= rules.undervalued) return 'undervalued';
        } else {
            if (rules.undervalued !== undefined && numericValue <= rules.undervalued) return 'undervalued';
            if (rules.overvalued !== undefined && numericValue >= rules.overvalued) return 'overvalued';
        }
        return '';
    }

    /**
     * スコアを星で描画し、詳細をツールチップで表示する
     */
    function renderScoreAsStars(score, details) {
        if (score === -1) return `<span class="score-na" title="評価指標なし">N/A</span>`;
        if (score === undefined || score === null) return 'N/A';

        const maxScore = 10;
        let starsHtml = '';
        const firstRowScore = Math.min(score, 5);
        starsHtml += '★'.repeat(firstRowScore) + '☆'.repeat(5 - firstRowScore);
        starsHtml += '<br>';
        const secondRowScore = Math.max(0, score - 5);
        starsHtml += '★'.repeat(secondRowScore) + '☆'.repeat(5 - secondRowScore);
        
        let tooltipText = `合計: ${score}/${maxScore}`;
        if (details) {
            const detailParts = [
                `PER: ${details.per || 0}/2`,
                `PBR: ${details.pbr || 0}/2`,
                `ROE: ${details.roe || 0}/2`,
                `利回り: ${details.yield || 0}/2`,
                `連続増配: ${details.consecutive_increase || 0}/2`
            ];
            tooltipText += ` (${detailParts.join(', ')})`;
        }
        return `<span class="score" title="${tooltipText}">${starsHtml}</span>`;
    }

    /**
     * 銘柄データの配列をソートする
     */
    function sortStocks(data) { // 引数にdataを追加
        data.sort((a, b) => {
            let valA = a[currentSort.key];
            let valB = b[currentSort.key];

            const parseValue = (value) => {
                if (value === undefined || value === null || value === 'N/A' || value === '--' || value === '') return -Infinity;
                if (typeof value === 'string') {
                    const cleanedValue = value.replace(/,/g, '').replace(/%/, '').replace(/倍/, '').replace(/円/, '');
                    const num = parseFloat(cleanedValue);
                    return isNaN(num) ? value : num;
                }
                return value;
            };

            const parsedA = parseValue(valA);
            const parsedB = parseValue(valB);

            if (typeof parsedA === 'number' && typeof parsedB === 'number') {
                return currentSort.order === 'asc' ? parsedA - parsedB : parsedB - parsedA;
            } else {
                return currentSort.order === 'asc'
                    ? String(parsedA).localeCompare(String(parsedB))
                    : String(parsedB).localeCompare(String(parsedA));
            }
        });
    }

    /**
     * 数値を兆、億、百万円単位にフォーマットする
     */
    function formatMarketCap(value) {
        if (value === 'N/A' || value === null || value === undefined || value === '--') return 'N/A';
        const num = typeof value === 'string' ? parseFloat(value.replace(/,/g, '')) : value;
        if (isNaN(num)) return 'N/A';

        const trillion = 1_000_000_000_000;
        const oku = 100_000_000;
        const million = 1_000_000;

        if (num >= trillion) return `${(num / trillion).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}兆円`;
        if (num >= oku) return `${(num / oku).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}億円`;
        if (num >= million) return `${(num / million).toLocaleString()}百万円`;
        return `${num.toLocaleString()}円`;
    }

    /**
     * 配当履歴オブジェクトをHTML文字列にフォーマットする
     */
    function formatDividendHistory(history) {
        if (!history || Object.keys(history).length === 0) return 'N/A';
        const sortedYears = Object.keys(history).sort((a, b) => b - a);
        return sortedYears.map(year => `${year}年: ${history[year]}円`).join(' | ');
    }

    /**
     * 取得したデータでテーブルを描画する
     */
    function renderStockTable(stocks) {
        stockTableBody.innerHTML = '';
        const colspan = tableHeaderRow.children.length;

        if (!stocks || stocks.length === 0) {
            stockTableBody.innerHTML = `<tr><td colspan="${colspan}" style="text-align:center;">登録されている銘柄はありません。</td></tr>`;
            return;
        }

        stocks.forEach(stock => {
            const row = stockTableBody.insertRow();

            if (stock.error) {
                row.className = 'error-row';
                row.title = stock.error;

                const createTextCell = (text) => {
                    const cell = row.insertCell();
                    cell.textContent = text;
                    return cell;
                };

                // チェックボックスセルを追加 (無効化)
                const checkboxCell = row.insertCell();
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.className = 'stock-checkbox';
                checkbox.dataset.code = stock.code;
                checkbox.disabled = true; // エラー行は選択不可
                checkboxCell.appendChild(checkbox);

                createTextCell(stock.code);
                createTextCell(stock.name || `銘柄 ${stock.code}`);
                createTextCell('N/A'); // industry
                createTextCell('N/A'); // score
                createTextCell('N/A'); // price
                createTextCell('N/A'); // change
                createTextCell('N/A'); // market_cap
                createTextCell('N/A'); // per
                createTextCell('N/A'); // pbr
                createTextCell('N/A'); // roe
                createTextCell('N/A'); // eps
                createTextCell('N/A'); // yield
                createTextCell('N/A'); // consecutive_increase_years

                const deleteCell = row.insertCell();
                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'delete-btn';
                deleteBtn.textContent = '削除';
                deleteBtn.dataset.code = stock.code;
                deleteCell.appendChild(deleteBtn);
                return;
            }

            const createCell = (html, className = '') => {
                const cell = row.insertCell();
                cell.innerHTML = html;
                if (className) cell.className = className;
                return cell;
            };
            
            const createTextCell = (text, className = '') => {
                const cell = row.insertCell();
                cell.textContent = text;
                if (className) cell.className = className;
                return cell;
            };

            // チェックボックスセルを追加
            const checkboxCell = row.insertCell();
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'stock-checkbox';
            checkbox.dataset.code = stock.code;
            checkboxCell.appendChild(checkbox);

            createTextCell(stock.code);
            createCell(`<a href="https://finance.yahoo.co.jp/quote/${stock.code}.T" target="_blank">${stock.name}</a>`);
            createTextCell(stock.industry || 'N/A');
            createCell(renderScoreAsStars(stock.score, stock.score_details));
            createTextCell(stock.price);
            createTextCell(`${stock.change} (${stock.change_percent === 'N/A' ? 'N/A' : stock.change_percent + '%'})`);
            createTextCell(formatMarketCap(stock.market_cap));
            createTextCell(stock.per, getHighlightClass('per', stock.per));
            createTextCell(stock.pbr, getHighlightClass('pbr', stock.pbr));
            createTextCell(stock.roe === 'N/A' ? 'N/A' : stock.roe + '%', getHighlightClass('roe', stock.roe));
            createTextCell(stock.eps === 'N/A' ? 'N/A' : stock.eps + '円');
            createTextCell(stock.yield === 'N/A' ? 'N/A' : stock.yield + '%', getHighlightClass('yield', stock.yield));

            const dividendCell = row.insertCell();
            dividendCell.title = formatDividendHistory(stock.dividend_history);
            const dividendLink = document.createElement('a');
            dividendLink.href = `https://finance.yahoo.co.jp/quote/${stock.code}.T/dividend`;
            dividendLink.target = '_blank';
            dividendLink.className = 'dividend-link';
            if (stock.consecutive_increase_years > 0) {
                const badge = document.createElement('span');
                badge.className = 'increase-badge';
                badge.textContent = `${stock.consecutive_increase_years}年連続`;
                dividendLink.appendChild(badge);
            } else {
                dividendLink.textContent = '-';
            }
            dividendCell.appendChild(dividendLink);

            const deleteCell = row.insertCell();
            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'delete-btn';
            deleteBtn.textContent = '削除';
            deleteBtn.dataset.code = stock.code;
            deleteCell.appendChild(deleteBtn);
        });
    }

    /**
     * ソート中のヘッダーにCSSクラスを付与する
     */
    function updateSortHeaders() {
        tableHeaders.forEach(header => {
            if (header.dataset.key === currentSort.key) {
                header.classList.add('sort-active');
                header.classList.toggle('sort-asc', currentSort.order === 'asc');
                header.classList.toggle('sort-desc', currentSort.order === 'desc');
            } else {
                header.classList.remove('sort-active', 'sort-asc', 'sort-desc');
            }
        });
    }

    /**
     * ローディングインジケーターの表示を切り替える
     */
    function showLoading(isLoading) {
        loadingIndicator.style.display = isLoading ? 'block' : 'none';
        stockTableBody.style.display = isLoading ? 'none' : '';
    }

    /**
     * 銘柄追加フォームの送信イベント
     */
    addStockForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const code = stockCodeInput.value.trim();
        if (!code) return;

        try {
            const response = await fetch('/api/stocks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: code }),
            });
            
            const data = await response.json();

            if (data.status === 'success') {
                showAlert(`銘柄 ${data.stock.name} (${code}) を追加しました。`, 'success');
            } else if (data.status === 'exists') {
                showAlert(data.message, 'warning');
            } else if (data.status === 'error') {
                showAlert(`銘柄 ${data.code} の追加に失敗しました: ${data.message}`, 'danger');
            }

            stockCodeInput.value = '';
            filterAndRender(); // テーブルと直近追加銘柄リストを再描画

        } catch (error) {
            console.error('Error adding stock:', error);
            showAlert('銘柄の追加中に予期せぬエラーが発生しました。', 'danger');
        }
    });

    /**
     * 削除ボタンのクリックイベント（イベントデリゲーション）
     */
    stockTableBody.addEventListener('click', async (event) => {
        if (event.target.classList.contains('delete-btn')) {
            const code = event.target.dataset.code;
            if (!confirm(`銘柄コード ${code} を削除しますか？`)) return;

            try {
                const response = await fetch(`/api/stocks/${code}`, { method: 'DELETE' });
                if (!response.ok) throw new Error('Failed to delete stock');
                showAlert(`銘柄 ${code} を削除しました。`, 'success');
                filterAndRender(); // テーブルを再描画
            } catch (error) {
                console.error('Error deleting stock:', error);
                showAlert('銘柄の削除に失敗しました。', 'danger');
            }
        }
    });

    /**
     * テーブルヘッダーのクリックイベント（ソート処理）
     */
    function addSortEventListeners() {
        tableHeaders.forEach(header => {
            header.addEventListener('click', () => {
                const key = header.dataset.key;
                if (currentSort.key === key) {
                    currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc';
                } else {
                    currentSort.key = key;
                    currentSort.order = 'asc';
                }
                sortAndRender();
            });
        });
    }

    /**
     * CSVダウンロードボタンのクリックイベント
     */
    downloadCsvButton.addEventListener('click', async () => {
        try {
            const response = await fetch('/api/stocks/csv');
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

            const disposition = response.headers.get('Content-Disposition');
            let filename = 'portfolio.csv';
            if (disposition && disposition.indexOf('attachment') !== -1) {
                const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
                const matches = filenameRegex.exec(disposition);
                if (matches != null && matches[1]) {
                    filename = decodeURI(matches[1].replace(/['"]/g, ''));
                }
            }

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (error) {
            console.error('Error downloading CSV:', error);
            showAlert('CSVファイルのダウンロードに失敗しました。', 'danger');
        }
    });

    /**
     * 選択された銘柄の削除ボタンの有効/無効を切り替える
     */
    function updateDeleteSelectedButtonState() {
        const checkedCheckboxes = document.querySelectorAll('.stock-checkbox:checked');
        deleteSelectedStocksButton.disabled = checkedCheckboxes.length === 0;
    }

    /**
     * 全選択チェックボックスのイベントリスナー
     */
    if (selectAllStocksCheckbox) {
        selectAllStocksCheckbox.addEventListener('change', () => {
            const isChecked = selectAllStocksCheckbox.checked;
            document.querySelectorAll('.stock-checkbox').forEach(checkbox => {
                if (!checkbox.disabled) { // エラー行のチェックボックスは操作しない
                    checkbox.checked = isChecked;
                }
            });
            updateDeleteSelectedButtonState();
        });
    }

    /**
     * 個別銘柄チェックボックスのイベントリスナー（イベントデリゲーション）
     */
    stockTableBody.addEventListener('change', (event) => {
        if (event.target.classList.contains('stock-checkbox')) {
            updateDeleteSelectedButtonState();

            // 全てのチェックボックスがチェックされているか確認し、全選択チェックボックスの状態を更新
            const allCheckboxes = document.querySelectorAll('.stock-checkbox:not(:disabled)');
            const checkedCheckboxes = document.querySelectorAll('.stock-checkbox:checked:not(:disabled)');
            if (selectAllStocksCheckbox) {
                selectAllStocksCheckbox.checked = allCheckboxes.length > 0 && allCheckboxes.length === checkedCheckboxes.length;
            }
        }
    });

    /**
     * 選択した銘柄を削除ボタンのイベントリスナー
     */
    if (deleteSelectedStocksButton) {
        deleteSelectedStocksButton.addEventListener('click', async () => {
            const checkedCheckboxes = document.querySelectorAll('.stock-checkbox:checked');
            const codesToDelete = Array.from(checkedCheckboxes).map(checkbox => checkbox.dataset.code);

            if (codesToDelete.length === 0) {
                showAlert('削除する銘柄が選択されていません。', 'warning');
                return;
            }

            if (!confirm(`選択された ${codesToDelete.length} 件の銘柄を削除しますか？\nこの操作は元に戻せません。`)) {
                return;
            }

            try {
                const response = await fetch('/api/stocks/bulk-delete', { // 新しいAPIエンドポイントを想定
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ codes: codesToDelete }),
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || '一括削除に失敗しました。');
                }

                showAlert(`${codesToDelete.length} 件の銘柄を削除しました。`, 'success');
                filterAndRender(); // テーブルを再描画
                if (selectAllStocksCheckbox) {
                    selectAllStocksCheckbox.checked = false; // 全選択チェックボックスを解除
                }
                updateDeleteSelectedButtonState(); // ボタンの状態を更新
            } catch (error) {
                console.error('Error bulk deleting stocks:', error);
                showAlert(`一括削除に失敗しました: ${error.message}`, 'danger');
            }
        });
    }

    // 初期表示
    addSortEventListeners();
    initialize();
    updateDeleteSelectedButtonState(); // 初期ロード時にボタンの状態を更新

    // フィルタ入力フィールドのイベントリスナー
    if (filterInput) {
        filterInput.addEventListener('input', () => {
            filterAndRender();
        });
    }
});