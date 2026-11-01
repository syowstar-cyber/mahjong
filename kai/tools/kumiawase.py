# -*- coding: utf-8 -*-
"""普段の回の組み合わせ（会ごとの kai/g/<会>/kumiawase.json）を作る。人数・半荘数・3麻か4麻か・卓番号は同じフォルダの taikai.json から読む。
・同じ相手とはできるだけ当たらない（当たる回数を全員にならす。下限より多くは当てない）
・抜け番は、それまでに多く打った人から回す（休む回数がそろう。続けて休む人はできるだけ出さない）
・席の風（東南西北）を、一人ひとりできるだけ均等にする
・卓番号は、同じ卓に続けて座らないよう散らす
乱数の種は回の名前と引数から作る＝同じ引数なら何度作っても同じ表（--seed で別の表）。
くじの会（taikai.json の kuji＝抽せんの日）は、抽せんの前に型（kata.json。P番号の代わりに枠1〜枠N）だけを作り、
誰がどの枠に入るかを、その日のナンバーズ4の当せん番号で決める（kai/tools/kuji.py。第20回と同じ仕組み）。

使い方:
  python kai/tools/kumiawase.py                      … 作って成績を出すだけ（何も書かない）
  python kai/tools/kumiawase.py --write              … 前日: kumiawase.json に書く（早川研は --group hayakawa を足す）
                                                       くじの会の抽せんの前は、kata.json（型）と、表が空の kumiawase.json を書く
                                                       （来られなくなった人は --absent P5 でくじから外す。抽せんの日の18時から後は書かない）
  python kai/tools/kumiawase.py --from 3 --absent P5 --write
                                                     … 当日: 3半荘目から組み直す（1・2半荘目はそのまま。P5 は抜けた）
                                                       増えた人は taikai.json の players を増やしてから
                                                       くじの会の抽せんの後は、枠の並びに戻して組み直す（くじで決まった枠を保つ）
                                                       型で外した人が来たら --back P5（外したときの枠で入る）
  python kai/tools/kumiawase.py --check              … いまの kumiawase.json を検査し、成績を出す（くじの会の抽せんの前は型）
  --group で会を選ぶ（既定は halu）。--config / --out / --kata は試験用（既定は kai/g/<会>/ の taikai.json・kumiawase.json・kata.json）"""
import argparse, hashlib, itertools, json, math, random, re, sys, unicodedata
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
    """卓番号の呼び名。設定の tables が足りていればその先頭から、なければ1から（点数入力ページと同じ決まり）"""
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


# ---- くじ（kai/kuji/index.html と同じ計算。kuji.py もここを使う） ----
def norm_n4(s):
    """当せん番号の書き方をそろえる（全角は半角に。先頭の0も残して4桁）"""
    s = re.sub(r"\s", "", unicodedata.normalize("NFKC", str(s)))
    if not re.fullmatch(r"\d{4}", s):
        raise SystemExit(f"ナンバーズ4の当せん番号の形が違う: {s!r}（4桁。例 0482）")
    return s


def kuji_seed(kata, n4):
    """くじの種＝回の名前・抽せんの日・当せん番号（例 halu-2026-11-14|2026-11-13|N4=0482）"""
    return f"{kata['kai']}|{kata['date']}|N4={norm_n4(n4)}"


def draw(seed, ps):
    """くじを引く人（P番号の並び）の [(P番号, くじ値)] を、くじ値の小さい順に返す。先頭が枠1。くじ値＝SHA-256(種 + "|" + P番号) の16進64桁"""
    vals = [(p, hashlib.sha256(f"{seed}|{p}".encode("utf-8")).hexdigest()) for p in ps]
    return sorted(vals, key=lambda x: (x[1], pnum(x[0])))


def kata_out(kata):
    """型を作るときに外した人（抽せんの前に来られなくなった人。くじに入らない）"""
    return sorted(kata.get("out", []), key=pnum)


def kata_present(kata):
    """くじを引く人＝P1〜P(型の人数) から、型で外した人を除いたもの"""
    out = set(kata_out(kata))
    return [f"P{i}" for i in range(1, kata["players"] + 1) if f"P{i}" not in out]


def out_slots(players, out):
    """型で外した人に当てる枠（くじを引く人の後ろ）。型の中では、この枠が「お休み」"""
    return ["P%d" % s for s in range(players - len(out) + 1, players + 1)]


def slot_map(kata, n4, players):
    """P番号の数 → 枠の番号。くじを引いた人は抽せんの順。型で外した人はその後ろ（番号の順）。
    抽せんより後に増えた人（型の人数より大きい番号）は、番号のまま"""
    m = {pnum(p): k + 1 for k, (p, _) in enumerate(draw(kuji_seed(kata, n4), kata_present(kata)))}
    m.update({pnum(p): pnum(s) for p, s in zip(kata_out(kata), out_slots(kata["players"], kata_out(kata)))})
    m.update({i: i for i in range(kata["players"] + 1, players + 1)})
    return m


def rename(rnd, f):
    """1半荘の表（P番号の形）の人を、f（数 → 数）で置き換える。P番号と枠のあいだの行き来に使う"""
    g = lambda ps: ["P%d" % f[pnum(p)] for p in ps]
    o = {"tables": [{"no": t["no"], "p": g(t["p"])} for t in rnd["tables"]], "rest": g(rnd.get("rest", []))}
    if rnd.get("out"):
        o["out"] = g(rnd["out"])
    return o


def kata_rounds(kata):
    """型（枠の数）を、P番号の形の表にする（"P3"＝枠3）。検査と成績をそのまま使うため。型で外した人の枠は「お休み」に入れる"""
    o = out_slots(kata["players"], kata_out(kata))
    res = {}
    for k, r in kata["rounds"].items():
        res[k] = {"tables": [{"no": t["no"], "p": ["P%d" % w for w in t["w"]]} for t in r["tables"]], "rest": ["P%d" % w for w in r.get("rest", [])]}
        if o:
            res[k]["out"] = list(o)
    return res


def lottery_rounds(kata, n4):
    """抽せんの結果の表（型の枠を P番号に置き換えたもの）。型で外した人は、どの半荘も「お休み」"""
    inv = {v: k for k, v in slot_map(kata, n4, kata["players"]).items()}
    return {k: rename(r, inv) for k, r in kata_rounds(kata).items()}


def dump(obj, head=("kai", "made", "from", "remade", "kuji")):
    """1卓を1行にして書く（人が読んで確かめやすいように）。中身は json.loads で元に戻る。head は rounds より前に書く項目（ないものは飛ばす）"""
    j = lambda v: json.dumps(v, ensure_ascii=False)
    lines = ["{"] + [f'  {j(k)}: {j(obj[k])},' for k in head if k in obj] + ['  "rounds": {']
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
    if cfg.get("kuji"):
        try:
            d = datetime.strptime(str(cfg["kuji"]), "%Y-%m-%d")
        except ValueError:
            raise SystemExit("kuji は抽せんの日（例 2026-11-13）")
        if d.weekday() >= 5:
            print(f"※ kuji（{cfg['kuji']}）は土日です。ナンバーズの抽せんは月〜金なので、日を確かめてください")
        if cfg.get("date") and str(cfg["kuji"]) >= str(cfg["date"]):
            print(f"※ kuji（{cfg['kuji']}）が開催日（{cfg['date']}）より前ではありません")


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


def report(cfg, rounds, label="P"):
    """成績: 同じ相手と2回以上当たった組・風・抜け番・同じ卓。label は人の呼び方（型は「枠」）"""
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
        print("    " + "・".join(f"{label}{a}-{label}{b}×{m}" for a, b, m in rep[:20]) + (" …" if len(rep) > 20 else ""))
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
        print(f"    {label + str(p):<5} {h.played[p]}・{h.rested[p]}・" + "".join(str(x) for x in h.wind[p][:M]) + f"・{opp}人")
    return {"repeats": len(rep), "max_meet": max((m for _, _, m in pairs), default=0), "over": over,
            "lower": lower, "wind_spread": spread, "played": (min(pl), max(pl)), "rested": (min(rs), max(rs)), "same_table": same}


def show(cfg, rounds, label="P"):
    nm = lambda p: label + p[1:]
    for k in sorted(rounds, key=int):
        r = rounds[k]
        print(f"■ {k}半荘目")
        for t in r["tables"]:
            print(f"  {t['no']:>2}卓  " + "  ".join(f"{WINDS[i]} {nm(p):<4}" for i, p in enumerate(t["p"])))
        if r.get("rest"):
            print("  抜け番 " + "・".join(map(nm, r["rest"])))
        if r.get("out"):
            print("  お休み " + "・".join(map(nm, r["out"])))


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


def lottery_done(cfg, old):
    """くじの会で、抽せんの結果（kuji.py が書く kuji.n4）が、もう kumiawase.json に入っているか"""
    return bool(cfg.get("kuji") and old and old.get("kai") == cfg["kai"] and (old.get("kuji") or {}).get("n4"))


KUJI_CUT = "18:00"   # 抽せんの日のこの時刻から後は、型を書かない（ナンバーズの抽せんは夕方。当せん番号が分かった後に型を選べないように）


def make_kata(cfg, absent, seed):
    """抽せんの前の型。P1〜PN を枠1〜枠N と読み替えて、ふつうと同じ作り方で作る。
    抽せんの前に来られなくなった人（absent）はくじに入れず、後ろの枠（お休み）にする＝抽せんの後の組み直しと同じ種になる"""
    out = sorted(set(absent), key=pnum)
    over = [p for p in out if pnum(p) > cfg["players"]]
    if over:
        raise SystemExit(f"--absent の {over} は players（{cfg['players']}）より大きい番号")
    k = make(cfg, None, 1, out_slots(cfg["players"], out), seed)
    kata = {"kai": cfg["kai"], "made": k["made"], "date": str(cfg["kuji"]), "players": cfg["players"]}
    if out:
        kata["out"] = out
    if seed:
        kata["seed"] = seed
    kata["rounds"] = {r: {"tables": [{"no": t["no"], "w": [pnum(p) for p in t["p"]]} for t in x["tables"]], "rest": [pnum(p) for p in x["rest"]]}
                      for r, x in k["rounds"].items()}
    return kata


def load_kata(path, cfg, date):
    """抽せんに使う型を読み、回と抽せんの日が合っているか確かめる"""
    kata = load(path)
    if not kata or kata.get("kai") != cfg["kai"] or not isinstance(kata.get("rounds"), dict):
        raise SystemExit(f"型（{path}）がないか、別の回のもの（抽せんの前に kumiawase.py --write で作る）")
    if kata.get("date") != date:
        raise SystemExit(f"型の抽せんの日（{kata.get('date')}）が {date} と違う")
    return kata


def remake_after_kuji(cfg, kata, old, start, absent, back=()):
    """抽せんの後の組み直し。枠の並びに戻して作り、P番号に戻す（くじで決まった枠と P番号の対応を保つ）。
    種は型と同じ＝人が変わらなければ、型のとおりの表に戻る（--seed は使わせない。抽せんの後に表を選べてしまう）"""
    if cfg["players"] < kata["players"]:
        raise SystemExit(f"抽せんの後は players を減らさない（型は{kata['players']}人）。来られない人は --absent で外す")
    m = slot_map(kata, old["kuji"]["n4"], cfg["players"])
    inv = {v: k for k, v in m.items()}
    bad = [p for p in absent if pnum(p) not in m]
    if bad:
        raise SystemExit(f"--absent の {bad} は players（{cfg['players']}）より大きい番号")
    kout = kata_out(kata)
    nb = [p for p in back if p not in kout]
    if nb:
        raise SystemExit(f"--back の {nb} は、型で外した人ではない（型で外した人: {'・'.join(kout) or 'なし'}）")
    # 型で外した人（くじに入っていない）は、--back で戻さないかぎりお休みのまま。戻った人は、外したときの枠（後ろの枠）で打つ
    absent = sorted((set(absent) | set(kout)) - set(back), key=pnum)
    old_s = {"kai": old["kai"], "rounds": {k: rename(r, m) for k, r in old["rounds"].items() if int(k) < start}}
    k = make(cfg, old_s, start, ["P%d" % m[pnum(p)] for p in absent], kata.get("seed", ""))
    k["rounds"] = {r: rename(x, inv) for r, x in k["rounds"].items()}
    # 組み直しの印（トップページの知らせ。前の晩に表を見た人が取り違えないように）。表が変わらなければ、前の印と from のまま
    if k["rounds"] == old["rounds"]:
        k["from"] = old.get("from", 1)
        if old.get("remade"):
            k["remade"] = True
    else:
        k["remade"] = True
    k["kuji"] = old["kuji"]
    return k


def main():
    ap = argparse.ArgumentParser(description="普段の回の組み合わせを作る")
    ap.add_argument("--group", default="halu", help="会（kai/g/<会>/ の設定を使う。既定は halu）")
    ap.add_argument("--config")
    ap.add_argument("--out")
    ap.add_argument("--kata")
    ap.add_argument("--from", dest="start", type=int, default=1, help="この半荘から作る（前の半荘はそのまま）")
    ap.add_argument("--absent", default="", help="打たない人（カンマ区切り。例 P5,P9）")
    ap.add_argument("--back", default="", help="くじの会の抽せんの後に、型で外した人を戻す（カンマ区切り）")
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
    a.kata = a.kata or str(gdir / "kata.json")
    cfg = load(a.config)
    check_cfg(cfg)
    old = load(a.out)
    done = lottery_done(cfg, old)
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
        elif cfg.get("kuji"):
            # くじの会の抽せんの前は、型を検査する
            kata = load(a.kata)
            if not kata or kata.get("kai") != cfg["kai"]:
                print("■ 型（kata.json）がまだない（kumiawase.py --write で作る）"); sys.exit(1)
            ko = kata.get("out", [])
            if not (isinstance(ko, list) and all(P_RE.match(str(p)) and pnum(p) <= cfg["players"] for p in ko) and len(set(ko)) == len(ko)):
                print(f"■ 型に問題あり\n  外した人（out）の形が違う {ko}"); sys.exit(1)
            errs = validate(cfg, {"kai": kata["kai"], "rounds": kata_rounds(kata)})
            if kata.get("players") != cfg["players"]:
                errs.append(f"型の人数（{kata.get('players')}）が players（{cfg['players']}）と違う（--write で作り直す）")
            if kata.get("date") != str(cfg["kuji"]):
                errs.append(f"型の抽せんの日（{kata.get('date')}）が kuji（{cfg['kuji']}）と違う（--write で作り直す）")
            if str(kata.get("made", "")) >= f"{kata.get('date')} {KUJI_CUT}":
                errs.append(f"型を作った時刻（{kata.get('made')}）が、抽せんの日の{KUJI_CUT}より後")
            if errs:
                print("■ 型に問題あり"); [print("  " + e) for e in errs]
                sys.exit(1)
            print(f"■ 型は問題なし（{kata['made']} に作成・抽せんは {kata['date']}"
                  + (f"・外した人 {'・'.join(kata_out(kata))}" if ko else "") + "）")
            if not a.quiet:
                show(cfg, kata_rounds(kata), "枠")
            report(cfg, kata_rounds(kata), "枠")
        return
    if not (1 <= a.start <= cfg["prelim"]):
        raise SystemExit(f"--from は 1〜{cfg['prelim']}")
    absent = [s.strip() for s in a.absent.split(",") if s.strip()]
    back = [s.strip() for s in a.back.split(",") if s.strip()]
    [pnum(p) for p in absent + back]   # 形を確かめる（P1〜P99）
    if set(absent) & set(back):
        raise SystemExit(f"同じ人が --absent と --back の両方にいる {sorted(set(absent) & set(back), key=pnum)}")
    if cfg.get("kuji") and not done:
        # くじの会の抽せんの前: 型（枠1〜枠N）を作る。前の表を出さないよう、表が空の kumiawase.json も書く
        if a.start != 1 or back:
            raise SystemExit("くじの会は、抽せんの前に --from・--back を使わない（表はまだない）。"
                             "来られなくなった人は --absent で外して型を作り直す。外した人が戻れるようになったら、--absent から消して作り直す")
        kata = make_kata(cfg, absent, a.seed)
        kr = kata_rounds(kata)
        errs = validate(cfg, {"kai": cfg["kai"], "rounds": kr})
        if errs:
            print("■ 作った型に問題あり（書きません）"); [print("  " + e) for e in errs]
            sys.exit(1)
        if not a.quiet:
            show(cfg, kr, "枠")
        report(cfg, kr, "枠")
        ko, n = kata_out(kata), len(kata_present(kata))
        print(f"くじ: {kata['date']} のナンバーズ4の当せん番号で、P1〜P{cfg['players']}"
              + (f"（{'・'.join(ko)} を除く{n}人）" if ko else "") + f" を枠1〜枠{n} に入れる（kuji.py）")
        if ko:
            print(f"  {'・'.join(ko)} はくじに入れない（来られない人）。枠{n + 1}〜枠{cfg['players']} に当て、どの半荘もお休み")
        if a.write:
            # 当せん番号が分かった後に型を作り直せないよう、抽せんの日の夕方から後は書かない
            cut = datetime.strptime(f"{kata['date']} {KUJI_CUT}", "%Y-%m-%d %H:%M").replace(tzinfo=JST)
            if datetime.now(JST) >= cut:
                raise SystemExit(f"抽せんの日（{kata['date']}）の{KUJI_CUT}を過ぎたので、型は書かない（当せん番号が分かった後に型を選べないように）。"
                                 "抽せんを延ばすときは、taikai.json の kuji を次の抽せんの日にしてから作る")
            Path(a.kata).write_text(dump(kata, ("kai", "made", "date", "players", "out", "seed")), encoding="utf-8")
            Path(a.out).write_text(dump({"kai": cfg["kai"], "made": kata["made"], "from": 1, "rounds": {}}), encoding="utf-8")
            print(f"書きました: {a.kata}（型）・{a.out}（表は空。抽せんの後に kuji.py が書く）")
        else:
            print("（書いていません。--write で書きます）")
        return
    if done:
        if a.seed:
            raise SystemExit("抽せんの後は --seed を使わない（組み直しの表を選べてしまう）")
        kumi = remake_after_kuji(cfg, load_kata(a.kata, cfg, old["kuji"].get("date")), old, a.start, absent, back)
    else:
        if back:
            raise SystemExit("--back は、くじの会の抽せんの後に、型で外した人を戻すときだけ使う")
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
