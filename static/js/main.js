document.addEventListener('DOMContentLoaded', () => {
    // --- DOM要素の取得 ---
    const loadingIndicator = document.getElementById('loading-indicator');
    const addAssetForm = document.getElementById('add-asset-form');
    const assetCodeInput = document.getElementById('asset-code-input');
    const downloadCsvButton = document.getElementById('download-csv-button');
    const refreshAllButton = document.getElementById('refresh-all-button');
    const alertContainer = document.getElementById('alert-container');
    const deleteSelectedStocksButton = document.getElementById('delete-selected-stocks-button');
    const recentStocksList = document.getElementById('recent-stocks-list');
    const filterInput = document.getElementById('filter-input');
    const tabNav = document.querySelector('.tab-nav');

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

    // --- グローバル変数 ---
    let allAssetsData = [];
    let accountTypes = [];
    let highlightRules = {};
    let currentSort = { key: 'code', order: 'asc' };
    let currentManagingCode = null;
    let activeTab = 'jp_stock';
    const COOLDOWN_MINUTES = 10;
    const COOLDOWN_STORAGE_KEY = 'fullUpdateCooldownEnd';
    const ASSETS_STORAGE_KEY = 'jpStockPortfolioAssets';
    let cooldownInterval;

    // --- 初期化処理 ---
    async function initialize() {
        showLoading(true);
        try {
            const stocksResponse = await fetch('/api/stocks');
            if (!stocksResponse.ok) {
                let errorDetail = 'Failed to fetch stocks';
                try {
                    const errorData = await stocksResponse.json();
                    errorDetail = errorData.detail || errorDetail;
                } catch (e) {
                    errorDetail = stocksResponse.statusText;
                }
                const error = new Error(errorDetail);
                error.status = stocksResponse.status;
                throw error;
            }
            const assets = await stocksResponse.json();

            const [rules, recent, accTypes] = await Promise.all([
                fetch('/api/highlight-rules').then(res => res.json()),
                fetch('/api/recent-stocks').then(res => res.json()),
                fetch('/api/account-types').then(res => res.json())
            ]);
            
            allAssetsData = assets;
            highlightRules = rules;
            accountTypes = accTypes;
            
            saveAssetsToStorage();
            renderRecentStocksList(recent);
            filterAndRender();
            return true; // Success
        } catch (error) {
            console.error('Initialization error:', error);
            if (error.status === 429) {
                showAlert('クールダウン中です。表示されているのは前回のデータです。', 'info');
                const cooldownEndInStorage = localStorage.getItem(COOLDOWN_STORAGE_KEY);
                if (!cooldownEndInStorage || Date.now() > parseInt(cooldownEndInStorage)) {
                    const newCooldownEnd = Date.now() + COOLDOWN_MINUTES * 60 * 1000;
                    localStorage.setItem(COOLDOWN_STORAGE_KEY, newCooldownEnd);
                    startCooldownTimer(newCooldownEnd);
                }
            } else {
                showAlert(`データ更新に失敗しました。表示されているのは古いデータかもしれません。(${error.message})`, 'warning');
                if (cooldownInterval) clearInterval(cooldownInterval);
                refreshAllButton.disabled = false;
                refreshAllButton.textContent = '全件更新';
                localStorage.removeItem(COOLDOWN_STORAGE_KEY);
            }
            return false; // Failure
        } finally {
            showLoading(false);
        }
    }

    // --- ストレージ関連 ---
    function saveAssetsToStorage() {
        localStorage.setItem(ASSETS_STORAGE_KEY, JSON.stringify(allAssetsData));
    }

    function loadAssetsFromStorage() {
        const storedAssets = localStorage.getItem(ASSETS_STORAGE_KEY);
        if (storedAssets) {
            allAssetsData = JSON.parse(storedAssets);
            filterAndRender();
        }
    }

    // --- クールダウン関連 ---
    function startCooldownTimer(endTime) {
        if (cooldownInterval) clearInterval(cooldownInterval);
        refreshAllButton.disabled = true;

        const updateTimer = () => {
            const now = Date.now();
            const remaining = endTime - now;

            if (remaining <= 0) {
                clearInterval(cooldownInterval);
                refreshAllButton.disabled = false;
                refreshAllButton.textContent = '全件更新';
                localStorage.removeItem(COOLDOWN_STORAGE_KEY);
            } else {
                const minutes = Math.floor((remaining / 1000 / 60) % 60);
                const seconds = Math.floor((remaining / 1000) % 60);
                refreshAllButton.textContent = `あと ${minutes}:${seconds.toString().padStart(2, '0')}`;
            }
        };

        updateTimer();
        cooldownInterval = setInterval(updateTimer, 1000);
    }

    function checkInitialCooldown() {
        const cooldownEnd = localStorage.getItem(COOLDOWN_STORAGE_KEY);
        if (cooldownEnd && Date.now() < parseInt(cooldownEnd)) {
            startCooldownTimer(parseInt(cooldownEnd));
        }
    }

    // --- レンダリング関連 ---
    function filterAndRender() {
        const filterText = filterInput.value.toLowerCase();
        let filteredAssets = allAssetsData.filter(asset => asset.asset_type === activeTab);

        if (filterText) {
            filteredAssets = filteredAssets.filter(asset =>
                String(asset.code).toLowerCase().includes(filterText) ||
                String(asset.name || '').toLowerCase().includes(filterText)
            );
        }
        sortAssets(filteredAssets);
        if (activeTab === 'jp_stock') {
            renderStockTable(filteredAssets);
        } else {
            renderFundTable(filteredAssets);
        }
        updateSortHeaders();
        updateDeleteSelectedButtonState();
    }

    function renderStockTable(stocks) {
        const tableBody = document.querySelector('#portfolio-table-jp_stock tbody');
        tableBody.innerHTML = '';
        if (!stocks || stocks.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="14" style="text-align:center;">登録されている銘柄はありません。</td></tr>`;
            return;
        }
        stocks.forEach(stock => {
            const row = tableBody.insertRow();
            row.dataset.code = stock.code;
            const createCell = (html, className = '') => {
                const cell = row.insertCell();
                cell.innerHTML = html;
                if (className) cell.className = className;
                return cell;
            };
            if (stock.error) {
                row.className = 'error-row';
                row.title = stock.error;
                createCell(`<input type="checkbox" class="asset-checkbox" data-code="${stock.code}" disabled>`);
                createCell(stock.code);
                const errorCell = createCell(stock.error, 'error-message');
                errorCell.colSpan = 11;
                createCell(`<button class="manage-btn" data-code="${stock.code}" disabled>管理</button>`);
                return;
            }
            createCell(`<input type="checkbox" class="asset-checkbox" data-code="${stock.code}">`);
            createCell(stock.code);
            createCell(`<a href="https://finance.yahoo.co.jp/quote/${stock.code}.T" target="_blank">${stock.name}</a>`);
            createCell(stock.industry || 'N/A');
            createCell(renderScoreAsStars(stock.score, stock.score_details));
            createCell(stock.price);
            createCell(`${stock.change} (${stock.change_percent || 'N/A'})`);
            createCell(formatMarketCap(stock.market_cap));
            createCell(stock.per, getHighlightClass('per', stock.per));
            createCell(stock.pbr, getHighlightClass('pbr', stock.pbr));
            createCell(stock.roe, getHighlightClass('roe', stock.roe));
            createCell(stock.yield, getHighlightClass('yield', stock.yield));
            const dividendCell = createCell('');
            dividendCell.title = formatDividendHistory(stock.dividend_history);
            dividendCell.innerHTML = `<a href="https://finance.yahoo.co.jp/quote/${stock.code}.T/dividend" target="_blank" class="dividend-link">
                ${stock.consecutive_increase_years > 0 ? `<span class="increase-badge">${stock.consecutive_increase_years}年連続</span>` : '-'}
            </a>`;
            createCell(`<button class="manage-btn" data-code="${stock.code}">管理</button>`);
        });
    }

    function renderFundTable(funds) {
        const tableBody = document.querySelector('#portfolio-table-investment_trust tbody');
        tableBody.innerHTML = '';
        if (!funds || funds.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="8" style="text-align:center;">登録されている投資信託はありません。</td></tr>`;
            return;
        }
        funds.forEach(fund => {
            const row = tableBody.insertRow();
            row.dataset.code = fund.code;
            const createCell = (html, className = '') => {
                const cell = row.insertCell();
                cell.innerHTML = html;
                if (className) cell.className = className;
                return cell;
            };
            if (fund.error) {
                row.className = 'error-row';
                row.title = fund.error;
                createCell(`<input type="checkbox" class="asset-checkbox" data-code="${fund.code}" disabled>`);
                createCell(fund.code);
                const errorCell = createCell(fund.error, 'error-message');
                errorCell.colSpan = 5;
                createCell(`<button class="manage-btn" data-code="${fund.code}" disabled>管理</button>`);
                return;
            }
            createCell(`<input type="checkbox" class="asset-checkbox" data-code="${fund.code}">`);
            createCell(fund.code);
            createCell(`<a href="https://finance.yahoo.co.jp/quote/${fund.code}" target="_blank">${fund.name}</a>`);
            createCell(fund.price);
            createCell(`${fund.change} (${fund.change_percent || 'N/A'})`);
            createCell(fund.net_assets);
            createCell(fund.trust_fee);
            createCell(`<button class="manage-btn" data-code="${fund.code}">管理</button>`);
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
    function sortAssets(data) {
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
        document.querySelectorAll(`#${activeTab} .sortable`).forEach(header => {
            header.classList.remove('sort-active', 'sort-asc', 'sort-desc');
            if (header.dataset.key === currentSort.key) {
                header.classList.add('sort-active', `sort-${currentSort.order}`);
            }
        });
    }
    function showLoading(isLoading) {
        // loadingIndicator.style.display = isLoading ? 'block' : 'none';
        // document.querySelectorAll('.tab-content').forEach(tc => tc.style.display = isLoading ? 'none' : '');
    }
    function updateDeleteSelectedButtonState() {
        const checkedCount = document.querySelectorAll(`#${activeTab} .asset-checkbox:checked`).length;
        deleteSelectedStocksButton.disabled = checkedCount === 0;
    }
    function formatMarketCap(value) {
        if (value === 'N/A' || value === null || value === undefined || value === '--') return 'N/A';
        const num = typeof value === 'string' ? parseFloat(value.replace(/,/g, '')) : value;
        if (isNaN(num)) return 'N/A';
        const trillion = 1e12, oku = 1e8;
        if (num >= trillion) return `${(num / trillion).toFixed(2)}兆円`;
        if (num >= oku) return `${(num / oku).toFixed(2)}億円`;
        return `${(num / 1e6).toLocaleString()}百万円`;
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
        recentStocksList.innerHTML = codes.length ? '' : '<li>最近追加した資産はありません。</li>';
        codes.forEach(code => {
            const li = document.createElement('li');
            li.className = 'recent-stock-item';
            li.textContent = code;
            li.addEventListener('click', () => { assetCodeInput.value = code; });
            recentStocksList.appendChild(li);
        });
    }

    // --- モーダル関連 ---
    function openManagementModal(code) {
        currentManagingCode = code;
        const asset = allAssetsData.find(s => s.code === code);
        if (!asset) return;
        modalTitle.textContent = `保有情報管理 (${asset.code} ${asset.name})`;
        renderHoldingsList(asset.holdings);
        hideHoldingForm();
        modalOverlay.classList.remove('hidden');
    }
    function renderHoldingsList(holdings) {
        const asset = allAssetsData.find(a => a.code === currentManagingCode);
        const isFund = asset && asset.asset_type === 'investment_trust';
        const quantityDigits = isFund ? 6 : 0; // 投資信託なら小数点以下6桁、それ以外は0桁

        holdingsListContainer.innerHTML = '';
        if (!holdings || holdings.length === 0) {
            holdingsListContainer.innerHTML = '<p>この資産の保有情報はありません。</p>';
            return;
        }
        holdings.forEach(h => {
            const item = document.createElement('div');
            item.className = 'holding-item';
            item.innerHTML = `
                <div class="holding-info">
                    <span class="account-type">${h.account_type}</span>
                    <span>取得単価: ${formatNumber(h.purchase_price, 2)}円</span>
                    <span>数量: ${formatNumber(h.quantity, quantityDigits)}</span>
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
        if (holding) {
            holdingFormTitle.textContent = '保有情報の編集';
            holdingIdInput.value = holding.id;
            accountTypeSelect.value = holding.account_type;
            purchasePriceInput.value = holding.purchase_price;
            quantityInput.value = holding.quantity;
        } else {
            holdingFormTitle.textContent = '保有情報の新規追加';
            holdingIdInput.value = '';
        }
        holdingFormContainer.classList.remove('hidden');
    }
    function hideHoldingForm() { holdingFormContainer.classList.add('hidden'); }
    async function handleHoldingFormSubmit(event) {
        event.preventDefault();
        const holdingId = holdingIdInput.value;
        const data = {
            account_type: accountTypeSelect.value,
            purchase_price: parseFloat(purchasePriceInput.value),
            quantity: parseFloat(quantityInput.value)
        };
        const url = holdingId ? `/api/holdings/${holdingId}` : `/api/stocks/${currentManagingCode}/holdings`;
        const method = holdingId ? 'PUT' : 'POST';
        try {
            const response = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
            if (!response.ok) throw new Error((await response.json()).detail || '保存失敗');
            showAlert('保有情報を保存しました。', 'success');
            const updatedAsset = await fetch(`/api/stocks/${currentManagingCode}`).then(res => res.json());
            const index = allAssetsData.findIndex(a => a.code === currentManagingCode);
            if (index !== -1) allAssetsData[index] = updatedAsset;
            saveAssetsToStorage();
            renderHoldingsList(updatedAsset.holdings);
            filterAndRender();
            hideHoldingForm();
        } catch (error) { showAlert(error.message, 'danger'); }
    }
    async function handleHoldingDelete(holdingId) {
        if (!confirm('この保有情報を削除しますか？')) return;
        try {
            const response = await fetch(`/api/holdings/${holdingId}`, { method: 'DELETE' });
            if (!response.ok) throw new Error('削除失敗');
            showAlert('保有情報を削除しました。', 'success');
            const updatedAsset = await fetch(`/api/stocks/${currentManagingCode}`).then(res => res.json());
            const index = allAssetsData.findIndex(a => a.code === currentManagingCode);
            if (index !== -1) allAssetsData[index] = updatedAsset;
            saveAssetsToStorage();
            renderHoldingsList(updatedAsset.holdings);
            filterAndRender();
        } catch (error) { showAlert(error.message, 'danger'); }
    }
    function closeModal() { modalOverlay.classList.add('hidden'); currentManagingCode = null; }

    // --- イベントリスナー ---
    addAssetForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const code = assetCodeInput.value.trim();
        const assetType = addAssetForm.querySelector('input[name="asset_type"]:checked').value;
        if (!code) return;
        try {
            const response = await fetch('/api/stocks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code, asset_type: assetType }),
            });
            const data = await response.json();
            showAlert(data.message, data.status === 'success' ? 'success' : (data.status === 'exists' ? 'warning' : 'danger'));
            
            if (data.status === 'success') {
                const newAsset = await fetch(`/api/stocks/${code}`).then(res => res.json());
                allAssetsData.push(newAsset);
                saveAssetsToStorage();

                // 追加した資産のタブに切り替える
                const newAssetType = newAsset.asset_type;
                if (activeTab !== newAssetType) {
                    activeTab = newAssetType;
                    document.querySelector('.tab-link.active').classList.remove('active');
                    const newTabLink = document.querySelector(`.tab-link[data-tab="${newAssetType}"]`);
                    if (newTabLink) newTabLink.classList.add('active');
                    
                    document.querySelector('.tab-content.active').classList.remove('active');
                    const newTabContent = document.getElementById(newAssetType);
                    if (newTabContent) newTabContent.classList.add('active');
                }

                const recent = await fetch('/api/recent-stocks').then(res => res.json());
                renderRecentStocksList(recent);
                filterAndRender();
            }
            assetCodeInput.value = '';
        } catch (error) { showAlert('資産の追加中にエラーが発生しました。', 'danger'); }
    });

    document.querySelectorAll('.portfolio-table tbody').forEach(tbody => {
        tbody.addEventListener('click', (event) => {
            if (event.target.classList.contains('manage-btn')) {
                openManagementModal(event.target.dataset.code);
            }
        });
    });

    document.querySelectorAll('.portfolio-table thead').forEach(thead => {
        thead.addEventListener('click', (event) => {
            const header = event.target.closest('.sortable');
            if (!header) return;
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

    tabNav.addEventListener('click', (event) => {
        if (event.target.classList.contains('tab-link')) {
            activeTab = event.target.dataset.tab;
            document.querySelector('.tab-link.active').classList.remove('active');
            event.target.classList.add('active');
            document.querySelector('.tab-content.active').classList.remove('active');
            document.getElementById(activeTab).classList.add('active');
            filterAndRender();
        }
    });

    downloadCsvButton.addEventListener('click', () => { window.location.href = '/api/stocks/csv'; });
    filterInput.addEventListener('input', filterAndRender);
    
    document.querySelectorAll('.select-all-assets').forEach(checkbox => {
        checkbox.addEventListener('change', (event) => {
            const assetType = event.target.dataset.assetType;
            document.querySelectorAll(`#portfolio-table-${assetType} .asset-checkbox:not(:disabled)`).forEach(cb => {
                cb.checked = event.target.checked;
            });
            updateDeleteSelectedButtonState();
        });
    });

    document.querySelectorAll('.portfolio-table tbody').forEach(tbody => {
        tbody.addEventListener('change', (event) => {
            if (event.target.classList.contains('asset-checkbox')) {
                const tableId = event.target.closest('.portfolio-table').id;
                const all = document.querySelectorAll(`#${tableId} .asset-checkbox:not(:disabled)`);
                const checked = document.querySelectorAll(`#${tableId} .asset-checkbox:checked:not(:disabled)`);
                const selectAllCheckbox = document.querySelector(`.select-all-assets[data-asset-type="${activeTab}"]`);
                selectAllCheckbox.checked = all.length > 0 && all.length === checked.length;
                updateDeleteSelectedButtonState();
            }
        });
    });

    deleteSelectedStocksButton.addEventListener('click', async () => {
        const codesToDelete = Array.from(document.querySelectorAll(`#${activeTab} .asset-checkbox:checked`)).map(cb => cb.dataset.code);
        if (codesToDelete.length === 0 || !confirm(`選択された ${codesToDelete.length} 件の資産を削除しますか？`)) return;
        try {
            const response = await fetch('/api/stocks/bulk-delete', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ codes: codesToDelete }),
            });
            if (!response.ok) throw new Error((await response.json()).detail || '一括削除失敗');
            showAlert(`${codesToDelete.length} 件の資産を削除しました。`, 'success');
            allAssetsData = allAssetsData.filter(asset => !codesToDelete.includes(asset.code));
            saveAssetsToStorage();
            filterAndRender();
            document.querySelector(`.select-all-assets[data-asset-type="${activeTab}"]`).checked = false;
            updateDeleteSelectedButtonState();
        } catch (error) { showAlert(error.message, 'danger'); }
    });

    refreshAllButton.addEventListener('click', async () => {
        if (refreshAllButton.disabled) return;

        showAlert('全資産のデータを更新しています...', 'info');
        
        const cooldownEnd = Date.now() + COOLDOWN_MINUTES * 60 * 1000;
        localStorage.setItem(COOLDOWN_STORAGE_KEY, cooldownEnd);
        startCooldownTimer(cooldownEnd);

        const success = await initialize();
        
        if (success) {
            showAlert('全資産のデータを更新しました。', 'success');
        }
    });

    // モーダルイベント
    addNewHoldingBtn.addEventListener('click', () => showHoldingForm());
    holdingForm.addEventListener('submit', handleHoldingFormSubmit);
    holdingFormCancelBtn.addEventListener('click', hideHoldingForm);
    holdingsListContainer.addEventListener('click', (event) => {
        const target = event.target;
        if (target.classList.contains('btn-edit')) {
            const holdingId = target.dataset.holdingId;
            const asset = allAssetsData.find(s => s.code === currentManagingCode);
            const holding = asset.holdings.find(h => h.id === holdingId);
            showHoldingForm(holding);
        } else if (target.classList.contains('btn-delete-holding')) {
            handleHoldingDelete(target.dataset.holdingId);
        }
    });
    modalCloseBtn.addEventListener('click', closeModal);
    modalOverlay.addEventListener('click', (event) => { if (event.target === modalOverlay) closeModal(); });

    // --- 初期実行 ---
    loadAssetsFromStorage();
    checkInitialCooldown();
    initialize();
});