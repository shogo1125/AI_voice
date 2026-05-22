# AI ボイスレコーダー（ローカルWhisper + Notion）

QZT 16GB で録音した音声を、ローカルWhisper（smallモデル）で文字起こしし、Notionデータベースに保存するパイプラインです。

## 必要なもの

- Mac（Apple Silicon推奨）
- QZT 16GB ボイスレコーダー（約¥4,000）
- [uv](https://docs.astral.sh/uv/)（Pythonパッケージ管理）
- ffmpeg
- Notionアカウント（無料プランでOK）

---

## セットアップ

### 1. uv をインストール（未インストールの場合）

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. ffmpeg をインストール

```bash
brew install ffmpeg
```

### 3. Python 仮想環境を作成してライブラリをインストール

```bash
uv sync
```

これにより `.venv/` が自動作成され、ライブラリがインストールされます。
システムのPython環境は汚染されません。

### 4. Notion 内部コネクト（インテグレーション）を作成

> `my-integrations` は [developers/connections](https://www.notion.so/developers/connections) にリダイレクトされます。正常な動作です。

#### 4-1. プライベートコネクトを作成してトークンを取得

1. [https://www.notion.so/developers/connections](https://www.notion.so/developers/connections) を開く
2. **「+ 新規コネクト」** をクリック（プライベート / 内部API接続を作成）
3. 名前（例: `AI_voice`）と **インストール可能なワークスペース** を設定
4. **機能（Capabilities）** で次を有効にする:
   - コンテンツを読み取る
   - コンテンツを更新する
   - **コンテンツを挿入**（ページ作成に必須）
5. 作成したコネクトの **「設定」** タブ → **「インテグレーショントークン」** → **アクセストークン** をコピー  
   - `ntn_` または `secret_` で始まる文字列（どちらも同じ用途）

#### 4-2. Notionデータベースを作成

1. Notionで新しいページを作成し、「データベース（テーブル表示）」を追加する
2. デフォルトで「名前」というタイトル列があればそのまま使用できる

#### 4-3. データベースをコネクトに接続

1. データベースを **フルページで開く**（親ページ内の埋め込み表示ではなく、データベース単体の画面）
2. 右上 **「⋯」** → **「コネクトを追加」**（または「接続を追加」）
3. 手順4-1で作成したコネクト（例: `AI_voice`）を検索して選択

一覧に出ない場合は、コネクトの **「コンテンツへのアクセス」** タブからデータベースを直接追加できます。

#### 4-4. データベースIDを取得

データベースをフルページで開き、ブラウザのアドレスバーからIDを取得する。

```
https://www.notion.so/367b98b3824f80ba8ebcff1734f4dab9?v=...
                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                       この32文字（ハイフンなし）がデータベースID
```

ハイフン付きのUUID形式（`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`）でも動作します。

### 5. .env ファイルを作成

`.env.example` をコピーして `.env` を作成し、取得した値を入力する。

```bash
cp .env.example .env
```

`.env` を編集:

```
NOTION_TOKEN=ntn_xxxx          # 手順4-1のアクセストークン
NOTION_DATABASE_ID=xxxx...    # 手順4-4のデータベースID
NOTION_TITLE_PROP=名前          # データベースのタイトル列名
```

> **NOTION_TITLE_PROP について**
> 日本語Notionでは「名前」が多いですが、環境によって異なります。
> 実行時に `〇〇 is expected to be title.` というエラーが出た場合は、
> エラーメッセージの「〇〇」をそのまま `NOTION_TITLE_PROP` に設定してください。

### 6. 設定の確認（任意）

WAVファイルがなくても、Notion接続だけ確認できます。

```bash
uv run pipeline.py
```

`incoming/` にWAVがない場合は「WAVファイルが見つかりません」と表示されますが、`.env` の読み込みエラーが出なければ設定は問題ありません。

---

## 使い方

### 1. QZT からファイルをコピー

1. QZT 16GB を Mac に USB 接続する
2. Finderでマウントされたドライブを開く
3. WAVファイルを `incoming/` フォルダにコピーする

```
AI_voice/
└── incoming/
    ├── 2026-05-20-09-00-00.WAV
    └── 2026-05-20-14-30-00.WAV
```

### 2. パイプラインを実行

```bash
uv run pipeline.py
```

実行ログの例:

```
==================================================
ライフログパイプライン（ローカルWhisper版）開始
==================================================

2 件のWAVファイルを検出:
   - 2026-05-20-09-00-00.WAV (45.2 MB)
   - 2026-05-20-14-30-00.WAV (22.8 MB)

Whisperモデル「small」をロード中...
モデルロード完了

処理中: 2026-05-20-09-00-00.WAV
  録音日: 2026-05-20
  分割中: 2026-05-20-09-00-00.WAV
  3 チャンクに分割完了
  文字起こし中 [1/3] 00:00:00 〜 00:15:00
    完了（286 文字）
  文字起こし中 [2/3] 00:15:00 〜 00:30:00
    完了（312 文字）
  文字起こし中 [3/3] 00:30:00 〜 00:45:00
    完了（198 文字）
  Notionにページを作成中: ライフログ 2026-05-20
  Notion保存完了: https://notion.so/...
  アーカイブ完了: archive/2026/05/2026-05-20-09-00-00.WAV
```

### 3. Notionで確認

データベースに「ライフログ YYYY-MM-DD」というページが作成され、
15分ごとのタイムスタンプ付きで文字起こし結果が保存されます。

---

## フォルダ構成

```
AI_voice/
├── incoming/        # QZTからコピーしたWAVを置く（処理後は自動削除）
├── archive/         # 処理済みWAV（年/月で自動整理）
│   └── 2026/05/
├── .venv/           # uvが自動作成する仮想環境（Gitにコミットしない）
├── .env             # APIキー（Gitにコミットしない）
├── .env.example     # .env のテンプレート
├── pipeline.py      # メインスクリプト
├── pyproject.toml   # プロジェクト設定・依存パッケージ定義
└── uv.lock          # 依存関係のロックファイル（Gitにコミットする）
```

---

## Whisperモデルの変更

処理速度と精度のバランスはモデルサイズで調整できます。
`pipeline.py` の先頭の1行を変更するだけです。

```python
WHISPER_MODEL_SIZE = "small"  # tiny / base / small / medium / large
```


| モデル    | 1時間の処理時間（CPU） | 精度    | サイズ   |
| ------ | ------------- | ----- | ----- |
| tiny   | 約5分           | 低い    | 75MB  |
| base   | 約10分          | 普通    | 150MB |
| small  | 約20分          | 良い    | 500MB |
| medium | 約35分          | とても良い | 1.5GB |
| large  | 約60分〜         | 最高    | 3GB   |


---

## トラブルシューティング

### `uv: command not found`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### `ffmpeg: command not found`

```bash
brew install ffmpeg
```

### Notion API エラー: `〇〇 is expected to be title`

`.env` の `NOTION_TITLE_PROP` をエラーメッセージの「〇〇」に変更してください。

```
NOTION_TITLE_PROP=名前  # 「名前」の部分をエラーメッセージの値に変更
```

### `KeyError: 'NOTION_TOKEN'`

`.env` ファイルが存在するか確認してください。

```bash
ls -la .env
```

