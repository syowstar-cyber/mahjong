# -*- coding: utf-8 -*-
"""Haluリーグの名簿を受け口へ送る・受け口を試す。受け口の URL は league/s/<シーズン>/season.json の api から読む。
名前は受け口にだけ置く＝名簿のファイルは scratchpad に置き、リポに入れない。出力に名前は出さない（P番号と人数だけ）。

使い方（リポの根で）:
  python league/tools/meibo.py <名簿ファイル>   … 名簿を送る。ファイルは UTF-8 で1行1人「P1 呼び名」（空白かタブで区切る）
                                                 渡した番号だけ直す（直したい人の行だけ送ってもよい）
  python league/tools/meibo.py --drop P9,P10     … その番号の名前を受け口の名簿から消す（番号を入れ替えたとき）
  python league/tools/meibo.py --show            … 受け口のいまの様子（名簿の人数と番号・点数の卓数・予定を付けた人数・最終更新）
  python league/tools/meibo.py --test            … 初回のテスト送信。シーズン setup-test に名簿・点数・予定を送り、
                                                 断るべきものを断るか、読み直せるか、消して空に戻るかを見る（送信履歴 LOG と最終更新 U_setup-test は残る）
  --season でシーズンを選ぶ（既定は league/seasons.json の current）。--config は試験用（既定は league/s/<シーズン>/season.json）
成功は1行目が OK で始まる。失敗は NG で始まり、終了コード 1"""
import argparse, json, re, sys, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
LEAGUE = Path(__file__).resolve().parents[1]
P_RE = re.compile(r"^P([1-9]|[1-9][0-9])$")
SEASON_RE = re.compile(r"^[0-9a-z-]{1,24}$")   # 受け口（Code.gs）と同じ形
TEST_SEASON = "setup-test"
JST = timezone(timedelta(hours=9))


def http(url, body=None, timeout=30):
    """受け口へ GET（body なし）か POST（body あり・JSON を UTF-8 で）。返事の JSON を返す。
    Content-Type は text/plain（ページと同じ送り方）。日本語は Git Bash の curl だと崩れるので urllib で送る"""
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "text/plain;charset=utf-8"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Api:
    def __init__(self, url, season, transport=http):
        self.url = str(url or "").strip()
        if not self.url:
            raise SystemExit("NG season.json の api が空（受け口が未設定）")
        self.season, self.t = season, transport

    def get(self, season=None):
        return self.t(self.url + ("&" if "?" in self.url else "?") + "season=" + urllib.parse.quote(season or self.season))

    def post(self, body):
        return self.t(self.url, body)


def read_names(path):
    names = {}
    for i, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = re.split(r"[\s　]+", s, maxsplit=1)
        if len(parts) != 2 or not P_RE.match(parts[0]):
            raise SystemExit(f"NG 名簿の {i}行目の形が違う（「P1 呼び名」の形）")
        p, n = parts[0], parts[1].strip()
        if len(n) > 20 or re.search(r"[\x00-\x1f<>]", n):
            raise SystemExit(f"NG 名簿の {i}行目の名前が長すぎるか、使えない文字がある（{p}）")
        if p in names:
            raise SystemExit(f"NG 名簿に {p} が2回ある")
        names[p] = n
    if not names:
        raise SystemExit("NG 名簿が空")
    return names


def nums(ps):
    ps = sorted(ps, key=lambda p: int(p[1:]))
    return "・".join(ps) if len(ps) <= 6 else f"{ps[0]}〜{ps[-1]}（{len(ps)}人）"


def send(api, names, players):
    """names = {P番号: 名前}。名前が '' の番号は消す"""
    over = [p for p in names if int(p[1:]) > players]
    if over:
        print(f"注意: season.json の players（{players}）より大きい番号がある {nums(over)}")
    j = api.post({"action": "roster", "season": api.season, "names": names})
    if not j.get("ok"):
        raise SystemExit(f"NG 受け口が断った: {j.get('error')}")
    got = j["data"]["roster"]
    miss = [p for p, n in names.items() if (got.get(p) != n if n else p in got)]
    if miss:
        raise SystemExit(f"NG 送った内容が受け口の名簿と合わない {nums(miss)}")
    put = [p for p, n in names.items() if n]
    drop = [p for p, n in names.items() if not n]
    what = "・".join(([f"入れた {len(put)}人（{nums(put)}）"] if put else []) + ([f"消した {nums(drop)}"] if drop else []))
    print(f"OK roster シーズン {api.season}・{what}・受け口の名簿は {len(got)}人（{nums(got) if got else 'なし'}）")


def show(api, cfg):
    j = api.get()
    if not j.get("ok"):
        raise SystemExit(f"NG 受け口がエラーを返した: {j.get('error')}")
    d = j["data"]
    r = d["roster"]
    tables = sum(len(t) for t in d["rounds"].values())
    total = int(cfg["rounds"]) * len(cfg["tables"])
    print(f"OK show シーズン {api.season}・名簿 {len(r)}人（{nums(r) if r else 'なし'}）・点数の卓 {tables}/{total}"
          f"・予定を付けた人 {len(d['avail'])}・最終更新 {d['updated'] or '―'}")


def empty(d):
    return not d["rounds"] and not d["roster"] and not d["avail"]


def wipe(api):
    """setup-test の残り（前の試しが途中で止まった分）を、受け口への送信で消す"""
    d = api.get(TEST_SEASON)["data"]
    for r, tabs in d["rounds"].items():
        for t in tabs:
            api.post({"action": "clear", "season": TEST_SEASON, "round": r, "table": int(t)})
    for p, marks in d["avail"].items():
        api.post({"action": "avail", "season": TEST_SEASON, "p": p, "marks": {k: "" for k in marks}})
    if d["roster"]:
        api.post({"action": "roster", "season": TEST_SEASON, "names": {p: "" for p in d["roster"]}})
    if not empty(api.get(TEST_SEASON)["data"]):
        raise SystemExit("NG test setup-test の残りを消せない。エディタの purgeSeason（PURGE='setup-test'）で消す")


def test(api):
    """シーズン setup-test で、名簿→1卓→断るもの（dup・範囲外・明日）→予定→読み直し→消して空に戻る、を確かめる"""
    S, steps = TEST_SEASON, []

    def need(ok, what):
        steps.append(("OK " if ok else "NG ") + what)
        if not ok:
            print("\n".join(steps))
            raise SystemExit(f"NG test（{what}）")

    j = api.get(S)
    if not j.get("ok") or "avail" not in (j.get("data") or {}):
        raise SystemExit(f"NG test 受け口が Haluリーグの Code.gs でない（error: {j.get('error')}）。URL を確かめる")
    if not empty(j["data"]):
        wipe(api)
        print("注意: setup-test に前の残りがあったので消した")
    today = datetime.now(JST).date()
    d0, d1 = today.isoformat(), (today + timedelta(days=1)).isoformat()
    four, raw = ["P1", "P2", "P3", "P4"], [40000, 30000, 20000, 10000]
    other = ["P5", "P6", "P7", "P8"]

    j = api.post({"action": "roster", "season": S, "names": {"P1": "テスト１", "P2": "テスト２"}})
    need(j.get("ok") and j["data"]["roster"].get("P1") == "テスト１", "名簿（日本語）を送る")
    j = api.post({"action": "score", "season": S, "round": "1", "table": 1, "p": four, "raw": raw, "d": d0})
    t = j.get("ok") and j["data"]["rounds"].get("1", {}).get("1")
    need(bool(t) and t["p"] == four and t["raw"] == raw and t["d"] == d0, "1卓（4人）を送る")
    upd = j["data"]["updated"]
    j = api.post({"action": "score", "season": S, "round": "1", "table": 2, "p": ["P5", "P6", "P7", "P1"], "raw": [25000] * 4, "d": d0})
    need(not j.get("ok") and j.get("error") == "dup" and j.get("players") == ["P1"], "同じ回戦のほかの卓に同じ人を送ると断る")
    j = api.post({"action": "score", "season": S, "round": "1", "table": 2, "p": other, "raw": [1000000, 0, 0, 0], "d": d0})
    need(not j.get("ok") and j.get("error") == "score", "範囲外の点数を断る")
    j = api.post({"action": "score", "season": S, "round": "1", "table": 2, "p": other, "raw": [25000] * 4, "d": d1})
    need(not j.get("ok") and j.get("error") == "date", "明日の日付を断る")
    j = api.post({"action": "avail", "season": S, "p": "P3", "marks": {d0: "o", d1: "t"}})
    need(j.get("ok") and j["data"]["avail"].get("P3") == {d0: "o", d1: "t"}, "予定の印を送る")
    need(j["data"]["updated"] == upd, "予定の印では最終更新が動かない")
    j = api.get(S)
    d = j.get("data") or {}
    t = (d.get("rounds") or {}).get("1", {}).get("1") or {}
    need(j.get("ok") and t.get("p") == four and (d.get("roster") or {}).get("P2") == "テスト２"
         and (d.get("avail") or {}).get("P3", {}).get(d1) == "t", "読み直す（GET）")
    j = api.post({"action": "clear", "season": S, "round": "1", "table": 1})
    need(j.get("ok") and "1" not in j["data"]["rounds"], "1卓を取り消す")
    j = api.post({"action": "avail", "season": S, "p": "P3", "marks": {d0: "", d1: ""}})
    need(j.get("ok") and "P3" not in j["data"]["avail"], "予定の印を消す")
    j = api.post({"action": "roster", "season": S, "names": {"P1": "", "P2": ""}})
    need(j.get("ok") and not j["data"]["roster"], "名簿を消す")
    j = api.get(S)
    need(j.get("ok") and empty(j["data"]), "空に戻った")
    print(f"OK test 受け口は使える（{len(steps)}項目）")
    print("\n".join(steps))


def main():
    ap = argparse.ArgumentParser(description="Haluリーグの名簿を受け口へ送る・受け口を試す")
    ap.add_argument("file", nargs="?", help="名簿ファイル（1行1人「P1 呼び名」）")
    ap.add_argument("--drop", help="名簿から消す番号（カンマ区切り。例 P9,P10）")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--season", help="シーズン（既定は league/seasons.json の current）")
    ap.add_argument("--config", help="試験用。season.json の置き場")
    a = ap.parse_args()
    season = a.season or json.loads((LEAGUE / "seasons.json").read_text(encoding="utf-8"))["current"]
    if not SEASON_RE.match(season):
        raise SystemExit("NG --season は英小文字・数字・- で24字まで")
    cfg = json.loads(Path(a.config or LEAGUE / "s" / season / "season.json").read_text(encoding="utf-8"))
    if cfg.get("season") != season:
        raise SystemExit(f"NG season.json の season（{cfg.get('season')}）が {season} と違う")
    api = Api(cfg.get("api"), season)
    if a.test:
        test(api)
    elif a.show:
        show(api, cfg)
    elif a.file or a.drop:
        names = read_names(a.file) if a.file else {}
        for p in [x.strip() for x in (a.drop or "").split(",") if x.strip()]:
            if not P_RE.match(p):
                raise SystemExit(f"NG --drop の番号の形が違う（{p}）")
            if p in names:
                raise SystemExit(f"NG {p} が名簿ファイルと --drop の両方にある")
            names[p] = ""
        send(api, names, int(cfg["players"]))
    else:
        ap.print_help()


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code)
            sys.exit(1)
        raise
    except Exception as e:   # 通信の失敗など
        print(f"NG {type(e).__name__}: {e}")
        sys.exit(1)
