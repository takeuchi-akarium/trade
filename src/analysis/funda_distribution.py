import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'src'))

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from datetime import datetime


def fetch_btc_daily(days=1100):
    print(f"[1/5] BTC日足データ取得中 ({days}日分)...")
    url = "https://api.binance.com/api/v3/klines"
    all_candles = []
    end_ms = int(datetime.utcnow().timestamp() * 1000)
    remaining = days
    while remaining > 0:
        limit = min(1000, remaining)
        params = {"symbol": "BTCUSDT", "interval": "1d", "endTime": end_ms, "limit": limit}
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        candles = resp.json()
        if not candles:
            break
        all_candles = candles + all_candles
        end_ms = candles[0][0] - 1
        remaining -= len(candles)
        if len(candles) < limit:
            break
    df = pd.DataFrame(all_candles, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","quote_vol","trades","taker_buy_base","taker_buy_quote","ignore"
    ])
    df["date"] = pd.to_datetime(df["open_time"], unit="ms").dt.normalize()
    df["close"] = df["close"].astype(float)
    df = df[["date","close"]].drop_duplicates("date").sort_values("date").reset_index(drop=True)
    print(f"  -> {len(df)} 本取得")
    return df


def fetch_gold_history(years=5):
    print("[2/5] ゴールド先物データ取得中...")
    ticker = yf.Ticker("GC=F")
    df = ticker.history(period=f"{years}y", interval="1d", auto_adjust=True)
    s = df["Close"].dropna()
    s.index = pd.to_datetime(s.index).normalize().tz_localize(None)
    print(f"  -> {len(s)} 本取得")
    return s


def fetch_tnx_history(years=5):
    print("[3/5] 10年債利回りデータ取得中...")
    ticker = yf.Ticker("^TNX")
    df = ticker.history(period=f"{years}y", interval="1d", auto_adjust=True)
    s = df["Close"].dropna()
    s.index = pd.to_datetime(s.index).normalize().tz_localize(None)
    print(f"  -> {len(s)} 本取得")
    return s


def fetch_fng_history(days=1100):
    print("[4/5] Fear&Greed履歴取得中...")
    resp = requests.get("https://api.alternative.me/fng/", params={"limit": days}, timeout=30)
    resp.raise_for_status()
    data = resp.json()["data"]
    records = {
        pd.Timestamp(datetime.utcfromtimestamp(int(d["timestamp"]))).normalize(): int(d["value"])
        for d in data
    }
    s = pd.Series(records).sort_index()
    print(f"  -> {len(s)} 本取得")
    return s


def calc_funda_score(gold_arr, tnx_arr, fng_arr, window=90, use_gold=True):
    goldZ = 0.0
    if use_gold and len(gold_arr) >= 51:
        mom50 = (gold_arr[-1] / gold_arr[-51] - 1) * 100
        moms = [(gold_arr[i] / gold_arr[i - 50] - 1) * 100 for i in range(50, len(gold_arr))]
        if len(moms) >= 2:
            wm = moms[-min(window, len(moms)):]
            m, s = np.mean(wm), np.std(wm)
            goldZ = -(mom50 - m) / s if s > 0 else 0.0
    tnxZ = 0.0
    if len(tnx_arr) >= 21:
        chg20 = tnx_arr[-1] - tnx_arr[-21]
        chgs = [tnx_arr[i] - tnx_arr[i - 20] for i in range(20, len(tnx_arr))]
        if len(chgs) >= 2:
            wc = chgs[-min(window, len(chgs)):]
            m, s = np.mean(wc), np.std(wc)
            tnxZ = (chg20 - m) / s if s > 0 else 0.0
    fngZ = 0.0
    if len(fng_arr) >= 30:
        fng = np.array(fng_arr, dtype=float)
        revert = np.mean(fng[-7:]) - np.mean(fng[-30:])
        reverts = []
        for i in range(29, len(fng)):
            reverts.append(np.mean(fng[max(0,i-6):i+1]) - np.mean(fng[max(0,i-29):i+1]))
        if len(reverts) >= 2:
            wr = reverts[-min(window, len(reverts)):]
            m, s = np.mean(wr), np.std(wr)
            fngZ = (revert - m) / s if s > 0 else 0.0
    return 0.41 * goldZ + 0.37 * tnxZ + 0.22 * fngZ, goldZ, tnxZ, fngZ


def compute_rolling_scores(btc, gold, tnx, fng):
    print("[5/5] ローリングスコア計算中...")
    rows = []
    dates = btc["date"].tolist()
    n = len(dates)
    for idx, date in enumerate(dates):
        if idx % 100 == 0:
            print(f"  ... {idx}/{n}")
        g = gold[gold.index <= date].values[-150:]
        t = tnx[tnx.index <= date].values[-120:]
        f = fng[fng.index <= date].values[-120:]
        score_new, gZ, tZ, fZ = calc_funda_score(g, t, f, use_gold=True)
        score_old, _, _, _ = calc_funda_score(g, t, f, use_gold=False)
        rows.append({
            "date": date,
            "btc_close": btc.loc[idx, "close"],
            "score_new": score_new,
            "score_old": score_old,
            "goldZ": gZ,
            "tnxZ": tZ,
            "fngZ": fZ,
            "gold_len": len(g),
        })
    df = pd.DataFrame(rows).set_index("date")
    print(f"  -> 完了: {len(df)} 日分")
    return df


def print_stats(label, series):
    s = series.dropna()
    print(f"  {label}:")
    print(f"    count={len(s)}, mean={s.mean():.4f}, std={s.std():.4f}")
    print(f"    min={s.min():.4f}, max={s.max():.4f}")
    ps = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    pv = np.percentile(s, ps)
    pstr = "  ".join(f"p{p}={v:.3f}" for p, v in zip(ps, pv))
    print(f"    {pstr}")


def analyze(df):
    NL = chr(10)
    SEP = "=" * 65
    print(NL + SEP)
    print("  ファンダスコア 分布分析レポート")
    print(SEP)
    valid = df[df["gold_len"] >= 51].copy()
    print(NL + "有効サンプル数: {} 日 (gold_len>=51, 全体: {} 日)".format(len(valid), len(df)))
    print("期間: {} ~ {}".format(valid.index[0].date(), valid.index[-1].date()))

    print(NL + "[A] 基本統計量")
    print_stats("score_new (ゴールドあり)", valid["score_new"])
    print_stats("score_old (ゴールドなし)", valid["score_old"])
    print_stats("goldZ", valid["goldZ"])
    print_stats("tnxZ",  valid["tnxZ"])
    print_stats("fngZ",  valid["fngZ"])

    print(NL + "[B] 絶対値が閾値を超える頻度")
    s = valid["score_new"]
    n = len(s)
    print("  {:>6}  {:>8}  {:>6}  {:>8}".format("閾値", "頻度", "日数", "年換算"))
    print("  " + "-" * 40)
    for th in [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
        cnt = (s.abs() > th).sum()
        pct = cnt / n * 100
        annual = cnt / (n / 250)
        print("  |s|>{:.1f}   {:>7.1f}%  {:>6d}日  {:>7.1f}回/年".format(th, pct, cnt, annual))

    print(NL + "[C] 方向別 閾値発火頻度")
    for label, mask in [
        ("score > 0.3  (やや強気)",         s > 0.3),
        ("score > 0.5  (Boost)",            s > 0.5),
        ("score < -0.3 (やや弱気)",          s < -0.3),
        ("score < -0.5 (Early Transition)",  s < -0.5),
    ]:
        cnt = mask.sum()
        pct = cnt / n * 100
        annual = cnt / (n / 250)
        print("  {:<36}  {:>5.1f}%  {:4d}日  {:5.1f}回/年".format(label, pct, cnt, annual))

    print(NL + "[D] BTC 30日先リターンとの相関")
    ret30 = valid["btc_close"].pct_change(30).shift(-30)
    merged = pd.concat([valid[["score_new","goldZ","tnxZ","fngZ"]], ret30], axis=1)
    merged.columns = ["score_new","goldZ","tnxZ","fngZ","ret30"]
    merged = merged.dropna()
    print("  有効サンプル: {} 日".format(len(merged)))
    corr = merged.corr()
    for col in ["score_new","goldZ","tnxZ","fngZ"]:
        c = corr.loc[col, "ret30"]
        print("  {:<12} vs ret30: {:+.4f}".format(col, c))

    print(NL + "  スコア分位別 平均30日先リターン:")
    bins = [-float("inf"), -0.5, -0.3, 0.0, 0.3, 0.5, float("inf")]
    labels_bin = ["<-0.5","[-0.5,-0.3)","[-0.3,0)","[0,0.3)","[0.3,0.5)",">=0.5"]
    merged["score_bin"] = pd.cut(merged["score_new"], bins=bins, labels=labels_bin)
    summary = merged.groupby("score_bin", observed=False)["ret30"].agg(["mean","std","count"])
    print("  {:15} {:>5} {:>9} {:>9}".format("区間","N","平均30d%","+/-std%"))
    print("  " + "-" * 45)
    for lbl, row in summary.iterrows():
        print("  {:<15} {:>5} {:>+8.1f}%  +/-{:.1f}%".format(
            str(lbl), int(row["count"]), row["mean"]*100, row["std"]*100))

    print(NL + "[E] ゴールドあり(新) vs ゴールドなし(旧)")
    diff = valid["score_new"] - valid["score_old"]
    print("  score_new - score_old: mean={:+.4f}, std={:.4f}".format(diff.mean(), diff.std()))
    print("  goldZ の寄与(weight=0.41): mean={:+.4f}, std={:.4f}".format(
        valid["goldZ"].mean(), valid["goldZ"].std()))
    large_diff = valid[diff.abs() > 0.3]
    print("  旧新スコア差 |diff|>0.3 の日数: {} ({:.1f}%)".format(
        len(large_diff), len(large_diff)/len(valid)*100))
    print(NL + "  {:20} {:>16} {:>16}".format("条件", "新(ゴールドあり)", "旧(ゴールドなし)"))
    print("  " + "-" * 55)
    for label, mask_new, mask_old in [
        ("score > 0.3",  s > 0.3,  valid["score_old"] > 0.3),
        ("score > 0.5",  s > 0.5,  valid["score_old"] > 0.5),
        ("score < -0.3", s < -0.3, valid["score_old"] < -0.3),
        ("score < -0.5", s < -0.5, valid["score_old"] < -0.5),
    ]:
        new_pct = mask_new.sum() / n * 100
        old_pct = mask_old.sum() / n * 100
        print("  {:<20} {:>14.1f}%  {:>14.1f}%".format(label, new_pct, old_pct))

    print(NL + "[F] 閾値設定の考察")
    for th in [0.3, 0.4, 0.5, 0.6]:
        up_pct = (s > th).sum() / n * 100
        dn_pct = (s < -th).sum() / n * 100
        print("  +/-{:.1f}: 強気={:.1f}%, 弱気={:.1f}%, 合計={:.1f}%".format(
            th, up_pct, dn_pct, up_pct+dn_pct))

    print(NL + "[G] 直近20日のスコア")
    print("  {:12} {:>10} {:>8} {:>8} {:>8}".format("日付","score_new","goldZ","tnxZ","fngZ"))
    print("  " + "-" * 52)
    for dt, row in valid.tail(20).iterrows():
        print("  {:<12} {:>+9.3f}  {:>+7.3f}  {:>+7.3f}  {:>+7.3f}".format(
            str(dt.date()), row["score_new"], row["goldZ"], row["tnxZ"], row["fngZ"]))

    print(NL + SEP)
    return valid


if __name__ == "__main__":
    btc  = fetch_btc_daily(days=1100)
    gold = fetch_gold_history(years=5)
    tnx  = fetch_tnx_history(years=5)
    fng  = fetch_fng_history(days=1100)
    df   = compute_rolling_scores(btc, gold, tnx, fng)

    out_dir = ROOT / "data" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "funda_distribution.csv"
    df.to_csv(out_path)
    print("\n[保存] " + str(out_path))

    analyze(df)
