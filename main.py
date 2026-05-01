"""
Card Tool — Generator + Checker in one app
Tabbed CustomTkinter UI with animations.
Generator outputs realistic cards: number | expiry | CVV | holder name.
Checker validates with Luhn + live BIN lookup.
"""

import customtkinter as ctk
import math
import random
import re
import string
import threading
import time
import urllib.request
import urllib.error
import json
from datetime import datetime

# ── Theme ────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG_DARK       = "#0d1117"
CARD_BG       = "#161b22"
SURFACE       = "#1c2129"
ACCENT        = "#58a6ff"
ACCENT_DIM    = "#1f3a5f"
SUCCESS       = "#3fb950"
ERROR         = "#f85149"
WARNING       = "#d29922"
TEXT_PRIMARY   = "#e6edf3"
TEXT_SECONDARY = "#8b949e"
BORDER        = "#30363d"

# ── Realistic name pools ─────────────────────────────────────────────────────
FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
    "Linda", "David", "Elizabeth", "William", "Barbara", "Richard", "Susan",
    "Joseph", "Jessica", "Thomas", "Sarah", "Christopher", "Karen", "Charles",
    "Lisa", "Daniel", "Nancy", "Matthew", "Betty", "Anthony", "Margaret",
    "Mark", "Sandra", "Donald", "Ashley", "Steven", "Kimberly", "Andrew",
    "Emily", "Paul", "Donna", "Joshua", "Michelle", "Kenneth", "Carol",
    "Kevin", "Amanda", "Brian", "Dorothy", "George", "Melissa", "Timothy",
    "Deborah", "Ronald", "Stephanie", "Edward", "Rebecca", "Jason", "Sharon",
    "Jeffrey", "Laura", "Ryan", "Cynthia", "Jacob", "Kathleen", "Gary",
    "Amy", "Nicholas", "Angela", "Eric", "Shirley", "Jonathan", "Anna",
    "Stephen", "Brenda", "Larry", "Pamela", "Justin", "Emma", "Scott",
    "Nicole", "Brandon", "Helen", "Benjamin", "Samantha", "Samuel", "Katherine",
    "Raymond", "Christine", "Gregory", "Debra", "Frank", "Rachel", "Alexander",
    "Carolyn", "Patrick", "Janet", "Jack", "Catherine", "Dennis", "Maria",
    "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia", "Mason", "Isabella",
    "Logan", "Mia", "Lucas", "Charlotte", "Aiden", "Amelia", "Oliver", "Harper",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz",
    "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris",
    "Morales", "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan",
    "Cooper", "Peterson", "Bailey", "Reed", "Kelly", "Howard", "Ramos",
    "Kim", "Cox", "Ward", "Richardson", "Watson", "Brooks", "Chavez",
    "Wood", "James", "Bennett", "Gray", "Mendoza", "Ruiz", "Hughes",
    "Price", "Alvarez", "Castillo", "Sanders", "Patel", "Myers", "Long",
    "Ross", "Foster", "Jimenez", "Powell", "Jenkins", "Perry", "Russell",
]

# ═════════════════════════════════════════════════════════════════════════════
#  LOCAL BIN DATABASE — 110+ countries, 700+ BINs (imported from bin_database)
# ═════════════════════════════════════════════════════════════════════════════

from bin_database import BIN_DB

# ── Build lookup structures from BIN_DB ──────────────────────────────────────
_BIN_INFO: dict[str, dict] = {}
_COUNTRY_BINS: dict[str, list[str]] = {}
_ALL_BINS: list[str] = []

for _bin, _scheme, _type, _bank, _country in BIN_DB:
    _BIN_INFO[_bin] = {
        "scheme": _scheme, "type": _type, "brand": "",
        "prepaid": None,
        "bank": {"name": _bank},
        "country": {"name": _country, "emoji": ""},
    }
    _COUNTRY_BINS.setdefault(_country, []).append(_bin)
    _ALL_BINS.append(_bin)

COUNTRY_LIST = sorted(_COUNTRY_BINS.keys())


# ═════════════════════════════════════════════════════════════════════════════
#  CARD ENGINE — shared by both tabs
# ═════════════════════════════════════════════════════════════════════════════

def luhn_check(number: str) -> bool:
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


def luhn_checksum(partial: str) -> int:
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


def detect_network(number: str) -> str:
    if re.match(r'^4', number):            return "Visa"
    if re.match(r'^5[1-5]', number):       return "MasterCard"
    if re.match(r'^2(?:2[2-9]|[3-6]|7[01]|720)', number): return "MasterCard"
    if re.match(r'^3[47]', number):        return "Amex"
    if re.match(r'^6(?:011|5)', number):   return "Discover"
    if re.match(r'^3(?:0[0-5]|[68])', number): return "Diners Club"
    if re.match(r'^35', number):           return "JCB"
    if re.match(r'^62', number):           return "UnionPay"
    return "Unknown"


def card_length_for_bin(bin6: str) -> int:
    first2 = int(bin6[:2])
    if first2 in (34, 37):
        return 15
    return 16


def cvv_length_for_network(network: str) -> int:
    return 4 if network == "Amex" else 3


def generate_card_number(bin_prefix: str, length: int) -> str:
    remaining = length - len(bin_prefix) - 1
    body = bin_prefix + "".join(str(random.randint(0, 9)) for _ in range(remaining))
    return body + str(luhn_checksum(body))


def generate_expiry() -> str:
    now = datetime.now()
    future_months = random.randint(1, 60)
    month = ((now.month - 1 + future_months) % 12) + 1
    year = now.year + (now.month - 1 + future_months) // 12
    return f"{month:02d}/{year % 100:02d}"


def generate_cvv(length: int) -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(length))


def generate_holder_name() -> str:
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def bin_lookup(bin_str: str) -> dict | None:
    """Instant local BIN lookup — no API, no rate limits."""
    bin6 = bin_str[:6]
    if bin6 in _BIN_INFO:
        return _BIN_INFO[bin6]
    # Try matching by prefix (first 4-5 digits)
    for length in (5, 4):
        prefix = bin6[:length]
        for k, v in _BIN_INFO.items():
            if k.startswith(prefix):
                return v
    return None


def online_bin_verify(bin6: str) -> dict | None:
    """Live BIN check via binlist.net — returns real API data or None."""
    url = f"https://lookup.binlist.net/{bin6}"
    req = urllib.request.Request(url, headers={
        "Accept-Version": "3",
        "User-Agent": "CardToolApp/2.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, OSError):
        return None


def validate_card_deep(num: str, expiry: str, cvv: str,
                       local_info: dict | None,
                       online_info: dict | None) -> tuple[str, str, str]:
    """
    Multi-layer card validation. Returns (status, icon, reason).
    Statuses: LIVE, DEAD, UNKNOWN
    """
    network = detect_network(num)
    bin6 = num[:6]

    # ── Layer 1: Luhn ──
    if not luhn_check(num):
        return ("DEAD", "❌", "Luhn FAIL — invalid checksum")

    # ── Layer 2: card length vs scheme ──
    expected_len = 15 if network == "Amex" else 16
    if len(num) != expected_len:
        return ("DEAD", "❌", f"Wrong length ({len(num)}) for {network} (expected {expected_len})")

    # ── Layer 3: BIN prefix matches claimed network ──
    if local_info:
        db_scheme = local_info.get("scheme", "")
        if db_scheme and db_scheme.lower() != network.lower():
            if not (db_scheme == "MasterCard" and network == "MasterCard"):
                return ("DEAD", "❌",
                        f"BIN scheme mismatch: DB={db_scheme}, detected={network}")

    # ── Layer 4: expiry date ──
    try:
        m, y = expiry.split("/")
        exp_month, exp_year = int(m), 2000 + int(y)
        now = datetime.now()
        if exp_year < now.year or (exp_year == now.year and exp_month < now.month):
            return ("DEAD", "❌", "Card expired")
    except (ValueError, IndexError):
        pass

    # ── Layer 5: CVV format ──
    cvv_expected = 4 if network == "Amex" else 3
    if len(cvv) != cvv_expected:
        return ("DEAD", "❌", f"CVV wrong length ({len(cvv)}) for {network}")

    # ── Layer 6: online BIN verification ──
    if online_info:
        api_scheme = (online_info.get("scheme") or "").title()
        api_type = (online_info.get("type") or "").title()
        api_bank = (online_info.get("bank") or {}).get("name", "Unknown")
        api_country = (online_info.get("country") or {}).get("name", "?")
        api_emoji = (online_info.get("country") or {}).get("emoji", "")
        prepaid = online_info.get("prepaid")

        reason = (f"Luhn ✓ | ONLINE VERIFIED | {api_scheme} {api_type} | "
                  f"{api_bank} | {api_emoji} {api_country}"
                  + (" | PREPAID" if prepaid else ""))
        return ("LIVE", "✅", reason)

    # ── Layer 7: local DB match ──
    if local_info:
        scheme = local_info.get("scheme", "")
        ctype = local_info.get("type", "")
        bank = (local_info.get("bank") or {}).get("name", "Unknown")
        country = (local_info.get("country") or {}).get("name", "?")

        reason = (f"Luhn ✓ | {scheme} {ctype} | {bank} | {country} | "
                  "API unreachable — local DB only")
        return ("UNKNOWN", "⚠️", reason)

    # ── Layer 8: no BIN info at all ──
    return ("UNKNOWN", "⚠️", f"Luhn ✓ | {network} | BIN not in any database")


def format_card_spaced(number: str) -> str:
    return " ".join(number[i:i+4] for i in range(0, len(number), 4))


# ═════════════════════════════════════════════════════════════════════════════
#  ANIMATED CANVAS — checker spinner / result ring
# ═════════════════════════════════════════════════════════════════════════════

class AnimatedCanvas(ctk.CTkCanvas):
    def __init__(self, master, size=140, **kw):
        super().__init__(master, width=size, height=size,
                         bg=BG_DARK, highlightthickness=0, **kw)
        self.size = size
        self.cx = size // 2
        self.cy = size // 2
        self.r = size // 2 - 16
        self._angle = 0
        self._running = False
        self._result = None
        self._pulse = 0
        self._morph = 0.0
        self._particles: list = []

    def start_spinner(self):
        self._result = None
        self._running = True
        self._morph = 0.0
        self._particles = [
            {"a": random.uniform(0, math.tau),
             "r": random.uniform(25, 60),
             "sp": random.uniform(0.01, 0.04) * random.choice([-1, 1]),
             "s": random.uniform(1.5, 3.0),
             "al": random.uniform(0.15, 0.55)}
            for _ in range(25)
        ]
        self._tick()

    def _tick(self):
        if not self._running:
            return
        self._angle = (self._angle + 6) % 360
        self._pulse += 0.08
        self.delete("all")
        for p in self._particles:
            p["a"] += p["sp"]
            px = self.cx + math.cos(p["a"]) * p["r"]
            py = self.cy + math.sin(p["a"]) * p["r"]
            v = p["al"]
            c = f"#{int(88*v):02x}{int(166*v):02x}{int(255*v):02x}"
            self.create_oval(px-p["s"], py-p["s"], px+p["s"], py+p["s"],
                             fill=c, outline="")
        ph = 0.5 + 0.5 * math.sin(self._pulse)
        w = 4 + ph * 3
        ext = 90 + ph * 60
        pad = 16
        self.create_arc(pad, pad, self.size-pad, self.size-pad,
                        start=self._angle, extent=ext,
                        style="arc", outline=ACCENT, width=w)
        self.create_arc(pad, pad, self.size-pad, self.size-pad,
                        start=self._angle+180, extent=ext,
                        style="arc", outline=ACCENT_DIM, width=w)
        self.create_text(self.cx, self.cy, text="⏳",
                         font=("Segoe UI Emoji", 22), fill=TEXT_PRIMARY)
        self.after(16, self._tick)

    def show_result(self, kind: str):
        self._running = False
        self._result = kind
        self._morph = 0.0
        self._anim_result()

    def _anim_result(self):
        self._morph = min(self._morph + 0.045, 1.0)
        self._pulse += 0.06
        self._draw_result()
        if self._morph < 1.0:
            self.after(16, self._anim_result)
        else:
            self._idle()

    def _idle(self):
        if self._running:
            return
        self._pulse += 0.04
        self._draw_result()
        self.after(30, self._idle)

    def _draw_result(self):
        self.delete("all")
        c1, c3 = 1.70158, 2.70158
        t = 1 + c3 * pow(self._morph - 1, 3) + c1 * pow(self._morph - 1, 2)
        ph = 0.5 + 0.5 * math.sin(self._pulse)
        col = {"success": SUCCESS, "error": ERROR, "warning": WARNING}.get(self._result, ACCENT)
        ico = {"success": "✔", "error": "✖", "warning": "⚠"}.get(self._result, "?")
        rd = self.r * t
        gp = self.cx - rd - (8 + ph * 5)
        self.create_oval(gp, gp, self.size-gp, self.size-gp,
                         outline=col, width=2, dash=(4, 4))
        p2 = self.cx - rd
        self.create_oval(p2, p2, self.size-p2, self.size-p2,
                         outline=col, width=4 + ph * 2)
        fs = int(30 * t)
        if fs > 0:
            self.create_text(self.cx, self.cy, text=ico,
                             font=("Segoe UI Emoji", fs), fill=col)

    def reset(self):
        self._running = False
        self._result = None
        self.delete("all")


# ═════════════════════════════════════════════════════════════════════════════
#  SMALL SPINNER — used in generator tab
# ═════════════════════════════════════════════════════════════════════════════

class SmallSpinner(ctk.CTkCanvas):
    def __init__(self, master, size=50, **kw):
        super().__init__(master, width=size, height=size,
                         bg=BG_DARK, highlightthickness=0, **kw)
        self.size = size
        self._a = 0
        self._on = False

    def start(self):
        self._on = True
        self._spin()

    def stop(self):
        self._on = False
        self.delete("all")

    def _spin(self):
        if not self._on:
            return
        self._a = (self._a + 9) % 360
        self.delete("all")
        p = 8
        ph = 0.5 + 0.5 * math.sin(self._a * math.pi / 180)
        self.create_arc(p, p, self.size-p, self.size-p,
                        start=self._a, extent=70 + ph * 50,
                        style="arc", outline=ACCENT, width=3)
        self.after(16, self._spin)


# ═════════════════════════════════════════════════════════════════════════════
#  GENERATOR TAB
# ═════════════════════════════════════════════════════════════════════════════

class GeneratorTab(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._build()

    def _build(self):
        # ── Input section ────────────────────────────────────────────────
        inp = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=14,
                           border_width=1, border_color=BORDER)
        inp.pack(padx=20, fill="x", pady=(10, 0))
        inner = ctk.CTkFrame(inp, fg_color="transparent")
        inner.pack(padx=18, pady=16, fill="x")

        # BIN row
        r1 = ctk.CTkFrame(inner, fg_color="transparent")
        r1.pack(fill="x")
        ctk.CTkLabel(r1, text="BIN (first 6-8 digits)",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=TEXT_SECONDARY).pack(side="left")
        ctk.CTkLabel(r1, text="empty = random",
                     font=ctk.CTkFont("Segoe UI", 9),
                     text_color="#484f58").pack(side="right")

        self.bin_entry = ctk.CTkEntry(
            inner, height=40, corner_radius=8,
            font=ctk.CTkFont("Consolas", 14),
            placeholder_text="e.g. 411111",
            fg_color=BG_DARK, border_color=BORDER,
            text_color=TEXT_PRIMARY)
        self.bin_entry.pack(fill="x", pady=(4, 10))

        # Country selector
        cr = ctk.CTkFrame(inner, fg_color="transparent")
        cr.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(cr, text="Country",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=TEXT_SECONDARY).pack(side="left")
        ctk.CTkLabel(cr, text="overrides BIN if set",
                     font=ctk.CTkFont("Segoe UI", 9),
                     text_color="#484f58").pack(side="right")

        country_options = ["Random"] + COUNTRY_LIST
        self.country_var = ctk.StringVar(value="Random")
        self.country_menu = ctk.CTkOptionMenu(
            inner, values=country_options, variable=self.country_var,
            height=36, corner_radius=8,
            font=ctk.CTkFont("Segoe UI", 12),
            fg_color=BG_DARK, button_color=ACCENT_DIM,
            button_hover_color="#1f6feb",
            dropdown_fg_color=CARD_BG, dropdown_hover_color=ACCENT_DIM,
            text_color=TEXT_PRIMARY)
        self.country_menu.pack(fill="x", pady=(0, 10))

        # Amount
        ar = ctk.CTkFrame(inner, fg_color="transparent")
        ar.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(ar, text="Amount",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=TEXT_SECONDARY).pack(side="left")
        self.amt = ctk.StringVar(value="10")
        for v in ("10", "25", "50", "100"):
            ctk.CTkRadioButton(
                ar, text=v, variable=self.amt, value=v,
                font=ctk.CTkFont("Segoe UI", 11), text_color=TEXT_PRIMARY,
                fg_color=ACCENT, hover_color="#1f6feb", border_color=BORDER
            ).pack(side="left", padx=(12, 0))

        # Buttons row
        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x")

        self.gen_btn = ctk.CTkButton(
            btn_row, text="Generate", height=40, corner_radius=10,
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            fg_color=ACCENT, hover_color="#1f6feb",
            command=self._on_gen)
        self.gen_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.check_all_btn = ctk.CTkButton(
            btn_row, text="Check All", height=40, corner_radius=10,
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            fg_color="#238636", hover_color="#2ea043",
            command=self._on_check_all)
        self.check_all_btn.pack(side="left", expand=True, fill="x", padx=(6, 0))

        # Spinner + BIN info
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.pack(fill="x", padx=20)
        self.spinner = SmallSpinner(mid, size=40)
        self.spinner.pack(side="left", padx=(0, 8), pady=(6, 0))
        self.info_lbl = ctk.CTkLabel(mid, text="",
                                     font=ctk.CTkFont("Segoe UI", 10),
                                     text_color=TEXT_SECONDARY, wraplength=500,
                                     anchor="w", justify="left")
        self.info_lbl.pack(side="left", fill="x", expand=True, pady=(6, 0))

        # ── Output ───────────────────────────────────────────────────────
        out = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=14,
                           border_width=1, border_color=BORDER)
        out.pack(padx=20, fill="both", expand=True, pady=(6, 4))

        self.output = ctk.CTkTextbox(
            out, font=ctk.CTkFont("Consolas", 11),
            fg_color=BG_DARK, text_color=TEXT_PRIMARY,
            border_width=0, corner_radius=8, wrap="none")
        self.output.pack(padx=10, pady=10, fill="both", expand=True)

        # ── Bottom bar ───────────────────────────────────────────────────
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.pack(padx=20, fill="x", pady=(0, 8))
        self.status = ctk.CTkLabel(bot, text="Ready",
                                   font=ctk.CTkFont("Segoe UI", 10),
                                   text_color=TEXT_SECONDARY)
        self.status.pack(side="left")
        ctk.CTkButton(bot, text="Copy All", width=90, height=28, corner_radius=8,
                      font=ctk.CTkFont("Segoe UI", 11, "bold"),
                      fg_color="#30363d", hover_color="#484f58",
                      text_color=TEXT_PRIMARY,
                      command=self._copy).pack(side="right")

        self._generated_cards: list[dict] = []

    # ── generate ─────────────────────────────────────────────────────────
    def _on_gen(self):
        raw = self.bin_entry.get().strip().replace(" ", "").replace("-", "")
        country = self.country_var.get()

        if raw and (not raw.isdigit() or len(raw) < 4 or len(raw) > 8):
            self.status.configure(text="BIN must be 4-8 digits", text_color=ERROR)
            return
        self.gen_btn.configure(state="disabled", text="Generating…")
        self.check_all_btn.configure(state="disabled")
        self.output.delete("1.0", "end")
        self.info_lbl.configure(text="")
        self.status.configure(text="Working…", text_color=TEXT_SECONDARY)
        self.spinner.start()
        amount = int(self.amt.get())
        threading.Thread(target=self._gen, args=(raw, amount, country),
                         daemon=True).start()

    def _gen(self, user_bin: str, amount: int, country: str):
        # Priority: user BIN > country selection > random
        if user_bin:
            bin6 = user_bin[:6].ljust(6, "0")
            prefix = user_bin
        elif country != "Random" and country in _COUNTRY_BINS:
            prefix = random.choice(_COUNTRY_BINS[country])
            bin6 = prefix
        else:
            prefix = random.choice(_ALL_BINS)
            bin6 = prefix

        length = card_length_for_bin(bin6)
        network = detect_network(prefix)
        cvv_len = cvv_length_for_network(network)

        # BIN lookup (instant local)
        info = bin_lookup(bin6)
        if info:
            bank = (info.get("bank") or {}).get("name", "")
            c_name = (info.get("country") or {}).get("name", "")
            scheme = (info.get("scheme") or "").title()
            ctype = (info.get("type") or "").title()
            parts = [f"BIN {bin6}"]
            if scheme:  parts.append(scheme)
            if ctype:   parts.append(ctype)
            if bank:    parts.append(bank)
            if c_name:  parts.append(c_name)
            info_text = "  •  ".join(parts)
        else:
            info_text = f"BIN {bin6}  •  {network}"

        # Generate realistic cards
        cards = []
        seen = set()
        while len(cards) < amount:
            # If country mode, rotate through all BINs of that country
            if not user_bin and country != "Random" and country in _COUNTRY_BINS:
                c_bins = _COUNTRY_BINS[country]
                cur_bin = c_bins[len(cards) % len(c_bins)]
                cur_len = card_length_for_bin(cur_bin)
                cur_net = detect_network(cur_bin)
                cur_cvv = cvv_length_for_network(cur_net)
                num = generate_card_number(cur_bin, cur_len)
            else:
                num = generate_card_number(prefix, length)
                cur_net = network
                cur_cvv = cvv_len

            if num in seen:
                continue
            seen.add(num)
            cards.append({
                "number": num,
                "expiry": generate_expiry(),
                "cvv":    generate_cvv(cur_cvv),
                "name":   generate_holder_name(),
                "network": cur_net,
            })

        # Format output — realistic pipe-delimited
        header = f"{'#':>3}   {'Card Number':<23} {'Exp':>5}  {'CVV':>4}  {'Holder Name'}"
        sep    = "─" * len(header)
        lines  = [header, sep]
        for i, c in enumerate(cards, 1):
            lines.append(
                f"{i:>3}.  {format_card_spaced(c['number']):<23} "
                f"{c['expiry']:>5}  {c['cvv']:>4}  {c['name']}"
            )

        text = "\n".join(lines)
        self._generated_cards = cards
        self.after(0, lambda: self._show(text, info_text, amount, network))

    def _show(self, text, info_text, count, network):
        self.spinner.stop()
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.info_lbl.configure(text=info_text)
        self.status.configure(
            text=f"Generated {count} {network} cards ✓", text_color=SUCCESS)
        self.gen_btn.configure(state="normal", text="Generate")
        self.check_all_btn.configure(state="normal")

    # ── check all generated cards (real per-card validation) ───────────
    def _on_check_all(self):
        if not self._generated_cards:
            self.status.configure(text="Generate cards first", text_color=WARNING)
            return
        self.check_all_btn.configure(state="disabled", text="Checking…")
        self.gen_btn.configure(state="disabled")
        self.spinner.start()
        self.output.delete("1.0", "end")
        self.status.configure(text="Checking all cards…", text_color=TEXT_SECONDARY)
        threading.Thread(target=self._check_all_worker, daemon=True).start()

    def _check_all_worker(self):
        total = len(self._generated_cards)
        # Cache lookups per BIN6 — both local and online
        local_cache: dict[str, dict | None] = {}
        online_cache: dict[str, dict | None] = {}
        results = []
        live = 0
        dead = 0
        unknown = 0

        for idx, c in enumerate(self._generated_cards):
            num = c["number"]
            bin6 = num[:6]

            # Local DB lookup (instant, cached)
            if bin6 not in local_cache:
                local_cache[bin6] = bin_lookup(bin6)
            local_info = local_cache[bin6]

            # Online BIN verification (rate-limited, cached)
            if bin6 not in online_cache:
                online_cache[bin6] = online_bin_verify(bin6)
                time.sleep(0.35)  # rate limit: ~3 req/sec for binlist.net
            online_info = online_cache[bin6]

            # Deep multi-layer validation
            status, status_icon, reason = validate_card_deep(
                num, c["expiry"], c["cvv"], local_info, online_info)

            if status == "LIVE":
                live += 1
            elif status == "DEAD":
                dead += 1
            else:
                unknown += 1

            results.append({
                "idx": idx + 1,
                "num": num,
                "exp": c["expiry"],
                "cvv": c["cvv"],
                "name": c["name"],
                "status": status,
                "icon": status_icon,
                "reason": reason,
            })

            # Live update the UI every card
            progress = idx + 1
            self.after(0, lambda p=progress, r=list(results), lv=live, dd=dead, unk=unknown:
                       self._update_check_progress(r, p, total, lv, dd, unk))

        # Final update
        self.after(0, lambda: self._finish_check(results, live, dead, unknown, total))

    def _update_check_progress(self, results, progress, total, live, dead, unknown=0):
        header = f"{'#':>3}  {'Status':<8}  {'Card Number':<23} {'Exp':>5}  {'CVV':>4}  {'Name':<20} Details"
        sep = "─" * 120
        lines = [header, sep]
        for r in results:
            lines.append(
                f"{r['idx']:>3}. {r['icon']}{r['status']:<7}  "
                f"{format_card_spaced(r['num']):<23} "
                f"{r['exp']:>5}  {r['cvv']:>4}  {r['name']:<20} {r['reason']}"
            )

        self.output.delete("1.0", "end")
        self.output.insert("1.0", "\n".join(lines))
        self.output.see("end")
        self.status.configure(
            text=f"Checking {progress}/{total}  •  ✅ {live} live  •  ❌ {dead} dead  •  ⚠️ {unknown} unknown",
            text_color=TEXT_SECONDARY)

    def _finish_check(self, results, live, dead, unknown, total):
        self.spinner.stop()
        # Append summary
        sep = "─" * 120
        rate = live / total * 100 if total > 0 else 0
        summary = (
            f"\n{sep}\n"
            f"  RESULTS:  ✅ {live} LIVE  •  ❌ {dead} DEAD  •  "
            f"⚠️ {unknown} UNKNOWN  •  Total: {total}  •  "
            f"Verified rate: {rate:.1f}%"
        )
        self.output.insert("end", summary)
        self.output.see("end")

        if live > 0 and dead == 0 and unknown == 0:
            col = SUCCESS
        elif dead > 0:
            col = ERROR
        else:
            col = WARNING
        self.status.configure(
            text=f"Done — ✅ {live} live  •  ❌ {dead} dead  •  ⚠️ {unknown} unknown  •  {rate:.1f}%",
            text_color=col)
        self.check_all_btn.configure(state="normal", text="Check All")
        self.gen_btn.configure(state="normal")

    # ── copy ─────────────────────────────────────────────────────────────
    def _copy(self):
        if not self._generated_cards:
            return
        lines = []
        for c in self._generated_cards:
            lines.append(f"{c['number']}|{c['expiry']}|{c['cvv']}|{c['name']}")
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self.status.configure(text="Copied to clipboard ✓", text_color=SUCCESS)


# ═════════════════════════════════════════════════════════════════════════════
#  CHECKER TAB
# ═════════════════════════════════════════════════════════════════════════════

class CheckerTab(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._build()

    def _build(self):
        # Input card
        inp = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=14,
                           border_width=1, border_color=BORDER)
        inp.pack(padx=20, fill="x", pady=(10, 0))
        inner = ctk.CTkFrame(inp, fg_color="transparent")
        inner.pack(padx=18, pady=16, fill="x")

        ctk.CTkLabel(inner, text="Card Number",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=TEXT_SECONDARY, anchor="w").pack(fill="x")

        self.entry = ctk.CTkEntry(
            inner, height=44, corner_radius=10,
            font=ctk.CTkFont("Consolas", 15),
            placeholder_text="Enter card number…",
            fg_color=BG_DARK, border_color=BORDER,
            text_color=TEXT_PRIMARY)
        self.entry.pack(fill="x", pady=(4, 12))
        self.entry.bind("<Return>", lambda e: self._on_check())

        self.btn = ctk.CTkButton(
            inner, text="Check Card", height=42, corner_radius=10,
            font=ctk.CTkFont("Segoe UI", 14, "bold"),
            fg_color=ACCENT, hover_color="#1f6feb",
            command=self._on_check)
        self.btn.pack(fill="x")

        ctk.CTkLabel(self, text="Luhn + length + online BIN verification",
                     font=ctk.CTkFont("Segoe UI", 9),
                     text_color="#484f58").pack(pady=(6, 0))

        # Canvas
        self.canvas = AnimatedCanvas(self, size=150)
        self.canvas.pack(pady=(10, 0))

        # Result
        self.result_frame = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=14,
                                         border_width=1, border_color=BORDER)
        self.result_frame.pack(padx=20, fill="x", pady=(10, 10))
        self.result_frame.pack_forget()

    def _on_check(self):
        card = self.entry.get().strip().replace(" ", "").replace("-", "")
        if not card:
            return
        self.btn.configure(state="disabled", text="Checking…")
        self.entry.configure(state="disabled")
        self.result_frame.pack_forget()
        self.canvas.reset()
        self.canvas.start_spinner()
        threading.Thread(target=self._check, args=(card,), daemon=True).start()

    def _check(self, card: str):
        if not card.isdigit() or len(card) < 12 or len(card) > 19:
            self.after(0, lambda: self._result("error", "Invalid Format ✖",
                "Card number must be 12-19 digits."))
            return

        if not luhn_check(card):
            net = detect_network(card)
            self.after(0, lambda: self._result("error", "Invalid Card ✖",
                f"Network: {net}\nLuhn checksum: FAILED\n\n"
                "This number is mathematically invalid."))
            return

        net = detect_network(card)

        # Card length check
        expected_len = 15 if net == "Amex" else 16
        if len(card) != expected_len:
            self.after(0, lambda: self._result("error", "Invalid Length ✖",
                f"Network: {net}\nLength: {len(card)} (expected {expected_len})\n\n"
                "Card length doesn't match the detected network."))
            return

        # Local DB lookup
        local_info = bin_lookup(card)

        # Online BIN verification (live API call)
        bin6 = card[:6]
        online_info = online_bin_verify(bin6)

        if online_info:
            scheme = (online_info.get("scheme") or "").title()
            ctype  = (online_info.get("type") or "unknown").title()
            brand  = online_info.get("brand") or ""
            prepaid = online_info.get("prepaid")
            country = (online_info.get("country") or {})
            bank    = (online_info.get("bank") or {})
            lines = [
                f"Network: {net}" + (f" ({scheme})" if scheme and scheme.lower() != net.lower() else ""),
                f"Card type: {ctype}" + (f"  •  Brand: {brand}" if brand else ""),
                f"Prepaid: {'Yes' if prepaid else 'No' if prepaid is not None else 'N/A'}",
                f"Issuing bank: {bank.get('name', 'Unknown')}",
                f"Country: {country.get('emoji', '')} {country.get('name', 'Unknown')}",
                f"Luhn checksum: PASSED ✓",
                f"BIN verification: ONLINE ✓",
            ]
            if prepaid:
                kind, title = "warning", "Valid — Prepaid ⚠"
            else:
                kind, title = "success", "Valid Card ✓"
            self.after(0, lambda: self._result(kind, title, "\n".join(lines)))
        elif local_info:
            scheme = local_info.get("scheme", "")
            ctype  = local_info.get("type", "")
            bank   = (local_info.get("bank") or {}).get("name", "Unknown")
            country = (local_info.get("country") or {}).get("name", "Unknown")
            lines = [
                f"Network: {net} ({scheme})",
                f"Card type: {ctype}",
                f"Issuing bank: {bank}",
                f"Country: {country}",
                f"Luhn checksum: PASSED ✓",
                f"BIN verification: LOCAL DB ONLY (API unreachable)",
            ]
            self.after(0, lambda: self._result("warning", "Valid — Unverified ⚠",
                "\n".join(lines)))
        else:
            self.after(0, lambda: self._result("warning", "Valid — Limited Info ⚠",
                f"Network: {net}\nLuhn: PASSED ✓\n\n"
                "BIN not found in any database.\n"
                "Online API unreachable."))

    def _result(self, kind, title, detail):
        col = {"success": SUCCESS, "error": ERROR, "warning": WARNING}[kind]
        ico = {"success": "✅", "error": "❌", "warning": "⚠️"}[kind]

        self.canvas.show_result(kind)

        for w in self.result_frame.winfo_children():
            w.destroy()
        self.result_frame.configure(border_color=col)

        pad = ctk.CTkFrame(self.result_frame, fg_color="transparent")
        pad.pack(padx=18, pady=14, fill="x")
        ctk.CTkLabel(pad, text=f"{ico}  {title}",
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=col).pack(anchor="w")
        ctk.CTkLabel(pad, text=detail,
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=TEXT_SECONDARY,
                     wraplength=460, justify="left").pack(anchor="w", pady=(4, 0))

        self.result_frame.pack(padx=20, fill="x", pady=(10, 10))

        self.btn.configure(state="normal", text="Check Card")
        self.entry.configure(state="normal")
        self.entry.delete(0, "end")
        self.entry.focus()


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ═════════════════════════════════════════════════════════════════════════════

class CardToolApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Card Tool — Generator & Checker")
        self.geometry("680x880")
        self.minsize(620, 720)
        self.configure(fg_color=BG_DARK)

        # Header
        ctk.CTkLabel(self, text="💳  Card Tool",
                     font=ctk.CTkFont("Segoe UI", 24, "bold"),
                     text_color=TEXT_PRIMARY).pack(pady=(18, 2))
        ctk.CTkLabel(self, text="Generate realistic cards  •  Validate with Luhn + BIN lookup",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=TEXT_SECONDARY).pack(pady=(0, 10))

        # Tabs
        self.tabs = ctk.CTkTabview(self, fg_color=CARD_BG,
                                   segmented_button_fg_color=SURFACE,
                                   segmented_button_selected_color=ACCENT,
                                   segmented_button_unselected_color="#21262d",
                                   segmented_button_selected_hover_color="#1f6feb",
                                   corner_radius=14)
        self.tabs.pack(padx=18, fill="both", expand=True, pady=(0, 14))

        gen_tab = self.tabs.add("🃏  Generator")
        chk_tab = self.tabs.add("🔍  Checker")

        GeneratorTab(gen_tab).pack(fill="both", expand=True)
        CheckerTab(chk_tab).pack(fill="both", expand=True)


if __name__ == "__main__":
    CardToolApp().mainloop()
