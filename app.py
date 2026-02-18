"""
PDF最低限編集Webアプリ
- ページ削除・回転・並び替えができるシンプルなツール
- PyMuPDF (fitz) で PDF を操作し、Flask で Web UI を提供する
"""

import json
import os
import uuid
import fitz  # PyMuPDF
from flask import Flask, request, redirect, url_for, send_file, render_template_string, after_this_request

app = Flask(__name__)

# アップロード上限: 20MB（低スペックサーバーでも安全に処理できるサイズ）
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

# アップロードされたPDFを一時保存するディレクトリ
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# HTMLテンプレート（インラインで定義し、ファイル数を最小に保つ）
# ---------------------------------------------------------------------------

# トップページ: PDFアップロード用フォーム
INDEX_HTML = """
<!DOCTYPE html>
<html lang="ja">
<head><meta charset="utf-8"><title>PDF最低限編集</title></head>
<body>
<h1>PDF最低限編集ツール</h1>
<form method="post" action="/upload" enctype="multipart/form-data">
  <input type="file" name="pdf" accept=".pdf" required>
  <button type="submit">アップロード</button>
</form>
</body>
</html>
"""

# 編集画面: ページ一覧と操作ボタンを表示
EDIT_HTML = """
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8"><title>PDF編集 - {{ filename }}</title>
<style>
  body { font-family: monospace; }
  table { border-collapse: collapse; margin: 1em 0; }
  th, td { border: 1px solid #999; padding: 6px 12px; text-align: center; }
  .actions form { display: inline; }
</style>
</head>
<body>
<h1>{{ filename }}（全{{ pages }}ページ）</h1>

<!-- ダウンロードボタン（クリック後にサーバー上のファイル削除を通知） -->
<button onclick="location.href='/download/{{ fid }}';
  setTimeout(function(){ alert('サーバー上の一時ファイルを削除しました。'); }, 500);">
  編集済みPDFをダウンロード
</button>
<hr>

<table>
<tr>
  <th>#</th><th>元ページ番号</th><th>回転</th><th>操作</th>
</tr>
{% for p in page_info %}
<tr>
  <td>{{ loop.index }}</td>
  <td>{{ p.label }}</td>
  <td>{{ p.rotation }}°</td>
  <td class="actions">
    <!-- 回転（時計回り90°） -->
    <form method="post" action="/rotate/{{ fid }}/{{ loop.index0 }}">
      <button title="時計回りに90°回転">↻ 回転</button>
    </form>
    <!-- 削除 -->
    <form method="post" action="/delete/{{ fid }}/{{ loop.index0 }}">
      <button title="このページを削除">✕ 削除</button>
    </form>
    <!-- 上へ移動（先頭ページ以外で表示） -->
    {% if loop.index0 > 0 %}
    <form method="post" action="/move/{{ fid }}/{{ loop.index0 }}">
      <input type="hidden" name="to" value="{{ loop.index0 - 1 }}">
      <button title="1つ上へ移動">▲ 上へ</button>
    </form>
    {% endif %}
    <!-- 下へ移動（末尾ページ以外で表示） -->
    {% if loop.index0 < pages - 1 %}
    <form method="post" action="/move/{{ fid }}/{{ loop.index0 }}">
      <input type="hidden" name="to" value="{{ loop.index0 + 1 }}">
      <button title="1つ下へ移動">▼ 下へ</button>
    </form>
    {% endif %}
  </td>
</tr>
{% endfor %}
</table>

<a href="/">← 別のPDFを編集する</a>
</body>
</html>
"""


def _pdf_path(fid: str) -> str:
    """ファイルIDからPDFの保存パスを返す"""
    return os.path.join(UPLOAD_DIR, f"{fid}.pdf")


def _meta_path(fid: str) -> str:
    """ファイルIDから元ページ番号を記録するJSONのパスを返す"""
    return os.path.join(UPLOAD_DIR, f"{fid}.json")


def _load_meta(fid: str, n: int) -> dict:
    """メタ情報（元ファイル名・元ページ番号リスト）を読み込む"""
    path = _meta_path(fid)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"filename": "unknown.pdf", "pages": list(range(1, n + 1))}


def _save_meta(fid: str, meta: dict) -> None:
    """メタ情報をJSONに保存する"""
    with open(_meta_path(fid), "w") as f:
        json.dump(meta, f)


def _get_page_info(doc: fitz.Document, original_pages: list[int]) -> list[dict]:
    """各ページの表示情報（元のページ番号と回転角度）を返す"""
    info = []
    for i in range(len(doc)):
        page = doc[i]
        info.append({
            "label": f"p.{original_pages[i]}",
            "rotation": page.rotation,
        })
    return info


# ---------------------------------------------------------------------------
# ルーティング
# ---------------------------------------------------------------------------

@app.errorhandler(413)
def too_large(e):
    """アップロードサイズ上限超過時のエラーハンドラ"""
    return "ファイルサイズが大きすぎます（上限: 20MB）", 413


@app.route("/")
def index():
    """トップページを表示"""
    return render_template_string(INDEX_HTML)


@app.route("/upload", methods=["POST"])
def upload():
    """PDFファイルを受け取り、一時保存して編集画面へリダイレクト"""
    f = request.files.get("pdf")
    if not f or not f.filename.lower().endswith(".pdf"):
        return "PDFファイルを選択してください", 400

    # ランダムなIDでファイルを保存（ファイル名の衝突を防ぐ）
    fid = uuid.uuid4().hex[:12]
    path = _pdf_path(fid)
    f.save(path)

    # 元ファイル名と元ページ番号の初期リストを保存
    original_name = f.filename.rsplit(".", 1)[0]  # 拡張子を除いた元ファイル名
    doc = fitz.open(path)
    _save_meta(fid, {"filename": original_name, "pages": list(range(1, len(doc) + 1))})
    doc.close()

    return redirect(url_for("edit", fid=fid))


@app.route("/edit/<fid>")
def edit(fid: str):
    """編集画面を表示: ページ一覧と各種操作ボタン"""
    path = _pdf_path(fid)
    if not os.path.exists(path):
        return "ファイルが見つかりません", 404

    doc = fitz.open(path)
    meta = _load_meta(fid, len(doc))
    page_info = _get_page_info(doc, meta["pages"])
    filename = meta["filename"] + ".pdf"
    doc.close()

    return render_template_string(
        EDIT_HTML,
        fid=fid,
        filename=filename,
        pages=len(page_info),
        page_info=page_info,
    )


@app.route("/rotate/<fid>/<int:page_idx>", methods=["POST"])
def rotate(fid: str, page_idx: int):
    """指定ページを時計回りに90°回転して保存"""
    path = _pdf_path(fid)
    doc = fitz.open(path)

    if 0 <= page_idx < len(doc):
        page = doc[page_idx]
        # 現在の回転角に90°加算（360°で0に戻る）
        page.set_rotation((page.rotation + 90) % 360)
        doc.save(path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)

    doc.close()
    return redirect(url_for("edit", fid=fid))


@app.route("/delete/<fid>/<int:page_idx>", methods=["POST"])
def delete(fid: str, page_idx: int):
    """指定ページを削除して保存"""
    path = _pdf_path(fid)
    doc = fitz.open(path)

    n = len(doc)
    if 0 <= page_idx < n and n > 1:
        doc.delete_page(page_idx)
        # 同じファイルへの非インクリメンタル保存は不可なので、一時ファイル経由で保存
        tmp = path + ".tmp"
        doc.save(tmp, deflate=True)
        doc.close()
        os.replace(tmp, path)
        # 元ページ番号リストからも該当ページを削除
        meta = _load_meta(fid, n)
        meta["pages"].pop(page_idx)
        _save_meta(fid, meta)
    else:
        doc.close()
    return redirect(url_for("edit", fid=fid))


@app.route("/move/<fid>/<int:from_idx>", methods=["POST"])
def move(fid: str, from_idx: int):
    """ページを指定位置へ移動（並び替え）して保存"""
    path = _pdf_path(fid)
    to_idx = int(request.form.get("to", from_idx))

    doc = fitz.open(path)
    n = len(doc)

    if 0 <= from_idx < n and 0 <= to_idx < n and from_idx != to_idx:
        # ページ順のリストを作り、要素を抜いて挿入先に差し込む
        order = list(range(n))
        order.insert(to_idx, order.pop(from_idx))
        doc.select(order)
        # 同じファイルへの非インクリメンタル保存は不可なので、一時ファイル経由で保存
        tmp = path + ".tmp"
        doc.save(tmp, deflate=True)
        doc.close()
        os.replace(tmp, path)
        # 元ページ番号リストも同じ順序で並び替え
        meta = _load_meta(fid, n)
        meta["pages"].insert(to_idx, meta["pages"].pop(from_idx))
        _save_meta(fid, meta)
    else:
        doc.close()
    return redirect(url_for("edit", fid=fid))


@app.route("/download/<fid>")
def download(fid: str):
    """編集済みPDFをダウンロードし、サーバー上の一時ファイルを削除する"""
    path = _pdf_path(fid)
    meta_path = _meta_path(fid)
    if not os.path.exists(path):
        return "ファイルが見つかりません", 404

    # 元ファイル名を取得してダウンロード名に使う
    meta = _load_meta(fid, 0)
    download_name = f"{meta['filename']}_edited.pdf"

    # レスポンス送信完了後にファイルを削除する
    @after_this_request
    def _cleanup(response):
        try:
            os.remove(path)
            if os.path.exists(meta_path):
                os.remove(meta_path)
        except OSError:
            pass
        return response
    return send_file(path, as_attachment=True, download_name=download_name)


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # デバッグモードで起動（本番運用時はWSGIサーバーを使うこと）
    app.run(debug=True, port=5001)
