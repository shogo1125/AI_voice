"""
AIボイスレコーダー パイプライン
QZT 16GB → WAVコピー → ffmpegチャンク分割 → Whisper small → Notion保存
"""

from __future__ import annotations  # Python 3.9 で | 記法を使えるようにする

import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import whisper
from dotenv import load_dotenv
from notion_client import Client
from notion_client.errors import APIResponseError

# =============================================================================
# 設定
# =============================================================================

load_dotenv()

BASE_DIR = Path(__file__).parent
INCOMING_DIR = BASE_DIR / "incoming"  # QZTからコピーしたWAVを置くフォルダ
ARCHIVE_DIR = BASE_DIR / "archive"   # 処理済みWAVの保管先

WHISPER_MODEL_SIZE = "small"          # tiny / base / small / medium / large
CHUNK_DURATION_SEC = 900              # 15分（900秒）ごとに分割


def _require_env(key: str) -> str:
    """必須環境変数を取得する。未設定の場合は分かりやすいエラーで終了する。"""
    value = os.environ.get(key)
    if not value:
        print(
            f"エラー: 環境変数 {key} が設定されていません。\n"
            f".env.example を参考に .env ファイルを作成してください。"
        )
        raise SystemExit(1)
    return value


# Notion設定（.envから読み込み）
NOTION_TOKEN = _require_env("NOTION_TOKEN")
NOTION_DATABASE_ID = _require_env("NOTION_DATABASE_ID")
NOTION_TITLE_PROP = os.environ.get("NOTION_TITLE_PROP", "名前")

notion = Client(auth=NOTION_TOKEN)

# データベースIDから data_source_id を解決（Notion API 2025-09 以降は必須）
_data_source_id_cache: Optional[str] = None


def _get_data_source_id() -> str:
    """
    NOTION_DATABASE_ID から data_source_id を取得する。
    新しいNotion APIではクエリ・ページ作成に data_source_id が必要。
    """
    global _data_source_id_cache
    if _data_source_id_cache:
        return _data_source_id_cache

    db = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
    sources = db.get("data_sources", [])
    if not sources:
        raise RuntimeError(
            "データベースに data_source が見つかりません。"
            "Notionでデータベースを開き直すか、接続設定を確認してください。"
        )
    _data_source_id_cache = sources[0]["id"]
    return _data_source_id_cache


# =============================================================================
# WAVファイル検出
# =============================================================================

def find_wav_files() -> list[Path]:
    """incoming/ フォルダのWAVファイルを取得（大文字・小文字の拡張子に対応）"""
    files = list(INCOMING_DIR.glob("*.wav")) + list(INCOMING_DIR.glob("*.WAV"))
    return sorted(set(files))  # 重複除外（大文字小文字が両方マッチする環境対策）


def extract_date(wav_path: Path) -> str:
    """
    QZTのファイル名から録音日を取得する。
    例: 2026-02-20-21-06-17.WAV → "2026-02-20"
    ファイル名が不明な形式の場合は実行日の日付を返す。
    """
    m = re.search(r"(\d{4}-\d{2}-\d{2})-\d{2}-\d{2}-\d{2}", wav_path.stem)
    if m:
        return m.group(1)
    return datetime.now().strftime("%Y-%m-%d")


# =============================================================================
# ffmpeg チャンク分割
# =============================================================================

def split_into_chunks(wav_path: Path, chunk_dir: Path) -> list[Path]:
    """ffmpegでWAVを15分ごとのチャンクに分割する"""
    chunk_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(wav_path),
        "-f", "segment",
        "-segment_time", str(CHUNK_DURATION_SEC),
        "-c", "copy",
        str(chunk_dir / "chunk_%03d.wav"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 失敗:\n{result.stderr}")
    return sorted(chunk_dir.glob("chunk_*.wav"))


# =============================================================================
# Whisper 文字起こし
# =============================================================================

def transcribe_chunks(chunks: list[Path], model) -> list[dict]:
    """
    各チャンクをWhisperで文字起こしし、タイムスタンプ付きの結果リストを返す。
    戻り値: [{"timestamp": "00:00:00 〜 00:15:00", "text": "..."}, ...]
    """
    results = []
    for i, chunk in enumerate(chunks):
        start_sec = i * CHUNK_DURATION_SEC
        end_sec = start_sec + CHUNK_DURATION_SEC
        timestamp = f"{_sec_to_hms(start_sec)} 〜 {_sec_to_hms(end_sec)}"

        print(f"  文字起こし中 [{i + 1}/{len(chunks)}] {timestamp}")
        result = model.transcribe(
            str(chunk),
            language="ja",
            fp16=False,  # CPU処理時はFalseが必要（Apple Silicon MPSでもFalseで安定動作）
        )
        text = result["text"].strip()
        results.append({"timestamp": timestamp, "text": text})
        print(f"    完了（{len(text)} 文字）")

    return results


def _sec_to_hms(seconds: int) -> str:
    """秒数を HH:MM:SS 形式に変換する"""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# =============================================================================
# Notion 保存
# =============================================================================

def _make_paragraph_block(text: str) -> dict:
    """Notionのparagraphブロックを生成する"""
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }


def _build_blocks(transcription_results: list[dict]) -> list[dict]:
    """
    文字起こし結果からNotionブロックのリストを生成する。
    構成: heading_3（タイムスタンプ）+ paragraph（本文、2000文字上限で分割）
    """
    blocks: list[dict] = []
    for item in transcription_results:
        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {
                "rich_text": [{"type": "text", "text": {"content": item["timestamp"]}}],
            },
        })
        text = item["text"]
        if not text:
            blocks.append(_make_paragraph_block("（文字起こし結果なし）"))
            continue
        # Notion rich_text の1要素は2000文字まで
        for j in range(0, len(text), 2000):
            blocks.append(_make_paragraph_block(text[j : j + 2000]))
    return blocks


def _append_blocks_in_batches(page_id: str, blocks: list[dict]) -> None:
    """Notion APIの100ブロック上限に対応するため、100件ずつ分割してリクエストを送る"""
    for i in range(0, len(blocks), 100):
        notion.blocks.children.append(
            block_id=page_id,
            children=blocks[i : i + 100],
        )


def _find_existing_page(date_str: str) -> Optional[str]:
    """同じ日付のNotionページが既に存在するか検索し、存在すればpage_idを返す"""
    response = notion.data_sources.query(
        data_source_id=_get_data_source_id(),
        filter={
            "property": NOTION_TITLE_PROP,
            "title": {"equals": f"ライフログ {date_str}"},
        },
    )
    results = response.get("results", [])
    return results[0]["id"] if results else None


def save_to_notion(date_str: str, transcription_results: list[dict]) -> str:
    """
    文字起こし結果をNotionに保存する。
    同じ日付のページが既に存在する場合は追記する。
    戻り値: 作成/更新したページのURL
    """
    blocks = _build_blocks(transcription_results)

    try:
        existing_page_id = _find_existing_page(date_str)
    except APIResponseError as e:
        raise RuntimeError(
            f"Notion API エラー: {e}\n"
            f"ヒント: .env の NOTION_TITLE_PROP が正しいか確認してください。"
        ) from e

    if existing_page_id:
        print(f"  既存ページに追記中: ライフログ {date_str}")
        _append_blocks_in_batches(existing_page_id, blocks)
        page_url = f"https://notion.so/{existing_page_id.replace('-', '')}"
    else:
        print(f"  Notionにページを作成中: ライフログ {date_str}")
        try:
            page = notion.pages.create(
                parent={"data_source_id": _get_data_source_id()},
                properties={
                    NOTION_TITLE_PROP: {
                        "title": [{"text": {"content": f"ライフログ {date_str}"}}],
                    },
                },
                children=blocks[:100],  # ページ作成時は最大100ブロックまで
            )
        except APIResponseError as e:
            raise RuntimeError(
                f"Notion ページ作成失敗: {e}\n"
                f"ヒント: .env の NOTION_TITLE_PROP をエラーメッセージの列名に合わせてください。"
            ) from e
        page_id = page["id"]
        page_url = page["url"]
        if len(blocks) > 100:
            _append_blocks_in_batches(page_id, blocks[100:])

    return page_url


# =============================================================================
# archive への移動
# =============================================================================

def archive_wav(wav_path: Path, date_str: str) -> None:
    """処理済みWAVを archive/YYYY/MM/ に移動する"""
    year, month, *_ = date_str.split("-")
    dest_dir = ARCHIVE_DIR / year / month
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(wav_path), dest_dir / wav_path.name)
    print(f"  アーカイブ完了: archive/{year}/{month}/{wav_path.name}")


# =============================================================================
# メイン
# =============================================================================

def main() -> None:
    print("=" * 50)
    print("ライフログパイプライン（ローカルWhisper版）開始")
    print("=" * 50)

    wav_files = find_wav_files()
    if not wav_files:
        print(
            "incoming/ にWAVファイルが見つかりません。\n"
            "QZT 16GB を USB で接続し、WAVファイルを incoming/ にコピーしてください。"
        )
        return

    print(f"\n{len(wav_files)} 件のWAVファイルを検出:")
    for f in wav_files:
        size_mb = f.stat().st_size / 1024 / 1024
        print(f"   - {f.name} ({size_mb:.1f} MB)")

    print(f"\nWhisperモデル「{WHISPER_MODEL_SIZE}」をロード中...")
    model = whisper.load_model(WHISPER_MODEL_SIZE)
    print("モデルロード完了\n")

    for wav_path in wav_files:
        print(f"処理中: {wav_path.name}")
        date_str = extract_date(wav_path)
        print(f"  録音日: {date_str}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            chunk_dir = Path(tmp_dir) / "chunks"

            print(f"  分割中: {wav_path.name}")
            chunks = split_into_chunks(wav_path, chunk_dir)
            print(f"  {len(chunks)} チャンクに分割完了")

            transcription_results = transcribe_chunks(chunks, model)
        # tempfile.TemporaryDirectory を抜けるとチャンクは自動削除される

        page_url = save_to_notion(date_str, transcription_results)
        print(f"  Notion保存完了: {page_url}")

        archive_wav(wav_path, date_str)
        print()

    print("=" * 50)
    print("完了  費用: $0.00（完全無料）")
    print("=" * 50)


if __name__ == "__main__":
    main()
