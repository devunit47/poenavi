# ぽえなび（PoENavi）

> このリポジトリは[buri34/poenavi](https://github.com/buri34/poenavi)のフォークです。フォークではソースのみを公開しています。ビルド済みZIPは[本家のReleases](https://github.com/buri34/poenavi/releases)から入手し、本家公式版の不具合は[本家のIssues](https://github.com/buri34/poenavi/issues)へ報告してください。

フォークで加えた主な変更

- 設定から配色・フォント・基準文字サイズを変更できるようにしました。
- ぽえとれのタイトルをタイトルバーに移し、画面の余白やアイコンボタンのホバー表示を調整しました。
- ぽえとれのレート表示が幅に収まらないときも、省略記号が残るようにしました。

Path of Exile 1 / Path of Exile 2向けの、Windows用プレイ支援ツールです。

攻略・レベリングを支援する「ぽえなび」と、日本語アイテムの価格検索・取引検索を支援する「ぽえとれ」を、起動時に選択して利用できます。

> [!IMPORTANT]
> 本ツールはGrinding Gear Gamesとは提携しておらず、同社による公認・承認を受けたものではありません。

## ぽえなびの主な機能

- PoE1 / PoE2のエリア移動・レベルアップ・Act進行を自動検知
- 攻略ガイド、マップ画像、経験値効率の目安を表示
- 自動ラップ対応のRTAタイマー
- 小型オーバーレイ「みになび」（PoE1 / PoE2）
- VOICEVOXによるみになびの音声案内（PoE2）
- PoBからのジェム取得リスト作成（PoE1）
- エリアメモ、切り離し可能な補助パネル
<img width="2314" height="1219" alt="poenavi2" src="https://github.com/user-attachments/assets/fa1232cb-707c-432d-b4cd-d08e8611ea9f" />

## ぽえとれの主な機能

- 日本語版でコピーしたアイテムを解析し、公式Trade APIで検索（PoE1 / PoE2）
- MOD・数値範囲・アイテム状態・検索プリセットを画面上で調整
- 価格一覧、価格推移、関連アイテムの参考価格を表示
- 操作モードとAUTO-HIDEに対応した変更可能な検索ホットキー
- メモ、画像管理、Cheat sheets
- OBS配信用の専用検索結果ウィンドウ
- Map Modチェック（PoE1）
- エクスペディション報酬を読み取り、poe.ninja価格を高貴なオーブ換算で表示（PoE2）
- アビス冒涜modのUnveil画面を読み取り、modのティアを表示（PoE2）
<img width="2090" height="1319" alt="poetore2" src="https://github.com/user-attachments/assets/9f3f0da0-d9be-42e8-831b-9eaf921207fa" />


## 共通機能

- PoE1 / PoE2と、ぽえなび / ぽえとれの起動モードを選択
- タスクトレイへの格納と復帰
- 自動アップデート

詳しい機能説明と画像付きの使い方は、原作者Buriの以下の記事にまとまっています。

- [ぽえなびの使い方を解説](https://note.com/buri8857/n/nd1e6a07b8a29)
- [ぽえとれの使い方を解説](https://note.com/buri8857/n/n8a5047edab08)

## ダウンロード

1. [本家のReleases](https://github.com/buri34/poenavi/releases)から、本家で配布されている公式版の最新版`PoENavi.zip`をダウンロード
2. ZIPを右クリックし、Windows標準の「すべて展開」で解凍
3. 解凍先の`PoENavi.exe`を起動

Pythonのインストールは不要です。設定やメモは`%APPDATA%\PoENavi\`へ保存されるため、アプリを更新しても引き継がれます。

フォークの変更を試す場合は、[ソースから起動](#ソースから起動)してください。

> [!WARNING]
> 現在の配布版はコード署名証明書を使用していません。また、PyInstaller製アプリの内部構造や利用実績などにより、SmartScreenの警告や一部のウイルス対策ソフトによる誤検知が発生する場合があります。
>
> SmartScreenが表示された場合は、発行元とダウンロード元が本家のリポジトリであることを確認したうえで、「詳細情報」から実行できます。不安な場合は実行せず、公開ソースから直接起動してください。

### 配布ファイルのウイルス検査

以下は本家で配布されている公式版についての記載です。

各リリースの`PoENavi.zip`はVirusTotalでスキャンし、
検査結果URLとSHA-256を該当するReleaseページへ掲載しています。

VirusTotalは、Microsoftなど複数のセキュリティ製品で同じファイルを検査し、その判定をまとめて確認できる第三者サービスです。
<img width="2168" height="1119" alt="poenavi" src="https://github.com/user-attachments/assets/e272273b-1273-4a7e-b7a1-a1daa59e33de" />
SHA-256が一致することで、検査対象と配布ファイルが同一であることも確認できます。

VirusTotalの結果は安全性を完全に保証するものではありませんが、
第三者サービスによる確認材料として公開しています。

最新版の結果は[本家のReleases](https://github.com/buri34/poenavi/releases)から確認してください。

### コード署名

以下は本家で配布されている公式版についての記載です。

Free code signing provided by [SignPath.io](https://signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).

PoENaviは、今後のWindows向けリリースを署名するためSignPath Foundationのオープンソース向けコード署名プログラムへ申請しています。審査・導入が完了するまで、現在の配布版は未署名です。

## 最初に行う設定

1. 起動時にPoE1 / PoE2を選択
2. 「ぽえなび」または「ぽえとれ」を選択
3. ぽえなびを使う場合は、設定画面で`Client.txt`の場所を確認
4. ぽえなびを使う場合は、PoE側のチャット設定で「ローカル」を有効化

「設定 → 外観」で、両モード共通の配色とフォントを変更できます。プリセットに加え、
文字・背景・枠線などの8色、フォント、基準文字サイズを選択できます。
保存後の案内から再起動すると反映されます。「外観を既定に戻す」で元の配色へ戻せます。
既定では従来のモード別配色を維持し、レアリティやマップ区分などのゲーム内容を表す色は固定です。

ぽえとれは、ゲーム内でアイテム情報をコピーして検索ホットキーを押すと利用できます。PoE2のエクスペディション報酬価格チェックは初期状態では無効です。ぽえとれ上部の専用ボタンから有効化し、環境に合わせて読取範囲を指定してください。

`Client.txt`は一般的に次の場所にあります。通常は自動検出されます。

```text
PoE1 Steam: C:\Program Files (x86)\Steam\steamapps\common\Path of Exile\logs\Client.txt
PoE2 Steam: C:\Program Files (x86)\Steam\steamapps\common\Path of Exile 2\logs\Client.txt
```

## 対応環境・制約

- 正式対応：Windows 10 / 11
- 対応ゲーム：Path of Exile 1 / Path of Exile 2
- ぽえとれ：PoE1 / PoE2
- PoBインポート：PoE1のみ
- VOICEVOX読み上げ：PoE2のみ（VOICEVOX本体の起動が必要）
- エクスペディション報酬価格チェック：PoE2版ぽえとれ・Windows 10 / 11のみ
- Linux：非公式サポート。一部のWindows依存機能は動作保証外
- PoEのローカルチャットログが無効だと、一部の自動ラップやガイド切替を検知できません

## 安全性と外部通信

PoENaviはゲームとは独立して動作し、処理内容をこのリポジトリで公開しています。

### PC内で読み取る情報

- PoEの`Client.txt`：エリア、レベル、Act進行、およびぽえとれ隠れ家滞在通知（集中モード）の検知
- ユーザーがコピーしたアイテム情報：ぽえとれの価格検索
- PoEウィンドウの位置・プロセス名・起動状態：対象ウィンドウの識別と隠れ家滞在通知
- ユーザーが指定した画面範囲の画像：PoE1ハイスト報酬／トリンケット、PoE2エクスペディション報酬、およびPoE2アビス冒涜ModのローカルOCR

設定、メモ、タイマー記録、価格キャッシュ、OCR用画像処理はPC内で扱います。`Client.txt`の内容、個人メモ、キャプチャ画像、OCR読取文字列を外部へ送信することはありません。

### 行わないこと

- ゲームメモリの読み取り・書き換え
- ゲームプロセスへのコード注入
- ゲームクライアントやゲームファイルの改変
- ネットワークパケットの傍受・改ざん
- 自律的な戦闘・移動・アイテム操作
- PoEアカウントの認証情報やセッション情報の収集

### OCRを使用する画面読取機能

PoE1の「ハイスト報酬／トリンケットOCR」、PoE2の「エクスペディション報酬価格チェック」と「アビス冒涜Modティアチェック」は、ユーザーが設定したホットキーを押した時だけ実行されます。

処理の流れは次のとおりです。

1. OSの画面キャプチャ機能で、ユーザーが指定したPoE画面の範囲を取得
2. Windows OCRを使ってPC内で文字を解析
   - ハイスト報酬やアビス冒涜Modなどで補助が必要な場合に限り、自動取得した高精度OCRパック（NDLOCR-Lite、PC内 `%LOCALAPPDATA%\PoENavi\ocr-packs\` に保存）でローカル再確認
3. 解析結果をPoENaviの独立したウィンドウとして表示

これらのOCR機能は、ゲームメモリやゲームファイルを読み取らず、ゲームプロセスへのコード注入も行いません。また、OCR結果を使った自動クリック、キー入力、Mod選択などのゲーム操作は行いません。

キャプチャ画像やOCRで読み取った文章は外部へ送信されません。エクスペディション／ハイスト報酬の参考価格はpoe.ninjaから取得し、アビス冒涜ModのTier判定にはPoENaviへ同梱したローカルデータを使用します。

Grinding Gear GamesのDeveloper Policyでは、ゲームとは独立して動作する実行アプリは「推奨はしないが許可する」とされる一方、ゲームクライアント、メモリ、ゲームファイルへの介入や、画面認識を起点とした自動操作は禁止されています。

PoENaviのOCR機能は、この方針を考慮して「ユーザーによる手動実行・画面の読取専用・ローカル解析・独立ウィンドウへの表示」という設計にしています。

この説明はGrinding Gear Gamesによる個別の承認を意味するものではありません。最新の方針は公式Developer Policyをご確認ください。

- [Path of Exile Developer Policy](https://www.pathofexile.com/developer/docs/index#policy)
- [Path of Exile Terms of Use](https://www.pathofexile.com/legal/terms-of-use-and-privacy-policy)

### 外部通信先

- GitHub Releases（`api.github.com` / `github.com`）：本家公式版のアップデート確認・取得、および高精度OCRパック（NDLOCR-Lite）の取得
- Path of Exile公式Trade / Leagues API（`www.pathofexile.com` / `jp.pathofexile.com`）：アイテム名、MOD、数値などの検索条件送信・リーグ取得
- Path of Exile公式CDN（`web.poecdn.com`）：アイテム／通貨アイコンおよびCurrency Exchange参考データ取得
- poe.ninja（`poe.ninja`）：通貨・アイテムの参考価格取得
- PoE Wiki（`www.poewiki.net`）：検索結果で表示するアイテム画像取得
- VOICEVOX Engine（`http://127.0.0.1:50021`、PC内ローカル通信のみ）：PoE2みになびの音声案内有効時のみ

ユーザー操作を起点に、検索文字列やチャットコマンドなどのキー入力をPoEへ送る機能があります。ログアウト機能を有効にしてホットキーを押した場合は、PoEクライアントのTCP接続を切断します。

## Safety and External Communications (English)

PoENavi runs independently from the game, and its source code is publicly available in this repository.

### Information Read Locally

- PoE's `Client.txt`: used to detect areas, levels, Act progression, and optional Poetore hideout-stay notifications
- Item information copied by the user: used for trade searches in Poetore
- The PoE window position, process name, and process state: used to identify the target window and support hideout-stay notifications
- Images of user-selected screen regions: used for local OCR of PoE1 Heist rewards/trinkets, PoE2 Expedition rewards, and PoE2 Abyss Desecration modifiers

Settings, notes, timer records, price caches, screenshots, and OCR processing remain on the user's PC. The contents of `Client.txt`, personal notes, captured images, and OCR text are not uploaded.

### What PoENavi Does Not Do

- Read or modify game memory
- Inject code into the game process
- Modify the game client or game files
- Intercept or alter network packets
- Automate combat, movement, or item interaction
- Collect PoE account credentials or session information

### OCR-Based Screen Reading

The PoE1 Heist reward/trinket OCR, PoE2 Expedition reward price checker, and PoE2 Abyss Desecration modifier Tier checker run only when the user presses the configured shortcut.

1. A user-configured region of the PoE screen is captured through the operating system's screen-capture API.
2. Text is recognized locally using Windows OCR.
   - When additional local confirmation is needed (such as missing numbers in Abyss Desecration modifiers or Heist OCR), the automatically downloaded high-accuracy OCR pack (NDLOCR-Lite, stored locally under `%LOCALAPPDATA%\PoENavi\ocr-packs\`) rechecks locally.
3. The result is shown in a separate PoENavi window.

These OCR features do not read game memory or files, inject code, or interact with the game process. OCR results are never used to click, press keys, select modifiers, or perform any other in-game action automatically.

Captured images and recognized text are not sent to an external server. Reference prices are obtained from poe.ninja, while Abyss Desecration modifier Tiers are determined using data bundled with PoENavi.

PoENavi's OCR features are designed with the Path of Exile Developer Policy in mind: they are manually initiated, read-only, processed locally, and displayed in a separate application window. This statement does not mean that PoENavi has been individually reviewed, endorsed, or approved by Grinding Gear Games. Please refer to the current official policies:

- [Path of Exile Developer Policy](https://www.pathofexile.com/developer/docs/index#policy)
- [Path of Exile Terms of Use](https://www.pathofexile.com/legal/terms-of-use-and-privacy-policy)

### External Connections

- GitHub Releases (`api.github.com`, `github.com`): checking for and downloading official updates, and downloading the optional NDLOCR-Lite high-accuracy OCR pack
- Official Path of Exile Trade & Leagues API (`www.pathofexile.com`, `jp.pathofexile.com`): submitting item names, modifiers, values, and other search conditions, and fetching league lists
- Official Path of Exile CDN (`web.poecdn.com`): downloading item/currency icons and Currency Exchange reference data
- poe.ninja (`poe.ninja`): obtaining reference prices for currencies and items
- PoE Wiki (`www.poewiki.net`): downloading item images displayed in search results
- VOICEVOX Engine (`http://127.0.0.1:50021`, localhost only): used only when PoE2 Mini-Navi voice guidance is enabled

Some non-OCR features can send search text or chat commands to PoE, but only in response to an explicit user action. OCR results never initiate keyboard or mouse input to the game. When the logout feature is enabled and its shortcut is pressed, PoENavi disconnects the PoE client's TCP connection.

## アップデート

自動アップデートは[本家のReleases](https://github.com/buri34/poenavi/releases)を参照する公式版の機能です。ソースから起動したフォーク版を更新する場合は、フォークのソースを取得し直してください。

起動時にGitHub Releasesの安定版を確認します。「今すぐアップデート」を選ぶと、ZIPのダウンロードとSHA-256検証を行い、ファイル更新後にPoENaviを再起動します。

手動確認は、設定画面の「アプリ情報 → アップデートを確認」から行えます。

## アンインストール

PoENaviはインストーラーやWindowsサービスを使用しません。アンインストールするには、PoENaviを終了して、展開した`PoENavi`フォルダを削除してください。

設定、メモ、タイマー記録なども削除する場合は、`%APPDATA%\PoENavi\`（高精度OCRパックを利用している場合は`%LOCALAPPDATA%\PoENavi\ocr-packs\`）を削除してください。必要な記録がある場合は、先にバックアップしてください。

## 不具合報告・要望

本家公式版の不具合や要望は、[本家のGitHub Issues](https://github.com/buri34/poenavi/issues)へ、次の情報を添えて報告してください。

- PoENaviのバージョン
- PoE1 / PoE2と、ぽえなび / ぽえとれのどちらか
- 再現手順と期待した動作
- エラーメッセージやスクリーンショット

個人情報、PoEの認証情報、APIキーなどは掲載しないでください。

フォーク固有の変更に起因する問題は、本家への報告を控え、このフォークのPull Requestなどでお知らせください。

## ソースから起動

```bash
git clone https://github.com/devunit47/poenavi.git
cd poenavi
pip install -r requirements.txt
python main.py
```

本家のソースから起動する場合は、次のURLでクローンし、同じ手順で起動してください。

```bash
git clone https://github.com/buri34/poenavi.git
```

テストは次のコマンドで実行できます。

```bash
python -m pytest -q
```

## 技術構成

- Python 3.12+
- PySide6（Qt 6）
- pynput / Windows API
- urllib3
- miniaudio（WAV／MP3通知音声の再生）
- Windows OCR（PoE1ハイスト報酬／トリンケット、PoE2エクスペディション報酬・アビス冒涜Mod読取）
- NDLOCR-Lite 1.3.1（PoE1ハイスト報酬やPoE2アビス冒涜Modの補助OCR）
- PyInstaller

## License・免責・Credits

- [MIT License](LICENSE)
- [第三者ライセンス・データ出典](THIRD_PARTY_NOTICES.md)
- [Privacy policy](PRIVACY.md)
- [Code signing policy](docs/CODE_SIGNING_POLICY.md)
- [Path of Exile](https://www.pathofexile.com/) by Grinding Gear Games
- 原作者（本家） [Buri](https://github.com/buri34)
- フォーク管理者 [devunit47](https://github.com/devunit47)

Path of Exile、ゲーム内名称、アイテムおよび関連ゲームデータの権利はGrinding Gear Gamesに帰属します。

## サポート

ぽえなびを気に入っていただけたら、以下のリンクから本家作者Buriの開発環境の維持・改善を応援できます。

- [OFUSE（おふせ）](https://ofuse.me/48eca107)
- [Ko-fi](https://ko-fi.com/buri8857)
- [Patreon](https://www.patreon.com/cw/Buri8857)
