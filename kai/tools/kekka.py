# -*- coding: utf-8 -*-
"""普段の回の結果を、保管庫に残す形（Markdown）で出す。受け口の点数と kai/taikai.json・kai/kumiawase.json から、
点数ページと同じ決まりで予選の集計と最終順位を計算する（決まりの正典は kai/README.md の「計算のきまり」）。
名前は受け口の名簿から読む＝出力には名前が入る。公開リポに置かず、保管庫へだけ書く。

使い方:
  python kai/tools/kekka.py                    … 受け口から読んで、標準出力に出す
  python kai/tools/kekka.py --data 控え.json   … 受け口の返事（GET の JSON）を保存したファイルから出す（試験用）
  --config / --kumi は試験用（既定は kai/taikai.json と kai/kumiawase.json）"""
import argparse, functools, json, sys, urllib.parse, urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
KAI = Path(__file__).resolve().parents[1]
WINDS = ["東", "南", "西", "北"]
pn = lambda p: int(p[1:])


def fpt(n):
    """0.1ポイント単位の整数を、点数ページと同じ形（+12.3／−4.0／0.0）にする"""
    return ("+" if n > 0 else "−" if n < 0 else "") + f"{abs(n) / 10:,.1f}"


def table_pts(raws, cfg):
    """1卓のポイント（0.1単位）。順位点は返し以上の人数で選ぶ（表のとき）。1位にオカ。同点は分けて、余りは起家に近い方へ"""
    M, ret = cfg["mode"], cfg["return"]
    if len(raws) != M:
        return [None] * len(raws)
    u = cfg["uma"]
    if isinstance(u, dict):
        u = u.get(str(sum(1 for r in raws if r >= ret)), u["1"])
    oka = (ret - cfg["start"]) * M // 100
    bonus = [round(x * 10) + (oka if i == 0 else 0) for i, x in enumerate(u)]
    order = sorted(range(M), key=lambda i: (-raws[i], i))
    pts, k = [None] * M, 0
    while k < M:
        j = k
        while j + 1 < M and raws[order[j + 1]] == raws[order[k]]:
            j += 1
        s, n = sum(bonus[k:j + 1]), j - k + 1
        base, rem = s // n, s - (s // n) * n
        for m in range(k, j + 1):
            i = order[m]
            pts[i] = (raws[i] - ret) // 100 + base + (1 if m - k < rem else 0)
        k = j + 1
    return pts


def fetch(cfg):
    api = str(cfg.get("api") or "").strip()
    if not api:
        raise SystemExit("taikai.json の api が空（受け口が未設定）。--data で控えのファイルを渡す")
    url = api + ("&" if "?" in api else "?") + "kai=" + urllib.parse.quote(cfg["kai"])
    with urllib.request.urlopen(url, timeout=30) as r:
        j = json.loads(r.read().decode("utf-8"))
    if not j.get("ok"):
        raise SystemExit(f"受け口がエラーを返した: {j.get('error')}")
    return j["data"]


def build(cfg, kumi, data):
    M, R = cfg["mode"], cfg["prelim"]
    H = cfg["final"]["hanchan"] if cfg["final"]["tables"] > 0 else 0
    prelim = [str(i) for i in range(1, R + 1)]
    finals = [f"F{i}" for i in range(1, H + 1)]
    rounds, roster = data.get("rounds") or {}, data.get("roster") or {}
    dn = lambda p: f"{roster[p]}（{p}）" if roster.get(p) else p
    players = {f"P{i}" for i in range(1, cfg["players"] + 1)}
    for r in rounds.values():
        for rec in r.values():
            players |= set(rec.get("p", []))
    tot, cnt, by = {p: 0 for p in players}, {p: 0 for p in players}, {p: {} for p in players}
    for r in prelim:
        for rec in (rounds.get(r) or {}).values():
            for p, v in zip(rec["p"], table_pts(rec["raw"], cfg)):
                if v is None:
                    continue
                tot[p] += v
                cnt[p] += 1
                by[p][r] = v
    rk = sorted(players, key=lambda p: (-tot[p], pn(p)))
    prank = {}
    for i, p in enumerate(rk):
        prank[p] = prank[rk[i - 1]] if i and tot[rk[i - 1]] == tot[p] else i + 1
    # 決勝: 決勝の点数が入った人を上に。1半荘なら素点、複数なら決勝のポイント合計。卓をまたいで比べ、同点は予選の順位（1半荘の同じ卓は起家に近い方）
    fin = {}
    for r in finals:
        for t, rec in (rounds.get(r) or {}).items():
            for s, (p, v) in enumerate(zip(rec["p"], table_pts(rec["raw"], cfg))):
                f = fin.setdefault(p, {"p": p, "pts": 0, "n": 0, "raw": None, "table": t, "seat": s})
                if v is None:
                    continue
                f["pts"] += v
                f["n"] += 1
                if r == "F1":
                    f["raw"], f["table"], f["seat"] = rec["raw"][s], t, s
    single = H == 1
    score = lambda f: (f["raw"] if f["raw"] is not None else float("-inf")) if single else (f["pts"] if f["n"] else float("-inf"))

    def cmp(a, b):
        if score(a) != score(b):
            return -1 if score(a) > score(b) else 1
        if single and a["table"] == b["table"]:
            return a["seat"] - b["seat"]
        return prank[a["p"]] - prank[b["p"]]
    fl = sorted(fin.values(), key=functools.cmp_to_key(lambda a, b: cmp(a, b) or pn(a["p"]) - pn(b["p"])))
    rows = []
    for i, f in enumerate(fl):
        same = i > 0 and cmp(fl[i - 1], f) == 0
        if same:
            rows[-1]["tie"] = True
        rows.append({"rank": rows[-1]["rank"] if same else i + 1, "tie": same, "p": f["p"], "how": "決勝",
                     "val": (f"{f['raw']:,}点" if f["raw"] is not None else "") if single else f"{fpt(f['pts'])}（{f['n']}/{H}）"})
    K, rest = len(rows), [p for p in rk if p not in fin]
    for j, p in enumerate(rest):
        same = j > 0 and tot[rest[j - 1]] == tot[p]
        if same:
            rows[-1]["tie"] = True
        rows.append({"rank": rows[-1]["rank"] if same else K + j + 1, "tie": same, "p": p, "how": "予選", "val": fpt(tot[p]) if cnt[p] else ""})
    # 入力のそろい具合（組み合わせ表の卓の数。表がなければ人数から）
    kr = (kumi or {}).get("rounds") or {}
    want = {r: len((kr.get(r) or {}).get("tables") or []) or len(players) // M for r in prelim}
    want.update({r: cfg["final"]["tables"] for r in finals})
    short = [f"{r}半荘目 {len(rounds.get(r) or {})}/{want[r]}卓" if r.isdigit() else f"決勝{r[1:]} {len(rounds.get(r) or {})}/{want[r]}卓"
             for r in prelim + finals if len(rounds.get(r) or {}) < want[r]]
    rest_by = {r: (kr.get(r) or {}).get("rest", []) for r in prelim}
    out_by = {r: (kr.get(r) or {}).get("out", []) for r in prelim}
    out_last = (kr.get(prelim[-1]) or {}).get("out", [])
    # 出力
    L = [f"# Halu杯 普段の回 {cfg.get('date') or cfg['kai']}", ""]
    rule = f"{M}麻・予選{R}半荘" + (f"・決勝{cfg['final']['tables']}卓{H}半荘" if H else "") + f"・{cfg['start']:,}点持ち{cfg['return']:,}点返し"
    L += [f"- {cfg.get('title', '')}（{rule}）。", f"- 出席 {len(players)}人。点数の最終更新 {data.get('updated') or '―'}。"]
    if out_last:
        L.append(f"- 途中で抜けた人: {'・'.join(dn(p) for p in out_last)}。")
    L.append("- 点数がそろっていない半荘: " + ("、".join(short) if short else "なし") + "。")
    L += ["", "## 最終順位", "", "| 順位 | 名前 | 決め方 | 点 |", "|---|---|---|---|"]
    for x in rows:
        win = "　優勝" if x["rank"] == 1 and not x["tie"] and not short else ""
        L.append(f"| {x['rank']}{' 同点' if x['tie'] else ''} | {dn(x['p'])}{win} | {x['how']} | {x['val']} |")
    L += ["", "## 予選の集計", "", "| 順位 | 名前 | " + " | ".join(prelim) + " | 合計 |", "|---|---|" + "---|" * len(prelim) + "---|"]
    for p in rk:
        cells = [fpt(by[p][r]) if r in by[p] else ("抜け" if p in rest_by[r] else "お休み" if p in out_by[r] else "") for r in prelim]
        tie = cnt[p] > 0 and any(q != p and cnt[q] > 0 and tot[q] == tot[p] for q in players)
        L.append(f"| {prank[p]}{' 同点' if tie else ''} | {dn(p)} | " + " | ".join(cells) + f" | {fpt(tot[p]) if cnt[p] else ''} |")
    L += ["", "## 卓ごとの点棒", ""]
    for r in prelim + finals:
        recs = rounds.get(r) or {}
        if not recs:
            continue
        L.append(f"- {r + '半荘目' if r.isdigit() else '決勝' + r[1:]}: " + "／".join(
            f"{t}卓 " + "・".join(f"{WINDS[i]}{dn(p)} {recs[t]['raw'][i]:,}" for i, p in enumerate(recs[t]["p"])) for t in sorted(recs, key=int)))
    return "\n".join(L) + "\n", rows


def main():
    ap = argparse.ArgumentParser(description="普段の回の結果を保管庫に残す形で出す")
    ap.add_argument("--config", default=str(KAI / "taikai.json"))
    ap.add_argument("--kumi", default=str(KAI / "kumiawase.json"))
    ap.add_argument("--data", help="受け口の返事（GET の JSON。data の中身か、{ok, data} のどちらでもよい）")
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    kp = Path(a.kumi)
    kumi = json.loads(kp.read_text(encoding="utf-8")) if kp.exists() else None
    if kumi and kumi.get("kai") != cfg["kai"]:
        kumi = None
    if a.data:
        d = json.loads(Path(a.data).read_text(encoding="utf-8"))
        data = d.get("data", d)
    else:
        data = fetch(cfg)
    if data.get("kai") not in (None, cfg["kai"]):
        raise SystemExit(f"受け口の回（{data.get('kai')}）が大会設定（{cfg['kai']}）と違う")
    text, _ = build(cfg, kumi, data)
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
