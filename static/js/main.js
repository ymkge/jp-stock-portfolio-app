document.addEventListener('DOMContentLoaded', () => {
    const stockTableBody = document.querySelector('#stock-table tbody');
    const loadingIndicator = document.getElementById('loading-indicator');
    const addStockForm = document.getElementById('add-stock-form');
    const stockCodeInput = document.getElementById('stock-code-input');
    const tableHeaders = document.querySelectorAll('#stock-table .sortable');

    let stocksData = []; // APIから取得した生のデータを保持
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
            sortAndRender(); // 取得したデータをソートして描画
        } catch (error) {
            console.error('Error fetching stocks:', error);
            stockTableBody.innerHTML = '<tr><td colspan="8" style="text-align:center; color: red;">データの読み込みに失敗しました。</td></tr>';
        } finally {
            showLoading(false);
        }
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
            const valA = a[currentSort.key];
            const valB = b[currentSort.key];

            // 汎用的な値のパース関数
            const parseValue = (value) => {
                if (typeof value === 'string') {
                    // "N/A" や "--" のような非数値は比較のために null を返す
                    if (value === 'N/A' || value === '--' || value === '') return null;
                    // 数値の前に余計な文字があってもパースできるようにする
                    const cleanedValue = value.replace(/,/g, '').replace(/%/, '').replace(/倍/, '').replace(/円/, '');
                    const num = parseFloat(cleanedValue);
                    return isNaN(num) ? value : num;
                }
                return value;
            };

            const parsedA = parseValue(valA);
            const parsedB = parseValue(valB);

            // null（非数値）のハンドリング: nullは常に末尾に
            if (parsedA === null && parsedB !== null) return 1;
            if (parsedA !== null && parsedB === null) return -1;
            if (parsedA === null && parsedB === null) return 0;

            // 数値と文字列の比較
            if (typeof parsedA === 'number' && typeof parsedB === 'number') {
                return currentSort.order === 'asc' ? parsedA - parsedB : parsedB - parsedA;
            } else {
                // 文字列比較
                return currentSort.order === 'asc'
                    ? String(parsedA).localeCompare(String(parsedB))
                    : String(parsedB).localeCompare(String(parsedA));
            }
        });
    }


    /**
     * 数値を兆、億、百万円単位にフォーマットする
     * @param {string | number} value - カンマ区切りの数値文字列または数値
     * @returns {string} フォーマットされた文字列
     */
    function formatMarketCap(value) {
        if (value === 'N/A' || value === null || value === undefined || value === '--') {
            return 'N/A';
        }

        // カンマを削除して数値に変換
        const num = typeof value === 'string' ? parseFloat(value.replace(/,/g, '')) : value;

        if (isNaN(num)) {
            return 'N/A';
        }

        const trillion = 1_000_000_000_000;
        const billion = 1_000_000_000;
        const million = 1_000_000;

        if (num >= trillion) {
            return `${(num / trillion).toFixed(2)} 兆円`;
        }
        if (num >= billion) {
            // 1兆円未満は億円単位
            return `${(num / billion).toFixed(2)} 億円`;
        }
        if (num >= million) {
            // 1億円未満は百万円単位
            return `${Math.round(num / million)} 百万円`;
        }
        // 100万円未満
        return `${num.toLocaleString()} 円`;
    }


    /**
     * 取得したデータでテーブルを描画する
     * @param {Array} stocks - ソート済みの銘柄データの配列
     */
    function renderStockTable(stocks) {
        stockTableBody.innerHTML = ''; // テーブルをクリア

        if (!stocks || stocks.length === 0) {
            stockTableBody.innerHTML = '<tr><td colspan="8" style="text-align:center;">登録されている銘柄はありません。</td></tr>';
            return;
        }

        stocks.forEach(stock => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${stock.code}</td>
                <td>${stock.name}</td>
                <td>${stock.price}</td>
                <td>${formatMarketCap(stock.market_cap)}</td>
                <td>${stock.per}</td>
                <td>${stock.pbr}</td>
                <td>${stock.dividend_yield}</td>
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
     * @param {boolean} isLoading
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
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ code: code }),
            });

            if (!response.ok) {
                throw new Error('Failed to add stock');
            }

            stockCodeInput.value = ''; // 入力欄をクリア
            await fetchAndDisplayStocks(); // テーブルを再描画
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
            if (!confirm(`銘柄コード ${code} を削除しますか？`)) {
                return;
            }

            try {
                const response = await fetch(`/api/stocks/${code}`, {
                    method: 'DELETE',
                });

                if (!response.ok) {
                    throw new Error('Failed to delete stock');
                }

                await fetchAndDisplayStocks(); // テーブルを再描画
            } catch (error) {
                console.error('Error deleting stock:', error);
                alert('銘柄の削除に失敗しました。');
            }
        }
    });

    /**
     * テーブルヘッダーのクリックイベント（ソート処理）
     */
    tableHeaders.forEach(header => {
        header.addEventListener('click', () => {
            const key = header.dataset.key;
            if (currentSort.key === key) {
                // 同じキーなら昇順/降順を切り替え
                currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc';
            } else {
                // 新しいキーならデフォルトで昇順
                currentSort.key = key;
                currentSort.order = 'asc';
            }
            sortAndRender();
        });
    });

    // 初期表示
    fetchAndDisplayStocks();
});
