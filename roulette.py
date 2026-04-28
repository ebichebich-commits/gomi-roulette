import tkinter as tk
from tkinter import messagebox
import math
import random
import json
import os
import csv
import subprocess
from datetime import datetime
try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

# ==========================================
# 設定エリア
# ==========================================
# 名簿・履歴ファイル名（実体は data_dir 内）
CSV_FILE = "members.csv"
DATA_FILE = "duty_history.json"

# 別リポジトリのクローン先を指定する JSON（このファイルは Git に含めない）
PATHS_CONFIG_NAME = "roulette_paths.json"

# 環境変数 GOMI_ROULETTE_DATA_DIR があれば最優先（クローン先の絶対パス）

# CSVがない場合のデフォルトメンバー（テスト用）
DEFAULT_MEMBERS = ["メンバーA", "メンバーB", "メンバーC", "メンバーD"]

PENALTY_RATE = 10
# ==========================================

ROLE_GOMI = "gomi"
ROLE_SOUJI = "souji"

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_WORKSPACE_DIR = os.path.dirname(_SCRIPT_DIR)

PHOTO_DIR_CANDIDATES = (
    os.path.join(_WORKSPACE_DIR, "Pictures"),
    os.path.join(_SCRIPT_DIR, "Pictures"),
)
SUPPORTED_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif")


def compute_candidate_pools(all_members, done_gomi, done_souji):
    """
    どちらか片方でも完了した人は、両方のルーレットから除外する。
    - ゴミだけ完了  -> ゴミ/掃除どちらにも出ない
    - 掃除だけ完了  -> ゴミ/掃除どちらにも出ない
    - 両方完了      -> ゴミ/掃除どちらにも出ない
    - 両方未完了    -> ゴミ/掃除どちらにも出る
    """
    dg, ds = set(done_gomi), set(done_souji)
    neither = [m for m in all_members if m not in dg and m not in ds]
    # ゴミ・掃除ともに「両方未完了」の人だけを候補にする
    return list(neither), list(neither)


def _read_paths_config():
    p = os.path.join(_SCRIPT_DIR, PATHS_CONFIG_NAME)
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def resolve_data_directory():
    """members.csv / duty_history.json を置くディレクトリ（非公開リポジトリのクローン推奨）"""
    raw = os.environ.get("GOMI_ROULETTE_DATA_DIR", "").strip()
    if not raw:
        cfg = _read_paths_config()
        raw = (cfg.get("data_repo_dir") or "").strip()
    if not raw:
        return _SCRIPT_DIR
    expanded = os.path.abspath(os.path.expanduser(raw))
    if os.path.isdir(expanded):
        return expanded
    return _SCRIPT_DIR


def should_auto_git_pull():
    cfg = _read_paths_config()
    if "auto_git_pull_on_startup" in cfg:
        return bool(cfg["auto_git_pull_on_startup"])
    return True


def _parse_date_folder_to_ymd(name):
    """日付フォルダ名を (year, month, day) に変換。解析できない場合は None。"""
    s = (name or "").strip()
    if not s:
        return None
    normalized = s.replace("_", "-").replace("/", "-")
    parts = [p for p in normalized.split("-") if p]
    now = datetime.now()

    # YYYY-MM-DD
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    # M-D
    elif len(parts) == 2 and all(p.isdigit() for p in parts):
        y, m, d = now.year, int(parts[0]), int(parts[1])
    # YYYYMMDD
    elif s.isdigit() and len(s) == 8:
        y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
    # MMDD
    elif s.isdigit() and len(s) == 4:
        y, m, d = now.year, int(s[:2]), int(s[2:4])
    else:
        return None

    try:
        datetime(y, m, d)
        return (y, m, d)
    except ValueError:
        return None


def resolve_pictures_root():
    for p in PHOTO_DIR_CANDIDATES:
        if os.path.isdir(p):
            return p
    return PHOTO_DIR_CANDIDATES[0]


def sync_private_data_repo(data_dir):
    """
    data_dir が git クローンなら git pull --ff-only。
    戻り値: None=スキップ, (0,None)=成功, (code, err)=失敗メッセージ用
    """
    if not os.path.isdir(os.path.join(data_dir, ".git")):
        return None
    try:
        r = subprocess.run(
            ["git", "-C", data_dir, "pull", "--ff-only"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode == 0:
            return (0, None)
        err = (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
        return (r.returncode, err)
    except FileNotFoundError:
        return (-1, "git コマンドが見つかりません（Git for Windows を入れてください）")
    except subprocess.TimeoutExpired:
        return (-1, "git pull がタイムアウトしました")
    except OSError as e:
        return (-1, str(e))


class DutyRouletteApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ゴミ捨て・掃除当番ルーレット")
        self.root.state("zoomed")
        self.root.resizable(True, True)

        cfg_raw = (os.environ.get("GOMI_ROULETTE_DATA_DIR", "").strip()
                   or (_read_paths_config().get("data_repo_dir") or "").strip())
        self.data_dir = resolve_data_directory()
        self.csv_path = os.path.join(self.data_dir, CSV_FILE)
        self.data_path = os.path.join(self.data_dir, DATA_FILE)
        self.pictures_root = resolve_pictures_root()
        self.weekly_photo_tk = None

        if cfg_raw and self.data_dir == _SCRIPT_DIR:
            messagebox.showwarning(
                "データフォルダ",
                f"設定のデータフォルダが見つかりませんでした:\n{cfg_raw}\n\n"
                f"スクリプトと同じ場所を使います:\n{_SCRIPT_DIR}",
            )
        elif should_auto_git_pull():
            pull_result = sync_private_data_repo(self.data_dir)
            if pull_result and pull_result[0] not in (0, None):
                messagebox.showwarning(
                    "git pull",
                    f"データの取得に失敗しました（オフラインの可能性があります）。\n"
                    f"手元のファイルで続行します。\n\n{pull_result[1]}",
                )

        # 1. 名簿CSVの読み込み
        self.all_members = self.load_members_from_csv()

        # 2. 履歴データの読み込み（旧形式は移行）
        self.history_data = self.load_history()
        self.migrate_legacy_if_needed()
        self.discard_incomplete_pair_on_disk()
        # get(key, []) は key があり値が null のとき None になるため or [] で正規化。別リストを保証。
        self.done_gomi = list(self.history_data.get("done_gomi") or [])
        self.done_souji = list(self.history_data.get("done_souji") or [])
        self.history_data["done_gomi"] = self.done_gomi
        self.history_data["done_souji"] = self.done_souji
        self.last_gomi_winner = self.history_data.get("last_gomi_winner", None)
        self.last_souji_winner = self.history_data.get("last_souji_winner", None)
        self.weights_gomi = self.history_data.setdefault("weights_gomi", {})
        self.weights_souji = self.history_data.setdefault("weights_souji", {})

        # 3. 起動時：前回のゴミ・掃除それぞれ実施確認
        self.check_previous_duty_status(ROLE_GOMI)
        self.check_previous_duty_status(ROLE_SOUJI)

        # 4. 全員が両方終わったらリセット
        self.check_cycle_reset()

        # 5. 役割ごとの候補（片方完了者はもう片方のルーレットからも消す）
        self.candidates_gomi, self.candidates_souji = compute_candidate_pools(
            self.all_members, self.done_gomi, self.done_souji
        )
        # 除外リスト用（どちらかの役まだ残っている人）
        self.candidates = sorted(
            set(self.candidates_gomi) | set(self.candidates_souji),
            key=lambda x: self.all_members.index(x) if x in self.all_members else 0,
        )
        self.weekly_excluded = set()
        self.exclusions_confirmed = False

        # 今セッション：1回目ゴミ → 2回目掃除
        self.session_gomi_winner = None  # 1回目終了後に設定（保存は掃除確定後までしない）
        self.draw_role = ROLE_GOMI  # ROLE_GOMI | ROLE_SOUJI

# 1. 左側のエリア（ルーレット）を作る
        self.left_frame = tk.Frame(root, bg="white")
        self.left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.right_frame = tk.Frame(root, bg="#f0f0f0", width=420)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.Y)

        # 左側余白を「今週の1枚」表示に使う
        self.photo_panel = tk.Frame(self.left_frame, bg="#efefef", width=260)
        self.photo_panel.pack(side=tk.LEFT, fill=tk.Y)
        self.photo_panel.pack_propagate(False)

        tk.Label(self.photo_panel, text="今週の1枚！！", font=("Meiryo", 14, "bold"), bg="#efefef").pack(pady=(16, 8))
        self.weekly_photo_canvas = tk.Canvas(
            self.photo_panel,
            bg="#e8e8e8",
            width=230,
            height=360,
            highlightthickness=0,
        )
        self.weekly_photo_canvas.pack(padx=10, pady=(0, 6))
        self.weekly_photo_path_label = tk.Label(
            self.photo_panel,
            text="",
            font=("Meiryo", 9),
            bg="#efefef",
            fg="#666666",
            wraplength=230,
            justify=tk.CENTER,
        )
        self.weekly_photo_path_label.pack(padx=8, pady=(0, 10))

        self.center_frame = tk.Frame(self.left_frame, bg="white")
        self.center_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.center_frame, bg="white", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, pady=(10, 8), padx=(0, 4))

        status_text = (
            f"データフォルダ: {self.data_dir}  |  "
            f"総メンバー: {len(self.all_members)}人 / "
            f"ゴミ残り: {len(self.candidates_gomi)} / 掃除残り: {len(self.candidates_souji)}"
        )
        self.status_label = tk.Label(self.center_frame, text=status_text, font=("Meiryo", 10), bg="white")
        self.status_label.pack()

        self.info_label = tk.Label(self.center_frame, text="", font=("Meiryo", 12), justify=tk.CENTER, bg="white")
        self.info_label.pack()

        self.winner_label = tk.Label(
            self.center_frame,
            text="",
            font=("Meiryo", 32, "bold"),
            fg="#c0392b",
            bg="white",
            wraplength=850,
            justify=tk.CENTER,
        )
        self.winner_label.pack(pady=24)

        tk.Label(self.right_frame, text="【 今週ルーレットから除外 】", font=("Meiryo", 12, "bold"), bg="#f0f0f0").pack(pady=(20, 5))
        tk.Label(
            self.right_frame,
            text="Ctrl/Shiftで複数選択\n（ゴミ・掃除の両方から外れます）",
            font=("Meiryo", 9),
            bg="#f0f0f0",
            justify=tk.CENTER,
        ).pack()
        ex_frame = tk.Frame(self.right_frame, bg="#f0f0f0")
        ex_frame.pack(padx=10, pady=8, fill=tk.X)
        self.exclude_listbox = tk.Listbox(
            ex_frame,
            font=("Meiryo", 12),
            height=8,
            width=28,
            selectmode=tk.EXTENDED,
            activestyle="dotbox",
        )
        ex_scroll = tk.Scrollbar(ex_frame, orient=tk.VERTICAL, command=self.exclude_listbox.yview)
        self.exclude_listbox.config(yscrollcommand=ex_scroll.set)
        self.exclude_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ex_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        for m in self.candidates:
            self.exclude_listbox.insert(tk.END, m)
        self.exclude_listbox.bind("<<ListboxSelect>>", self.on_weekly_exclusion_change)
        self.btn_confirm_exclusions = tk.Button(
            self.right_frame,
            text="除外を確定する（この内容で抽選）",
            font=("Meiryo", 11, "bold"),
            command=self.confirm_weekly_exclusions,
        )
        self.btn_confirm_exclusions.pack(pady=(4, 2), padx=10, fill=tk.X)
        self.btn_cancel_exclusion_confirm = tk.Button(
            self.right_frame,
            text="確定を取り消す（選び直し）",
            font=("Meiryo", 10),
            command=self.cancel_exclusion_confirm,
            state=tk.DISABLED,
        )
        self.btn_cancel_exclusion_confirm.pack(pady=(0, 4), padx=10, fill=tk.X)
        tk.Button(
            self.right_frame,
            text="除外をすべて解除",
            font=("Meiryo", 11),
            command=self.clear_weekly_exclusions,
        ).pack(pady=(0, 10))

        tk.Button(
            self.right_frame,
            text="データを更新（git pull）",
            font=("Meiryo", 10),
            command=self.on_pull_data_repo,
        ).pack(pady=(0, 8))

        tk.Label(self.right_frame, text="【 危険度ランキング 】", font=("Meiryo", 18, "bold"), bg="#f0f0f0").pack(pady=20)

        self.ranking_box = tk.Text(self.right_frame, font=("Meiryo", 14), width=30, height=22, bg="#f0f0f0", bd=0)
        self.ranking_box.pack(padx=20, pady=10)

        self.update_ranking_display()
        self.load_weekly_photo()
        self.refresh_info_spin_hint()

        self.angle = 0
        self.speed = 0
        self.is_spinning = False
        self.stopping = False

        self.draw_wheel()
        self.root.bind('<space>', self.toggle_spin)
        self.animate()

        self.root.bind('<Escape>', lambda e: self.root.destroy())

    def role_weights(self, role):
        return self.weights_gomi if role == ROLE_GOMI else self.weights_souji

    def role_candidates(self, role):
        return self.candidates_gomi if role == ROLE_GOMI else self.candidates_souji

    def migrate_legacy_if_needed(self):
        d = self.history_data
        # 旧形式は「当番1種類」のみ。done_members を掃除完了までコピーすると掃除未実施者が消えるため、掃除は空で始める。
        if "done_gomi" not in d and "done_members" in d:
            d["done_gomi"] = list(d["done_members"])
            d["done_souji"] = []
        if "done_gomi" not in d:
            d["done_gomi"] = []
        if "done_souji" not in d:
            d["done_souji"] = []
        if "last_gomi_winner" not in d and "last_winner" in d:
            lw = d.get("last_winner")
            d["last_gomi_winner"] = lw
            d["last_souji_winner"] = lw
        if "last_gomi_winner" not in d:
            d["last_gomi_winner"] = None
        if "last_souji_winner" not in d:
            d["last_souji_winner"] = None
        ow = d.get("weights") or {}
        if "weights_gomi" not in d:
            d["weights_gomi"] = dict(ow)
        if "weights_souji" not in d:
            d["weights_souji"] = dict(ow)
        d.setdefault("pair_pending_souji", False)
        d.setdefault("pair_session_excluded", [])

    def discard_incomplete_pair_on_disk(self):
        """掃除抽選まで終わらず終了していたデータは無効化してファイルに書き戻す"""
        d = self.history_data
        if not d.get("pair_pending_souji"):
            return
        d["pair_pending_souji"] = False
        d["pair_session_excluded"] = []
        d["last_gomi_winner"] = None
        try:
            with open(self.data_path, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=4)
        except OSError:
            pass

    def active_pool(self):
        """今回の役割のルーレット参加候補（除外・掃除時はゴミ当選者も除外）"""
        base = self.role_candidates(self.draw_role)
        pool = [m for m in base if m not in self.weekly_excluded]
        if self.draw_role == ROLE_SOUJI and self.session_gomi_winner:
            pool = [m for m in pool if m != self.session_gomi_winner]
        return pool

    def wheel_order(self):
        active = self.active_pool()
        wmap = self.role_weights(self.draw_role)
        return sorted(active, key=lambda m: wmap.get(m, 1.0), reverse=True)

    def refresh_info_spin_hint(self):
        if self.exclusions_confirmed:
            if self.draw_role == ROLE_GOMI:
                line = "【1回目・ゴミ捨て当番】[Space] でスタート / ストップ"
            else:
                line = "【2回目・掃除当番】[Space] でスタート / ストップ"
            self.info_label.config(text=line, font=("Meiryo", 14))
        else:
            self.info_label.config(
                text="まず「除外を確定する」を押してから [Space] で抽選できます。\n"
                "未確定のとき [Space] を押すと、除外の選択が解除されます。\n"
                "（1回目：ゴミ捨て → 2回目：掃除）\n"
                "※途中で閉じた場合は抽選は無効。次回は最初からやり直しです。",
                font=("Meiryo", 12),
            )

    def set_exclusion_editor_locked(self, locked):
        self.exclude_listbox.config(state=tk.DISABLED if locked else tk.NORMAL)

    def _can_run_both_draws(self):
        """確定時点で、ゴミ1回＋掃除1回（掃除はゴミ当選者以外）が理論上可能か"""
        ga = [m for m in self.candidates_gomi if m not in self.weekly_excluded]
        sa = [m for m in self.candidates_souji if m not in self.weekly_excluded]
        if not ga or not sa:
            return False, "ゴミまたは掃除の候補がいません。除外を減らしてください。"
        for g in ga:
            souji_after = [m for m in sa if m != g]
            if not souji_after:
                return (
                    False,
                    "どの組み合わせでも掃除当番が決められません。\n"
                    "（掃除候補がゴミ当選者しかいない状態になり得ます）\n除外または名簿を見直してください。",
                )
        return True, ""

    def confirm_weekly_exclusions(self):
        ok, err = self._can_run_both_draws()
        if not ok:
            messagebox.showwarning("確定できません", err)
            return
        self.exclusions_confirmed = True
        self.draw_role = ROLE_GOMI
        self.session_gomi_winner = None
        self.set_exclusion_editor_locked(True)
        self.btn_confirm_exclusions.config(state=tk.DISABLED)
        self.btn_cancel_exclusion_confirm.config(state=tk.NORMAL)
        self.refresh_info_spin_hint()
        self.update_ranking_display()

    def cancel_exclusion_confirm(self):
        self.exclusions_confirmed = False
        self.draw_role = ROLE_GOMI
        self.session_gomi_winner = None
        self.set_exclusion_editor_locked(False)
        self.btn_confirm_exclusions.config(state=tk.NORMAL)
        self.btn_cancel_exclusion_confirm.config(state=tk.DISABLED)
        self.refresh_info_spin_hint()
        self.update_ranking_display()

    def on_weekly_exclusion_change(self, event=None):
        sel = self.exclude_listbox.curselection()
        self.weekly_excluded = {self.candidates[i] for i in sel if i < len(self.candidates)}
        self.update_ranking_display()

    def clear_weekly_exclusions(self):
        self.weekly_excluded.clear()
        self.exclude_listbox.selection_clear(0, tk.END)
        self.exclusions_confirmed = False
        self.draw_role = ROLE_GOMI
        self.session_gomi_winner = None
        self.set_exclusion_editor_locked(False)
        self.btn_confirm_exclusions.config(state=tk.NORMAL)
        self.btn_cancel_exclusion_confirm.config(state=tk.DISABLED)
        self.refresh_info_spin_hint()
        self.update_ranking_display()

    def _ranking_block_for_role(self, role, exclude_names):
        """テキスト用：役割ごとの候補と確率（exclude_names は集合・この中の名前は除く）"""
        lines = []
        base = [m for m in self.role_candidates(role) if m not in self.weekly_excluded]
        active = [m for m in base if m not in exclude_names]
        wmap = self.role_weights(role)
        sorted_members = sorted(active, key=lambda m: wmap.get(m, 1.0), reverse=True)
        total_weight = sum(wmap.get(m, 1.0) for m in active)
        for i, member in enumerate(sorted_members):
            w = wmap.get(member, 1.0)
            prob = (w / total_weight) * 100 if total_weight > 0 else 0
            rank_icon = "👑" if i == 0 else f"{i+1}."
            lines.append(f"{rank_icon} {member}\n")
            lines.append(f"    倍率: {w:.2f}倍 (確率: {prob:.1f}%)\n\n")
        return "".join(lines)

    def update_ranking_display(self):
        self.ranking_box.delete(1.0, tk.END)

        if not self.exclusions_confirmed:
            self.ranking_box.insert(tk.END, "〔確定前：両方の候補を表示〕\n")
            self.ranking_box.insert(tk.END, "1回目Space＝ゴミ／2回目＝掃除です。\n\n")
            self.ranking_box.insert(tk.END, "── ゴミ捨て当番の候補 ──\n\n")
            self.ranking_box.insert(tk.END, self._ranking_block_for_role(ROLE_GOMI, set()))
            self.ranking_box.insert(tk.END, "── 掃除当番の候補 ──\n\n")
            ex_gomi = {self.session_gomi_winner} if self.session_gomi_winner else set()
            self.ranking_box.insert(tk.END, self._ranking_block_for_role(ROLE_SOUJI, ex_gomi))
            return

        role = self.draw_role
        label = "ゴミ捨て当番" if role == ROLE_GOMI else "掃除当番"
        self.ranking_box.insert(tk.END, f"〔{label}・今の抽選の確率〕\n\n")

        active = self.active_pool()
        wmap = self.role_weights(role)
        sorted_members = sorted(active, key=lambda m: wmap.get(m, 1.0), reverse=True)
        total_weight = sum(wmap.get(m, 1.0) for m in active)

        for i, member in enumerate(sorted_members):
            w = wmap.get(member, 1.0)
            prob = (w / total_weight) * 100 if total_weight > 0 else 0
            rank_icon = "👑" if i == 0 else f"{i+1}."
            self.ranking_box.insert(tk.END, f"{rank_icon} {member}\n")
            self.ranking_box.insert(tk.END, f"    倍率: {w:.2f}倍 (確率: {prob:.1f}%)\n\n")

    def on_pull_data_repo(self):
        r = sync_private_data_repo(self.data_dir)
        if r is None:
            messagebox.showinfo("データ更新", "このフォルダは git リポジトリではありません。\nroulette_paths.json の data_repo_dir を確認してください。")
            return
        if r[0] == 0:
            messagebox.showinfo("データ更新", "git pull が完了しました。\nアプリを一度終了して起動し直すと反映されます。")
        else:
            messagebox.showwarning("データ更新", f"git pull に失敗しました。\n\n{r[1]}")

    def _list_weekly_photo_candidates(self):
        """Pictures 配下の日付フォルダの画像候補を返す。"""
        root = self.pictures_root
        if not os.path.isdir(root):
            return None, []

        dated_dirs = []
        for entry in os.listdir(root):
            full = os.path.join(root, entry)
            if not os.path.isdir(full):
                continue
            ymd = _parse_date_folder_to_ymd(entry)
            if ymd is not None:
                dated_dirs.append((ymd, full))

        if not dated_dirs:
            return None, []

        now = datetime.now()
        today_ymd = (now.year, now.month, now.day)
        target_dir = None
        for ymd, full in dated_dirs:
            if ymd == today_ymd:
                target_dir = full
                break
        if target_dir is None:
            target_dir = sorted(dated_dirs, key=lambda x: x[0], reverse=True)[0][1]

        files = []
        for name in sorted(os.listdir(target_dir)):
            p = os.path.join(target_dir, name)
            ext = os.path.splitext(name)[1].lower()
            if os.path.isfile(p) and ext in SUPPORTED_IMAGE_EXTS:
                files.append(p)
        return target_dir, files

    def load_weekly_photo(self):
        target_dir, files = self._list_weekly_photo_candidates()
        canvas_w = max(self.weekly_photo_canvas.winfo_width(), 230)
        canvas_h = max(self.weekly_photo_canvas.winfo_height(), 360)
        if not target_dir:
            self.weekly_photo_canvas.delete("all")
            self.weekly_photo_canvas.create_text(
                canvas_w // 2, canvas_h // 2,
                text=f"画像フォルダがありません\n{self.pictures_root}",
                font=("Meiryo", 11),
                justify=tk.CENTER,
            )
            self.weekly_photo_path_label.config(text="")
            self.weekly_photo_tk = None
            return
        if not files:
            self.weekly_photo_canvas.delete("all")
            self.weekly_photo_canvas.create_text(
                canvas_w // 2, canvas_h // 2,
                text=f"画像がありません\n{target_dir}",
                font=("Meiryo", 11),
                justify=tk.CENTER,
            )
            self.weekly_photo_path_label.config(text="")
            self.weekly_photo_tk = None
            return

        # 複数枚ある場合はランダムで1枚を表示（毎回起動時に変わる）
        chosen = random.choice(files)
        try:
            max_w = max(canvas_w - 8, 100)
            max_h = max(canvas_h - 8, 120)
            if Image is not None and ImageTk is not None:
                pil_img = Image.open(chosen)
                pil_img.thumbnail((max_w, max_h))
                self.weekly_photo_tk = ImageTk.PhotoImage(pil_img)
            else:
                img = tk.PhotoImage(file=chosen)
                source_w = max(img.width(), 1)
                source_h = max(img.height(), 1)
                ratio = min(max_w / source_w, max_h / source_h, 1.0)
                scaled = img
                if ratio < 1.0:
                    step = max(int(1 / ratio), 1)
                    scaled = img.subsample(step, step)
                self.weekly_photo_tk = scaled
            self.weekly_photo_canvas.delete("all")
            self.weekly_photo_canvas.create_image(canvas_w // 2, canvas_h // 2, image=self.weekly_photo_tk)
            self.weekly_photo_path_label.config(text=os.path.basename(chosen))
        except Exception:
            self.weekly_photo_tk = None
            self.weekly_photo_canvas.delete("all")
            self.weekly_photo_canvas.create_text(
                canvas_w // 2, canvas_h // 2,
                text="画像の読み込みに失敗しました。\nJPG/JPEG を使う場合は\n`pip install pillow` を実行してください",
                font=("Meiryo", 11),
                justify=tk.CENTER,
            )
            self.weekly_photo_path_label.config(text=os.path.basename(chosen))

    def load_members_from_csv(self):
        members = []
        if not os.path.exists(self.csv_path):
            self.create_default_csv()
            return DEFAULT_MEMBERS

        try:
            with open(self.csv_path, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    if row and row[0].strip():
                        members.append(row[0].strip())
            return members
        except UnicodeDecodeError:
            try:
                with open(self.csv_path, newline='', encoding='cp932') as f:
                    reader = csv.reader(f)
                    members = [row[0].strip() for row in reader if row and row[0].strip()]
                return members
            except:
                return DEFAULT_MEMBERS
        except Exception as e:
            messagebox.showerror("エラー", f"CSV読み込みエラー:\n{e}")
            return DEFAULT_MEMBERS

    def create_default_csv(self):
        try:
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                for m in DEFAULT_MEMBERS:
                    writer.writerow([m])
        except:
            pass

    def load_history(self):
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data
            except:
                return {}
        return {}

    def save_data(self):
        self.history_data["last_gomi_winner"] = self.last_gomi_winner
        self.history_data["last_souji_winner"] = self.last_souji_winner
        self.history_data["done_gomi"] = self.done_gomi
        self.history_data["done_souji"] = self.done_souji
        self.history_data["weights_gomi"] = self.weights_gomi
        self.history_data["weights_souji"] = self.weights_souji
        self.history_data["pair_pending_souji"] = False
        self.history_data["pair_session_excluded"] = []
        with open(self.data_path, 'w', encoding='utf-8') as f:
            json.dump(self.history_data, f, ensure_ascii=False, indent=4)

    def show_large_winner_dialog(self, role, winner, win_rate_pct):
        dlg = tk.Toplevel(self.root)
        dlg.title("当選")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        title_f = ("Meiryo", 22)
        name_f = ("Meiryo", 28, "bold")
        sub_f = ("Meiryo", 18)
        btn_f = ("Meiryo", 17)

        if role == ROLE_GOMI:
            head = "今週のゴミ捨て当番は"
        else:
            head = "今週の掃除当番は"

        tk.Label(dlg, text=head, font=title_f).pack(padx=36, pady=(32, 10))
        tk.Label(dlg, text=f"【 {winner} 】", font=name_f, fg="#c0392b").pack(padx=36, pady=6)
        tk.Label(dlg, text="さんです！", font=title_f).pack(padx=36, pady=(6, 18))
        tk.Label(
            dlg,
            text=f"この抽選での当選確率：{win_rate_pct:.1f}%",
            font=sub_f,
        ).pack(padx=36, pady=(0, 22))
        tk.Button(dlg, text="OK", font=btn_f, width=14, command=dlg.destroy).pack(pady=(0, 30))

        self.root.update_idletasks()
        dlg.update_idletasks()
        w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

        self.root.wait_window(dlg)

    def check_previous_duty_status(self, role):
        last = self.last_gomi_winner if role == ROLE_GOMI else self.last_souji_winner
        done_list = self.done_gomi if role == ROLE_GOMI else self.done_souji
        if not last or last in done_list:
            return

        duty_name = "ゴミ捨て" if role == ROLE_GOMI else "掃除"
        dlg = tk.Toplevel(self.root)
        dlg.title(f"前回の確認（{duty_name}）")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        result = [None]

        def finish_yes():
            result[0] = True
            dlg.destroy()

        def finish_no():
            result[0] = False
            dlg.destroy()

        big = ("Meiryo", 20)
        btn_font = ("Meiryo", 17)

        tk.Label(
            dlg,
            text=f"前回の{duty_name}当番は【 {last} 】さんでした。",
            font=big,
            pady=10,
        ).pack(padx=24, pady=(20, 8))
        tk.Label(
            dlg,
            text=f"任務（{duty_name}）は完了しましたか？",
            font=big,
        ).pack(padx=24, pady=(0, 24))

        bf = tk.Frame(dlg)
        bf.pack(pady=(0, 24))
        tk.Button(bf, text="はい（完了した）", font=btn_font, width=16, command=finish_yes).pack(side=tk.LEFT, padx=8)
        tk.Button(bf, text="いいえ（まだ）", font=btn_font, width=16, command=finish_no).pack(side=tk.LEFT, padx=8)

        self.root.update_idletasks()
        dlg.update_idletasks()
        w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

        self.root.wait_window(dlg)

        if result[0] is None:
            return

        wmap = self.weights_gomi if role == ROLE_GOMI else self.weights_souji

        if result[0]:
            if role == ROLE_GOMI:
                self.done_gomi.append(last)
            else:
                self.done_souji.append(last)
            messagebox.showinfo("確認", f"{duty_name}当番を完了リストに加えました。")
        else:
            current_weight = wmap.get(last, 1.0)
            wmap[last] = current_weight * PENALTY_RATE
            messagebox.showwarning(
                "未完了",
                f"{last}さんの{duty_name}当番：当選確率が{(PENALTY_RATE-1)*100}%アップ！！",
            )

        self.save_data()

    def check_cycle_reset(self):
        member_set = set(self.all_members)
        g_done = set(self.done_gomi)
        s_done = set(self.done_souji)

        if member_set.issubset(g_done) and member_set.issubset(s_done) and len(member_set) > 0:
            messagebox.showinfo(
                "祝！一周完了",
                "全員のゴミ捨て・掃除当番が終了しました！\nリストをリセットして、新しい周を開始します。",
            )
            self.done_gomi = []
            self.done_souji = []
            self.history_data["done_gomi"] = self.done_gomi
            self.history_data["done_souji"] = self.done_souji
            self.last_gomi_winner = None
            self.last_souji_winner = None
            self.history_data["pair_pending_souji"] = False
            self.history_data["pair_session_excluded"] = []
            self.save_data()

    def draw_wheel(self):
        self.canvas.delete("all")

        c_w = max(self.canvas.winfo_width(), 600)
        c_h = max(self.canvas.winfo_height(), 600)
        cx, cy = c_w // 2, c_h // 2
        r = max(min(c_w, c_h) // 2 - 32, 160)

        active = self.active_pool()
        if not self.candidates:
            self.canvas.create_text(cx, cy, text="No Candidates", font=("Arial", 20))
            return
        if not active:
            self.canvas.create_text(cx, cy, text="全員除外中\nリストで調整してください", font=("Meiryo", 22, "bold"), fill="#c0392b")
            return

        ordered = self.wheel_order()
        wmap = self.role_weights(self.draw_role)
        total_weight = sum(wmap.get(m, 1.0) for m in ordered)

        current_angle = 0
        colors = [
            "#FF9AA2", "#FFB7B2", "#FFDAC1", "#E2F0CB",
            "#B5EAD7", "#C7CEEA", "#F8B195", "#F67280",
        ]
        for i, member in enumerate(ordered):
            w = wmap.get(member, 1.0)
            extent_angle = (w / total_weight) * 360
            color = colors[i % len(colors)]

            self.canvas.create_arc(
                cx-r, cy-r, cx+r, cy+r,
                start=current_angle, extent=extent_angle,
                fill=color, outline="white"
            )

            text_angle_deg = current_angle + (extent_angle / 2)
            text_rad = math.radians(text_angle_deg)
            tx = cx + (r * 0.65) * math.cos(text_rad)
            ty = cy - (r * 0.65) * math.sin(text_rad)

            display_text = f"{member}\n(x{w:.1f})"
            font_size = max(int(r * 0.065), 11)
            self.canvas.create_text(tx, ty, text=display_text, font=("Meiryo", font_size, "bold"))

            current_angle += extent_angle

        rad = math.radians(self.angle)
        hand_len = int(r * 0.58)
        hx = cx + hand_len * math.cos(rad)
        hy = cy - hand_len * math.sin(rad)

        arrow_a = max(int(r * 0.60), 80)
        arrow_b = max(int(r * 0.65), 90)
        arrow_c = max(int(r * 0.085), 14)
        self.canvas.create_line(
            cx, cy, hx, hy,
            width=max(int(r * 0.012), 3),
            fill="black",
            arrow=tk.LAST,
            arrowshape=(arrow_a, arrow_b, arrow_c),
        )
        self.canvas.create_oval(cx-10, cy-10, cx+10, cy+10, fill="white")

        role_label = "ゴミ捨て" if self.draw_role == ROLE_GOMI else "掃除"
        if self.exclusions_confirmed:
            sub = f"【{role_label}当番の候補のみ表示中】"
            if self.draw_role == ROLE_SOUJI and self.session_gomi_winner:
                sub += f"\n（今週のゴミ当選者 {self.session_gomi_winner} は除く）"
        else:
            sub = "【ゴミ当番の候補のみ表示中】※掃除は右のランキング参照"
        self.canvas.create_text(cx, max(cy - r - 22, 20), text=sub, font=("Meiryo", 13, "bold"))

    def toggle_spin(self, event=None):
        if not self.is_spinning:
            if not self.exclusions_confirmed:
                self.clear_weekly_exclusions()
                return
            if not self.active_pool():
                messagebox.showwarning("抽選不可", "参加する人がいません。除外リストを確認してください。")
                return
            self.is_spinning = True
            self.stopping = False
            self.speed = 25 + random.random() * 15
            rtxt = "ゴミ捨て" if self.draw_role == ROLE_GOMI else "掃除"
            self.winner_label.config(text=f"抽選中…（{rtxt}当番）")
        else:
            if not self.stopping:
                self.stopping = True

    def animate(self):
        if self.is_spinning:
            self.angle += self.speed
            self.angle %= 360

            if self.stopping:
                self.speed *= 0.96
                if self.speed < 0.15:
                    self.speed = 0
                    self.is_spinning = False
                    self.stopping = False
                    self.determine_winner()

        self.draw_wheel()
        self.root.after(20, self.animate)

    def _apply_weekly_exclusion_bonus(self):
        """除外者にゴミ・掃除それぞれの重みを補正"""
        for role in (ROLE_GOMI, ROLE_SOUJI):
            base = self.role_candidates(role)
            wmap = self.role_weights(role)
            total_all = sum(wmap.get(m, 1.0) for m in base)
            for m in self.weekly_excluded:
                w_m = wmap.get(m, 1.0)
                if total_all > 0:
                    share = w_m / total_all
                    wmap[m] = w_m * (1.0 + share)

    def determine_winner(self):
        ordered = self.wheel_order()
        if not ordered:
            return

        wmap = self.role_weights(self.draw_role)
        total_weight = sum(wmap.get(m, 1.0) for m in ordered)
        target_angle = self.angle

        current_check_angle = 0
        winner = ordered[-1]

        for member in ordered:
            w = wmap.get(member, 1.0)
            extent_angle = (w / total_weight) * 360

            if current_check_angle <= target_angle < (current_check_angle + extent_angle):
                winner = member
                break

            current_check_angle += extent_angle

        win_rate = (wmap.get(winner, 1.0) / total_weight) * 100
        role = self.draw_role

        if role == ROLE_GOMI:
            # ゴミ当選はメモリのみ。掃除まで終わるまで JSON には書かない（途中終了＝無効）
            self.session_gomi_winner = winner
            self.winner_label.config(
                text=f"ゴミ捨て当番 決定\n【 {winner} 】さん（この抽選 {win_rate:.1f}%）\n\n"
                "続けて [Space] で掃除当番を抽選\n（※掃除まで終えるまで保存されません）",
            )
            self.show_large_winner_dialog(role, winner, win_rate)
            self.draw_role = ROLE_SOUJI
            self.refresh_info_spin_hint()
            self.update_ranking_display()
        else:
            self._apply_weekly_exclusion_bonus()
            self.last_gomi_winner = self.session_gomi_winner
            self.last_souji_winner = winner
            self.winner_label.config(
                text=f"ゴミ捨て：【 {self.session_gomi_winner} 】さん\n"
                f"掃除：【 {winner} 】さん\n（掃除の当選確率 {win_rate:.1f}%）",
            )
            self.show_large_winner_dialog(role, winner, win_rate)
            self.save_data()

            self.session_gomi_winner = None
            self.draw_role = ROLE_GOMI
            self.weekly_excluded.clear()
            self.exclude_listbox.selection_clear(0, tk.END)
            self.exclusions_confirmed = False
            self.set_exclusion_editor_locked(False)
            self.btn_confirm_exclusions.config(state=tk.NORMAL)
            self.btn_cancel_exclusion_confirm.config(state=tk.DISABLED)
            self.refresh_info_spin_hint()
            self.update_ranking_display()

        self.candidates_gomi, self.candidates_souji = compute_candidate_pools(
            self.all_members, self.done_gomi, self.done_souji
        )
        self.candidates = sorted(
            set(self.candidates_gomi) | set(self.candidates_souji),
            key=lambda x: self.all_members.index(x) if x in self.all_members else 0,
        )
        self.status_label.config(
            text=(
                f"データフォルダ: {self.data_dir}  |  "
                f"総メンバー: {len(self.all_members)}人 / "
                f"ゴミ残り: {len(self.candidates_gomi)} / 掃除残り: {len(self.candidates_souji)}"
            )
        )


if __name__ == "__main__":
    root = tk.Tk()
    app = DutyRouletteApp(root)
    root.mainloop()
