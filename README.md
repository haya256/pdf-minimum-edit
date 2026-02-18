# PDF最低限編集ツール

PDFファイルをページ単位で最低限の編集ができるWebアプリ。

## 機能

- ページの削除
- ページの回転（90°ずつ）
- ページの並び替え（上へ / 下へ）

サムネイルなし、ページ番号のテキスト表示のみの質実剛健なUI。

## 技術スタック

- Python / Flask
- PyMuPDF (fitz)

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

http://localhost:5001 にアクセス。

## ライセンス

MIT
