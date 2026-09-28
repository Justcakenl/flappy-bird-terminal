#!/usr/bin/env python3
"""Flappy Bird for the terminal.

Space flaps, p pauses, q quits. Requires nothing beyond the standard library.
"""

import argparse
import curses
import json
import math
import os
import random
import sys
import time

__version__ = "1.2.0"

# Vertical motion is a multiple of the playfield height, so a 24-row window
# plays like a 60-row one. Horizontal motion is in columns per second.
GRAVITY = 3.85
FLAP_SPEED = 1.00
MAX_FALL = 1.90
DEATH_HOP = 0.35

STEP = 1.0 / 240.0
MAX_CATCHUP = 0.10
GRACE = 0.30

PIPE_WIDTH = 4
CAP_OVERHANG = 1
GAP_START = 0.255
GAP_FLOOR = 0.190
GAP_DECAY = 0.0026
GAP_MIN_ROWS = 3.0

# Difficulty is set by two intents rather than by tuning speed and spacing
# apart: a pipe crosses the whole window in SCREEN_SWEEP seconds, and one
# arrives every PIPE_PERIOD seconds. Spacing follows from both, so the game is
# as hard in an 80-column window as in a 200-column one.
SCREEN_SWEEP = 3.4
PIPE_PERIOD = 0.95
SPEED_FLOOR = 17.0
SPEED_GROWTH = 0.014
SPEED_CEILING = 1.80
SPACING_MIN = PIPE_WIDTH + 2 * CAP_OVERHANG + 4

BIRD_COLUMN = 0.22
BIRD_WIDTH = 3
BIRD_RADIUS = 0.40

BAR_ROWS = 1
GROUND_ROWS = 2
MIN_COLS = 32
MIN_ROWS = 12

MEDALS = ((40, "PLATINUM"), (30, "GOLD"), (20, "SILVER"), (10, "BRONZE"))
WINGS = ("^", "-", "v")

GLYPHS = {
    "wall": "│",
    "fill": "▒",
    "cap": "═",
    "cap_left": "╞",
    "cap_right": "╡",
    "ground": "═",
    "soil": "▒",
    "grit": "░",
    "clod": "▓",
    "speck": ".",
    "body": "@",
    "beak": ">",
    "hbar": "═",
    "vbar": "║",
    "tl": "╔",
    "tr": "╗",
    "bl": "╚",
    "br": "╝",
}
ASCII_GLYPHS = {
    "wall": "|",
    "fill": ":",
    "cap": "=",
    "cap_left": "+",
    "cap_right": "+",
    "ground": "=",
    "soil": ":",
    "grit": ".",
    "clod": "#",
    "speck": ".",
    "body": "@",
    "beak": ">",
    "hbar": "=",
    "vbar": "|",
    "tl": "+",
    "tr": "+",
    "bl": "+",
    "br": "+",
}

# Phosphor palettes: four intensities, the way a monochrome CRT had them.
LEVELS = ("faint", "dim", "normal", "bright")
PALETTES = {
    "green": {"faint": 22, "dim": 28, "normal": 40, "bright": 46},
    "amber": {"faint": 94, "dim": 136, "normal": 178, "bright": 214},
}
BASE_COLOR = {"green": curses.COLOR_GREEN, "amber": curses.COLOR_YELLOW}

# Role to intensity, plus attributes that survive every colour mode.
STYLE = {
    "wall": ("normal", 0),
    "fill": ("dim", 0),
    "cap": ("bright", curses.A_BOLD),
    "ground": ("normal", 0),
    "soil": ("dim", 0),
    "grit": ("faint", 0),
    "clod": ("dim", 0),
    "speck": ("faint", 0),
    "wing": ("normal", 0),
    "body": ("bright", curses.A_BOLD),
    "beak": ("normal", curses.A_BOLD),
    "bar": ("normal", curses.A_REVERSE),
    "bar_hit": ("bright", curses.A_REVERSE | curses.A_BOLD),
    "frame": ("dim", 0),
    "text": ("normal", 0),
    "muted": ("dim", 0),
    "accent": ("bright", curses.A_BOLD),
    "alert": ("bright", curses.A_REVERSE | curses.A_BOLD),
    "medal": ("bright", curses.A_BOLD),
}


def clamp(value, low, high):
    return low if value < low else (high if value > high else value)


class Theme:
    """Glyph set plus a role-to-attribute table, built once per session.

    With colors=0 only the plain attributes survive, which is the mode the
    offline renderer and the tests run in.
    """

    def __init__(self, colors=0, ascii_only=False, palette="green"):
        self.glyph = ASCII_GLYPHS if ascii_only else GLYPHS
        shade = dict.fromkeys(LEVELS, 0)
        if colors:
            background = -1
            try:
                curses.init_pair(1, curses.COLOR_WHITE, -1)
            except curses.error:
                background = curses.COLOR_BLACK
            indices = PALETTES[palette]
            fallback = BASE_COLOR[palette]
            for pair, level in enumerate(LEVELS, start=1):
                attr = curses.A_BOLD if level == "bright" and colors < 256 else 0
                try:
                    curses.init_pair(pair, indices[level] if colors >= 256 else fallback,
                                     background)
                    attr |= curses.color_pair(pair)
                except curses.error:
                    pass
                shade[level] = attr
        self.attr = {role: shade[level] | extra for role, (level, extra) in STYLE.items()}


class Canvas:
    """A character grid with attributes, flushed to curses in colour runs."""

    def __init__(self, rows, cols):
        self.rows = rows
        self.cols = cols
        self.chars = [[" "] * cols for _ in range(rows)]
        self.attrs = [[0] * cols for _ in range(rows)]

    def clear(self):
        for y in range(self.rows):
            self.chars[y] = [" "] * self.cols
            self.attrs[y] = [0] * self.cols

    def fill(self, top, bottom, left, right, char, attr):
        left = max(0, left)
        right = min(self.cols - 1, right)
        top = max(0, top)
        bottom = min(self.rows - 1, bottom)
        if right < left or bottom < top:
            return
        span = right - left + 1
        for y in range(top, bottom + 1):
            self.chars[y][left:right + 1] = [char] * span
            self.attrs[y][left:right + 1] = [attr] * span

    def write(self, y, x, text, attr):
        if not 0 <= y < self.rows:
            return
        chars, attrs = self.chars[y], self.attrs[y]
        for offset, char in enumerate(text):
            column = x + offset
            if 0 <= column < self.cols:
                chars[column] = char
                attrs[column] = attr

    def blit(self, window):
        for y in range(self.rows):
            chars, attrs = self.chars[y], self.attrs[y]
            # Writing the bottom-right cell makes curses scroll and raise.
            limit = self.cols - 1 if y == self.rows - 1 else self.cols
            x = 0
            while x < limit:
                attr = attrs[x]
                end = x + 1
                while end < limit and attrs[end] == attr:
                    end += 1
                try:
                    window.addstr(y, x, "".join(chars[x:end]), attr)
                except curses.error:
                    pass
                x = end

    def __str__(self):
        return "\n".join("".join(row) for row in self.chars)


class Scores:
    """Best score and totals, kept in the XDG data directory."""

    FIELDS = ("best", "games", "total")

    def __init__(self, path=None):
        if path is None:
            root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
            path = os.path.join(root, "flappy", "scores.json")
        self.path = path
        self.data = dict.fromkeys(self.FIELDS, 0)
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                stored = json.load(handle)
        except (OSError, ValueError):
            return self.data
        if isinstance(stored, dict):
            for field in self.FIELDS:
                value = stored.get(field)
                if type(value) is int and 0 <= value < 10 ** 9:
                    self.data[field] = value
        return self.data

    def record(self, score):
        """Add one finished round. Returns True on a new best."""
        beaten = score > self.data["best"]
        if beaten:
            self.data["best"] = score
        self.data["games"] += 1
        self.data["total"] += score
        self.save()
        return beaten

    def save(self):
        scratch = self.path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(scratch, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle)
            os.replace(scratch, self.path)
        except OSError:
            pass

    def clear(self):
        self.data = dict.fromkeys(self.FIELDS, 0)
        self.save()


class Pipe:
    __slots__ = ("x", "gap_top", "gap", "counted")

    def __init__(self, x, gap_top, gap):
        self.x = x                # left edge, columns, fractional
        self.gap_top = gap_top    # top of the opening, playfield rows
        self.gap = gap            # opening height in rows
        self.counted = False


TITLE, READY, FLYING, FALLING, DEAD = range(5)


class Game:
    def __init__(self, theme, rows, cols, best=0, hard=False, seed=None):
        self.theme = theme
        self.best = best
        self.hard = hard
        self.random = random.Random(seed)
        self.state = TITLE
        self.score = 0
        self.clock = 0.0
        self.since_death = 0.0
        self.hit_glow = 0.0
        self.beat_best = False
        self.paused = False
        self.unsaved = None
        self.pipes = []
        self.specks = []
        self.scroll = 0.0
        self.measure(rows, cols)
        self.bird_y = self.field * 0.42
        self.bird_v = 0.0

    def measure(self, rows, cols):
        self.rows = rows
        self.cols = cols
        self.cramped = rows < MIN_ROWS or cols < MIN_COLS
        self.top = BAR_ROWS
        self.field = max(1, rows - BAR_ROWS - GROUND_ROWS)
        self.ground = rows - GROUND_ROWS
        self.bird_x = max(2, int(cols * BIRD_COLUMN))
        self.base_speed = max(SPEED_FLOOR, cols / SCREEN_SWEEP)
        if self.hard:
            self.base_speed *= 1.20
        self.spacing = max(SPACING_MIN, round(self.base_speed * PIPE_PERIOD))
        self.scatter_specks()

    def resize(self, rows, cols):
        """Keep the round alive across a window change by rescaling the world."""
        was_cols, was_field = self.cols, self.field
        self.measure(rows, cols)
        if was_field > 0 and self.field != was_field:
            scale = self.field / was_field
            self.bird_y = clamp(self.bird_y * scale, BIRD_RADIUS,
                                max(BIRD_RADIUS, self.field - BIRD_RADIUS))
            self.bird_v *= scale
            for pipe in self.pipes:
                pipe.gap = clamp(pipe.gap * scale, GAP_MIN_ROWS, max(GAP_MIN_ROWS, self.field))
                pipe.gap_top = clamp(pipe.gap_top * scale, 0.0,
                                     max(0.0, self.field - pipe.gap))
        if was_cols > 0 and cols != was_cols:
            scale = cols / was_cols
            for pipe in self.pipes:
                pipe.x *= scale
        self.pipes = [pipe for pipe in self.pipes if pipe.x + PIPE_WIDTH > 0]

    def scatter_specks(self):
        self.specks = []
        if self.field < 4:
            return
        for _ in range(max(3, self.cols // 14)):
            self.specks.append([self.random.uniform(0, self.cols),
                                self.random.randrange(0, self.field - 1)])

    @property
    def speed(self):
        return self.base_speed * min(SPEED_CEILING, 1.0 + SPEED_GROWTH * self.score)

    @property
    def gravity(self):
        return GRAVITY * self.field

    def gap_size(self):
        bonus = 0.05 if self.hard else 0.0
        share = max(GAP_FLOOR - bonus / 2, GAP_START - bonus - GAP_DECAY * self.score)
        return max(GAP_MIN_ROWS, self.field * share)

    def flap(self):
        if self.state in (TITLE, DEAD):
            self.restart()
            return
        if self.state == READY:
            self.state = FLYING
            self.pipes = [self.make_pipe(self.cols + 4.0)]
        if self.state == FLYING:
            self.bird_v = -FLAP_SPEED * self.field

    def restart(self):
        self.state = READY
        self.score = 0
        self.pipes = []
        self.bird_y = self.field * 0.42
        self.bird_v = 0.0
        self.hit_glow = 0.0
        self.beat_best = False
        self.paused = False
        self.unsaved = None

    def toggle_pause(self):
        if self.state in (READY, FLYING):
            self.paused = not self.paused

    def make_pipe(self, x):
        gap = min(self.gap_size(), max(GAP_MIN_ROWS, self.field - 2.0), float(self.field))
        low, high = 1.0, self.field - gap - 1.0
        if high < low:
            low = high = max(0.0, (self.field - gap) * 0.5)
        if self.pipes:
            reach = self.field * 0.42
            previous = self.pipes[-1].gap_top
            near_low, near_high = max(low, previous - reach), min(high, previous + reach)
            if near_high >= near_low:
                low, high = near_low, near_high
        return Pipe(x, self.random.uniform(low, high), gap)

    def advance(self, dt):
        self.clock += dt
        if self.cramped or self.paused:
            return
        if self.state in (FLYING, FALLING):
            self.scroll += self.speed * dt
        self.drift_specks(dt)
        if self.hit_glow > 0.0:
            self.hit_glow = max(0.0, self.hit_glow - dt)

        if self.state in (TITLE, READY):
            hover = math.sin(self.clock * 4.0) * min(0.9, self.field * 0.06)
            self.bird_y = clamp(self.field * 0.42 + hover, BIRD_RADIUS,
                                max(BIRD_RADIUS, self.field - BIRD_RADIUS))
            self.bird_v = 0.0
            return
        if self.state == DEAD:
            self.since_death += dt
            return

        self.bird_v = clamp(self.bird_v + self.gravity * dt,
                            -MAX_FALL * self.field, MAX_FALL * self.field)
        self.bird_y += self.bird_v * dt

        if self.state == FALLING:
            if self.bird_y + BIRD_RADIUS >= self.field:
                self.bird_y = self.field - BIRD_RADIUS
                self.bird_v = 0.0
                self.settle()
            return

        # The ceiling stops the bird instead of killing it, as in the original.
        if self.bird_y - BIRD_RADIUS < 0.0:
            self.bird_y = BIRD_RADIUS
            self.bird_v = max(0.0, self.bird_v)

        if self.bird_y + BIRD_RADIUS >= self.field:
            self.bird_y = self.field - BIRD_RADIUS
            self.crash(grounded=True)
            return

        for pipe in self.pipes:
            pipe.x -= self.speed * dt
        if self.pipes and self.pipes[-1].x <= self.cols - self.spacing:
            self.pipes.append(self.make_pipe(self.pipes[-1].x + self.spacing))
        if self.pipes and self.pipes[0].x + PIPE_WIDTH + CAP_OVERHANG < -1:
            self.pipes.pop(0)

        nose = float(self.bird_x)
        tail = float(self.bird_x + BIRD_WIDTH)
        for pipe in self.pipes:
            if not pipe.counted and pipe.x + PIPE_WIDTH <= nose:
                pipe.counted = True
                self.score += 1
            if nose < pipe.x + PIPE_WIDTH and pipe.x < tail:
                above = self.bird_y - BIRD_RADIUS < pipe.gap_top
                below = self.bird_y + BIRD_RADIUS > pipe.gap_top + pipe.gap
                if above or below:
                    self.crash()
                    return

    def drift_specks(self, dt):
        step = self.base_speed * 0.30 * dt
        for speck in self.specks:
            speck[0] -= step
            if speck[0] < 0:
                speck[0] = self.cols + self.random.uniform(0, 12)
                speck[1] = self.random.randrange(0, max(1, self.field - 1))

    def crash(self, grounded=False):
        self.hit_glow = 0.35
        self.unsaved = self.score
        if grounded:
            self.bird_v = 0.0
            self.settle()
        else:
            self.state = FALLING
            self.bird_v = -DEATH_HOP * self.field

    def settle(self):
        self.state = DEAD
        self.since_death = 0.0
        final = self.score if self.unsaved is None else self.unsaved
        self.beat_best = final > self.best
        if self.beat_best:
            self.best = final

    # -- drawing ----------------------------------------------------------

    def draw(self, canvas):
        canvas.clear()
        if self.cramped:
            self.draw_cramped(canvas)
            return
        self.draw_specks(canvas)
        self.draw_pipes(canvas)
        self.draw_ground(canvas)
        self.draw_bird(canvas)
        self.draw_bar(canvas)
        if self.paused:
            self.dialog(canvas, "PAUSED",
                        [("[P]  RESUME", "muted"), ("[Q]  QUIT", "muted")])
        elif self.state == TITLE:
            self.draw_title(canvas)
        elif self.state == DEAD:
            self.draw_result(canvas)

    def draw_cramped(self, canvas):
        attr = self.theme.attr["text"]
        lines = (f"WINDOW TOO SMALL: {self.cols}x{self.rows}",
                 f"NEEDS AT LEAST {MIN_COLS}x{MIN_ROWS}")
        for offset, line in enumerate(lines):
            y = max(0, canvas.rows // 2 - 1) + offset
            canvas.write(y, max(0, (canvas.cols - len(line)) // 2), line[:canvas.cols], attr)

    def draw_specks(self, canvas):
        glyph = self.theme.glyph["speck"]
        attr = self.theme.attr["speck"]
        for x, y in self.specks:
            canvas.write(self.top + y, int(x), glyph, attr)

    def draw_pipes(self, canvas):
        glyph = self.theme.glyph
        attr = self.theme.attr
        first = self.top
        last = self.top + self.field - 1
        for pipe in self.pipes:
            left = int(math.floor(pipe.x))
            right = left + PIPE_WIDTH - 1
            if right + CAP_OVERHANG < 0 or left - CAP_OVERHANG >= self.cols:
                continue
            # A cell only partly covered by a pipe is drawn solid: the game
            # looks stricter than the hitbox is, never the other way round.
            upper = self.top + int(math.ceil(pipe.gap_top)) - 1
            lower = self.top + int(math.floor(pipe.gap_top + pipe.gap))
            for top, bottom in ((first, min(upper, last)), (max(lower, first), last)):
                if bottom < top:
                    continue
                canvas.fill(top, bottom, left + 1, right - 1, glyph["fill"], attr["fill"])
                canvas.fill(top, bottom, left, left, glyph["wall"], attr["wall"])
                canvas.fill(top, bottom, right, right, glyph["wall"], attr["wall"])
            for row in (upper, lower):
                if first <= row <= last:
                    canvas.fill(row, row, left, right, glyph["cap"], attr["cap"])
                    canvas.write(row, left - CAP_OVERHANG, glyph["cap_left"], attr["cap"])
                    canvas.write(row, right + CAP_OVERHANG, glyph["cap_right"], attr["cap"])

    def draw_ground(self, canvas):
        glyph = self.theme.glyph
        attr = self.theme.attr
        surface, earth = self.ground, self.ground + 1
        canvas.fill(surface, surface, 0, self.cols - 1, glyph["ground"], attr["ground"])
        canvas.fill(earth, canvas.rows - 1, 0, self.cols - 1, glyph["soil"], attr["soil"])
        shift = int(self.scroll)
        for x in range(self.cols):
            phase = (x + shift) % 12
            if phase < 3:
                canvas.write(earth, x, glyph["grit"], attr["grit"])
            elif phase == 7:
                canvas.write(earth, x, glyph["clod"], attr["clod"])

    def draw_bird(self, canvas):
        glyph = self.theme.glyph
        attr = self.theme.attr
        y = self.top + int(clamp(self.bird_y, 0, self.field - 1))
        if self.state in (TITLE, READY):
            wing = WINGS[1]
        elif self.bird_v < -self.field * 0.15:
            wing = WINGS[0]
        elif self.bird_v > self.field * 0.35:
            wing = WINGS[2]
        else:
            wing = WINGS[1]
        canvas.write(y, self.bird_x, wing, attr["wing"])
        canvas.write(y, self.bird_x + 1, glyph["body"], attr["body"])
        canvas.write(y, self.bird_x + 2, glyph["beak"], attr["beak"])

    def draw_bar(self, canvas):
        attr = self.theme.attr["bar_hit" if self.hit_glow > 0.0 else "bar"]
        canvas.fill(0, 0, 0, self.cols - 1, " ", attr)
        left = f" FLAPPY   SCORE {self.score}   BEST {self.best}"
        canvas.write(0, 0, left[:self.cols], attr)
        keys = "[SPACE] FLAP  [P] PAUSE  [Q] QUIT "
        if len(left) + len(keys) + 2 <= self.cols:
            canvas.write(0, self.cols - len(keys), keys, attr)

    def draw_title(self, canvas):
        arrow = "UP" if self.theme.glyph is ASCII_GLYPHS else "↑"
        self.dialog(canvas, "FLAPPY", [
            (f"[SPACE] [{arrow}] [W]   FLAP", "text"),
            ("[P]             PAUSE", "muted"),
            ("[Q]             QUIT", "muted"),
            ("", "text"),
            ("PRESS SPACE TO START", "accent", True),
        ])

    def draw_result(self, canvas):
        medal = next((name for need, name in MEDALS if self.score >= need), None)
        lines = [(f"SCORE   {self.score}", "text"),
                 (f"BEST    {self.best}", "muted")]
        if medal:
            lines.append((f"MEDAL   {medal}", "medal"))
        if self.beat_best:
            lines.append(("NEW RECORD", "accent"))
        lines += [("", "text"), ("[SPACE] RETRY   [Q] QUIT", "muted", True)]
        self.dialog(canvas, "GAME OVER", lines)

    def dialog(self, canvas, title, lines):
        glyph = self.theme.glyph
        frame = self.theme.attr["frame"]
        widest = max(len(text) for text, *_ in lines)
        inner = clamp(max(widest + 4, len(title) + 8), 4, max(4, self.cols - 2))
        width, height = inner + 2, len(lines) + 2
        x = max(0, (self.cols - width) // 2)
        y = max(0, (self.rows - height) // 2)
        canvas.fill(y, y + height - 1, x, x + width - 1, " ", self.theme.attr["text"])
        header = f"[ {title} ]"
        if len(header) + 4 <= inner:
            rule = glyph["hbar"]
            lead = 2
            top = glyph["tl"] + rule * lead + header + rule * (inner - lead - len(header))
            canvas.write(y, x, top + glyph["tr"], frame)
            canvas.write(y, x + 1 + lead, header, self.theme.attr["accent"])
        else:
            canvas.write(y, x, glyph["tl"] + glyph["hbar"] * inner + glyph["tr"], frame)
        canvas.write(y + height - 1, x,
                     glyph["bl"] + glyph["hbar"] * inner + glyph["br"], frame)
        for row in range(1, height - 1):
            canvas.write(y + row, x, glyph["vbar"], frame)
            canvas.write(y + row, x + width - 1, glyph["vbar"], frame)
        for offset, line in enumerate(lines):
            text, style = line[0], line[1]
            centred = len(line) > 2 and line[2]
            text = text[:inner - 2]
            indent = 1 + (inner - len(text)) // 2 if centred else 2
            canvas.write(y + 1 + offset, x + indent, text, self.theme.attr[style])


FLAP_KEYS = frozenset({ord(" "), ord("w"), ord("W"), ord("k"), ord("K"),
                       curses.KEY_UP, 10, 13, curses.KEY_ENTER})
QUIT_KEYS = frozenset({ord("q"), ord("Q"), 27})
PAUSE_KEYS = frozenset({ord("p"), ord("P")})
RESTART_KEYS = frozenset({ord("r"), ord("R")})


def detect_colors(disabled):
    if disabled:
        return 0
    try:
        if not curses.has_colors():
            return 0
        curses.start_color()
        try:
            curses.use_default_colors()
        except curses.error:
            pass
        return 256 if curses.COLORS >= 256 else 8
    except curses.error:
        return 0


def play(screen, options, scores):
    curses.noecho()
    curses.cbreak()
    screen.keypad(True)
    screen.nodelay(True)
    try:
        curses.curs_set(0)
    except curses.error:
        pass

    ascii_only = options.ascii or "utf" not in (
        getattr(sys.stdout, "encoding", "") or "").lower()
    theme = Theme(detect_colors(options.no_color), ascii_only, options.palette)

    rows, cols = screen.getmaxyx()
    game = Game(theme, rows, cols, best=scores.data["best"],
                hard=options.hard, seed=options.seed)
    canvas = Canvas(rows, cols)

    interval = 1.0 / clamp(options.fps, 5, 240)
    previous = time.monotonic()
    backlog = 0.0

    while True:
        now = time.monotonic()
        elapsed = min(now - previous, MAX_CATCHUP)
        previous = now

        pending = []
        while True:
            key = screen.getch()
            if key == -1:
                break
            pending.append(key)

        resized = False
        locked = game.state == DEAD and game.since_death < GRACE
        for key in pending:
            if key == curses.KEY_RESIZE:
                resized = True
            elif key in QUIT_KEYS:
                if not locked:
                    return 0
            elif key in PAUSE_KEYS:
                game.toggle_pause()
            elif key in RESTART_KEYS:
                if not locked and game.state in (TITLE, DEAD):
                    game.restart()
            elif key in FLAP_KEYS and not locked:
                game.flap()

        # Not every terminal sends KEY_RESIZE; the reported size is the truth.
        height, width = screen.getmaxyx()
        if resized or (height, width) != (rows, cols):
            rows, cols = height, width
            game.resize(rows, cols)
            canvas = Canvas(rows, cols)
            screen.erase()

        backlog += elapsed
        steps = 0
        while backlog >= STEP and steps < 600:
            game.advance(STEP)
            backlog -= STEP
            steps += 1
        if steps == 600:
            backlog = 0.0

        if game.unsaved is not None and game.state == DEAD:
            scores.record(game.unsaved)
            game.best = max(game.best, scores.data["best"])
            game.unsaved = None

        game.draw(canvas)
        canvas.blit(screen)
        screen.refresh()

        idle = interval - (time.monotonic() - now)
        if idle > 0:
            time.sleep(idle)


def render_once(options):
    """Draw a single frame as plain text. Useful for checking geometry."""
    try:
        cols, rows = (int(part) for part in options.render.lower().split("x"))
    except ValueError:
        print("--render takes COLSxROWS, for example 80x24", file=sys.stderr)
        return 2
    if cols < 1 or rows < 1:
        print("--render needs positive dimensions", file=sys.stderr)
        return 2
    theme = Theme(0, options.ascii, options.palette)
    game = Game(theme, rows, cols, hard=options.hard,
                seed=options.seed if options.seed is not None else 7)
    if options.steps > 0:
        game.flap()
    for tick in range(max(0, options.steps)):
        if tick % 28 == 0:
            game.flap()
        game.advance(STEP * 4)
    canvas = Canvas(rows, cols)
    game.draw(canvas)
    print(canvas)
    print(f"state={game.state} score={game.score} y={game.bird_y:.2f} "
          f"pipes={len(game.pipes)}")
    return 0


def selftest():
    import tempfile

    assert set(GLYPHS) == set(ASCII_GLYPHS), "glyph sets must define the same keys"
    assert set(PALETTES) == set(BASE_COLOR)
    for shades in PALETTES.values():
        assert set(shades) == set(LEVELS)
    theme = Theme(0, False)
    assert set(theme.attr) == set(STYLE)
    for level, _ in STYLE.values():
        assert level in LEVELS

    # A flap rises, gravity brings it back, and the arc stays playable.
    game = Game(theme, 30, 90, seed=1)
    game.state = FLYING
    game.bird_y, game.bird_v = game.field * 0.5, 0.0
    game.flap()
    assert game.bird_v < 0
    apex = game.bird_y
    for _ in range(400):
        game.advance(STEP)
        apex = min(apex, game.bird_y)
    rise = game.field * 0.5 - apex
    assert 0.06 * game.field < rise < 0.30 * game.field, f"bad flap arc: {rise}"

    # Falling speed is capped.
    game = Game(theme, 30, 90, seed=2)
    game.state = FLYING
    game.bird_y, game.bird_v = 1.0, 0.0
    for _ in range(5000):
        game.advance(STEP)
    assert game.bird_v <= MAX_FALL * game.field + 1e-6

    # The ceiling blocks, the ground kills.
    game = Game(theme, 30, 90, seed=3)
    game.state = FLYING
    game.bird_y, game.bird_v = 0.2, -50.0
    game.advance(STEP)
    assert game.state == FLYING and game.bird_y >= BIRD_RADIUS - 1e-9
    game.bird_y, game.bird_v = game.field - 0.1, 10.0
    game.advance(STEP)
    assert game.state == DEAD

    def hit_at(offset):
        probe = Game(theme, 30, 90, seed=4)
        probe.state = FLYING
        probe.pipes = [Pipe(float(probe.bird_x), 5.0, 6.0)]
        probe.bird_y, probe.bird_v = 8.0 + offset, 0.0
        probe.advance(STEP)
        return probe.state

    assert hit_at(0.0) == FLYING
    assert hit_at(-4.0) == FALLING
    assert hit_at(4.0) == FALLING

    # Passing one pipe scores exactly one point.
    game = Game(theme, 30, 90, seed=5)
    game.state = FLYING
    game.pipes = [Pipe(float(game.bird_x) - PIPE_WIDTH, 2.0, game.field - 4.0)]
    game.bird_y = 2.0 + (game.field - 4.0) / 2
    for _ in range(50):
        game.bird_v = 0.0
        game.advance(STEP)
    assert game.score == 1, f"expected 1 point, got {game.score}"

    # The opening narrows with the score but never past the floor.
    game = Game(theme, 40, 120, seed=6)
    wide = game.gap_size()
    game.score = 200
    narrow = game.gap_size()
    assert GAP_MIN_ROWS <= narrow < wide

    # Difficulty must stay in the band this was tuned for. An opening measured
    # in flap arcs is the only scale-free unit available, and the seconds
    # between pipes must not drift with the window size.
    for rows, cols in ((24, 80), (34, 120), (60, 200), (14, 40)):
        game = Game(theme, rows, cols, seed=7)
        arc = (FLAP_SPEED * game.field) ** 2 / (2 * game.gravity)
        period = game.spacing / game.speed
        assert 0.85 <= period <= 1.05, (cols, rows, period)
        if game.field * GAP_START > GAP_MIN_ROWS:
            game.score = 0
            assert 1.7 <= game.gap_size() / arc <= 2.2, (cols, rows, game.gap_size() / arc)
            game.score = 100
            assert 1.3 <= game.gap_size() / arc <= 1.6, (cols, rows, game.gap_size() / arc)

    # Pipes stay inside the playfield at every size and score.
    for rows, cols in ((12, 32), (24, 80), (60, 200)):
        game = Game(theme, rows, cols, seed=rows * cols)
        for score in (0, 5, 25, 100):
            game.score = score
            for _ in range(40):
                pipe = game.make_pipe(float(cols))
                assert pipe.gap_top >= 0.0, (rows, cols, score)
                assert pipe.gap_top + pipe.gap <= game.field + 1e-9, (rows, cols, score)
                game.pipes.append(pipe)
            game.pipes = game.pipes[-1:]

    # Nothing may blow up while drawing, and resizing must leave a sane world.
    rng = random.Random(99)
    for rows, cols in ((10, 20), (12, 32), (13, 40), (24, 80), (31, 101), (60, 200)):
        game = Game(theme, rows, cols, seed=rows + cols)
        canvas = Canvas(rows, cols)
        game.draw(canvas)
        game.flap()
        game.flap()
        for tick in range(500):
            if rng.random() < 0.02:
                game.flap()
            if rng.random() < 0.004:
                game.toggle_pause()
                game.advance(STEP)
                game.toggle_pause()
            game.advance(STEP * 4)
            if tick % 25 == 0:
                canvas = Canvas(rows, cols)
                game.draw(canvas)
                assert len(canvas.chars) == rows
                assert all(len(row) == cols for row in canvas.chars)
                assert len(str(canvas).split("\n")) == rows
        for height, width in ((20, 60), (11, 33), (45, 150), (rows, cols)):
            game.resize(height, width)
            canvas = Canvas(height, width)
            game.draw(canvas)
            assert -1.0 <= game.bird_y <= game.field + 1.0
            for pipe in game.pipes:
                assert pipe.gap >= GAP_MIN_ROWS - 1e-9
                assert 0.0 <= pipe.gap_top <= game.field + 1e-9

    # Every dialog must fit and stay inside the canvas, however narrow.
    for rows, cols in ((12, 32), (14, 36), (24, 80), (40, 200)):
        plain = Game(theme, rows, cols, seed=1)
        canvas = Canvas(rows, cols)
        plain.draw(canvas)
        plain.score, plain.best, plain.beat_best = 41, 41, True
        plain.state = DEAD
        plain.draw(canvas)
        plain.paused = True
        plain.draw(canvas)

    # The ASCII glyph set must survive the same run.
    game = Game(Theme(0, True), 24, 80, seed=11)
    canvas = Canvas(24, 80)
    game.flap()
    for _ in range(200):
        game.advance(STEP * 4)
        game.draw(canvas)

    # A round is recorded once, and a lost round cannot lower the best.
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "scores.json")
        board = Scores(path)
        assert board.data["best"] == 0
        assert board.record(12) is True
        assert board.record(5) is False
        assert Scores(path).data == {"best": 12, "games": 2, "total": 17}
        board.clear()
        assert Scores(path).data["best"] == 0
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        assert Scores(path).data["best"] == 0
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"best": "99", "games": True, "total": -4}, handle)
        assert Scores(path).data == {"best": 0, "games": 0, "total": 0}

    print("selftest ok")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="flappy",
                                     description="Flappy Bird for the terminal.")
    parser.add_argument("--hard", action="store_true",
                        help="faster pipes and tighter openings")
    parser.add_argument("--palette", choices=sorted(PALETTES), default="green",
                        help="phosphor colour (default green)")
    parser.add_argument("--ascii", action="store_true",
                        help="plain ASCII instead of line-drawing glyphs")
    parser.add_argument("--no-color", action="store_true", help="disable colour")
    parser.add_argument("--fps", type=int, default=60, metavar="N",
                        help="frames per second, 5 to 240 (default 60)")
    parser.add_argument("--seed", type=int, metavar="N", help="fixed pipe sequence")
    parser.add_argument("--reset", action="store_true", help="forget the high score")
    parser.add_argument("--selftest", action="store_true",
                        help="check the game logic, no terminal needed")
    parser.add_argument("--render", metavar="COLSxROWS",
                        help="print one frame as text and exit")
    parser.add_argument("--steps", type=int, default=120, metavar="N",
                        help="simulation steps before --render draws")
    parser.add_argument("--version", action="version", version=f"flappy {__version__}")
    options = parser.parse_args(argv)

    if options.selftest:
        return selftest()
    if options.render:
        return render_once(options)

    scores = Scores()
    if options.reset:
        scores.clear()
        print("high score cleared")
        return 0
    if not sys.stdout.isatty():
        print("flappy needs a terminal; try --render 80x24 or --selftest",
              file=sys.stderr)
        return 2
    try:
        return curses.wrapper(play, options, scores)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
