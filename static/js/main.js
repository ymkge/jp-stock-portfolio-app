document.addEventListener('DOMContentLoaded', () => {
    const stockTableBody = document.querySelector('#stock-table tbody');
    const loadingIndicator = document.getElementById('loading-indicator');
    const addStockForm = document.getElementById('add-stock-form');
    const stockCodeInput = document.getElementById('stock-code-input');
    const tableHeaderRow = document.getElementById('table-header-row');
    const downloadCsvButton = document.getElementById('download-csv-button');
    
    let tableHeaders = document.querySelectorAll('#stock-table .sortable');

    let stocksData = [];
    let highlightRules = {}; // ハイライトルールを保持

    let currentSort = {
        key: 'code',
        order: 'asc'
    };

    /**
     * ページの初期化処理
     */
    async function initialize() {
        showLoading(true);
        try {
            // 株価データとハイライトルールを並行して取得
            const [stocksResponse, rulesResponse] = await Promise.all([
                fetch('/api/stocks'),
                fetch('/api/highlight-rules')
            ]);

            if (!stocksResponse.ok) throw new Error(`Failed to fetch stocks: ${stocksResponse.status}`);
            if (!rulesResponse.ok) throw new Error(`Failed to fetch highlight rules: ${rulesResponse.status}`);

            stocksData = await stocksResponse.json();
            highlightRules = await rulesResponse.json();

            sortAndRender(); // ソートして描画
        } catch (error) {
            console.error('Initialization error:', error);
            const colspan = tableHeaderRow.children.length || 10;
            stockTableBody.innerHTML = `<tr><td colspan="${colspan}" style="text-align:center; color: red;">データの読み込みに失敗しました。</td></tr>`;
        } finally {
            showLoading(false);
        }
    }

    /**
     * 指標の値に基づいてハイライト用のCSSクラスを返す
     * @param {string} key - 指標のキー (per, pbr, roe, yield)
     * @param {string|number} value - 指標の値
     * @returns {string} - CSSクラス名 ('undervalued', 'overvalued', or '')
     */
    function getHighlightClass(key, value) {
        const rules = highlightRules[key];
        if (!rules || value === 'N/A' || value === null || value === undefined || value === '--') {
            return '';
        }

        const numericValue = parseFloat(String(value).replace(/[^0-9.-]/g, ''));
        if (isNaN(numericValue)) {
            return '';
        }

        // 高い方が良い指標 (yield, roe)
        if (key === 'yield' || key === 'roe') {
            if (rules.undervalued !== undefined && numericValue >= rules.undervalued) {
                return 'undervalued';
            }
        } 
        // 低い方が良い指標 (per, pbr)
        else {
            if (rules.undervalued !== undefined && numericValue <= rules.undervalued) {
                return 'undervalued';
            }
            if (rules.overvalued !== undefined && numericValue >= rules.overvalued) {
                return 'overvalued';
            }
        }

        return '';
    }

    /**
     * スコアを星で描画する (最大8点)
     * @param {number} score - スコア
     * @returns {string} - 星のHTML文字列
     */
    function renderScoreAsStars(score) {
        if (score === undefined || score === null) {
            return 'N/A';
        }
        const maxScore = 8;
        const filledStars = '★'.repeat(score);
        const emptyStars = '☆'.repeat(maxScore - score);
        return `<span class="score" title="${score}/${maxScore}">${filledStars}${emptyStars}</span>`;
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
            valA = a[currentSort.key];
            valB = b[currentSort.key];

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
            row.innerHTML = `
                <td>${stock.code}</td>
                <td><a href="https://finance.yahoo.co.jp/quote/${stock.code}.T" target="_blank">${stock.name}</a></td>
                <td>${renderScoreAsStars(stock.score)}</td>
                <td>${stock.price}</td>
                <td>${stock.change} (${stock.change_percent === 'N/A' ? 'N/A' : stock.change_percent + '%'})</td>
                <td>${formatMarketCap(stock.market_cap)}</td>
                <td class="${getHighlightClass('per', stock.per)}">${stock.per}</td>
                <td class="${getHighlightClass('pbr', stock.pbr)}">${stock.pbr}</td>
                <td class="${getHighlightClass('roe', stock.roe)}">${stock.roe === 'N/A' ? 'N/A' : stock.roe + '%'}</td>
                <td>${stock.eps === 'N/A' ? 'N/A' : stock.eps + '円'}</td>
                <td class="${getHighlightClass('yield', stock.yield)}">${stock.yield === 'N/A' ? 'N/A' : stock.yield + '%'}</td>
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
            await initialize();
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
                await initialize();
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
    initialize();
});