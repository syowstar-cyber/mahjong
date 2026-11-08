# -*- coding: utf-8 -*-
"""Haluリーグの対戦カード（シーズン全部の回戦と卓）を作って検算する。

  python league/tools/cards.py --season 2027-shinshun            … 作って検算を出すだけ（書かない）
  python league/tools/cards.py --season 2027-shinshun --write    … s/<シーズン>/cards.json に書く
  python league/tools/cards.py --season 2027-shinshun --check    … いまの cards.json を検算する

設定は s/<シーズン>/season.json の players（人数）・mode（1卓の人数）・tables（1回戦の卓の番号）・rounds（回戦の数）。
いま組めるのは 10名・四麻・1回戦2卓（休み2人）で、rounds が15の倍数の形だけ（ほかの形は、要るときに作り方を足す）。

できる形（2027-shinshun＝60回戦）:
  - 全員の半荘数が同じ（48）・休みの回数が同じ（12）
  - どの2人も同じ回数だけ同じ卓（16回ずつ）
  - 同じ顔ぶれの卓は二度とない（120卓すべて別）
  - 15回戦ごと（ほぼ1か月）に、各人12半荘・どの2人も4回ずつ。5回戦ごとに、全員が1回ずつ休む
  - 休みは2回続かない（同じ2人がそろって休むのは、シーズンで最大3回。休む回数と、どの2人の対戦回数には響かない）

作り方（15回戦ずつ）: 10名を a0〜a4・b0〜b4 の2組に分け、番号を5で割った余りでずらす。
元の3回戦（休みは a0 と b_t。t は3つとも別）を、それぞれ5回ずつずらすと15回戦になる。
元の3回戦は、どの2人の「組と番号の差」の種類（9種類）も、合わせてちょうど4回ずつ同じ卓になるものを選ぶ（80通りある）。
ずらしても種類は変わらないので、15回戦でどの2人も4回ずつ同じ卓になる。
4つの区切りには、ずらしてできる顔ぶれ（5卓ずつの軌道）が互いに重ならない元の3回戦を選ぶ（重ならない4つの組は5,305通り）。
誰を a0〜b4 にするかはシーズンを通して同じで、くじ（--seed）で決める。
同じ引数なら何度作っても同じ表になる。別の表にしたいときは --seed 2 などを足す。
シーズンが始まった後（season.json の from の日から）は書き直さない（対戦カードは始まった後に変えない）。
"""
import argparse
import datetime
import json
import random
import re
import sys
from collections import defaultdict
from itertools import combinations
from math import comb
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

LEAGUE = Path(__file__).resolve().parent.parent
JST = datetime.timezone(datetime.timedelta(hours=9))


def die(msg):
    print("NG", msg)
    sys.exit(1)


def load_season(sid):
    if not re.match(r"^[0-9a-z-]{1,24}$", sid):
        die("シーズンの名前は英小文字・数字・- で24字まで: " + sid)
    p = LEAGUE / "s" / sid / "season.json"
    if not p.exists():
        die("見つからない: " + p.relative_to(LEAGUE.parent).as_posix())
    c = json.loads(p.read_text(encoding="utf-8"))
    if c.get("season") != sid:
        die("season.json の season がフォルダの名前と違う")
    return c


def shape(c):
    """人数・卓から、1人の半荘数・どの2人の回数・休みの回り方・区切り（どの2人の回数もそろう回戦の数）を出す。"""
    N, k, tabs, R = c["players"], c["mode"], c["tables"], c["rounds"]
    if k not in (3, 4):
        die("mode は 3 か 4")
    T = len(tabs)
    rest = N - T * k
    if T < 1 or rest < 0:
        die("1回戦の卓（tables）の人数が players より多い")
    if (R * T * k) % N:
        die("1人あたりの半荘数が割り切れない（rounds×卓×mode が players で割り切れない）")
    P, C = T * comb(k, 2), comb(N, 2)
    if (R * P) % C:
        die("どの2人も同じ回数にはならない（rounds×卓×(mode×(mode−1)÷2) が players×(players−1)÷2 で割り切れない）")
    B = N // rest if rest and N % rest == 0 else (1 if not rest else 0)   # 全員が1回ずつ休む回戦の数（0＝そろわない）
    L = R                                                                 # 区切り: どの2人の回数もそろう、いちばん短い回戦の数
    for m in range(B or 1, R + 1, B or 1):
        if R % m == 0 and (m * P) % C == 0:
            L = m
            break
    return dict(N=N, k=k, T=T, tabs=tabs, R=R, rest=rest, G=R * T * k // N, lam=R * P // C,
                B=B, L=L, lamL=L * P // C)


def pid(a, b):
    return (a, b) if a < b else (b, a)


# ---- 10名・四麻・1回戦2卓の作り方 ----
LABELS = [("a", i) for i in range(5)] + [("b", i) for i in range(5)]


def kind(p, q):
    """2人の組の種類（番号をずらしても変わらない）。a どうし・b どうしは差 1 か 2、a と b は差 0〜4"""
    if p[0] == q[0]:
        d = (q[1] - p[1]) % 5
        return (p[0] * 2, min(d, 5 - d))
    a, b = (p, q) if p[0] == "a" else (q, p)
    return ("ab", (b[1] - a[1]) % 5)


def base_solutions():
    """元の3回戦の組（休みは a0 と b_t、t は3つとも別）で、9種類どれも合わせて4回ずつ同じ卓になるもの。決まった順で返す"""
    kinds = [("aa", 1), ("aa", 2), ("bb", 1), ("bb", 2)] + [("ab", d) for d in range(5)]
    ix = {x: i for i, x in enumerate(kinds)}
    by_t = defaultdict(list)
    for t in range(5):
        play = [p for p in LABELS if p not in (("a", 0), ("b", t))]
        for rest3 in combinations(play[1:], 3):
            q1 = (play[0],) + rest3
            q2 = tuple(p for p in play if p not in q1)
            v = [0] * len(kinds)
            for q in (q1, q2):
                for p, r in combinations(q, 2):
                    v[ix[kind(p, r)]] += 1
            by_t[t].append((t, q1, q2, tuple(v)))
    sols = []
    for ts in combinations(range(5), 3):
        for o1 in by_t[ts[0]]:
            for o2 in by_t[ts[1]]:
                need = tuple(4 - x - y for x, y in zip(o1[3], o2[3]))
                if min(need) < 0:
                    continue
                for o3 in by_t[ts[2]]:
                    if o3[3] == need:
                        sols.append([o[:3] for o in (o1, o2, o3)])
    return sols


def orbit(q):
    """顔ぶれ q（組と番号の4つ）を番号ずらしでまとめた代表。同じ代表の顔ぶれは、ずらすと重なる（5卓で1つの軌道）"""
    return min(tuple(sorted((g, (i + s) % 5) for g, i in q)) for s in range(5))


def pick_terms(sols, nt, rng):
    """軌道が互いに重ならない元の3回戦を nt 個選ぶ（重ならなければ、シーズンを通して同じ顔ぶれの卓が出ない）。
    休みの2人の形（t）の使い方が偏らない組を優先する（偏ると、同じ2人がそろって休む回数が増える）"""
    orbs = [frozenset(orbit(q) for t, q1, q2 in sol for q in (q1, q2)) for sol in sols]
    combos = []

    def dfs(start, chosen, used):
        if len(chosen) == nt:
            combos.append(tuple(chosen))
            return
        for i in range(start, len(sols)):
            if not orbs[i] & used:
                dfs(i + 1, chosen + [i], used | orbs[i])
    dfs(0, [], frozenset())
    if not combos:
        return None
    # t ごとの使った回数の二乗の和が小さいほど、ならされている（12回を5つに分けるなら 3・3・2・2・2 がいちばん小さい）
    spread = lambda cb: sum(sum(1 for i in cb for t, _, _ in sols[i] if t == x) ** 2 for x in range(5))
    best = min(spread(cb) for cb in combos)
    pick = list(rng.choice([cb for cb in combos if spread(cb) == best]))
    rng.shuffle(pick)
    return [sols[i] for i in pick]


def term_rounds(sol, who, prev_last, rng):
    """人を当てはめた15回戦を作り、休みが2回続かない並べ方を返す（3つのまとまりの順と、まとまりの中の順を入れ替えて探す）"""
    blocks = []
    for t, q1, q2 in sol:
        blk = []
        for s in range(5):
            mv = lambda p: who[(p[0], (p[1] + s) % 5)]
            blk.append({"t": [sorted(map(mv, q1)), sorted(map(mv, q2))], "r": sorted([who[("a", s)], who[("b", (t + s) % 5)]])})
        blocks.append(blk)
    for _ in range(5000):
        for blk in blocks:
            rng.shuffle(blk)
        rng.shuffle(blocks)
        seq = ([prev_last] if prev_last else []) + [rd for blk in blocks for rd in blk]
        if not any(set(seq[i]["r"]) & set(seq[i + 1]["r"]) for i in range(len(seq) - 1)):
            return [rd for blk in blocks for rd in blk]
    return None


def build_10(sh, seed):
    if (sh["N"], sh["k"], sh["T"], sh["L"]) != (10, 4, 2, 15):
        die(f"いま組めるのは 10名・四麻・1回戦2卓で、rounds が15の倍数の形だけ（{sh['N']}名・mode {sh['k']}・{sh['T']}卓・{sh['R']}回戦）")
    rng = random.Random(seed)
    nt = sh["R"] // 15
    terms = pick_terms(base_solutions(), nt, rng)
    if not terms:
        die(f"{sh['R']}回戦では、同じ顔ぶれの卓を出さずに組めない（この作り方は90回戦まで）")
    people = list(range(10))
    rng.shuffle(people)
    who = {lab: people[i] for i, lab in enumerate(LABELS)}   # 組と番号 → 人（0〜9）。シーズンを通して同じ
    out = []
    for n, sol in enumerate(terms):
        rounds = term_rounds(sol, who, out[-1] if out else None, rng)
        if not rounds:
            die(f"{n * 15 + 1}〜{n * 15 + 15}回戦で、休みが2回続かない並べ方が見つからない（--seed を変えて試す）")
        out.extend(rounds)
    P = lambda x: "P" + str(x + 1)
    rounds = {}
    for n, rd in enumerate(out, 1):
        tbs = sorted(rd["t"], key=lambda tb: tb[0])
        rounds[str(n)] = {"tables": [{"no": no, "p": [P(x) for x in tb]} for no, tb in zip(sh["tabs"], tbs)],
                          "rest": [P(x) for x in rd["r"]]}
    return rounds


# ---- 検算（作り方と関係なく、cards.json の中身を数え直す） ----
def check(c, sh, cards, quiet=False):
    N, k, T, R, L, B = sh["N"], sh["k"], sh["T"], sh["R"], sh["L"], sh["B"]
    pn = lambda s: int(s[1:])
    everyone = ["P" + str(i + 1) for i in range(N)]
    errs = []
    rounds = cards.get("rounds") or {}
    if cards.get("season") != c["season"]:
        errs.append("cards.json の season が season.json と違う")
    if sorted(rounds, key=lambda x: int(x) if x.isdigit() else 0) != [str(i) for i in range(1, R + 1)]:
        errs.append(f"回戦が 1〜{R} でそろっていない")
        return errs
    games, rests = defaultdict(int), defaultdict(int)
    pair, pair_term, quart, restpair = defaultdict(int), defaultdict(lambda: defaultdict(int)), defaultdict(int), defaultdict(int)
    twice = 0
    for n in range(1, R + 1):
        rd = rounds[str(n)]
        tbs = rd.get("tables") or []
        if [t.get("no") for t in tbs] != list(sh["tabs"]):
            errs.append(f"{n}回戦: 卓の番号が season.json の tables と違う")
        seen = []
        for t in tbs:
            ps = t.get("p") or []
            if len(ps) != k or len(set(ps)) != k or any(p not in everyone for p in ps):
                errs.append(f"{n}回戦 {t.get('no')}卓: P1〜P{N} の別々の{k}人でない")
            seen += ps
            for p in ps:
                games[p] += 1
            for a, b in combinations(sorted(ps, key=pn), 2):
                pair[(a, b)] += 1
                pair_term[(n - 1) // L][(a, b)] += 1
            quart[tuple(sorted(ps, key=pn))] += 1
        rs = rd.get("rest") or []
        for p in rs:
            rests[p] += 1
        for a, b in combinations(sorted(rs, key=pn), 2):
            restpair[(a, b)] += 1
        if n > 1 and set(rs) & set(rounds[str(n - 1)].get("rest") or []):
            twice += 1
        if sorted(seen + rs, key=pn) != everyone:
            errs.append(f"{n}回戦: 打つ人と休む人で、全員がちょうど1回ずつになっていない")
    if any(games[p] != sh["G"] for p in everyone):
        errs.append("半荘数が全員同じでない: " + "・".join(f"{p}={games[p]}" for p in everyone if games[p] != sh["G"]))
    allpairs = list(combinations(everyone, 2))
    off = [(a, b, pair[(a, b)]) for a, b in allpairs if pair[(a, b)] != sh["lam"]]
    if off:
        errs.append(f"同じ卓の回数が{sh['lam']}回でない組: " + "・".join(f"{a}-{b}={n}" for a, b, n in off[:8]) + ("…" if len(off) > 8 else ""))
    dup = [q for q, n in quart.items() if n > 1]
    if dup:
        errs.append("同じ顔ぶれの卓が2回以上: " + "・".join("+".join(q) for q in dup[:5]))
    term_ok = all(pair_term[t][(a, b)] == sh["lamL"] for t in range(R // L) for a, b in allpairs)
    block_ok = bool(B) and all(
        sorted((p for n in range(s + 1, s + B + 1) for p in rounds[str(n)].get("rest") or []), key=pn) == everyone
        for s in range(0, R, B)) if sh["rest"] else True
    if not quiet:
        print(f"■ {N}名・{R}回戦・1回戦{T}卓（{'四麻' if k == 4 else '三麻'}・卓の番号 {'・'.join(str(x) for x in sh['tabs'])}）")
        print(f"  1人あたり {sh['G']}半荘・休み {R - sh['G']}回: " + ("全員同じ" if all(games[p] == sh['G'] for p in everyone) else "そろっていない"))
        print(f"  どの2人も同じ卓 {sh['lam']}回ずつ（{len(allpairs)}組）: " + ("はい" if not off else f"いいえ（{len(off)}組が違う）"))
        print(f"  同じ顔ぶれの卓: " + (f"なし（{len(quart)}卓すべて別）" if not dup else f"{len(dup)}組が2回以上"))
        if L < R:
            spans = "・".join(f"{t * L + 1}〜{(t + 1) * L}" for t in range(R // L))
            print(f"  {L}回戦ごと（{spans}回戦）に、各人{L * T * k // N}半荘・どの2人も{sh['lamL']}回ずつ: " + ("はい" if term_ok else "いいえ"))
        if sh["rest"]:
            if B:
                print(f"  {B}回戦ごとに、全員が1回ずつ休む: " + ("はい" if block_ok else "いいえ"))
            print(f"  休みが2回続く: {twice}回")
            if sh["rest"] >= 2:
                mx = max(restpair.values()) if restpair else 0
                cnt = lambda n: sum(1 for v in restpair.values() if v == n)
                print(f"  同じ2人がそろって休む回数: 最大{mx}回（" + "・".join(f"{n}回の組 {cnt(n)}組" for n in range(mx, 0, -1) if cnt(n)) + "）")
    return errs


def main():
    ap = argparse.ArgumentParser(description="Haluリーグの対戦カードを作って検算する")
    ap.add_argument("--season", required=True, help="シーズンの名前（league/s/ の下のフォルダ）")
    ap.add_argument("--write", action="store_true", help="cards.json に書く")
    ap.add_argument("--check", action="store_true", help="いまの cards.json を検算する")
    ap.add_argument("--seed", type=int, default=1, help="別の表にしたいときに変える（既定 1）")
    a = ap.parse_args()
    c = load_season(a.season)
    sh = shape(c)
    path = LEAGUE / "s" / a.season / "cards.json"
    if a.check:
        if not path.exists():
            die("cards.json がまだない")
        errs = check(c, sh, json.loads(path.read_text(encoding="utf-8")))
    else:
        today = datetime.datetime.now(JST).strftime("%Y-%m-%d")
        if a.write and path.exists() and today >= str(c.get("from") or "9999"):
            die(f"シーズンが始まった（{c.get('from')}〜）ので、cards.json を書き直しません")
        rounds = build_10(sh, a.seed)
        cards = {"season": c["season"], "made": datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "seed": a.seed, "rounds": rounds}
        errs = check(c, sh, cards)
    if errs:
        print("■ 問題あり")
        for e in errs:
            print("  - " + e)
        sys.exit(1)
    print("■ 形は問題なし")
    if a.write and not a.check:
        # 1回戦を1行にまとめて書く（差分を読みやすく）
        keys = list(rounds)
        lines = ["{", f'  "season": {json.dumps(cards["season"])},', f'  "made": {json.dumps(cards["made"])},',
                 f'  "seed": {cards["seed"]},', '  "rounds": {']
        lines += [f'    {json.dumps(n)}: {json.dumps(rounds[n], ensure_ascii=False)}' + ("," if i < len(keys) - 1 else "")
                  for i, n in enumerate(keys)]
        lines += ["  }", "}", ""]
        path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        print("書きました:", path.relative_to(LEAGUE.parent).as_posix())


if __name__ == "__main__":
    main()
