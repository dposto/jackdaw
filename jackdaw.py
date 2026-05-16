#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 David Posto
# https://github.com/dposto/jackdaw
#
# Jackdaw — lightweight HTML editor with live preview.
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# See LICENSE for the full license text.
"""
Jackdaw - Lightweight HTML editor with live preview
Requires: python3-pyqt6, python3-pyqt6.qtwebengine, python3-pyqt6.qtwebchannel
Optional: python3-enchant (or: pip install pyenchant --break-system-packages) for spell check
"""

__version__ = "1.0.0"

import sys
import os
import re
import math
import json
from html.parser import HTMLParser
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QPlainTextEdit, QTextEdit, QToolBar, QFileDialog, QDialog,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QStatusBar, QCompleter,
    QTabBar, QMessageBox, QToolButton, QInputDialog, QMenu, QListWidget, QListWidgetItem,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtCore import (
    Qt, QTimer, QRegularExpression, QObject, pyqtSlot,
    QRect, QRectF, QSize, QSizeF, QSettings, QSignalBlocker, QPointF,
    QStandardPaths,
)
from PyQt6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QColor, QFont, QTextDocument,
    QKeySequence, QAction, QActionGroup, QIcon, QTextCursor, QPainter, QPalette, QPen,
    QPainterPath,
)

try:
    from PyQt6.QtWebChannel import QWebChannel
    HAS_WEBCHANNEL = True
except ImportError:
    HAS_WEBCHANNEL = False

try:
    import enchant
    HAS_ENCHANT = True
except ImportError:
    HAS_ENCHANT = False

# ─────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────
def get_config_dir():
    """Return the platform-appropriate config directory for Jackdaw.

    - Linux/macOS: ~/.config/jackdaw  (or $XDG_CONFIG_HOME/jackdaw)
    - Windows:     %APPDATA%\\jackdaw
    Uses QStandardPaths so it respects OS conventions and any custom
    install/portable locations automatically.
    """
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    )
    # Qt includes the app name on some platforms but not others
    path = base if base.endswith("jackdaw") else os.path.join(base, "jackdaw")
    os.makedirs(path, exist_ok=True)
    return path


# ─────────────────────────────────────────────
SETTINGS_VERSION = 7   # bump this to wipe stale saved settings

# Cross-platform monospace font
MONO_FONT = "Consolas" if sys.platform == "win32" else "Monospace"

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

HTML_TAGS = [
    "a", "abbr", "address", "article", "aside", "audio",
    "b", "blockquote", "body", "br", "button",
    "canvas", "caption", "cite", "code", "col", "colgroup",
    "data", "datalist", "dd", "del", "details", "dfn", "dialog", "div", "dl", "dt",
    "em", "embed",
    "fieldset", "figcaption", "figure", "footer", "form",
    "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hr", "html",
    "i", "iframe", "img", "input", "ins",
    "kbd", "label", "legend", "li", "link",
    "main", "map", "mark", "menu", "meta", "meter",
    "nav", "noscript",
    "object", "ol", "optgroup", "option", "output",
    "p", "picture", "pre", "progress",
    "q", "rp", "rt", "ruby",
    "s", "samp", "script", "section", "select", "small", "source", "span",
    "strong", "style", "sub", "summary", "sup",
    "table", "tbody", "td", "template", "textarea", "tfoot", "th", "thead",
    "time", "title", "tr", "track",
    "u", "ul", "var", "video", "wbr",
]

DARK_PREVIEW_CSS = """
<style id="__jackdaw_dark__">
html, body { background-color: #1e1e1e !important; color: #d4d4d4 !important; }
a { color: #6ab0f5 !important; }
#__hp_gutter { background: #2a2a2a !important; border-right: 1px solid #3a3a3a !important; }
</style>
"""

BRIDGE_JS = """
(function() {
    if (window.__jackdawBridgeInstalled) return;
    window.__jackdawBridgeInstalled = true;

    function tryConnect() {
        if (typeof qt === 'undefined' || typeof qt.webChannelTransport === 'undefined') {
            setTimeout(tryConnect, 100);
            return;
        }
        new QWebChannel(qt.webChannelTransport, function(channel) {
            var bridge = channel.objects.previewBridge;
            var scrollTicking = false;
            window.addEventListener('scroll', function() {
                if (!scrollTicking) {
                    scrollTicking = true;
                    requestAnimationFrame(function() {
                        var scrollable = document.documentElement.scrollHeight - window.innerHeight;
                        var pct = scrollable > 0 ? window.scrollY / scrollable : 0;
                        bridge.onPreviewScroll(pct);
                        scrollTicking = false;
                    });
                }
            }, { passive: true });

            document.addEventListener('click', function(e) {
                var candidate = e.target;
                while (candidate && candidate !== document.body) {
                    var t = (candidate.tagName || '').toLowerCase();
                    if (['li','p','h1','h2','h3','h4','h5','h6','td','th',
                         'blockquote','div','section','article','ol','ul',
                         'img','a','table','tr','font','b','strong'].includes(t)) break;
                    candidate = candidate.parentElement;
                }
                if (!candidate || candidate === document.body) candidate = e.target;
                bridge.onPreviewClick(
                    (candidate.tagName||'').toLowerCase(),
                    candidate.id||'',
                    candidate.getAttribute?candidate.getAttribute('name')||'':'',
                    candidate.getAttribute?candidate.getAttribute('src')||'':'',
                    candidate.getAttribute?candidate.getAttribute('href')||'':'',
                    (candidate.textContent||'').trim().replace(/\\s+/g,' ').substring(0,60)
                );
            }, true);

            // ── Position marker: Range-based text matching ──

            var markerEl = null;
            var pendingUpdate = null;
            var rafScheduled = false;
            var lastSearch = "";
            var lastPct = -1;

            function getMarker() {
                if (!markerEl) {
                    markerEl = document.createElement('div');
                    markerEl.id = '__hp_pos_marker';
                    markerEl.style.cssText =
                        'position: absolute;' +
                        'left: 0;' +
                        'width: 6px;' +
                        'background: #007acc;' +
                        'z-index: 99999;' +
                        'pointer-events: none;' +
                        'transition: top 0.08s linear, height 0.08s linear, opacity 0.15s;';
                    document.body.appendChild(markerEl);
                }
                return markerEl;
            }

            function shouldSkip(searchText, occurrence) {
                if (searchText === lastSearch && occurrence === lastPct) {
                    return true;
                }
                lastSearch = searchText;
                lastPct = occurrence;
                return false;
            }

            // Reset cache when preview scrolls so marker recalculates
            window.addEventListener('scroll', function() {
                lastSearch = "";
                lastPct = -1;
            }, { passive: true });

            function findBestMatch(searchText, occurrence) {
                if (!searchText || searchText.length < 2) return null;

                var walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT, null
                );

                var matchCount = 0;
                var node;

                while ((node = walker.nextNode())) {
                    var idx = node.textContent.indexOf(searchText);
                    if (idx === -1) continue;

                    try {
                        var range = document.createRange();
                        range.setStart(node, idx);
                        range.setEnd(node, idx + searchText.length);

                        var rect = range.getBoundingClientRect();
                        if (rect.height === 0) continue;

                        // If inside a blockquote, use the blockquote's full rect
                        var bq = node.parentElement;
                        while (bq && bq !== document.body) {
                            if (bq.tagName === 'BLOCKQUOTE') {
                                rect = bq.getBoundingClientRect();
                                break;
                            }
                            bq = bq.parentElement;
                        }

                        if (matchCount === occurrence) {
                            return rect;
                        }
                        matchCount++;
                    } catch(e) {}
                }

                return null;
            }

            function updateMarker(payload) {
                if (shouldSkip(payload.searchText, payload.occurrence)) return;

                var rect = findBestMatch(payload.searchText, payload.occurrence || 0);
                var el = getMarker();

                if (!rect) {
                    el.style.opacity = '0';
                    return;
                }

                el.style.opacity = '1';
                // Document-space: rect.top is viewport-relative, add scrollY for absolute
                el.style.top = (rect.top + window.scrollY) + 'px';
                el.style.height = Math.max(20, rect.height) + 'px';
            }

            window.scheduleMarkerUpdate = function(payload) {
                pendingUpdate = payload;
                if (!rafScheduled) {
                    rafScheduled = true;
                    requestAnimationFrame(function() {
                        rafScheduled = false;
                        if (pendingUpdate) {
                            updateMarker(pendingUpdate);
                            pendingUpdate = null;
                        }
                    });
                }
            };

            // Find image by src and mark its blockquote parent (or the image itself)
            window.__jackdawMarkerByImg = function(src, occurrence) {
                lastSearch = "";
                lastPct = -1;
                if (occurrence === undefined) occurrence = 0;

                var el = getMarker();

                // Collect all matching images
                var imgs = document.querySelectorAll('img');
                var matchCount = 0;
                for (var i = 0; i < imgs.length; i++) {
                    var img = imgs[i];
                    if (!img.src) continue;
                    var imgSrc = img.getAttribute('src') || '';
                    if (imgSrc !== src && img.src.indexOf(src) === -1) continue;

                    if (matchCount === occurrence) {
                        // Use blockquote parent if present, otherwise the image
                        var target = img;
                        var parent = img.parentElement;
                        while (parent && parent !== document.body) {
                            if (parent.tagName === 'BLOCKQUOTE') {
                                target = parent;
                                break;
                            }
                            parent = parent.parentElement;
                        }

                        var rect = target.getBoundingClientRect();
                        el.style.opacity = '1';
                        el.style.top = (rect.top + window.scrollY) + 'px';
                        el.style.height = Math.max(20, rect.height) + 'px';
                        return;
                    }
                    matchCount++;
                }

                el.style.opacity = '0';
            };
        });
    }
    tryConnect();
})();
"""

# ─────────────────────────────────────────────
#  App-level dark/light Fusion palette
#  (Setting palette on QApplication is the only
#  reliable way to override GNOME/GTK theming)
# ─────────────────────────────────────────────
def _apply_fusion_palette(app: QApplication, dark: bool):
    p = QPalette()
    if dark:
        p.setColor(QPalette.ColorRole.Window,          QColor("#1e1e1e"))
        p.setColor(QPalette.ColorRole.WindowText,      QColor("#d4d4d4"))
        p.setColor(QPalette.ColorRole.Base,             QColor("#1e1e1e"))
        p.setColor(QPalette.ColorRole.AlternateBase,    QColor("#2d2d2d"))
        p.setColor(QPalette.ColorRole.ToolTipBase,      QColor("#2d2d2d"))
        p.setColor(QPalette.ColorRole.ToolTipText,      QColor("#d4d4d4"))
        p.setColor(QPalette.ColorRole.Text,             QColor("#d4d4d4"))
        p.setColor(QPalette.ColorRole.Button,           QColor("#333333"))
        p.setColor(QPalette.ColorRole.ButtonText,       QColor("#d4d4d4"))
        p.setColor(QPalette.ColorRole.Link,             QColor("#569cd6"))
        p.setColor(QPalette.ColorRole.Highlight,        QColor("#264f78"))
        p.setColor(QPalette.ColorRole.HighlightedText,  QColor("#d4d4d4"))
        p.setColor(QPalette.ColorRole.Light,            QColor("#444444"))
        p.setColor(QPalette.ColorRole.Midlight,         QColor("#3a3a3a"))
        p.setColor(QPalette.ColorRole.Dark,             QColor("#111111"))
        p.setColor(QPalette.ColorRole.Mid,              QColor("#6a6a6a"))
        p.setColor(QPalette.ColorRole.Shadow,           QColor("#000000"))
    else:
        p.setColor(QPalette.ColorRole.Window,          QColor("#f0f0f0"))
        p.setColor(QPalette.ColorRole.WindowText,      QColor("#1e1e1e"))
        p.setColor(QPalette.ColorRole.Base,             QColor("#ffffff"))
        p.setColor(QPalette.ColorRole.AlternateBase,    QColor("#f5f5f5"))
        p.setColor(QPalette.ColorRole.Text,             QColor("#1e1e1e"))
        p.setColor(QPalette.ColorRole.Button,           QColor("#e0e0e0"))
        p.setColor(QPalette.ColorRole.ButtonText,       QColor("#1e1e1e"))
        p.setColor(QPalette.ColorRole.Link,             QColor("#0000cd"))
        p.setColor(QPalette.ColorRole.Highlight,        QColor("#0078d4"))
        p.setColor(QPalette.ColorRole.HighlightedText,  QColor("#ffffff"))
    app.setPalette(p)

    # Global QMenu stylesheet — covers menu bar menus which ignore
    # per-widget stylesheets on Wayland/GNOME
    if dark:
        sep_color = "#6a6a6a"
        bg        = "#1e1e1e"
        border    = "#454545"
        text      = "#cccccc"
        hover_bg  = "#094771"
        disabled  = "#666666"
    else:
        sep_color = "#c0c0c0"
        bg        = "#ffffff"
        border    = "#c8c8c8"
        text      = "#1e1e1e"
        hover_bg  = "#0060c0"
        disabled  = "#aaaaaa"

    app.setStyleSheet(f"""
        QMenu {{
            background-color: {bg};
            border: 1px solid {border};
            padding: 4px 0px;
            font-size: 13px;
            color: {text};
        }}
        QMenu::item {{
            color: {text};
            padding: 5px 32px 5px 16px;
            background: transparent;
        }}
        QMenu::item:selected {{
            background-color: {hover_bg};
            color: #ffffff;
        }}
        QMenu::item:disabled {{
            color: {disabled};
        }}
        QMenu::separator {{
            height: 2px;
            background: {sep_color};
            margin: 3px 0px;
        }}
        QMenu::indicator {{
            width: 14px;
            height: 14px;
            margin-left: 4px;
        }}
    """)


# ─────────────────────────────────────────────
#  Color swatch data (stored per text block)
# ─────────────────────────────────────────────
from PyQt6.QtGui import QTextBlockUserData

class ColorSwatchData(QTextBlockUserData):
    """Stores color swatch positions for a single text block."""
    def __init__(self):
        super().__init__()
        self.swatches = []   # list of (column, QColor)


# ─────────────────────────────────────────────
#  HTML tag validator
# ─────────────────────────────────────────────
class _TagTracker(HTMLParser):
    """Stack-based tracker that records tag mismatches with line numbers."""

    _VOID = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
    # Tags whose closing tag the HTML spec says is truly optional —
    # structural boilerplate users rarely write by hand.
    # Deliberately excludes <li>, <p>, <td>, <tr>, etc. so the validator
    # flags them when forgotten (that's what the user wants to catch).
    _OPTIONAL_CLOSE = {"html", "head", "body",
                        "thead", "tbody", "tfoot", "colgroup"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self._stack  = []   # [(tag, lineno), …]
        self.errors  = []   # [(lineno, message), …]

    def handle_starttag(self, tag, attrs):
        if tag in self._VOID or tag in self._OPTIONAL_CLOSE:
            return
        lineno, _ = self.getpos()
        self._stack.append((tag, lineno))

    def handle_endtag(self, tag):
        if tag in self._VOID or tag in self._OPTIONAL_CLOSE:
            return
        lineno, _ = self.getpos()
        # Walk back through the stack looking for a match
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                # Any tags opened AFTER the match are implicitly unclosed here
                for skipped_tag, skipped_line in self._stack[i + 1:]:
                    if skipped_tag not in self._OPTIONAL_CLOSE:
                        self.errors.append((
                            skipped_line,
                            f"<{skipped_tag}> opened here has no closing tag "
                            f"(found </{tag}> on line {lineno} first)"
                        ))
                self._stack = self._stack[:i]
                return
        # Closing tag with no opener at all
        self.errors.append((lineno,
            f"</{tag}> has no matching opening tag"))

    def finish(self):
        for tag, lineno in self._stack:
            if tag not in self._OPTIONAL_CLOSE:
                self.errors.append((lineno, f"<{tag}> is never closed"))


def validate_html_tags(text):
    """Return list of (lineno, message) sorted by line, or [] if no issues."""
    tracker = _TagTracker()
    try:
        tracker.feed(text)
        tracker.close()
    except Exception:
        pass
    tracker.finish()
    return sorted(set(tracker.errors), key=lambda e: e[0])


# ─────────────────────────────────────────────
#  Spell checker
# ─────────────────────────────────────────────
def _plain_text_word_ranges(text):
    """Yield (start, end) for every word in `text` that sits outside HTML tags.

    Skips content inside <…>, HTML entities (&…;), script/style blocks,
    and URL-like strings in visible text.
    """
    # Mask everything inside tags so we only see plain text
    masked = list(text)
    i = 0
    in_script_style = False
    ss_close = ""
    while i < len(text):
        if not in_script_style and text[i] == '<':
            j = text.find('>', i)
            end = j + 1 if j != -1 else len(text)
            tag_inner = text[i + 1:end - 1].strip().lower()
            if tag_inner.startswith(('script', 'style')):
                tag_name = tag_inner.split()[0].lstrip('/')
                in_script_style = True
                ss_close = f'</{tag_name}'
            for k in range(i, end):
                masked[k] = ' '
            i = end
        elif in_script_style:
            close_idx = text.lower().find(ss_close, i)
            if close_idx == -1:
                for k in range(i, len(text)):
                    masked[k] = ' '
                break
            gt = text.find('>', close_idx)
            end = gt + 1 if gt != -1 else len(text)
            for k in range(i, end):
                masked[k] = ' '
            in_script_style = False
            i = end
        elif text[i] == '&':
            j = text.find(';', i)
            end = j + 1 if j != -1 else i + 1
            for k in range(i, end):
                masked[k] = ' '
            i = end
        else:
            i += 1

    masked_str = ''.join(masked)

    # Also mask URLs and email addresses in visible text content
    url_pat = re.compile(
        r'(?:'
        r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'  # email addresses
        r'|https?://[^\s<>"\']+'          # http(s):// URLs
        r'|ftp://[^\s<>"\']+'             # ftp:// URLs
        r'|www\.[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}[^\s<>"\']*'   # www.example.com
        r'|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/[^\s<>"\']*'       # domain.com/path
        r')',
        re.IGNORECASE,
    )
    masked_list = list(masked_str)
    for m in url_pat.finditer(masked_str):
        for k in range(m.start(), m.end()):
            masked_list[k] = ' '
    masked_str = ''.join(masked_list)

    for m in re.finditer(r"\b[a-zA-Z']{2,}\b", masked_str):
        word = m.group()
        # Skip all-caps abbreviations (HTML, CSS, URL, etc.)
        if word.replace("'", "").isupper() and len(word) > 2:
            continue
        yield m.start(), m.end()


class SpellChecker:
    def __init__(self, lang="en_US"):
        self._dict  = None
        self._pwl   = None   # personal word list
        self._enabled = False
        if not HAS_ENCHANT:
            return
        try:
            self._dict = enchant.Dict(lang)
            pwl_path   = os.path.join(get_config_dir(), "personal_wordlist.txt")
            self._pwl  = enchant.DictWithPWL(lang, pwl_path)
            self._enabled = True
        except Exception:
            self._dict = None

    @property
    def available(self):
        return self._dict is not None

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, val):
        self._enabled = val and self.available

    def check(self, word):
        if not self._enabled or self._pwl is None:
            return True
        try:
            return self._pwl.check(word)
        except Exception:
            return True

    def suggest(self, word):
        if not self._enabled or self._pwl is None:
            return []
        try:
            return self._pwl.suggest(word)[:8]
        except Exception:
            return []

    def add(self, word):
        """Add word to personal word list."""
        if self._pwl:
            try:
                self._pwl.add(word)
            except Exception:
                pass


# ─────────────────────────────────────────────
#  Syntax Highlighter
# ─────────────────────────────────────────────
class HTMLHighlighter(QSyntaxHighlighter):
    def __init__(self, document, dark=True):
        super().__init__(document)
        self.dark = dark
        self._build_formats()

    def _fmt(self, color, bold=False, italic=False, underline=False):
        f = QTextCharFormat()
        f.setForeground(QColor(color))
        if bold:
            f.setFontWeight(QFont.Weight.Bold)
        if italic:
            f.setFontItalic(True)
        if underline:
            f.setFontUnderline(True)
        return f

    def _build_formats(self):
        d = self.dark
        # Tags: blue (no bold), except <font> which gets red
        self.fmt_tag     = self._fmt("#569cd6" if d else "#0000cd")          # blue
        self.fmt_font_tag= self._fmt("#f44747" if d else "#cc0000")          # bright red for <font>
        self.fmt_bracket = self._fmt("#808080" if d else "#888888")           # gray for < / >
        self.fmt_attr    = self._fmt("#9cdcfe" if d else "#7b4f00")          # light blue attrs
        self.fmt_value   = self._fmt("#ce9178" if d else "#a31515")          # orangish-brown values
        self.fmt_comment = self._fmt("#6a9955" if d else "#218a00", italic=True)
        self.fmt_doctype = self._fmt("#808080")
        self.fmt_entity  = self._fmt("#569cd6" if d else "#0000cd")               # blue like tags
        self.fmt_url     = self._fmt("#ce9178" if d else "#a31515", underline=True)  # value + underline
        # Illegal/invisible characters: yellow highlight like VS Code
        self.fmt_illegal = QTextCharFormat()
        self.fmt_illegal.setBackground(QColor("#524a19" if d else "#fff3cd"))
        self.fmt_illegal.setForeground(QColor("#f0c674" if d else "#856404"))
        self.fmt_illegal.setUnderlineStyle(
            QTextCharFormat.UnderlineStyle.WaveUnderline)
        self.fmt_illegal.setUnderlineColor(QColor("#c8b900" if d else "#b8860b"))
        self.comment_start = QRegularExpression(r'<!--')
        self.comment_end   = QRegularExpression(r'-->')

    def set_dark(self, dark: bool):
        self.dark = dark
        self._build_formats()
        self.rehighlight()

    def highlightBlock(self, text):
        self.setCurrentBlockState(0)
        self._cur_swatches = []   # collect swatches for this block
        start = 0
        if self.previousBlockState() != 1:
            m = self.comment_start.match(text)
            start = m.capturedStart() if m.hasMatch() else -1

        while start >= 0:
            end_m = self.comment_end.match(text, start)
            if end_m.hasMatch():
                length = end_m.capturedStart() + end_m.capturedLength() - start
                self.setFormat(start, length, self.fmt_comment)
                next_m = self.comment_start.match(text, start + length)
                start  = next_m.capturedStart() if next_m.hasMatch() else -1
            else:
                self.setCurrentBlockState(1)
                self.setFormat(start, len(text) - start, self.fmt_comment)
                return

        if self.previousBlockState() == 1:
            end_m = self.comment_end.match(text)
            if end_m.hasMatch():
                end  = end_m.capturedStart() + end_m.capturedLength()
                self.setFormat(0, end, self.fmt_comment)
                text = " " * end + text[end:]
                self.setCurrentBlockState(0)
            else:
                self.setFormat(0, len(text), self.fmt_comment)
                self.setCurrentBlockState(1)
                return

        for pattern, fmt in [
            (QRegularExpression(r'<!DOCTYPE[^>]*>',
                QRegularExpression.PatternOption.CaseInsensitiveOption), self.fmt_doctype),
            (QRegularExpression(r'&[a-zA-Z0-9#]+;'), self.fmt_entity),
        ]:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        i = 0
        while i < len(text):
            if text[i] == '<':
                j        = text.find('>', i)
                end      = j if j != -1 else len(text) - 1
                tag_text = text[i:end + 1]
                name_m   = re.match(r'<(/?\w[\w.-]*)', tag_text)
                if name_m:
                    tag_name = name_m.group(1).lower().lstrip('/')
                    tag_fmt = self.fmt_font_tag if tag_name == 'font' else self.fmt_tag

                    # < bracket = gray
                    self.setFormat(i, 1, self.fmt_bracket)

                    raw_name = name_m.group(1)  # e.g. "/font" or "li"
                    if raw_name.startswith('/'):
                        # Slash after < = gray, then tag name in color
                        self.setFormat(i + 1, 1, self.fmt_bracket)
                        self.setFormat(i + 2, len(raw_name) - 1, tag_fmt)
                    else:
                        self.setFormat(i + 1, len(raw_name), tag_fmt)

                    # > bracket = gray
                    if j != -1:
                        self.setFormat(j, 1, self.fmt_bracket)
                    inner = tag_text[1 + len(name_m.group(1)):]
                    base  = i + 1 + len(name_m.group(1))

                    # Collect attribute names with their positions for url detection
                    attr_positions = {}  # end_of_equals_pos → attr_name
                    for am in re.finditer(r'\b([\w-]+)\s*(=)', inner):
                        self.setFormat(base + am.start(1), len(am.group(1)), self.fmt_attr)
                        self.setFormat(base + am.start(2), 1, self.fmt_bracket)
                        attr_positions[am.end(2)] = am.group(1).lower()

                    for vm in re.finditer(r'(=)\s*(["\'])(.*?)\2', inner):
                        self.setFormat(base + vm.start(1), 1, self.fmt_bracket)
                        val_full_start = vm.start(2)
                        val_full_len = len(vm.group(2)) + len(vm.group(3)) + 1
                        # Use underlined format for href/src values
                        attr_name = attr_positions.get(vm.start(1) + 1, "")
                        val_fmt = self.fmt_url if attr_name in ("href", "src", "action") else self.fmt_value
                        self.setFormat(base + val_full_start, val_full_len, val_fmt)
                        val_text  = vm.group(3)
                        val_start = base + vm.start(3)
                        self._find_colors_in_value(val_text, val_start)
                i = end + 1
            else:
                i += 1

        # ── Highlight illegal/invisible characters ──
        # Detect control chars, zero-width spaces, smart quotes,
        # non-breaking spaces, and other non-standard Unicode
        block_text = self.currentBlock().text()
        for ci, ch in enumerate(block_text):
            cp = ord(ch)
            if (
                (cp < 0x20 and cp not in (0x09, 0x0A, 0x0D))  # control chars (keep tab, LF, CR)
                or cp == 0x7F          # DEL
                or cp == 0xA0          # non-breaking space
                or cp == 0xAD          # soft hyphen
                or 0x2010 <= cp <= 0x2015  # various dashes (‐ ‑ ‒ – — ―)
                or 0x2018 <= cp <= 0x201F  # smart quotes (' ' ‚ ‛ " " „ ‟)
                or cp == 0x2026        # ellipsis …
                or cp == 0x2039 or cp == 0x203A  # single angle quotes ‹ ›
                or cp == 0x00AB or cp == 0x00BB  # double angle quotes « »
                or cp == 0xFEFF        # BOM / zero-width no-break space
                or 0x200B <= cp <= 0x200F  # zero-width spaces, LTR/RTL marks
                or 0x202A <= cp <= 0x202E  # LTR/RTL embedding
                or 0x2060 <= cp <= 0x2064  # invisible operators
                or 0x2066 <= cp <= 0x2069  # isolate marks
                or cp == 0xFFFD        # replacement character
                or cp == 0xFFFF        # not a character
            ):
                self.setFormat(ci, 1, self.fmt_illegal)

        # Store swatch data on the block for the editor to paint
        if self._cur_swatches:
            data = ColorSwatchData()
            data.swatches = self._cur_swatches
            self.currentBlock().setUserData(data)
        else:
            self.currentBlock().setUserData(None)

    def _find_colors_in_value(self, val_text, block_col_start):
        """Find color values inside an attribute value string and record swatch positions."""
        CSS_COLORS = {
            "red", "green", "blue", "yellow", "orange", "purple", "black",
            "white", "grey", "gray", "cyan", "magenta", "pink", "brown",
            "navy", "teal", "maroon", "lime", "aqua", "olive", "silver",
            "fuchsia", "coral", "crimson", "gold", "indigo", "ivory",
            "khaki", "lavender", "orchid", "plum", "salmon", "sienna",
            "tan", "tomato", "turquoise", "violet", "wheat",
        }
        # Find hex colors
        for m in re.finditer(r'#([0-9a-fA-F]{3}){1,2}\b', val_text):
            col = block_col_start + m.start()
            self._cur_swatches.append((col, QColor(m.group(0))))
        # Find named colors
        for m in re.finditer(r'\b([a-zA-Z]+)\b', val_text):
            if m.group(1).lower() in CSS_COLORS:
                col = block_col_start + m.start()
                self._cur_swatches.append((col, QColor(m.group(1))))


# ─────────────────────────────────────────────
#  Tab data  (owns document + highlighter)
# ─────────────────────────────────────────────
class TabData:
    _counter          = 0
    _untitled_counter = 0

    def __init__(self, path=None, content=""):
        TabData._counter += 1
        self.path         = path
        self.content      = content or ""
        self._dirty       = False
        self._session_backed = False
        self.cursor_pos   = 0
        self.scroll_value = 0
        self.custom_name  = None   # user-supplied display name (overrides filename)
        if not path:
            TabData._untitled_counter += 1
            self._untitled_num = TabData._untitled_counter
        else:
            self._untitled_num = 0

    @property
    def title(self):
        """Plain display name — dirty state is shown on the close button, not here."""
        if self.custom_name:
            return self.custom_name
        if self.path:
            return os.path.basename(self.path)
        snippet = self._content_snippet()
        if snippet:
            return f"{snippet} Untitled-{self._untitled_num}"
        return f"Untitled-{self._untitled_num}"

    def _content_snippet(self, max_chars=20):
        """First meaningful text from content, tags stripped, for auto-naming."""
        text = re.sub(r'<[^>]+>', ' ', self.content)   # strip tags
        text = re.sub(r'&\w+;', ' ', text)              # strip entities
        text = re.sub(r'\s+', ' ', text).strip()
        first_line = text.split('\n')[0].strip()
        if len(first_line) > max_chars:
            first_line = first_line[:max_chars].rstrip()
        return first_line

    def mark_dirty(self):
        self._dirty          = True
        self._session_backed = False   # new changes not yet in crash recovery

    def mark_clean(self):
        self._dirty          = False
        self._session_backed = False

    def mark_session_backed(self):
        """Called by session saver — content is now in crash recovery."""
        if self._dirty:
            self._session_backed = True

    @property
    def is_dirty(self):
        return self._dirty

    @property
    def is_session_backed(self):
        """Dirty but already captured in crash recovery session."""
        return self._dirty and self._session_backed


# ─────────────────────────────────────────────
#  WebChannel bridge
# ─────────────────────────────────────────────
class PreviewBridge(QObject):
    def __init__(self, editor, main_window):
        super().__init__()
        self._editor         = editor
        self._mw             = main_window
        self.scroll_enabled  = True
        self.click_enabled   = True
        self._scroll_syncing = False

    @pyqtSlot(float)
    def onPreviewScroll(self, pct):
        if not self.scroll_enabled or self._scroll_syncing:
            return

        # Ignore preview scroll events caused by editor → preview sync.
        # Otherwise the preview immediately feeds a rounded percentage
        # back into the editor, producing the jerk/backtrack effect.
        if getattr(self._mw, '_syncing_to_preview', False):
            return

        sb = self._editor.verticalScrollBar()
        if sb.maximum() == 0:
            return
        self._scroll_syncing = True
        sb.setValue(int(pct * sb.maximum()))
        QTimer.singleShot(60, self._clear_scroll)

    def _clear_scroll(self):
        self._scroll_syncing = False

    @pyqtSlot(str, str, str, str, str, str)
    def onPreviewClick(self, tag, el_id, name, src, href, text_snip):
        if not self.click_enabled:
            return
        source = self._editor.toPlainText()
        pos    = None
        for attr, val in [("id", el_id), ("name", name), ("src", src), ("href", href)]:
            if val:
                for q in ('"', "'"):
                    idx = source.find(f'{attr}={q}{val}{q}')
                    if idx != -1:
                        pos = source.rfind('<', 0, idx)
                        break
            if pos is not None:
                break
        if pos is None and text_snip and len(text_snip) > 3:
            clean = re.sub(r'\s+', ' ', text_snip[:40]).strip()
            idx   = source.find(clean)
            if idx != -1:
                pos = source.rfind('<', 0, idx + 1) or idx
        if pos is not None:
            cursor = self._editor.textCursor()
            cursor.setPosition(pos)
            self._editor.setTextCursor(cursor)
            self._editor.ensureCursorVisible()
            self._editor.centerCursor()


# ─────────────────────────────────────────────
#  Line Number Area
# ─────────────────────────────────────────────
class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor.paint_line_numbers(event)


# ─────────────────────────────────────────────
#  Tag utilities
# ─────────────────────────────────────────────
def find_unclosed_tag(text):
    stack = []
    for m in re.finditer(r'<(/?)(\w[\w.-]*)(?:\s[^>]*)?>',  text):
        closing = m.group(1) == '/'
        tag     = m.group(2).lower()
        if tag in VOID_TAGS:
            continue
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i] == tag:
                    stack.pop(i)
                    break
        else:
            stack.append(tag)
    return stack[-1] if stack else None


# ─────────────────────────────────────────────
#  Editor widget
# ─────────────────────────────────────────────
class HTMLEditor(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self._dark             = True
        self._tag_mode         = "auto"   # "manual" | "smart" | "auto"
        self._completer_enabled = True
        self._find_extra_selections  = []
        self._spell_extra_selections = []
        self._spell_ranges           = []
        self._error_lines            = set()   # line numbers (1-based) with tag errors
        self._zoom_in_request = lambda: None
        self._zoom_out_request = lambda: None
        self._updating_margins = False
        self._updating_scroll_padding = False

        app = QApplication.instance()
        if app:
            app.applicationStateChanged.connect(lambda _state: self.viewport().update())

        self.setFont(QFont(MONO_FONT, 11))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self._line_area = LineNumberArea(self)
        self.setCenterOnScroll(True)
        self.blockCountChanged.connect(self._update_line_area_width)
        self.blockCountChanged.connect(self._update_scroll_padding)
        self.updateRequest.connect(self._update_line_area)
        self.cursorPositionChanged.connect(self._line_area.update)
        self._update_line_area_width()

        self._completer = QCompleter(HTML_TAGS, self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.activated.connect(self._insert_dropdown_completion)

    def _selection_color(self):
        """VS Code-like active/inactive selection colors."""
        if self.window() and self.window().isActiveWindow():
            return QColor("#264f78")    # active
        return QColor("#3a3d41")        # inactive gray

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.viewport().update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.viewport().update()

    def wheelEvent(self, event):
        """Ctrl+scroll to zoom editor font size."""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self._zoom_in_request()
            elif delta < 0:
                self._zoom_out_request()
            event.accept()
            return
        super().wheelEvent(event)

    def apply_theme(self, dark: bool):
        """Apply dark/light theme via app-level Fusion palette."""
        self._dark = dark
        _apply_fusion_palette(QApplication.instance(), dark)
        # Suppress Qt's native selection background on the editor only —
        # our custom overlay in paintEvent handles it with syntax colors.
        # HighlightedText stays as normal text color so text is never invisible.
        p = self.palette()
        p.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0, 0))
        p.setColor(QPalette.ColorRole.HighlightedText,
                    QColor("#d4d4d4") if dark else QColor("#1e1e1e"))
        self.setPalette(p)
        self._line_area.update()

    # ── Line numbers ──────────────────────────

    def line_number_area_width(self):
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance('9') * digits

    def _update_line_area_width(self):
        """Update only the left gutter margin.

        The previous bottom-margin version shrank the actual editing viewport,
        which left only about one visible line and made the rest of the editor
        appear cut off. Keep viewport margins for the line-number gutter only.
        """
        if self._updating_margins:
            return
        self._updating_margins = True
        try:
            left = self.line_number_area_width()
            self.setViewportMargins(left, 0, 0, 0)
        finally:
            self._updating_margins = False

    def _update_scroll_padding(self):
        """Give the last block real bottom margin so it can scroll to top.

        This avoids both failed approaches:
        - no bottom viewport margin, so the visible editor stays full height
        - no fake scrollbar maximum, so Qt never scrolls past layout geometry

        The padding is stored as formatting on the final text block. It does not
        change the plain text returned by toPlainText() or written to disk.
        """
        if self._updating_scroll_padding:
            return

        doc = self.document()
        last = doc.lastBlock()
        if not last.isValid():
            return

        padding = max(0, self.viewport().height() - self.fontMetrics().height() - 4)
        fmt = last.blockFormat()
        if abs(fmt.bottomMargin() - padding) < 1:
            return

        self._updating_scroll_padding = True
        try:
            old_modified = doc.isModified()
            cursor = QTextCursor(last)
            fmt.setBottomMargin(padding)

            # Block both widget AND document signals so setBlockFormat
            # doesn't trigger textChanged → mark_dirty
            blocker     = QSignalBlocker(self)
            doc_blocker = QSignalBlocker(doc)
            cursor.setBlockFormat(fmt)
            del doc_blocker
            del blocker

            doc.setModified(old_modified)
            self.viewport().update()
        finally:
            self._updating_scroll_padding = False

    def _update_line_area(self, rect, dy):
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        # Do not update viewport margins from updateRequest; that path is hot and
        # can produce visible geometry churn while scrolling.

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )
        self._update_line_area_width()
        self._update_scroll_padding()

    def paint_line_numbers(self, event):
        painter = QPainter(self._line_area)
        bg = QColor("#252526") if self._dark else QColor("#f0f0f0")
        fg = QColor("#858585") if self._dark else QColor("#999999")
        hl_bg = QColor("#2a2d32") if self._dark else QColor("#e4e4e4")
        hl_fg = QColor("#c6c6c6") if self._dark else QColor("#333333")
        sep = QColor("#3a3a3a") if self._dark else QColor("#cccccc")

        painter.fillRect(event.rect(), bg)

        # Draw separator line on the right edge
        sep_x = self._line_area.width() - 1
        painter.setPen(sep)
        painter.drawLine(sep_x, event.rect().top(), sep_x, event.rect().bottom())

        current_line = self.textCursor().blockNumber()
        block     = self.firstVisibleBlock()
        block_num = block.blockNumber()
        top    = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        lh     = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                is_current = block_num == current_line
                has_error  = (block_num + 1) in self._error_lines
                if is_current:
                    painter.fillRect(0, top, self._line_area.width() - 2, lh, hl_bg)
                painter.setPen(hl_fg if is_current else fg)
                painter.drawText(
                    0, top, self._line_area.width() - 8, lh,
                    Qt.AlignmentFlag.AlignRight, str(block_num + 1),
                )
                if has_error:
                    dot_size = 6
                    dot_x    = 3
                    dot_y    = top + (lh - dot_size) // 2
                    painter.setBrush(QColor("#f44747"))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(dot_x, dot_y, dot_size, dot_size)
            block     = block.next()
            top       = bottom
            bottom    = top + int(self.blockBoundingRect(block).height())
            block_num += 1

    # ── ExtraSelections management ──────────────

    def _refresh_extra_selections(self):
        """Merge spell underlines + find highlights into one ExtraSelections list."""
        self.setExtraSelections(self._spell_extra_selections + self._find_extra_selections)

    def set_find_extra_selections(self, selections):
        self._find_extra_selections = selections
        self._refresh_extra_selections()

    def clear_find_extra_selections(self):
        self._find_extra_selections = []
        self._refresh_extra_selections()

    def set_spell_extra_selections(self, selections, ranges=None):
        self._spell_extra_selections = selections
        self._spell_ranges = ranges or []
        self._refresh_extra_selections()
        self.viewport().update()

    def clear_spell_extra_selections(self):
        self._spell_extra_selections = []
        self._spell_ranges = []
        self._refresh_extra_selections()
        self.viewport().update()

    def set_error_lines(self, lines):
        """Set of 1-based line numbers that have tag errors (shown in gutter)."""
        self._error_lines = set(lines)
        self._line_area.update()

    def update_selection_highlight(self):
        """Selection is painted manually in paintEvent."""
        self.viewport().update()

    # ── Paint: selection overlay + color swatches ──

    def paintEvent(self, event):
        """Paint editor, then draw VS Code-style translucent selection overlay.

        Qt's native selection is suppressed by setting the selection format to
        transparent in the palette (see apply_theme). Our custom overlay paints
        the selection with proper syntax colors on top.
        """
        super().paintEvent(event)

        cursor = self.textCursor()
        if cursor.hasSelection():
            self._paint_selection_vscode_style(cursor)
            self._paint_indent_dots(cursor)

        self._paint_indent_guides()

        # Color swatch painting
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        block = self.firstVisibleBlock()
        while block.isValid():
            geom = self.blockBoundingGeometry(block).translated(self.contentOffset())
            if geom.top() > event.rect().bottom():
                break

            data = block.userData()
            if isinstance(data, ColorSwatchData) and data.swatches:
                for col, color in data.swatches:
                    c = self.textCursor()
                    c.setPosition(block.position() + col)
                    rect = self.cursorRect(c)

                    space_w = self.fontMetrics().horizontalAdvance(" ")

                    size = 9

                    # Center swatch inside the space before the color name
                    x = rect.x() - space_w + (space_w - size) // 2 - 1
                    y = rect.y() + (rect.height() - size) // 2

                    swatch_color = QColor(color)

                    # Smart border: light border for dark colors, dark for bright
                    if swatch_color.lightness() > 180:
                        border = QColor("#5a5a5a")
                    else:
                        border = QColor("#d4d4d4")

                    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                    painter.setPen(QPen(border, 1))
                    painter.setBrush(swatch_color)
                    painter.drawRect(x, y, size, size)

            block = block.next()

        painter.end()

        # ── Custom spell-check wave underline ──
        if self._spell_ranges:
            self._paint_spell_waves()

    def _paint_indent_guides(self):
        """Draw VS Code-style vertical indent guide lines every 4 spaces."""
        painter = QPainter(self.viewport())
        color   = QColor("#3a3a3a") if self._dark else QColor("#d0d0d0")
        painter.setPen(QPen(color, 1))

        content_offset = self.contentOffset()
        vp_rect        = self.viewport().rect()

        block = self.firstVisibleBlock()
        while block.isValid():
            geom = self.blockBoundingGeometry(block).translated(content_offset)
            if geom.top() > vp_rect.bottom():
                break
            if block.isVisible():
                text   = block.text()
                indent = len(text) - len(text.lstrip(' '))
                if indent > 0:
                    layout = block.layout()
                    if layout.lineCount() > 0:
                        line = layout.lineAt(0)
                        for level in range(0, indent + 1, 4):
                            x = int(geom.left() + line.cursorToX(level)[0])
                            painter.drawLine(x, int(geom.top()), x, int(geom.bottom()))
            block = block.next()

        painter.end()

    def _paint_indent_dots(self, cursor):
        """Draw pale dots over leading spaces in selected lines."""
        start = cursor.selectionStart()
        end   = cursor.selectionEnd()
        if start == end:
            return

        painter = QPainter(self.viewport())
        color   = QColor("#555555") if self._dark else QColor("#bbbbbb")
        painter.setPen(color)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        dot_r          = 1.5
        content_offset = self.contentOffset()
        doc            = self.document()

        block = doc.findBlock(start)
        while block.isValid() and block.position() <= end:
            text   = block.text()
            indent = len(text) - len(text.lstrip(' '))
            if indent > 0:
                geom   = self.blockBoundingGeometry(block).translated(content_offset)
                layout = block.layout()
                if layout.lineCount() > 0:
                    line = layout.lineAt(0)
                    cy   = geom.top() + line.y() + line.height() / 2
                    for i in range(indent):
                        # cursorToX gives the pixel position of the i-th character
                        x_left  = geom.left() + line.cursorToX(i)[0]
                        x_right = geom.left() + line.cursorToX(i + 1)[0]
                        cx      = (x_left + x_right) / 2
                        painter.drawEllipse(QPointF(cx, cy), dot_r, dot_r)
            block = block.next()

        painter.end()

    def _paint_spell_waves(self):
        """Draw a loose, large sine-wave underline under misspelled words."""
        import math as _math

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#ff2020"), 1.5))

        doc            = self.document()
        content_offset = self.contentOffset()
        vp_rect        = self.viewport().rect()

        amplitude  = 2.5    # px — height of the wave
        wavelength = 10.0   # px — larger = looser/wider cycles
        step       = 1.5    # px — sample interval (smaller = smoother)

        for start, end in self._spell_ranges:
            block = doc.findBlock(start)
            if not block.isValid():
                continue

            block_geom  = self.blockBoundingGeometry(block).translated(content_offset)
            layout      = block.layout()
            block_start = block.position()
            local_start = start - block_start
            local_end   = end   - block_start

            for li in range(layout.lineCount()):
                line = layout.lineAt(li)
                ls   = line.textStart()
                le   = ls + line.textLength()
                a    = max(local_start, ls)
                b    = min(local_end,   le)
                if a >= b:
                    continue

                x1 = block_geom.left() + line.cursorToX(a)[0]
                x2 = block_geom.left() + line.cursorToX(b)[0]
                y  = block_geom.top()  + line.y() + line.height() - 1

                if y < vp_rect.top() or y > vp_rect.bottom():
                    continue

                path  = QPainterPath()
                x     = x1
                first = True
                while x <= x2 + step:
                    wx = min(x, x2)
                    wy = y + amplitude * _math.sin((wx - x1) / wavelength * 2 * _math.pi)
                    if first:
                        path.moveTo(wx, wy)
                        first = False
                    else:
                        path.lineTo(wx, wy)
                    x += step

                painter.drawPath(path)

        painter.end()

    # ── Selection outline helpers ───────────────

    def _same_pt(self, a, b, eps=0.1):
        return abs(a.x() - b.x()) < eps and abs(a.y() - b.y()) < eps

    def _normalize_selection_rects(self, rects, snap_px=None):
        """Reduce tiny line-to-line width differences like VS Code."""
        if not rects:
            return []

        if snap_px is None:
            snap_px = self.fontMetrics().horizontalAdvance("M") * 1.5

        rs = [QRectF(r) for r in rects]

        for i in range(1, len(rs)):
            prev = rs[i - 1]
            cur = rs[i]

            if abs(cur.left() - prev.left()) <= snap_px:
                left = min(cur.left(), prev.left())
                cur.setLeft(left)
                prev.setLeft(left)

            if abs(cur.right() - prev.right()) <= snap_px:
                right = max(cur.right(), prev.right())
                cur.setRight(right)
                prev.setRight(right)

        for i in range(len(rs) - 2, -1, -1):
            nxt = rs[i + 1]
            cur = rs[i]

            if abs(cur.left() - nxt.left()) <= snap_px:
                left = min(cur.left(), nxt.left())
                cur.setLeft(left)
                nxt.setLeft(left)

            if abs(cur.right() - nxt.right()) <= snap_px:
                right = max(cur.right(), nxt.right())
                cur.setRight(right)
                nxt.setRight(right)

        return rs

    def _selection_outline_points(self, rects):
        """Build a single clockwise polygon around stacked selection rects."""
        if not rects:
            return []

        rs = [QRectF(r) for r in rects]
        pts = []

        first = rs[0]
        last = rs[-1]

        # Start at top-left, then go across the top of the first line.
        pts.append(QPointF(first.left(), first.top()))
        pts.append(QPointF(first.right(), first.top()))

        # Walk down the RIGHT edge
        for i, r in enumerate(rs):
            if i > 0:
                prev = rs[i - 1]
                y = r.top()
                if abs(prev.right() - r.right()) > 0.1:
                    pts.append(QPointF(prev.right(), y))
                    pts.append(QPointF(r.right(), y))
            pts.append(QPointF(r.right(), r.bottom()))

        # Bottom edge of the last line
        pts.append(QPointF(last.left(), last.bottom()))

        # Walk up the LEFT edge
        for i in range(len(rs) - 1, -1, -1):
            r = rs[i]
            if i < len(rs) - 1:
                nxt = rs[i + 1]
                y = nxt.top()
                if abs(nxt.left() - r.left()) > 0.1:
                    pts.append(QPointF(nxt.left(), y))
                    pts.append(QPointF(r.left(), y))
            pts.append(QPointF(r.left(), r.top()))

        # Remove consecutive duplicates
        clean = []
        for p in pts:
            if not clean or not self._same_pt(clean[-1], p):
                clean.append(p)

        if len(clean) > 1 and self._same_pt(clean[0], clean[-1]):
            clean.pop()

        return clean

    def _rounded_outline_path(self, points, radius):
        """Round every corner of a polygon using quadratic curves."""
        path = QPainterPath()
        if len(points) < 3:
            return path

        n = len(points)

        def inset_points(prev_p, cur_p, next_p):
            v1x = prev_p.x() - cur_p.x()
            v1y = prev_p.y() - cur_p.y()
            v2x = next_p.x() - cur_p.x()
            v2y = next_p.y() - cur_p.y()

            len1 = math.hypot(v1x, v1y)
            len2 = math.hypot(v2x, v2y)
            if len1 < 0.01 or len2 < 0.01:
                return cur_p, cur_p

            d = min(radius, len1 / 2.0, len2 / 2.0)

            p1 = QPointF(
                cur_p.x() + (v1x / len1) * d,
                cur_p.y() + (v1y / len1) * d,
            )
            p2 = QPointF(
                cur_p.x() + (v2x / len2) * d,
                cur_p.y() + (v2y / len2) * d,
            )
            return p1, p2

        prev_p = points[-1]
        cur_p = points[0]
        next_p = points[1]
        start_p, _ = inset_points(prev_p, cur_p, next_p)

        path.moveTo(start_p)

        for i in range(n):
            prev_p = points[i - 1]
            cur_p = points[i]
            next_p = points[(i + 1) % n]

            p1, p2 = inset_points(prev_p, cur_p, next_p)
            path.lineTo(p1)
            path.quadTo(cur_p, p2)

        path.closeSubpath()
        return path

    def _paint_selection_vscode_style(self, cursor):
        """Draw VS Code-style selection: connected background, then syntax text on top."""
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        if start == end:
            return

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        selection_color = self._selection_color()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(selection_color)

        doc = self.document()
        block = doc.findBlock(start)

        viewport_rect = self.viewport().rect()
        content_offset = self.contentOffset()

        selection_rects = []
        selected_line_paints = []

        while block.isValid() and block.position() < end:
            block_pos = block.position()
            block_len = block.length()
            block_text_len = max(0, block_len - 1)

            sel_start = max(start - block_pos, 0)
            sel_end = min(end - block_pos, block_text_len)

            if sel_start <= sel_end:
                block_geom = self.blockBoundingGeometry(block).translated(content_offset)
                layout = block.layout()

                for i in range(layout.lineCount()):
                    line = layout.lineAt(i)

                    line_start = line.textStart()
                    line_end = line_start + line.textLength()

                    a = max(sel_start, line_start)
                    b = min(sel_end, line_end)

                    if a > b:
                        continue

                    x1 = line.cursorToX(a)[0]
                    x2 = line.cursorToX(b)[0]

                    if b >= line_end:
                        x2 += 5

                    y = block_geom.top() + line.y()
                    h = line.height()

                    rect = QRectF(
                        block_geom.left() + x1,
                        y,
                        max(2.0, x2 - x1),
                        h,
                    )

                    if rect.toRect().intersects(viewport_rect):
                        # Slight horizontal inset only. Do NOT shrink vertically.
                        paint_rect = rect.adjusted(0.5, 0.0, -0.5, 0.0)

                        selection_rects.append(paint_rect)
                        selected_line_paints.append((block, block_geom, rect.toRect()))

            block = block.next()

        # Build one continuous selection shape with rounded inside/outside corners.
        radius = 3.0

        # VS Code-like: snap tiny one-character width differences
        selection_rects = self._normalize_selection_rects(selection_rects)

        outline_points = self._selection_outline_points(selection_rects)
        selection_path = self._rounded_outline_path(outline_points, radius)
        painter.fillPath(selection_path, selection_color)

        # Repaint selected text over the selection background.
        text_color = QColor("#d4d4d4") if self._dark else QColor("#1e1e1e")

        for block, block_geom, clip_rect in selected_line_paints:
            painter.save()
            painter.setClipRect(clip_rect)
            painter.setPen(text_color)

            block.layout().draw(
                painter,
                QPointF(block_geom.left(), block_geom.top())
            )

            painter.restore()

        painter.end()

    # ── Tag autocomplete ──────────────────────

    def _insert_dropdown_completion(self, completion):
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        cursor.removeSelectedText()
        if self._tag_mode != "manual" and not completion.startswith("/") and completion not in VOID_TAGS:
            cursor.insertText(f"{completion}></{completion}>")
            cursor.setPosition(cursor.position() - len(f"</{completion}>"))
        else:
            cursor.insertText(completion + ">")
        self.setTextCursor(cursor)

    def _handle_gt(self):
        if self._tag_mode != "auto":
            return
        cursor = self.textCursor()
        pos    = cursor.position()
        before = self.toPlainText()[:pos - 1]
        lt     = before.rfind('<')
        if lt == -1:
            return
        fragment = before[lt:]
        # Don't fire on closing tags like </i
        if fragment.startswith('</'):
            self._completer.popup().hide()
            return
        m = re.match(r'^<(\w[\w.-]*)(?:\s[^>]*)?$', fragment)
        if not m:
            return
        tag = m.group(1).lower()
        # Always hide completer when > is typed — void or not
        self._completer.popup().hide()
        if tag in VOID_TAGS:
            return
        cursor.insertText(f"</{tag}>")
        cursor.setPosition(pos)
        self.setTextCursor(cursor)

    def _handle_slash_after_lt(self):
        if self._tag_mode == "manual":
            return
        cursor = self.textCursor()
        pos    = cursor.position()
        tag    = find_unclosed_tag(self.toPlainText()[:pos - 2])
        if not tag:
            return
        self._completer.popup().hide()
        cursor.insertText(tag + ">")
        self.setTextCursor(cursor)

    def contextMenuEvent(self, event):
        """Standard context menu, extended with spell suggestions and rich copy."""
        menu = self.createStandardContextMenu()
        self._style_context_menu(menu)

        # Replace the standard Copy action with copy_rich
        for action in menu.actions():
            if action.text().replace('&', '') in ('Copy', 'Copy\tCtrl+C'):
                action.triggered.disconnect()
                action.triggered.connect(self.copy_rich)
                break

        mw = self.window()
        checker = getattr(mw, '_spell', None)
        if checker and checker.enabled:
            cursor = self.cursorForPosition(event.pos())
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            word = cursor.selectedText().strip("'")

            if word and not checker.check(word):
                spell_actions = []

                suggestions = checker.suggest(word)
                if suggestions:
                    for suggestion in suggestions:
                        act = QAction(suggestion, self)
                        act.setData((cursor, suggestion))
                        act.triggered.connect(self._apply_suggestion)
                        spell_actions.append(act)
                else:
                    no_act = QAction("(no suggestions)", self)
                    no_act.setEnabled(False)
                    spell_actions.append(no_act)

                add_act = QAction(f'Add "{word}" to dictionary', self)
                add_act.setData((checker, word))
                add_act.triggered.connect(self._add_to_dictionary)
                spell_actions.append(add_act)

                first = menu.actions()[0] if menu.actions() else None
                sep = menu.insertSeparator(first) if first else menu.addSeparator()
                for act in reversed(spell_actions):
                    menu.insertAction(sep, act)

        menu.exec(event.globalPos())

    def _style_context_menu(self, menu):
        """Apply a VS Code-inspired stylesheet to a QMenu."""
        # Strip icons — they add visual noise without benefit
        for action in menu.actions():
            action.setIcon(QIcon())

        dark = self._dark
        if dark:
            bg            = "#1e1e1e"
            bg_hover      = "#094771"
            border        = "#454545"
            text          = "#cccccc"
            text_disabled = "#666666"
            separator     = "#6a6a6a"
        else:
            bg            = "#ffffff"
            bg_hover      = "#0060c0"
            border        = "#c8c8c8"
            text          = "#1e1e1e"
            text_disabled = "#aaaaaa"
            separator     = "#c0c0c0"

        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {bg};
                border: 1px solid {border};
                padding: 4px 0px;
                font-size: 13px;
            }}
            QMenu::item {{
                color: {text};
                padding: 5px 32px 5px 16px;
                background: transparent;
            }}
            QMenu::item:selected {{
                background-color: {bg_hover};
                color: #ffffff;
            }}
            QMenu::item:disabled {{
                color: {text_disabled};
            }}
            QMenu::separator {{
                height: 2px;
                background: {separator};
                margin: 3px 0px;
            }}
        """)

    def _apply_suggestion(self):
        act = self.sender()
        cursor, suggestion = act.data()
        cursor.insertText(suggestion)
        self.setTextCursor(cursor)

    def _add_to_dictionary(self):
        act = self.sender()
        checker, word = act.data()
        checker.add(word)
        # Re-run spellcheck so the underline disappears immediately
        mw = self.window()
        if hasattr(mw, '_run_spellcheck'):
            mw._run_spellcheck()

    def _indent_selection(self, cursor, dedent=False):
        """Add or remove 4 leading spaces from every line in the selection."""
        doc        = self.document()
        sel_start  = cursor.selectionStart()
        sel_end    = cursor.selectionEnd()

        first_block = doc.findBlock(sel_start)
        last_block  = doc.findBlock(sel_end)
        # Don't process the last block if the selection ends at column 0
        if last_block.position() == sel_end and last_block != first_block:
            last_block = last_block.previous()

        cursor.beginEditBlock()
        block = first_block
        while block.isValid():
            bc = QTextCursor(block)
            if dedent:
                text = block.text()
                spaces = len(text) - len(text.lstrip(' '))
                remove = min(spaces, 4)
                if remove:
                    bc.movePosition(QTextCursor.MoveOperation.StartOfLine)
                    for _ in range(remove):
                        bc.deleteChar()
            else:
                bc.movePosition(QTextCursor.MoveOperation.StartOfLine)
                bc.insertText('    ')
            if block == last_block:
                break
            block = block.next()
        cursor.endEditBlock()

        # Re-select the same lines
        new_start = doc.findBlock(sel_start).position()
        new_end   = last_block.position() + last_block.length() - 1
        cursor.setPosition(new_start)
        cursor.setPosition(new_end, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def _try_expand_snippet(self):
        """If word before cursor matches a snippet trigger, expand it. Returns True if expanded."""
        mw  = self.window()
        mgr = getattr(mw, '_snippet_mgr', None)
        if not mgr:
            return False
        cursor = self.textCursor()
        pos    = cursor.position()
        text   = self.toPlainText()[:pos]

        # Take only the last whitespace-delimited token, then strip any
        # leading tag characters so "<li>steplink" → "steplink"
        m = re.search(r'(\S+)$', text)
        if not m:
            return False
        raw     = m.group(1)
        # Strip everything up to and including the last '>' so tags don't pollute the trigger
        gt = raw.rfind('>')
        trigger = raw[gt + 1:] if gt != -1 else raw
        if not trigger:
            return False

        snippet = mgr.find_by_trigger(trigger)
        if not snippet:
            return False

        # Delete only the trigger text (not any preceding tag), then insert
        cursor.setPosition(pos - len(trigger))
        cursor.setPosition(pos, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        mgr.insert_into_editor(snippet, self)
        return True

    def copy_rich(self):
        """Copy selected text to clipboard with syntax highlighting.

        Generates Chrome-compatible clipboard HTML (StartFragment/EndFragment
        markers) so Google Docs, Notion, etc. pick up the rich formatting.
        """
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return

        sel_start  = cursor.selectionStart()
        sel_end    = cursor.selectionEnd()
        doc        = self.document()
        dark       = self._dark
        bg_hex     = "#1e1e1e" if dark else "#ffffff"
        default_fg = "#d4d4d4" if dark else "#1e1e1e"
        font_face  = "Consolas, 'Courier New', monospace"

        # ── Build the inner HTML fragment ──────────────────────────────
        inner_parts = []
        block = doc.findBlock(sel_start)
        while block.isValid() and block.position() < sel_end:
            block_start = block.position()
            block_end   = block_start + block.length() - 1

            chunk_start = max(sel_start, block_start)
            chunk_end   = min(sel_end,   block_end)

            layout     = block.layout()
            formats    = layout.formats()
            block_text = block.text()

            # Per-character format map
            char_fmts = [None] * len(block_text)
            for fr in formats:
                for idx in range(fr.start, min(fr.start + fr.length, len(block_text))):
                    char_fmts[idx] = fr.format

            local_start = chunk_start - block_start
            local_end   = chunk_end   - block_start

            i = local_start
            while i < local_end:
                fmt = char_fmts[i]
                j = i + 1
                while j < local_end and char_fmts[j] == fmt:
                    j += 1

                chunk = (block_text[i:j]
                         .replace('&', '&amp;')
                         .replace('<', '&lt;')
                         .replace('>', '&gt;')
                         .replace(' ', '&nbsp;'))

                if fmt:
                    fg    = fmt.foreground().color()
                    style = f'color:{fg.name()};'
                    if fmt.fontWeight() >= 700:
                        style += 'font-weight:bold;'
                    if fmt.fontItalic():
                        style += 'font-style:italic;'
                    if fmt.fontUnderline():
                        style += 'text-decoration:underline;'
                    inner_parts.append(f'<span style="{style}">{chunk}</span>')
                else:
                    inner_parts.append(chunk)
                i = j

            if block.position() + block.length() - 1 < sel_end:
                inner_parts.append('<br style="margin:0;padding:0;line-height:1.4;">')

            block = block.next()

        inner_html = ''.join(inner_parts)

        # Wrap in a styled <div> so Google Docs picks up background + font
        fragment = (
            f'<div style="'
            f'background-color:{bg_hex};'
            f'color:{default_fg};'
            f'font-family:{font_face};'
            f'font-size:13px;'
            f'padding:8px;'
            f'margin:0;'
            f'border-radius:4px;'
            f'white-space:pre;'
            f'line-height:1.4;'
            f'">{inner_html}</div>'
        )

        # ── Chrome clipboard HTML format ────────────────────────────────
        # Chrome/Google Docs requires Version, StartHTML, EndHTML,
        # StartFragment, EndFragment byte offsets in a specific header.
        # We build the full document first, then calculate offsets.
        # ── Build clipboard HTML ────────────────────────────────────────
        # On Linux, text/html clipboard is plain HTML — no CF_HTML headers.
        # The Version:/StartHTML:/EndFragment: format is Windows-only and
        # causes Chrome on Linux to reject the clipboard data entirely.
        full_html = (
            '<html>\n'
            '<head><meta charset="UTF-8"></head>\n'
            '<body>\n'
            f'{fragment}\n'
            '</body>\n'
            '</html>'
        )

        # ── Put on clipboard ────────────────────────────────────────────
        from PyQt6.QtCore import QMimeData, QByteArray
        mime = QMimeData()
        mime.setText(cursor.selectedText()
                     .replace('\u2029', '\n')   # Qt paragraph separator → newline
                     .replace('\u2028', '\n'))   # Qt line separator → newline
        mime.setData("text/html", QByteArray(full_html.encode("utf-8")))
        QApplication.clipboard().setMimeData(mime)

    def keyPressEvent(self, event):
        # Ctrl+C — rich copy with syntax highlighting
        if (event.key() == Qt.Key.Key_C and
                event.modifiers() == Qt.KeyboardModifier.ControlModifier):
            self.copy_rich()
            return
        # Escape: cancel snippet session or close find bar
        if event.key() == Qt.Key.Key_Escape:
            session = getattr(self, '_snippet_session', None)
            if session and session.is_active:
                session.cancel()
                self._snippet_session = None
                return
            mw = self.window()
            if hasattr(mw, 'find_bar') and mw.find_bar.isVisible():
                mw.find_bar.hide_bar()
                return

        # Tab: advance active session → try trigger expansion → indent
        if event.key() == Qt.Key.Key_Tab and not self._completer.popup().isVisible():
            session = getattr(self, '_snippet_session', None)
            if session and session.is_active:
                more = session.advance()
                if not more:
                    self._snippet_session = None
                return
            if self._try_expand_snippet():
                return
            # Indent current line or all selected lines by 4 spaces
            cursor = self.textCursor()
            if cursor.hasSelection():
                self._indent_selection(cursor, dedent=False)
            else:
                cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
                cursor.insertText('    ')
            return

        # Shift+Tab: dedent current line or all selected lines by up to 4 spaces
        if event.key() == Qt.Key.Key_Backtab:
            cursor = self.textCursor()
            if cursor.hasSelection():
                self._indent_selection(cursor, dedent=True)
            else:
                text   = self.textCursor().block().text()
                spaces = len(text) - len(text.lstrip(' '))
                remove = min(spaces, 4)
                if remove:
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
                    for _ in range(remove):
                        cursor.deleteChar()
            return

        if self._completer.popup().isVisible():
            if event.key() in (
                Qt.Key.Key_Enter, Qt.Key.Key_Return,
                Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab,
            ):
                event.ignore()
                return

        # If Enter is pressed on the last block, clear scroll padding first
        # so Qt doesn't consume the keypress inside the padding space
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            doc    = self.document()
            cursor = self.textCursor()
            if cursor.block() == doc.lastBlock():
                last = doc.lastBlock()
                fmt  = last.blockFormat()
                if fmt.bottomMargin() > 0:
                    self._updating_scroll_padding = True
                    fmt.setBottomMargin(0)
                    c = QTextCursor(last)
                    blocker = QSignalBlocker(self)
                    c.setBlockFormat(fmt)
                    del blocker
                    doc.setModified(cursor.document().isModified())
                    self._updating_scroll_padding = False
        super().keyPressEvent(event)
        ch = event.text()
        if ch == '>':
            self._handle_gt()
        elif ch == '/':
            pos = self.textCursor().position()
            if pos >= 2 and self.toPlainText()[pos - 2] == '<':
                self._handle_slash_after_lt()
        else:
            self._maybe_show_dropdown()

    def _maybe_show_dropdown(self):
        if not self._completer_enabled:
            return
        cursor  = self.textCursor()
        pos     = cursor.position()
        before  = self.toPlainText()[:pos]
        last_lt = before.rfind('<')
        last_gt = before.rfind('>')
        if last_lt == -1 or last_gt > last_lt:
            self._completer.popup().hide()
            return
        after_lt = before[last_lt + 1:]
        if not re.match(r'^[\w]*$', after_lt):
            self._completer.popup().hide()
            return
        self._completer.setCompletionPrefix(after_lt)
        if self._completer.completionCount() == 0:
            self._completer.popup().hide()
            return
        popup = self._completer.popup()
        popup.setCurrentIndex(self._completer.completionModel().index(0, 0))
        cr = self.cursorRect()
        cr.setWidth(popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width())
        self._completer.complete(cr)


# ─────────────────────────────────────────────
#  Find bar  (Firefox-style, docked at bottom)
# ─────────────────────────────────────────────
class FindBar(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self._editor = editor
        self.setVisible(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(3)

        # ── Find row ──────────────────────────
        find_row = QHBoxLayout()
        find_row.setSpacing(4)

        self._close_btn = QToolButton()
        self._close_btn.setText("×")
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setAutoRaise(True)
        self._close_btn.setToolTip("Close (Esc)")
        self._close_btn.clicked.connect(self.hide_bar)
        find_row.addWidget(self._close_btn)

        find_row.addWidget(QLabel("Find:"))

        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Search…")
        self.find_input.setMinimumWidth(180)
        self.find_input.returnPressed.connect(self.find_next)
        self.find_input.textChanged.connect(self._highlight_all)
        self.find_input.installEventFilter(self)
        find_row.addWidget(self.find_input, 1)

        self._prev_btn = QToolButton()
        self._prev_btn.setText("▲")
        self._prev_btn.setAutoRaise(True)
        self._prev_btn.setToolTip("Previous (Shift+Enter)")
        self._prev_btn.clicked.connect(self.find_prev)
        find_row.addWidget(self._prev_btn)

        self._next_btn = QToolButton()
        self._next_btn.setText("▼")
        self._next_btn.setAutoRaise(True)
        self._next_btn.setToolTip("Next (Enter)")
        self._next_btn.clicked.connect(self.find_next)
        find_row.addWidget(self._next_btn)

        self.case_cb = QCheckBox("Aa")
        self.case_cb.setToolTip("Case sensitive")
        self.case_cb.toggled.connect(self._highlight_all)
        find_row.addWidget(self.case_cb)

        self._status_lbl = QLabel("")
        self._status_lbl.setMinimumWidth(90)
        find_row.addWidget(self._status_lbl)
        find_row.addStretch()

        outer.addLayout(find_row)

        # ── Replace row (hidden in find-only mode) ─
        self._replace_row = QWidget()
        rr = QHBoxLayout(self._replace_row)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.setSpacing(4)

        rr.addWidget(QLabel("Replace:"))

        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Replace with…")
        self.replace_input.setMinimumWidth(180)
        self.replace_input.returnPressed.connect(self.replace_one)
        self.replace_input.installEventFilter(self)
        rr.addWidget(self.replace_input, 1)

        self._replace_btn = QPushButton("Replace")
        self._replace_btn.clicked.connect(self.replace_one)
        rr.addWidget(self._replace_btn)

        self._replace_all_btn = QPushButton("Replace All")
        self._replace_all_btn.clicked.connect(self.replace_all)
        rr.addWidget(self._replace_all_btn)

        self.regex_cb = QCheckBox(".*")
        self.regex_cb.setToolTip("Regular expression")
        rr.addWidget(self.regex_cb)

        rr.addStretch()

        self._replace_row.setVisible(False)
        outer.addWidget(self._replace_row)

    # ── Public show/hide ──────────────────────

    def show_find(self):
        self._replace_row.setVisible(False)
        self.setVisible(True)
        self.find_input.setFocus()
        self.find_input.selectAll()
        self._highlight_all()

    def show_replace(self):
        self._replace_row.setVisible(True)
        self.setVisible(True)
        self.find_input.setFocus()
        self.find_input.selectAll()
        self._highlight_all()

    def hide_bar(self):
        self.setVisible(False)
        self._editor.clear_find_extra_selections()
        self._editor.setFocus()

    # ── Event filter: Esc / Shift+Enter in inputs ─

    def eventFilter(self, obj, event):
        if event.type() == event.Type.KeyPress:
            inputs = [self.find_input]
            if hasattr(self, 'replace_input'):
                inputs.append(self.replace_input)
            if obj in inputs:
                if event.key() == Qt.Key.Key_Escape:
                    self.hide_bar()
                    return True
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                        self.find_prev()
                        return True
        return super().eventFilter(obj, event)

    # ── Internals ─────────────────────────────

    def _find_flags(self, backward=False):
        flags = QTextDocument.FindFlag(0)
        if self.case_cb.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        return flags

    def _highlight_all(self):
        term = self.find_input.text()
        selections = []
        count = 0
        if term:
            doc   = self._editor.document()
            flags = QTextDocument.FindFlag(0)
            if self.case_cb.isChecked():
                flags |= QTextDocument.FindFlag.FindCaseSensitively
            cursor = QTextCursor(doc)
            while True:
                cursor = doc.find(term, cursor, flags)
                if cursor.isNull():
                    break
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(QColor("#614d15"))
                sel.format.setForeground(QColor("#ffffff"))
                sel.cursor = cursor
                selections.append(sel)
                count += 1
        self._editor.set_find_extra_selections(selections)
        if term:
            self._status_lbl.setText(
                f"{count} match{'es' if count != 1 else ''}" if count else "No results"
            )
        else:
            self._status_lbl.setText("")

    def find_next(self):
        t = self.find_input.text()
        if not t:
            return
        found = self._editor.find(t, self._find_flags())
        if not found:
            cursor = self._editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self._editor.setTextCursor(cursor)
            found = self._editor.find(t, self._find_flags())
        if not found:
            self._status_lbl.setText("No results")

    def find_prev(self):
        t = self.find_input.text()
        if not t:
            return
        found = self._editor.find(t, self._find_flags(backward=True))
        if not found:
            cursor = self._editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._editor.setTextCursor(cursor)
            found = self._editor.find(t, self._find_flags(backward=True))
        if not found:
            self._status_lbl.setText("No results")

    def replace_one(self):
        cursor = self._editor.textCursor()
        t = self.find_input.text()
        if cursor.hasSelection() and cursor.selectedText() == t:
            cursor.insertText(self.replace_input.text())
        self.find_next()

    def replace_all(self):
        term = self.find_input.text()
        if not term:
            return
        flags = 0 if self.case_cb.isChecked() else re.IGNORECASE
        pat   = term if self.regex_cb.isChecked() else re.escape(term)
        new_content, count = re.subn(
            pat, self.replace_input.text(),
            self._editor.toPlainText(), flags=flags,
        )
        if count:
            # Use cursor select-all + insertText to preserve undo history
            cursor = self._editor.textCursor()
            cursor.beginEditBlock()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertText(new_content)
            cursor.endEditBlock()
        self._status_lbl.setText(f"Replaced {count}")


# ─────────────────────────────────────────────
#  Snippet system
# ─────────────────────────────────────────────
class SnippetSession:
    """Manages active tabstop navigation after a snippet is inserted.

    Body syntax:
      $1, $2 … numbered tabstops; Tab advances through them in order.
      Same number = mirrored: when you Tab away, the typed text is
      copied to every other occurrence of that number automatically.
      $0 = final cursor position (always last).
      Legacy | = single tabstop (still supported).
    """

    def __init__(self, editor, absolute_stops, end_cursor):
        """absolute_stops: list of (stop_num, doc_char_pos) in body order.
        end_cursor: live QTextCursor just after the snippet — Qt keeps it
                    updated as mirror insertions shift the document.
        """
        self._editor     = editor
        self._end_cursor = end_cursor   # live — drifts correctly with inserts
        doc              = editor.document()

        # Build live QTextCursor objects (Qt auto-updates them on edits)
        from collections import defaultdict
        groups = defaultdict(list)
        for num, pos in absolute_stops:
            c = QTextCursor(doc)
            c.setPosition(pos)
            groups[num].append(c)

        # Ordered unique stop numbers; $0 always last
        nums = sorted(set(n for n, _ in absolute_stops))
        if 0 in nums:
            nums.remove(0)
            nums.append(0)

        self._stop_order    = nums
        self._groups        = dict(groups)
        self._current_idx   = 0
        self._anchor_pos    = None   # plain int — immune to Qt cursor drift
        self._active        = True

    def start(self):
        self._goto_stop(0)

    def _goto_stop(self, idx):
        self._current_idx = idx
        if idx >= len(self._stop_order):
            self._active = False
            return
        num     = self._stop_order[idx]
        cursors = self._groups.get(num, [])
        if not cursors:
            self._active = False
            return
        self._editor.setTextCursor(cursors[0])
        # Save as plain int — a live QTextCursor drifts forward when the user types
        self._anchor_pos = cursors[0].position()

    def advance(self):
        """Sync mirrors then move to next stop. Returns True if more stops remain."""
        if not self._active:
            return False

        num     = self._stop_order[self._current_idx]
        mirrors = self._groups.get(num, [])[1:]   # skip primary

        if mirrors and self._anchor_pos is not None:
            current_pos = self._editor.textCursor().position()
            typed = ""
            if current_pos > self._anchor_pos:
                typed = self._editor.document().toPlainText()[
                    self._anchor_pos:current_pos
                ]
            # Insert at mirrors in reverse document order to keep earlier offsets valid
            for mc in sorted(mirrors, key=lambda c: c.position(), reverse=True):
                mc.insertText(typed)

        next_idx = self._current_idx + 1
        if next_idx >= len(self._stop_order):
            self._active = False
            # Land cursor just after the snippet using the live end cursor
            c = QTextCursor(self._editor.document())
            c.setPosition(self._end_cursor.position())
            self._editor.setTextCursor(c)
            return False

        self._goto_stop(next_idx)
        return True

    def cancel(self):
        self._active = False

    @property
    def is_active(self):
        return self._active


class SnippetManager:
    """Loads/saves snippets from ~/.config/jackdaw/snippets.json.

    Body syntax:
      $1, $2 … numbered tabstops (same number = mirrored).
      $0      = final cursor position.
      |       = legacy single-cursor marker.
    """

    def __init__(self):
        self._path  = os.path.join(get_config_dir(), "snippets.json")
        self._items = []
        self._load()

    # ── Persistence ───────────────────────────

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, encoding="utf-8") as f:
                    data = json.load(f)
                # If any snippet still uses legacy | syntax and no $N, migrate to defaults
                if isinstance(data, list) and data:
                    has_tabstop = any('$' in s.get('body', '') for s in data)
                    if has_tabstop:
                        self._items = data
                        return
            except Exception:
                pass
        self._items = self._defaults()
        self._save()

    def _save(self):
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._items, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _defaults(self):
        return [
            {"name": "Link",
             "trigger": "link",
             "body": '<a href="$1" target="_blank">$2</a>'},
            {"name": "Note paragraph",
             "trigger": "note",
             "body": '<p><strong>Note:</strong> $1</p>'},
            {"name": "Bold",
             "trigger": "bold",
             "body": "<b>$1</b>"},
            {"name": "Italic",
             "trigger": "ital",
             "body": "<i>$1</i>"},
            {"name": "Image",
             "trigger": "img",
             "body": '<img src="$1" alt="$2">'},
        ]

    # ── API ───────────────────────────────────

    @property
    def snippets(self):
        return list(self._items)

    def find_by_trigger(self, trigger):
        for s in self._items:
            if s.get("trigger", "").lower() == trigger.lower():
                return s
        return None

    def add(self, snippet):
        self._items.append(snippet)
        self._save()

    def update(self, index, snippet):
        if 0 <= index < len(self._items):
            self._items[index] = snippet
            self._save()

    def remove(self, index):
        if 0 <= index < len(self._items):
            self._items.pop(index)
            self._save()

    def export_to_file(self, path):
        """Write snippets to a shareable JSON file. Returns (ok, error_msg)."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._items, f, indent=2, ensure_ascii=False)
            return True, ""
        except Exception as e:
            return False, str(e)

    def import_from_file(self, path, merge=True):
        """Load snippets from a JSON file.
        merge=True  → add new snippets, skip duplicates by trigger.
        merge=False → replace all snippets.
        Returns (added_count, skipped_count, error_msg).
        """
        try:
            with open(path, encoding="utf-8") as f:
                incoming = json.load(f)
            if not isinstance(incoming, list):
                return 0, 0, "File does not contain a snippet list."
        except Exception as e:
            return 0, 0, str(e)

        if not merge:
            self._items = incoming
            self._save()
            return len(incoming), 0, ""

        existing_triggers = {s.get("trigger", "").lower() for s in self._items}
        added = skipped = 0
        for s in incoming:
            if not isinstance(s, dict):
                continue
            t = s.get("trigger", "").lower()
            if t and t in existing_triggers:
                skipped += 1
            else:
                self._items.append(s)
                existing_triggers.add(t)
                added += 1
        self._save()
        return added, skipped, ""

    def insert_into_editor(self, snippet, editor):
        """Insert snippet body at cursor and start a SnippetSession."""
        body    = snippet.get("body", "")
        pattern = re.compile(r'\$(\d+)')

        # Build clean text and record tabstop positions within it
        clean       = ""
        tab_in_body = []   # (stop_num, char_pos_in_clean)
        last        = 0
        for m in pattern.finditer(body):
            clean += body[last:m.start()]
            tab_in_body.append((int(m.group(1)), len(clean)))
            last = m.end()
        clean += body[last:]

        # Legacy | marker fallback
        if not tab_in_body and '|' in clean:
            idx   = clean.index('|')
            clean = clean[:idx] + clean[idx + 1:]
            tab_in_body = [(1, idx)]

        cursor     = editor.textCursor()
        insert_pos = cursor.position()
        cursor.insertText(clean)

        # Live cursor at the end — Qt will push it forward as mirrors insert text
        end_cursor = QTextCursor(editor.document())
        end_cursor.setPosition(insert_pos + len(clean))

        if tab_in_body:
            absolute = [(num, insert_pos + rel) for num, rel in tab_in_body]
            session  = SnippetSession(editor, absolute, end_cursor)
            editor._snippet_session = session
            session.start()
        else:
            cursor.setPosition(insert_pos + len(clean))
            editor.setTextCursor(cursor)

        editor.setFocus()


class SnippetEditDialog(QDialog):
    """Add / edit a single snippet."""

    def __init__(self, snippet=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Snippet" if snippet else "New Snippet")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)

        # Name + trigger on one row
        top = QHBoxLayout()

        name_col = QVBoxLayout()
        name_col.addWidget(QLabel("Name:"))
        self._name = QLineEdit(snippet.get("name", "") if snippet else "")
        name_col.addWidget(self._name)
        top.addLayout(name_col, 2)

        trigger_col = QVBoxLayout()
        trigger_col.addWidget(QLabel("Trigger  (type then Tab to expand):"))
        self._trigger = QLineEdit(snippet.get("trigger", "") if snippet else "")
        trigger_col.addWidget(self._trigger)
        top.addLayout(trigger_col, 1)

        layout.addLayout(top)

        layout.addWidget(QLabel("Body  ( $1 $2 … = tabstops; same number = mirrored; $0 = final position ):"))
        self._body = QPlainTextEdit()
        self._body.setFont(QFont(MONO_FONT, 10))
        self._body.setPlainText(snippet.get("body", "") if snippet else "")
        self._body.setMinimumHeight(110)
        layout.addWidget(self._body)

        btns = QHBoxLayout()
        btns.addStretch()
        ok  = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        can = QPushButton("Cancel")
        can.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(can)
        layout.addLayout(btns)

    def _accept(self):
        if not self._name.text().strip():
            self._name.setFocus()
            return
        self.accept()

    def get_snippet(self):
        return {
            "name":    self._name.text().strip(),
            "trigger": self._trigger.text().strip(),
            "body":    self._body.toPlainText(),
        }


class ManageSnippetsDialog(QDialog):
    """List all snippets with Add / Edit / Delete controls."""

    def __init__(self, mgr, parent=None):
        super().__init__(parent)
        self._mgr = mgr
        self.setWindowTitle("Manage Snippets")
        self.setMinimumSize(520, 340)

        layout = QVBoxLayout(self)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._edit)
        layout.addWidget(self._list)

        hint = QLabel("Tip: type the trigger word then Tab to expand.  "
                      "In the body: $1 $2 … are tabstops; Tab advances between them.  "
                      "Same number ($1 … $1) = mirrored — typed text copies to both.  "
                      "$0 = final cursor position.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btns = QHBoxLayout()
        for label, slot in [("Add", self._add), ("Edit", self._edit), ("Delete", self._delete)]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch()
        imp_btn = QPushButton("Import…")
        imp_btn.clicked.connect(self._import)
        btns.addWidget(imp_btn)
        exp_btn = QPushButton("Export…")
        exp_btn.clicked.connect(self._export)
        btns.addWidget(exp_btn)
        btns.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        btns.addWidget(close)
        layout.addLayout(btns)

        self._refresh()

    def _refresh(self):
        self._list.clear()
        for s in self._mgr.snippets:
            name    = s.get("name", "")
            trigger = s.get("trigger", "")
            body    = s.get("body", "").replace("\n", " ")[:50]
            label   = f"{name}"
            if trigger:
                label += f"  [{trigger}]"
            label += f"  →  {body}"
            self._list.addItem(label)

    def _add(self):
        dlg = SnippetEditDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._mgr.add(dlg.get_snippet())
            self._refresh()

    def _edit(self):
        idx = self._list.currentRow()
        if idx < 0:
            return
        dlg = SnippetEditDialog(snippet=self._mgr.snippets[idx], parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._mgr.update(idx, dlg.get_snippet())
            self._refresh()

    def _delete(self):
        idx = self._list.currentRow()
        if idx < 0:
            return
        name  = self._mgr.snippets[idx].get("name", "snippet")
        reply = QMessageBox.question(
            self, "Delete Snippet", f'Delete "{name}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._mgr.remove(idx)
            self._refresh()

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Snippets", "jackdaw-snippets.json",
            "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        ok, err = self._mgr.export_to_file(path)
        if ok:
            QMessageBox.information(self, "Export",
                f"Exported {len(self._mgr.snippets)} snippet(s) to:\n{path}")
        else:
            QMessageBox.warning(self, "Export Failed", err)

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Snippets", "",
            "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        # Use custom buttons since StandardButton doesn't have Merge/Replace
        msg = QMessageBox(self)
        msg.setWindowTitle("Import Mode")
        msg.setText(
            "How would you like to import?\n\n"
            "Merge — add new snippets, skip duplicates\n"
            "Replace — discard all current snippets"
        )
        merge_btn   = msg.addButton("Merge",   QMessageBox.ButtonRole.AcceptRole)
        replace_btn = msg.addButton("Replace", QMessageBox.ButtonRole.DestructiveRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked is None or clicked.text() == "Cancel":
            return
        merge = clicked is merge_btn

        added, skipped, err = self._mgr.import_from_file(path, merge=merge)
        if err:
            QMessageBox.warning(self, "Import Failed", err)
        else:
            detail = f"Added: {added}"
            if merge and skipped:
                detail += f"\nSkipped (duplicate trigger): {skipped}"
            QMessageBox.information(self, "Import Complete", detail)
        self._refresh()


# ─────────────────────────────────────────────
#  Validation panel  (docked at bottom)
# ─────────────────────────────────────────────
class ValidationPanel(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self._editor = editor
        self.setVisible(False)
        self.setMaximumHeight(160)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header bar ────────────────────────
        header = QWidget()
        header.setObjectName("ValHeader")
        hr = QHBoxLayout(header)
        hr.setContentsMargins(8, 3, 4, 3)

        self._title_lbl = QLabel("HTML Issues")
        self._title_lbl.setStyleSheet("font-weight: bold;")
        hr.addWidget(self._title_lbl)
        hr.addStretch()

        close_btn = QToolButton()
        close_btn.setText("×")
        close_btn.setFixedSize(20, 20)
        close_btn.setAutoRaise(True)
        close_btn.clicked.connect(self.hide)
        hr.addWidget(close_btn)

        layout.addWidget(header)

        # ── Error list ────────────────────────
        self._list = QListWidget()
        self._list.setFrameShape(QListWidget.Shape.NoFrame)
        self._list.itemClicked.connect(self._jump_to_line)
        layout.addWidget(self._list)

    def set_errors(self, errors):
        """errors: list of (lineno, message)."""
        self._list.clear()
        if not errors:
            self._title_lbl.setText("HTML Issues — ✓ No problems found")
            return

        count = len(errors)
        self._title_lbl.setText(
            f"HTML Issues — {count} problem{'s' if count != 1 else ''}"
        )
        for lineno, msg in errors:
            item = QListWidgetItem(f"  Line {lineno}:  {msg}")
            item.setData(Qt.ItemDataRole.UserRole, lineno)
            item.setForeground(QColor("#f44747"))
            self._list.addItem(item)

    def _jump_to_line(self, item):
        lineno = item.data(Qt.ItemDataRole.UserRole)
        if lineno is None:
            return
        doc    = self._editor.document()
        block  = doc.findBlockByLineNumber(lineno - 1)
        if block.isValid():
            cursor = QTextCursor(block)
            self._editor.setTextCursor(cursor)
            self._editor.ensureCursorVisible()
            self._editor.centerCursor()
            self._editor.setFocus()

    def apply_theme(self, dark):
        bg     = "#1e1e1e" if dark else "#f5f5f5"
        border = "#3a3a3a" if dark else "#cccccc"
        fg     = "#d4d4d4" if dark else "#1e1e1e"
        item_bg = "#252526" if dark else "#ffffff"
        self.setStyleSheet(f"""
            ValidationPanel {{
                background: {bg};
            }}
            QWidget#ValHeader {{
                background: {bg};
                border-top: 1px solid {border};
            }}
            QListWidget {{
                background: {item_bg};
                color: {fg};
                border-top: 1px solid {border};
            }}
            QListWidget::item:selected {{
                background: #264f78;
                color: #ffffff;
            }}
            QListWidget::item:hover {{
                background: {"#2a2d35" if dark else "#e8e8e8"};
            }}
        """)


# ─────────────────────────────────────────────
#  Main window
# ─────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jackdaw")

        # ── Settings ──────────────────────────────────────────────────
        self._s = QSettings("jackdaw", "jackdaw")
        if self._s.value("settings_version", 0, type=int) < SETTINGS_VERSION:
            self._s.clear()
            self._s.setValue("settings_version", SETTINGS_VERSION)

        self._editor_dark    = self._s.value("editor_dark",    True,  type=bool)
        self._preview_dark   = self._s.value("preview_dark",   False, type=bool)
        self._font_size      = self._s.value("font_size",      11,    type=int)
        self._editor_zoom    = self._s.value("editor_zoom",    1.0,   type=float)
        self._preview_zoom   = self._s.value("preview_zoom",   1.0,   type=float)
        self._sync_scroll    = self._s.value("sync_scroll",    True,  type=bool)
        self._sync_click     = self._s.value("sync_click",     True,  type=bool)
        self._word_wrap      = self._s.value("word_wrap",      False,  type=bool)
        self._tag_mode       = self._s.value("tag_mode",       "auto", type=str)
        if self._tag_mode not in ("manual", "smart", "auto"):
            self._tag_mode = "auto"
        self._tag_completer  = self._s.value("tag_completer",  True,   type=bool)
        self._spell_enabled  = self._s.value("spell_enabled",  True,   type=bool)
        self._val_enabled    = self._s.value("val_enabled",    True,  type=bool)

        self._spell = SpellChecker()
        if self._spell.available:
            self._spell.enabled = self._spell_enabled

        self._snippet_mgr = SnippetManager()

        self._tabs: list[TabData] = []
        self._cur_idx             = -1
        self._syncing_to_preview  = False

        self._cursor_indicator_timer = QTimer(singleShot=True, interval=500)
        self._cursor_indicator_timer.timeout.connect(self._sync_cursor_to_preview)

        self._build_ui()
        self._build_menus()
        self._apply_tabbar_style()
        self.setStatusBar(QStatusBar())
        self._setup_webchannel()

        if self._s.contains("geometry"):
            self.restoreGeometry(self._s.value("geometry"))
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            w = min(int(screen.width()  * 0.80), 1400)
            h = min(int(screen.height() * 0.75), 860)
            self.resize(w, h)
            self.move(
                screen.x() + (screen.width()  - w) // 2,
                screen.y() + (screen.height() - h) // 2,
            )
        if self._s.contains("splitter"):
            self.splitter.restoreState(self._s.value("splitter"))

        self._preview_timer = QTimer(singleShot=True, interval=800)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self.editor.textChanged.connect(self._on_doc_changed)
        self.editor.textChanged.connect(self._preview_timer.start)
        self.editor.cursorPositionChanged.connect(self._update_status)
        self.editor.cursorPositionChanged.connect(self._on_cursor_moved)
        self.editor.verticalScrollBar().valueChanged.connect(self._editor_scrolled)
        self.editor.selectionChanged.connect(self.editor.update_selection_highlight)

        self._spell_timer = QTimer(singleShot=True, interval=800)
        self._spell_timer.timeout.connect(self._run_spellcheck)
        self.editor.textChanged.connect(self._on_text_changed_spell)
        self.editor.textChanged.connect(self._on_text_changed_find)

        self._val_timer = QTimer(singleShot=True, interval=600)
        self._val_timer.timeout.connect(self._run_validation)
        self.editor.textChanged.connect(self._val_timer.start)

        # Wire editor Ctrl+scroll to zoom
        self.editor._zoom_in_request = self.editor_zoom_in
        self.editor._zoom_out_request = self.editor_zoom_out

        self._session_timer = QTimer(interval=30_000)
        self._session_timer.timeout.connect(self._save_session)
        self._session_timer.start()

        self._restore_session()

        # Delay initial preview — QWebEngineView isn't ready during __init__
        QTimer.singleShot(300, self._refresh_preview)

    # ── Build UI ───────────────────────────────

    def _build_ui(self):
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll   = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)

        self.tab_strip = QWidget()
        self.tab_strip.setObjectName("TabStrip")

        tab_row = QHBoxLayout(self.tab_strip)
        tab_row.setContentsMargins(4, 0, 4, 0)
        tab_row.setSpacing(1)

        self.tab_bar = QTabBar()
        self.tab_bar.setTabsClosable(False)
        self.tab_bar.setMovable(True)
        self.tab_bar.setExpanding(False)
        self.tab_bar.setDocumentMode(False)
        self.tab_bar.setDrawBase(False)
        self.tab_bar.setUsesScrollButtons(True)
        self.tab_bar.setElideMode(Qt.TextElideMode.ElideRight)
        self.tab_bar.currentChanged.connect(self._on_tab_changed)
        self.tab_bar.tabMoved.connect(self._on_tab_moved)
        self.tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_bar.customContextMenuRequested.connect(self._on_tabbar_context_menu)

        self.new_tab_btn = QToolButton()
        self.new_tab_btn.setObjectName("BrowserNewTab")
        self.new_tab_btn.setText("+")
        self.new_tab_btn.setAutoRaise(True)
        self.new_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_tab_btn.setToolTip("New Tab (Ctrl+T)")
        self.new_tab_btn.clicked.connect(lambda: self._new_tab())

        self.tab_strip.setFixedHeight(30)
        self.tab_bar.setFixedHeight(28)
        self.new_tab_btn.setFixedSize(24, 24)

        tab_row.addWidget(self.tab_bar, 0, Qt.AlignmentFlag.AlignBottom)
        tab_row.addWidget(self.new_tab_btn, 0, Qt.AlignmentFlag.AlignBottom)
        tab_row.addStretch(1)

        ll.addWidget(self.tab_strip)

        self.editor = HTMLEditor()
        self.editor._tag_mode          = self._tag_mode
        self.editor._completer_enabled = self._tag_completer
        self.editor.apply_theme(self._editor_dark)
        # Single highlighter — re-attached after every tab switch
        self._highlighter = HTMLHighlighter(self.editor.document(), dark=self._editor_dark)
        if self._word_wrap:
            self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        font = QFont(MONO_FONT, self._font_size)
        self.editor.setFont(font)
        if self._editor_zoom != 1.0:
            self.editor.setStyleSheet(
                f"QPlainTextEdit {{ font-size: {self._font_size * self._editor_zoom:.1f}pt; }}"
            )
        ll.addWidget(self.editor)

        self.find_bar = FindBar(self.editor)
        ll.addWidget(self.find_bar)

        self.val_panel = ValidationPanel(self.editor)
        self.val_panel.apply_theme(self._editor_dark)
        ll.addWidget(self.val_panel)

        self.preview = QWebEngineView()
        # Install event filter on preview's internal widget for Ctrl+scroll
        self.preview.installEventFilter(self)
        QTimer.singleShot(500, self._install_preview_wheel_filter)
        self.preview.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self.preview.setZoomFactor(self._preview_zoom)

        self.splitter.addWidget(left)
        self.splitter.addWidget(self.preview)
        self.splitter.setSizes([720, 720])
        self.setCentralWidget(self.splitter)

    # ── Tab management ─────────────────────────

    def _save_current_tab_state(self):
        if 0 <= self._cur_idx < len(self._tabs):
            tab = self._tabs[self._cur_idx]
            tab.content = self.editor.toPlainText()
            tab.cursor_pos = self.editor.textCursor().position()
            tab.scroll_value = self.editor.verticalScrollBar().value()

    def _attach_tab(self, index: int, save_current=True):
        if index < 0 or index >= len(self._tabs):
            return

        if save_current and self._cur_idx != index:
            self._save_current_tab_state()

        self._cur_idx = index
        tab = self._tabs[index]

        # Load this tab's content into the editor.
        blocker = QSignalBlocker(self.editor)
        self.editor.setPlainText(tab.content)
        del blocker

        self._highlighter.rehighlight()

        cursor = self.editor.textCursor()
        cursor.setPosition(min(tab.cursor_pos, len(tab.content)))
        self.editor.setTextCursor(cursor)

        self.editor.verticalScrollBar().setValue(tab.scroll_value)
        self.editor._update_line_area_width()
        self.editor._update_scroll_padding()
        self.editor.viewport().update()

        self.setWindowTitle(f"Jackdaw — {tab.path or 'Untitled'}")
        self._preview_initialized = False
        self._refresh_preview()
        self._spell_timer.start()
        self._val_timer.start()

    def _new_tab(self, path=None, content=""):
        self._save_current_tab_state()

        tab = TabData(path=path, content=content or "")
        tab.mark_clean()

        self._tabs.append(tab)
        index = len(self._tabs) - 1

        blocker = QSignalBlocker(self.tab_bar)
        self.tab_bar.addTab(tab.title)
        self._install_tab_close_button(index)
        self.tab_bar.setCurrentIndex(index)
        del blocker

        self.tab_bar.setVisible(True)
        self.tab_bar.updateGeometry()
        self.tab_strip.updateGeometry()
        self.tab_strip.update()

        self._attach_tab(index, save_current=False)

        return tab

    def _on_doc_changed(self):
        tab = self._current_tab()
        if not tab:
            return
        new_content = self.editor.toPlainText()
        if new_content == tab.content:
            return   # formatting/scroll-padding change, not actual text
        tab.content = new_content
        tab.mark_dirty()
        idx = self._tabs.index(tab)
        self._update_tab(idx)
        self._preview_timer.start()

    def _on_tab_changed(self, new_idx: int):
        self._attach_tab(new_idx, save_current=True)

    def _on_tab_moved(self, from_idx, to_idx):
        self._tabs.insert(to_idx, self._tabs.pop(from_idx))
        self._cur_idx = to_idx

    def _on_tabbar_context_menu(self, pos):
        idx = self.tab_bar.tabAt(pos)
        if idx == -1:
            return
        menu = QMenu(self)
        self.editor._style_context_menu(menu)
        rename_act = menu.addAction("Rename Tab…")
        menu.addSeparator()
        close_act = menu.addAction("Close Tab")
        action = menu.exec(self.tab_bar.mapToGlobal(pos))
        if action == rename_act:
            self._rename_tab(idx)
        elif action == close_act:
            self._close_tab(idx)

    def _rename_tab(self, idx=None):
        if idx is None:
            idx = self.tab_bar.currentIndex()
        if not (0 <= idx < len(self._tabs)):
            return
        tab = self._tabs[idx]
        current = tab.custom_name or (os.path.basename(tab.path) if tab.path else "Untitled")
        name, ok = QInputDialog.getText(
            self, "Rename Tab", "Tab name:", text=current
        )
        if ok and name.strip():
            tab.custom_name = name.strip()
            self._update_tab(idx)

    def _make_tab_close_button(self):
        btn = QToolButton(self.tab_bar)
        btn.setObjectName("TabCloseButton")
        btn.setText("×")
        btn.setAutoRaise(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedSize(16, 16)
        btn.clicked.connect(self._on_tab_close_button_clicked)
        btn.installEventFilter(self)
        return btn

    def _install_tab_close_button(self, index):
        self.tab_bar.setTabButton(
            index,
            QTabBar.ButtonPosition.RightSide,
            self._make_tab_close_button()
        )

    def _on_tab_close_button_clicked(self):
        btn = self.sender()
        if not btn:
            return
        for i in range(self.tab_bar.count()):
            if self.tab_bar.tabButton(i, QTabBar.ButtonPosition.RightSide) is btn:
                self._close_tab(i)
                break

    def _close_tab(self, idx: int):
        if not (0 <= idx < len(self._tabs)):
            return
        tab = self._tabs[idx]
        if tab.is_dirty:
            name  = os.path.basename(tab.path) if tab.path else "Untitled"
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                f'"{name}" has unsaved changes. Close anyway?',
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Save:
                self.tab_bar.setCurrentIndex(idx)
                self.save_file()
        self._tabs.pop(idx)
        self.tab_bar.removeTab(idx)
        if not self._tabs:
            self._new_tab()

    def _current_tab(self):
        if 0 <= self._cur_idx < len(self._tabs):
            return self._tabs[self._cur_idx]
        return None

    def _update_tab(self, idx):
        """Sync tab label and close-button appearance for the tab at idx."""
        if not (0 <= idx < len(self._tabs)):
            return
        tab = self._tabs[idx]
        self.tab_bar.setTabText(idx, tab.title)
        btn = self.tab_bar.tabButton(idx, QTabBar.ButtonPosition.RightSide)
        if btn:
            if not tab.is_dirty:
                # Saved — gray ×
                btn.setText("×")
                btn.setToolTip("Close tab")
                btn.setStyleSheet("")
            elif tab.is_session_backed:
                # Unsaved but in crash recovery — gray ●
                btn.setText("●")
                btn.setToolTip("Unsaved changes (backed up) — click to close")
                btn.setStyleSheet("color: #858585; font-size: 13px; border: none; background: transparent;")
            else:
                # Unsaved and NOT yet in crash recovery — red ●
                btn.setText("●")
                btn.setToolTip("Unsaved changes (not yet backed up) — click to close")
                btn.setStyleSheet("color: #f44747; font-size: 13px; border: none; background: transparent;")

    def _session_path(self):
        """Path to the session file."""
        return os.path.join(get_config_dir(), "session.json")

    def _save_session(self):
        """Save all tabs (content, path, cursor, scroll, dirty) to a JSON file."""
        self._save_current_tab_state()
        tabs_data = []
        for tab in self._tabs:
            tabs_data.append({
                "path":         tab.path,
                "content":      tab.content,
                "cursor_pos":   tab.cursor_pos,
                "scroll_value": tab.scroll_value,
                "dirty":        tab.is_dirty,
            })
        session = {
            "current_tab": self._cur_idx,
            "tabs":        tabs_data,
        }
        try:
            with open(self._session_path(), "w", encoding="utf-8") as f:
                json.dump(session, f, ensure_ascii=False)
            # Mark all dirty tabs as now captured in crash recovery
            for i, tab in enumerate(self._tabs):
                tab.mark_session_backed()
                self._update_tab(i)
        except OSError:
            pass

    def _restore_session(self):
        """Restore tabs from session file, or create a blank tab if none exists."""
        path = self._session_path()
        restored = False
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    session = json.load(f)
                tabs_data = session.get("tabs", [])
                if tabs_data:
                    for td in tabs_data:
                        tab = self._new_tab(
                            path=td.get("path"),
                            content=td.get("content", ""),
                        )
                        tab.cursor_pos   = td.get("cursor_pos", 0)
                        tab.scroll_value = td.get("scroll_value", 0)
                        if td.get("dirty", False):
                            tab.mark_dirty()
                            tab.mark_session_backed()  # already in session — start gray
                        else:
                            tab.mark_clean()
                        idx = self._tabs.index(tab)
                        self._update_tab(idx)

                    # Switch to the previously active tab
                    cur = session.get("current_tab", 0)
                    cur = max(0, min(cur, len(self._tabs) - 1))
                    self.tab_bar.setCurrentIndex(cur)
                    self._attach_tab(cur, save_current=False)
                    restored = True
            except (json.JSONDecodeError, OSError, KeyError):
                pass

        if not restored:
            self._new_tab()

    # ── WebChannel ────────────────────────────

    def _setup_webchannel(self):
        if not HAS_WEBCHANNEL:
            return
        self._bridge  = PreviewBridge(self.editor, self)
        self._channel = QWebChannel()
        self._channel.registerObject("previewBridge", self._bridge)
        self.preview.page().setWebChannel(self._channel)
        self.preview.loadFinished.connect(self._inject_bridge)

    def _inject_bridge(self, ok):
        if not ok or not HAS_WEBCHANNEL:
            return
        js = (
            "if(typeof QWebChannel !== 'undefined'){"
            + BRIDGE_JS +
            "}else{"
            "var s=document.createElement('script');"
            "s.src='qrc:///qtwebchannel/qwebchannel.js';"
            "s.onload=function(){" + BRIDGE_JS + "};"
            "document.head.appendChild(s);"
            "}"
        )
        self.preview.page().runJavaScript(js)

    # ── Menus ─────────────────────────────────

    def _build_menus(self):
        mb = self.menuBar()

        fm = mb.addMenu("&File")
        self._act(fm, "&New Tab",    "Ctrl+T",       lambda: self._new_tab())
        fm.addSeparator()
        self._act(fm, "&Open...",    "Ctrl+O",       self.open_file)
        self._act(fm, "&Save",       "Ctrl+S",       self.save_file)
        self._act(fm, "Save &As...", "Ctrl+Shift+S", self.save_as)
        fm.addSeparator()
        self._act(fm, "Close &Tab",  "Ctrl+W",
                  lambda: self._close_tab(self.tab_bar.currentIndex()))
        fm.addSeparator()
        self._act(fm, "&Quit", "Ctrl+Q", self.close)

        em = mb.addMenu("&Edit")
        self._act(em, "&Undo", "Ctrl+Z", self.editor.undo)
        self._act(em, "&Redo", "Ctrl+Y", self.editor.redo)
        em.addSeparator()
        self._act(em, "Cu&t",        "Ctrl+X", self.editor.cut)
        self._act(em, "&Copy",       "Ctrl+C", self.editor.copy_rich)
        self._act(em, "&Paste",      "Ctrl+V", self.editor.paste)
        self._act(em, "Select &All", "Ctrl+A", self.editor.selectAll)
        em.addSeparator()
        self._act(em, "&Find...",            "Ctrl+F", self.show_find)
        self._act(em, "Find && &Replace...", "Ctrl+H", self.show_find_replace)
        em.addSeparator()
        tag_menu = em.addMenu("Tag &Completion")
        tag_group = QActionGroup(self)
        tag_group.setExclusive(True)
        self._tag_mode_actions = {}
        for mode, label in [
            ("manual", "&Manual — no completion"),
            ("smart",  "&Smart — complete on </"),
            ("auto",   "&Auto — pair tag immediately"),
        ]:
            a = QAction(label, self, checkable=True)
            a.setChecked(self._tag_mode == mode)
            a.setData(mode)
            a.triggered.connect(self._on_tag_mode_changed)
            tag_group.addAction(a)
            tag_menu.addAction(a)
            self._tag_mode_actions[mode] = a
        tag_menu.addSeparator()
        self._chk(tag_menu, "Show Tag &Suggestions Dropdown",
                  self._tag_completer, self.toggle_tag_completer, "_act_tag_completer")
        self._chk(em, "Preview &Click Sync", self._sync_click, self.toggle_click_sync, "_act_click_sync")
        spell_enabled = self._spell.available and self._spell.enabled
        spell_label   = "&Spell Check" if self._spell.available else "&Spell Check (install pyenchant)"
        self._chk(em, spell_label, spell_enabled, self.toggle_spellcheck, "_act_spell")
        if not self._spell.available:
            self._act_spell.setEnabled(False)
        self._chk(em, "&Validate HTML Tags", self._val_enabled, self.toggle_validation, "_act_val")
        em.addSeparator()
        self._act(em, "Rename Tab…", None, self._rename_tab)

        vm = mb.addMenu("&View")
        self._chk(vm, "Editor &Dark Mode",    self._editor_dark,  self.toggle_editor_theme,  "_act_editor_dark")

        self._insert_menu = mb.addMenu("&Insert")
        self._rebuild_insert_menu()
        self._chk(vm, "Preview D&ark Mode",   self._preview_dark, self.toggle_preview_theme, "_act_preview_dark",
                  shortcut=None)
        vm.addSeparator()
        self._chk(vm, "&Word Wrap",    self._word_wrap,   self.toggle_word_wrap,   "_act_wordwrap")
        self._chk(vm, "&Sync Scroll",  self._sync_scroll, self.toggle_sync_scroll, "_act_sync")
        vm.addSeparator()
        self._act(vm, "Editor Zoom &In",   "Ctrl+=", self.editor_zoom_in)
        self._act(vm, "Editor Zoom &Out",  "Ctrl+-", self.editor_zoom_out)
        vm.addSeparator()
        self._act(vm, "Preview Zoom I&n",  "Ctrl+]", self.preview_zoom_in)
        self._act(vm, "Preview Zoom Ou&t", "Ctrl+[", self.preview_zoom_out)

        hm = mb.addMenu("&Help")
        self._act(hm, "&Quick Start",        None, self.show_quickstart)
        self._act(hm, "&Keyboard Shortcuts", None, self.show_shortcuts)
        hm.addSeparator()
        self._act(hm, "&GitHub Repository",  None, self.open_github)
        hm.addSeparator()
        self._act(hm, "&License",            None, self.show_license)
        self._act(hm, "&About Jackdaw",      None, self.show_about)

    def _act(self, menu, label, shortcut, slot):
        a = QAction(label, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def _chk(self, menu, label, checked, slot, attr, shortcut=None):
        a = QAction(label, self, checkable=True, checked=checked)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(slot)
        menu.addAction(a)
        setattr(self, attr, a)
        return a

    def _apply_tabbar_style(self):
        if self._editor_dark:
            self.tab_strip.setStyleSheet("""
                QWidget#TabStrip {
                    background: #1e1e1e;
                    border-bottom: 1px solid #2d2d30;
                }
                QTabBar {
                    background: transparent;
                }
                QTabBar::tab {
                    background: #2a2d35;
                    color: #d4d4d4;
                    border: 1px solid #3a3d41;
                    border-bottom: none;
                    border-radius: 0px;
                    padding: 4px 12px;
                    margin: 0px;
                    min-width: 120px;
                    max-width: 240px;
                    min-height: 24px;
                }
                QTabBar::tab:selected {
                    background: #1e1e1e;
                    color: #ffffff;
                    border: 1px solid #4a4d52;
                    border-top: 2px solid #007acc;
                    border-bottom: none;
                    border-radius: 0px;
                    padding: 3px 12px 4px 12px;
                    margin: 0px;
                    min-width: 120px;
                    max-width: 240px;
                    min-height: 24px;
                }
                QTabBar::tab:hover:!selected {
                    background: #32353d;
                }
                QTabBar::close-button {
                    subcontrol-position: right;
                    margin-left: 6px;
                    border-radius: 4px;
                }
                QTabBar::close-button:hover {
                    background: #4a4d52;
                }
                QToolButton#BrowserNewTab {
                    background: transparent;
                    color: #d4d4d4;
                    border: none;
                    border-radius: 0px;
                    padding: 2px 8px;
                    font-size: 16px;
                    font-weight: bold;
                }
                QToolButton#BrowserNewTab:hover {
                    background: #32353d;
                }
                QToolButton#TabCloseButton {
                    background: transparent;
                    color: #aeb6c2;
                    border: none;
                    border-radius: 0px;
                    padding: 0px;
                    font-size: 13px;
                    font-weight: bold;
                }
                QToolButton#TabCloseButton:hover {
                    background: #3a3d41;
                    color: #ffffff;
                }
            """)
        else:
            self.tab_strip.setStyleSheet("""
                QWidget#TabStrip {
                    background: #f3f3f3;
                    border-bottom: 1px solid #cfcfcf;
                }
                QTabBar {
                    background: transparent;
                }
                QTabBar::tab {
                    background: #e6e6e6;
                    color: #222222;
                    border: 1px solid #c9c9c9;
                    border-bottom: none;
                    border-radius: 0px;
                    padding: 4px 12px;
                    margin: 0px;
                    min-width: 120px;
                    max-width: 240px;
                    min-height: 24px;
                }
                QTabBar::tab:selected {
                    background: #ffffff;
                    color: #111111;
                    border: 1px solid #bdbdbd;
                    border-top: 2px solid #007acc;
                    border-bottom: none;
                    border-radius: 0px;
                    padding: 3px 12px 4px 12px;
                    margin: 0px;
                    min-width: 120px;
                    max-width: 240px;
                    min-height: 24px;
                }
                QTabBar::tab:hover:!selected {
                    background: #ededed;
                }
                QToolButton#BrowserNewTab {
                    background: transparent;
                    color: #333333;
                    border: none;
                    border-radius: 0px;
                    padding: 2px 8px;
                    font-size: 16px;
                    font-weight: bold;
                }
                QToolButton#BrowserNewTab:hover {
                    background: #e6e6e6;
                }
                QToolButton#TabCloseButton {
                    background: transparent;
                    color: #666666;
                    border: none;
                    border-radius: 0px;
                    padding: 0px;
                    font-size: 13px;
                    font-weight: bold;
                }
                QToolButton#TabCloseButton:hover {
                    background: #dddddd;
                    color: #111111;
                }
            """)

    def _install_preview_wheel_filter(self):
        """Install event filter on QWebEngineView's internal child widget."""
        child = self.preview.focusProxy()
        if child:
            child.installEventFilter(self)

    def eventFilter(self, obj, event):
        """Handle preview Ctrl+scroll zoom and tab close button hover."""
        # Ctrl+scroll on preview → zoom
        if event.type() == event.Type.Wheel:
            from PyQt6.QtCore import Qt as QtConst
            if event.modifiers() == QtConst.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                if delta > 0:
                    self.preview_zoom_in()
                elif delta < 0:
                    self.preview_zoom_out()
                return True

        # Tab close button hover: show × instead of ●
        if isinstance(obj, QToolButton) and obj.objectName() == "TabCloseButton":
            if event.type() == event.Type.Enter:
                obj._saved_text  = obj.text()
                obj._saved_style = obj.styleSheet()
                if obj.text() == "●":
                    obj.setText("×")
                    obj.setStyleSheet("")
            elif event.type() == event.Type.Leave:
                if hasattr(obj, '_saved_text'):
                    obj.setText(obj._saved_text)
                    obj.setStyleSheet(obj._saved_style)

        return super().eventFilter(obj, event)

    # ── Preview ───────────────────────────────

    _preview_initialized = False
    _last_preview_html   = ""

    def _refresh_preview(self):
        html = self.editor.toPlainText()
        base_css = """
<style id="__jackdaw_base__">
body { font-family: Arial, sans-serif; font-size: 14px; margin: 16px; margin-left: 20px; }
font[size="1"] { font-size: 10px; }
font[size="2"] { font-size: 13px; }
font[size="3"] { font-size: 16px; }
font[size="4"] { font-size: 19px; }
font[size="5"] { font-size: 24px; }
font[size="6"] { font-size: 32px; }
font[size="7"] { font-size: 48px; }
/* Gutter strip on the left edge */
#__hp_gutter {
    position: fixed;
    left: 0; top: 0;
    width: 6px;
    height: 100vh;
    background: #e8e8e8;
    border-right: 1px solid #d0d0d0;
    z-index: 99998;
    pointer-events: none;
}
</style>
<div id="__hp_gutter"></div>
"""
        if self._preview_dark:
            base_css += DARK_PREVIEW_CSS

        lower = html.lower()
        idx   = lower.find("<head>")
        if idx != -1:
            ins  = idx + len("<head>")
            html = html[:ins] + base_css + html[ins:]
        else:
            html = base_css + html

        # Skip identical refreshes
        if html == self._last_preview_html and self._preview_initialized:
            return
        self._last_preview_html = html

        bg = QColor("#1e1e1e") if self._preview_dark else QColor("#ffffff")

        # If the page is already loaded and the document structure hasn't
        # changed significantly, update innerHTML in-place so the browser
        # keeps its image cache and images don't flicker/reload.
        has_head  = "<head>"  in html.lower()
        had_head  = "<head>"  in self._last_preview_html.lower() if self._preview_initialized else False

        if self._preview_initialized and has_head == had_head:
            import json as _json
            escaped = _json.dumps(html)
            js = f"""
(function() {{
    var parser = new DOMParser();
    var doc = parser.parseFromString({escaped}, 'text/html');
    // Update head styles
    var oldStyles = document.querySelectorAll('style');
    oldStyles.forEach(function(s) {{ s.remove(); }});
    var newStyles = doc.querySelectorAll('style');
    newStyles.forEach(function(s) {{
        document.head.appendChild(document.adoptNode(s));
    }});
    // Save position marker before wiping body (it lives outside the HTML content)
    var marker = document.getElementById('__hp_pos_marker');
    // Update body content — preserves image cache
    document.body.innerHTML = doc.body.innerHTML;
    // Restore marker so it doesn't disappear after an incremental update
    if (marker) document.body.appendChild(marker);
    // Re-apply background
    document.documentElement.style.backgroundColor = '{bg.name()}';
    document.body.style.backgroundColor = '{bg.name()}';
}})();
"""
            self.preview.page().runJavaScript(js)
        else:
            # Full reload — tab switch, first load, or structure change
            self.preview.page().setBackgroundColor(bg)
            self.preview.setHtml(html)
            self._preview_initialized = True

    def _re_inject_bridge(self):
        """Re-inject bridge JS after document.write() destroyed the old one.

        Uses a single fire-and-forget runJavaScript call with the QWebChannel
        availability check inlined, avoiding nested callbacks that can orphan
        if document.write() fires again before the callback returns.
        """
        if not HAS_WEBCHANNEL:
            return
        js = (
            "if(typeof QWebChannel !== 'undefined'){"
            + BRIDGE_JS +
            "}else{"
            "var s=document.createElement('script');"
            "s.src='qrc:///qtwebchannel/qwebchannel.js';"
            "s.onload=function(){" + BRIDGE_JS + "};"
            "document.head.appendChild(s);"
            "}"
        )
        self.preview.page().runJavaScript(js)

    # ── Scroll sync ───────────────────────────

    def _editor_scrolled(self, value):
        if not self._sync_scroll or self._syncing_to_preview:
            return
        if HAS_WEBCHANNEL and hasattr(self, "_bridge") and self._bridge._scroll_syncing:
            return
        sb = self.editor.verticalScrollBar()
        if sb.maximum() == 0:
            return
        pct = value / sb.maximum()
        self._syncing_to_preview = True
        self.preview.page().runJavaScript(
            f"window.scrollTo(0,(document.documentElement.scrollHeight-window.innerHeight)*{pct:.6f});"
        )
        # Give QWebEngine enough time to emit the resulting scroll event
        QTimer.singleShot(120, lambda: setattr(self, '_syncing_to_preview', False))

    def _on_cursor_moved(self):
        """Debounce cursor position → preview position marker."""
        if HAS_WEBCHANNEL:
            self._cursor_indicator_timer.start()

    def _sync_cursor_to_preview(self):
        """Show position marker at matching text in preview."""
        if not HAS_WEBCHANNEL:
            return

        cursor = self.editor.textCursor()
        block = cursor.block()
        line_text = block.text().strip()

        # First: check if current line has an <img> tag — search by src attribute
        img_match = re.search(r"""<img\b[^>]*\bsrc=["']([^"']+)["']""", line_text, re.IGNORECASE)
        if img_match:
            src = img_match.group(1)
            safe_src = src.replace('\\', '\\\\').replace("'", "\\'")
            # Count which occurrence of this img src in the source
            source_text = self.editor.toPlainText()
            occurrence = 0
            search_pos = 0
            cursor_end = block.position() + block.length()
            while True:
                idx = source_text.find(src, search_pos)
                if idx == -1 or idx >= cursor_end:
                    break
                occurrence += 1
                search_pos = idx + 1
            occurrence = max(0, occurrence - 1)
            self.preview.page().runJavaScript(
                f"if(typeof window.__jackdawMarkerByImg==='function') "
                f"window.__jackdawMarkerByImg('{safe_src}', {occurrence});"
            )
            return

        # Search current line and nearby lines for usable text
        for offset in range(0, 8):
            for direction in (0, 1, -1):
                check = self.editor.document().findBlockByNumber(
                    block.blockNumber() + offset * direction
                )
                if not check.isValid():
                    continue
                text = check.text().strip()

                # Extract text segments between tags, take the longest one
                segments = re.split(r'<[^>]+>', text)
                segments = [re.sub(r'&\w+;', ' ', s).strip() for s in segments]
                segments = [re.sub(r'\s+', ' ', s) for s in segments if len(s.strip()) >= 3]

                if not segments:
                    continue

                snippet = max(segments, key=len)[:50]

                if len(snippet) >= 3:
                    safe = snippet.replace('\\', '\\\\').replace("'", "\\'").replace('\n', ' ')
                    # Count which occurrence this is in the source
                    source_text = self.editor.toPlainText()
                    occurrence = 0
                    search_pos = 0
                    # Use end of block so we count the match ON this line
                    cursor_end = check.position() + check.length()
                    while True:
                        idx = source_text.find(snippet, search_pos)
                        if idx == -1 or idx >= cursor_end:
                            break
                        occurrence += 1
                        search_pos = idx + 1
                    occurrence = max(0, occurrence - 1)  # zero-based index

                    self.preview.page().runJavaScript(
                        f"if(typeof scheduleMarkerUpdate==='function') "
                        f"scheduleMarkerUpdate({{searchText:'{safe}',occurrence:{occurrence}}});"
                    )
                    return

        # No text found nearby — hide marker
        self.preview.page().runJavaScript(
            "var m=document.getElementById('__hp_pos_marker'); if(m) m.style.opacity='0';"
        )

    # ── File actions ──────────────────────────

    def open_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open HTML File", "",
            "HTML Files (*.html *.htm);;All Files (*)"
        )
        for path in paths:
            for i, tab in enumerate(self._tabs):
                if tab.path == path:
                    self.tab_bar.setCurrentIndex(i)
                    break
            else:
                with open(path, encoding="utf-8") as f:
                    content = f.read()
                tab = self._new_tab(path=path, content=content)
                self._update_tab(self._tabs.index(tab))

    def save_file(self):
        tab = self._current_tab()
        if tab and tab.path:
            self._write(tab, tab.path)
        else:
            self.save_as()

    def save_as(self):
        tab = self._current_tab()
        if not tab:
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Save HTML File", tab.path or "",
            "HTML Files (*.html *.htm);;All Files (*)"
        )
        if path:
            # Linux doesn't auto-append the extension — do it ourselves
            if not path.lower().endswith((".html", ".htm")):
                if "*.htm)" in selected_filter and not "*.html" in selected_filter:
                    path += ".htm"
                else:
                    path += ".html"
            tab.path = path
            self._write(tab, path)

    def _write(self, tab: TabData, path: str):
        # Make sure current editor text is stored before writing.
        if tab is self._current_tab():
            tab.content = self.editor.toPlainText()
        with open(path, "w", encoding="utf-8") as f:
            f.write(tab.content)
        tab.mark_clean()
        self._update_tab(self._tabs.index(tab))
        self.setWindowTitle(f"Jackdaw — {path}")
        self.statusBar().showMessage(f"Saved — {path}")

    def show_find(self):
        self.find_bar.show_find()

    def show_find_replace(self):
        self.find_bar.show_replace()

    # ── Toggles ───────────────────────────────

    def toggle_editor_theme(self):
        self._editor_dark = not self._editor_dark
        self._act_editor_dark.setChecked(self._editor_dark)
        self.editor.apply_theme(self._editor_dark)
        self._highlighter.set_dark(self._editor_dark)
        self._highlighter.rehighlight()
        self._apply_tabbar_style()
        self.val_panel.apply_theme(self._editor_dark)
        self.editor.viewport().update()

    def toggle_preview_theme(self):
        self._preview_dark = not self._preview_dark
        self._act_preview_dark.setChecked(self._preview_dark)
        self._preview_initialized = False
        self._refresh_preview()

    def _on_text_changed_spell(self):
        """Clear stale spell underlines immediately, then schedule a recheck."""
        self.editor.clear_spell_extra_selections()
        self._spell_timer.start()

    def _on_text_changed_find(self):
        """Re-run find highlights after text changes so they stay accurate."""
        if hasattr(self, 'find_bar') and self.find_bar.isVisible():
            self.find_bar._highlight_all()
        else:
            self.editor.clear_find_extra_selections()

    def toggle_validation(self):
        self._val_enabled = not self._val_enabled
        self._act_val.setChecked(self._val_enabled)
        if not self._val_enabled:
            self.val_panel.setVisible(False)
            self.editor.set_error_lines([])
        else:
            self._run_validation()

    def _run_validation(self):
        if not self._val_enabled:
            return
        errors = validate_html_tags(self.editor.toPlainText())
        self.val_panel.set_errors(errors)
        self.val_panel.setVisible(True)
        self.editor.set_error_lines([lineno for lineno, _ in errors])
        # Update status bar with error count
        c = self.editor.textCursor()
        base = f"Ln {c.blockNumber() + 1},  Col {c.columnNumber() + 1}"
        if errors:
            self.statusBar().showMessage(
                f"{base}     ⚠ {len(errors)} HTML issue{'s' if len(errors) != 1 else ''}"
            )

    def toggle_spellcheck(self):
        self._spell.enabled = not self._spell.enabled
        self._act_spell.setChecked(self._spell.enabled)
        if not self._spell.enabled:
            self.editor.clear_spell_extra_selections()
        else:
            self._run_spellcheck()

    def _run_spellcheck(self):
        if not self._spell.enabled:
            return
        text = self.editor.toPlainText()
        doc  = self.editor.document()

        selections = []
        ranges     = []
        for start, end in _plain_text_word_ranges(text):
            word = text[start:end].strip("'")
            if not word or self._spell.check(word):
                continue
            cursor = QTextCursor(doc)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            sel = QTextEdit.ExtraSelection()
            sel.format = QTextCharFormat()   # no Qt underline — we draw our own
            sel.cursor = cursor
            selections.append(sel)
            ranges.append((start, end))

        self.editor.set_spell_extra_selections(selections, ranges)

    def _rebuild_insert_menu(self):
        self._insert_menu.clear()
        for i, s in enumerate(self._snippet_mgr.snippets):
            a = QAction(s.get("name", f"Snippet {i + 1}"), self)
            a.setData(i)
            a.triggered.connect(self._insert_snippet_action)
            self._insert_menu.addAction(a)
        if self._snippet_mgr.snippets:
            self._insert_menu.addSeparator()
        self._insert_menu.addAction(
            QAction("Manage Snippets…", self, triggered=self._manage_snippets)
        )

    def _insert_snippet_action(self):
        idx      = self.sender().data()
        snippets = self._snippet_mgr.snippets
        if 0 <= idx < len(snippets):
            self._snippet_mgr.insert_into_editor(snippets[idx], self.editor)

    def _manage_snippets(self):
        dlg = ManageSnippetsDialog(self._snippet_mgr, self)
        dlg.exec()
        self._rebuild_insert_menu()

    def toggle_tag_completer(self):
        self._tag_completer = not self._tag_completer
        self.editor._completer_enabled = self._tag_completer
        if not self._tag_completer:
            self.editor._completer.popup().hide()
        self._act_tag_completer.setChecked(self._tag_completer)

    def _on_tag_mode_changed(self):
        action = self.sender()
        if action:
            self._tag_mode = action.data()
            self.editor._tag_mode = self._tag_mode

    def toggle_click_sync(self):
        self._sync_click = not self._sync_click
        if HAS_WEBCHANNEL and hasattr(self, "_bridge"):
            self._bridge.click_enabled = self._sync_click
        self._act_click_sync.setChecked(self._sync_click)

    def toggle_word_wrap(self):
        self._word_wrap = not self._word_wrap
        self.editor.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth if self._word_wrap
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        self._act_wordwrap.setChecked(self._word_wrap)

    def toggle_sync_scroll(self):
        self._sync_scroll = not self._sync_scroll
        if HAS_WEBCHANNEL and hasattr(self, "_bridge"):
            self._bridge.scroll_enabled = self._sync_scroll
        self._act_sync.setChecked(self._sync_scroll)

    def editor_zoom_in(self):
        self._editor_zoom = min(3.0, round(self._editor_zoom + 0.05, 2))
        self._apply_font()

    def editor_zoom_out(self):
        self._editor_zoom = max(0.3, round(self._editor_zoom - 0.05, 2))
        self._apply_font()

    def _apply_font(self):
        # Set base font then apply zoom factor so we get fractional sizing
        font = QFont(MONO_FONT, self._font_size)
        self.editor.setFont(font)
        self.editor.setStyleSheet(
            f"QPlainTextEdit {{ font-size: {self._font_size * self._editor_zoom:.1f}pt; }}"
        )
        self.editor._update_line_area_width()
        self.editor._update_scroll_padding()
        self._highlighter.rehighlight()

    def preview_zoom_in(self):
        self._preview_zoom = min(4.0, self._preview_zoom + 0.1)
        self.preview.setZoomFactor(self._preview_zoom)

    def preview_zoom_out(self):
        self._preview_zoom = max(0.2, self._preview_zoom - 0.1)
        self.preview.setZoomFactor(self._preview_zoom)

    def _update_status(self):
        c = self.editor.textCursor()
        self.statusBar().showMessage(
            f"Ln {c.blockNumber() + 1},  Col {c.columnNumber() + 1}"
        )

    # ── Help dialogs ──────────────────────────

    def show_quickstart(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Quick Start")
        dlg.setMinimumSize(560, 480)
        layout = QVBoxLayout(dlg)
        view = QWebEngineView()
        view.setHtml("""
<html><head><style>
body { font-family: Arial, sans-serif; font-size: 14px;
       margin: 24px; background: #1e1e1e; color: #d4d4d4; line-height: 1.6; }
h2 { color: #569cd6; border-bottom: 1px solid #3a3a3a; padding-bottom: 6px; }
h3 { color: #9cdcfe; margin-top: 20px; }
code { background: #2d2d2d; padding: 1px 5px; border-radius: 3px;
       font-family: Consolas, monospace; color: #ce9178; }
ul { padding-left: 20px; }
li { margin-bottom: 4px; }
</style></head><body>
<h2>Jackdaw Quick Start</h2>
<h3>Opening Files</h3>
<ul>
  <li>Use <code>File → Open</code> or <code>Ctrl+O</code> to open HTML files.</li>
  <li>Multiple files open in separate tabs.</li>
  <li>Session is restored automatically on next launch.</li>
</ul>
<h3>Editing</h3>
<ul>
  <li>The left pane is the HTML editor; the right pane is a live preview.</li>
  <li>Preview updates automatically as you type.</li>
  <li>Click anything in the preview to jump to that line in the editor.</li>
</ul>
<h3>Tag Completion</h3>
<ul>
  <li><b>Auto</b> — typing <code>&lt;li&gt;</code> immediately produces <code>&lt;li&gt;&lt;/li&gt;</code>.</li>
  <li><b>Smart</b> — typing <code>&lt;/</code> completes the nearest unclosed tag.</li>
  <li><b>Manual</b> — no automatic completion.</li>
  <li>Toggle via <code>Edit → Tag Completion</code>.</li>
</ul>
<h3>Snippets</h3>
<ul>
  <li>Type a trigger word then press <code>Tab</code> to expand a snippet.</li>
  <li>Use <code>$1</code>, <code>$2</code> in snippet bodies for tabstops.</li>
  <li>Same number (<code>$1 … $1</code>) mirrors typed text to both positions.</li>
  <li>Manage snippets via <code>Insert → Manage Snippets…</code></li>
</ul>
<h3>Indentation</h3>
<ul>
  <li><code>Tab</code> — indent current line or selection by 4 spaces.</li>
  <li><code>Shift+Tab</code> — unindent current line or selection by up to 4 spaces.</li>
</ul>
<h3>Spell Check</h3>
<ul>
  <li>Requires <code>python-pyenchant</code> and <code>aspell-en</code>.</li>
  <li>Right-click a misspelled word for suggestions or to add to dictionary.</li>
  <li>Toggle via <code>Edit → Spell Check</code>.</li>
</ul>
<h3>HTML Validation</h3>
<ul>
  <li>Unclosed or mismatched tags are flagged in the panel below the editor.</li>
  <li>Click any error to jump to that line.</li>
  <li>Toggle via <code>Edit → Validate HTML Tags</code>.</li>
</ul>
<h3>Saving</h3>
<ul>
  <li><code>Ctrl+S</code> — save current file.</li>
  <li><code>Ctrl+Shift+S</code> — save as.</li>
  <li>The tab dot shows save state:
    <ul>
      <li><b style="color:#f44747;">●</b> <b>Red</b> — unsaved changes not yet written to crash recovery.</li>
      <li><b style="color:#858585;">●</b> <b>Gray</b> — unsaved changes, but safely backed up to crash recovery session.</li>
      <li><b>×</b> — file is saved.</li>
    </ul>
  </li>
  <li>Crash recovery auto-saves every 30 seconds to the app config folder and restores on next launch.</li>
</ul>
</body></html>""")
        layout.addWidget(view)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        layout.addWidget(close)
        dlg.exec()

    def show_shortcuts(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Keyboard Shortcuts")
        dlg.setMinimumSize(500, 560)
        layout = QVBoxLayout(dlg)
        view = QWebEngineView()
        view.setHtml("""
<html><head><style>
body { font-family: Arial, sans-serif; font-size: 14px;
       margin: 24px; background: #1e1e1e; color: #d4d4d4; line-height: 1.6; }
h2 { color: #569cd6; border-bottom: 1px solid #3a3a3a; padding-bottom: 6px; }
h3 { color: #9cdcfe; margin-top: 18px; margin-bottom: 6px; }
table { width: 100%; border-collapse: collapse; }
td { padding: 5px 8px; border-bottom: 1px solid #2d2d2d; }
td:first-child { color: #d4d4d4; width: 55%; }
td:last-child { font-family: Consolas, monospace; color: #ce9178;
                text-align: right; white-space: nowrap; }
</style></head><body>
<h2>Keyboard Shortcuts</h2>
<h3>File</h3>
<table>
<tr><td>New Tab</td><td>Ctrl+T</td></tr>
<tr><td>Open</td><td>Ctrl+O</td></tr>
<tr><td>Save</td><td>Ctrl+S</td></tr>
<tr><td>Save As</td><td>Ctrl+Shift+S</td></tr>
<tr><td>Close Tab</td><td>Ctrl+W</td></tr>
<tr><td>Quit</td><td>Ctrl+Q</td></tr>
</table>
<h3>Edit</h3>
<table>
<tr><td>Undo</td><td>Ctrl+Z</td></tr>
<tr><td>Redo</td><td>Ctrl+Y</td></tr>
<tr><td>Cut</td><td>Ctrl+X</td></tr>
<tr><td>Copy (with syntax highlight)</td><td>Ctrl+C</td></tr>
<tr><td>Paste</td><td>Ctrl+V</td></tr>
<tr><td>Select All</td><td>Ctrl+A</td></tr>
<tr><td>Find</td><td>Ctrl+F</td></tr>
<tr><td>Find &amp; Replace</td><td>Ctrl+H</td></tr>
</table>
<h3>Editor</h3>
<table>
<tr><td>Indent (line or selection)</td><td>Tab</td></tr>
<tr><td>Unindent (line or selection)</td><td>Shift+Tab</td></tr>
<tr><td>Expand snippet</td><td>Tab (after trigger word)</td></tr>
<tr><td>Next tabstop</td><td>Tab (during snippet)</td></tr>
<tr><td>Cancel snippet</td><td>Escape</td></tr>
<tr><td>Close find bar</td><td>Escape</td></tr>
</table>
<h3>View</h3>
<table>
<tr><td>Editor Zoom In</td><td>Ctrl+=</td></tr>
<tr><td>Editor Zoom Out</td><td>Ctrl+-</td></tr>
<tr><td>Preview Zoom In</td><td>Ctrl+]</td></tr>
<tr><td>Preview Zoom Out</td><td>Ctrl+[</td></tr>
<tr><td>Editor/Preview Zoom (scroll)</td><td>Ctrl+Scroll</td></tr>
</table>
<h3>Find Bar</h3>
<table>
<tr><td>Find Next</td><td>Enter</td></tr>
<tr><td>Find Previous</td><td>Shift+Enter</td></tr>
<tr><td>Close</td><td>Escape</td></tr>
</table>
</body></html>""")
        layout.addWidget(view)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        layout.addWidget(close)
        dlg.exec()

    def open_github(self):
        import webbrowser
        webbrowser.open("https://github.com/dposto/jackdaw")

    def show_license(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("License")
        dlg.setMinimumSize(520, 440)
        layout = QVBoxLayout(dlg)
        view = QWebEngineView()
        view.setHtml("""
<html><head><style>
body { font-family: Arial, sans-serif; font-size: 14px;
       margin: 24px; background: #1e1e1e; color: #d4d4d4; line-height: 1.6; }
h2 { color: #569cd6; }
h3 { color: #9cdcfe; margin-top: 20px; }
p { margin: 8px 0; }
code { background: #2d2d2d; padding: 1px 5px; border-radius: 3px;
       font-family: Consolas, monospace; color: #ce9178; }
.note { background: #2d2d2d; padding: 10px 14px; border-left: 3px solid #569cd6;
        border-radius: 3px; margin-top: 16px; }
</style></head><body>
<h2>License</h2>
<p>Jackdaw is copyright &copy; 2026 David Posto and is licensed under the
<b>GNU General Public License v3.0</b> (GPL-3.0-or-later).</p>
<p>You are free to use, study, modify, and distribute this software under
the terms of the GPL. Any distribution must include the source code or
make it available, and derivative works must be licensed under the same terms.</p>
<div class="note">
This program is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the
Free Software Foundation, either version 3 of the License, or (at your
option) any later version.
</div>
<h3>Third-Party Libraries</h3>
<p><b>PyQt6</b> — GPL-3.0 or commercial — Riverbank Computing Limited</p>
<p><b>Qt6</b> — LGPL-3.0 / GPL-3.0 / commercial — The Qt Company</p>
<p><b>PyEnchant</b> (optional) — LGPL-2.1 — Ryan Kelly et al.</p>
<p><b>Enchant-2</b> (optional) — LGPL-2.1 — Dom Lachowicz et al.</p>
<p><b>Python Standard Library</b> — PSF-2.0</p>
<p style="margin-top:20px; color: #858585; font-size:12px;">
Jackdaw is an independent open-source project. It is not affiliated with,
endorsed by, or a fork of Visual Studio Code, VSCodium, or Microsoft.
</p>
</body></html>""")
        layout.addWidget(view)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        layout.addWidget(close)
        dlg.exec()

    def show_about(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("About Jackdaw")
        dlg.setMinimumSize(420, 300)
        layout = QVBoxLayout(dlg)
        view = QWebEngineView()
        view.setHtml(f"""
<html><head><style>
body {{ font-family: Arial, sans-serif; font-size: 14px;
       margin: 32px; background: #1e1e1e; color: #d4d4d4;
       line-height: 1.7; text-align: center; }}
h1 {{ color: #569cd6; font-size: 28px; margin-bottom: 4px; }}
.version {{ color: #858585; font-size: 13px; margin-bottom: 20px; }}
.desc {{ max-width: 340px; margin: 0 auto 20px auto; }}
a {{ color: #6ab0f5; }}
.footer {{ color: #555555; font-size: 12px; margin-top: 24px; }}
</style></head><body>
<h1>Jackdaw</h1>
<div class="version">Version {__version__}</div>
<div class="desc">
  A lightweight, open-source HTML editor with live preview.<br>
  Built with PyQt6 and Qt6.
</div>
<div>
  <a href="https://github.com/dposto/jackdaw">github.com/dposto/jackdaw</a>
</div>
<div class="footer">
  Copyright &copy; 2026 David Posto<br>
  Licensed under the GNU General Public License v3.0<br><br>
  Jackdaw is an independent project, not affiliated with Microsoft or VS Code.
</div>
</body></html>""")
        layout.addWidget(view)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        layout.addWidget(close)
        dlg.exec()

    # ── Settings save / close ─────────────────

    def _save_settings(self):
        s = self._s
        s.setValue("settings_version", SETTINGS_VERSION)
        s.setValue("editor_dark",      self._editor_dark)
        s.setValue("preview_dark",     self._preview_dark)
        s.setValue("font_size",        self._font_size)
        s.setValue("editor_zoom",      self._editor_zoom)
        s.setValue("preview_zoom",     self._preview_zoom)
        s.setValue("sync_scroll",      self._sync_scroll)
        s.setValue("sync_click",       self._sync_click)
        s.setValue("word_wrap",        self._word_wrap)
        s.setValue("tag_mode",         self._tag_mode)
        s.setValue("tag_completer",    self._tag_completer)
        s.setValue("spell_enabled",    self._spell.enabled)
        s.setValue("val_enabled",      self._val_enabled)
        s.setValue("geometry",         self.saveGeometry())
        s.setValue("splitter",         self.splitter.saveState())
        s.sync()   # force flush to disk immediately

    def closeEvent(self, event):
        self._save_session()
        self._save_settings()
        event.accept()


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────
def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-v"):
        print(f"Jackdaw {__version__}")
        sys.exit(0)

    import os
    # Reduce QWebEngineView flicker on Wayland by enabling shared GL context
    # and disabling the compositing path that causes full-surface repaints.
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu-compositing")
    os.environ.setdefault("QT_OPENGL", "software")

    app = QApplication(sys.argv)
    app.setApplicationName("Jackdaw")
    app.setStyle("Fusion")
    # Read saved theme preference (default: dark)
    s = QSettings("jackdaw", "jackdaw")
    dark = s.value("editor_dark", True, type=bool)
    # Apply palette on the APPLICATION — the only reliable way
    # to override GNOME/GTK platform theming on Arch/Wayland
    _apply_fusion_palette(app, dark)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
