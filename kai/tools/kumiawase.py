# -*- coding: utf-8 -*-
"""普段の回の組み合わせ（会ごとの kai/g/<会>/kumiawase.json）を作る。人数・半荘数・3麻か4麻か・卓番号は同じフォルダの taikai.json から読む。
・同じ相手とはできるだけ当たらない（当たる回数を全員にならす。下限より多くは当てない）
・抜け番は、それまでに多く打った人から回す（休む回数がそろう。続けて休む人はできるだけ出さない）
・席の風（東南西北）を、一人ひとりできるだけ均等にする
・卓番号は、同じ卓に続けて座らないよう散らす
乱数の種は回の名前と引数から作る＝同じ引数なら何度作っても同じ表（--seed で別の表）。

使い方:
  python kai/tools/kumiawase.py                      … 作って成績を出すだけ（何も書かない）
  python kai/tools/kumiawase.py --write              … 前日: kumiawase.json に書く（早川研は --group hayakawa を足す）
  python kai/tools/kumiawase.py --from 3 --absent P5 --write
                                                     … 当日: 3半荘目から組み直す（1・2半荘目はそのまま。P5 は抜けた）
                                                       増えた人は taikai.json の players を増やしてから
  python kai/tools/kumiawase.py --check              … いまの kumiawase.json を検査し、成績を出す
  --group で会を選ぶ（既定は halu）。--config / --out は試験用（既定は kai/g/<会>/taikai.json と kumiawase.json）"""
import argparse, hashlib, itertools, json, math, random, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")  # cp932コンソールでの文字化け回避
KAI = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
WINDS = ["東", "南", "西", "北"]
P_RE = re.compile(r"^P([1-9]|[1-9][0-9])$")
NMAX = 100   # P1〜P99


def pnum(p):
    m = P_RE.match(str(p))
    if not m:
        raise SystemExit(f"プレイヤーの形が違う: {p!r}（P1〜P99）")
    return int(m.group(1))


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def table_nos(cfg, n):
    """卓番号の呼び名。設定の tables が足りていればその先頭から、なければ1から（点数ページと同じ決まり）"""
    t = cfg.get("tables") or []
    return list(t[:n]) if len(t) >= n else list(range(1, n + 1))


class Hist:
    """それまでの半荘の積み上げ（同じ相手と当たった回数・風・抜け番・打った数・座った卓）"""
    def __init__(self):
        self.meets = [[0] * NMAX for _ in range(NMAX)]
        self.wind = [[0] * 4 for _ in range(NMAX)]
        self.played = [0] * NMAX
        self.rested = [0] * NMAX
        self.tab = [dict() for _ in range(NMAX)]
        self.last_rest = set()

    def add(self, rnd):
        for t in rnd["tables"]:
            ps = t["p"]
            for i, a in enumerate(ps):
                self.wind[a][i] += 1
                self.played[a] += 1
                self.tab[a][t["no"]] = self.tab[a].get(t["no"], 0) + 1
                for b in ps[i + 1:]:
                    self.meets[a][b] += 1
                    self.meets[b][a] += 1
        for p in rnd["rest"]:
            self.rested[p] += 1
        self.last_rest = set(rnd["rest"])


def pick_rests(present, k, hist, nrounds, rng):
    """半荘ごとの抜け番。それまでに多く打った人から休む。同じなら前の半荘に休んでいない人、そのあとは乱数"""
    played = hist.played[:]
    last = set(hist.last_rest)
    out = []
    for _ in range(nrounds):
        order = sorted(present, key=lambda p: (-played[p], p in last, rng.random()))
        rest = sorted(order[:k])
        for p in order[k:]:
            played[p] += 1
        out.append(rest)
        last = set(rest)
    return out


def pair_cost(meets, players):
    return sum(meets[a][b] ** 2 for a, b in itertools.combinations(players, 2))


def partition(seated_by_round, M, hist, rng, players, iters_per_round=30000, restarts=6):
    """卓分け。同じ相手と当たった回数の2乗の和を、焼きなましで小さくする（回数をならす＝重なりを減らす）"""
    best, best_cost = None, None
    for _ in range(restarts):
        meets = [row[:] for row in hist.meets]
        state = []
        for seated in seated_by_round:
            s = seated[:]
            rng.shuffle(s)
            tabs = [s[i * M:(i + 1) * M] for i in range(len(s) // M)]
            for t in tabs:
                for a, b in itertools.combinations(t, 2):
                    meets[a][b] += 1
                    meets[b][a] += 1
            state.append(tabs)
        movable = [r for r, tabs in enumerate(state) if len(tabs) >= 2]
        iters = iters_per_round * len(state)
        t0, t1 = 2.0, 0.02
        for it in range(iters if movable else 0):
            temp = t0 * (t1 / t0) ** (it / iters)
            tabs = state[rng.choice(movable)]
            i, j = rng.sample(range(len(tabs)), 2)
            A, B = tabs[i], tabs[j]
            ai, bj = rng.randrange(M), rng.randrange(M)
            a, b = A[ai], B[bj]
            d = 0
            for x in A:
                if x != a:
                    d += (1 - 2 * meets[a][x]) + (2 * meets[b][x] + 1)
            for y in B:
                if y != b:
                    d += (1 - 2 * meets[b][y]) + (2 * meets[a][y] + 1)
            if d <= 0 or rng.random() < math.exp(-d / temp):
                for x in A:
                    if x != a:
                        meets[a][x] -= 1; meets[x][a] -= 1
                        meets[b][x] += 1; meets[x][b] += 1
                for y in B:
                    if y != b:
                        meets[b][y] -= 1; meets[y][b] -= 1
                        meets[a][y] += 1; meets[y][a] += 1
                A[ai], B[bj] = b, a
        c = pair_cost(meets, players)
        if best_cost is None or c < best_cost:
            best, best_cost = [[t[:] for t in tabs] for tabs in state], c
    return best


def seat_winds(state, M, hist, rng, iters=60000):
    """卓の中の席の順（東から）。一人ひとりの風の回数の2乗の和を小さくする（均等に近づける）"""
    wind = [row[:] for row in hist.wind]
    tables = [t for tabs in state for t in tabs]
    for t in tables:
        rng.shuffle(t)
        for i, p in enumerate(t):
            wind[p][i] += 1
    if not tables:
        return
    t0, t1 = 1.5, 0.02
    for it in range(iters):
        temp = t0 * (t1 / t0) ** (it / iters)
        t = rng.choice(tables)
        i, j = rng.sample(range(M), 2)
        a, b = t[i], t[j]
        d = (1 - 2 * wind[a][i]) + (2 * wind[a][j] + 1) + (1 - 2 * wind[b][j]) + (2 * wind[b][i] + 1)
        if d <= 0 or rng.random() < math.exp(-d / temp):
            wind[a][i] -= 1; wind[a][j] += 1
            wind[b][j] -= 1; wind[b][i] += 1
            t[i], t[j] = b, a


def number_tables(state, nos, hist, rng, iters=30000):
    """卓番号を付ける。一人ひとりが同じ卓に座る回数の3乗の和を、全部の半荘を通して小さくする（卓を散らす）。
    2乗の和だと、同じ和で最多の回数が多い付け方と区別できない（16人5半荘・9人3半荘で確かめた）ため3乗にした"""
    up = lambda c: 3 * c * c + 3 * c + 1        # c → c+1 で増える分
    down = lambda c: -(3 * c * c - 3 * c + 1)   # c → c−1 で増える分（負）
    tab = [dict(d) for d in hist.tab]
    num = []
    for tabs in state:
        perm = nos[:len(tabs)]
        rng.shuffle(perm)
        num.append(perm)
        for i, t in enumerate(tabs):
            for p in t:
                tab[p][perm[i]] = tab[p].get(perm[i], 0) + 1
    movable = [r for r, tabs in enumerate(state) if len(tabs) >= 2]
    t0, t1 = 1.5, 0.02
    for it in range(iters if movable else 0):
        temp = t0 * (t1 / t0) ** (it / iters)
        r = rng.choice(movable)
        i, j = rng.sample(range(len(state[r])), 2)
        u, v = num[r][i], num[r][j]
        d = sum(up(tab[p].get(v, 0)) + down(tab[p][u]) for p in state[r][i])
        d += sum(up(tab[p].get(u, 0)) + down(tab[p][v]) for p in state[r][j])
        if d <= 0 or rng.random() < math.exp(-d / temp):
            for p in state[r][i]:
                tab[p][u] -= 1; tab[p][v] = tab[p].get(v, 0) + 1
            for p in state[r][j]:
                tab[p][v] -= 1; tab[p][u] = tab[p].get(u, 0) + 1
            num[r][i], num[r][j] = v, u
    return [sorted(({"no": num[r][i], "p": t[:]} for i, t in enumerate(tabs)), key=lambda x: x["no"]) for r, tabs in enumerate(state)]


def to_ints(rnd):
    return {"tables": [{"no": int(t["no"]), "p": [pnum(p) for p in t["p"]]} for t in rnd.get("tables", [])],
            "rest": [pnum(p) for p in rnd.get("rest", [])], "out": [pnum(p) for p in rnd.get("out", [])]}


def to_strs(rnd):
    o = {"tables": [{"no": t["no"], "p": ["P%d" % p for p in t["p"]]} for t in rnd["tables"]], "rest": ["P%d" % p for p in rnd["rest"]]}
    if rnd.get("out"):
        o["out"] = ["P%d" % p for p in rnd["out"]]
    return o


def dump(obj):
    """1卓を1行にして書く（人が読んで確かめやすいように）。中身は json.loads で元に戻る"""
    j = lambda v: json.dumps(v, ensure_ascii=False)
    lines = ["{", f'  "kai": {j(obj["kai"])},', f'  "made": {j(obj["made"])},', f'  "from": {obj["from"]},', '  "rounds": {']
    keys = sorted(obj["rounds"], key=int)
    for ki, k in enumerate(keys):
        r = obj["rounds"][k]
        lines.append(f'    {j(k)}: {{')
        lines.append('      "tables": [')
        lines += [f'        {j(t)}' + ("," if i < len(r["tables"]) - 1 else "") for i, t in enumerate(r["tables"])]
        tail = [f'      "rest": {j(r["rest"])}'] + ([f'      "out": {j(r["out"])}'] if r.get("out") else [])
        lines.append("      ],")
        lines += [x + ("," if i < len(tail) - 1 else "") for i, x in enumerate(tail)]
        lines.append("    }" + ("," if ki < len(keys) - 1 else ""))
    lines += ["  }", "}", ""]
    s = "\n".join(lines)
    if json.loads(s) != obj:
        raise SystemExit("書き出しの形が崩れた（dump の不具合）")
    return s


def check_cfg(cfg):
    if not cfg:
        raise SystemExit("大会設定（taikai.json）が読めない")
    for k in ("kai", "mode", "players", "prelim"):
        if k not in cfg:
            raise SystemExit(f"大会設定に {k} がない")
    if cfg["mode"] not in (3, 4):
        raise SystemExit("mode は 3 か 4")
    if not (isinstance(cfg["players"], int) and cfg["mode"] <= cfg["players"] <= 99):
        raise SystemExit("players は mode〜99")
    if not (isinstance(cfg["prelim"], int) and 1 <= cfg["prelim"] <= 20):
        raise SystemExit("prelim は 1〜20")


def validate(cfg, kumi, absent=()):
    """組み合わせの形を検査する。問題の一覧を返す（空なら問題なし）"""
    M, errs = cfg["mode"], []
    if not kumi or not isinstance(kumi.get("rounds"), dict):
        return ["rounds がない"]
    if kumi.get("kai") != cfg["kai"]:
        errs.append(f'kai が大会設定と違う（{kumi.get("kai")} と {cfg["kai"]}）')
    for k, r in kumi["rounds"].items():
        if not re.fullmatch(r"[1-9]|1[0-9]|20", k) or int(k) > cfg["prelim"]:
            errs.append(f"{k}半荘目: 予選の半荘数（{cfg['prelim']}）の外")
            continue
        seen, nos = [], []
        for t in r.get("tables", []):
            nos.append(t.get("no"))
            if not (isinstance(t.get("no"), int) and 1 <= t["no"] <= 40):
                errs.append(f"{k}半荘目: 卓番号が 1〜40 でない（{t.get('no')}）")
            if len(t.get("p", [])) != M:
                errs.append(f"{k}半荘目 {t.get('no')}卓: {M}人でない")
            seen += list(t.get("p", []))
        if len(set(nos)) != len(nos):
            errs.append(f"{k}半荘目: 同じ卓番号が2つある")
        rest, out = list(r.get("rest", [])), list(r.get("out", []))
        allp = seen + rest + out
        bad = [p for p in allp if not P_RE.match(str(p))]
        if bad:
            errs.append(f"{k}半荘目: プレイヤーの形が違う {bad}")
            continue
        dup = sorted({p for p in allp if allp.count(p) > 1}, key=pnum)
        if dup:
            errs.append(f"{k}半荘目: 同じ人が2か所にいる {dup}")
        if len(rest) >= M:
            errs.append(f"{k}半荘目: 抜け番が{len(rest)}人（{M}人いればもう1卓できる）")
        over = [p for p in allp if pnum(p) > cfg["players"]]
        if over:
            errs.append(f"{k}半荘目: players（{cfg['players']}）より大きい番号 {over}")
    return errs


def report(cfg, rounds):
    """成績: 同じ相手と2回以上当たった組・風・抜け番・同じ卓"""
    M = cfg["mode"]
    h = Hist()
    keys = sorted(rounds, key=int)
    for k in keys:
        h.add(to_ints(rounds[k]))
    everyone = sorted({p for k in keys for t in to_ints(rounds[k])["tables"] for p in t["p"]} | {p for k in keys for p in to_ints(rounds[k])["rest"]})
    pairs = [(a, b, h.meets[a][b]) for a, b in itertools.combinations(everyone, 2)]
    rep = sorted([x for x in pairs if x[2] >= 2], key=lambda x: -x[2])
    # 余分に当たった回数（2回目からを数える）と、その下限（当たる回数の合計が、組の数を超えた分は必ず余分になる）
    slots = sum(len(rounds[k]["tables"]) for k in keys) * M * (M - 1) // 2
    over = sum(m - 1 for _, _, m in pairs if m >= 2)
    lower = max(0, slots - len(pairs))
    print(f"■ 成績（{len(keys)}半荘・{len(everyone)}人・{M}麻）")
    print(f"  同じ相手と2回以上: {len(rep)}組" + (f"（最多 {rep[0][2]}回）" if rep else "") + f"　余分に当たった回数 {over}（下限 {lower}）")
    if rep:
        print("    " + "・".join(f"P{a}-P{b}×{m}" for a, b, m in rep[:20]) + (" …" if len(rep) > 20 else ""))
    spread = max(max(h.wind[p][:M]) - min(h.wind[p][:M]) for p in everyone) if everyone else 0
    print(f"  風の偏り（一人の中で最多と最少の差）: 最大 {spread}")
    pl = [h.played[p] for p in everyone]
    rs = [h.rested[p] for p in everyone]
    print(f"  打つ半荘: {min(pl)}〜{max(pl)}　抜け番: {min(rs)}〜{max(rs)}回")
    same = max((max(h.tab[p].values()) for p in everyone if h.tab[p]), default=0)
    print(f"  同じ卓に座る回数: 最多 {same}回")
    print("  一人ずつ（打った・抜け・風 " + "".join(WINDS[:M]) + "・当たった人数）:")
    for p in everyone:
        opp = sum(1 for q in everyone if q != p and h.meets[p][q] > 0)
        print(f"    P{p:<3} {h.played[p]}・{h.rested[p]}・" + "".join(str(x) for x in h.wind[p][:M]) + f"・{opp}人")
    return {"repeats": len(rep), "max_meet": max((m for _, _, m in pairs), default=0), "over": over,
            "lower": lower, "wind_spread": spread, "played": (min(pl), max(pl)), "rested": (min(rs), max(rs)), "same_table": same}


def show(cfg, rounds):
    for k in sorted(rounds, key=int):
        r = rounds[k]
        print(f"■ {k}半荘目")
        for t in r["tables"]:
            print(f"  {t['no']:>2}卓  " + "  ".join(f"{WINDS[i]} {p:<4}" for i, p in enumerate(t["p"])))
        if r.get("rest"):
            print("  抜け番 " + "・".join(r["rest"]))
        if r.get("out"):
            print("  お休み " + "・".join(r["out"]))


def make(cfg, kumi_old, start, absent, seed):
    M, R = cfg["mode"], cfg["prelim"]
    hist, rounds = Hist(), {}
    if start > 1:
        if not kumi_old or kumi_old.get("kai") != cfg["kai"]:
            raise SystemExit("組み直しは、同じ回の kumiawase.json がいる（kai が違うか、ファイルがない）")
        for k in range(1, start):
            if str(k) not in kumi_old.get("rounds", {}):
                raise SystemExit(f"{k}半荘目の表がない（--from {start} にはそこまでの表がいる）")
            rounds[str(k)] = kumi_old["rounds"][str(k)]
            hist.add(to_ints(kumi_old["rounds"][str(k)]))
    out = sorted(pnum(p) for p in absent)
    present = [p for p in range(1, cfg["players"] + 1) if p not in out]
    if len(present) < M:
        raise SystemExit(f"打てる人が{len(present)}人で、{M}人に足りない")
    n_tab, k_rest = len(present) // M, len(present) % M
    key = f"{cfg['kai']}|from={start}|absent={','.join(map(str, out))}|players={cfg['players']}|mode={M}|prelim={R}|seed={seed}"
    rng = random.Random(int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16))
    nr = R - start + 1
    rests = pick_rests(present, k_rest, hist, nr, rng)
    seated = [[p for p in present if p not in rs] for rs in rests]
    state = partition(seated, M, hist, rng, present)
    seat_winds(state, M, hist, rng)
    numbered = number_tables(state, table_nos(cfg, n_tab), hist, rng)
    for i in range(nr):
        rounds[str(start + i)] = to_strs({"tables": numbered[i], "rest": rests[i], "out": [p for p in out if p <= cfg["players"]]})
    return {"kai": cfg["kai"], "made": datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "from": start, "rounds": rounds}


def main():
    ap = argparse.ArgumentParser(description="普段の回の組み合わせを作る")
    ap.add_argument("--group", default="halu", help="会（kai/g/<会>/ の設定を使う。既定は halu）")
    ap.add_argument("--config")
    ap.add_argument("--out")
    ap.add_argument("--from", dest="start", type=int, default=1, help="この半荘から作る（前の半荘はそのまま）")
    ap.add_argument("--absent", default="", help="打たない人（カンマ区切り。例 P5,P9）")
    ap.add_argument("--seed", default="", help="別の組み合わせにしたいときの種")
    ap.add_argument("--write", action="store_true", help="kumiawase.json に書く")
    ap.add_argument("--check", action="store_true", help="いまの kumiawase.json を検査して成績を出す")
    ap.add_argument("--quiet", action="store_true", help="表と一人ずつの成績を出さない")
    a = ap.parse_args()
    if not re.fullmatch(r"[a-z0-9-]{1,20}", a.group):
        raise SystemExit("--group は英小文字・数字・- で20字まで")
    gdir = KAI / "g" / a.group
    a.config = a.config or str(gdir / "taikai.json")
    a.out = a.out or str(gdir / "kumiawase.json")
    cfg = load(a.config)
    check_cfg(cfg)
    old = load(a.out)
    if a.check:
        errs = validate(cfg, old)
        if errs:
            print("■ 問題あり"); [print("  " + e) for e in errs]
            sys.exit(1)
        print("■ 形は問題なし")
        if old["rounds"]:
            if not a.quiet:
                show(cfg, old["rounds"])
            report(cfg, old["rounds"])
        return
    if not (1 <= a.start <= cfg["prelim"]):
        raise SystemExit(f"--from は 1〜{cfg['prelim']}")
    absent = [s.strip() for s in a.absent.split(",") if s.strip()]
    kumi = make(cfg, old, a.start, absent, a.seed)
    errs = validate(cfg, kumi)
    if errs:
        print("■ 作った表に問題あり（書きません）"); [print("  " + e) for e in errs]
        sys.exit(1)
    if not a.quiet:
        show(cfg, kumi["rounds"])
    report(cfg, kumi["rounds"])
    if a.write:
        Path(a.out).write_text(dump(kumi), encoding="utf-8")
        print(f"書きました: {a.out}")
    else:
        print("（書いていません。--write で書きます）")


if __name__ == "__main__":
    main()
