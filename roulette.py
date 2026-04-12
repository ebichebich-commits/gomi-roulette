import tkinter as tk
from tkinter import messagebox
import math
import random
import json
import os
import csv

# ==========================================
# 設定エリア
# ==========================================
# 名簿ファイル名（このスクリプトと同じ場所に置いてください）
CSV_FILE = "members.csv"

# データ保存用ファイル名（自動生成されます）
DATA_FILE = "duty_history.json"

# CSVがない場合のデフォルトメンバー（テスト用）
DEFAULT_MEMBERS = ["メンバーA", "メンバーB", "メンバーC", "メンバーD"]

PENALTY_RATE = 10
# ==========================================

ROLE_GOMI = "gomi"
ROLE_SOUJI = "souji"


class DutyRouletteApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ゴミ捨て・掃除当番ルーレット")
        self.root.geometry("1600x1000")
        self.root.resizable(False, False)#??????????????????????????????

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

        # 5. 役割ごとの候補
        self.candidates_gomi = [m for m in self.all_members if m not in self.done_gomi]
        self.candidates_souji = [m for m in self.all_members if m not in self.done_souji]
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

        self.right_frame = tk.Frame(root, bg="#f0f0f0", width=400)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas = tk.Canvas(root, width=900, height=900, bg="white")
        self.canvas.pack(pady=50)

        status_text = (
            f"総メンバー: {len(self.all_members)}人 / "
            f"ゴミ残り: {len(self.candidates_gomi)} / 掃除残り: {len(self.candidates_souji)}"
        )
        self.status_label = tk.Label(root, text=status_text, font=("Meiryo", 10))
        self.status_label.pack()

        self.info_label = tk.Label(root, text="", font=("Meiryo", 12), justify=tk.CENTER)
        self.info_label.pack()

        self.winner_label = tk.Label(
            root,
            text="",
            font=("Meiryo", 32, "bold"),
            fg="#c0392b",
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

        tk.Label(self.right_frame, text="【 危険度ランキング 】", font=("Meiryo", 18, "bold"), bg="#f0f0f0").pack(pady=20)

        self.ranking_box = tk.Text(self.right_frame, font=("Meiryo", 14), width=30, height=22, bg="#f0f0f0", bd=0)
        self.ranking_box.pack(padx=20, pady=10)

        self.update_ranking_display()
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
            with open(DATA_FILE, "w", encoding="utf-8") as f:
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

    def load_members_from_csv(self):
        members = []
        if not os.path.exists(CSV_FILE):
            self.create_default_csv()
            return DEFAULT_MEMBERS

        try:
            with open(CSV_FILE, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    if row and row[0].strip():
                        members.append(row[0].strip())
            return members
        except UnicodeDecodeError:
            try:
                with open(CSV_FILE, newline='', encoding='cp932') as f:
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
            with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                for m in DEFAULT_MEMBERS:
                    writer.writerow([m])
        except:
            pass

    def load_history(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
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
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
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

        cx, cy = 450, 450
        r = 430

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
            self.canvas.create_text(tx, ty, text=display_text, font=("Meiryo", 26, "bold"))

            current_angle += extent_angle

        rad = math.radians(self.angle)
        hand_len = 250
        hx = cx + hand_len * math.cos(rad)
        hy = cy - hand_len * math.sin(rad)

        self.canvas.create_line(cx, cy, hx, hy, width=5, fill="black", arrow=tk.LAST, arrowshape=(260, 280, 36))
        self.canvas.create_oval(cx-10, cy-10, cx+10, cy+10, fill="white")

        role_label = "ゴミ捨て" if self.draw_role == ROLE_GOMI else "掃除"
        if self.exclusions_confirmed:
            sub = f"【{role_label}当番の候補のみ表示中】"
            if self.draw_role == ROLE_SOUJI and self.session_gomi_winner:
                sub += f"\n（今週のゴミ当選者 {self.session_gomi_winner} は除く）"
        else:
            sub = "【ゴミ当番の候補のみ表示中】※掃除は右のランキング参照"
        self.canvas.create_text(cx, cy - r - 28, text=sub, font=("Meiryo", 14, "bold"))

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

        self.candidates_gomi = [m for m in self.all_members if m not in self.done_gomi]
        self.candidates_souji = [m for m in self.all_members if m not in self.done_souji]
        self.candidates = sorted(
            set(self.candidates_gomi) | set(self.candidates_souji),
            key=lambda x: self.all_members.index(x) if x in self.all_members else 0,
        )
        self.status_label.config(
            text=(
                f"総メンバー: {len(self.all_members)}人 / "
                f"ゴミ残り: {len(self.candidates_gomi)} / 掃除残り: {len(self.candidates_souji)}"
            )
        )


if __name__ == "__main__":
    root = tk.Tk()
    app = DutyRouletteApp(root)
    root.mainloop()
