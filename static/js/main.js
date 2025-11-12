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
    
    // --- モーダル関連DOM要素 ---
    const modalOverlay = document.getElementById('modal-overlay');
    const modalTitle = document.getElementById('modal-title');
    const holdingsListContainer = document.getElementById('holdings-list-container');
    const addNewHoldingBtn = document.getElementById('add-new-holding-btn');
    const holdingFormContainer = document.getElementById('holding-form-container');
    const holdingForm = document.getElementById('holding-form');
    const holdingFormTitle = document.getElementById('holding-form-title');
    const holdingIdInput = document.getElementById('holding-id-input');
    const accountTypeSelect = document.getElementById('account-type-select');
    const purchasePriceInput = document.getElementById('purchase-price-input');
    const quantityInput = document.getElementById('quantity-input');
    const holdingFormCancelBtn = document.getElementById('holding-form-cancel-btn');
    const modalCloseBtn = document.getElementById('modal-close-btn');

    let tableHeaders = document.querySelectorAll('#stock-table .sortable');

    // --- グローバル変数 ---
    let stocksData = [];
    let accountTypes = [];
    let highlightRules = {};
    let currentSort = { key: 'code', order: 'asc' };
    let currentManagingCode = null;

    // --- 初期化処理 ---
    async function initialize() {
        showLoading(true);
        try {
            const [stocks, rules, recent, accTypes] = await Promise.all([
                fetch('/api/stocks').then(res => res.json()),
                fetch('/api/highlight-rules').then(res => res.json()),
                fetch('/api/recent-stocks').then(res => res.json()),
                fetch('/api/account-types').then(res => res.json())
            ]);
            stocksData = stocks;
            highlightRules = rules;
            accountTypes = accTypes;
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
                row.innerHTML = `<td><input type="checkbox" disabled></td>` +
                                `<td>${stock.code || 'N/A'}</td>` +
                                `<td colspan="${colspan - 3}">銘柄が見つからないか、データの取得に失敗しました。</td>` +
                                `<td><button class="manage-btn" data-code="${stock.code || ''}" disabled>管理</button></td>`;
                return;
            }
            
            createCell(`<input type="checkbox" class="stock-checkbox" data-code="${stock.code}">`);
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
            const dividendCell = createCell('');
            dividendCell.title = formatDividendHistory(stock.dividend_history);
            dividendCell.innerHTML = `<a href="https://finance.yahoo.co.jp/quote/${stock.code}.T/dividend" target="_blank" class="dividend-link">
                ${stock.consecutive_increase_years > 0 ? `<span class="increase-badge">${stock.consecutive_increase_years}年連続</span>` : '-'}
            </a>`;
            createCell(`<button class="manage-btn" data-code="${stock.code}">管理</button>`);
        });
    }

    // --- ヘルパー関数 ---
    const formatNumber = (num, fractionDigits = 0) => (num === null || num === undefined) ? 'N/A' : num.toLocaleString(undefined, { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits });
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
            let valA = a[currentSort.key], valB = b[currentSort.key];
            const parseValue = (v) => {
                if (v === undefined || v === null || v === 'N/A' || v === '--' || v === '') return -Infinity;
                if (typeof v === 'string') {
                    const num = parseFloat(v.replace(/,/g, '').replace(/%|倍|円/g, ''));
                    return isNaN(num) ? v : num;
                }
                return v;
            };
            const parsedA = parseValue(valA), parsedB = parseValue(valB);
            if (typeof parsedA === 'number' && typeof parsedB === 'number') return currentSort.order === 'asc' ? parsedA - parsedB : parsedB - parsedA;
            return currentSort.order === 'asc' ? String(parsedA).localeCompare(String(parsedB)) : String(parsedB).localeCompare(String(parsedA));
        });
    }
    function updateSortHeaders() {
        tableHeaders.forEach(header => {
            header.classList.remove('sort-active', 'sort-asc', 'sort-desc');
            if (header.dataset.key === currentSort.key) header.classList.add('sort-active', `sort-${currentSort.order}`);
        });
    }
    function showLoading(isLoading) {
        loadingIndicator.style.display = isLoading ? 'block' : 'none';
        stockTableBody.style.display = isLoading ? 'none' : '';
    }
    function updateDeleteSelectedButtonState() {
        deleteSelectedStocksButton.disabled = document.querySelectorAll('.stock-checkbox:checked').length === 0;
    }
    function formatMarketCap(value) {
        if (value === 'N/A' || value === null || value === undefined || value === '--') return 'N/A';
        const num = typeof value === 'string' ? parseFloat(value.replace(/,/g, '')) : value;
        if (isNaN(num)) return 'N/A';
        const trillion = 1e12, oku = 1e8, million = 1e6;
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
        let stars = '★'.repeat(Math.min(score, 5)) + '☆'.repeat(5 - Math.min(score, 5));
        stars += '<br>' + '★'.repeat(Math.max(0, score - 5)) + '☆'.repeat(5 - Math.max(0, score - 5));
        const tooltip = `合計: ${score}/10 (PER: ${details.per||0}/2, PBR: ${details.pbr||0}/2, ROE: ${details.roe||0}/2, 利回り: ${details.yield||0}/2, 連続増配: ${details.consecutive_increase||0}/2)`;
        return `<span class="score" title="${tooltip}">${stars}</span>`;
    }
    function getHighlightClass(key, value) {
        const rules = highlightRules[key];
        if (!rules || value === 'N/A' || value === null || value === undefined || value === '--') return '';
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
    function renderRecentStocksList(codes) {
        if (!recentStocksList) return;
        recentStocksList.innerHTML = codes.length ? '' : '<li>最近追加した銘柄はありません。</li>';
        codes.forEach(code => {
            const li = document.createElement('li');
            li.className = 'recent-stock-item';
            li.textContent = code;
            li.addEventListener('click', () => { stockCodeInput.value = code; });
            recentStocksList.appendChild(li);
        });
    }

    // --- 新しいモーダル関連の関数 ---
    function openManagementModal(code) {
        currentManagingCode = code;
        const stock = stocksData.find(s => s.code === code);
        if (!stock) return;
        modalTitle.textContent = `保有情報管理 (${stock.code} ${stock.name})`;
        renderHoldingsList(stock.holdings);
        hideHoldingForm();
        modalOverlay.classList.remove('hidden');
    }

    function renderHoldingsList(holdings) {
        holdingsListContainer.innerHTML = '';
        if (!holdings || holdings.length === 0) {
            holdingsListContainer.innerHTML = '<p>この銘柄の保有情報はありません。</p>';
            return;
        }
        holdings.forEach(h => {
            const item = document.createElement('div');
            item.className = 'holding-item';
            item.innerHTML = `
                <div class="holding-info">
                    <span class="account-type">${h.account_type}</span>
                    <span>取得単価: ${formatNumber(h.purchase_price, 2)}円</span>
                    <span>数量: ${formatNumber(h.quantity)}株</span>
                </div>
                <div class="holding-actions">
                    <button class="btn-sm btn-edit" data-holding-id="${h.id}">編集</button>
                    <button class="btn-sm btn-delete-holding" data-holding-id="${h.id}">削除</button>
                </div>
            `;
            holdingsListContainer.appendChild(item);
        });
    }

    function showHoldingForm(holding = null) {
        holdingForm.reset();
        accountTypeSelect.innerHTML = accountTypes.map(t => `<option value="${t}">${t}</option>`).join('');
        if (holding) { // 編集モード
            holdingFormTitle.textContent = '保有情報の編集';
            holdingIdInput.value = holding.id;
            accountTypeSelect.value = holding.account_type;
            purchasePriceInput.value = holding.purchase_price;
            quantityInput.value = holding.quantity;
        } else { // 新規追加モード
            holdingFormTitle.textContent = '保有情報の新規追加';
            holdingIdInput.value = '';
        }
        holdingFormContainer.classList.remove('hidden');
    }

    function hideHoldingForm() {
        holdingFormContainer.classList.add('hidden');
    }

    async function handleHoldingFormSubmit(event) {
        event.preventDefault();
        const holdingId = holdingIdInput.value;
        const data = {
            account_type: accountTypeSelect.value,
            purchase_price: parseFloat(purchasePriceInput.value),
            quantity: parseInt(quantityInput.value, 10)
        };

        const url = holdingId ? `/api/holdings/${holdingId}` : `/api/stocks/${currentManagingCode}/holdings`;
        const method = holdingId ? 'PUT' : 'POST';

        try {
            const response = await fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '保存に失敗しました。');
            }
            showAlert('保有情報を保存しました。', 'success');
            // initialize() の代わりに部分更新
            const updatedStockData = await fetch(`/api/stocks/${currentManagingCode}`).then(res => res.json());
            if (updatedStockData && !updatedStockData.error) {
                const index = stocksData.findIndex(s => s.code === currentManagingCode);
                if (index !== -1) {
                    stocksData[index] = updatedStockData; // stocksData を更新
                }
                renderHoldingsList(updatedStockData.holdings); // モーダル内の保有リストを更新
                filterAndRender(); // メインテーブルを再描画
            } else {
                showAlert('更新された銘柄のデータ取得に失敗しました。', 'danger');
                await initialize(); // フォールバックとして全更新
            }
            hideHoldingForm();
        } catch (error) {
            showAlert(error.message, 'danger');
        }
    }

    async function handleHoldingDelete(holdingId) {
        if (!confirm('この保有情報を削除しますか？')) return;
        try {
            const response = await fetch(`/api/holdings/${holdingId}`, { method: 'DELETE' });
            if (!response.ok) throw new Error('削除に失敗しました。');
            showAlert('保有情報を削除しました。', 'success');
            // initialize() の代わりに部分更新
            const updatedStockData = await fetch(`/api/stocks/${currentManagingCode}`).then(res => res.json());
            if (updatedStockData && !updatedStockData.error) {
                const index = stocksData.findIndex(s => s.code === currentManagingCode);
                if (index !== -1) {
                    stocksData[index] = updatedStockData; // stocksData を更新
                }
                renderHoldingsList(updatedStockData.holdings); // モーダル内の保有リストを更新
                filterAndRender(); // メインテーブルを再描画
            } else {
                showAlert('更新された銘柄のデータ取得に失敗しました。', 'danger');
                await initialize(); // フォールバックとして全更新
            }
        } catch (error) {
            showAlert(error.message, 'danger');
        }
    }

    function closeModal() {
        modalOverlay.classList.add('hidden');
        currentManagingCode = null;
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
                body: JSON.stringify({ code }),
            });
            const data = await response.json();
            showAlert(data.message, data.status === 'success' ? 'success' : (data.status === 'exists' ? 'warning' : 'danger'));
            if (data.status === 'success') {
                // initialize() の代わりに部分更新
                // 新しく追加された銘柄のデータを取得
                const newStockResponse = await fetch(`/api/stocks/${code}`);
                const newStockData = await newStockResponse.json();

                if (newStockResponse.ok && !newStockData.error) {
                    stocksData.push(newStockData); // stocksData に追加
                    // recentStocks も更新
                    const recent = await fetch('/api/recent-stocks').then(res => res.json());
                    renderRecentStocksList(recent);
                    filterAndRender(); // テーブルを再描画
                } else {
                    // エラーの場合は、念のためinitialize()を呼び出すか、エラー表示を強化
                    showAlert('追加された銘柄のデータ取得に失敗しました。', 'danger');
                    await initialize(); // フォールバックとして全更新
                }
            }
            stockCodeInput.value = '';
        } catch (error) {
            showAlert('銘柄の追加中にエラーが発生しました。', 'danger');
        }
    });

    stockTableBody.addEventListener('click', (event) => {
        if (event.target.classList.contains('manage-btn')) {
            openManagementModal(event.target.dataset.code);
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
            const all = document.querySelectorAll('.stock-checkbox:not(:disabled)');
            const checked = document.querySelectorAll('.stock-checkbox:checked:not(:disabled)');
            selectAllStocksCheckbox.checked = all.length > 0 && all.length === checked.length;
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
            // initialize() の代わりに部分更新
            stocksData = stocksData.filter(stock => !codesToDelete.includes(stock.code)); // stocksData から削除
            filterAndRender(); // テーブルを再描画
            selectAllStocksCheckbox.checked = false; // 全選択チェックボックスを解除
            updateDeleteSelectedButtonState(); // 削除ボタンの状態を更新
        } catch (error) {
            showAlert(error.message, 'danger');
        }
    });

    // 新しいモーダルのイベントリスナー
    addNewHoldingBtn.addEventListener('click', () => showHoldingForm());
    holdingForm.addEventListener('submit', handleHoldingFormSubmit);
    holdingFormCancelBtn.addEventListener('click', hideHoldingForm);
    holdingsListContainer.addEventListener('click', (event) => {
        const target = event.target;
        if (target.classList.contains('btn-edit')) {
            const holdingId = target.dataset.holdingId;
            const stock = stocksData.find(s => s.code === currentManagingCode);
            const holding = stock.holdings.find(h => h.id === holdingId);
            showHoldingForm(holding);
        } else if (target.classList.contains('btn-delete-holding')) {
            handleHoldingDelete(target.dataset.holdingId);
        }
    });
    modalCloseBtn.addEventListener('click', closeModal);
    modalOverlay.addEventListener('click', (event) => {
        if (event.target === modalOverlay) closeModal();
    });

    // --- 初期実行 ---
    initialize();
});
