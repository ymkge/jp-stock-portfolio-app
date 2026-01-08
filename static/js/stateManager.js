// static/js/stateManager.js

/**
 * アプリケーション全体の状態を管理するオブジェクト（メモリキャッシュ）
 * - portfolio, analysis: 各ページのデータ領域
 * - global: 全ページ共通の最終取得時刻
 */
const state = {
    portfolio: {
        data: null,
    },
    analysis: {
        data: null,
    },
    global: {
        lastFetchTime: null,
    }
};

// バックエンドのAPIクールダウン設定（秒）
const API_COOLDOWN_SECONDS = 10;
const SESSION_STORAGE_KEY = 'globalLastFetchTime';

/**
 * 全件更新系APIを呼び出してよいかチェックする。
 * 時刻管理は共通の 'global' 領域で行う。
 * @returns {boolean} - API呼び出しが許可される場合はtrue
 */
function canFetch() {
    let lastFetchTime = state.global.lastFetchTime;
    if (!lastFetchTime) {
        const storedTime = sessionStorage.getItem(SESSION_STORAGE_KEY);
        if (storedTime) {
            lastFetchTime = new Date(storedTime);
            state.global.lastFetchTime = lastFetchTime;
        }
    }
    if (!lastFetchTime) {
        return true;
    }
    const now = new Date();
    const secondsSinceLastFetch = (now - lastFetchTime) / 1000;
    return secondsSinceLastFetch > API_COOLDOWN_SECONDS;
}

/**
 * API最終取得時刻を更新する。
 */
function updateTimestamp() {
    const now = new Date();
    state.global.lastFetchTime = now;
    sessionStorage.setItem(SESSION_STORAGE_KEY, now.toISOString());
}

/**
 * 指定されたタイプのデータキャッシュを更新する。
 * @param {('portfolio'|'analysis')} dataType - 更新するデータの種類
 * @param {any} data - APIから取得した新しいデータ
 */
function updateState(dataType, data) {
    if (state[dataType]) {
        state[dataType].data = data;
    }
}

/**
 * 指定されたタイプのキャッシュデータを取得する。
 * @param {('portfolio'|'analysis')} dataType - 取得するデータの種類
 * @returns {any|null} - 保持しているデータ、なければnull
 */
function getState(dataType) {
    return state[dataType]?.data;
}

/**
 * すべての状態をクリアする。
 * メモリキャッシュとsessionStorageの両方から最終取得時刻を削除する。
 */
function clearState() {
    state.portfolio.data = null;
    state.analysis.data = null;
    state.global.lastFetchTime = null;
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
}

// 他のJSファイルからアクセスできるよう、windowオブジェクトに公開する
window.appState = {
    canFetch,
    updateTimestamp, // 新しく追加
    updateState,
    getState,
    clearState,
};
