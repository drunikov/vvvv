#!/usr/bin/env python3
"""Flask web UI for the task tracker. Shares tasks.json with task_tracker.py."""

from __future__ import annotations

import json
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List

from flask import Flask, redirect, render_template_string, request, url_for

DATA_FILE = Path(__file__).resolve().parent / "tasks.json"

app = Flask(__name__)


@dataclass
class Task:
    title: str
    done: bool = False


def load_tasks() -> List[Task]:
    if not DATA_FILE.exists():
        return []
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return [Task(**item) for item in raw]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def save_tasks(tasks: List[Task]) -> None:
    DATA_FILE.write_text(
        json.dumps([asdict(task) for task in tasks], indent=2),
        encoding="utf-8",
    )


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Task Tracker</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:'Segoe UI',system-ui,sans-serif; background:#f4f5f7; color:#1f2937; display:flex; justify-content:center; padding:40px 16px; }
  .container { width:100%; max-width:540px; }
  h1 { font-size:1.8rem; margin-bottom:4px; }
  .sub { color:#6b7280; font-size:.9rem; margin-bottom:20px; }
  .add-form { display:flex; gap:8px; margin-bottom:24px; }
  .add-form input { flex:1; padding:10px 14px; border:1px solid #d1d5db; border-radius:8px; font-size:1rem; outline:none; transition:border .15s; }
  .add-form input:focus { border-color:#2563eb; }
  .add-form button { padding:10px 20px; background:#2563eb; color:#fff; border:none; border-radius:8px; font-size:1rem; font-weight:600; cursor:pointer; transition:background .15s; }
  .add-form button:hover { background:#1d4ed8; }
  .task-list { list-style:none; }
  .task-item { display:flex; align-items:center; gap:12px; padding:12px 14px; background:#fff; border:1px solid #e5e7eb; border-radius:8px; margin-bottom:8px; transition:box-shadow .15s; }
  .task-item:hover { box-shadow:0 1px 4px rgba(0,0,0,.06); }
  .task-item.done .title { text-decoration:line-through; color:#9ca3af; }
  .title { flex:1; font-size:1rem; }
  .btn { padding:6px 12px; border:none; border-radius:6px; font-size:.85rem; cursor:pointer; font-weight:500; transition:background .15s; }
  .btn-toggle { background:#f0fdf4; color:#16a34a; }
  .btn-toggle:hover { background:#dcfce7; }
  .btn-toggle.undo { background:#fefce8; color:#ca8a04; }
  .btn-toggle.undo:hover { background:#fef9c3; }
  .btn-delete { background:#fef2f2; color:#dc2626; }
  .btn-delete:hover { background:#fee2e2; }
  .status { text-align:center; color:#6b7280; margin-top:16px; font-size:.9rem; }
  .empty { text-align:center; color:#9ca3af; padding:32px 0; font-size:1.1rem; }
</style>
</head>
<body>
<div class="container">
  <h1>Task Tracker</h1>
  <p class="sub">Add, complete, and delete tasks.</p>

  <form class="add-form" method="POST" action="/add">
    <input type="text" name="title" placeholder="New task..." autofocus autocomplete="off">
    <button type="submit">Add</button>
  </form>

  {% if tasks %}
  <ul class="task-list">
    {% for task in tasks %}
    <li class="task-item {{ 'done' if task.done else '' }}">
      <span class="title">{{ task.title }}</span>
      <form method="POST" action="/toggle/{{ loop.index0 }}" style="display:inline">
        <button class="btn btn-toggle {{ 'undo' if task.done else '' }}" type="submit">
          {{ 'Undo' if task.done else 'Done' }}
        </button>
      </form>
      <form method="POST" action="/delete/{{ loop.index0 }}" style="display:inline">
        <button class="btn btn-delete" type="submit">Delete</button>
      </form>
    </li>
    {% endfor %}
  </ul>
  <p class="status">{{ done_count }}/{{ total }} completed</p>
  {% else %}
  <p class="empty">No tasks yet. Add one above!</p>
  {% endif %}
</div>
</body>
</html>
"""


@app.route("/")
def index():
    tasks = load_tasks()
    done_count = sum(1 for t in tasks if t.done)
    return render_template_string(
        HTML_TEMPLATE, tasks=tasks, done_count=done_count, total=len(tasks)
    )


@app.route("/add", methods=["POST"])
def add():
    title = (request.form.get("title") or "").strip()
    if title:
        tasks = load_tasks()
        tasks.append(Task(title=title))
        save_tasks(tasks)
    return redirect(url_for("index"))


@app.route("/toggle/<int:idx>", methods=["POST"])
def toggle(idx: int):
    tasks = load_tasks()
    if 0 <= idx < len(tasks):
        tasks[idx].done = not tasks[idx].done
        save_tasks(tasks)
    return redirect(url_for("index"))


@app.route("/delete/<int:idx>", methods=["POST"])
def delete(idx: int):
    tasks = load_tasks()
    if 0 <= idx < len(tasks):
        tasks.pop(idx)
        save_tasks(tasks)
    return redirect(url_for("index"))


def main() -> None:
    port = 5050
    print(f"Opening Task Tracker at http://localhost:{port}")
    webbrowser.open(f"http://localhost:{port}")
    app.run(port=port, debug=False)


if __name__ == "__main__":
    main()
