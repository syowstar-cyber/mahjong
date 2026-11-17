# -*- coding: utf-8 -*-
"""普段の回の名簿を受け口へ送る・受け口を試す。受け口の URL と回の名前は会ごとの kai/g/<会>/taikai.json の api と kai から読む。
名前は受け口にだけ置く＝名簿のファイルは scratchpad に置き、リポに入れない。出力に名前は出さない（P番号と人数だけ）。

使い方:
  python kai/tools/meibo.py <名簿ファイル>   … 名簿を送る。ファイルは UTF-8 で1行1人「P1 呼び名」（空白かタブで区切る）
                                               渡した番号だけ直す（直したい人の行だけ送ってもよい）
  python kai/tools/meibo.py --show            … 受け口の名簿の人数と番号を出す
  python kai/tools/meibo.py --shukketsu <名簿ファイル> … 出席確認の一覧（受け口の回 <kai>-s。人数未定の間に、幹部用ページで参加のチェックを付ける一覧）へ送る。
                                               番号は一覧の中だけのもの。受け口に入っている番号へ別の名前は上書きしない（チェックは番号に付いているため）
  python kai/tools/meibo.py --shukketsu --show … 出席確認の一覧の人数と、参加のチェックの人数を出す
  python kai/tools/meibo.py --kakutei         … 締め切り: 出席確認の一覧の参加のチェックから、大会の名簿（P1〜。一覧の番号の順）を作って受け口へ送る。
                                               大会の名簿に別の中身が入っていたら送らない。続けて taikai.json に players を書き、kumiawase.py --write で型を作る
  python kai/tools/meibo.py --kakutei --redo  … 抽せんの前に大会の名簿を作り直す（直前の欠席など）。点数の入った半荘があるときと、
                                               抽せんの日の KUJI_CUT（kumiawase.py）から後は、--redo でも送らない
  python kai/tools/meibo.py --test            … 初回のテスト送信。回 setup-test に決勝最終実況と名簿と1卓を送り、読み直し、消して空に戻るかを見る
  --group で会を選ぶ（既定は halu）。--config は試験用（既定は kai/g/<会>/taikai.json）
成功は1行目が OK で始まる。失敗は NG で始まり、終了コード 1"""
import argparse, json, re, sys, unicodedata, urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import kumiawase as K  # noqa: E402  同じフォルダの組み合わせの道具（抽せんの日の締めの時刻 KUJI_CUT と JST を共通に使う）
KAI = Path(__file__).resolve().parents[1]
P_RE = re.compile(r"^P([1-9]|[1-9][0-9])$")
TEST_KAI = "setup-test"


def http(url, body=None, timeout=30):
    """受け口へ GET（body なし）か POST（body あり・JSON を UTF-8 で）。返事の JSON を返す。
    Content-Type は text/plain（ページと同じ送り方）。日本語は Git Bash の curl だと崩れるので urllib で送る"""
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "text/plain;charset=utf-8"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Api:
    def __init__(self, cfg, transport=http):
        self.url = str(cfg.get("api") or "").strip()
        if not self.url:
            raise SystemExit("NG taikai.json の api が空（受け口が未設定）")
        self.kai, self.t = cfg["kai"], transport

    def get(self, kai=None):
        return self.t(self.url + ("&" if "?" in self.url else "?") + "kai=" + urllib.parse.quote(kai or self.kai))

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
    # 人数未定の会（players を書かない。2026-11-17）は、番号の上限を見ない
    over = [p for p in names if players is not None and int(p[1:]) > players]
    if over:
        print(f"注意: taikai.json の players（{players}）より大きい番号がある {nums(over)}")
    j = api.post({"action": "roster", "kai": api.kai, "names": names})
    if not j.get("ok"):
        raise SystemExit(f"NG 受け口が断った: {j.get('error')}")
    got = j["data"]["roster"]
    miss = [p for p in names if got.get(p) != names[p]]
    if miss:
        raise SystemExit(f"NG 送った名前が受け口に入っていない {nums(miss)}")
    print(f"OK roster 送った {len(names)}人（{nums(names)}）・受け口の名簿は {len(got)}人")


def show(api, checks=False):
    j = api.get()
    if not j.get("ok"):
        raise SystemExit(f"NG 受け口がエラーを返した: {j.get('error')}")
    r = j["data"]["roster"]
    if checks:
        u = j["data"].get("uchiage") or {}
        yes = [p for p in r if (u.get(p) or {}).get("choice") == "yes"]
        print(f"OK show 出席確認の一覧 {api.kai}・名前 {len(r)}人（{nums(r) if r else 'なし'}）・参加のチェック {len(yes)}人")
        return
    print(f"OK show 回 {api.kai}・名簿 {len(r)}人（{nums(r) if r else 'なし'}）・点数の入った半荘 {len(j['data']['rounds'])}・最終更新 {j['data']['updated'] or '―'}")


def kakutei(api, cfg, redo=False, now=None):
    """締め切り: 出席確認の一覧（<kai>-s）で参加のチェックが付いた人を、一覧の番号の順に P1〜 として大会の名簿（<kai>）へ送る。
    大会の名簿がもう同じ中身なら送り直さない。別の中身が入っていたら送らない（番号と名前の組は、くじの前に公開して固定するため）。
    抽せんの前に作り直すときだけ redo（--redo）で、前の名簿を置き換える。
    どちらも、点数の入った半荘があるときと、抽せんの日（kuji）の KUJI_CUT から後は送らない（当せん番号が分かった後に番号と名前の組を変えないように）"""
    j = api.get(api.kai + "-s")
    if not j.get("ok"):
        raise SystemExit(f"NG 受け口がエラーを返した: {j.get('error')}")
    r, u = j["data"].get("roster") or {}, j["data"].get("uchiage") or {}
    yes = sorted((p for p in r if P_RE.match(p) and r[p] and (u.get(p) or {}).get("choice") == "yes"), key=lambda p: int(p[1:]))
    mode = cfg.get("mode")
    if mode not in (3, 4):
        raise SystemExit("NG taikai.json の mode が 3 か 4 でない")
    if len(yes) < mode:
        raise SystemExit(f"NG 参加のチェックが {len(yes)}人で、{mode}人より少ない（組み合わせを作れない）")
    if len(yes) > 99:
        raise SystemExit(f"NG 参加のチェックが {len(yes)}人で、99人を超える")
    names = {f"P{i}": r[p] for i, p in enumerate(yes, 1)}
    if len({re.sub(r"\s", "", unicodedata.normalize("NFKC", n)) for n in names.values()}) != len(names):
        raise SystemExit("NG 参加のチェックの中に、同じ名前の人が2人いる（幹部用ページの一覧で直してから）")
    j = api.get()
    if not j.get("ok"):
        raise SystemExit(f"NG 受け口がエラーを返した: {j.get('error')}")
    got = j["data"].get("roster") or {}
    if got == names:
        print(f"OK kakutei 大会の名簿は、もう参加のチェックと同じ {len(names)}人（{nums(names)}）が入っている（送り直さない）")
    else:
        if got and not redo:
            raise SystemExit(f"NG 大会の名簿（{api.kai}）に、もう {len(got)}人（{nums(got)}）が入っていて、参加のチェックと中身が違う（送らなかった）。"
                             "抽せんの前に作り直すなら --kakutei --redo")
        if j["data"].get("rounds"):
            raise SystemExit("NG 点数の入った半荘があるので、大会の名簿を送らない")
        if cfg.get("kuji") and (now or datetime.now(K.JST)) >= datetime.strptime(f"{cfg['kuji']} {K.KUJI_CUT}", "%Y-%m-%d %H:%M").replace(tzinfo=K.JST):
            raise SystemExit(f"NG 抽せんの日（{cfg['kuji']}）の{K.KUJI_CUT}を過ぎたので、大会の名簿を送らない（番号と名前の組は、当せん番号が分かる前に固定する）")
        # 前の名簿にだけある番号は空で送って消す（受け口の roster は番号ごとに上書きし、空は消す）
        j = api.post({"action": "roster", "kai": api.kai, "names": dict(names, **{p: "" for p in got if p not in names})})
        if not j.get("ok"):
            raise SystemExit(f"NG 受け口が断った: {j.get('error')}")
        if j["data"]["roster"] != names:
            raise SystemExit(f"NG 送った後の大会の名簿（{len(j['data']['roster'])}人）が、参加のチェックと合わない")
        print(f"OK kakutei 参加のチェック {len(names)}人を、大会の名簿 {nums(names)} として送った" + (f"（前の {len(got)}人の名簿を置き換えた）" if got else ""))
    pl = cfg.get("players")
    if pl is None:
        print(f"次: taikai.json に \"players\": {len(names)} を書き、kumiawase.py --write で型を作る")
    elif pl == len(names):
        print(f"taikai.json の players は {pl}（同じ）")
    else:
        print(f"次: taikai.json の players（{pl}）を {len(names)} に直し、kumiawase.py --write で型を作り直す")


def keep_numbers(api, names):
    """出席確認の一覧では、受け口に入っている番号へ別の名前を上書きしない（参加のチェックは番号に付いているので、別の人に付いてしまう）"""
    j = api.get()
    if not j.get("ok"):
        raise SystemExit(f"NG 受け口がエラーを返した: {j.get('error')}")
    got = j["data"].get("roster") or {}
    clash = [p for p in names if p in got and got[p] != names[p]]
    if clash:
        raise SystemExit(f"NG 出席確認の一覧の {nums(clash)} には、もう別の名前が入っている（送らなかった）。空いている番号で送る")


def test(api):
    """回 setup-test で、決勝最終実況→名簿→1卓→読み直し→取り消し→名簿と実況を消す→空に戻る、を確かめる（送信履歴 LOG と最終更新 U_setup-test は残る）"""
    steps = []
    def need(ok, what):
        steps.append(("OK " if ok else "NG ") + what)
        if not ok:
            print("\n".join(steps))
            raise SystemExit(f"NG test（{what}）")
    # 実況を最初に送る（古い受け口は action で断り、何も書かない＝setup-test に残り物を作らない）
    live = {"seats": ["P2", "P3", "P1"], "kyoku": 5, "honba": 1, "kyotaku": 1, "raw": [52000, 30000, 22000], "end": False}
    j = api.post({"action": "live", "kai": TEST_KAI, "live": live})
    if j.get("error") == "action":
        raise SystemExit("NG test 受け口が古い（決勝最終実況に未対応）。kai/gas/README.md の手順で新しいバージョンをデプロイする")
    need(j.get("ok") and (j["data"].get("live") or {}).get("raw") == live["raw"], "決勝最終実況を送る")
    j = api.post({"action": "roster", "kai": TEST_KAI, "names": {"P1": "テスト１", "P2": "テスト２"}})
    need(j.get("ok") and j["data"]["roster"].get("P1") == "テスト１", "名簿（日本語）を送る")
    j = api.post({"action": "score", "kai": TEST_KAI, "round": "1", "table": 1, "p": ["P1", "P2", "P3"], "raw": [45000, 35000, 25000]})
    need(j.get("ok") and j["data"]["rounds"]["1"]["1"]["raw"] == [45000, 35000, 25000], "1卓（3人）を送る")
    j = api.post({"action": "score", "kai": TEST_KAI, "round": "1", "table": 2, "p": ["P1", "P4", "P5"], "raw": [35000, 35000, 35000]})
    need(not j.get("ok") and j.get("error") == "dup", "同じ半荘のほかの卓に同じ人を送ると断る")
    j = api.post({"action": "score", "kai": TEST_KAI, "round": "1", "table": 3, "p": ["P6", "P7", "P8"], "raw": [1000000, 0, 0]})
    need(not j.get("ok") and j.get("error") == "score", "範囲外の点数を断る")
    j = api.get(TEST_KAI)
    need(j.get("ok") and j["data"]["rounds"]["1"]["1"]["p"] == ["P1", "P2", "P3"] and j["data"]["roster"].get("P2") == "テスト２"
         and (j["data"].get("live") or {}).get("seats") == live["seats"], "読み直す（GET）")
    j = api.post({"action": "clear", "kai": TEST_KAI, "round": "1", "table": 1})
    need(j.get("ok") and "1" not in j["data"]["rounds"], "1卓を取り消す")
    j = api.post({"action": "roster", "kai": TEST_KAI, "names": {"P1": "", "P2": ""}})
    need(j.get("ok") and not j["data"]["roster"], "名簿を消す")
    j = api.post({"action": "live", "kai": TEST_KAI, "live": None})
    need(j.get("ok") and j["data"].get("live") is None, "決勝最終実況を消す")
    j = api.get(TEST_KAI)
    need(j.get("ok") and not j["data"]["rounds"] and not j["data"]["roster"] and j["data"].get("live") is None, "空に戻った")
    print("OK test 受け口は使える（10項目）")
    print("\n".join(steps))


def main():
    ap = argparse.ArgumentParser(description="普段の回の名簿を受け口へ送る・受け口を試す")
    ap.add_argument("file", nargs="?", help="名簿ファイル（1行1人「P1 呼び名」）")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--group", default="halu", help="会（kai/g/<会>/ の設定を使う。既定は halu）")
    ap.add_argument("--config")
    ap.add_argument("--shukketsu", action="store_true", help="出席確認の一覧（受け口の回 <kai>-s）へ送る・見る")
    ap.add_argument("--kakutei", action="store_true", help="締め切り: 参加のチェックから大会の名簿を作って送る")
    ap.add_argument("--redo", action="store_true", help="--kakutei で、抽せんの前に大会の名簿を作り直す")
    a = ap.parse_args()
    if not re.fullmatch(r"[a-z0-9-]{1,20}", a.group):
        raise SystemExit("--group は英小文字・数字・- で20字まで")
    gdir = KAI / "g" / a.group
    cfg = json.loads(Path(a.config or gdir / "taikai.json").read_text(encoding="utf-8"))
    api = Api(cfg)
    # 出席確認の一覧は、幹部用ページの skai と同じ回の名前（<kai>-s）
    if (a.shukketsu or a.kakutei) and not re.fullmatch(r"[0-9A-Za-z-]{1,24}", str(cfg["kai"]) + "-s"):
        raise SystemExit("NG 回の名前が長すぎて、出席確認の一覧（<kai>-s）を作れない（kai は22字まで）")
    if a.redo and not a.kakutei:
        raise SystemExit("NG --redo は --kakutei と使う")
    if a.kakutei:
        kakutei(api, cfg, a.redo)
        return
    if a.shukketsu:
        api.kai = str(cfg["kai"]) + "-s"
    if a.test:
        test(api)
    elif a.show:
        show(api, a.shukketsu)
    elif a.file and a.shukketsu:
        names = read_names(a.file)
        keep_numbers(api, names)
        send(api, names, None)
    elif a.file:
        send(api, read_names(a.file), cfg.get("players"))
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
