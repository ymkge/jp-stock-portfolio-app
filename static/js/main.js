document.addEventListener('DOMContentLoaded', () => {
    const stockTableBody = document.querySelector('#stock-table tbody');
    const loadingIndicator = document.getElementById('loading-indicator');
    const addStockForm = document.getElementById('add-stock-form');
    const stockCodeInput = document.getElementById('stock-code-input');
    const tableHeaderRow = document.getElementById('table-header-row');
    const downloadCsvButton = document.getElementById('download-csv-button'); // CSVボタン追加
    
    let tableHeaders = document.querySelectorAll('#stock-table .sortable');

    let stocksData = []; // APIから取得した生のデータを保持
    let dividendYears = []; // 配当履歴の年 (例: ["2024", "2023", ...])
    let headersInitialized = false; // ヘッダーが初期化されたか

    let currentSort = {
        key: 'code', // デフォルトのソートキー
        order: 'asc'   // 'asc' or 'desc'
    };

    /**
     * データを取得してテーブルを初期表示する
     */
    async function fetchAndDisplayStocks() {
        showLoading(true);
        try {
            const response = await fetch('/api/stocks');
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            stocksData = await response.json();

            // NOTE: CSVダウンロード機能実装に伴い、配当履歴関連の処理は一旦コメントアウト
            // if (stocksData.length > 0 && !headersInitialized) {
            //     // 最初のデータから配当履歴の年を取得し、ヘッダーを更新
            //     dividendYears = stocksData[0].dividend_history ? Object.keys(stocksData[0].dividend_history).sort((a, b) => b - a) : [];
            //     updateTableHeaders();
            //     headersInitialized = true;
            // }

            sortAndRender(); // 取得したデータをソートして描画
        } catch (error) {
            console.error('Error fetching stocks:', error);
            const colspan = tableHeaderRow.children.length;
            stockTableBody.innerHTML = `<tr><td colspan="${colspan}" style="text-align:center; color: red;">データの読み込みに失敗しました。</td></tr>`;
        } finally {
            showLoading(false);
        }
    }

    /**
     * 配当履歴の年数に応じてテーブルヘッダーを動的に更新する
     */
    function updateTableHeaders() {
        const operationHeader = tableHeaderRow.querySelector('th:last-child');

        dividendYears.forEach(year => {
            const th = document.createElement('th');
            th.className = 'sortable';
            th.dataset.key = `div_${year}`;
            th.textContent = `${year}年 配当`;
            tableHeaderRow.insertBefore(th, operationHeader);
        });

        // ヘッダーのイベントリスナーを再設定
        tableHeaders = document.querySelectorAll('#stock-table .sortable');
        addSortEventListeners();
    }

    /**
     * 現在のソート条件でデータをソートし、テーブルを再描画する
     */
    function sortAndRender() {
        sortStocks();
        renderStockTable(stocksData);
        updateSortHeaders();
    }

    /**
     * 銘柄データの配列をソートする
     */
    function sortStocks() {
        stocksData.sort((a, b) => {
            let valA, valB;

            if (currentSort.key.startsWith('div_')) {
                const year = currentSort.key.split('_')[1];
                valA = a.dividend_history ? a.dividend_history[year] : null;
                valB = b.dividend_history ? b.dividend_history[year] : null;
            } else {
                valA = a[currentSort.key];
                valB = b[currentSort.key];
            }

            const parseValue = (value) => {
                if (typeof value === 'string') {
                    if (value === 'N/A' || value === '--' || value === '') return null;
                    const cleanedValue = value.replace(/,/g, '').replace(/%/, '').replace(/倍/, '').replace(/円/, '');
                    const num = parseFloat(cleanedValue);
                    return isNaN(num) ? value : num;
                }
                return value;
            };

            const parsedA = parseValue(valA);
            const parsedB = parseValue(valB);

            if (parsedA === null && parsedB !== null) return 1;
            if (parsedA !== null && parsedB === null) return -1;
            if (parsedA === null && parsedB === null) return 0;

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
        if (value === 'N/A' || value === null || value === undefined || value === '--') {
            return 'N/A';
        }
        const num = typeof value === 'string' ? parseFloat(value.replace(/,/g, '')) : value;
        if (isNaN(num)) return 'N/A';

        const trillion = 1_000_000_000_000;
        const billion = 1_000_000_000;
        const million = 1_000_000;

        if (num >= trillion) return `${(num / trillion).toFixed(2)} 兆円`;
        if (num >= billion) return `${(num / billion).toFixed(2)} 億円`;
        if (num >= million) return `${Math.round(num / million)} 百万円`;
        return `${num.toLocaleString()} 円`;
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
            const row = document.createElement('tr');
            // NOTE: CSVダウンロード機能実装に伴い、配当履歴関連の処理は一旦コメントアウト
            // let dividendCells = dividendYears.map(year => {
            //     const value = stock.dividend_history ? (stock.dividend_history[year] || '0') : 'N/A';
            //     return `<td>${value} 円</td>`;
            // }).join('');

            row.innerHTML = `
                <td>${stock.code}</td>
                <td><a href="https://finance.yahoo.co.jp/quote/${stock.code}.T" target="_blank">${stock.name}</a></td>
                <td>${stock.price}</td>
                <td>${stock.change} (${stock.change_percent})</td>
                <td>${formatMarketCap(stock.market_cap)}</td>
                <td>${stock.per}</td>
                <td>${stock.pbr}</td>
                <td>${stock.yield}</td>
                <td><button class="delete-btn" data-code="${stock.code}">削除</button></td>
            `;
            stockTableBody.appendChild(row);
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
            if (!response.ok) throw new Error('Failed to add stock');
            stockCodeInput.value = '';
            await fetchAndDisplayStocks();
        } catch (error) {
            console.error('Error adding stock:', error);
            alert('銘柄の追加に失敗しました。');
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
                await fetchAndDisplayStocks();
            } catch (error) {
                console.error('Error deleting stock:', error);
                alert('銘柄の削除に失敗しました。');
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
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

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
            alert('CSVファイルのダウンロードに失敗しました。');
        }
    });

    // 初期表示
    addSortEventListeners();
    fetchAndDisplayStocks();
});