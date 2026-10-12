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
import subprocess
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
PAGE = Path(__file__).resolve().parent / "index.html"

CSV_FILE = "members.csv"
DATA_FILE = "duty_history.json"
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

    def data(self) -> dict:
        t = self.weekly_dir()
        photos, q, a, ai = [], None, None, False
        if t:
            for p in sorted(t.iterdir()):
                if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_EXTS and p.name.lower() not in QUIZ_ANSWER_IMAGE_NAMES:
                    photos.append(self.url(p))
            q, a = read_weekly_quiz(t)
            ai = any((t / n).is_file() for n in QUIZ_ANSWER_IMAGE_NAMES)
        return {
            "ok": True,
            "members": read_members(self.data_dir / CSV_FILE),
            "history": read_history(self.data_dir / DATA_FILE),
            "week_folder": t.name if t else None,
            "photos": photos,
            # 答えは抽選が終わるまで送らない（/api/quiz-answer で取得）
            "quiz_question": q if (q and a) else None,
            "quiz_has_answer": bool(q and a),
            "has_answer_image": ai,
        }

    def quiz_answer(self) -> dict:
        t = self.weekly_dir()
        q, a = read_weekly_quiz(t)
        if not (q and a):
            return {"ok": True, "answer": None, "image": None}
        img = next((self.url(t / n) for n in QUIZ_ANSWER_IMAGE_NAMES if (t / n).is_file()), None)
        return {"ok": True, "answer": a, "image": img}

    def session_end(self, history: dict) -> dict:
        history["pair_pending_souji"] = False
        history["pair_session_excluded"] = []
        msg = contact_message(history.get("last_gomi_winner"), history.get("last_souji_winner"))
        with _write_lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.data_dir / (DATA_FILE + ".tmp")
            tmp.write_text(json.dumps(history, ensure_ascii=False, indent=4), encoding="utf-8")
            os.replace(tmp, self.data_dir / DATA_FILE)
            (self.data_dir / "latest_teams_message.txt").write_text(msg, encoding="utf-8")
        return {"ok": True, "message": msg}

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
            if path == "/api/data":
                return self._json(app.data())
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
