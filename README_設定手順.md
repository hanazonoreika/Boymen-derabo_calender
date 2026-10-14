# ボイメン5人 統合イベントカレンダー（GitHub Pages + Actions）

## できること
- 月間カレンダー、メンバーカラー、公式URL、詳細表示
- 手動予定はブラウザの localStorage に保存
- GitHub Actions が6時間ごとに公式ページを確認し、`data/events.json` を更新
- BOYS AND MEN側・でらボ側は別々に取得し、一方が失敗しても他方の取得結果を残す
- 過去1年〜未来1年の明示的な日付が取れた情報を対象にする（年が書かれていない日付は推測しない）

## 初回セットアップ（無料）
1. https://github.com/ でアカウントを作成し、メール確認を完了する。
2. ログイン後、右上の `+` → `New repository`。
3. Repository name に `boimen-calendar` と入力。
4. **Public** を選び、`Create repository`。
   - GitHub Free の Pages は公開リポジトリで利用する構成です。公開リポジトリのソースコードは誰でも見られるので、個人情報や秘密情報を入れないでください。
5. 作成したリポジトリの `Add file` → `Upload files` を選び、このZIPを展開した中身をアップロードする。`.github` フォルダも必要です。フォルダを含むアップロードがうまくいかない場合は、下の「ブラウザ上でファイルを作る」を参照。
6. `Commit changes` を押す。
7. `Settings` → `Pages` → `Build and deployment` → `Source` で **GitHub Actions** を選ぶ。
8. `Actions` タブで `Update official schedules and publish calendar` の実行結果を確認。初回は `Run workflow` を押して手動実行してもOK。
9. 成功したら `Settings` → `Pages` の上部に表示される `https://USERNAME.github.io/boimen-calendar/` を開く。

## GitHub Actions が動いたか確認
- リポジトリの `Actions` → `Update official schedules and publish calendar` → 最新実行を開く。
- `Scrape official schedules` のログと `data/events.json` を見る。
- 公開サイトの「公式データを再読込」は、既に公開済みの JSON を読み直す操作。スクレイピングをその場で起動するボタンではありません。
- 定期実行は6時間ごと。GitHub Actions のスケジュール実行は混雑時に遅れることがあります。

## 大事な制限
- このスクレーパーは公開HTML内のリンクと、明示的な年付き日付を使う「ベストエフォート」の実装です。公式サイトのDOMや掲載形式が変わると、0件になったり、記事のタイトルとイベント日が結び付かない場合があります。
- 公式サイトの全イベントを完全に抽出できると保証するものではありません。初回実行後に `data/events.json` の件数と出典URLを確認し、必要に応じて `scripts/scrape.py` の解析を調整してください。
- 公式サイトのアクセス条件・利用規約を尊重し、頻度を過度に上げないでください。
- 手動予定は端末・ブラウザごとに保存され、別端末とは同期されません。必要に応じて「バックアップ」を使ってください。
- 公式データはGitHubリポジトリに公開されます。手動予定はブラウザ内だけです。

## 「ブラウザ上でファイルを作る」方法
GitHubの `Add file` → `Create new file` を使い、各ファイルを1つずつ作成・貼り付けてください。パス欄に `.github/workflows/update-and-deploy.yml` のようにフォルダ込みで入力するとフォルダも作れます。スクリプトとHTMLはZIP内の同名ファイルをコピーします。

## 取得が失敗する場合
Bitfanまたは公式サイトがHTMLを動的生成している場合、requestsで取得したHTMLだけでは日付とイベントの関連付けが取れないことがあります。その場合は、失敗したサイトのHTML構造に合わせて抽出処理を調整します。一方のサイトの失敗はもう一方の同期を停止しない作りです。
