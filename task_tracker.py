#!/usr/bin/env python3
"""Simple CLI task tracker with local JSON persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List

DATA_FILE = Path("tasks.json")


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
        print("Warning: tasks.json is invalid. Starting with an empty list.")
        return []


def save_tasks(tasks: List[Task]) -> None:
    DATA_FILE.write_text(
        json.dumps([asdict(task) for task in tasks], indent=2),
        encoding="utf-8",
    )


def print_tasks(tasks: List[Task]) -> None:
    if not tasks:
        print("\nNo tasks yet.")
        return

    print("\nYour tasks:")
    for idx, task in enumerate(tasks, start=1):
        mark = "x" if task.done else " "
        print(f"{idx}. [{mark}] {task.title}")


def add_task(tasks: List[Task]) -> None:
    title = input("Task title: ").strip()
    if not title:
        print("Task title cannot be empty.")
        return

    tasks.append(Task(title=title))
    save_tasks(tasks)
    print("Task added.")


def complete_task(tasks: List[Task]) -> None:
    if not tasks:
        print("No tasks to complete.")
        return

    print_tasks(tasks)
    raw = input("Enter task number to mark complete: ").strip()

    if not raw.isdigit():
        print("Please enter a valid number.")
        return

    idx = int(raw) - 1
    if idx < 0 or idx >= len(tasks):
        print("Task number out of range.")
        return

    tasks[idx].done = True
    save_tasks(tasks)
    print("Task marked complete.")


def delete_task(tasks: List[Task]) -> None:
    if not tasks:
        print("No tasks to delete.")
        return

    print_tasks(tasks)
    raw = input("Enter task number to delete: ").strip()

    if not raw.isdigit():
        print("Please enter a valid number.")
        return

    idx = int(raw) - 1
    if idx < 0 or idx >= len(tasks):
        print("Task number out of range.")
        return

    removed = tasks.pop(idx)
    save_tasks(tasks)
    print(f"Deleted: {removed.title}")


def main() -> None:
    tasks = load_tasks()

    while True:
        print(
            "\nTask Tracker\n"
            "1) View tasks\n"
            "2) Add task\n"
            "3) Complete task\n"
            "4) Delete task\n"
            "5) Quit"
        )

        choice = input("Choose an option: ").strip()

        if choice == "1":
            print_tasks(tasks)
        elif choice == "2":
            add_task(tasks)
        elif choice == "3":
            complete_task(tasks)
        elif choice == "4":
            delete_task(tasks)
        elif choice == "5":
            print("Goodbye!")
            break
        else:
            print("Invalid option. Please choose 1-5.")


if __name__ == "__main__":
    main()
