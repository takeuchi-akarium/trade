# trade

BTC（暗号資産）および日本株を対象とした自動売買システム。

## セットアップ

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env  # APIキー等を設定
```

## コマンド一覧

### ダッシュボード

```bash
python src/web/app.py
```

| URL | 内容 |
|-----|------|
| http://localhost:5000 | メインダッシュボード（マクロ・BTC・リードラグ） |
| http://localhost:5000/simulations | バックテスト結果一覧 |
| http://localhost:5000/trader | 自動売買の実績・損益推移 |

### 自動売買

```bash
# ドライラン（注文なし、動作確認用）
python src/trader/run.py --dry-run

# 本番実行（1回判定→発注）
python src/trader/run.py

# 常駐モード
python src/trader/run.py --daemon
```

毎朝7:00にタスクスケジューラで自動実行される（`setup_tasks.ps1` で登録）。
`config.yaml` の `dry_run: true` の間は注文は出ない。

### バックテスト

```bash
# 登録済み戦略の一覧
python src/simulator/runner.py list

# 単一戦略のバックテスト
python src/simulator/runner.py run --strategy bb --symbol BTCUSDT --interval 1d

# 複数戦略の比較
python src/simulator/runner.py compare --strategies rsi,bb,ema,vwap --symbol BTCUSDT

# ライブシミュレーション（ペーパートレード、Ctrl+Cで停止）
python src/simulator/runner.py live --strategy rsi --symbol BTCUSDT --interval 5m
```

### 朝バッチ（GitHub Actionsで毎朝7:00 JST自動実行）

```bash
python src/batch_morning.py    # 統合朝レポート（リードラグ・BTC・マクロ・ニュース）
```

### その他

```bash
python src/btc/fetch_btc.py    # BTCデータ取得（Binance公開API）
python src/batch_rss.py        # RSSニュース監視
python src/batch_tdnet.py      # TDnet適時開示監視
```

## 構成

```
src/
├── strategies/          # 戦略パッケージ（プラグイン方式）
│   ├── base.py          #   共通インターフェース
│   ├── registry.py      #   戦略レジストリ
│   ├── scalping/        #   RSI, BB, EMA, VWAP（L/S対応）
│   ├── grid/            #   グリッドトレード
│   ├── adaptive/        #   Adaptive（Grid + Trend自動切替）
│   ├── btc/             #   BTC MAクロス
│   ├── dual_momentum/   #   デュアルモメンタム (GEM)
│   ├── leadlag/         #   日米リードラグ (PCA)
│   └── pair_trading/    #   ペアトレード
├── simulator/           # シミュレーション基盤
│   ├── runner.py        #   統一CLI
│   ├── metrics.py       #   共通メトリクス
│   └── report.py        #   結果保存（JSON）
├── exchange/            # 取引所API
│   ├── base.py          #   共通インターフェース
│   └── gmo.py           #   GMOコイン実装
├── trader/              # 自動売買エンジン
│   ├── engine.py        #   複数戦略同時稼働
│   ├── risk.py          #   リスク管理
│   └── run.py           #   CLI
├── common/              # 共通ユーティリティ
├── signals/             # マクロシグナル・アラート
├── web/                 # Flaskダッシュボード
├── batch_morning.py     # 統合朝バッチ
└── batch_*.py           # 各種監視バッチ
docs/
├── index.html           # メインダッシュボード
├── simulations.html     # シミュレーション結果
└── trader.html          # 自動売買実績
config.yaml              # 全設定（戦略・通知・リスク管理）
data/
├── simulations/         # バックテスト結果（JSON）
├── trader/              # 自動売買の状態ファイル
└── signals/             # シグナルログ
```

## 戦略一覧

| 名前 | 説明 | カテゴリ |
|------|------|---------|
| `rsi` / `rsi_ls` | RSI逆張り | 短期 |
| `bb` / `bb_ls` | ボリンジャーバンド | 短期 |
| `ema` / `ema_ls` | EMAクロス | 短期 |
| `vwap` / `vwap_ls` | VWAP乖離 | 短期 |
| `grid` | グリッドトレード | 短期 |
| `adaptive` | Grid + Trend自動切替 | 短期 |
| `btc_ma` | BTC MAクロス (Mid-Band Exit) | 長期 |
| `dual_momentum` | デュアルモメンタム (GEM) | 長期 |
| `leadlag` | 日米リードラグ (PCA) | 長期 |
| `pair_bb` / `pair_ema` | ペアトレード | ペア |

`_ls` 付きはロング/ショート両対応。

### 新しい戦略の追加

1. `src/strategies/新戦略/` フォルダを作成
2. `__init__.py` に `Strategy` を継承して `register()` を呼ぶ
3. `src/strategies/__init__.py` に import を追加
4. 完了 — CLIから使える

## 自動売買の設定

`config.yaml` の `trader:` セクション:

```yaml
trader:
  exchange: gmo
  symbol: BTC
  dry_run: true    # false にすると実注文を出す
  strategies:
    - name: bb
      mode: long_short
      interval: 1d
      weight: 50       # 資金の50%
      params:
        period: 10
        std: 2.0
    - name: grid
      mode: long
      interval: 1h
      weight: 30       # 資金の30%
```

## 環境変数（.env）

```
DISCORD_WEBHOOK_URL=    # Discord通知
LINE_TOKEN=             # LINE通知（任意）
GMO_API_KEY=            # GMOコイン APIキー
GMO_API_SECRET=         # GMOコイン シークレット
```

## タスクスケジューラ登録（Windows）

管理者権限のPowerShellで:

```powershell
powershell -ExecutionPolicy Bypass -File "G:\workspace\trade\setup_tasks.ps1"
```

毎朝7:00にBTC自動売買が実行される。PCが7時に起動していなくても、起動後に自動実行。

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

## ロードマップ

- [x] データ取得（Binance公開API）
- [x] バックテスト（移動平均クロス）
- [x] パラメータ最適化（グリッドサーチ、ヒートマップ）
- [x] ペーパートレード（シグナル検知・損益追跡）
- [x] シグナル収集システム（VIX・Fear&Greed）
- [x] 通知システム（Discord / LINE / ログ）
- [x] TDnet適時開示・RSSニュース自動スコアリング
- [x] 日米リードラグ戦略
- [x] Webダッシュボード
- [x] 戦略パッケージ化（プラグイン方式）
- [x] 統一シミュレーションCLI
- [x] GMOコイン API連携・自動売買エンジン
- [x] 複数戦略同時稼働（BB L/S + Grid）
- [ ] 本番自動売買開始（口座開設待ち）
- [ ] 日本小型株対応（SBI証券API）
