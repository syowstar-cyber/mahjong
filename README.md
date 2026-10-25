# mahjong

麻雀の普段の会で使うページ一式（GitHub Pages・公開）。記念大会（店の貸し切り・ゲストあり）の一式は halu-cup リポにある。

| フォルダ | 中身 | 公開ページ |
|---|---|---|
| `kai/` | Halu杯の普段の回（3麻・4麻）のキット。組み合わせページ・点数ページ・組み合わせを作るスクリプト・受け口。使い方は `kai/README.md` | https://syowstar-cyber.github.io/mahjong/kai/ |
| `hayakawa/` | 早川麻雀研究会（4人・6半荘）の点数ページ・ルール・点数計算。受け口は別のプロジェクト（`hayakawa/gas/`） | https://syowstar-cyber.github.io/mahjong/hayakawa/ |
| `docs/` | 普段の回のキットの設計と決めごと（`普段の回_設計.md`）と、前日・当日・終わった後の手順（`普段の回_手順書.md`） | ― |

- 公開リポなので、参加者の名前・連絡先・金額・パスワードやキーをファイルに置かない。名前は受け口（Google Apps Script のスクリプト プロパティ）にだけ持つ。
- 検索エンジンには載らない設定（`robots.txt` と各ページの `noindex`）。
- `.work/`（試験の道具など）は git に入れない。
