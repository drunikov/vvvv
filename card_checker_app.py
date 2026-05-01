"""
Card Availability Checker — CustomTkinter App with Animations
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

# ── Real card validation helpers ──────────────────────────────────────────────

def luhn_check(number: str) -> bool:
    """Validate a card number with the Luhn algorithm (ISO/IEC 7812)."""
    digits = [int(d) for d in number]
    digits.reverse()
    total = 0
    for i, d in enumerate(digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def detect_card_network(number: str) -> str:
    """Identify the card network from the card number prefix (IIN ranges)."""
    if re.match(r'^4[0-9]{12}(?:[0-9]{3})?$', number):
        return "Visa"
    if re.match(r'^5[1-5][0-9]{14}$', number):
        return "MasterCard"
    if re.match(r'^2(?:2[2-9][1-9]|2[3-9]|[3-6]|7[01]|720)[0-9]{12}$', number):
        return "MasterCard"
    if re.match(r'^3[47][0-9]{13}$', number):
        return "American Express"
    if re.match(r'^6(?:011|5[0-9]{2})[0-9]{12}$', number):
        return "Discover"
    if re.match(r'^3(?:0[0-5]|[68][0-9])[0-9]{11}$', number):
        return "Diners Club"
    if re.match(r'^(?:2131|1800|35\d{3})\d{11}$', number):
        return "JCB"
    if re.match(r'^62[0-9]{14,17}$', number):
        return "UnionPay"
    if re.match(r'^5019[0-9]{12}$', number):
        return "Dankort"
    if re.match(r'^6304|6759|6761|6762|6763[0-9]{12,15}$', number):
        return "Maestro"
    return "Unknown"


def bin_lookup(number: str) -> dict | None:
    """Query the free binlist.net API for BIN info (first 6-8 digits)."""
    bin_prefix = number[:8]
    url = f"https://lookup.binlist.net/{bin_prefix}"
    req = urllib.request.Request(url, headers={
        "Accept-Version": "3",
        "User-Agent": "CardCheckerApp/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return None

# ── Colour palette ──────────────────────────────────────────────────────────
BG_DARK      = "#0d1117"
CARD_BG      = "#161b22"
ACCENT       = "#58a6ff"
ACCENT_DIM   = "#1f3a5f"
SUCCESS      = "#3fb950"
ERROR        = "#f85149"
WARNING      = "#d29922"
TEXT_PRIMARY  = "#e6edf3"
TEXT_SECONDARY = "#8b949e"


# ═══════════════════════════════════════════════════════════════════════════════
class AnimatedCanvas(ctk.CTkCanvas):
    """Canvas that draws an animated spinner / result ring."""

    def __init__(self, master, size=160, **kw):
        super().__init__(master, width=size, height=size,
                         bg=BG_DARK, highlightthickness=0, **kw)
        self.size = size
        self.cx = size // 2
        self.cy = size // 2
        self.r = size // 2 - 18
        self._angle = 0
        self._running = False
        self._result = None          # None | "success" | "error" | "warning"
        self._pulse_phase = 0
        self._morph = 0.0            # 0‥1 controls result reveal
        self._particles: list = []

    # ── spinner ──────────────────────────────────────────────────────────

    def start_spinner(self):
        self._result = None
        self._running = True
        self._morph = 0.0
        self._particles = self._make_particles(30)
        self._tick_spinner()

    def _tick_spinner(self):
        if not self._running:
            return
        self._angle = (self._angle + 6) % 360
        self._pulse_phase += 0.08
        self._draw_spinner()
        self.after(16, self._tick_spinner)          # ~60 fps

    def _draw_spinner(self):
        self.delete("all")
        # orbiting particles
        for p in self._particles:
            p["a"] += p["speed"]
            px = self.cx + math.cos(p["a"]) * p["r"]
            py = self.cy + math.sin(p["a"]) * p["r"]
            alpha_hex = self._alpha(p["alpha"])
            self.create_oval(px - p["s"], py - p["s"],
                             px + p["s"], py + p["s"],
                             fill=alpha_hex, outline="")

        # arc sweep
        pulse = 0.5 + 0.5 * math.sin(self._pulse_phase)
        width = 4 + pulse * 3
        extent = 90 + pulse * 60
        pad = 18
        self.create_arc(pad, pad, self.size - pad, self.size - pad,
                        start=self._angle, extent=extent,
                        style="arc", outline=ACCENT, width=width)
        self.create_arc(pad, pad, self.size - pad, self.size - pad,
                        start=self._angle + 180, extent=extent,
                        style="arc", outline=ACCENT_DIM, width=width)

        # centre text
        self.create_text(self.cx, self.cy, text="⏳",
                         font=("Segoe UI Emoji", 28), fill=TEXT_PRIMARY)

    # ── result animation ─────────────────────────────────────────────────
    def show_result(self, kind: str):
        """kind: 'success' | 'error' | 'warning'"""
        self._running = False
        self._result = kind
        self._morph = 0.0
        self._animate_result()

    def _animate_result(self):
        self._morph = min(self._morph + 0.04, 1.0)
        self._pulse_phase += 0.06
        self._draw_result()
        if self._morph < 1.0:
            self.after(16, self._animate_result)
        else:
            # gentle continuous pulse after complete
            self._idle_pulse()

    def _idle_pulse(self):
        self._pulse_phase += 0.04
        self._draw_result()
        self.after(30, self._idle_pulse)

    def _draw_result(self):
        self.delete("all")
        t = self._ease_out_back(self._morph)
        pulse = 0.5 + 0.5 * math.sin(self._pulse_phase)

        colour = {
            "success": SUCCESS, "error": ERROR, "warning": WARNING
        }.get(self._result, ACCENT)
        icon = {"success": "✔", "error": "✖", "warning": "⚠"}.get(self._result, "?")

        # glowing ring
        r_draw = self.r * t
        glow = 8 + pulse * 6
        pad_g = self.cx - r_draw - glow
        self.create_oval(pad_g, pad_g,
                         self.size - pad_g, self.size - pad_g,
                         outline=colour, width=2, dash=(4, 4))

        pad = self.cx - r_draw
        self.create_oval(pad, pad, self.size - pad, self.size - pad,
                         outline=colour, width=4 + pulse * 2)

        # icon
        fs = int(36 * t)
        if fs > 0:
            self.create_text(self.cx, self.cy, text=icon,
                             font=("Segoe UI Emoji", fs), fill=colour)

    # ── helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _ease_out_back(t):
        c1 = 1.70158
        c3 = c1 + 1
        return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)

    def _alpha(self, a):
        """Return an ACCENT-ish colour dimmed by factor *a* (0‥1)."""
        r, g, b = 88, 166, 255          # ACCENT rgb
        r = int(r * a); g = int(g * a); b = int(b * a)
        return f"#{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def _make_particles(n):
        particles = []
        for _ in range(n):
            particles.append({
                "a": random.uniform(0, math.tau),
                "r": random.uniform(30, 70),
                "speed": random.uniform(0.01, 0.04) * random.choice([-1, 1]),
                "s": random.uniform(1.5, 3.5),
                "alpha": random.uniform(0.15, 0.6),
            })
        return particles


# ═══════════════════════════════════════════════════════════════════════════════
class CardCheckerApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("Card Availability Checker")
        self.geometry("520x700")
        self.resizable(False, False)
        self.configure(fg_color=BG_DARK)

        self._build_ui()

    # ── UI construction ──────────────────────────────────────────────────
    def _build_ui(self):
        # Title
        title = ctk.CTkLabel(self, text="💳  Card Checker",
                             font=ctk.CTkFont("Segoe UI", 28, "bold"),
                             text_color=TEXT_PRIMARY)
        title.pack(pady=(30, 4))

        subtitle = ctk.CTkLabel(self, text="Verify your card availability instantly",
                                font=ctk.CTkFont("Segoe UI", 13),
                                text_color=TEXT_SECONDARY)
        subtitle.pack(pady=(0, 24))

        # Card frame
        card_frame = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=16,
                                  border_width=1, border_color="#30363d")
        card_frame.pack(padx=36, fill="x")

        inner = ctk.CTkFrame(card_frame, fg_color="transparent")
        inner.pack(padx=24, pady=24, fill="x")

        lbl = ctk.CTkLabel(inner, text="Card Number",
                           font=ctk.CTkFont("Segoe UI", 12),
                           text_color=TEXT_SECONDARY, anchor="w")
        lbl.pack(fill="x")

        self.card_entry = ctk.CTkEntry(
            inner, height=46, corner_radius=10,
            font=ctk.CTkFont("Consolas", 16),
            placeholder_text="Enter card number…",
            fg_color="#0d1117", border_color="#30363d",
            text_color=TEXT_PRIMARY)
        self.card_entry.pack(fill="x", pady=(6, 16))
        self.card_entry.bind("<Return>", lambda e: self._on_check())

        self.check_btn = ctk.CTkButton(
            inner, text="Check Card", height=44, corner_radius=10,
            font=ctk.CTkFont("Segoe UI", 15, "bold"),
            fg_color=ACCENT, hover_color="#1f6feb",
            command=self._on_check)
        self.check_btn.pack(fill="x")

        # Hint
        hint = ctk.CTkLabel(self,
                            text="Validates with Luhn algorithm + live BIN lookup (binlist.net)",
                            font=ctk.CTkFont("Segoe UI", 10),
                            text_color="#484f58", wraplength=440)
        hint.pack(pady=(10, 0))

        # Animation canvas
        self.canvas = AnimatedCanvas(self, size=180)
        self.canvas.pack(pady=(20, 0))

        # Result area
        self.result_frame = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=14,
                                         border_width=1, border_color="#30363d")
        self.result_frame.pack(padx=36, fill="x", pady=(16, 30))
        self.result_frame.pack_forget()              # hidden initially

        self.result_icon_lbl = ctk.CTkLabel(self.result_frame, text="",
                                            font=ctk.CTkFont("Segoe UI Emoji", 22))
        self.result_title_lbl = ctk.CTkLabel(self.result_frame, text="",
                                             font=ctk.CTkFont("Segoe UI", 17, "bold"),
                                             text_color=TEXT_PRIMARY)
        self.result_detail_lbl = ctk.CTkLabel(self.result_frame, text="",
                                              font=ctk.CTkFont("Segoe UI", 12),
                                              text_color=TEXT_SECONDARY,
                                              wraplength=400, justify="left")

    # ── logic ────────────────────────────────────────────────────────────
    def _on_check(self):
        card = self.card_entry.get().strip().replace(" ", "").replace("-", "")
        if not card:
            return

        # Disable input while checking
        self.check_btn.configure(state="disabled", text="Checking…")
        self.card_entry.configure(state="disabled")
        self.result_frame.pack_forget()

        # Start spinner
        self.canvas.start_spinner()

        # Simulate async lookup
        threading.Thread(target=self._check_card, args=(card,), daemon=True).start()

    def _check_card(self, card: str):
        # ── Step 1: basic format check ──────────────────────────────────
        if not card.isdigit() or len(card) < 12 or len(card) > 19:
            self.after(0, lambda: self._show_result(
                "error", "Invalid Format ✖",
                "Card number must be 12-19 digits.\n"
                "Please check and try again."))
            return

        # ── Step 2: Luhn checksum ───────────────────────────────────────
        if not luhn_check(card):
            network = detect_card_network(card)
            self.after(0, lambda: self._show_result(
                "error", "Invalid Card Number ✖",
                f"Network detected: {network}\n"
                f"Luhn checksum: FAILED\n\n"
                "This card number is mathematically invalid.\n"
                "Every real card passes the Luhn check."))
            return

        # ── Step 3: identify network ────────────────────────────────────
        network = detect_card_network(card)

        # ── Step 4: live BIN lookup ─────────────────────────────────────
        bin_info = bin_lookup(card)

        if bin_info:
            scheme   = (bin_info.get("scheme") or "").title()
            card_type = (bin_info.get("type") or "unknown").title()
            brand    = (bin_info.get("brand") or "")
            prepaid  = bin_info.get("prepaid")
            country  = bin_info.get("country", {})
            country_name = country.get("name", "Unknown")
            country_emoji = country.get("emoji", "")
            bank     = bin_info.get("bank", {})
            bank_name = bank.get("name", "Unknown")

            lines = [
                f"Network: {network}" + (f" ({scheme})" if scheme and scheme.lower() != network.lower() else ""),
                f"Card type: {card_type}" + (f"  •  Brand: {brand}" if brand else ""),
                f"Prepaid: {'Yes' if prepaid else 'No' if prepaid is not None else 'N/A'}",
                f"Issuing bank: {bank_name}",
                f"Country: {country_emoji} {country_name}",
                f"Luhn checksum: PASSED ✓",
            ]
            detail = "\n".join(lines)

            if prepaid:
                result, title = "warning", "Valid Card — Prepaid ⚠"
            else:
                result, title = "success", "Valid Card ✓"
        else:
            # BIN API unreachable — still report Luhn + network
            detail = (
                f"Network: {network}\n"
                f"Luhn checksum: PASSED ✓\n\n"
                "BIN lookup unavailable (API timeout or rate-limited).\n"
                "The card number structure is valid."
            )
            result, title = "warning", "Card Valid — Limited Info ⚠"

        self.after(0, lambda: self._show_result(result, title, detail))

    def _show_result(self, kind, title, detail):
        colour = {"success": SUCCESS, "error": ERROR, "warning": WARNING}[kind]
        icon = {"success": "✅", "error": "❌", "warning": "⚠️"}[kind]

        self.canvas.show_result(kind)

        # Populate result frame
        for w in self.result_frame.winfo_children():
            w.destroy()

        self.result_frame.configure(border_color=colour)

        pad = ctk.CTkFrame(self.result_frame, fg_color="transparent")
        pad.pack(padx=20, pady=18, fill="x")

        ctk.CTkLabel(pad, text=f"{icon}  {title}",
                     font=ctk.CTkFont("Segoe UI", 17, "bold"),
                     text_color=colour).pack(anchor="w")

        ctk.CTkLabel(pad, text=detail,
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=TEXT_SECONDARY,
                     wraplength=400, justify="left").pack(anchor="w", pady=(6, 0))

        # Slide-in: start off-screen, animate into place
        self.result_frame.pack(padx=36, fill="x", pady=(16, 30))
        self._fade_in_result(0)

        # Re-enable input
        self.check_btn.configure(state="normal", text="Check Card")
        self.card_entry.configure(state="normal")
        self.card_entry.delete(0, "end")
        self.card_entry.focus()

    def _fade_in_result(self, step):
        """Opacity‑like fade via incremental border alpha trick."""
        if step > 6:
            return
        # Just a visual cue: we quickly cycle border width for a 'pop' effect
        w = max(1, 3 - abs(step - 3))
        self.result_frame.configure(border_width=w)
        self.after(40, lambda: self._fade_in_result(step + 1))


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = CardCheckerApp()
    app.mainloop()
