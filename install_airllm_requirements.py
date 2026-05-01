#!/usr/bin/env python3
"""Install dependencies for airllm_chat_app.py.

Cross-platform behavior:
- Linux (auto): installs AirLLM stack + base deps, with --break-system-packages.
- Windows (auto): installs base deps for Ollama/backend usage, avoids fragile AirLLM stack.
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys

BASE_REQUIREMENTS = [
    "customtkinter",
    "huggingface_hub",
]

AIRLLM_REQUIREMENTS = [
    "airllm",
    "optimum<2",
    "sentencepiece",
    "bitsandbytes",
    "torch",
    "transformers<4.49",
]


def _is_linux() -> bool:
    return platform.system().lower() == "linux"


def _is_windows() -> bool:
    return platform.system().lower() == "windows"


def _run(cmd: list[str]) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _backend_to_with_airllm(backend: str) -> bool:
    if backend == "airllm":
        return True
    if backend == "ollama":
        return False
    return not _is_windows()


def install_requirements(backend: str) -> None:
    pip_base = [sys.executable, "-m", "pip"]
    extra_flags = ["--break-system-packages"] if _is_linux() else []
    with_airllm = _backend_to_with_airllm(backend)

    print("Installing dependencies for AirLLM chat app...")
    if extra_flags:
        print("Linux detected: using --break-system-packages")
    if _is_windows() and backend == "auto":
        print("Windows auto mode: using Ollama-friendly deps by default.")

    _run(pip_base + ["install", "--upgrade", "pip"] + extra_flags)

    _run(pip_base + ["install"] + extra_flags + BASE_REQUIREMENTS)

    if with_airllm:
        _run(pip_base + ["install"] + extra_flags + AIRLLM_REQUIREMENTS)

    if with_airllm:
        print("Done. Backend ready: airllm")
    else:
        print("Done. Backend ready: ollama")

    if _is_windows() and not with_airllm:
        print("Next: install Ollama from https://ollama.com/download and run 'ollama pull llama3.1:8b'")

    print("Done. You can now run: python airllm_chat_app.py")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install dependencies for airllm_chat_app.py")
    parser.add_argument(
        "--backend",
        choices=["auto", "airllm", "ollama"],
        default="auto",
        help="Dependency profile to install (default: auto)",
    )
    args = parser.parse_args()

    try:
        install_requirements(args.backend)
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"Install failed with exit code {exc.returncode}")
        return exc.returncode or 1
    except KeyboardInterrupt:
        print("Install cancelled.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
