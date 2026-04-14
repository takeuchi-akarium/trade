# CLAUDE.md

## このリポジトリについて

BTC（暗号資産）および日本株を対象とした自動売買システムの開発リポジトリ。
バックテスト → ペーパートレード → 本番自動売買の順に段階的に構築する。

## 技術スタック

- **言語**: Python 3.14
- **主要ライブラリ**: pandas, numpy, plotly, requests
- **データソース**: Binance公開API（BTC）、J-Quants（日本株、将来）
- **仮想環境**: `.venv/`

## 開発コマンド

```bash
# 仮想環境有効化
.venv/Scripts/activate

# データ取得
python src/fetch_btc.py

# 依存関係インストール
python -m pip install -r requirements.txt
```

## シミュレーション

全戦略は `src/strategies/` にパッケージ化されている。共通CLIで実行し、結果はFlaskダッシュボードで確認する。

```bash
# 戦略一覧
python src/simulator/runner.py list

# バックテスト（結果は data/simulations/ にJSON保存）
python src/simulator/runner.py run --strategy rsi --symbol BTCUSDT --interval 1d
python src/simulator/runner.py run --strategy btc_ma --symbol BTCUSDT --years 3

# 複数戦略比較
python src/simulator/runner.py compare --strategies rsi,bb,ema,vwap --symbol BTCUSDT

# リアルタイムペーパートレード（常駐、Ctrl+Cで停止）
python src/simulator/runner.py live --strategy rsi --symbol BTCUSDT --interval 5m

# ダッシュボード起動 → ブラウザで確認
python src/web/app.py
# http://localhost:5000             ← メインダッシュボード
# http://localhost:5000/simulations ← シミュレーション結果
# http://localhost:5000/trade-journal ← トレード判断記録
# http://localhost:5000/bench       ← ベンチマーク実行・結果確認
```

### DART戦略 (Dynamic Adaptive Regime Trading)

BTCの種戦略。SMA50乖離率の強度に応じて参加戦略数を動的に変える「段階制(gradient)」で運用。
強トレンド時は1戦略に集中、レンジ時は3戦略で分散、強下落時は全退避。
ファンダメンタルズ（ゴールド/10年債/FnG）でEarly Transition（早期退避）とBoost（攻勢）を補正。

- **実装**: `src/trader/engine.py` (レジーム判定・配分ロジック)
- **実行**: `python src/trader/run.py --dry-run`
- **設定**: `config.yaml` の `trader` セクション
- **解説**: `docs/strategy.html`

### 登録済み戦略

| 名前 | カテゴリ | 説明 |
|------|---------|------|
| `rsi` | short_term | RSI逆張り |
| `bb` | short_term | ボリンジャーバンド（DART: 押し目買い） |
| `ema` | short_term | EMAクロス |
| `ema_don` | short_term | EMA + ドンチャン補完（DART: 順張り主力） |
| `vwap` | short_term | VWAP乖離 |
| `btc_ma` | long_term | BTC MAクロス (Mid-Band Exit) |
| `dual_momentum` | long_term | デュアルモメンタム (GEM) |
| `leadlag` | long_term | 日米リードラグ (PCA SUB) |
| `dart` | composite | DART段階制 (bb+ema_don+bb_ls 動的配分) |
| `pair_bb` | pair | ペアトレード スプレッドBB |
| `pair_ema` | pair | ペアトレード スプレッドEMA |

### 新しい戦略の追加方法

1. `src/strategies/新戦略/` フォルダを作成
2. `__init__.py` に `Strategy` を継承したクラスを実装し `register()` を呼ぶ
3. `src/strategies/__init__.py` に `import strategies.新戦略` を追加
4. 完了 — CLIから使える

## データキャッシュ

Binance OHLCVデータは `data/cache/{symbol}_{interval}.csv` に自動キャッシュされる。
2回目以降のバックテストは差分のみAPI取得するため高速。

```bash
# キャッシュは自動。手動クリアしたい場合:
rm data/cache/BTCUSDT_1d.csv   # 特定データのみ
rm -rf data/cache/              # 全キャッシュ
```

| データソース | キャッシュ場所 | 更新方式 |
|-------------|--------------|---------|
| Binance OHLCV | `data/cache/{symbol}_{interval}.csv` | 増分更新（12h以上経過で差分取得） |
| dual_momentum | `data/dual_momentum/monthly_prices.csv` | 増分更新 |
| leadlag | `data/leadlag/us_sectors.csv`, `jp_sectors.csv` | 増分更新 |

## ベンチマーク (bench)

戦略の定量評価を統一フォーマットで実行する。CLIまたはWebダッシュボードから実行可能。

### Webダッシュボード

`http://localhost:5000/bench` でベンチマークの実行と結果確認ができる。

- **実行フォーム**: type / strategies / symbol / interval / years / SL / TP を指定して Run
- **結果一覧**: `data/simulations/bench/` に保存された過去の結果をカード表示。クリックで詳細テーブル展開
  - backtest → リターン降順テーブル + 月次リターン
  - scenario → 確率加重リターン + シナリオ別リターン
  - allocation → 配分パターン比較（期待/実データリターン・MDD）
- 実行はサブプロセスで非同期。完了後にCLI出力とresultsを自動更新

### CLI

### 3つのベンチタイプ

| type | データ | 評価内容 |
|------|--------|---------|
| `backtest` | 実データ | 戦略の実績パフォーマンス |
| `scenario` | 合成6パターン | 戦略の相場耐性 |
| `allocation` | 両方 | 戦略の配分パターン比較（等配分 vs 各単独 vs DART段階制） |

```bash
# --- backtest: 実データで戦略を評価 ---
python src/simulator/runner.py bench --type backtest --strategies all --years 3
python src/simulator/runner.py bench --type backtest --strategies short_term --sl 5.0
python src/simulator/runner.py bench --type backtest --strategies dart,bb,ema_don --years 3

# --- scenario: 合成データ6パターンで耐性を評価 ---
python src/simulator/runner.py bench --type scenario --strategies dart,bb,ema_don --sl 5.0

# --- allocation: 配分パターン比較 ---
python src/simulator/runner.py bench --type allocation --years 3                          # DART (bb,ema_don,bb_ls)
python src/simulator/runner.py bench --type allocation --strategies rsi,bb,ema --years 1  # 任意の戦略
```

### パラメータ

| 引数 | デフォルト | 説明 |
|------|-----------|------|
| `--type` | backtest | backtest / scenario / allocation |
| `--strategies` | all | 戦略名カンマ区切り / all / カテゴリ名 |
| `--symbol` | BTCUSDT | 銘柄 |
| `--interval` | 1d | 時間足 |
| `--years` | 1 | 期間（年） |
| `--sl` | なし | ストップロス(%) |
| `--tp` | なし | テイクプロフィット(%) |

### シナリオ一覧（scenario / allocation で使用）

| シナリオ | 確率 | 内容 |
|---------|------|------|
| `bear` | 15% | 下落→回復 (-60%) |
| `range` | 25% | レンジ相場（平均回帰） |
| `crash_recovery` | 10% | V字回復 |
| `slow_bleed` | 20% | ダラダラ下落 (-40%) |
| `bubble_burst` | 15% | バブル崩壊 (3倍→-70%) |
| `range_breakout` | 15% | ヨコヨコ→急騰 |

### allocation の動作

`--strategies` の指定によって動作が変わる:

| 指定 | 動作 | 比較パターン |
|------|------|-------------|
| 未指定 or `bb,ema_don,bb_ls` | DART専用 | 現行ミックス / 得意戦略のみ / 段階制 |
| それ以外 | 汎用 | 等配分 (1/N) / 各戦略単独 |

DART専用モードではレジーム連動のリバランスコストも考慮。
汎用モードでは任意のN戦略を組み合わせて「混ぜたほうが良いか、単独が良いか」を評価できる。

### 出力

各ベンチはリターン降順のテーブルと示唆を自動出力する。示唆の観点:
- 極値の指摘（最高リターン、最低MDD、最高シャープ）とそのトレードオフ
- 統計的信頼性の警告（取引数が少ない場合）
- シナリオ耐性（全シナリオ黒字か、最悪ケースの特定）
- 配分パターンの優劣（allocation時）

## トレード判断記録（Trade Journal）

板情報・ニュース・テクニカル・判断理由を記録し、結果と照合してパターン認識を蓄積するツール。

```bash
# 新規記録
python src/trade_journal.py add --ticker 8035 --direction short --name "東京エレクトロン" \
  --ask-volume 24000 --bid-volume 900 --close 44040 --bb "+2σ〜+3σ" --rsi 63.9 \
  --news "米イラン停戦交渉決裂|ホルムズ海峡再閉鎖" --reasoning "停戦ラリー巻き戻し"

# 結果記入
python src/trade_journal.py result --id 20260413_8035 --entry 44000 --exit 42590 --outcome win

# 一覧・統計
python src/trade_journal.py list
python src/trade_journal.py stats

# ダッシュボード
# http://localhost:5000/trade-journal
```

データは `data/trade_journal/entries.json` に保存。板のスクリーンショットは `data/trade_journal/screenshots/` に配置する。
将来、証券会社API（立花証券 e支店 or 三菱UFJ eスマート証券）で板情報の自動取得を追加予定。

## ルール

@.claude/rules/general.md
@.claude/rules/security.md

## 利用可能なエージェント

| エージェント | 説明 |
|------------|------|
| `researcher` | コードベースの調査・分析（影響範囲の特定、パターン分析など） |
| `strategist` | 投資・トレード戦略の立案・評価（アイデア出し、リスク評価） |
| `builder` | シミュレーション・バックテスト・自動売買のコード実装 |
| `backtester` | バックテスト実行と結果分析（戦略の定量評価・比較） |
| `test-runner` | テスト実行と失敗分析 |

## 利用可能なスキル

| コマンド | 説明 |
|---------|------|
| `/commit` | コミットメッセージを生成してコミット |
| `/review` | コードレビューを実施 |
| `/ship` | レビュー→コミット→PR作成 |

## メモリ

Claude Codeはプロジェクト固有のメモリを `~/.claude/projects/<path>/memory/` に保存できる。
次回の会話でも活かすべき情報は積極的に保存する。

| 種別 | 保存する情報の例 |
|------|----------------|
| `user` | ユーザーの役割・技術レベル・好み |
| `feedback` | 「こうしてほしい／やめてほしい」という指示 |
| `project` | 背景・制約・意思決定の経緯 |
| `reference` | 外部ドキュメント・Slack・Linear などのリンク |
