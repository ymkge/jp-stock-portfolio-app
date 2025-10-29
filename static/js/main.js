document.addEventListener('DOMContentLoaded', () => {
    const stockTableBody = document.querySelector('#stock-table tbody');
    const loadingIndicator = document.getElementById('loading-indicator');
    const addStockForm = document.getElementById('add-stock-form');
    const stockCodeInput = document.getElementById('stock-code-input');

    /**
     * データを取得してテーブルを更新する
     */
    async function fetchAndDisplayStocks() {
        showLoading(true);
        try {
            const response = await fetch('/api/stocks');
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const stocks = await response.json();
            renderStockTable(stocks);
        } catch (error) {
            console.error('Error fetching stocks:', error);
            stockTableBody.innerHTML = '<tr><td colspan="8" style="text-align:center; color: red;">データの読み込みに失敗しました。</td></tr>';
        } finally {
            showLoading(false);
        }
    }

    /**
     * 取得したデータでテーブルを描画する
     * @param {Array} stocks - 銘柄データの配列
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
                <td>${stock.market_cap}</td>
                <td>${stock.per}</td>
                <td>${stock.pbr}</td>
                <td>${stock.dividend_yield}</td>
                <td><button class="delete-btn" data-code="${stock.code}">削除</button></td>
            `;
            stockTableBody.appendChild(row);
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

    // 初期表示
    fetchAndDisplayStocks();
});