document.addEventListener('DOMContentLoaded', () => {
    // --- DOM要素の取得 ---
    const stockTableBody = document.querySelector('#stock-table tbody');
    const loadingIndicator = document.getElementById('loading-indicator');
    const addStockForm = document.getElementById('add-stock-form');
    const stockCodeInput = document.getElementById('stock-code-input');
    const tableHeaderRow = document.getElementById('table-header-row');
    const downloadCsvButton = document.getElementById('download-csv-button');
    const alertContainer = document.getElementById('alert-container');
    const selectAllStocksCheckbox = document.getElementById('select-all-stocks');
    const deleteSelectedStocksButton = document.getElementById('delete-selected-stocks-button');
    const recentStocksList = document.getElementById('recent-stocks-list');
    const filterInput = document.getElementById('filter-input');
    
    const modalOverlay = document.getElementById('modal-overlay');
    const managementForm = document.getElementById('management-form');
    const modalStockCode = document.getElementById('modal-stock-code');
    const isManagedCheckbox = document.getElementById('is-managed-checkbox');
    const managedFields = document.getElementById('managed-fields');
    const purchasePriceInput = document.getElementById('purchase-price-input');
    const quantityInput = document.getElementById('quantity-input');
    const modalCancelButton = document.getElementById('modal-cancel-button');

    let tableHeaders = document.querySelectorAll('#stock-table .sortable');

    // --- グローバル変数 ---
    let stocksData = [];
    let highlightRules = {};
    let currentSort = { key: 'code', order: 'asc' };

    // --- 初期化処理 ---
    async function initialize() {
        showLoading(true);
        try {
            const [stocks, rules, recent] = await Promise.all([
                fetch('/api/stocks').then(res => res.json()),
                fetch('/api/highlight-rules').then(res => res.json()),
                fetch('/api/recent-stocks').then(res => res.json())
            ]);
            stocksData = stocks;
            highlightRules = rules;
            renderRecentStocksList(recent);
            filterAndRender();
        } catch (error) {
            console.error('Initialization error:', error);
            showAlert('データの読み込みに失敗しました。', 'danger');
        } finally {
            showLoading(false);
        }
    }

    // --- レンダリング関連 ---

    function renderRecentStocksList(codes) {
        if (!recentStocksList) return;
        recentStocksList.innerHTML = codes.length ? '' : '<li>最近追加した銘柄はありません。</li>';
        codes.forEach(code => {
            const li = document.createElement('li');
            li.className = 'recent-stock-item';
            li.textContent = code;
            li.dataset.code = code;
            li.addEventListener('click', () => { stockCodeInput.value = code; });
            recentStocksList.appendChild(li);
        });
    }

    function filterAndRender() {
        const filterText = filterInput ? filterInput.value.toLowerCase() : '';
        let filteredStocks = stocksData;
        if (filterText) {
            filteredStocks = stocksData.filter(stock => 
                String(stock.code).toLowerCase().includes(filterText) || 
                String(stock.name || '').toLowerCase().includes(filterText)
            );
        }
        sortStocks(filteredStocks);
        renderStockTable(filteredStocks);
        updateSortHeaders();
        updateDeleteSelectedButtonState();
    }

    function renderStockTable(stocks) {
        stockTableBody.innerHTML = '';
        const colspan = tableHeaderRow.children.length;

        if (!stocks || stocks.length === 0) {
            stockTableBody.innerHTML = `<tr><td colspan="${colspan}" style="text-align:center;">登録されている銘柄はありません。</td></tr>`;
            return;
        }

        stocks.forEach(stock => {
            const row = stockTableBody.insertRow();
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

            if (stock.error) {
                row.className = 'error-row';
                row.title = stock.error;
                row.innerHTML = `<td colspan="1"><input type="checkbox" disabled></td>` +
                                `<td>${stock.code}</td>` +
                                `<td colspan="${colspan - 3}">銘柄が見つからないか、データの取得に失敗しました。</td>` +
                                `<td><button class="manage-btn" data-code="${stock.code}">管理</button></td>` +
                                `<td><button class="delete-btn" data-code="${stock.code}">削除</button></td>`;
                return;
            }
            
            createCell(`<input type="checkbox" class="stock-checkbox" data-code="${stock.code}">`);
            createTextCell(stock.code);
            createCell(`<a href="https://finance.yahoo.co.jp/quote/${stock.code}.T" target="_blank">${stock.name}</a>`);
            createTextCell(stock.industry || 'N/A');
            createCell(renderScoreAsStars(stock.score, stock.score_details));
            createTextCell(stock.price);
            createTextCell(`${stock.change} (${stock.change_percent === 'N/A' ? 'N/A' : stock.change_percent + '%'})`);
            
            // --- 保有銘柄の計算値を描画 ---
            createTextCell(formatNumber(stock.market_value), getProfitClass(stock.profit_loss));
            createTextCell(formatProfit(stock.profit_loss), getProfitClass(stock.profit_loss));
            createTextCell(stock.profit_loss_rate !== null && stock.profit_loss_rate !== undefined ? `${stock.profit_loss_rate.toFixed(2)}%` : 'N/A', getProfitClass(stock.profit_loss_rate));
            createTextCell(formatNumber(stock.estimated_annual_dividend));
            // --------------------------------

            createTextCell(formatMarketCap(stock.market_cap));
            createTextCell(stock.per, getHighlightClass('per', stock.per));
            createTextCell(stock.pbr, getHighlightClass('pbr', stock.pbr));
            createTextCell(stock.roe === 'N/A' ? 'N/A' : stock.roe + '%', getHighlightClass('roe', stock.roe));
            createTextCell(stock.eps === 'N/A' ? 'N/A' : stock.eps + '円');
            createTextCell(stock.yield === 'N/A' ? 'N/A' : stock.yield + '%', getHighlightClass('yield', stock.yield));
            
            const dividendCell = createCell('');
            dividendCell.title = formatDividendHistory(stock.dividend_history);
            dividendCell.innerHTML = `<a href="https://finance.yahoo.co.jp/quote/${stock.code}.T/dividend" target="_blank" class="dividend-link">
                ${stock.consecutive_increase_years > 0 ? `<span class="increase-badge">${stock.consecutive_increase_years}年連続</span>` : '-'}
            </a>`;

            createCell(`<button class="manage-btn" data-code="${stock.code}">管理</button>`);
            createCell(`<button class="delete-btn" data-code="${stock.code}">削除</button>`);
        });
    }

    // --- ヘルパー関数 ---

    const formatNumber = (num, fractionDigits = 0) => {
        if (num === null || num === undefined) return 'N/A';
        return num.toLocaleString(undefined, { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits });
    };

    const formatProfit = (num) => {
        if (num === null || num === undefined) return 'N/A';
        const sign = num > 0 ? '+' : '';
        return sign + formatNumber(num);
    };

    const getProfitClass = (num) => {
        if (num === null || num === undefined) return '';
        if (num > 0) return 'text-plus';
        if (num < 0) return 'text-minus';
        return '';
    };

    function showAlert(message, type = 'danger') {
        const alert = document.createElement('div');
        alert.className = `alert alert-${type}`;
        alert.textContent = message;
        alertContainer.appendChild(alert);
        requestAnimationFrame(() => alert.classList.add('show'));
        setTimeout(() => {
            alert.classList.remove('show');
            alert.classList.add('hide');
            alert.addEventListener('transitionend', () => alert.remove());
        }, 5000);
    }

    function sortStocks(data) {
        data.sort((a, b) => {
            let valA = a[currentSort.key];
            let valB = b[currentSort.key];
            const parseValue = (v) => {
                if (v === undefined || v === null || v === 'N/A' || v === '--' || v === '') return -Infinity;
                if (typeof v === 'string') {
                    const num = parseFloat(v.replace(/,/g, '').replace(/%|倍|円/g, ''));
                    return isNaN(num) ? v : num;
                }
                return v;
            };
            const parsedA = parseValue(valA);
            const parsedB = parseValue(valB);
            if (typeof parsedA === 'number' && typeof parsedB === 'number') {
                return currentSort.order === 'asc' ? parsedA - parsedB : parsedB - parsedA;
            }
            return currentSort.order === 'asc' ? String(parsedA).localeCompare(String(parsedB)) : String(parsedB).localeCompare(String(parsedA));
        });
    }

    function updateSortHeaders() {
        tableHeaders.forEach(header => {
            header.classList.remove('sort-active', 'sort-asc', 'sort-desc');
            if (header.dataset.key === currentSort.key) {
                header.classList.add('sort-active', `sort-${currentSort.order}`);
            }
        });
    }

    function showLoading(isLoading) {
        loadingIndicator.style.display = isLoading ? 'block' : 'none';
        stockTableBody.style.display = isLoading ? 'none' : '';
    }

    function updateDeleteSelectedButtonState() {
        const checkedCount = document.querySelectorAll('.stock-checkbox:checked').length;
        deleteSelectedStocksButton.disabled = checkedCount === 0;
    }
    
    function formatMarketCap(value) {
        if (value === 'N/A' || value === null || value === undefined || value === '--') return 'N/A';
        const num = typeof value === 'string' ? parseFloat(value.replace(/,/g, '')) : value;
        if (isNaN(num)) return 'N/A';
        const trillion = 1_000_000_000_000, oku = 100_000_000, million = 1_000_000;
        if (num >= trillion) return `${(num / trillion).toFixed(2)}兆円`;
        if (num >= oku) return `${(num / oku).toFixed(2)}億円`;
        return `${(num / million).toLocaleString()}百万円`;
    }

    function formatDividendHistory(history) {
        if (!history || Object.keys(history).length === 0) return 'N/A';
        return Object.keys(history).sort((a, b) => b - a).map(year => `${year}年: ${history[year]}円`).join(' | ');
    }

    function renderScoreAsStars(score, details) {
        if (score === -1) return `<span class="score-na" title="評価指標なし">N/A</span>`;
        if (score === undefined || score === null) return 'N/A';
        const maxScore = 10;
        let stars = '★'.repeat(Math.min(score, 5)) + '☆'.repeat(5 - Math.min(score, 5));
        stars += '<br>' + '★'.repeat(Math.max(0, score - 5)) + '☆'.repeat(5 - Math.max(0, score - 5));
        const tooltip = `合計: ${score}/${maxScore} (PER: ${details.per||0}/2, PBR: ${details.pbr||0}/2, ROE: ${details.roe||0}/2, 利回り: ${details.yield||0}/2, 連続増配: ${details.consecutive_increase||0}/2)`;
        return `<span class="score" title="${tooltip}">${stars}</span>`;
    }

    // --- モーダル関連の関数 ---

    function openManagementModal(code) {
        const stock = stocksData.find(s => s.code === code);
        if (!stock) return;

        modalStockCode.value = code;
        document.getElementById('modal-title').textContent = `保有情報管理 (${stock.code} ${stock.name})`;
        isManagedCheckbox.checked = stock.is_managed;
        purchasePriceInput.value = stock.purchase_price || '';
        quantityInput.value = stock.quantity || '';
        
        managedFields.classList.toggle('hidden', !stock.is_managed);
        modalOverlay.classList.remove('hidden');
    }

    function closeManagementModal() {
        modalOverlay.classList.add('hidden');
    }

    async function handleManagementFormSubmit(event) {
        event.preventDefault();
        const code = modalStockCode.value;
        const is_managed = isManagedCheckbox.checked;
        const purchase_price = purchasePriceInput.value ? parseFloat(purchasePriceInput.value) : null;
        const quantity = quantityInput.value ? parseInt(quantityInput.value, 10) : null;

        if (is_managed && (purchase_price === null || quantity === null || purchase_price <= 0 || quantity <= 0)) {
            showAlert('管理対象にする場合は、0より大きい取得単価と数量を入力してください。', 'warning');
            return;
        }

        try {
            const response = await fetch(`/api/stocks/${code}/management`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_managed, purchase_price, quantity }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '更新に失敗しました。');
            }

            showAlert(`銘柄 ${code} の保有情報を更新しました。`, 'success');
            closeManagementModal();
            await initialize();
        } catch (error) {
            console.error('Error updating stock management:', error);
            showAlert(error.message, 'danger');
        }
    }

    // --- イベントリスナー ---

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
                await initialize();
            } else {
                showAlert(data.message, data.status === 'exists' ? 'warning' : 'danger');
            }
            stockCodeInput.value = '';
        } catch (error) {
            showAlert('銘柄の追加中にエラーが発生しました。', 'danger');
        }
    });

    stockTableBody.addEventListener('click', async (event) => {
        const target = event.target;
        if (target.classList.contains('delete-btn')) {
            const code = target.dataset.code;
            if (!confirm(`銘柄コード ${code} を削除しますか？`)) return;
            try {
                await fetch(`/api/stocks/${code}`, { method: 'DELETE' });
                showAlert(`銘柄 ${code} を削除しました。`, 'success');
                await initialize();
            } catch (error) {
                showAlert('銘柄の削除に失敗しました。', 'danger');
            }
        } else if (target.classList.contains('manage-btn')) {
            openManagementModal(target.dataset.code);
        }
    });

    tableHeaders.forEach(header => {
        header.addEventListener('click', () => {
            const key = header.dataset.key;
            if (currentSort.key === key) {
                currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc';
            } else {
                currentSort.key = key;
                currentSort.order = 'asc';
            }
            filterAndRender();
        });
    });

    downloadCsvButton.addEventListener('click', () => { window.location.href = '/api/stocks/csv'; });
    filterInput.addEventListener('input', filterAndRender);
    
    selectAllStocksCheckbox.addEventListener('change', () => {
        document.querySelectorAll('.stock-checkbox:not(:disabled)').forEach(cb => { cb.checked = selectAllStocksCheckbox.checked; });
        updateDeleteSelectedButtonState();
    });
    stockTableBody.addEventListener('change', (event) => {
        if (event.target.classList.contains('stock-checkbox')) {
            const allCheckboxes = document.querySelectorAll('.stock-checkbox:not(:disabled)');
            const checkedCount = document.querySelectorAll('.stock-checkbox:checked:not(:disabled)').length;
            selectAllStocksCheckbox.checked = allCheckboxes.length > 0 && allCheckboxes.length === checkedCount;
            updateDeleteSelectedButtonState();
        }
    });
    deleteSelectedStocksButton.addEventListener('click', async () => {
        const codesToDelete = Array.from(document.querySelectorAll('.stock-checkbox:checked')).map(cb => cb.dataset.code);
        if (codesToDelete.length === 0 || !confirm(`選択された ${codesToDelete.length} 件の銘柄を削除しますか？`)) return;
        try {
            await fetch('/api/stocks/bulk-delete', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ codes: codesToDelete }),
            });
            showAlert(`${codesToDelete.length} 件の銘柄を削除しました。`, 'success');
            await initialize();
        } catch (error) {
            showAlert('一括削除に失敗しました。', 'danger');
        }
    });

    managementForm.addEventListener('submit', handleManagementFormSubmit);
    modalCancelButton.addEventListener('click', closeManagementModal);
    modalOverlay.addEventListener('click', (event) => {
        if (event.target === modalOverlay) closeManagementModal();
    });
    isManagedCheckbox.addEventListener('change', () => {
        managedFields.classList.toggle('hidden', !isManagedCheckbox.checked);
    });

    // --- 初期実行 ---
    initialize();
});