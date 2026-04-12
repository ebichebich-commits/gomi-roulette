# gomi-roulette

ゴミ捨て・掃除当番を重み付きルーレットで決めるデスクトップアプリ（Python + Tkinter）。

## 必要なもの

- Python 3（標準ライブラリのみ。追加の `pip install` は不要）

## セットアップ（クローン後）

1. このフォルダに **`members.csv`** を自分で置く（1列1名、UTF-8 推奨）。
   - ひな形: `members.csv.example` をコピーして `members.csv` にリネームし、名前を書き換える。
2. 初回起動で `duty_history.json` が**自動作成**される（履歴・重み）。これも Git には含めない。

```powershell
python roulette.py
```

## 個人情報について

- **`members.csv`** と **`duty_history.json`** は `.gitignore` で除外済みです。
- リポジトリには**プログラムだけ**が入ります。名簿・履歴は各 PC のローカルにだけ置いてください。

## ブラウザから「どこでも」について

このリポジトリのアプリは **Tkinter のデスクトップアプリ**です。GitHub のページを開いただけではブラウザ上では動きません。

ブラウザで回したい場合は、別途 Web アプリ化（サーバー + フロント）が必要です。**名簿を公開サーバーに送らない**設計（ログイン・自分の端末だけで動かす等）を別プロジェクトで検討してください。

## GitHub に上げる例

```powershell
cd path\to\gomi-roulette
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<ユーザー名>/gomi-roulette.git
git push -u origin main
```
