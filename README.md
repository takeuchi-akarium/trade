# trade

BTC（暗号資産）および日本株を対象とした自動売買システム。
バックテスト → ペーパートレード → 本番自動売買の順に段階的に構築する。

## セットアップ

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
```

## 使い方

```bash
# BTCデータ取得（Binance公開API、口座不要）
python src/btc/fetch_btc.py

# バックテスト（移動平均クロス戦略）
python src/btc/backtest.py

# パラメータ最適化（グリッドサーチ）
python src/btc/optimize.py

# ペーパートレード（毎日1回実行）
python src/btc/paper_trade.py

# シグナル収集（15分バッチ）
python src/batch_15m.py

# 価格監視（5分バッチ）
python src/batch_5m.py
```

## 構成

```
src/
├── btc/
│   ├── fetch_btc.py    # データ取得（日足・1時間足、ページネーション対応）
│   ├── backtest.py     # バックテスト（MAクロス戦略、HTMLチャート出力）
│   ├── optimize.py     # MAパラメータ最適化（グリッドサーチ）
│   └── paper_trade.py  # ペーパートレード（シグナル検知・損益追跡）
├── signals/
│   ├── collectors/
│   │   └── macro_collector.py  # VIX・Fear&Greed 取得
│   ├── scorer.py               # 生データ → -100〜+100 スコア変換
│   └── aggregator.py           # スコア統合 → BUY/HOLD/SELL
├── common/
│   ├── config_loader.py        # config.yaml 読み込み（環境変数展開）
│   └── notifier.py             # Discord / LINE / ログ通知
├── batch_5m.py                 # 5分バッチ（価格監視）
└── batch_15m.py                # 15分バッチ（シグナル収集・通知）
config.yaml                     # 通知設定・シグナル閾値
.env                            # Webhook URL など秘密情報（.gitignore対象）
data/
├── btc/
│   ├── btc_1d.csv          # 日足データ（.gitignore対象）
│   ├── paper_state.json    # ペーパートレードのポジション状態
│   └── paper_log.csv       # 取引履歴ログ
└── signals/
    ├── latest_signal.json  # 最新シグナル（他スクリプトから参照可）
    └── signal_log.tsv      # シグナル変化ログ
```

## 日米リードラグ戦略

論文: [部分空間正則化付きPCAを用いた日米業種リードラグ投資戦略 (中川ら, SIG-FIN-036, 2026)](https://www.jstage.jst.go.jp/article/jsaisigtwo/2026/FIN-036/2026_76/_pdf/-char/ja)

## シグナルの見方と使い方

### 通知の内容

Discord に届く通知の例：
```
シグナル変化: HOLD → SELL  (スコア: -38)
  fear_greed: 12 (Extreme Fear)  (-76)
  vix: 23.9  (+0)
```

| 項目 | 意味 |
|------|------|
| シグナル | BUY / HOLD / SELL の3段階 |
| スコア | -100〜+100。+30以上でBUY、-30以下でSELL |
| fear_greed | 暗号資産市場全体の心理。0=極度の恐怖、100=極度の強欲 |
| vix | 米国株の恐怖指数。高いほど市場が不安定 |

### スコアの計算方法

- **Fear & Greed**: `(値 - 50) × 2`  → 50=中立、0=−100、100=+100
- **VIX**: VIX < 15 で +40、VIX 20〜25 で 0、VIX > 40 で −100

複数指標の**加重平均**が最終スコアになる（重みは `config.yaml` の `weights` で調整可）。

### 売買判断への使い方

**重要：このシグナルはあくまで「市場環境の参考情報」。売買の最終判断は自分で行う。**

| シグナル | 意味 | 考え方 |
|---------|------|--------|
| **BUY** | マクロ環境が強気 | エントリーや買い増しを検討する根拠の一つ |
| **HOLD** | 中立 | 様子見。既存ポジションは維持 |
| **SELL** | マクロ環境が弱気 | 新規エントリーを控える、利確・損切りを検討 |

**現状の限界（今後改善予定）：**
- 指標が2つ（Fear&Greed、VIX）のみで精度は低い
- ニュース・決算・突発イベントは未対応
- BTCの売買ロジック（MAクロス）とはまだ連動していない

### 閾値のカスタマイズ

`config.yaml` で調整できる：
```yaml
signal:
  buy_threshold: 30   # これ以上でBUY（厳しくしたいなら50に上げる）
  sell_threshold: -30 # これ以下でSELL（厳しくしたいなら-50に下げる）
```

## 通知設定

1. `cp .env.example .env` で `.env` を作成
2. Discord を使う場合: サーバー設定 → 連携サービス → Webhook から URL を取得して `.env` に設定
3. `config.yaml` で `discord.enabled: true` に変更

## タスクスケジューラ登録（Windows）

コマンドプロンプトを **管理者として実行** して以下を入力。

### 登録

```bat
REM 15分バッチ（マクロシグナル: Fear&Greed, VIX）
schtasks /create /tn "trade_15m" /tr "G:\workspace\trade\.venv\Scripts\python.exe G:\workspace\trade\src\batch_15m.py" /sc minute /mo 15 /f

REM 15分バッチ（TDnet適時開示監視）
schtasks /create /tn "trade_tdnet" /tr "G:\workspace\trade\.venv\Scripts\python.exe G:\workspace\trade\src\batch_tdnet.py" /sc minute /mo 15 /f

REM 30分バッチ（RSSニュース監視）
schtasks /create /tn "trade_rss" /tr "G:\workspace\trade\.venv\Scripts\python.exe G:\workspace\trade\src\batch_rss.py" /sc minute /mo 30 /f

REM 5分バッチ（価格監視）
schtasks /create /tn "trade_5m" /tr "G:\workspace\trade\.venv\Scripts\python.exe G:\workspace\trade\src\batch_5m.py" /sc minute /mo 5 /f
```

### 確認・停止・削除

```bat
REM 登録状況確認
schtasks /query /tn "trade_15m"
schtasks /query /tn "trade_5m"

REM 一時停止
schtasks /end /tn "trade_15m"
schtasks /end /tn "trade_5m"

REM 削除（完全解除）
schtasks /delete /tn "trade_15m" /f
schtasks /delete /tn "trade_tdnet" /f
schtasks /delete /tn "trade_rss" /f
schtasks /delete /tn "trade_5m" /f
```

### PCの状態とバッチの動作

| 状態 | 動作 |
|------|------|
| **通常稼働中** | 15分・5分ごとに自動実行 |
| **シャットダウン** | 停止。**次回起動後から自動で再開**（再登録不要） |
| **スリープ中** | 停止。**スリープ解除後から自動で再開** |
| **スリープ中に実行時刻を過ぎた場合** | デフォルトではスキップ（通知は来ない） |

> スリープ中の実行時刻を逃したくない場合は、タスクスケジューラのGUIで
> 「スケジュールした時刻にタスクを開始できなかった場合、すぐにタスクを実行する」にチェックを入れる。

## ロードマップ

- [x] データ取得（Binance公開API）
- [x] バックテスト（移動平均クロス）
- [x] パラメータ最適化（グリッドサーチ、ヒートマップ）
- [x] ペーパートレード（シグナル検知・損益追跡）
- [x] シグナル収集システム（VIX・Fear&Greed）
- [x] 通知システム（Discord / LINE / ログ）
- [ ] ニュース収集（RSSコレクター追加）
- [ ] タスクスケジューラ自動実行
- [ ] 本番自動売買（取引所API連携）
