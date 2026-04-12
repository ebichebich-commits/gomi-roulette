# gomi-roulette

ゴミ捨て・掃除当番を重み付きルーレットで決めるデスクトップアプリ（Python + Tkinter）。

## 必要なもの

- Python 3（標準ライブラリのみ。追加の `pip install` は不要）

## セットアップ（クローン後）

### A. データだけこの PC に置く（従来どおり）

1. このフォルダに **`members.csv`**（1列1名、UTF-8 推奨）。
   - ひな形: `members.csv.example` → `members.csv` にコピー。
2. 初回起動で **`duty_history.json`** が自動作成。

### B. 別の非公開リポジトリに名簿・履歴を置く（推奨・同期楽）

1. GitHub で **Private** リポジトリを作る（例: `gomi-roulette-data`）。
2. 中身に **`members.csv`** と **`duty_history.json`** をコミット（このリポジトリは閉じたメンバーだけが clone できる）。
3. 各 PC でそのリポジトリを **好きな場所に clone** する。
4. このアプリ側で `roulette_paths.example.json` を **`roulette_paths.json`** にコピーし、`data_repo_dir` を **その clone の絶対パス**に書き換える（この JSON は `.gitignore` 済みでコード用リポジトリに乗りません）。
5. 起動時に **自動で `git pull`**（`auto_git_pull_on_startup`: `false` でオフ）。手動は画面の **「データを更新（git pull）」**。
6. ルーレットで保存した履歴は **その clone 内の `duty_history.json` に書き込み** → あとで **`git add` / `commit` / `push`** すれば他メンバーの次回 `pull` に反映（**push は Git の操作で行う**）。

環境変数 **`GOMI_ROULETTE_DATA_DIR`** に clone パスを入れると、`roulette_paths.json` より優先されます。

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
