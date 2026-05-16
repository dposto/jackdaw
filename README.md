# Jackdaw

A lightweight, VS Code-inspired HTML editor with live preview, built with PyQt6.

---

## Features

- Live split preview with scroll and click sync
- Syntax highlighting with color swatches
- HTML tag validation with inline gutter markers
- Spell check (requires PyEnchant)
- Snippet system with tabstop expansion (`$1`, `$2`, mirrored stops)
- Find bar and Find & Replace (Firefox-style, docked)
- Multi-tab editing with session restore
- Tab/Shift+Tab indent (4 spaces) with indent guides and dots
- Tag completion modes: Manual, Smart (`</` completes), Auto (pairs on `>`)
- Dark and light themes

---

## Requirements

```
python3-pyqt6
python3-pyqt6-webengine
```

**Optional (spell check):**
```
python3-enchant   # Arch: sudo pacman -S python-pyenchant aspell aspell-en
                  # Debian/Ubuntu: sudo apt install python3-enchant aspell-en
```

---

## Running

```bash
python jackdaw.py
```

---

## Snippets

Snippets are stored in `~/.config/jackdaw/snippets.json` and can be
imported/exported via **Insert → Manage Snippets…** for team sharing.

Body syntax:
- `$1`, `$2` — tabstops; Tab advances between them
- Same number (`$1 … $1`) — mirrored; typed text copies to both on Tab
- `$0` — final cursor position
- `|` — legacy single-cursor marker (still supported)

---

## License

GPL-3.0 — see [LICENSE](LICENSE)

See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for dependency license details.

---

## Credits

Built with:
- [PyQt6](https://riverbankcomputing.com/software/pyqt/) — Riverbank Computing
- [Qt6](https://qt.io/) — The Qt Company
- [PyEnchant](https://pyenchant.github.io/pyenchant/) — Ryan Kelly et al.
- [Enchant](https://abiword.github.io/enchant/) — Dom Lachowicz et al.

---

*Jackdaw is an independent open-source project. It is not affiliated with,
endorsed by, or a fork of Visual Studio Code, VSCodium, or Microsoft.*
