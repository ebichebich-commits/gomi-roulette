"""ゴミ捨て・掃除当番ルーレット Web サーバー（標準ライブラリのみ・依存なし）。

  python web/server.py [--host 0.0.0.0] [--port 8095] [--data-dir PATH]

データフォルダ（gomi-roulette-data）の解決順:
  --data-dir > 環境変数 GOMI_ROULETTE_DATA_DIR > roulette_paths.json の data_repo_dir
  > <このリポジトリの隣>/gomi-roulette-data > ~/gomi-roulette-data
"""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
import random
import subprocess
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
WEB = Path(__file__).resolve().parent
PAGE = WEB / "index.html"
SOUNDS = WEB / "sounds"
SOUND_EXTS = (".mp3", ".wav", ".ogg", ".m4a")

CSV_FILE = "members.csv"
DATA_FILE = "duty_history.json"
ARCHIVE_DIR = "history_archive"
ARCHIVE_META = "history_archive_meta.json"
AI_QUIZ_FILE = "ai_quiz_queue.json"
# 指定クイズ（quiz.txt）が無い週だけ使う。一度出したら列の末尾へ回す。
AI_QUIZZES = [
    {"q": "いつも留守なのに働いている人は？", "a": "留守番"},
    {"q": "どれだけ走っても前に進まない乗り物は？", "a": "ルームランナー"},
    {"q": "毎日会社にいるのに給料をもらわない人は？", "a": "社長の写真"},
    {"q": "走ると怒られる場所は？", "a": "プールサイド"},
    {"q": "いつも上から目線の野菜は？", "a": "高菜"},
    {"q": "一番口が堅い文房具は？", "a": "のり（口を封じる）"},
    {"q": "何度負けても兜を脱がない虫は？", "a": "カブトムシ"},
    {"q": "毎日サボっているのに1日2回正しい時計は？", "a": "止まった時計"},
    {"q": "どんなに賢くても解けない問題は？", "a": "まだ出題されていない問題"},
    {"q": "どれだけ頑張っても1位になれない人は？", "a": "審判"},
    {"q": "何度注意されても、同じことを繰り返す鳥は？", "a": "オウム（オウム返し）"},
    {"q": "医者が一番診察したくない楽器は？", "a": "オルガン（悪寒＝おかん、とは違うので注意）"},
    {"q": "いつも裁判で負けている動物は？", "a": "カバ（かばう側だから）"},
    {"q": "どんなに急いでも、絶対に走らない駅は？", "a": "停車駅"},
    {"q": "いつも人の秘密をばらす海の生き物は？", "a": "カニ（口が軽いという設定）"},
    {"q": "毎日学校にいるのに、絶対に卒業できないのは？", "a": "校長先生"},
    {"q": "一番礼儀正しい果物は？", "a": "レモン（礼問、という語呂）"},
    {"q": "勉強するほど軽くなるものは？", "a": "問題集（解いた問題の重荷）"},
    {"q": "何もしていないのに毎日クビになるものは？", "a": "シャツ（首から脱ぐから）"},
    {"q": "絶対に嘘をつけない楽器は？", "a": "正直なラッパ（ラッパを吹く＝大げさに話す、の逆）"},
    {"q": "世界で一番謝っている国は？", "a": "ソーリー（韓国のソウルに似ているという語呂）"},
    {"q": "どんなに偉くても頭を下げる人は？", "a": "美容師（シャンプーのとき）"},
    {"q": "誰よりも早く出社に来るのに、仕事をしない人は？", "a": "社員証の写真"},
    {"q": "どれだけ食べても太らない料理は？", "a": "食品サンプル"},
    {"q": "絶対に浮気しない文房具は？", "a": "一途な定規（まっすぐだから）"},
    {"q": "いつも人の話を聞かない野菜は？", "a": "キクイモ（聞く芋、という逆説）"},
    {"q": "何回殴られても絶対に怒らない人は？", "a": "サンドバッグの絵"},
    {"q": "一番頭が良さそうな魚は？", "a": "博士の帽子をかぶった魚"},
    {"q": "どれだけお金を積んでも買えない本は？", "a": "売り切れた本"},
    {"q": "いつも他人の名前で呼ばれる人は？", "a": "モノマネ芸人"},
]
ARCHIVE_KEEP_DAYS = 180
QUIZ_FILE_NAME = "quiz.txt"
QUIZ_ANSWER_IMAGE_NAMES = ("quiz-answer.png", "quiz-answer.jpg", "quiz-answer.jpeg", "quiz-answer.gif")
SUPPORTED_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif")
DEFAULT_MEMBERS = ["メンバーA", "メンバーB", "メンバーC", "メンバーD"]
REPORT_SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1dQkSW-dIugdTNqJ4usAkveFnUkIfIhv-E9gh1wFX7O4/edit?usp=sharing"
CLEANING_WIKI_URL = "https://www.hashimoto.lab.uec.ac.jp/intra/?%A5%B4%A5%DF%BC%CE%A4%C6%C5%F6%C8%D6"

_write_lock = threading.Lock()


def resolve_data_dir(cli: str | None) -> Path:
    cands: list[Path] = []
    for raw in (cli, os.environ.get("GOMI_ROULETTE_DATA_DIR")):
        if raw and raw.strip():
            cands.append(Path(raw.strip()).expanduser())
    cfg = ROOT / "roulette_paths.json"
    if cfg.is_file():
        try:
            raw = (json.loads(cfg.read_text(encoding="utf-8-sig")).get("data_repo_dir") or "").strip()
            if raw:
                cands.append(Path(raw).expanduser())
        except (OSError, ValueError):
            pass
    cands.append(ROOT.parent / "gomi-roulette-data")
    cands.append(Path.home() / "gomi-roulette-data")
    for c in cands:
        if c.is_dir():
            return c
    return cands[0]


def parse_date_folder(name: str):
    s = (name or "").strip()
    if not s:
        return None
    parts = [p for p in s.replace("_", "-").replace("/", "-").split("-") if p]
    now = datetime.now()
    try:
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            y, m, d = map(int, parts)
        elif len(parts) == 2 and all(p.isdigit() for p in parts):
            y, m, d = now.year, int(parts[0]), int(parts[1])
        elif s.isdigit() and len(s) == 8:
            y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
        elif s.isdigit() and len(s) == 4:
            y, m, d = now.year, int(s[:2]), int(s[2:4])
        else:
            return None
        datetime(y, m, d)
        return (y, m, d)
    except ValueError:
        return None


def read_weekly_quiz(target: Path | None):
    """quiz.txt: A. / A: / 答え / 答: から下を答え、上を問題とする。"""
    if not target:
        return None, None
    p = target / QUIZ_FILE_NAME
    if not p.is_file():
        return None, None
    try:
        lines = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return None, None
    if not lines:
        return None, None
    start = next((i for i, ln in enumerate(lines) if ln.startswith(("A.", "A:", "答え", "答:"))), None)
    if start is None:
        q, a = lines[0], "\n".join(lines[1:]).strip()
    else:
        q, a = "\n".join(lines[:start]).strip(), "\n".join(lines[start:]).strip()
    return q, (a or None)


def read_members(path: Path) -> list[str]:
    if not path.is_file():
        return list(DEFAULT_MEMBERS)
    for enc in ("utf-8-sig", "cp932"):
        try:
            with open(path, newline="", encoding=enc) as f:
                m = [r[0].strip() for r in csv.reader(f) if r and r[0].strip()]
            return m or list(DEFAULT_MEMBERS)
        except UnicodeDecodeError:
            continue
        except OSError:
            break
    return list(DEFAULT_MEMBERS)


def read_history(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8-sig"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def contact_message(gomi, souji) -> str:
    return (
        "ゴミ捨て→ \n\n"
        f"{gomi or '未決定'}\n"
        "掃除→ \n\n"
        f"{souji or '未決定'}\n\n"
        " ★★★★★★★★★★★★\n"
        f"当番報告スプレッドシート（{REPORT_SPREADSHEET_URL} ）（←ここに報告！）\n"
        "★★★★★★★★★★★★\n\n\n\n"
        "・来週火曜日の時点できれいにしておくことを心がけてください！\n\n"
        f"掃除・ゴミ捨て方法Wiki（{CLEANING_WIKI_URL} ）"
    )


class App:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.pictures = data_dir / "Pictures"

    def weekly_dir(self) -> Path | None:
        if not self.pictures.is_dir():
            return None
        dated = [(parse_date_folder(e.name), e) for e in self.pictures.iterdir() if e.is_dir()]
        dated = [(y, e) for y, e in dated if y]
        if not dated:
            return None
        n = datetime.now()
        today = (n.year, n.month, n.day)
        for y, e in dated:
            if y == today:
                return e
        return sorted(dated, key=lambda x: x[0], reverse=True)[0][1]

    def url(self, p: Path) -> str:
        return "/api/file/" + "/".join(quote(s) for s in p.relative_to(self.pictures).as_posix().split("/"))

    def _ai_quiz_path(self) -> Path:
        return self.data_dir / AI_QUIZ_FILE

    def _read_ai_queue(self) -> tuple[dict, bool]:
        p = self._ai_quiz_path()
        n = len(AI_QUIZZES)
        fresh = not p.is_file()
        raw = {}
        if not fresh:
            try:
                loaded = json.loads(p.read_text(encoding="utf-8-sig"))
                if isinstance(loaded, dict):
                    raw = loaded
            except (OSError, ValueError):
                fresh = True
        order = [i for i in (raw.get("order") or []) if isinstance(i, int) and 0 <= i < n]
        seen = set(order)
        for i in range(n):
            if i not in seen:
                order.append(i)
        if fresh or not raw.get("order"):
            order = list(range(n))
            random.shuffle(order)
            fresh = True
        by_week = {}
        src = raw.get("by_week") if isinstance(raw.get("by_week"), dict) else {}
        for k, v in src.items():
            if isinstance(v, int) and 0 <= v < n:
                by_week[str(k)] = v
        return {"order": order, "by_week": by_week}, fresh

    def _write_ai_queue(self, state: dict) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ai_quiz_path().write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def assign_ai_quiz(self, week_key: str) -> tuple[str, str]:
        """同じ週は同じ問題。初めての週だけ先頭を出し、その問題を列の最後へ回す。"""
        with _write_lock:
            state, need_write = self._read_ai_queue()
            by_week = state["by_week"]
            order = state["order"]
            if week_key in by_week:
                idx = by_week[week_key]
            else:
                idx = order[0]
                state["order"] = order[1:] + [idx]
                by_week[week_key] = idx
                if len(by_week) > 80:
                    for k in sorted(by_week)[:-80]:
                        by_week.pop(k, None)
                need_write = True
            if need_write:
                self._write_ai_queue(state)
        item = AI_QUIZZES[idx]
        return item["q"], item["a"]

    def _folder_is_this_week(self, folder: Path | None) -> bool:
        if not folder:
            return False
        parsed = parse_date_folder(folder.name)
        if not parsed:
            return False
        folder_day = datetime(*parsed)
        today = datetime.now()
        return folder_day.isocalendar()[:2] == today.isocalendar()[:2]

    def resolve_quiz(self) -> dict:
        """今週フォルダに quiz.txt があればそちら。無ければ田中作AIクイズ。"""
        t = self.weekly_dir()
        if t and self._folder_is_this_week(t):
            q, a = read_weekly_quiz(t)
            if q and a:
                img = next((self.url(t / n) for n in QUIZ_ANSWER_IMAGE_NAMES if (t / n).is_file()), None)
                return {"question": q, "answer": a, "source": "week", "image": img}
        week_key = datetime.now().strftime("%G-W%V")
        q, a = self.assign_ai_quiz(week_key)
        return {"question": q, "answer": a, "source": "ai", "image": None}

    def data(self) -> dict:
        t = self.weekly_dir()
        photos = []
        if t:
            for p in sorted(t.iterdir()):
                if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_EXTS and p.name.lower() not in QUIZ_ANSWER_IMAGE_NAMES:
                    photos.append(self.url(p))
        quiz = self.resolve_quiz()
        return {
            "ok": True,
            "members": read_members(self.data_dir / CSV_FILE),
            "history": read_history(self.data_dir / DATA_FILE),
            "week_folder": t.name if t else None,
            "photos": photos,
            # 答えは抽選が終わるまで送らない（/api/quiz-answer で取得）
            "quiz_question": quiz["question"],
            "quiz_has_answer": True,
            "quiz_source": quiz["source"],
            "has_answer_image": bool(quiz["image"]),
        }

    def quiz_answer(self) -> dict:
        quiz = self.resolve_quiz()
        return {"ok": True, "answer": quiz["answer"], "image": quiz["image"], "source": quiz["source"]}

    def _archive_root(self) -> Path:
        return self.data_dir / ARCHIVE_DIR

    def _meta_path(self) -> Path:
        return self.data_dir / ARCHIVE_META

    def _read_meta(self) -> dict:
        p = self._meta_path()
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
            if isinstance(d, dict) and isinstance(d.get("files"), list):
                return d
        except (OSError, ValueError):
            pass
        return {"files": [], "current": None}

    def _write_meta(self, meta: dict) -> None:
        self._meta_path().write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def _prune_archives(self, meta: dict) -> dict:
        root = self._archive_root()
        keep_after = datetime.now().timestamp() - ARCHIVE_KEEP_DAYS * 86400
        kept = []
        for name in meta.get("files") or []:
            fp = root / name
            if not fp.is_file():
                continue
            try:
                if fp.stat().st_mtime >= keep_after:
                    kept.append(name)
                else:
                    fp.unlink(missing_ok=True)
            except OSError:
                kept.append(name)
        meta["files"] = kept
        if meta.get("current") not in kept:
            meta["current"] = kept[-1] if kept else None
        return meta

    def _save_archive_snapshot(self, history: dict, label: str = "") -> str:
        root = self._archive_root()
        root.mkdir(parents=True, exist_ok=True)
        # 同一秒の before/after が上書きされないよう microsecond + label
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in (label or "snap"))[:40]
        name = f"{stamp}-{safe}.json"
        payload = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "label": label or stamp,
            "history": history,
        }
        (root / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return name

    def _write_history_file(self, history: dict) -> None:
        tmp = self.data_dir / (DATA_FILE + ".tmp")
        tmp.write_text(json.dumps(history, ensure_ascii=False, indent=4), encoding="utf-8")
        os.replace(tmp, self.data_dir / DATA_FILE)

    def list_archives(self) -> dict:
        meta = self._prune_archives(self._read_meta())
        root = self._archive_root()
        items = []
        for name in meta.get("files") or []:
            fp = root / name
            if not fp.is_file():
                continue
            try:
                raw = json.loads(fp.read_text(encoding="utf-8-sig"))
                h = raw.get("history") if isinstance(raw, dict) else {}
                items.append({
                    "id": name,
                    "saved_at": raw.get("saved_at") if isinstance(raw, dict) else name,
                    "label": raw.get("label") if isinstance(raw, dict) else name,
                    "gomi": (h or {}).get("last_gomi_winner"),
                    "souji": (h or {}).get("last_souji_winner"),
                    "current": name == meta.get("current"),
                })
            except (OSError, ValueError):
                continue
        return {"ok": True, "archives": items, "current": meta.get("current")}

    def restore_archive(self, archive_id: str | None, direction: str | None = None) -> dict:
        with _write_lock:
            meta = self._prune_archives(self._read_meta())
            files = meta.get("files") or []
            if not files:
                return {"ok": False, "error": "保存された週履歴がありません"}
            cur = meta.get("current")
            try:
                idx = files.index(cur) if cur in files else len(files) - 1
            except ValueError:
                idx = len(files) - 1
            if direction == "prev":
                idx = max(0, idx - 1)
            elif direction == "next":
                idx = min(len(files) - 1, idx + 1)
            elif archive_id:
                if archive_id not in files:
                    return {"ok": False, "error": "指定の履歴がありません"}
                idx = files.index(archive_id)
            else:
                return {"ok": False, "error": "direction または id が必要です"}
            name = files[idx]
            fp = self._archive_root() / name
            raw = json.loads(fp.read_text(encoding="utf-8-sig"))
            history = raw.get("history") if isinstance(raw, dict) else None
            if not isinstance(history, dict):
                return {"ok": False, "error": "履歴ファイルが壊れています"}
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._write_history_file(history)
            meta["current"] = name
            self._write_meta(meta)
            msg = contact_message(history.get("last_gomi_winner"), history.get("last_souji_winner"))
            (self.data_dir / "latest_teams_message.txt").write_text(msg, encoding="utf-8")
            return {"ok": True, "current": name, "history": history, "message": msg}

    def session_end(self, history: dict) -> dict:
        history["pair_pending_souji"] = False
        history["pair_session_excluded"] = []
        history["week_slots_finished"] = True
        msg = contact_message(history.get("last_gomi_winner"), history.get("last_souji_winner"))
        with _write_lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            # 上書き前の状態をアーカイブ（戻せるように）
            old = read_history(self.data_dir / DATA_FILE)
            meta = self._prune_archives(self._read_meta())
            if old:
                old_name = self._save_archive_snapshot(old, label="before-save")
                if old_name not in meta["files"]:
                    meta["files"].append(old_name)
            self._write_history_file(history)
            new_name = self._save_archive_snapshot(history, label="after-save")
            if new_name not in meta["files"]:
                meta["files"].append(new_name)
            meta["current"] = new_name
            meta = self._prune_archives(meta)
            self._write_meta(meta)
            (self.data_dir / "latest_teams_message.txt").write_text(msg, encoding="utf-8")
        return {"ok": True, "message": msg, "archived": True}

    def pull(self) -> dict:
        if not (self.data_dir / ".git").is_dir():
            return {"ok": False, "error": "データフォルダは git リポジトリではありません"}
        try:
            r = subprocess.run(["git", "-C", str(self.data_dir), "pull", "--ff-only"],
                               capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "error": str(e)}
        if r.returncode == 0:
            return {"ok": True}
        return {"ok": False, "error": (r.stderr or r.stdout or f"exit {r.returncode}").strip()}


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        server_version = "GomiRoulette/1.0"

        def _send(self, status, body: bytes, ctype: str, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status=200):
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            if path in ("/", "/index.html", "/gomi", "/dashboard/gomi", "/dashboard/gomi/"):
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if path.startswith("/sounds/"):
                try:
                    full = (SOUNDS / path[len("/sounds/"):]).resolve()
                    full.relative_to(SOUNDS.resolve())
                except (ValueError, OSError):
                    return self._json({"ok": False}, 404)
                if not full.is_file() or full.suffix.lower() not in SOUND_EXTS:
                    return self._json({"ok": False}, 404)
                ctype = mimetypes.guess_type(full.name)[0] or "audio/mpeg"
                return self._send(200, full.read_bytes(), ctype)
            if path == "/api/data":
                return self._json(app.data())
            if path == "/api/archives":
                return self._json(app.list_archives())
            if path == "/api/quiz-answer":
                return self._json(app.quiz_answer())
            if path.startswith("/api/file/"):
                try:
                    full = (app.pictures / path[len("/api/file/"):]).resolve()
                    full.relative_to(app.pictures.resolve())
                except (ValueError, OSError):
                    return self._json({"ok": False}, 404)
                if not full.is_file() or full.suffix.lower() not in SUPPORTED_IMAGE_EXTS:
                    return self._json({"ok": False}, 404)
                ctype = mimetypes.guess_type(full.name)[0] or "application/octet-stream"
                return self._send(200, full.read_bytes(), ctype)
            if path == "/healthz":
                return self._json({"ok": True})
            self._json({"ok": False, "error": "not found"}, 404)

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            except (ValueError, OSError):
                return self._json({"ok": False, "error": "bad request"}, 400)
            if path == "/api/session-end":
                h = body.get("history")
                if not isinstance(h, dict):
                    return self._json({"ok": False, "error": "history required"}, 400)
                try:
                    return self._json(app.session_end(h))
                except OSError as e:
                    return self._json({"ok": False, "error": str(e)}, 500)
            if path == "/api/archives/restore":
                try:
                    return self._json(app.restore_archive(body.get("id"), body.get("direction")))
                except (OSError, ValueError) as e:
                    return self._json({"ok": False, "error": str(e)}, 500)
            if path == "/api/pull":
                return self._json(app.pull())
            self._json({"ok": False, "error": "not found"}, 404)

        def log_message(self, fmt, *args):
            print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--data-dir", default=None)
    a = ap.parse_args()
    data_dir = resolve_data_dir(a.data_dir)
    print(f"data dir: {data_dir}\nlistening: http://{a.host}:{a.port}/", flush=True)
    ThreadingHTTPServer((a.host, a.port), make_handler(App(data_dir))).serve_forever()


if __name__ == "__main__":
    main()
