#!/usr/bin/env python3
"""Приложение-опросник без веб-фреймворков.

Стек: встроенный http.server + in-memory база данных SQLite (sqlite3).
Фронтенд: Vue 3 через CDN в static/index.html, раздаётся тем же сервером.

Эндпоинты:
    GET  /questions  — список жёстко заданных вопросов из БД;
    POST /answers    — приём ответов и сохранение в in-memory БД;
    GET  /           — страница опросника (static/index.html).

Запуск:
    python3 app.py
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HOST = "0.0.0.0"
PORT = 8000
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.log")


def log(msg: str) -> None:
    """Пишет сообщение в stdout и в файл server.log (с flush)."""
    print(msg, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

# ---------------------------------------------------------------------------
# In-memory база данных SQLite.
# Используется ЕДИНОЕ соединение на всё приложение: каждое новое соединение
# к :memory: создавало бы отдельную пустую базу. check_same_thread=False —
# ThreadingHTTPServer обрабатывает запросы в разных потоках.
# ---------------------------------------------------------------------------
DB = sqlite3.connect(":memory:", check_same_thread=False)
DB.row_factory = sqlite3.Row
DB_LOCK = threading.Lock()  # защита записи при многопоточном доступе

# Жёстко заданные вопросы (заполняют таблицу questions при старте).
QUESTIONS = [
    "Какой ваш любимый язык программирования?",
    "Сколько лет вы пишете код?",
    "Какая технология вам интересна больше всего?",
    "Что бы вы хотели улучшить в своих навыках?",
]


def init_db() -> None:
    """Создаёт таблицы и заполняет базу вопросами при старте."""
    with DB_LOCK:
        DB.executescript(
            """
            CREATE TABLE IF NOT EXISTS questions (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS answers (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL,
                answer      TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                FOREIGN KEY (question_id) REFERENCES questions (id)
            );
            """
        )
        # Заполняем вопросами, только если таблица пуста (идемпотентность).
        count = DB.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        if count == 0:
            DB.executemany(
                "INSERT INTO questions (text) VALUES (?)",
                [(question,) for question in QUESTIONS],
            )
        DB.commit()


class QuestionnaireHandler(BaseHTTPRequestHandler):
    """Обработчик HTTP-запросов."""

    # -- утилиты -----------------------------------------------------------

    def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
        """Отправляет сырое тело ответа с заголовками."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict) -> None:
        """Отправляет JSON-ответ с корректной кодировкой UTF-8."""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", body)

    def _send_file(self, status: int, path: str, content_type: str) -> None:
        """Отправляет файл с диска."""
        try:
            with open(path, "rb") as handle:
                body = handle.read()
        except OSError:
            self._send_json(404, {"error": "Файл не найден"})
            return
        self._send_bytes(status, content_type, body)

    def _read_json_body(self):
        """Читает и парсит JSON-тело запроса. Возвращает (data, error)."""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None, "Некорректный заголовок Content-Length"
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, "Тело запроса должно быть корректным JSON"
        return data, None

    def log_message(self, format, *args):  # noqa: A002
        """Компактное логирование запросов (stdout + server.log)."""
        log(
            f"[{self.log_date_time_string()}] {self.address_string()} "
            f"{format % args}"
        )

    # -- маршрутизация -----------------------------------------------------

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            index_path = os.path.join(STATIC_DIR, "index.html")
            self._send_file(200, index_path, "text/html; charset=utf-8")
        elif path == "/questions":
            self._get_questions()
        else:
            self._send_json(404, {"error": "Не найдено"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/answers":
            self._post_answers()
        else:
            self._send_json(404, {"error": "Не найдено"})

    # -- эндпоинты ---------------------------------------------------------

    def _get_questions(self) -> None:
        """GET /questions — список всех вопросов из базы."""
        with DB_LOCK:
            rows = DB.execute(
                "SELECT id, text FROM questions ORDER BY id"
            ).fetchall()
        self._send_json(200, {"questions": [dict(row) for row in rows]})

    def _post_answers(self) -> None:
        """POST /answers — валидация и сохранение ответов в in-memory БД.

        Ожидаемое тело запроса:
            {"answers": [{"question_id": 1, "answer": "Python"}, ...]}

        Ответ: 201 Created или 400 Bad Request / 500 Internal Server Error.
        """
        data, error = self._read_json_body()
        if error:
            self._send_json(400, {"error": error})
            return
        if not isinstance(data, dict):
            self._send_json(400, {"error": "Тело запроса должно быть JSON-объектом"})
            return

        answers = data.get("answers")
        if not isinstance(answers, list) or not answers:
            self._send_json(
                400, {"error": "Поле 'answers' должно быть непустым списком"}
            )
            return

        # Валидация структуры ответов.
        seen = set()
        for item in answers:
            if not isinstance(item, dict):
                self._send_json(400, {"error": "Каждый ответ должен быть объектом"})
                return
            question_id = item.get("question_id")
            text = item.get("answer")
            if (
                not isinstance(question_id, int)
                or not isinstance(text, str)
                or not text.strip()
            ):
                self._send_json(
                    400,
                    {
                        "error": "У каждого ответа должны быть целочисленный "
                        "'question_id' и непустой текстовый 'answer'"
                    },
                )
                return
            if question_id in seen:
                self._send_json(
                    400, {"error": f"Дублирующийся question_id: {question_id}"}
                )
                return
            seen.add(question_id)

        # Проверяем, что все question_id существуют в таблице questions.
        placeholders = ",".join("?" * len(seen))
        with DB_LOCK:
            found = {
                row["id"]
                for row in DB.execute(
                    f"SELECT id FROM questions WHERE id IN ({placeholders})",
                    tuple(seen),
                ).fetchall()
            }
        missing = sorted(seen - found)
        if missing:
            self._send_json(400, {"error": f"Неизвестные question_id: {missing}"})
            return

        # Сохраняем ответы одной транзакцией.
        now = datetime.now(timezone.utc).isoformat()
        cleaned = [(a["question_id"], a["answer"].strip(), now) for a in answers]
        try:
            with DB_LOCK:
                DB.executemany(
                    "INSERT INTO answers (question_id, answer, created_at) "
                    "VALUES (?, ?, ?)",
                    cleaned,
                )
                DB.commit()
                # В Python 3.9 cursor.lastrowid после executemany() равен None,
                # поэтому первый id вычисляем через SELECT (защищено DB_LOCK).
                last_id = DB.execute(
                    "SELECT id FROM answers ORDER BY id DESC LIMIT 1"
                ).fetchone()["id"]
                first_id = last_id - len(cleaned) + 1
        except sqlite3.Error:
            self._send_json(500, {"error": "Ошибка при сохранении ответов"})
            return

        saved = [
            {
                "id": first_id + i,
                "question_id": question_id,
                "answer": answer,
                "created_at": now,
            }
            for i, (question_id, answer, _) in enumerate(cleaned)
        ]
        self._send_json(201, {"saved": saved, "count": len(saved)})


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), QuestionnaireHandler)
    log(f"Сервер запущен: http://localhost:{PORT}")
    log("GET  /            — страница опросника (Vue)")
    log("GET  /questions   — список вопросов")
    log("POST /answers     — сохранение ответов")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Остановка сервера...")


if __name__ == "__main__":
    main()