import sqlite3
import json
import os
from datetime import datetime


DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "projects.db")


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number INTEGER UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            keyword TEXT,
            title TEXT,
            description TEXT,
            tags TEXT,
            script TEXT,
            thumbnail_prompts TEXT,
            audio_path TEXT,
            video_path TEXT,
            source_urls TEXT,
            notes TEXT
        )
    """)
    conn.commit()
    conn.close()


def next_project_number():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT MAX(number) FROM projects")
    row = c.fetchone()
    conn.close()
    max_num = row[0] if row[0] is not None else 0
    return max_num + 1


def save_project(data: dict) -> int:
    conn = get_connection()
    c = conn.cursor()
    number = next_project_number()
    c.execute("""
        INSERT INTO projects
            (number, created_at, keyword, title, description, tags, script,
             thumbnail_prompts, audio_path, video_path, source_urls, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        number,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        data.get("keyword", ""),
        data.get("title", ""),
        data.get("description", ""),
        json.dumps(data.get("tags", []), ensure_ascii=False),
        data.get("script", ""),
        json.dumps(data.get("thumbnail_prompts", []), ensure_ascii=False),
        data.get("audio_path", ""),
        data.get("video_path", ""),
        json.dumps(data.get("source_urls", []), ensure_ascii=False),
        data.get("notes", ""),
    ))
    project_id = c.lastrowid
    conn.commit()
    conn.close()
    return project_id


def update_project(project_id: int, data: dict):
    conn = get_connection()
    c = conn.cursor()
    fields = []
    values = []
    for key, val in data.items():
        if key in ("tags", "thumbnail_prompts", "source_urls"):
            val = json.dumps(val, ensure_ascii=False)
        fields.append(f"{key} = ?")
        values.append(val)
    values.append(project_id)
    c.execute(f"UPDATE projects SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    conn.close()


def get_all_projects():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM projects ORDER BY number DESC")
    rows = c.fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        for field in ("tags", "thumbnail_prompts", "source_urls"):
            try:
                d[field] = json.loads(d[field]) if d[field] else []
            except Exception:
                d[field] = []
        result.append(d)
    return result


def get_project(project_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for field in ("tags", "thumbnail_prompts", "source_urls"):
        try:
            d[field] = json.loads(d[field]) if d[field] else []
        except Exception:
            d[field] = []
    return d


def delete_project(project_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()
