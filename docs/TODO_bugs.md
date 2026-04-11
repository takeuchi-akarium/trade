# バグ修正TODO

## 致命的 / 重大 (即修正)

- [x] **#1 RiskManagerのライフサイクル修正** — runCycleで1回だけ生成し、setDailyStartを呼ぶよう修正
- [x] **#2 指値注文の約定確認を追加** — _waitExecution()でポーリング確認、未約定時はキャンセル+state未更新
- [x] **#3 逆指値キャンセル失敗時の処理** — キャンセル失敗・決済注文失敗時はERRORを返しstate未更新
- [x] **#4 決済失敗後のエントリー抑止** — position未変更時はエントリーをスキップして早期リターン
- [x] **#5 パストラバーサル脆弱性** — resolve()+is_relative_to()でSIM_DIR配下か検証
- [x] **#6 Flask debug=True環境変数化** — FLASK_DEBUG環境変数で制御
- [x] **#7 L/S戦略のcalcMetrics修正** — type in ("sell", "close") でフィルタ
- [x] **#8 allocatedCapital計算修正** — availableJpy(JPY残高)ベースに変更

## 中程度

- [x] ショートエントリー時の手数料未差引 — capital -= fee を追加
- [x] ライブモードで未確定足のcloseでシグナル判定 — data.iloc[:-1]で確定足のみ使用
- [x] ライブステータスの初期資金10万円ハードコード — state["initialCapital"]を参照
- [ ] VWAPが日をまたいでリセットされない — `scalping/strategies.py:94-115`
- [x] APIキー未設定で空文字認証リクエスト — Private API呼出前に_checkApiKey()
- [ ] getBalance()のキー大文字小文字問題 — `gmo.py:98-107`
- [ ] グリッド戦略のcapitalPerGrid再計算でサイズ不整合 — `grid/__init__.py:147-157`
- [ ] API障害時リトライなし、O(N^2)メモリコピー — `fetch_btc.py:54-59`
- [ ] yfinance MultiIndex互換性 — `dual_momentum/fetch_data.py:44`
- [x] pnl==0がlosses扱い — `engine.py:220-224` → pnl < 0 のみlossesに変更

## 軽微

- [x] loadJsonでJSONDecodeError未処理 — try/exceptでNone返却
- [ ] 朝バッチでスタックトレース消失 — `batch_morning.py`
- [ ] optimize.py, paper_trade.pyの相対import — `btc/optimize.py:13`
- [ ] LINE Notify API終了済み — `notifier.py:93`
- [ ] tradesリスト上限なし — `engine.py:131`
- [ ] dryRun残高50,000円ハードコード — `engine.py:262`
- [x] calcCombinedSignalsのコメントと実装矛盾 — コメントを実装に合わせて修正
- [ ] fetch_btc.pyの重複 — `btc/` と `strategies/btc/`
