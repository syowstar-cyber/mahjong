# Haluリーグ（個人戦のリーグ）

全員が全員と同じ回数だけ打つ、長いリーグのページ一式。
決めたことと、その理由は `docs/Haluリーグ_設計.md`。

## ページ

- スコアボード `league/`。`?s=<シーズン>` で前のシーズンを開く。付けなければ `seasons.json` の今期。
- 点数入力 `league/score/`。カードを選び、4人の名前ごとに点棒（百点単位）と打った日を入れて送る。
- 調整表 `league/chousei/`。日ごとに○△×を付けて送る。4人とも○のカードを日ごとに出す。
- ルール `league/rule/`。第20回 Halu杯のルールを元に、リーグに合わせて直したもの。受け口は使わない。
- 4つのページの上と下に、切り替えのボタンがある。`?s=` は切り替えても付いたまま。

## ファイル

| 置き場 | 中身 |
|---|---|
| `seasons.json` | シーズンの一覧（list）と今期（current） |
| `s/<シーズン>/season.json` | シーズンの設定（下の表） |
| `s/<シーズン>/cards.json` | 対戦カード。`tools/cards.py` が書く。始まった後は書き直さない |
| `tools/cards.py` | 対戦カードを作って検算する |
| `gas/Code.gs` | 受け口（GAS）。点数・名簿・予定を受ける。配置の手順は `gas/README.md` |
| `tools/meibo.py` | 名簿を受け口へ送る。`--show` で受け口の様子、`--test` で試しの送信 |

名前はファイルに置かない。リポにあるのは P1〜の番号だけで、名前は受け口の名簿から読む。

## season.json の項目

| 項目 | 意味 |
|---|---|
| season | シーズンの名前（フォルダの名前と同じ） |
| title・short | 画面の題・短い名前 |
| color | 見出しの色 |
| mode | 1卓の人数（4） |
| players | 人数 |
| tables | 1回戦の卓の番号（[1, 2]） |
| rounds | 回戦の数 |
| start・return | 持ち点・返し |
| uma | 順位点（オカは別）。オカ（(return−start)×mode）は1着に足す |
| from・to | 期間。from の日から、対戦カードは書き直せない |
| place | 会場 |
| slots | 調整表に出す日。`{days: 曜日（0が日曜〜6が土曜）の並び, label: 時間の名前, main: 基本の日なら true}` の並び。なければ土曜のランチ後と月〜金の夜 |
| api | 受け口の URL。空なら記録を読まない |

## 新しいシーズンを始める

1. `s/<シーズン>/season.json` を作る。api は前のシーズンと同じ URL。
   - シーズンは番号で呼ぶ。フォルダと season は `season2`、title は「Haluリーグ〜シーズン2〜」の形（年は付けない）。
2. `python league/tools/cards.py --season <シーズン> --write` で対戦カードを作る。
3. `seasons.json` の list に足し、current を変える。
4. `python league/tools/meibo.py <名簿ファイル> --season <シーズン>` で、受け口の名簿に P1〜の名前を入れる。
5. 受け口はデプロイし直さない（置き場はシーズンごとに分かれる）。

## cards.json（対戦カード）

```json
{ "season": "season1", "made": "2026-11-08 14:48", "seed": 1,
  "rounds": { "1": { "tables": [ { "no": 1, "p": ["P1", "P5", "P8", "P9"] },
                                 { "no": 2, "p": ["P2", "P4", "P6", "P7"] } ],
                     "rest": ["P3", "P10"] } } }
```

- 卓の p は顔ぶれだけで、席の順ではない。席は卓で決める。
- 点数入力は、この並びのまま受け口へ送る。同点で0.1が割り切れない分は、並びの前の人が多く取る。
- 打つ順は回戦の順が基本。そろわないときは、そろうカードを先に打ってよい。

## 試験

- `python .work/league_test/build.py` で、試験用の写しを4枚作る（`.work` は git の対象外）。
- 写しは、本物の `gas/Code.gs` をブラウザの中で動かす（`.work/league_test/gas_shim.js`）。ルールはそのまま写す。
- `http://localhost:8125/.work/league_test/index.html`（スコアボード）を開く。
- 点数入力は `.../score/index.html`、調整表は `.../chousei/index.html`、ルールは `.../rule/index.html`。
- 送った後の状態は、3枚の間で引き継ぐ。見本に戻すときは `LGMOCK.reset()` の後に開き直す。
- 写しだけが `window.LG_BASE`・`LG_API`・`LG_TODAY`（調整表の今日）を差し替える。
- 受け口だけの検査は `.../gas_check.html`（59項目）。
