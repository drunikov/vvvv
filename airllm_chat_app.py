#!/usr/bin/env python3
"""CustomTkinter chat UI backed by AirLLM 4-bit inference."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import traceback
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import tkinter.messagebox as messagebox

import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG = "#0b1020"
SIDEBAR_BG = "#10192b"
CARD_BG = "#141f33"
SURFACE = "#1b2940"
BORDER = "#2b3b59"
USER_BUBBLE = "#2f6feb"
ASSISTANT_BUBBLE = "#1a2740"
TEXT_PRIMARY = "#eaf1ff"
TEXT_SECONDARY = "#9eb0cf"
SUCCESS = "#3fb950"
WARNING = "#d29922"
ERROR = "#f85149"

DEFAULT_MODEL_ID = "meta-llama/Llama-3.1-70B-Instruct"
MODEL_PRESETS = [
    "meta-llama/Llama-3.1-70B-Instruct",
    "meta-llama/Llama-3.3-70B-Instruct",
]
BACKEND_OPTIONS = ["airllm", "ollama"]
OLLAMA_FALLBACK_PRESETS = ["llama3.1:8b", "qwen2.5:7b", "mistral:7b"]


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class ChatMessage:
    role: str
    content: str
    created_at: str = field(default_factory=utc_now)


@dataclass
class Conversation:
    id: str
    title: str
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    messages: list[ChatMessage] = field(default_factory=list)


class ChatStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> tuple[list[Conversation], str | None, dict]:
        if not self.path.exists():
            return [], None, {}

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return [], None, {}

        conversations: list[Conversation] = []
        for raw_conv in data.get("conversations", []):
            messages = [
                ChatMessage(
                    role=raw_msg.get("role", "assistant"),
                    content=raw_msg.get("content", ""),
                    created_at=raw_msg.get("created_at", utc_now()),
                )
                for raw_msg in raw_conv.get("messages", [])
            ]
            conversations.append(
                Conversation(
                    id=raw_conv.get("id", str(uuid.uuid4())),
                    title=raw_conv.get("title", "New Chat"),
                    created_at=raw_conv.get("created_at", utc_now()),
                    updated_at=raw_conv.get("updated_at", utc_now()),
                    messages=messages,
                )
            )

        selected_id = data.get("selected_conversation_id")
        settings = data.get("settings", {})
        return conversations, selected_id, settings

    def save(self, conversations: list[Conversation], selected_id: str | None, settings: dict) -> None:
        payload = {
            "version": 1,
            "selected_conversation_id": selected_id,
            "settings": settings,
            "conversations": [
                {
                    "id": conv.id,
                    "title": conv.title,
                    "created_at": conv.created_at,
                    "updated_at": conv.updated_at,
                    "messages": [
                        {
                            "role": msg.role,
                            "content": msg.content,
                            "created_at": msg.created_at,
                        }
                        for msg in conv.messages
                    ],
                }
                for conv in conversations
            ],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class AirLLMService:
    def __init__(self):
        self.model = None
        self.model_id: str | None = None
        self._lock = threading.Lock()

    def ensure_loaded(
        self,
        model_id: str,
        hf_token: str,
        layer_shards_path: str,
        profiling_mode: bool,
    ) -> None:
        with self._lock:
            if self.model is not None and self.model_id == model_id:
                return

            try:
                from airllm import AutoModel
            except Exception as exc:
                raise RuntimeError(
                    "AirLLM import failed. Install compatible deps with: "
                    "python install_airllm_requirements.py "
                    f"(original error: {exc})"
                ) from exc

            kwargs = {
                "compression": "4bit",
                "profiling_mode": profiling_mode,
            }
            if hf_token:
                kwargs["hf_token"] = hf_token
            if layer_shards_path:
                kwargs["layer_shards_saving_path"] = layer_shards_path

            self.model = AutoModel.from_pretrained(model_id, **kwargs)
            self.model_id = model_id

    def generate_reply(
        self,
        messages: list[dict[str, str]],
        max_new_tokens: int,
        temperature: float,
        top_p: float,
        stop_event: threading.Event,
    ) -> str:
        if stop_event.is_set():
            return ""

        if self.model is None:
            raise RuntimeError("Model is not loaded.")

        tokenizer = self.model.tokenizer
        if hasattr(tokenizer, "apply_chat_template"):
            prompt_text = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        else:
            prompt_text = self._fallback_prompt(messages)

        tokenized = tokenizer(
            [prompt_text],
            return_tensors="pt",
            return_attention_mask=False,
            truncation=True,
            max_length=4096,
            padding=False,
        )
        input_ids = tokenized["input_ids"]

        try:
            import torch

            if torch.cuda.is_available():
                input_ids = input_ids.cuda()
        except Exception:
            pass

        if stop_event.is_set():
            return ""

        generation_output = self.model.generate(
            input_ids,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            use_cache=True,
            return_dict_in_generate=True,
        )

        sequence = generation_output.sequences[0]
        prompt_len = int(input_ids.shape[-1])
        generated_ids = sequence[prompt_len:]
        text = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()

        if text:
            return text

        full_text = tokenizer.decode(sequence, skip_special_tokens=True)
        if full_text.startswith(prompt_text):
            return full_text[len(prompt_text):].strip()
        return full_text.strip()

    @staticmethod
    def _fallback_prompt(messages: list[dict[str, str]]) -> str:
        lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        lines.append("ASSISTANT:")
        return "\n".join(lines)


class OllamaService:
    def __init__(self):
        self.base_url = "http://127.0.0.1:11434"

    def is_available(self) -> bool:
        return shutil.which("ollama") is not None

    def list_models(self) -> list[str]:
        if not self.is_available():
            return []
        try:
            proc = subprocess.run(
                ["ollama", "list"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            raise RuntimeError(f"Failed to list Ollama models: {exc}") from exc

        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        if len(lines) <= 1:
            return []

        models: list[str] = []
        for line in lines[1:]:
            parts = line.split()
            if parts:
                models.append(parts[0])
        return models

    def ensure_loaded(self, model_id: str) -> None:
        if not self.is_available():
            raise RuntimeError(
                "Ollama is not installed. Install from https://ollama.com/download"
            )
        if not model_id.strip():
            raise RuntimeError("Set an Ollama model name, e.g. llama3.1:8b")

        models = self.list_models()
        if model_id not in models:
            raise RuntimeError(
                f"Ollama model '{model_id}' not found. Run: ollama pull {model_id}"
            )

    def generate_reply(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_new_tokens: int,
        temperature: float,
        top_p: float,
        stop_event: threading.Event,
    ) -> str:
        if stop_event.is_set():
            return ""

        payload = {
            "model": model_id,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": max_new_tokens,
                "temperature": temperature,
                "top_p": top_p,
            },
        }

        req = urllib.request.Request(
            url=f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=1800) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(
                "Cannot connect to Ollama at http://127.0.0.1:11434. "
                "Start it with: ollama serve"
            ) from exc

        if stop_event.is_set():
            return ""

        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid Ollama response: {raw[:200]}") from exc

        err = obj.get("error")
        if err:
            raise RuntimeError(f"Ollama error: {err}")

        msg = (obj.get("message") or {}).get("content", "")
        return msg.strip()


class AirLLMChatApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AirLLM Chat Desktop")
        self.geometry("1280x860")
        self.minsize(980, 700)
        self.configure(fg_color=BG)

        self.store = ChatStore(Path(__file__).resolve().parent / "airllm_chat_history.json")
        self.service = AirLLMService()
        self.ollama_service = OllamaService()

        self.default_settings = {
            "backend": "airllm",
            "model_id": DEFAULT_MODEL_ID,
            "max_new_tokens": 512,
            "temperature": 0.7,
            "top_p": 0.9,
            "system_prompt": "You are a helpful assistant.",
            "layer_shards_path": "",
            "profiling_mode": False,
        }

        self.settings = dict(self.default_settings)
        self.conversations: list[Conversation] = []
        self.selected_conversation_id: str | None = None

        self.is_busy = False
        self.is_streaming = False
        self.active_stop_event = threading.Event()

        self.streaming_conv_id: str | None = None
        self.streaming_msg_idx: int | None = None
        self.streaming_words: list[str] = []
        self.streaming_word_pos = 0

        self.message_labels: dict[int, ctk.CTkLabel] = {}

        self._build_ui()
        self._load_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(
            self,
            width=280,
            corner_radius=0,
            fg_color=SIDEBAR_BG,
            border_width=1,
            border_color=BORDER,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        ctk.CTkLabel(
            self.sidebar,
            text="AirLLM Chat",
            font=ctk.CTkFont("Segoe UI", 22, "bold"),
            text_color=TEXT_PRIMARY,
        ).pack(padx=16, pady=(18, 4), anchor="w")

        ctk.CTkLabel(
            self.sidebar,
            text="Local AI desktop client • AirLLM + Ollama",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=TEXT_SECONDARY,
        ).pack(padx=16, pady=(0, 10), anchor="w")

        top_buttons = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        top_buttons.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkButton(
            top_buttons,
            text="New Chat",
            height=36,
            corner_radius=9,
            fg_color="#238636",
            hover_color="#2ea043",
            command=self._new_chat,
        ).pack(side="left", expand=True, fill="x", padx=(0, 4))

        ctk.CTkButton(
            top_buttons,
            text="Rename",
            height=36,
            corner_radius=9,
            fg_color="#30363d",
            hover_color="#484f58",
            command=self._rename_selected_chat,
        ).pack(side="left", expand=True, fill="x", padx=(4, 0))

        ctk.CTkButton(
            self.sidebar,
            text="Delete Chat",
            height=34,
            corner_radius=9,
            fg_color="#da3633",
            hover_color="#f85149",
            command=self._delete_selected_chat,
        ).pack(fill="x", padx=12, pady=(0, 8))

        self.chat_list = ctk.CTkScrollableFrame(
            self.sidebar,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color="#2f353f",
            scrollbar_button_hover_color="#3d4450",
        )
        self.chat_list.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        self.main = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_rowconfigure(2, weight=1)
        self.main.grid_columnconfigure(0, weight=1)

        self.header = ctk.CTkFrame(
            self.main,
            fg_color=SURFACE,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        self.header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        self.header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self.header,
            text="Model:",
            font=ctk.CTkFont("Segoe UI", 12),
            text_color=TEXT_SECONDARY,
        ).grid(row=0, column=0, padx=(12, 4), pady=10, sticky="w")

        self.loaded_model_label = ctk.CTkLabel(
            self.header,
            text="Not loaded",
            font=ctk.CTkFont("Consolas", 12),
            text_color=TEXT_PRIMARY,
            anchor="w",
        )
        self.loaded_model_label.grid(row=0, column=1, padx=4, pady=10, sticky="ew")

        self.status_label = ctk.CTkLabel(
            self.header,
            text="Ready",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=TEXT_SECONDARY,
            wraplength=940,
            justify="left",
        )
        self.status_label.grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 10), sticky="w")

        self.load_button = ctk.CTkButton(
            self.header,
            text="Load Model",
            width=110,
            height=34,
            corner_radius=9,
            fg_color="#1f6feb",
            hover_color="#388bfd",
            command=self._on_load_model,
        )
        self.load_button.grid(row=0, column=2, padx=(4, 8), pady=9)

        self.settings_toggle = ctk.CTkButton(
            self.header,
            text="Settings",
            width=100,
            height=34,
            corner_radius=9,
            fg_color="#30363d",
            hover_color="#484f58",
            command=self._toggle_settings,
        )
        self.settings_toggle.grid(row=0, column=3, padx=(0, 10), pady=9)

        self.settings_panel = ctk.CTkFrame(
            self.main,
            fg_color=CARD_BG,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )

        self._build_settings_panel()
        self.settings_visible = False

        self.chat_area = ctk.CTkScrollableFrame(
            self.main,
            fg_color=CARD_BG,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
            scrollbar_button_color="#2f353f",
            scrollbar_button_hover_color="#3d4450",
        )
        self.chat_area.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 8))

        composer = ctk.CTkFrame(
            self.main,
            fg_color=SURFACE,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        composer.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 14))

        self.input_box = ctk.CTkTextbox(
            composer,
            height=120,
            corner_radius=10,
            border_width=0,
            fg_color=BG,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont("Segoe UI", 13),
            wrap="word",
        )
        self.input_box.pack(fill="both", expand=True, padx=10, pady=(10, 8))
        self.input_box.bind("<Return>", self._on_return_key)

        composer_buttons = ctk.CTkFrame(composer, fg_color="transparent")
        composer_buttons.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(
            composer_buttons,
            text="Enter to send • Shift+Enter newline",
            font=ctk.CTkFont("Segoe UI", 10),
            text_color=TEXT_SECONDARY,
        ).pack(side="left")

        self.send_button = ctk.CTkButton(
            composer_buttons,
            text="Send",
            width=100,
            height=34,
            corner_radius=9,
            fg_color="#238636",
            hover_color="#2ea043",
            command=self._on_send,
        )
        self.send_button.pack(side="right", padx=(8, 0))

        self.stop_button = ctk.CTkButton(
            composer_buttons,
            text="Stop",
            width=100,
            height=34,
            corner_radius=9,
            fg_color="#da3633",
            hover_color="#f85149",
            command=self._on_stop,
            state="disabled",
        )
        self.stop_button.pack(side="right", padx=(8, 0))

        self.clear_button = ctk.CTkButton(
            composer_buttons,
            text="Clear Chat",
            width=100,
            height=34,
            corner_radius=9,
            fg_color="#30363d",
            hover_color="#484f58",
            command=self._clear_selected_chat,
        )
        self.clear_button.pack(side="right")

    def _build_settings_panel(self) -> None:
        body = ctk.CTkFrame(self.settings_panel, fg_color="transparent")
        body.pack(fill="x", padx=14, pady=12)

        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(2, weight=0)
        body.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            body,
            text="Model Preset",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont("Segoe UI", 11),
        ).grid(row=0, column=0, sticky="w", padx=(0, 6), pady=(0, 6))
        self.model_preset_var = ctk.StringVar(value=MODEL_PRESETS[0])
        self.model_preset_menu = ctk.CTkOptionMenu(
            body,
            variable=self.model_preset_var,
            values=MODEL_PRESETS,
            command=self._on_model_preset,
            fg_color=BG,
            button_color="#1f3a5f",
            button_hover_color="#1f6feb",
            dropdown_fg_color=CARD_BG,
            dropdown_hover_color="#2a313b",
            text_color=TEXT_PRIMARY,
        )
        self.model_preset_menu.grid(row=0, column=1, sticky="ew", pady=(0, 6))

        ctk.CTkLabel(
            body,
            text="Model ID",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont("Segoe UI", 11),
        ).grid(row=0, column=2, sticky="w", padx=(10, 6), pady=(0, 6))
        self.model_id_entry = ctk.CTkEntry(
            body,
            fg_color=BG,
            border_color=BORDER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont("Consolas", 12),
        )
        self.model_id_entry.grid(row=0, column=3, sticky="ew", pady=(0, 6))

        ctk.CTkLabel(
            body,
            text="HF Token",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont("Segoe UI", 11),
        ).grid(row=1, column=0, sticky="w", padx=(0, 6), pady=6)
        self.hf_token_entry = ctk.CTkEntry(
            body,
            fg_color=BG,
            border_color=BORDER,
            text_color=TEXT_PRIMARY,
            show="*",
            placeholder_text="optional here, else uses HF_TOKEN env",
        )
        self.hf_token_entry.grid(row=1, column=1, sticky="ew", pady=6)

        ctk.CTkLabel(
            body,
            text="Layer Shards Path",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont("Segoe UI", 11),
        ).grid(row=1, column=2, sticky="w", padx=(10, 6), pady=6)
        self.shards_entry = ctk.CTkEntry(
            body,
            fg_color=BG,
            border_color=BORDER,
            text_color=TEXT_PRIMARY,
            placeholder_text="optional local path",
        )
        self.shards_entry.grid(row=1, column=3, sticky="ew", pady=6)

        ctk.CTkLabel(
            body,
            text="Max New Tokens",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont("Segoe UI", 11),
        ).grid(row=2, column=0, sticky="w", padx=(0, 6), pady=6)
        self.max_tokens_entry = ctk.CTkEntry(
            body,
            width=140,
            fg_color=BG,
            border_color=BORDER,
            text_color=TEXT_PRIMARY,
        )
        self.max_tokens_entry.grid(row=2, column=1, sticky="w", pady=6)

        self.profiling_var = ctk.BooleanVar(value=False)
        self.profiling_checkbox = ctk.CTkCheckBox(
            body,
            text="Profiling mode",
            variable=self.profiling_var,
            text_color=TEXT_PRIMARY,
            fg_color="#1f6feb",
            hover_color="#388bfd",
        )
        self.profiling_checkbox.grid(row=2, column=3, sticky="w", pady=6)

        ctk.CTkLabel(
            body,
            text="Temperature",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont("Segoe UI", 11),
        ).grid(row=3, column=0, sticky="w", padx=(0, 6), pady=6)
        self.temperature_var = ctk.DoubleVar(value=0.7)
        self.temperature_slider = ctk.CTkSlider(
            body,
            from_=0.0,
            to=1.5,
            variable=self.temperature_var,
            number_of_steps=150,
            command=self._update_slider_labels,
        )
        self.temperature_slider.grid(row=3, column=1, sticky="ew", pady=6)
        self.temperature_value_label = ctk.CTkLabel(
            body,
            text="0.70",
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont("Consolas", 11),
        )
        self.temperature_value_label.grid(row=3, column=2, sticky="w", padx=(10, 6), pady=6)

        ctk.CTkLabel(
            body,
            text="Top P",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont("Segoe UI", 11),
        ).grid(row=4, column=0, sticky="w", padx=(0, 6), pady=6)
        self.top_p_var = ctk.DoubleVar(value=0.9)
        self.top_p_slider = ctk.CTkSlider(
            body,
            from_=0.1,
            to=1.0,
            variable=self.top_p_var,
            number_of_steps=90,
            command=self._update_slider_labels,
        )
        self.top_p_slider.grid(row=4, column=1, sticky="ew", pady=6)
        self.top_p_value_label = ctk.CTkLabel(
            body,
            text="0.90",
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont("Consolas", 11),
        )
        self.top_p_value_label.grid(row=4, column=2, sticky="w", padx=(10, 6), pady=6)

        ctk.CTkLabel(
            body,
            text="System Prompt",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont("Segoe UI", 11),
        ).grid(row=5, column=0, sticky="nw", padx=(0, 6), pady=(8, 4))
        self.system_prompt_box = ctk.CTkTextbox(
            body,
            height=90,
            fg_color=BG,
            border_width=1,
            border_color=BORDER,
            text_color=TEXT_PRIMARY,
            wrap="word",
            font=ctk.CTkFont("Segoe UI", 12),
        )
        self.system_prompt_box.grid(row=5, column=1, columnspan=3, sticky="ew", pady=(8, 4))

        ctk.CTkLabel(
            body,
            text="Backend",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont("Segoe UI", 11),
        ).grid(row=6, column=0, sticky="w", padx=(0, 6), pady=(8, 4))
        self.backend_var = ctk.StringVar(value="airllm")
        self.backend_menu = ctk.CTkOptionMenu(
            body,
            variable=self.backend_var,
            values=BACKEND_OPTIONS,
            command=self._on_backend_changed,
            fg_color=BG,
            button_color="#1f3a5f",
            button_hover_color="#1f6feb",
            dropdown_fg_color=CARD_BG,
            dropdown_hover_color="#2a313b",
            text_color=TEXT_PRIMARY,
        )
        self.backend_menu.grid(row=6, column=1, sticky="w", pady=(8, 4))

        ctk.CTkButton(
            body,
            text="Auto Detect",
            height=30,
            width=120,
            corner_radius=8,
            fg_color="#30363d",
            hover_color="#484f58",
            command=self._auto_detect_setup,
        ).grid(row=6, column=2, sticky="w", padx=(10, 6), pady=(8, 4))

        ctk.CTkButton(
            body,
            text="Refresh Models",
            height=30,
            width=140,
            corner_radius=8,
            fg_color="#30363d",
            hover_color="#484f58",
            command=self._refresh_model_presets_from_backend,
        ).grid(row=6, column=3, sticky="w", pady=(8, 4))

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        ctk.CTkButton(
            actions,
            text="Save Settings",
            height=34,
            corner_radius=9,
            fg_color="#30363d",
            hover_color="#484f58",
            command=self._save_settings_from_ui,
        ).pack(side="left")

        ctk.CTkLabel(
            actions,
            text="HF token is not persisted to disk.",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont("Segoe UI", 10),
        ).pack(side="left", padx=10)

    def _on_model_preset(self, value: str) -> None:
        self.model_id_entry.delete(0, "end")
        self.model_id_entry.insert(0, value)

    def _on_backend_changed(self, value: str) -> None:
        backend = value.lower().strip()
        if backend not in BACKEND_OPTIONS:
            backend = "airllm"
            self.backend_var.set(backend)
        self._sync_backend_ui(backend)
        self._refresh_model_presets(preferred_model=self.model_id_entry.get().strip())

    def _discover_local_airllm_models(self) -> list[str]:
        candidates: list[Path] = []
        app_root = Path(__file__).resolve().parent
        for root in [app_root / "models", Path.home() / "models", Path("/models")]:
            if root.exists() and root.is_dir():
                try:
                    candidates.extend(p for p in root.iterdir() if p.is_dir())
                except OSError:
                    continue

        local_models: list[str] = []
        for folder in candidates:
            has_config = (folder / "config.json").exists()
            has_tokenizer = (folder / "tokenizer.model").exists() or (folder / "tokenizer.json").exists()
            if has_config and has_tokenizer:
                local_models.append(str(folder))

        return sorted(set(local_models))

    def _refresh_model_presets(self, preferred_model: str | None = None) -> None:
        backend = self.backend_var.get().strip().lower()
        values: list[str]

        if backend == "ollama":
            try:
                values = self.ollama_service.list_models()
            except Exception:
                values = []
            if not values:
                values = list(OLLAMA_FALLBACK_PRESETS)
        else:
            local_models = self._discover_local_airllm_models()
            values = local_models + [m for m in MODEL_PRESETS if m not in local_models]

        current = (preferred_model or self.model_id_entry.get().strip()).strip()
        if current and current not in values:
            values = [current] + values

        if not values:
            values = [DEFAULT_MODEL_ID]

        self.model_preset_menu.configure(values=values)

        selected = current if current in values else values[0]
        self.model_preset_var.set(selected)

        if preferred_model is not None or not self.model_id_entry.get().strip():
            self.model_id_entry.delete(0, "end")
            self.model_id_entry.insert(0, selected)

    def _refresh_model_presets_from_backend(self) -> None:
        self._refresh_model_presets(preferred_model=self.model_id_entry.get().strip())
        self._set_status("Model presets refreshed.", SUCCESS)

    def _sync_backend_ui(self, backend: str | None = None) -> None:
        selected = (backend or self.backend_var.get()).strip().lower()
        is_ollama = selected == "ollama"

        self.hf_token_entry.configure(state="disabled" if is_ollama else "normal")
        self.shards_entry.configure(state="disabled" if is_ollama else "normal")
        self.profiling_checkbox.configure(state="disabled" if is_ollama else "normal")

        if is_ollama:
            self.hf_token_entry.configure(placeholder_text="not used for ollama")
        else:
            self.hf_token_entry.configure(placeholder_text="optional here, else uses HF_TOKEN env")

    def _auto_detect_setup(self, quiet: bool = False) -> None:
        backend = "airllm"
        preferred: str | None = None

        if self.ollama_service.is_available():
            try:
                ollama_models = self.ollama_service.list_models()
            except Exception:
                ollama_models = []
            if ollama_models:
                backend = "ollama"
                preferred = ollama_models[0]

        if backend == "airllm":
            local_models = self._discover_local_airllm_models()
            if local_models:
                preferred = local_models[0]

        self.backend_var.set(backend)
        self._sync_backend_ui(backend)
        self._refresh_model_presets(preferred_model=preferred)

        if preferred:
            self.model_id_entry.delete(0, "end")
            self.model_id_entry.insert(0, preferred)

        if not quiet:
            if backend == "ollama":
                self._set_status(f"Auto-detected Ollama backend ({preferred}).", SUCCESS)
            elif preferred:
                self._set_status(f"Auto-detected local AirLLM model at {preferred}.", SUCCESS)
            else:
                self._set_status("No local models detected; using default AirLLM preset.", WARNING)

    def _toggle_settings(self) -> None:
        self.settings_visible = not self.settings_visible
        if self.settings_visible:
            self.settings_panel.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
            self.settings_toggle.configure(text="Hide Settings")
        else:
            self.settings_panel.grid_forget()
            self.settings_toggle.configure(text="Settings")

    def _load_state(self) -> None:
        loaded_conversations, selected_id, loaded_settings = self.store.load()
        backend_was_saved = "backend" in loaded_settings

        self.conversations = loaded_conversations
        self.settings.update({k: loaded_settings.get(k, v) for k, v in self.default_settings.items()})

        if not self.conversations:
            self._create_conversation("New Chat", select=True)
        else:
            ids = {conv.id for conv in self.conversations}
            self.selected_conversation_id = selected_id if selected_id in ids else self.conversations[0].id

        self._populate_settings_ui()
        if not backend_was_saved:
            self._auto_detect_setup(quiet=True)
        self._refresh_chat_list()
        self._render_messages()
        self._set_status("Ready")

    def _populate_settings_ui(self) -> None:
        backend = str(self.settings.get("backend", "airllm")).lower()
        if backend not in BACKEND_OPTIONS:
            backend = "airllm"
        self.backend_var.set(backend)

        self.model_id_entry.delete(0, "end")
        self.model_id_entry.insert(0, self.settings["model_id"])

        self._refresh_model_presets(preferred_model=self.settings["model_id"])
        self._sync_backend_ui(backend)

        self.shards_entry.delete(0, "end")
        self.shards_entry.insert(0, self.settings["layer_shards_path"])

        self.max_tokens_entry.delete(0, "end")
        self.max_tokens_entry.insert(0, str(self.settings["max_new_tokens"]))

        self.temperature_var.set(float(self.settings["temperature"]))
        self.top_p_var.set(float(self.settings["top_p"]))
        self.profiling_var.set(bool(self.settings["profiling_mode"]))
        self._update_slider_labels()

        self.system_prompt_box.delete("1.0", "end")
        self.system_prompt_box.insert("1.0", self.settings["system_prompt"])

    def _save_state(self) -> None:
        safe_settings = dict(self.settings)
        self.store.save(self.conversations, self.selected_conversation_id, safe_settings)

    def _save_settings_from_ui(self) -> bool:
        backend = self.backend_var.get().strip().lower()
        if backend not in BACKEND_OPTIONS:
            self._set_status("Backend must be airllm or ollama.", ERROR)
            return False

        default_model = DEFAULT_MODEL_ID if backend == "airllm" else OLLAMA_FALLBACK_PRESETS[0]
        model_id = self.model_id_entry.get().strip() or default_model
        layer_shards_path = self.shards_entry.get().strip()
        system_prompt = self.system_prompt_box.get("1.0", "end").strip() or "You are a helpful assistant."

        try:
            max_new_tokens = int(self.max_tokens_entry.get().strip())
        except ValueError:
            self._set_status("Max New Tokens must be an integer.", ERROR)
            return False

        if max_new_tokens < 16 or max_new_tokens > 4096:
            self._set_status("Max New Tokens must be between 16 and 4096.", ERROR)
            return False

        if backend == "airllm" and not self._is_remote_model_id(model_id):
            local_path = Path(model_id).expanduser()
            if not local_path.exists():
                self._set_status(f"Local model path not found: {local_path}", ERROR)
                return False

        self.settings["backend"] = backend
        self.settings["model_id"] = model_id
        self.settings["layer_shards_path"] = layer_shards_path
        self.settings["system_prompt"] = system_prompt
        self.settings["max_new_tokens"] = max_new_tokens
        self.settings["temperature"] = round(float(self.temperature_var.get()), 2)
        self.settings["top_p"] = round(float(self.top_p_var.get()), 2)
        self.settings["profiling_mode"] = bool(self.profiling_var.get())
        self._save_state()
        self._set_status("Settings saved.", SUCCESS)
        return True

    @staticmethod
    def _is_remote_model_id(model_id: str) -> bool:
        model_id = model_id.strip()
        p = Path(model_id).expanduser()
        if p.exists():
            return False
        if model_id.startswith("~/"):
            return False
        if "\\" in model_id:
            return False
        if len(model_id) >= 3 and model_id[1] == ":" and model_id[2] in ("/", "\\"):
            return False
        if model_id.startswith(("./", "../", "models/", "model/")):
            return False
        if model_id.startswith("/") or model_id.startswith("."):
            return False
        if model_id.count("/") != 1:
            return False
        return True

    def _update_slider_labels(self, _value: float | None = None) -> None:
        self.temperature_value_label.configure(text=f"{float(self.temperature_var.get()):.2f}")
        self.top_p_value_label.configure(text=f"{float(self.top_p_var.get()):.2f}")

    def _set_status(self, text: str, color: str = TEXT_SECONDARY) -> None:
        self.status_label.configure(text=text, text_color=color)

    def _selected_conversation(self) -> Conversation | None:
        if not self.selected_conversation_id:
            return None
        for conv in self.conversations:
            if conv.id == self.selected_conversation_id:
                return conv
        return None

    def _create_conversation(self, title: str, select: bool = True) -> Conversation:
        conversation = Conversation(id=str(uuid.uuid4()), title=title)
        self.conversations.insert(0, conversation)
        if select:
            self.selected_conversation_id = conversation.id
        self._save_state()
        return conversation

    def _new_chat(self) -> None:
        self._create_conversation("New Chat", select=True)
        self._refresh_chat_list()
        self._render_messages()
        self.input_box.focus()

    def _rename_selected_chat(self) -> None:
        conv = self._selected_conversation()
        if conv is None:
            return

        dialog = ctk.CTkInputDialog(text="Enter new chat title", title="Rename Chat")
        new_title = (dialog.get_input() or "").strip()
        if not new_title:
            return

        conv.title = new_title[:80]
        conv.updated_at = utc_now()
        self._refresh_chat_list()
        self._save_state()

    def _delete_selected_chat(self) -> None:
        conv = self._selected_conversation()
        if conv is None:
            return

        ok = messagebox.askyesno("Delete Chat", f"Delete '{conv.title}'?")
        if not ok:
            return

        self.conversations = [c for c in self.conversations if c.id != conv.id]
        if not self.conversations:
            self._create_conversation("New Chat", select=True)
        else:
            self.selected_conversation_id = self.conversations[0].id

        self._refresh_chat_list()
        self._render_messages()
        self._save_state()

    def _clear_selected_chat(self) -> None:
        conv = self._selected_conversation()
        if conv is None:
            return
        if not conv.messages:
            return

        ok = messagebox.askyesno("Clear Chat", "Clear all messages in this chat?")
        if not ok:
            return

        conv.messages.clear()
        conv.updated_at = utc_now()
        self._render_messages()
        self._save_state()
        self._set_status("Chat cleared.")

    def _refresh_chat_list(self) -> None:
        for child in self.chat_list.winfo_children():
            child.destroy()

        self.conversations.sort(key=lambda c: c.updated_at, reverse=True)

        for conv in self.conversations:
            selected = conv.id == self.selected_conversation_id
            btn = ctk.CTkButton(
                self.chat_list,
                text=conv.title,
                anchor="w",
                height=42,
                corner_radius=10,
                fg_color="#1f6feb" if selected else CARD_BG,
                hover_color="#388bfd" if selected else "#2a313b",
                text_color=TEXT_PRIMARY,
                command=lambda cid=conv.id: self._select_chat(cid),
            )
            btn.pack(fill="x", padx=6, pady=4)

    def _select_chat(self, conversation_id: str) -> None:
        self.selected_conversation_id = conversation_id
        self._refresh_chat_list()
        self._render_messages()
        self._save_state()

    def _render_messages(self) -> None:
        for child in self.chat_area.winfo_children():
            child.destroy()
        self.message_labels.clear()

        conv = self._selected_conversation()
        if conv is None:
            return

        if not conv.messages:
            empty = ctk.CTkLabel(
                self.chat_area,
                text="Start a conversation. Load model, then send your first message.",
                text_color=TEXT_SECONDARY,
                font=ctk.CTkFont("Segoe UI", 13),
            )
            empty.pack(pady=40)
            return

        for idx, msg in enumerate(conv.messages):
            row = ctk.CTkFrame(self.chat_area, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=6)

            is_user = msg.role == "user"
            bubble = ctk.CTkFrame(
                row,
                fg_color=USER_BUBBLE if is_user else ASSISTANT_BUBBLE,
                corner_radius=14,
                border_width=1,
                border_color="#2b313c" if is_user else BORDER,
            )
            bubble.pack(anchor="e" if is_user else "w", padx=4)

            role_text = "You" if is_user else "Assistant"
            ctk.CTkLabel(
                bubble,
                text=role_text,
                text_color="#dbe9ff" if is_user else TEXT_SECONDARY,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).pack(anchor="w", padx=12, pady=(8, 0))

            content_label = ctk.CTkLabel(
                bubble,
                text=msg.content or " ",
                wraplength=760,
                justify="left",
                text_color=TEXT_PRIMARY,
                font=ctk.CTkFont("Segoe UI", 13),
            )
            content_label.pack(anchor="w", padx=12, pady=(4, 10))
            self.message_labels[idx] = content_label

        self.after(20, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        canvas = getattr(self.chat_area, "_parent_canvas", None)
        if canvas is not None:
            canvas.yview_moveto(1.0)

    def _on_return_key(self, event) -> str | None:
        shift_pressed = bool(event.state & 0x0001)
        if shift_pressed:
            return None
        self._on_send()
        return "break"

    def _on_send(self) -> None:
        if self.is_busy:
            return

        user_text = self.input_box.get("1.0", "end").strip()
        if not user_text:
            return

        if not self._save_settings_from_ui():
            return

        conv = self._selected_conversation()
        if conv is None:
            conv = self._create_conversation("New Chat", select=True)

        conv.messages.append(ChatMessage(role="user", content=user_text))
        conv.messages.append(ChatMessage(role="assistant", content=""))
        conv.updated_at = utc_now()

        if conv.title == "New Chat":
            conv.title = user_text[:48] + ("..." if len(user_text) > 48 else "")

        assistant_idx = len(conv.messages) - 1

        self.input_box.delete("1.0", "end")
        self._refresh_chat_list()
        self._render_messages()
        self._save_state()

        messages_for_model = self._build_model_messages(conv)

        model_id = self.settings["model_id"]
        backend = self.settings["backend"]
        hf_token = self.hf_token_entry.get().strip() or os.getenv("HF_TOKEN", "")
        shards_path = self.settings["layer_shards_path"]
        profiling_mode = self.settings["profiling_mode"]
        max_new_tokens = self.settings["max_new_tokens"]
        temperature = self.settings["temperature"]
        top_p = self.settings["top_p"]

        if (
            backend == "airllm"
            and self.service.model is None
            and self._is_remote_model_id(model_id)
        ):
            ok = messagebox.askyesno(
                "Download Large Model",
                "This looks like a remote Hugging Face model and can download many GB. Continue?",
            )
            if not ok:
                self._set_status("Model download canceled.", WARNING)
                return

        self.active_stop_event = threading.Event()
        self._set_busy(True)
        self._set_status("Generating reply...", TEXT_SECONDARY)

        thread = threading.Thread(
            target=self._generation_worker,
            args=(
                conv.id,
                assistant_idx,
                backend,
                messages_for_model,
                model_id,
                hf_token,
                shards_path,
                profiling_mode,
                max_new_tokens,
                temperature,
                top_p,
                self.active_stop_event,
            ),
            daemon=True,
        )
        thread.start()

    def _build_model_messages(self, conv: Conversation) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        system_prompt = self.settings["system_prompt"].strip()
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        for msg in conv.messages:
            if msg.role not in {"user", "assistant"}:
                continue
            if not msg.content.strip():
                continue
            messages.append({"role": msg.role, "content": msg.content})

        return messages

    def _set_busy(self, busy: bool) -> None:
        self.is_busy = busy
        self.send_button.configure(state="disabled" if busy else "normal")
        self.stop_button.configure(state="normal" if busy else "disabled")
        self.load_button.configure(state="disabled" if busy else "normal")

    def _on_stop(self) -> None:
        if not self.is_busy:
            return
        self.active_stop_event.set()
        if self.is_streaming:
            self._set_status("Stopping streamed response...", WARNING)
        else:
            self._set_status("Stop requested. Waiting for generation to return...", WARNING)

    def _generation_worker(
        self,
        conversation_id: str,
        assistant_idx: int,
        backend: str,
        messages_for_model: list[dict[str, str]],
        model_id: str,
        hf_token: str,
        shards_path: str,
        profiling_mode: bool,
        max_new_tokens: int,
        temperature: float,
        top_p: float,
        stop_event: threading.Event,
    ) -> None:
        try:
            self.after(0, lambda: self._set_status("Loading model if needed...", TEXT_SECONDARY))

            if backend == "ollama":
                self.ollama_service.ensure_loaded(model_id)
                self.after(0, lambda: self.loaded_model_label.configure(text=f"ollama: {model_id}"))
            else:
                self.service.ensure_loaded(model_id, hf_token, shards_path, profiling_mode)
                self.after(0, lambda: self.loaded_model_label.configure(text=f"airllm: {model_id}"))

            if stop_event.is_set():
                self.after(0, lambda: self._finalize_stopped(conversation_id, assistant_idx))
                return

            if backend == "ollama":
                reply_text = self.ollama_service.generate_reply(
                    model_id=model_id,
                    messages=messages_for_model,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    stop_event=stop_event,
                )
            else:
                reply_text = self.service.generate_reply(
                    messages_for_model,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    stop_event=stop_event,
                )

            self.after(0, lambda: self._start_streaming_reply(conversation_id, assistant_idx, reply_text, stop_event))
        except Exception as exc:
            err_text = self._friendly_error(exc)
            self.after(0, lambda: self._handle_generation_error(conversation_id, assistant_idx, err_text))

    def _start_streaming_reply(
        self,
        conversation_id: str,
        assistant_idx: int,
        reply_text: str,
        stop_event: threading.Event,
    ) -> None:
        conv = self._conversation_by_id(conversation_id)
        if conv is None:
            self._set_busy(False)
            return

        if stop_event.is_set():
            self._finalize_stopped(conversation_id, assistant_idx)
            return

        cleaned = reply_text.strip() or "[No text returned.]"
        self.streaming_conv_id = conversation_id
        self.streaming_msg_idx = assistant_idx
        self.streaming_words = cleaned.split()
        self.streaming_word_pos = 0
        self.is_streaming = True

        self._set_status("Streaming response...", TEXT_SECONDARY)
        self._stream_tick(stop_event)

    def _stream_tick(self, stop_event: threading.Event) -> None:
        if not self.is_streaming or self.streaming_conv_id is None or self.streaming_msg_idx is None:
            return

        conv = self._conversation_by_id(self.streaming_conv_id)
        if conv is None:
            self._finish_streaming()
            return

        if stop_event.is_set():
            self._finalize_stopped(self.streaming_conv_id, self.streaming_msg_idx)
            return

        if self.streaming_word_pos >= len(self.streaming_words):
            self._finish_streaming()
            return

        step = 6
        self.streaming_word_pos = min(self.streaming_word_pos + step, len(self.streaming_words))
        partial = " ".join(self.streaming_words[: self.streaming_word_pos]).strip()

        if 0 <= self.streaming_msg_idx < len(conv.messages):
            conv.messages[self.streaming_msg_idx].content = partial
            conv.messages[self.streaming_msg_idx].created_at = conv.messages[self.streaming_msg_idx].created_at or utc_now()
            conv.updated_at = utc_now()

            if conv.id == self.selected_conversation_id and self.streaming_msg_idx in self.message_labels:
                self.message_labels[self.streaming_msg_idx].configure(text=partial or " ")
                self._scroll_to_bottom()

        if self.streaming_word_pos >= len(self.streaming_words):
            self._finish_streaming()
            return

        self.after(25, lambda: self._stream_tick(stop_event))

    def _finish_streaming(self) -> None:
        self.is_streaming = False
        self._save_state()
        self._refresh_chat_list()
        self._set_status("Done.", SUCCESS)
        self._set_busy(False)

    def _finalize_stopped(self, conversation_id: str, assistant_idx: int) -> None:
        conv = self._conversation_by_id(conversation_id)
        if conv and 0 <= assistant_idx < len(conv.messages):
            content = conv.messages[assistant_idx].content.strip()
            if not content:
                conv.messages[assistant_idx].content = "[Stopped]"
            conv.updated_at = utc_now()

        self.is_streaming = False
        self._render_messages()
        self._refresh_chat_list()
        self._save_state()
        self._set_status("Generation stopped.", WARNING)
        self._set_busy(False)

    def _handle_generation_error(self, conversation_id: str, assistant_idx: int, message: str) -> None:
        conv = self._conversation_by_id(conversation_id)
        if conv and 0 <= assistant_idx < len(conv.messages):
            conv.messages[assistant_idx].content = message
            conv.updated_at = utc_now()

        self.is_streaming = False
        self._render_messages()
        self._refresh_chat_list()
        self._save_state()
        self._set_status("Generation failed.", ERROR)
        self._set_busy(False)

    def _friendly_error(self, exc: Exception) -> str:
        text = str(exc)
        low = text.lower()

        if "airllm import failed" in low:
            return "AirLLM import failed. Run: python install_airllm_requirements.py"
        if "airllm is not installed" in low:
            return "AirLLM is missing. Install with: pip install airllm bitsandbytes"
        if "ollama is not installed" in low:
            return "Ollama is not installed. Install it from https://ollama.com/download"
        if "cannot connect to ollama" in low or "connection refused" in low:
            return "Ollama is not running. Start it with: ollama serve"
        if "ollama model" in low and "not found" in low:
            return text
        if "bettertransformer requires transformers<4.49" in low:
            return (
                "Dependency mismatch: AirLLM's BetterTransformer needs transformers<4.49. "
                "Run: python install_airllm_requirements.py"
            )
        if "no module named 'sentencepiece'" in low:
            return "Missing dependency: sentencepiece. Run: python install_airllm_requirements.py"
        if "401" in low or "unauthorized" in low or "gated" in low or "access" in low:
            return (
                "Model access failed. Ensure your HF account is approved for "
                "meta-llama/Llama-3.1-70B-Instruct and set HF_TOKEN."
            )
        if "bitsandbytes" in low:
            return "bitsandbytes failed to initialize. Install/upgrade bitsandbytes for your CUDA setup."
        if "cuda" in low and "out of memory" in low:
            return "CUDA out of memory. Close other GPU apps or lower max tokens."
        if "no module named" in low:
            return f"Missing Python dependency: {text}. Run: python install_airllm_requirements.py"

        return f"Error: {text}"

    def _conversation_by_id(self, conversation_id: str) -> Conversation | None:
        for conv in self.conversations:
            if conv.id == conversation_id:
                return conv
        return None

    def _on_load_model(self) -> None:
        if self.is_busy:
            return

        if not self._save_settings_from_ui():
            return
        backend = self.settings["backend"]
        model_id = self.settings["model_id"]
        hf_token = self.hf_token_entry.get().strip() or os.getenv("HF_TOKEN", "")
        shards_path = self.settings["layer_shards_path"]
        profiling_mode = self.settings["profiling_mode"]

        if backend == "airllm" and self._is_remote_model_id(model_id):
            ok = messagebox.askyesno(
                "Download Large Model",
                "This appears to be a remote Hugging Face model and can download many GB. Continue?",
            )
            if not ok:
                self._set_status("Model download canceled.", WARNING)
                return

        self._set_busy(True)
        if backend == "ollama":
            self._set_status("Checking Ollama model...", WARNING)
        else:
            self._set_status("Loading model... this can take several minutes.", WARNING)

        thread = threading.Thread(
            target=self._load_model_worker,
            args=(backend, model_id, hf_token, shards_path, profiling_mode),
            daemon=True,
        )
        thread.start()

    def _load_model_worker(
        self,
        backend: str,
        model_id: str,
        hf_token: str,
        shards_path: str,
        profiling_mode: bool,
    ) -> None:
        try:
            if backend == "ollama":
                self.ollama_service.ensure_loaded(model_id)
                self.after(0, lambda: self.loaded_model_label.configure(text=f"ollama: {model_id}"))
                self.after(0, lambda: self._set_status("Ollama model ready.", SUCCESS))
            else:
                self.service.ensure_loaded(model_id, hf_token, shards_path, profiling_mode)
                self.after(0, lambda: self.loaded_model_label.configure(text=f"airllm: {model_id}"))
                self.after(0, lambda: self._set_status("Model loaded.", SUCCESS))
        except Exception as exc:
            err_text = self._friendly_error(exc)
            self.after(0, lambda: self._set_status(err_text, ERROR))
        finally:
            self.after(0, lambda: self._set_busy(False))

    def _on_close(self) -> None:
        self.active_stop_event.set()
        self._save_settings_from_ui()
        self._save_state()
        self.destroy()


def main() -> None:
    app = AirLLMChatApp()
    app.mainloop()


if __name__ == "__main__":
    main()
