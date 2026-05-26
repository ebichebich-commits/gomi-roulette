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

## 今週の1枚（写真表示）

- アプリ右側に「今週の1枚！！」を表示します（ウィンドウサイズは変更なし）。
- 画像は `Pictures` フォルダ配下の**日付フォルダ**に入れてください。
  - 例: `Pictures/4-28/` または `Pictures/2026-04-28/`
- 対応拡張子: `.png` `.jpg` `.jpeg` `.gif`
- 同じ日付フォルダに複数枚入れた場合は、起動時にその中から1枚をランダム表示します。

## 今週のクイズ！！

写真が無い週は、日付フォルダに **`quiz.txt`** を置くと、アプリ右側に「今週のクイズ！！」を表示できます。

### 置き場所

```text
Pictures/
  5-26/
    quiz.txt
```

日付フォルダ名は写真と同じルールです。

- `Pictures/5-26/`
- `Pictures/2026-05-26/`
- `Pictures/0526/`
- `Pictures/20260526/`

### `quiz.txt` の書き方

```text
1行目: 問題文
2行目以降: 答え
```

例:

```text
5月26日、ゴミ当番が一番言ってはいけない一言は？
今日のゴミ、明日の俺に引き継ぎます。
```

### 答え表示の仕組み

- `quiz.txt` の **1行目** が問題として表示されます。
- `quiz.txt` の **2行目以降** が答えとして保存されます。
- ゴミ・掃除の両方の抽選が終わるまで、答えは表示されません。
- 両方の抽選が終わると「今週のクイズ　答えはこちら」という小さい画面が出ます。
- 「進」ボタンを押すと、答えが大きく表示されます。
- 答え画面の `OK` を押すと、今回の結果が `duty_history.json` に保存されてアプリが閉じます。
- 同じ日付フォルダに写真がある場合は写真表示が優先されます。ただし `quiz.txt` があれば、抽選後の答え表示には使われます。

### 来週以降の作業

1. `Pictures` の中に今週の日付フォルダを作る。
2. その中に `quiz.txt` を作る。
3. 1行目に問題、2行目以降に答えを書く。
4. 写真を見せたい週は、同じフォルダに画像も入れる。
5. `python roulette.py` で起動する。

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
