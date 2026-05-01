"""
Card Generator — CustomTkinter App
Generates Luhn-valid card numbers from a user-supplied BIN or a random one.
"""

import customtkinter as ctk
import math
import random
import re
import threading
import time
import urllib.request
import urllib.error
import json

# ── Theme ────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG_DARK       = "#0d1117"
CARD_BG       = "#161b22"
ACCENT        = "#58a6ff"
ACCENT_DIM    = "#1f3a5f"
SUCCESS       = "#3fb950"
ERROR         = "#f85149"
WARNING       = "#d29922"
TEXT_PRIMARY   = "#e6edf3"
TEXT_SECONDARY = "#8b949e"

# ── Common BINs for random mode ─────────────────────────────────────────────
RANDOM_BINS = [
    "411111", "431940", "400360",          # Visa
    "510510", "522131", "540735",          # MasterCard
    "340000", "370000",                    # Amex
    "601100", "650100",                    # Discover
    "353011", "356600",                    # JCB
    "621234", "625900",                    # UnionPay
]

# ── Card length by network ──────────────────────────────────────────────────
def card_length_for_bin(bin6: str) -> int:
    first = int(bin6[0])
    first2 = int(bin6[:2])
    if first2 in (34, 37):
        return 15                          # Amex
    if first == 4:
        return 16                          # Visa
    if 51 <= first2 <= 55:
        return 16                          # MasterCard
    return 16                              # default


# ── Luhn helpers ─────────────────────────────────────────────────────────────
def luhn_checksum(partial: str) -> int:
    """Return the Luhn check digit for a partial card number (without check digit)."""
    digits = [int(d) for d in partial]
    digits.reverse()
    total = 0
    for i, d in enumerate(digits):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - (total % 10)) % 10


def generate_card(bin_prefix: str, length: int) -> str:
    """Generate a single Luhn-valid card number starting with *bin_prefix*."""
    remaining = length - len(bin_prefix) - 1       # -1 for check digit
    body = bin_prefix + "".join(str(random.randint(0, 9)) for _ in range(remaining))
    return body + str(luhn_checksum(body))


def detect_network(number: str) -> str:
    if re.match(r'^4', number):          return "Visa"
    if re.match(r'^5[1-5]', number):     return "MasterCard"
    if re.match(r'^3[47]', number):      return "Amex"
    if re.match(r'^6(?:011|5)', number): return "Discover"
    if re.match(r'^35', number):         return "JCB"
    if re.match(r'^62', number):         return "UnionPay"
    return "Other"


def bin_lookup(bin6: str) -> dict | None:
    url = f"https://lookup.binlist.net/{bin6}"
    req = urllib.request.Request(url, headers={
        "Accept-Version": "3",
        "User-Agent": "CardGenApp/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
class SpinnerCanvas(ctk.CTkCanvas):
    """Small animated spinner."""

    def __init__(self, master, size=80, **kw):
        super().__init__(master, width=size, height=size,
                         bg=BG_DARK, highlightthickness=0, **kw)
        self.size = size
        self.cx = size // 2
        self.cy = size // 2
        self._angle = 0
        self._running = False

    def start(self):
        self._running = True
        self._tick()

    def stop(self):
        self._running = False
        self.delete("all")

    def _tick(self):
        if not self._running:
            return
        self._angle = (self._angle + 8) % 360
        self.delete("all")
        pad = 10
        phase = 0.5 + 0.5 * math.sin(self._angle * math.pi / 180)
        ext = 70 + phase * 50
        self.create_arc(pad, pad, self.size - pad, self.size - pad,
                        start=self._angle, extent=ext,
                        style="arc", outline=ACCENT, width=4)
        self.create_arc(pad, pad, self.size - pad, self.size - pad,
                        start=self._angle + 180, extent=ext,
                        style="arc", outline=ACCENT_DIM, width=3)
        self.after(16, self._tick)


# ═══════════════════════════════════════════════════════════════════════════════
class CardGeneratorApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("Card Generator")
        self.geometry("620x780")
        self.resizable(False, False)
        self.configure(fg_color=BG_DARK)
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Title
        ctk.CTkLabel(self, text="🃏  Card Generator",
                     font=ctk.CTkFont("Segoe UI", 26, "bold"),
                     text_color=TEXT_PRIMARY).pack(pady=(24, 2))
        ctk.CTkLabel(self, text="Generate Luhn-valid card numbers from any BIN",
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=TEXT_SECONDARY).pack(pady=(0, 18))

        # ── Input card ───────────────────────────────────────────────────
        input_frame = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=14,
                                   border_width=1, border_color="#30363d")
        input_frame.pack(padx=30, fill="x")
        inner = ctk.CTkFrame(input_frame, fg_color="transparent")
        inner.pack(padx=20, pady=18, fill="x")

        # BIN entry
        row1 = ctk.CTkFrame(inner, fg_color="transparent")
        row1.pack(fill="x")
        ctk.CTkLabel(row1, text="BIN (first 6-8 digits)",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=TEXT_SECONDARY).pack(side="left")
        ctk.CTkLabel(row1, text="leave empty = random BIN",
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color="#484f58").pack(side="right")

        self.bin_entry = ctk.CTkEntry(
            inner, height=42, corner_radius=8,
            font=ctk.CTkFont("Consolas", 15),
            placeholder_text="e.g. 411111",
            fg_color="#0d1117", border_color="#30363d",
            text_color=TEXT_PRIMARY)
        self.bin_entry.pack(fill="x", pady=(4, 12))

        # Amount selector
        amt_row = ctk.CTkFrame(inner, fg_color="transparent")
        amt_row.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(amt_row, text="Amount",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=TEXT_SECONDARY).pack(side="left")

        self.amount_var = ctk.StringVar(value="10")
        for val in ("10", "25", "50", "100"):
            ctk.CTkRadioButton(
                amt_row, text=val, variable=self.amount_var, value=val,
                font=ctk.CTkFont("Segoe UI", 12),
                text_color=TEXT_PRIMARY,
                fg_color=ACCENT, hover_color="#1f6feb",
                border_color="#30363d"
            ).pack(side="left", padx=(14, 0))

        # Generate button
        self.gen_btn = ctk.CTkButton(
            inner, text="Generate Cards", height=42, corner_radius=10,
            font=ctk.CTkFont("Segoe UI", 14, "bold"),
            fg_color=ACCENT, hover_color="#1f6feb",
            command=self._on_generate)
        self.gen_btn.pack(fill="x")

        # ── Spinner ──────────────────────────────────────────────────────
        self.spinner = SpinnerCanvas(self, size=60)
        self.spinner.pack(pady=(10, 0))

        # ── BIN info label ───────────────────────────────────────────────
        self.bin_info_lbl = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont("Segoe UI", 11),
            text_color=TEXT_SECONDARY, wraplength=540)
        self.bin_info_lbl.pack(pady=(4, 4))

        # ── Output area ──────────────────────────────────────────────────
        out_frame = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=14,
                                 border_width=1, border_color="#30363d")
        out_frame.pack(padx=30, fill="both", expand=True, pady=(6, 8))

        self.output_box = ctk.CTkTextbox(
            out_frame, font=ctk.CTkFont("Consolas", 13),
            fg_color="#0d1117", text_color=TEXT_PRIMARY,
            border_width=0, corner_radius=8, wrap="none")
        self.output_box.pack(padx=12, pady=12, fill="both", expand=True)

        # ── Bottom bar ───────────────────────────────────────────────────
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.pack(padx=30, fill="x", pady=(0, 14))

        self.status_lbl = ctk.CTkLabel(
            bot, text="Ready", font=ctk.CTkFont("Segoe UI", 11),
            text_color=TEXT_SECONDARY)
        self.status_lbl.pack(side="left")

        self.copy_btn = ctk.CTkButton(
            bot, text="Copy All", width=100, height=32, corner_radius=8,
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
            fg_color="#30363d", hover_color="#484f58",
            text_color=TEXT_PRIMARY,
            command=self._copy_all)
        self.copy_btn.pack(side="right")

    # ── Generate logic ───────────────────────────────────────────────────
    def _on_generate(self):
        raw = self.bin_entry.get().strip().replace(" ", "").replace("-", "")

        if raw and (not raw.isdigit() or len(raw) < 4 or len(raw) > 8):
            self.status_lbl.configure(text="BIN must be 4-8 digits", text_color=ERROR)
            return

        self.gen_btn.configure(state="disabled", text="Generating…")
        self.bin_entry.configure(state="disabled")
        self.output_box.delete("1.0", "end")
        self.bin_info_lbl.configure(text="")
        self.status_lbl.configure(text="Working…", text_color=TEXT_SECONDARY)
        self.spinner.start()

        amount = int(self.amount_var.get())
        threading.Thread(target=self._generate, args=(raw, amount), daemon=True).start()

    def _generate(self, user_bin: str, amount: int):
        # Pick BIN
        if user_bin:
            bin6 = user_bin[:6].ljust(6, "0")
            prefix = user_bin
        else:
            bin6 = random.choice(RANDOM_BINS)
            prefix = bin6

        length = card_length_for_bin(bin6)
        network = detect_network(prefix)

        # BIN lookup
        info = bin_lookup(bin6)
        if info:
            bank = (info.get("bank") or {}).get("name", "")
            country = (info.get("country") or {}).get("name", "")
            emoji = (info.get("country") or {}).get("emoji", "")
            ctype = (info.get("type") or "").title()
            scheme = (info.get("scheme") or "").title()
            parts = [f"BIN {bin6}"]
            if scheme:   parts.append(scheme)
            if ctype:    parts.append(ctype)
            if bank:     parts.append(bank)
            if country:  parts.append(f"{emoji} {country}")
            info_text = "  •  ".join(parts)
        else:
            info_text = f"BIN {bin6}  •  {network}  •  (BIN lookup unavailable)"

        # Generate cards
        cards = []
        seen = set()
        while len(cards) < amount:
            c = generate_card(prefix, length)
            if c not in seen:
                seen.add(c)
                cards.append(c)

        # Format output
        lines = []
        for i, c in enumerate(cards, 1):
            formatted = " ".join([c[j:j+4] for j in range(0, len(c), 4)])
            lines.append(f"{i:>3}.  {formatted}")

        text = "\n".join(lines)

        self.after(0, lambda: self._show_results(text, info_text, amount, network))

    def _show_results(self, text, info_text, count, network):
        self.spinner.stop()
        self.output_box.delete("1.0", "end")
        self.output_box.insert("1.0", text)
        self.bin_info_lbl.configure(text=info_text)
        self.status_lbl.configure(
            text=f"Generated {count} Luhn-valid {network} cards ✓",
            text_color=SUCCESS)
        self.gen_btn.configure(state="normal", text="Generate Cards")
        self.bin_entry.configure(state="normal")

    def _copy_all(self):
        text = self.output_box.get("1.0", "end").strip()
        if not text:
            return
        # Extract just the card numbers (remove line numbers)
        numbers = []
        for line in text.split("\n"):
            parts = line.strip().split(".", 1)
            if len(parts) == 2:
                numbers.append(parts[1].strip().replace(" ", ""))
        self.clipboard_clear()
        self.clipboard_append("\n".join(numbers))
        self.status_lbl.configure(text="Copied to clipboard ✓", text_color=SUCCESS)


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = CardGeneratorApp()
    app.mainloop()
