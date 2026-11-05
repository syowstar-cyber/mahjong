# -*- coding: utf-8 -*-
"""普段の回の組み合わせを、ナンバーズ4の当せん番号のくじで決める（kai/kuji/index.html と同じ計算。第20回の tools/kuji.py を移したもの）。
型は抽せんの前に kumiawase.py --write が kai/g/<会>/kata.json へ書く（卓・席・抜け番を、P番号の代わりに枠1〜枠N で決めたもの）。
種     = "<回の名前>|<抽せんの日>|N4=<当せん番号>"（先頭の0も残して4桁。例 halu-2026-11-14|2026-11-13|N4=0482）
くじ値 = SHA-256(種 + "|P" + 番号) の16進64桁（くじを引く人＝P1〜PN から、型で外した人を除いた全員）
くじ値の小さい順に 枠1〜 を割り当て、型の枠を P番号に置き換える。型で外した人は、その後ろの枠（どの半荘もお休み）。

使い方:
  python kai/tools/kuji.py 0482            … 計算して表示だけ（何も書かない）
  python kai/tools/kuji.py 0482 --write    … 本番: kumiawase.json に書く（早川研は --group hayakawa を足す）
  python kai/tools/kuji.py --check         … kumiawase.json の本番の番号で計算し直し、型のとおりか確かめる
  --redo は、本番の番号を打ち間違えて書いたときだけ（公式の番号で書き直す。組み直した表も消える）。
  --config / --out / --kata は試験用（既定は kai/g/<会>/ の taikai.json・kumiawase.json・kata.json）"""
import argparse, re, sys
from datetime import datetime
from pathlib import Path
import io

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kumiawase as K  # noqa: E402  同じフォルダの組み合わせの道具（検査・成績・書き出しを共通に使う）


def check(cfg, kata, old):
    """本番の番号で計算し直し、kumiawase.json の表が型のとおりか確かめる。組み直した半荘は、それより前だけを比べる"""
    if not K.lottery_done(cfg, old):
        raise SystemExit("kumiawase.json に本番の番号がまだない（抽せんの後に kuji.py <番号> --write）")
    errs = K.validate(cfg, old)
    if errs:
        print("■ 形に問題あり"); [print("  " + e) for e in errs]
        sys.exit(1)
    n4 = K.norm_n4(old["kuji"]["n4"])
    want = K.lottery_rounds(kata, n4)
    # 組み直した表（kumiawase.py が remade と from を書く）は、組み直した半荘より前だけを比べる
    start = old.get("from", 1) if old.get("remade") or old.get("from", 1) > 1 else cfg["prelim"] + 1
    bad = [k for k in sorted(want, key=int) if int(k) < start and old["rounds"].get(k) != want[k]]
    print("種:", K.kuji_seed(kata, n4))
    if bad:
        print("不一致: " + "・".join(bad) + "半荘目が型と本番の番号のとおりでない（kuji.py <番号> --write で作り直す）")
        sys.exit(1)
    if start > cfg["prelim"]:
        print("一致（全部の半荘が、型と本番の番号のとおり）")
    else:
        outs = sorted({p for k, r in old["rounds"].items() if int(k) >= start for p in r.get("out", [])}, key=K.pnum)
        print(("一致（" + str(start - 1) + "半荘目まで）。" if start > 1 else "") + f"{start}半荘目からは当日の組み直し"
              + ("（お休み: " + "・".join(outs) + "）" if outs else ""))


def main():
    ap = argparse.ArgumentParser(description="ナンバーズ4の当せん番号のくじで、組み合わせを決める")
    ap.add_argument("n4", nargs="?", help="ナンバーズ4の当せん番号（4桁。例 0482）")
    ap.add_argument("--group", default="halu", help="会（kai/g/<会>/ の設定を使う。既定は halu）")
    ap.add_argument("--config")
    ap.add_argument("--out")
    ap.add_argument("--kata")
    ap.add_argument("--write", action="store_true", help="kumiawase.json に書く")
    ap.add_argument("--check", action="store_true", help="kumiawase.json が型と本番の番号のとおりか確かめる")
    ap.add_argument("--redo", action="store_true", help="打ち間違えた本番の番号を、公式の番号で書き直す")
    ap.add_argument("--quiet", action="store_true", help="表と一人ずつの成績を出さない")
    a = ap.parse_args()
    if not re.fullmatch(r"[a-z0-9-]{1,20}", a.group):
        raise SystemExit("--group は英小文字・数字・- で20字まで")
    gdir = K.KAI / "g" / a.group
    cfg = K.load(a.config or gdir / "taikai.json")
    K.check_cfg(cfg)
    if not cfg.get("kuji"):
        raise SystemExit("taikai.json に kuji（抽せんの日）がない＝この会はくじを使わない")
    out = Path(a.out or gdir / "kumiawase.json")
    old = K.load(out)
    kata = K.load_kata(a.kata or gdir / "kata.json", cfg, str(cfg["kuji"]))
    if a.check:
        check(cfg, kata, old)
        return
    if not a.n4:
        raise SystemExit(__doc__)
    n4 = K.norm_n4(a.n4)
    if kata["players"] > cfg["players"]:
        raise SystemExit(f"型の人数（{kata['players']}）が players（{cfg['players']}）より多い。来られない人は、抽せんの後に kumiawase.py --absent で外す")
    seed = K.kuji_seed(kata, n4)
    print("種:", seed)
    for k, (p, h) in enumerate(K.draw(seed, K.kata_present(kata)), 1):
        print(f"枠{k:>2} {p:>3} {h[:16]}")
    ko = K.kata_out(kata)
    for p, s in zip(ko, K.out_slots(kata["players"], ko)):
        print(f"枠{K.pnum(s):>2} {p:>3} （型で外した人。くじに入れない・どの半荘もお休み）")
    rounds = K.lottery_rounds(kata, n4)
    kumi = {"kai": cfg["kai"], "made": datetime.now(K.JST).strftime("%Y-%m-%d %H:%M"), "from": 1, "kuji": {"date": kata["date"], "n4": n4}, "rounds": rounds}
    errs = K.validate(cfg, kumi)
    if errs:
        print("■ 作った表に問題あり（書きません）"); [print("  " + e) for e in errs]
        sys.exit(1)
    if not a.quiet:
        K.show(cfg, rounds)
    K.report(cfg, rounds)
    if kata["players"] < cfg["players"]:
        print(f"※ 型より後に増えた人（P{kata['players'] + 1}〜P{cfg['players']}）は、書いたあとに kumiawase.py --write で入れる（枠は番号のまま）")
    if not a.write:
        print("（書いていません。--write で書きます）")
        return
    if K.lottery_done(cfg, old) and not a.redo:
        if old["kuji"]["n4"] != n4:
            raise SystemExit(f"本番の番号（{old['kuji']['n4']}）がもう入っている。くじは引き直さない（打ち間違いを直すときだけ --redo）")
        if old.get("remade"):
            raise SystemExit("抽せんの後に組み直した表がある。書くと組み直しが消える（そうしたいときだけ --redo）")
    out.write_text(K.dump(kumi), encoding="utf-8")
    print(f"書きました: {out}")


if __name__ == "__main__":
    # 面A（実行エントリの責務）: stdout/stderr を UTF-8 に固定＝cp932 コンソールでの UnicodeEncodeError 防止。
    # pythonw で起動すると stdout/stderr は None（.buffer で即落ちる）＝None のときは包まない。
    if sys.stdout is not None:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if sys.stderr is not None:
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    main()
