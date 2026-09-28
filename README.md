# flappy

Flappy Bird for the terminal. One file, no dependencies, retro phosphor look.

```
 FLAPPY   SCORE 3   BEST 23                [SPACE] FLAP  [P] PAUSE  [Q] QUIT
                  │▒▒│                 │▒▒│                 │▒▒│
                  │▒▒│                 │▒▒│                 │▒▒│
                 ╞════╡                 │▒▒│                .│▒▒│
                                        │▒▒│                ╞════╡
                -@>                    ╞════╡
                                                       .
                 ╞════╡                                     ╞════╡
                  │▒▒│                 ╞════╡                │▒▒│
                  │▒▒│                  │▒▒│                 │▒▒│
════════════════════════════════════════════════════════════════════════════
▒▒▓▒▒▒▒░░░▒▒▒▒▓▒▒▒▒░░░▒▒▒▒▓▒▒▒▒░░░▒▒▒▒▓▒▒▒▒░░░▒▒▒▒▓▒▒▒▒░░░▒▒▒▒▓▒▒▒▒░░░▒▒▒▒▓▒
```

## Install

```sh
mkdir -p ~/.local/bin && curl -fsSL https://raw.githubusercontent.com/OWNER/flappy-terminal/main/flappy.py -o ~/.local/bin/flappy && chmod +x ~/.local/bin/flappy
```

Then run `flappy`.

If you would rather have a script pick the directory, check your Python, and verify the download
before installing it:

```sh
curl -fsSL https://raw.githubusercontent.com/OWNER/flappy-terminal/main/install.sh | sh
```

Needs Python 3.8 or newer with `curses`, which ships with Python on Linux and macOS. On Debian and
Ubuntu the module lives in `python3-curses`. There is nothing to compile and nothing on PyPI: the
game is the one file you just downloaded, and uninstalling is `rm ~/.local/bin/flappy`.

## Controls

| Key | Action |
|---|---|
| `space` / `↑` / `w` / `k` / `enter` | flap, and start or restart |
| `p` | pause |
| `r` | restart, on the title or game over screen |
| `q` / `esc` | quit |

## Options

| Option | Effect |
|---|---|
| `--palette green\|amber` | phosphor colour, green by default |
| `--hard` | faster pipes, tighter openings |
| `--ascii` | plain ASCII instead of line-drawing glyphs |
| `--no-color` | no colour at all |
| `--fps N` | 5 to 240, default 60 |
| `--seed N` | fixed pipe sequence, for comparing runs |
| `--reset` | forget the high score |
| `--selftest` | check the game logic, no terminal needed |
| `--render COLSxROWS` | print one frame as text and exit |
| `--steps N` | simulation steps before `--render` draws; `0` gives the title screen |

## High score

Kept in `$XDG_DATA_HOME/flappy/scores.json`, which defaults to
`~/.local/share/flappy/scores.json`:

```json
{"best": 12, "games": 2, "total": 17}
```

Written atomically through a temporary file plus `os.replace`. A corrupt, unreadable or
wrong-typed file is ignored and you start from zero. Clear it with `flappy --reset`.

Medals arrive at 10, 20, 30 and 40 points: bronze, silver, gold, platinum.

## Difficulty

The opening is measured in flap arcs, the one unit that does not change with the window size: it
starts at 1.96 arcs and closes to 1.46 by score 25. A pipe crosses the whole window in 3.4 seconds
and one arrives every 0.95 seconds at score 0, dropping to about 0.5 seconds as the speed ramps.
Those numbers hold in an 80-column window and in a 200-column one, and `--selftest` fails if a
change pushes them out of that band. `--hard` starts at 1.58 arcs and closes to 1.27.

## Tests

```sh
python3 flappy.py --selftest             # physics, collisions, scoring, dialogs, resize fuzz, storage
python3 flappy.py --render 80x24         # inspect the geometry without a terminal
python3 flappy.py --render 76x22 --steps 0
python3 flappy.py --render 40x14 --ascii
```

`--selftest` prints `selftest ok` and exits 0. The curses loop itself is exercised by driving the
program in a pty with real keystrokes; `--render` and `--selftest` cover everything else. CI runs
the same checks on Python 3.8 through 3.13.

## How it works

- **The picture** is one phosphor colour in four intensities, the way a monochrome CRT had them.
  Nothing paints a background except the reverse-video status bar, so the sky is simply your
  terminal background.
- **Pipes** are tubes built from line-drawing characters: walls `│`, a shaded core `▒`, and a
  flange cap `╞════╡` that overhangs a column on each side.
- **The ground** is a double rule `═` over a scrolling three-tone dither.
- **Menus** are double-line boxes with the title set into the top border, `╔══[ GAME OVER ]══╗`.
- **Physics** is expressed as a fraction of the playfield height, so an 80×24 window plays like a
  200×60 one. Fixed 1/240 s steps, decoupled from the frame rate.
- **Partly covered cells** are drawn as solid pipe. The game looks stricter than its hitbox, never
  the other way round.
- **Resizing** rescales the bird and the pipes so a round survives being dragged to a new size.
- **Fallbacks** go 256 colours → 8 → none, and line-drawing → ASCII.

Below 32×12 it shows a message instead of an unplayable board.

## License

MIT, see [LICENSE](LICENSE).
