// static/js/stateManager.js

/**
 * HTTPエラーを扱うカスタムエラークラス
 */
class HttpError extends Error {
    constructor(message, status) {
        super(message);
        this.name = 'HttpError';
        this.status = status;
    }
}

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
// DBキャッシュ導入により、フロントエンドでの制限は不要になりました。
const API_COOLDOWN_SECONDS = 0; 
const SESSION_STORAGE_KEY = 'globalLastFetchTime';

/**
 * 全件更新系APIを呼び出してよいかチェックする。
 * @returns {boolean} - 常にtrue（DBキャッシュがバックエンドで制御するため）
 */
function canFetch() {
    return true;
}

/**
 * クールダウンの残り時間をミリ秒単位で取得する。
 * @returns {number} - 常に0
 */
function getCooldownRemainingTime() {
    return 0;
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
    HttpError,
    canFetch,
    getCooldownRemainingTime,
    updateTimestamp,
    updateState,
    getState,
    clearState,
};
