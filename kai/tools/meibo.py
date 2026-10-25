# -*- coding: utf-8 -*-
"""普段の回の名簿を受け口へ送る・受け口を試す。受け口の URL と回の名前は会ごとの kai/g/<会>/taikai.json の api と kai から読む。
名前は受け口にだけ置く＝名簿のファイルは scratchpad に置き、リポに入れない。出力に名前は出さない（P番号と人数だけ）。

使い方:
  python kai/tools/meibo.py <名簿ファイル>   … 名簿を送る。ファイルは UTF-8 で1行1人「P1 呼び名」（空白かタブで区切る）
                                               渡した番号だけ直す（直したい人の行だけ送ってもよい）
  python kai/tools/meibo.py --show            … 受け口の名簿の人数と番号を出す
  python kai/tools/meibo.py --test            … 初回のテスト送信。回 setup-test に名簿と1卓を送り、読み直し、消して空に戻るかを見る
  --group で会を選ぶ（既定は halu。早川研は --group hayakawa）。--config は試験用（既定は kai/g/<会>/taikai.json）
成功は1行目が OK で始まる。失敗は NG で始まり、終了コード 1"""
import argparse, json, re, sys, urllib.parse, urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
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
    over = [p for p in names if int(p[1:]) > players]
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


def show(api):
    j = api.get()
    if not j.get("ok"):
        raise SystemExit(f"NG 受け口がエラーを返した: {j.get('error')}")
    r = j["data"]["roster"]
    print(f"OK show 回 {api.kai}・名簿 {len(r)}人（{nums(r) if r else 'なし'}）・点数の入った半荘 {len(j['data']['rounds'])}・最終更新 {j['data']['updated'] or '―'}")


def test(api):
    """回 setup-test で、名簿→1卓→読み直し→取り消し→名簿を消す→空に戻る、を確かめる（送信履歴 LOG と最終更新 U_setup-test は残る）"""
    steps = []
    def need(ok, what):
        steps.append(("OK " if ok else "NG ") + what)
        if not ok:
            print("\n".join(steps))
            raise SystemExit(f"NG test（{what}）")
    j = api.post({"action": "roster", "kai": TEST_KAI, "names": {"P1": "テスト１", "P2": "テスト２"}})
    need(j.get("ok") and j["data"]["roster"].get("P1") == "テスト１", "名簿（日本語）を送る")
    j = api.post({"action": "score", "kai": TEST_KAI, "round": "1", "table": 1, "p": ["P1", "P2", "P3"], "raw": [45000, 35000, 25000]})
    need(j.get("ok") and j["data"]["rounds"]["1"]["1"]["raw"] == [45000, 35000, 25000], "1卓（3人）を送る")
    j = api.post({"action": "score", "kai": TEST_KAI, "round": "1", "table": 2, "p": ["P1", "P4", "P5"], "raw": [35000, 35000, 35000]})
    need(not j.get("ok") and j.get("error") == "dup", "同じ半荘のほかの卓に同じ人を送ると断る")
    j = api.post({"action": "score", "kai": TEST_KAI, "round": "1", "table": 3, "p": ["P6", "P7", "P8"], "raw": [1000000, 0, 0]})
    need(not j.get("ok") and j.get("error") == "score", "範囲外の点数を断る")
    j = api.get(TEST_KAI)
    need(j.get("ok") and j["data"]["rounds"]["1"]["1"]["p"] == ["P1", "P2", "P3"] and j["data"]["roster"].get("P2") == "テスト２", "読み直す（GET）")
    j = api.post({"action": "clear", "kai": TEST_KAI, "round": "1", "table": 1})
    need(j.get("ok") and "1" not in j["data"]["rounds"], "1卓を取り消す")
    j = api.post({"action": "roster", "kai": TEST_KAI, "names": {"P1": "", "P2": ""}})
    need(j.get("ok") and not j["data"]["roster"], "名簿を消す")
    j = api.get(TEST_KAI)
    need(j.get("ok") and not j["data"]["rounds"] and not j["data"]["roster"], "空に戻った")
    print("OK test 受け口は使える（8項目）")
    print("\n".join(steps))


def main():
    ap = argparse.ArgumentParser(description="普段の回の名簿を受け口へ送る・受け口を試す")
    ap.add_argument("file", nargs="?", help="名簿ファイル（1行1人「P1 呼び名」）")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--group", default="halu", help="会（kai/g/<会>/ の設定を使う。既定は halu）")
    ap.add_argument("--config")
    a = ap.parse_args()
    if not re.fullmatch(r"[a-z0-9-]{1,20}", a.group):
        raise SystemExit("--group は英小文字・数字・- で20字まで")
    gdir = KAI / "g" / a.group
    cfg = json.loads(Path(a.config or gdir / "taikai.json").read_text(encoding="utf-8"))
    api = Api(cfg)
    if a.test:
        test(api)
    elif a.show:
        show(api)
    elif a.file:
        send(api, read_names(a.file), cfg["players"])
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
