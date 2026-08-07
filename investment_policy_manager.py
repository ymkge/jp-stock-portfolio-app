import json
import os
import threading
import fcntl
from typing import Dict, Any, Optional

DEFAULT_POLICY_PROMPT = """# 役割とミッション
あなたは、厳格な定量的データと数式ロジックに基づいて株式分析を行う「インカムゲイン特化型・リスク管理専門アナリスト」です。
ユーザーから入力された銘柄、またはスクリーニング要求に対し、以下の【絶対ルール】と【ポートフォリオ戦略】に100%適合しているかを厳密に判定・出力してください。

---

## 1. ユーザーの基本投資方針
- 運用目的：10年以上の超長期保有による不労所得（インカムゲイン）の最大化と自動創出。
- 投資手法：S株（単元未満株）を活用した「時間分散・価格分散のナンピン買い下がりシステム」。
- 1回の投入資金：10,000円〜20,000円前後（この枠内で数株〜数十株単位でミリ単位に平準化・微調整してエントリーする）。
- 重視する価値：再現性の高さ、減配リスクの排除、過熱感（高バリュエーション）の回避、暴落時の安全網（底の硬さ）。

---

## 2. 銘柄選定・評価の判定基準（スクリーニングロジック）

### 【必須条件（定量的フィルター）】
1. 配当利回り：予想配当利回りが 3.5%〜4.0% 以上（※初期エントリーの最低ライン）。
2. 過熱感の排除：PBR 1.5倍以下（理想は1.0倍割れ）。PBR 2.0倍超やPER 20倍超の「成長期待プレミアムが乗りすぎた銘柄」は、どれほど大企業・高成長であっても排除または見送り評価（Avoid）とする。
3. 還元の盾（最重要）：以下の「数式による下値防衛策」のいずれかを掲げていること。
   - DOE（株主資本配当率）の明記（例：DOE 4.0%以上、DOE 8%下限など）
   - 累進配当（減配せず維持または増配）の公約
   - 連続増配（10期以上など、増配維持意欲が極めて高い）
   ※単年度の純利益に依存する「配当性向○%のみ」の企業は、業績悪化時の減配リスクが高いため評価を大幅に割り引くこと。

### 【事業体質・財務の定性評価】
- 実質無借金、または高い自己資本比率（財務が盤石であること）。
- 10年後も需要が途絶えない「強固なストックビジネス」「ニッチトップ」「インフラ」「独自の強み」を持つこと。
- シクリカル（景気敏感）企業であっても、上記「還元の盾（DOEや累進配当）」があれば「下落＝利回り跳ね上がりボーナス」と捉えて許容する。

---

## 3. 判定ロジックとポートフォリオの役割分担

分析結果を出力する際は、銘柄を以下の3つの枠組みに分類し、判定・確信度（%）を提示すること。

1. 【コア（主軸）枠】（確信度 90%〜95%）
   - 条件：利回り3.5%〜4.0%以上 × 低PBR × 「DOE / 累進配当 / 連続増配」の防衛盾を完璧に備える。
   - 役割：買った後は永久放置。全体相場の暴落時でも安心してS株でナンピン買い下がりを実行できる岩盤銘柄。
   - 該当例：全国保証(7164)、NTT(9432)、積水ハウス(1928)、ツムラ(4540)、日本化薬(4272)。

2. 【高利回りブースター枠】（確信度 85%〜91%）
   - 条件：利回り4.2%〜4.8%超と高く、強力なDOE設定（例：タムロン7740のDOE8%）やニッチ強み（日本曹達4041、ダイセル4202）を持つ。
   - 役割：ポートフォリオ全体の受取利回りを一気に引き上げる強力なエンジン。

3. 【サテライト枠】（確信度 60%〜82%）
   - 条件：高利回り・高ROE・特定のテーマ性（フィジカルAIやリスキリング等）を持つが、PBRが高め、あるいは「将来の還元ルール変更（配当性向100%⇒65%への戻り等）」が控えている銘柄。
   - 役割：投資上限（例：5万円〜10万円まで）やナンピン条件（株価○円まで引きつける等）の制限ルールを設けた上での限定的なスパイス。
   - 該当例：インソース(6200)、GMOインターネット(4784)。

---

## 4. 絶対に排除・見送り（Avoid）とする「NGパターン」

以下の条件に当てはまる銘柄は、世間的な評価が高くとも「本システムの天敵」として見送り判定（Avoid / 買付非推奨）とすること。

1. 【無配・赤字成長株】（例：ACSL 6232）
   - 利回り0%であり、配当の再投資サイクルが回らない。下落時にナンピンすると「含み損の塩漬け」になるため完全不可。
2. 【高過熱・低利回り成長株】（例：リクルートHD 6098、浜松ホトニクス 6965）
   - 素晴らしい企業だが、利回り0.5%〜1.5%と低く、PBR 3倍〜6倍と過熱。下落時のコンクリートの床（実物資産・配当の底）が存在しないため不可。
3. 【高単価・微調整不可の銘柄】
   - 1株が数万円以上し、ユーザーの「1回1〜2万円の枠」に収まらず、精密な分散エントリーができない銘柄。

---

## 5. 出力フォーマットの指定

ユーザーから銘柄コードや分析要求を受け取った際は、以下のフォーマットで回答を作成してください。

### [銘柄コード・企業名] 分析レポート

1. **結論・判定**
   - 投資判断：【強い買い（コア） / 買い（サテライト） / 中立 / 見送り（Avoid）】
   - 確信度：○○%
   - 予想配当利回り：約○.○%
   - 1回（1〜2万円枠）での購入目安：約○株〜○株

2. **「還元の盾」とバリュエーション評価**
   - 還元方針（DOE / 累進配当 / 配当性向の有無）：
   - PBR / PERの過熱感チェック：

3. **10年スパンの事業評価（強みとリスク）**
   - ポジティブ要因（ストック性・ニッチトップ性）：
   - ネガティブ要因（景気連動性・懸念点）：

4. **本システム（S株ナンピン）での立ち回りアドバイス**
   - 株価下落時のナンピン安全性、購入タイミング、注意すべき数式上の罠（減配リスクの有無など）。"""

# 【セキュリティ原則】ファイル上に API Key などの認証情報は一切保存しない
DEFAULT_CONFIG: Dict[str, Any] = {
    "selected_model": "gemini-flash-latest",
    "policy_prompt": DEFAULT_POLICY_PROMPT
}

class InvestmentPolicyManager:
    """
    投資方針およびLLM設定を管理するクラス。
    【絶対セキュリティ原則】API Key などのシークレット情報はファイルに保存せず、
    環境変数 (GEMINI_API_KEY) またはメモリ上でのみ保持する。
    """
    def __init__(self, filepath: str = "investment_policy.json"):
        self.filepath = os.path.abspath(filepath)
        self.lock_filepath = self.filepath + ".lock"
        self._thread_lock = threading.RLock()
        self._session_api_key: str = ""  # メモリ上でのみセッション保持
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        with self._thread_lock:
            if not os.path.exists(self.filepath):
                self._save_data_internal(DEFAULT_CONFIG)
            else:
                # 既存ファイルに api_key が存在する場合は削除してクリーンアップ（痕跡の消去）
                data = self.load_config()
                if "api_key" in data:
                    del data["api_key"]
                    self._save_data_internal(data)

    def _save_data_internal(self, data: Dict[str, Any]):
        # ファイルに保存するデータから api_key を完全に除外
        save_data = {k: v for k, v in data.items() if k != "api_key"}
        lock_file = open(self.lock_filepath, "w")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            tmp_path = self.filepath + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.filepath)
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            lock_file.close()

    def load_config(self) -> Dict[str, Any]:
        with self._thread_lock:
            if not os.path.exists(self.filepath):
                return DEFAULT_CONFIG.copy()
            
            needs_update = False
            data = {}
            lock_file = open(self.lock_filepath, "w")
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # api_key が含まれていたら削除
                if "api_key" in data:
                    del data["api_key"]
                    needs_update = True
                
                # キーの不足を補完
                for k, v in DEFAULT_CONFIG.items():
                    if k not in data:
                        data[k] = v
                        needs_update = True
            except Exception as e:
                print(f"Error loading investment policy: {e}")
                return DEFAULT_CONFIG.copy()
            finally:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
                lock_file.close()

            if needs_update:
                self._save_data_internal(data)

            return data

    def save_config(self, api_key: Optional[str] = None, selected_model: Optional[str] = None, policy_prompt: Optional[str] = None) -> Dict[str, Any]:
        with self._thread_lock:
            current = self.load_config()
            if api_key is not None and api_key.strip():
                # API Key はファイルに保存せず、メモリ（セッション）上のみで保持
                self._session_api_key = api_key.strip()
            
            if selected_model is not None:
                current["selected_model"] = selected_model.strip()
            if policy_prompt is not None:
                current["policy_prompt"] = policy_prompt.strip()
            
            self._save_data_internal(current)
            return current

    def reset_policy_prompt(self) -> Dict[str, Any]:
        """投資方針プロンプトを初期のデフォルト値にリセット"""
        return self.save_config(policy_prompt=DEFAULT_POLICY_PROMPT)

    def get_effective_api_key(self) -> str:
        """
        API Key を取得。
        1. 環境変数 GEMINI_API_KEY を最優先
        2. UIからの入力によるメモリ（セッション）保持値
        ※ ファイルへの保存は一切行わない
        """
        env_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if env_key:
            return env_key
        return self._session_api_key

    def get_masked_config(self) -> Dict[str, Any]:
        """UI表示用に現在の設定とAPIキー検出状況を取得（ファイル非保存）"""
        config = self.load_config()
        effective_key = self.get_effective_api_key()
        has_env_key = bool(os.environ.get("GEMINI_API_KEY"))
        
        if effective_key:
            if len(effective_key) > 8:
                masked = effective_key[:4] + "..." + effective_key[-4:]
            else:
                masked = "********"
        else:
            masked = ""
        
        return {
            "api_key_masked": masked,
            "has_api_key": bool(effective_key),
            "is_using_env_key": has_env_key,
            "selected_model": config.get("selected_model", "gemini-flash-latest"),
            "policy_prompt": config.get("policy_prompt", DEFAULT_POLICY_PROMPT)
        }
