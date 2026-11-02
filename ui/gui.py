#!/usr/bin/env python3
"""probs-mang GUI: track the DSA problems you solve.

Welcome window
    left  : basic operations (new / browse / edit / delete problems)
    right : statistics (top, filled later from data_analysis) and the
            consistency calendar (bottom)

Problem window
    top          : problem name (also shown as the window title)
    left         : code
    top right    : terminal, compile / run output, type program input here
    bottom right : test cases, used as stdin by Run

Everything is done by the C++ backend (build/probs_mang) through the line
protocol of engine/api.cpp: one command per line, the value on the next line,
replies are lines that start with "\\x1e".
"""

from __future__ import annotations

import codecs
import datetime as dt
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
import tty
from bisect import bisect_right
from collections import defaultdict
from tkinter import font as tkfont
from tkinter import messagebox, ttk

APP_NAME = "DSA Management"
HERE = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------
# backend protocol
# --------------------------------------------------------------------------

def find_backend():
    candidates = [
        os.environ.get("PROBS_MANG_BIN"),
        os.path.join(HERE, "..", "build", "probs_mang"),
        shutil.which("probs_mang"),
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return os.path.abspath(path)
    return None


BACKEND = find_backend()
RS = "\x1e"  # starts every reply line of the backend
ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*\x07|[@-Z\\-_])")


def escape(s):
    return (s.replace("\\", "\\\\").replace("\n", "\\n")
             .replace("\t", "\\t").replace("\r", "\\r"))


def unescape(s):
    table = {"n": "\n", "t": "\t", "r": "\r"}
    return re.sub(r"\\(.)", lambda m: table.get(m.group(1), m.group(1)), s)


def parse_row(payload):
    """ROW payload -> dict of column -> text value."""
    row = {}
    for part in payload.split("\t"):
        key, sep, value = part.partition("=")
        if sep:
            row[key] = unescape(value)
    return row


def backend_env():
    env = dict(os.environ)
    env["TERM"] = "dumb"   # no colour escapes from g++
    env["GCC_COLORS"] = ""
    return env


class BackendError(Exception):
    pass


def backend_call(lines, timeout=30):
    """Run the backend once with the given command lines.

    Returns the replies as a list of (tag, payload) tuples.
    """
    if not BACKEND:
        raise BackendError("backend not found, build it with:\n"
                           "cmake -S . -B build && cmake --build build")
    data = "".join(line + "\n" for line in lines) + "END\n"
    try:
        out = subprocess.run([BACKEND], input=data.encode(), stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=timeout,
                             env=backend_env()).stdout
    except subprocess.TimeoutExpired:
        raise BackendError("the backend did not answer in time") from None
    except OSError as e:
        raise BackendError(str(e)) from None
    replies = []
    for line in out.decode("utf-8", "replace").split("\n"):
        i = line.find(RS)
        if i >= 0:
            tag, _, payload = line[i + 1:].partition(" ")
            replies.append((tag, payload))
    return replies


def sanitize_name(raw):
    """Problem names are file names (test/<name>.cpp): letters, digits, _ and -."""
    name = re.sub(r"\s+", "_", raw.strip())
    return re.sub(r"[^A-Za-z0-9_-]", "", name)[:100]


class PtySession:
    """One backend process on a pseudo terminal.

    The commands are written up front; output is streamed to on_text, reply
    lines go to on_reply. When the reply "DONE <final>" arrives END is sent,
    so anything typed until then reaches the running program instead.
    """

    def __init__(self, widget, on_text, on_reply, on_exit):
        self.widget = widget
        self.on_text = on_text
        self.on_reply = on_reply
        self.on_exit = on_exit
        self.out_q = queue.Queue()
        self.in_q = queue.Queue()
        self.proc = None
        self.master = None
        self.final = None
        self.buf = ""
        self.alive = False
        self.stopped = False
        self.interactive = False

    def start(self, lines, final):
        if not BACKEND:
            raise BackendError("backend not found, build it with:\n"
                               "cmake -S . -B build && cmake --build build")
        master, slave = os.openpty()
        tty.setraw(slave)  # commands may be long lines, no echo
        try:
            self.proc = subprocess.Popen([BACKEND], stdin=slave, stdout=slave,
                                         stderr=slave, start_new_session=True,
                                         close_fds=True, env=backend_env())
        except OSError:
            os.close(master)
            raise
        finally:
            os.close(slave)
        self.master = master
        self.final = final
        self.alive = True
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._writer, daemon=True).start()
        self.send("".join(line + "\n" for line in lines))
        self.widget.after(20, self._poll)

    def send(self, text):
        if self.alive:
            self.in_q.put(text.encode("utf-8"))

    def stop(self):
        if self.alive and self.proc:
            self.stopped = True
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def _writer(self):
        while True:
            data = self.in_q.get()
            if data is None:
                return
            try:
                while data:
                    n = os.write(self.master, data)
                    data = data[n:]
            except OSError:
                return

    def _reader(self):
        dec = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            try:
                data = os.read(self.master, 65536)
            except OSError:  # EIO once the backend is gone
                data = b""
            if not data:
                break
            self.out_q.put(dec.decode(data))
        rest = dec.decode(b"", final=True)
        if rest:
            self.out_q.put(rest)
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        self.out_q.put(None)

    def _poll(self):
        finished = False
        chunks = []
        size = 0
        while size < 256 * 1024:
            try:
                item = self.out_q.get_nowait()
            except queue.Empty:
                break
            if item is None:
                finished = True
                break
            chunks.append(item)
            size += len(item)
        if chunks:
            self._feed("".join(chunks))
        if finished:
            if self.buf:
                self.on_text(self.buf)
                self.buf = ""
            self.alive = False
            self.in_q.put(None)
            try:
                os.close(self.master)
            except OSError:
                pass
            self.on_exit(self.proc.returncode, self.stopped)
        else:
            try:
                self.widget.after(20, self._poll)
            except tk.TclError:  # window closed
                self.stop()

    def _feed(self, data):
        self.buf += data
        while self.buf:
            i = self.buf.find(RS)
            if i < 0:
                self.on_text(self.buf)
                self.buf = ""
                return
            if i > 0:
                self.on_text(self.buf[:i])
                self.buf = self.buf[i:]
            j = self.buf.find("\n")
            if j < 0:
                return  # wait for the rest of the reply line
            tag, _, payload = self.buf[1:j].partition(" ")
            self.buf = self.buf[j + 1:]
            if tag == "INTERACTIVE":
                self.interactive = True
            elif tag == "RESULT":
                self.interactive = False
            if tag == "DONE" and payload == self.final:
                self.send("END\n")
            self.on_reply(tag, payload)


# --------------------------------------------------------------------------
# problem metadata (columns of the problems table)
# --------------------------------------------------------------------------

PLATFORMS = ["LeetCode", "Codeforces", "CodeChef", "AtCoder", "GeeksforGeeks",
             "HackerRank", "HackerEarth", "CSES", "SPOJ", "InterviewBit", "Other"]
PROBLEM_TYPES = ["Array", "String", "Hashing", "Two Pointers", "Sliding Window",
                 "Binary Search", "Sorting", "Stack", "Queue", "Linked List",
                 "Recursion", "Backtracking", "Tree", "BST", "Heap", "Graph",
                 "Shortest Path", "DSU", "Trie", "Segment Tree", "Greedy", "DP",
                 "Bit Manipulation", "Math", "Number Theory", "Geometry",
                 "Implementation", "Other"]
DIFFICULTIES = ["Easy", "Medium", "Hard"]
COMPLEXITIES = ["O(1)", "O(log n)", "O(sqrt n)", "O(n)", "O(n log n)", "O(n^2)",
                "O(n^2 log n)", "O(n^3)", "O(2^n)", "O(n!)", "O(V + E)",
                "O(E log V)", "O(n * m)"]

# key, label, kind, choices, max length
FIELDS = [
    ("date_of_doing", "Date (YYYY-MM-DD)", "date", None, None),
    ("platform", "Platform", "text", PLATFORMS, 50),
    ("problem_type", "Problem type", "text", PROBLEM_TYPES, 50),
    ("difficulty", "Difficulty", "text", DIFFICULTIES, 20),
    ("time_taken_minutes", "Time taken (minutes)", "int", None, None),
    ("time_complexity", "Time complexity", "text", COMPLEXITIES, 50),
    ("space_complexity", "Space complexity", "text", COMPLEXITIES, 50),
    ("tags", "Tags (comma separated)", "tags", None, None),
    ("importance_rating", "Importance (1-5)", "rating", ["", "1", "2", "3", "4", "5"], None),
    ("revision_count", "Revisions", "count", None, None),
    ("is_completed", "Completed", "bool", None, None),
    ("comment", "Comment", "multiline", None, None),
]
META_KEYS = [f[0] for f in FIELDS]


def default_meta():
    meta = {key: "" for key in META_KEYS}
    meta.update(date_of_doing=dt.date.today().isoformat(), revision_count="0",
                is_completed="false")
    return meta


def is_true(value):
    return str(value).lower() in ("true", "t", "1", "yes")


class MetadataDialog(tk.Toplevel):
    """Modal form for the metadata columns, self.result is the edited dict."""

    def __init__(self, parent, meta, title):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(True, False)
        self.result = None
        self.widgets = {}

        frm = ttk.Frame(self, padding=14)
        frm.pack(fill=tk.BOTH, expand=True)
        frm.columnconfigure(1, weight=1)
        for row, (key, label, kind, choices, _) in enumerate(FIELDS):
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="nw",
                                            padx=(0, 12), pady=4)
            value = meta.get(key, "")
            if kind == "bool":
                var = tk.BooleanVar(value=is_true(value))
                ttk.Checkbutton(frm, variable=var).grid(row=row, column=1, sticky="w")
            elif kind == "multiline":
                var = tk.Text(frm, height=5, width=44, wrap="word", relief="solid",
                              borderwidth=1)
                var.insert("1.0", value)
                var.grid(row=row, column=1, sticky="ew", pady=4)
            else:
                var = tk.StringVar(value=value)
                if choices:
                    w = ttk.Combobox(frm, textvariable=var, values=choices, width=42,
                                     state="readonly" if kind == "rating" else "normal")
                elif kind in ("int", "count"):
                    w = ttk.Spinbox(frm, textvariable=var, from_=0, to=100000, width=42)
                else:
                    w = ttk.Entry(frm, textvariable=var, width=44)
                w.grid(row=row, column=1, sticky="ew", pady=4)
            self.widgets[key] = var

        buttons = ttk.Frame(frm)
        buttons.grid(row=len(FIELDS), column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="OK", command=self._ok).pack(side=tk.RIGHT, padx=6)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Control-Return>", lambda e: self._ok())

        self.wait_visibility()
        self.grab_set()
        self.focus_set()

    def _ok(self):
        out = {}
        for key, label, kind, _, maxlen in FIELDS:
            w = self.widgets[key]
            if kind == "bool":
                out[key] = "true" if w.get() else "false"
                continue
            if kind == "multiline":
                value = w.get("1.0", "end-1c").strip()
            else:
                value = w.get().strip()
            if kind == "date":
                value = value or dt.date.today().isoformat()
                try:
                    dt.date.fromisoformat(value)
                except ValueError:
                    return self._bad(f"{label}: use the format YYYY-MM-DD")
            elif kind in ("int", "count"):
                if kind == "count" and not value:
                    value = "0"
                if value and (not value.isdigit() or int(value) > 2_000_000_000):
                    return self._bad(f"{label}: enter a whole number")
            elif kind == "tags":
                value = ",".join(t.strip() for t in value.split(",") if t.strip())
            if maxlen and len(value) > maxlen:
                return self._bad(f"{label}: at most {maxlen} characters")
            out[key] = value
        self.result = out
        self.destroy()

    def _bad(self, message):
        messagebox.showerror("Invalid value", message, parent=self)


def ask_metadata(parent, meta, title="Problem details"):
    dialog = MetadataDialog(parent, meta, title)
    parent.wait_window(dialog)
    return dialog.result


# --------------------------------------------------------------------------
# widgets
# --------------------------------------------------------------------------

def mono_font(size=11):
    family = tkfont.nametofont("TkFixedFont").actual("family")
    for candidate in ("JetBrains Mono", "Fira Code", "DejaVu Sans Mono",
                      "Ubuntu Mono", "Liberation Mono"):
        if candidate in tkfont.families():
            family = candidate
            break
    return (family, size)


class Terminal(ttk.Frame):
    """Output console that also takes keyboard input after the last output.

    Enter sends the typed line, Ctrl-D sends EOF, Ctrl-C (without a selection)
    stops the running program.
    """

    MAX_LINES = 5000
    NAV_KEYS = {"Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
                "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
                "Escape", "Caps_Lock", "Super_L", "Super_R", "Menu"}

    def __init__(self, master, on_input, on_eof, on_interrupt):
        super().__init__(master)
        self.on_input = on_input
        self.on_eof = on_eof
        self.on_interrupt = on_interrupt
        self.text = tk.Text(self, wrap="char", bg="#1e1f22", fg="#d4d4d4",
                            insertbackground="#ffffff", selectbackground="#264f78",
                            font=mono_font(10), relief="flat", padx=8, pady=6,
                            undo=False)
        scroll = ttk.Scrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        for tag, opts in {
            "prompt": dict(foreground="#61afef"),
            "input": dict(foreground="#e5c07b"),
            "dim": dict(foreground="#7f848e"),
            "ok": dict(foreground="#98c379"),
            "err": dict(foreground="#e06c75"),
            "warn": dict(foreground="#d19a66"),
            "info": dict(foreground="#56b6c2"),
            "good": dict(foreground="#98c379", font=mono_font(10) + ("bold",)),
            "bad": dict(foreground="#e06c75", font=mono_font(10) + ("bold",)),
        }.items():
            self.text.tag_configure(tag, **opts)

        self.text.mark_set("inp", "end-1c")
        self.text.mark_gravity("inp", "left")
        t = self.text
        t.bind("<Key>", self._on_key)
        t.bind("<Return>", self._on_return)
        t.bind("<KP_Enter>", self._on_return)
        t.bind("<BackSpace>", self._on_backspace)
        t.bind("<Delete>", self._on_delete)
        t.bind("<Control-d>", self._on_ctrl_d)
        t.bind("<Control-c>", self._on_ctrl_c)
        t.bind("<Control-l>", lambda e: (self.clear(), "break")[1])
        t.bind("<<Paste>>", self._to_input)
        t.bind("<<PasteSelection>>", self._to_input)
        t.bind("<<Cut>>", self._on_cut)

    # output -------------------------------------------------------------
    def write(self, s, tag=None):
        if not s:
            return
        s = ANSI_RE.sub("", s).replace("\r\n", "\n").replace("\r", "")
        t = self.text
        t.mark_set("out", "inp")
        t.mark_gravity("out", "right")
        t.insert("out", s, tag or ())
        t.mark_set("inp", "out")
        lines = int(t.index("end-1c").split(".")[0])
        if lines > self.MAX_LINES:
            t.delete("1.0", f"{lines - self.MAX_LINES}.0")
        t.see("end")

    def ensure_newline(self):
        t = self.text
        if t.compare("inp", ">", "1.0") and t.get("inp-1c") != "\n":
            self.write("\n")

    def line(self, s, tag=None):
        self.ensure_newline()
        self.write(s + "\n", tag)

    def clear(self):
        self.text.delete("1.0", "inp")

    # input --------------------------------------------------------------
    def _in_output(self, index="insert"):
        return self.text.compare(index, "<", "inp")

    def _sel_in_output(self):
        return bool(self.text.tag_ranges("sel")) and self._in_output("sel.first")

    def _to_input(self, event=None):
        if self._in_output():
            self.text.mark_set("insert", "end-1c")
        if self._sel_in_output():
            self.text.tag_remove("sel", "1.0", "end")

    def _on_key(self, event):
        if event.keysym in self.NAV_KEYS or (event.state & 0x4 and event.keysym.lower() in "ac"):
            return None
        if event.char or event.keysym in ("Tab",):
            self._to_input()
        return None

    def _on_return(self, event):
        t = self.text
        line = t.get("inp", "end-1c")
        t.tag_add("input", "inp", "end-1c")
        t.insert("end", "\n")
        t.mark_set("inp", "end-1c")
        t.mark_set("insert", "end-1c")
        t.see("end")
        self.on_input(line + "\n")
        return "break"

    def _on_backspace(self, event):
        if self.text.tag_ranges("sel"):
            return "break" if self._sel_in_output() else None
        if self.text.compare("insert", "<=", "inp"):
            return "break"
        return None

    def _on_delete(self, event):
        if self._sel_in_output() or self._in_output():
            return "break"
        return None

    def _on_cut(self, event):
        return "break" if self._sel_in_output() else None

    def _on_ctrl_d(self, event):
        t = self.text
        pending = t.get("inp", "end-1c")
        t.tag_add("input", "inp", "end-1c")
        t.insert("end", "^D\n", "dim")
        t.mark_set("inp", "end-1c")
        t.mark_set("insert", "end-1c")
        self.on_eof(pending)
        return "break"

    def _on_ctrl_c(self, event):
        if self.text.tag_ranges("sel"):
            return None  # copy
        self.text.insert("end", "^C\n", "dim")
        self.text.mark_set("inp", "end-1c")
        self.on_interrupt()
        return "break"


CPP_RULES = [
    ("kw", re.compile(
        r"\b(?:alignas|auto|break|case|catch|class|const|constexpr|continue|"
        r"default|delete|do|else|enum|explicit|extern|false|for|friend|goto|if|"
        r"inline|mutable|namespace|new|noexcept|nullptr|operator|private|"
        r"protected|public|return|sizeof|static|static_cast|struct|switch|"
        r"template|this|throw|true|try|typedef|typename|union|using|virtual|"
        r"volatile|while)\b")),
    ("type", re.compile(
        r"\b(?:bool|char|double|float|int|long|short|signed|unsigned|void|"
        r"size_t|string|vector|map|set|multiset|unordered_map|unordered_set|"
        r"pair|tuple|queue|stack|deque|priority_queue|array|bitset|list|ll|ull|"
        r"int64_t|uint64_t|std)\b")),
    ("num", re.compile(r"\b(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)[uUlLfF]*\b")),
    ("pre", re.compile(r"^[ \t]*#[^\n]*", re.M)),
    ("str", re.compile(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'')),
    ("com", re.compile(r"//[^\n]*|/\*.*?(?:\*/|\Z)", re.S)),
]
CPP_COLORS = {"kw": "#a626a4", "type": "#0184bc", "num": "#986801",
              "pre": "#c18401", "str": "#50a14f", "com": "#a0a1a7"}

CPP_TEMPLATE = """#include <bits/stdc++.h>
using namespace std;

int main() {

    return 0;
}
"""


class CodeEditor(ttk.Frame):
    """Text widget with line numbers, C++ highlighting and auto indent."""

    def __init__(self, master, on_change=None):
        super().__init__(master)
        self.on_change = on_change
        self.font = mono_font(11)
        self.gutter = tk.Canvas(self, width=44, bg="#f3f3f3", highlightthickness=0)
        self.text = tk.Text(self, wrap="none", undo=True, maxundo=-1,
                            autoseparators=True, font=self.font, bg="#ffffff",
                            fg="#383a42", insertbackground="#000000",
                            selectbackground="#cde3fb", relief="flat",
                            padx=6, pady=4, tabs=(tkfont.Font(font=self.font).measure("    "),))
        ys = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.text.yview)
        xs = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.text.xview)
        self._ys = ys
        self.text.configure(yscrollcommand=self._on_yscroll, xscrollcommand=xs.set)
        self.gutter.grid(row=0, column=0, sticky="ns")
        self.text.grid(row=0, column=1, sticky="nsew")
        ys.grid(row=0, column=2, sticky="ns")
        xs.grid(row=1, column=1, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        for tag, color in CPP_COLORS.items():
            self.text.tag_configure(tag, foreground=color)
        self.text.tag_configure("com", foreground=CPP_COLORS["com"],
                                font=self.font + ("italic",))
        self._hl_job = None

        t = self.text
        t.bind("<Tab>", self._on_tab)
        t.bind("<ISO_Left_Tab>", self._on_shift_tab)
        t.bind("<Shift-Tab>", self._on_shift_tab)
        t.bind("<Return>", self._on_return)
        t.bind("<KeyRelease-braceright>", self._on_close_brace)
        t.bind("<Control-y>", lambda e: (t.edit_redo() if t.edit("canredo") else None, "break")[1])
        t.bind("<<Modified>>", self._on_modified)
        t.bind("<Configure>", lambda e: self._redraw_gutter())

    # content ------------------------------------------------------------
    def get(self):
        return self.text.get("1.0", "end-1c")

    def set(self, content):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.edit_reset()
        self.text.mark_set("insert", "1.0")
        self._highlight()

    # editing helpers ----------------------------------------------------
    def _on_tab(self, event):
        t = self.text
        if t.tag_ranges("sel"):
            first = int(t.index("sel.first").split(".")[0])
            last = int(t.index("sel.last").split(".")[0])
            for line in range(first, last + 1):
                t.insert(f"{line}.0", "    ")
        else:
            t.insert("insert", "    ")
        return "break"

    def _on_shift_tab(self, event):
        t = self.text
        if t.tag_ranges("sel"):
            first = int(t.index("sel.first").split(".")[0])
            last = int(t.index("sel.last").split(".")[0])
        else:
            first = last = int(t.index("insert").split(".")[0])
        for line in range(first, last + 1):
            lead = t.get(f"{line}.0", f"{line}.4")
            n = len(lead) - len(lead.lstrip(" "))
            if n:
                t.delete(f"{line}.0", f"{line}.{n}")
        return "break"

    def _on_return(self, event):
        t = self.text
        if t.tag_ranges("sel"):
            t.delete("sel.first", "sel.last")
        before = t.get("insert linestart", "insert")
        indent = re.match(r"[ \t]*", before).group(0)
        if before.rstrip().endswith("{"):
            indent += "    "
        t.insert("insert", "\n" + indent)
        t.see("insert")
        return "break"

    def _on_close_brace(self, event):
        t = self.text
        before = t.get("insert linestart", "insert-1c")
        if before and not before.strip() and before.endswith("    "):
            t.delete("insert-5c", "insert-1c")

    # highlighting -------------------------------------------------------
    def _on_modified(self, event=None):
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        if self._hl_job:
            self.after_cancel(self._hl_job)
        self._hl_job = self.after(150, self._highlight)
        self._redraw_gutter()
        if self.on_change:
            self.on_change()

    def _highlight(self):
        self._hl_job = None
        content = self.get()
        starts = [0] + [m.end() for m in re.finditer("\n", content)]

        def index(offset):
            line = bisect_right(starts, offset) - 1
            return f"{line + 1}.{offset - starts[line]}"

        for tag in CPP_COLORS:
            self.text.tag_remove(tag, "1.0", "end")
        for tag, pattern in CPP_RULES:
            for m in pattern.finditer(content):
                if m.end() > m.start():
                    self.text.tag_add(tag, index(m.start()), index(m.end()))
        self._redraw_gutter()

    # line numbers -------------------------------------------------------
    def _on_yscroll(self, first, last):
        self._ys.set(first, last)
        self._redraw_gutter()

    def _redraw_gutter(self):
        g = self.gutter
        g.delete("all")
        width = int(g.winfo_width()) or 44
        index = self.text.index("@0,0")
        while True:
            info = self.text.dlineinfo(index)
            if info is None:
                break
            g.create_text(width - 8, info[1] + 4, anchor="ne", fill="#9a9a9a",
                          text=index.split(".")[0], font=self.font)
            nxt = self.text.index(f"{index}+1line")
            if nxt == index:
                break
            index = nxt


class ConsistencyCalendar(ttk.Frame):
    """GitHub style heat map of problems per day."""

    COLORS = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]
    ROLLING = "Last 12 months"

    def __init__(self, master, on_day_click=None):
        super().__init__(master)
        self.on_day_click = on_day_click
        self.counts = {}
        self.names = defaultdict(list)
        self.items = {}

        head = ttk.Frame(self)
        head.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Label(head, text="Consistency Calendar", font=("TkDefaultFont", 11, "bold")
                  ).pack(side=tk.LEFT)
        self.period = tk.StringVar(value=self.ROLLING)
        self.period_box = ttk.Combobox(head, textvariable=self.period, width=16,
                                       state="readonly", values=[self.ROLLING])
        self.period_box.pack(side=tk.RIGHT)
        self.period_box.bind("<<ComboboxSelected>>", lambda e: self.draw())

        self.canvas = tk.Canvas(self, bg="white", highlightthickness=0, height=170)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        self.info = ttk.Label(self, text="", foreground="#57606a", anchor="w")
        self.info.pack(fill=tk.X, padx=12, pady=(0, 10))

        self.canvas.bind("<Configure>", lambda e: self.draw())
        self.canvas.tag_bind("day", "<Enter>", self._on_enter)
        self.canvas.tag_bind("day", "<Leave>", self._on_leave)
        self.canvas.tag_bind("day", "<Button-1>", self._on_click)

    def set_problems(self, problems):
        self.counts = defaultdict(int)
        self.names = defaultdict(list)
        for p in problems:
            try:
                day = dt.date.fromisoformat(p.get("date_of_doing", ""))
            except ValueError:
                continue
            self.counts[day] += 1
            self.names[day].append(p.get("name", "?"))
        this_year = dt.date.today().year
        years = sorted({d.year for d in self.counts} | {this_year}, reverse=True)
        self.period_box.configure(values=[self.ROLLING] + [str(y) for y in years])
        self.draw()

    def _range(self):
        today = dt.date.today()
        sel = self.period.get()
        if sel.isdigit():
            start, end = dt.date(int(sel), 1, 1), dt.date(int(sel), 12, 31)
        else:
            end = today
            start = today - dt.timedelta(days=364)
        grid_start = start - dt.timedelta(days=(start.weekday() + 1) % 7)  # Sunday
        return start, end, grid_start

    def _level(self, count):
        return min(count, len(self.COLORS) - 1)

    def draw(self):
        c = self.canvas
        c.delete("all")
        self.items = {}
        width, height = c.winfo_width(), c.winfo_height()
        if width < 60 or height < 60:
            return
        today = dt.date.today()
        start, end, grid_start = self._range()
        weeks = (end - grid_start).days // 7 + 1
        left, top, bottom = 34, 20, 30

        step = min(24.0, (width - left - 20) / weeks, (height - top - bottom) / 7)
        step = max(step, 6.0)
        gap = max(2, round(step * 0.18))
        cell = step - gap
        grid_w = weeks * step
        x0 = max(left + 4, (width - grid_w - left) / 2 + left)
        y0 = top + max(0, (height - top - bottom - 7 * step) / 2)
        small = ("TkDefaultFont", 8)

        for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
            c.create_text(x0 - 6, y0 + row * step + cell / 2, text=label, anchor="e",
                          font=small, fill="#57606a")

        last_label_x = -1e9
        day = grid_start
        while day <= end:
            offset = (day - grid_start).days
            col, row = divmod(offset, 7)
            x = x0 + col * step
            y = y0 + row * step
            if day.day == 1 or (day == start and day.day < 20):
                if x - last_label_x >= 3 * step:
                    c.create_text(x, y0 - 6, text=day.strftime("%b"), anchor="sw",
                                  font=small, fill="#57606a")
                    last_label_x = x
            if start <= day <= min(end, today):
                count = self.counts.get(day, 0)
                item = c.create_rectangle(
                    x, y, x + cell, y + cell, fill=self.COLORS[self._level(count)],
                    outline="#57606a" if day == today else "#d0d7de",
                    width=2 if day == today else 1, tags=("day",))
                self.items[item] = day
            day += dt.timedelta(days=1)

        # summary and legend
        in_range = sum(n for d, n in self.counts.items() if start <= d <= end)
        current, longest = self._streaks(today)
        period = "the last 12 months" if not self.period.get().isdigit() else self.period.get()
        y_text = y0 + 7 * step + 12
        c.create_text(x0, y_text, anchor="w", font=small, fill="#57606a",
                      text=f"{in_range} problem{'s' * (in_range != 1)} in {period}"
                           f"   ·   current streak {current} day{'s' * (current != 1)}"
                           f"   ·   longest streak {longest} day{'s' * (longest != 1)}")
        lx = x0 + grid_w - len(self.COLORS) * 13 - 30
        c.create_text(lx - 4, y_text, anchor="e", text="Less", font=small, fill="#57606a")
        for i, color in enumerate(self.COLORS):
            c.create_rectangle(lx + i * 13, y_text - 5, lx + i * 13 + 10, y_text + 5,
                               fill=color, outline="#d0d7de")
        c.create_text(lx + len(self.COLORS) * 13 + 2, y_text, anchor="w", text="More",
                      font=small, fill="#57606a")

    def _streaks(self, today):
        days = {d for d, n in self.counts.items() if n}
        current = 0
        d = today if today in days else today - dt.timedelta(days=1)
        while d in days:
            current += 1
            d -= dt.timedelta(days=1)
        longest = run = 0
        prev = None
        for d in sorted(days):
            run = run + 1 if prev and (d - prev).days == 1 else 1
            longest = max(longest, run)
            prev = d
        return current, longest

    def _day_under_mouse(self):
        item = self.canvas.find_withtag("current")
        return (item[0], self.items.get(item[0])) if item else (None, None)

    def _on_enter(self, event):
        item, day = self._day_under_mouse()
        if day is None:
            return
        self.canvas.itemconfigure(item, outline="#1f2328", width=2)
        n = self.counts.get(day, 0)
        when = day.strftime("%A, %d %b %Y")
        if n:
            names = ", ".join(self.names[day][:6]) + (" …" if n > 6 else "")
            self.info.configure(text=f"{n} problem{'s' * (n != 1)} on {when}: {names}"
                                     "   (click to list them)")
        else:
            self.info.configure(text=f"No problems on {when}")

    def _on_leave(self, event):
        for item, day in self.items.items():
            today = day == dt.date.today()
            self.canvas.itemconfigure(item, outline="#57606a" if today else "#d0d7de",
                                      width=2 if today else 1)
        self.info.configure(text="")

    def _on_click(self, event):
        _, day = self._day_under_mouse()
        if day is not None and self.on_day_click:
            self.on_day_click(day)


# --------------------------------------------------------------------------
# problem editor window
# --------------------------------------------------------------------------

class ProblemEditor(tk.Toplevel):
    """Name on top, code left, terminal top right, test cases bottom right."""

    def __init__(self, app, loaded=None):
        super().__init__(app.root)
        self.app = app
        self.session = None
        self.after_session = None
        self.started = time.monotonic()
        self.geometry("1300x850")
        self.minsize(900, 560)

        loaded = loaded or {}
        row = loaded.get("row", {})
        self.problem_id = int(row["id"]) if row.get("id") else None
        self.meta = default_meta()
        self.meta.update({k: row[k] for k in META_KEYS if k in row})
        self.loaded_completed = is_true(self.meta.get("is_completed"))
        self.revision_bumped = False
        self.confirmed_name = row.get("name") if self.problem_id is not None else None

        self.name_var = tk.StringVar(value=row.get("name", ""))
        self._build()
        self.code.set(loaded.get("code", CPP_TEMPLATE if not row else ""))
        self._set_test_cases(loaded.get("testcases", ""))
        self.saved_state = self._state() if self.problem_id is not None else None

        self.name_var.trace_add("write", lambda *a: self._update_title())
        self._update_title()
        self._tick()
        self.protocol("WM_DELETE_WINDOW", self.close)
        if self.problem_id is None:
            self.name_entry.focus_set()
        else:
            self.code.text.focus_set()
            self.terminal.line(f"Opened problem {self.problem_id}: {row.get('name')}"
                               f"  ({row.get('file_path', '')})", "dim")

    # layout -------------------------------------------------------------
    def _build(self):
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill=tk.X)
        ttk.Label(top, text="Problem name", font=("TkDefaultFont", 11, "bold")
                  ).pack(side=tk.LEFT)
        self.name_entry = ttk.Entry(top, textvariable=self.name_var, width=34,
                                    font=("TkDefaultFont", 12))
        self.name_entry.pack(side=tk.LEFT, padx=(8, 12))
        self.name_entry.bind("<Return>", lambda e: (self._normalize_name(), self.code.text.focus_set()))
        self.name_entry.bind("<FocusOut>", lambda e: self._normalize_name())

        self.buttons = {}
        for key, text, cmd in (
            ("submit", "Submit ✓", self.submit),
            ("stop", "Stop", self.stop),
            ("runi", "Run (manual input)", lambda: self._run_action("RUNI", "run (manual input)")),
            ("run", "Run", lambda: self._run_action("RUN", "run")),
            ("compile", "Compile", lambda: self._run_action("COMPILE", "compile")),
            ("save", "Save", lambda: self._run_action("SUBMIT", "save")),
            ("details", "Details…", self.edit_details),
        ):
            b = ttk.Button(top, text=text, command=cmd)
            b.pack(side=tk.RIGHT, padx=2)
            self.buttons[key] = b
        self.buttons["stop"].state(["disabled"])

        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=6)

        left = ttk.Frame(main)
        self.code_label = ttk.Label(left, text="Code", anchor="w")
        self.code_label.pack(fill=tk.X, padx=4, pady=(4, 2))
        self.code = CodeEditor(left)
        self.code.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 4))

        right = ttk.PanedWindow(main, orient=tk.VERTICAL)
        term_frame = ttk.Frame(right)
        head = ttk.Frame(term_frame)
        head.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(head, text="Terminal", anchor="w").pack(side=tk.LEFT)
        ttk.Button(head, text="Clear", width=6,
                   command=lambda: self.terminal.clear()).pack(side=tk.RIGHT)
        self.term_hint = ttk.Label(head, text="", foreground="#57606a")
        self.term_hint.pack(side=tk.RIGHT, padx=8)
        self.terminal = Terminal(term_frame, self._terminal_input, self._terminal_eof,
                                 self.stop)
        self.terminal.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 4))

        tc_frame = ttk.Frame(right)
        ttk.Label(tc_frame, anchor="w",
                  text="Test cases (stdin for Run, leave empty to type the input "
                       "in the terminal)").pack(fill=tk.X, padx=4, pady=(4, 2))
        tc_inner = ttk.Frame(tc_frame)
        tc_inner.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 4))
        self.tests = tk.Text(tc_inner, wrap="none", undo=True, font=mono_font(10),
                             bg="#ffffff", relief="flat", padx=6, pady=4)
        tsb = ttk.Scrollbar(tc_inner, command=self.tests.yview)
        self.tests.configure(yscrollcommand=tsb.set)
        self.tests.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tsb.pack(side=tk.RIGHT, fill=tk.Y)

        right.add(term_frame, weight=3)
        right.add(tc_frame, weight=2)
        main.add(left, weight=3)
        main.add(right, weight=2)

        bar = ttk.Frame(self, padding=(10, 3))
        bar.pack(fill=tk.X)
        self.status = ttk.Label(bar, text="", anchor="w")
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.clock = ttk.Label(bar, text="", anchor="e", foreground="#57606a")
        self.clock.pack(side=tk.RIGHT)

        for seq, action in (
            ("<Control-s>", lambda: self._run_action("SUBMIT", "save")),
            ("<F7>", lambda: self._run_action("COMPILE", "compile")),
            ("<Control-b>", lambda: self._run_action("COMPILE", "compile")),
            ("<F5>", lambda: self._run_action("RUN", "run")),
            ("<F6>", lambda: self._run_action("RUNI", "run (manual input)")),
            ("<Control-Return>", self.submit),
        ):
            self.bind(seq, lambda e, a=action: (a(), "break")[1])

    # helpers ------------------------------------------------------------
    def _set_test_cases(self, content):
        self.tests.delete("1.0", "end")
        self.tests.insert("1.0", content)
        self.tests.edit_reset()

    def _test_cases(self):
        content = self.tests.get("1.0", "end-1c")
        return content if content.strip() else ""

    def _state(self):
        return (self.name_var.get(), self.code.get(), self._test_cases(),
                tuple(self.meta.get(k, "") for k in META_KEYS))

    def dirty(self):
        return self._state() != self.saved_state

    def _update_title(self):
        name = sanitize_name(self.name_var.get()) or "Untitled problem"
        self.title(f"{name} — {APP_NAME}")
        self.code_label.configure(text=f"Code — test/{name}.cpp" if name else "Code")

    def _tick(self):
        try:
            secs = int(time.monotonic() - self.started)
            ident = f"id {self.problem_id}" if self.problem_id is not None else "not in database yet"
            self.clock.configure(text=f"{ident}   ·   time {secs // 60:02d}:{secs % 60:02d}")
            self.after(1000, self._tick)
        except tk.TclError:
            pass

    def set_status(self, text, color="#1f2328"):
        self.status.configure(text=text, foreground=color)

    def _normalize_name(self):
        raw = self.name_var.get()
        name = sanitize_name(raw)
        if name != raw:
            self.name_var.set(name)
            if name:
                self.terminal.line(f"name changed to '{name}' (letters, digits, _ and - only)",
                                   "dim")
        return name

    def _validated_name(self):
        """The problem name, after making sure no other problem's files get overwritten."""
        name = self._normalize_name()
        if not name:
            messagebox.showwarning(APP_NAME, "Enter the problem name at the top first.",
                                   parent=self)
            self.name_entry.focus_set()
            return None
        if name == self.confirmed_name:
            return name

        same = [p for p in self.app.problems
                if p.get("name") == name and p.get("id") != str(self.problem_id)]
        if same:
            other = same[0]
            if messagebox.askyesno(
                    APP_NAME, f"A problem named '{name}' already exists "
                              f"(id {other.get('id')}, {other.get('date_of_doing')}).\n\n"
                              "Open it instead? (No: pick another name)", parent=self):
                self.app.open_problem(int(other["id"]))
            self.name_entry.focus_set()
            return None

        test_dir = self.app.get_test_dir()
        if not test_dir:
            messagebox.showerror(APP_NAME, "The backend did not report its test folder, "
                                           "is it built?", parent=self)
            return None
        code_path = os.path.join(test_dir, name + ".cpp")
        if os.path.exists(code_path):
            answer = messagebox.askyesnocancel(
                APP_NAME, f"test/{name}.cpp already exists.\n\n"
                          "Yes: load that file into the editor\n"
                          "No: overwrite it with the editor content\n"
                          "Cancel: choose another name", parent=self)
            if answer is None:
                self.name_entry.focus_set()
                return None
            if answer:
                self._load_files(test_dir, name)
                self.confirmed_name = name
                return None
        self.confirmed_name = name
        return name

    def _load_files(self, test_dir, name):
        with open(os.path.join(test_dir, name + ".cpp"), encoding="utf-8",
                  errors="replace") as f:
            self.code.set(f.read())
        tc_path = os.path.join(test_dir, f"input_{name}.txt")
        if os.path.exists(tc_path):
            with open(tc_path, encoding="utf-8", errors="replace") as f:
                self._set_test_cases(f.read())
        self.terminal.line(f"loaded test/{name}.cpp, press the button again to continue",
                           "dim")

    # actions ------------------------------------------------------------
    def _run_action(self, action, label, before=None):
        if self.session and self.session.alive:
            self.bell()
            self.set_status("Wait for the running command to finish, or press Stop.",
                            "#9a6700")
            return
        name = self._validated_name()
        if not name:
            return
        if before:
            before()

        state = self._state()
        lines = ["NAME", name, "CODE", escape(state[1]), "TESTCASES", escape(state[2])]
        if self.problem_id is not None:
            lines += ["FIELD", f"id={self.problem_id}"]
        for key in META_KEYS:
            lines += ["FIELD", f"{key}={escape(self.meta.get(key, ''))}"]
        # every action stores the files and the database row first
        lines.append("SUBMIT")
        if action != "SUBMIT":
            lines.append(action)

        self.terminal.line(f"$ {label} {name}", "prompt")
        self.set_status(f"{label.capitalize()}…")
        self._db_ok = None
        self._pending_state = state
        self.session = PtySession(self, self.terminal.write, self._on_reply,
                                  self._on_exit)
        try:
            self.session.start(lines, action)
        except (OSError, BackendError) as e:
            self.session = None
            self.terminal.line(str(e), "err")
            self.set_status("Could not start the backend.", "#cf222e")
            return
        self._set_running(True)

    def _on_reply(self, tag, payload):
        text = unescape(payload)
        t = self.terminal
        if tag == "RESULT":
            ok = "succes" in text.lower() and "error" not in text.lower()
            t.line(("✔ " if ok else "✘ ") + text, "good" if ok else "bad")
            self.term_hint.configure(text="")
        elif tag == "ID":
            self.problem_id = int(text)
            self._db_ok = True
            self.saved_state = self._pending_state
            self.confirmed_name = self._pending_state[0]
        elif tag == "OK":
            t.line(text, "ok")
        elif tag == "ERR":
            if text.startswith("database"):
                self._db_ok = False
            t.line(text, "err")
        elif tag == "WARN":
            t.line(text, "warn")
        elif tag == "INFO":
            t.line(text, "info")
        elif tag == "INTERACTIVE":
            self.term_hint.configure(text="program input: type here · Ctrl-D EOF · Ctrl-C stop")
            self.terminal.text.focus_set()
            self.terminal.text.mark_set("insert", "end-1c")

    def _on_exit(self, returncode, stopped):
        self.session = None
        self._set_running(False)
        self.term_hint.configure(text="")
        if stopped:
            self.terminal.line("[stopped]", "warn")
        elif returncode not in (0, None):
            self.terminal.line(f"[backend exited with code {returncode}]", "err")
        if self._db_ok:
            self.set_status(f"Saved files and database row (id {self.problem_id}).", "#1a7f37")
            self.app.refresh()
        elif self._db_ok is False:
            self.set_status("Files saved, but the database save failed (see terminal).",
                            "#cf222e")
        else:
            self.set_status("Done." if not stopped else "Stopped.")
        callback, self.after_session = self.after_session, None
        if callback:
            callback()

    def _set_running(self, running):
        for key, b in self.buttons.items():
            if key == "stop":
                b.state(["!disabled"] if running else ["disabled"])
            elif key != "details":
                b.state(["disabled"] if running else ["!disabled"])

    def _terminal_input(self, line):
        if self.session and self.session.alive and self.session.interactive:
            self.session.send(line)
        else:
            self.terminal.line("(no program is reading input, use Run with empty test "
                               "cases or Run (manual input))", "dim")

    def _terminal_eof(self, pending):
        if self.session and self.session.alive and self.session.interactive:
            self.session.send(pending + "\x04")

    def stop(self):
        if self.session and self.session.alive:
            self.session.stop()

    def submit(self):
        def mark_done():
            if self.loaded_completed and not self.revision_bumped:
                count = int(self.meta.get("revision_count") or 0)
                self.meta["revision_count"] = str(count + 1)
                self.revision_bumped = True
            self.meta["is_completed"] = "true"
            if not self.meta.get("time_taken_minutes"):
                minutes = round((time.monotonic() - self.started) / 60)
                self.meta["time_taken_minutes"] = str(max(1, minutes))
        self._run_action("SUBMIT", "submit", before=mark_done)

    def edit_details(self):
        result = ask_metadata(self, self.meta, f"Details — {self.name_var.get() or 'problem'}")
        if result is not None:
            self.meta.update(result)
            self.set_status("Details changed, press Save to store them.")

    def close(self, force=False):
        if not force and self.dirty():
            answer = messagebox.askyesnocancel(
                APP_NAME, f"Save '{self.name_var.get() or 'this problem'}' to the files "
                          "and the database before closing?", parent=self)
            if answer is None:
                return
            if answer:
                if self.session and self.session.alive:
                    self.session.stop()
                    self.after(300, self.close)
                    return
                self.after_session = lambda: self.close(force=not self.dirty())
                self._run_action("SUBMIT", "save")
                if self.session is None:  # could not start (e.g. no name)
                    self.after_session = None
                return
        if self.session and self.session.alive:
            self.session.stop()
        if self in self.app.editors:
            self.app.editors.remove(self)
        self.destroy()


# --------------------------------------------------------------------------
# problems browser
# --------------------------------------------------------------------------

class ProblemsWindow(tk.Toplevel):
    COLUMNS = [("id", "ID", 50), ("name", "Name", 210), ("date_of_doing", "Date", 95),
               ("platform", "Platform", 105), ("problem_type", "Type", 115),
               ("difficulty", "Difficulty", 80), ("is_completed", "Done", 55),
               ("revision_count", "Revisions", 75), ("importance_rating", "Importance", 85),
               ("time_taken_minutes", "Minutes", 65), ("tags", "Tags", 170)]

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title(f"All problems — {APP_NAME}")
        self.geometry("1150x620")
        self.sort_key, self.sort_reverse = "date_of_doing", True
        self.date_filter = None

        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill=tk.X)
        ttk.Label(bar, text="Search").pack(side=tk.LEFT)
        self.search = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.search, width=28)
        entry.pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(bar, text="Status").pack(side=tk.LEFT)
        self.status_filter = tk.StringVar(value="All")
        ttk.Combobox(bar, textvariable=self.status_filter, state="readonly", width=10,
                     values=["All", "Completed", "Pending"]).pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(bar, text="Difficulty").pack(side=tk.LEFT)
        self.diff_filter = tk.StringVar(value="All")
        ttk.Combobox(bar, textvariable=self.diff_filter, state="readonly", width=9,
                     values=["All"] + DIFFICULTIES).pack(side=tk.LEFT, padx=(6, 12))
        self.date_label = ttk.Label(bar, text="", foreground="#0969da")
        self.date_label.pack(side=tk.LEFT)
        self.date_clear = ttk.Button(bar, text="× date", width=7,
                                     command=lambda: self.set_date_filter(None))
        for var in (self.search, self.status_filter, self.diff_filter):
            var.trace_add("write", lambda *a: self.reload())

        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True, padx=10)
        self.tree = ttk.Treeview(body, columns=[c[0] for c in self.COLUMNS],
                                 show="headings", selectmode="browse")
        for key, label, width in self.COLUMNS:
            self.tree.heading(key, text=label, command=lambda k=key: self._sort(k))
            self.tree.column(key, width=width, anchor="w", stretch=key in ("name", "tags"))
        sb = ttk.Scrollbar(body, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.tag_configure("done", foreground="#1a7f37")
        self.tree.bind("<Double-1>", lambda e: self.open_selected())
        self.tree.bind("<Return>", lambda e: self.open_selected())
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_detail())

        self.detail = ttk.Label(self, text="", anchor="w", foreground="#57606a",
                                wraplength=1100, justify="left")
        self.detail.pack(fill=tk.X, padx=12, pady=(6, 0))

        actions = ttk.Frame(self, padding=(10, 8))
        actions.pack(fill=tk.X)
        for text, cmd in (("Open in editor", self.open_selected),
                          ("Edit details…", self.edit_selected),
                          ("Toggle completed", self.toggle_completed),
                          ("+1 revision", self.add_revision),
                          ("Delete", self.delete_selected)):
            ttk.Button(actions, text=text, command=cmd).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(actions, text="Refresh", command=app.refresh).pack(side=tk.RIGHT)
        self.count_label = ttk.Label(actions, text="", foreground="#57606a")
        self.count_label.pack(side=tk.RIGHT, padx=10)

        self.protocol("WM_DELETE_WINDOW", self._close)
        entry.focus_set()
        self.reload()

    def _close(self):
        self.app.problems_window = None
        self.destroy()

    def set_date_filter(self, day):
        self.date_filter = day
        if day:
            self.date_label.configure(text=f"on {day.strftime('%d %b %Y')}")
            self.date_clear.pack(side=tk.LEFT, padx=6)
        else:
            self.date_label.configure(text="")
            self.date_clear.pack_forget()
        self.reload()

    def _visible(self):
        query = self.search.get().strip().lower()
        status, diff = self.status_filter.get(), self.diff_filter.get()
        for p in self.app.problems:
            if self.date_filter and p.get("date_of_doing") != self.date_filter.isoformat():
                continue
            if status == "Completed" and not is_true(p.get("is_completed")):
                continue
            if status == "Pending" and is_true(p.get("is_completed")):
                continue
            if diff != "All" and p.get("difficulty") != diff:
                continue
            if query and not any(query in p.get(k, "").lower() for k in
                                 ("name", "platform", "problem_type", "tags", "comment")):
                continue
            yield p

    def _sort(self, key):
        if self.sort_key == key:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_key, self.sort_reverse = key, False
        self.reload()

    def reload(self):
        selected = self.selected_id()
        self.tree.delete(*self.tree.get_children())
        numeric = {"id", "revision_count", "importance_rating", "time_taken_minutes"}

        def sort_value(p):
            v = p.get(self.sort_key, "")
            if self.sort_key in numeric:
                return (0, int(v)) if v.lstrip("-").isdigit() else (1, 0)
            return (0, v.lower())

        rows = sorted(self._visible(), key=sort_value, reverse=self.sort_reverse)
        for p in rows:
            values = [("✓" if is_true(p.get(k)) else "") if k == "is_completed"
                      else p.get(k, "") for k, _, _ in self.COLUMNS]
            self.tree.insert("", "end", iid=p["id"], values=values,
                             tags=("done",) if is_true(p.get("is_completed")) else ())
        if selected is not None and self.tree.exists(str(selected)):
            self.tree.selection_set(str(selected))
        self.count_label.configure(text=f"{len(rows)} of {len(self.app.problems)} problems")
        self._show_detail()

    def selected_id(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def selected(self):
        pid = self.selected_id()
        return next((p for p in self.app.problems if p["id"] == str(pid)), None)

    def _show_detail(self):
        p = self.selected()
        if not p:
            self.detail.configure(text="Select a problem, double click opens it in the editor.")
            return
        parts = [p.get("file_path", "")]
        if p.get("testcases_path"):
            parts.append(f"test cases: {p['testcases_path']}")
        if p.get("time_complexity") or p.get("space_complexity"):
            parts.append(f"time {p.get('time_complexity') or '?'}, "
                         f"space {p.get('space_complexity') or '?'}")
        if p.get("comment"):
            parts.append("comment: " + p["comment"].replace("\n", " ⏎ "))
        self.detail.configure(text="   ·   ".join(parts))

    def _need_selection(self):
        p = self.selected()
        if not p:
            messagebox.showinfo(APP_NAME, "Select a problem first.", parent=self)
        return p

    def open_selected(self):
        p = self._need_selection()
        if p:
            self.app.open_problem(int(p["id"]))

    def edit_selected(self):
        p = self._need_selection()
        if not p:
            return
        result = ask_metadata(self, p, f"Details — {p.get('name')}")
        if result is None:
            return
        changed = {k: v for k, v in result.items() if v != p.get(k, "")}
        self.app.update_fields(int(p["id"]), changed, parent=self)

    def toggle_completed(self):
        p = self._need_selection()
        if p:
            value = "false" if is_true(p.get("is_completed")) else "true"
            self.app.update_fields(int(p["id"]), {"is_completed": value}, parent=self)

    def add_revision(self):
        p = self._need_selection()
        if p:
            count = int(p.get("revision_count") or 0) + 1
            self.app.update_fields(int(p["id"]), {"revision_count": str(count)}, parent=self)

    def delete_selected(self):
        p = self._need_selection()
        if not p:
            return
        if not messagebox.askyesno(
                APP_NAME, f"Delete problem '{p.get('name')}' (id {p['id']}) from the "
                          "database?\n\nIts files in test/ are kept.", parent=self):
            return
        self.app.delete_problem(int(p["id"]), parent=self)


# --------------------------------------------------------------------------
# welcome window
# --------------------------------------------------------------------------

def render_statistics(frame, problems):
    """Fill the statistics panel of the welcome window.

    Left empty on purpose, to be implemented with data_analysis.
    `frame` is the empty panel, `problems` the rows of the problems table
    (dicts of column -> text). Called after every refresh.
    """


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("1150x760")
        self.root.minsize(820, 520)
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Side.TButton", padding=(10, 8), anchor="w")

        self.problems = []
        self.test_dir = None
        self.editors = []
        self.problems_window = None
        self._jobs = queue.Queue()

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.bind("<Control-n>", lambda e: self.new_problem())
        self.root.bind("<F5>", lambda e: self.refresh())
        self.root.after(50, self._poll_jobs)
        if not BACKEND:
            self.root.after(200, lambda: messagebox.showerror(
                APP_NAME, "The C++ backend (probs_mang) was not found.\n\nBuild it with:\n"
                          "cmake -S . -B build && cmake --build build", parent=self.root))
        self.refresh()

    def _build(self):
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # left sidebar: basic operations
        side = ttk.Frame(paned, relief=tk.SUNKEN, padding=10)
        ttk.Label(side, text="Options", font=("TkDefaultFont", 11, "bold")
                  ).pack(fill=tk.X, pady=(0, 6))
        for text, cmd in (("＋  New Problem", self.new_problem),
                          ("☰  All Problems", self.show_problems),
                          ("⟳  Refresh", self.refresh),
                          ("📁  Open Files Folder", self.open_folder)):
            ttk.Button(side, text=text, command=cmd, style="Side.TButton"
                       ).pack(fill=tk.X, pady=3)

        ttk.Separator(side).pack(fill=tk.X, pady=10)
        ttk.Label(side, text="Recent", font=("TkDefaultFont", 10, "bold")).pack(fill=tk.X)
        self.recent = tk.Listbox(side, activestyle="none", relief="flat", height=12,
                                 highlightthickness=0, selectbackground="#ddf4ff",
                                 selectforeground="#1f2328")
        self.recent.pack(fill=tk.BOTH, expand=True, pady=(4, 6))
        self.recent.bind("<Double-1>", lambda e: self._open_recent())
        self.recent.bind("<Return>", lambda e: self._open_recent())
        self._recent_ids = []

        self.db_status = ttk.Label(side, text="", wraplength=230, justify="left")
        self.db_status.pack(fill=tk.X, pady=(4, 6))
        ttk.Button(side, text="Quit", command=self.quit).pack(fill=tk.X)

        # right: statistics (top) and calendar (bottom)
        right = ttk.PanedWindow(paned, orient=tk.VERTICAL)
        stats = ttk.Frame(right, relief=tk.SUNKEN)
        ttk.Label(stats, text="Statistics", font=("TkDefaultFont", 11, "bold"),
                  anchor="w").pack(fill=tk.X, padx=10, pady=(10, 5))
        self.stats_body = ttk.Frame(stats)
        self.stats_body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        cal = ttk.Frame(right, relief=tk.SUNKEN)
        self.calendar = ConsistencyCalendar(cal, on_day_click=self.show_day)
        self.calendar.pack(fill=tk.BOTH, expand=True)

        right.add(stats, weight=3)
        right.add(cal, weight=2)
        paned.add(side, weight=1)
        paned.add(right, weight=4)

    # background calls ---------------------------------------------------
    def run_async(self, fn, done):
        def work():
            try:
                result = (fn(), None)
            except Exception as e:  # reported to done()
                result = (None, e)
            self._jobs.put((done, result))
        threading.Thread(target=work, daemon=True).start()

    def _poll_jobs(self):
        while True:
            try:
                done, (result, error) = self._jobs.get_nowait()
            except queue.Empty:
                break
            done(result, error)
        self.root.after(50, self._poll_jobs)

    # data ---------------------------------------------------------------
    def refresh(self):
        self.db_status.configure(text="Loading…", foreground="#57606a")
        self.run_async(lambda: backend_call(["INFO", "LIST"]), self._on_refreshed)

    def _on_refreshed(self, replies, error):
        if error:
            self.db_status.configure(text=f"Backend error: {error}", foreground="#cf222e")
            return
        rows, errors = [], []
        for tag, payload in replies:
            if tag == "INFO" and unescape(payload).startswith("test_dir="):
                self.test_dir = unescape(payload)[len("test_dir="):]
            elif tag == "ROW":
                rows.append(parse_row(payload))
            elif tag == "ERR":
                errors.append(unescape(payload))
        if errors:
            self.db_status.configure(text="Database error:\n" + errors[0],
                                     foreground="#cf222e")
            return
        self.problems = rows
        done = sum(is_true(p.get("is_completed")) for p in rows)
        self.db_status.configure(
            text=f"Database connected\n{len(rows)} problems, {done} completed",
            foreground="#1a7f37")
        self.calendar.set_problems(rows)
        self._fill_recent()
        render_statistics(self.stats_body, rows)
        if self.problems_window:
            self.problems_window.reload()

    def get_test_dir(self):
        if self.test_dir is None:
            try:
                for tag, payload in backend_call(["INFO"], timeout=10):
                    text = unescape(payload)
                    if tag == "INFO" and text.startswith("test_dir="):
                        self.test_dir = text[len("test_dir="):]
            except BackendError:
                pass
        return self.test_dir

    def _fill_recent(self):
        self.recent.delete(0, tk.END)
        self._recent_ids = []
        for p in self.problems[:30]:
            mark = "✓" if is_true(p.get("is_completed")) else "•"
            self.recent.insert(tk.END, f"{mark} {p.get('name')}   {p.get('date_of_doing')}")
            self._recent_ids.append(int(p["id"]))

    def _open_recent(self):
        sel = self.recent.curselection()
        if sel:
            self.open_problem(self._recent_ids[sel[0]])

    def update_fields(self, problem_id, fields, parent=None):
        if not fields:
            return
        lines = []
        for key, value in fields.items():
            lines += ["UPDATE", str(problem_id), f"{key}={escape(value)}"]

        def done(replies, error):
            errors = [unescape(p) for t, p in replies or [] if t == "ERR"]
            if error or errors:
                messagebox.showerror(APP_NAME, f"Update failed:\n{error or errors[0]}",
                                     parent=parent or self.root)
            self.refresh()
        self.run_async(lambda: backend_call(lines), done)

    def delete_problem(self, problem_id, parent=None):
        def done(replies, error):
            errors = [unescape(p) for t, p in replies or [] if t == "ERR"]
            if error or errors:
                messagebox.showerror(APP_NAME, f"Delete failed:\n{error or errors[0]}",
                                     parent=parent or self.root)
            for editor in self.editors:
                if editor.problem_id == problem_id:
                    editor.problem_id = None
                    editor.saved_state = None
                    editor.terminal.line("this problem was deleted from the database, "
                                         "Save stores it again as a new one", "warn")
            self.refresh()
        self.run_async(lambda: backend_call(["DELETE", str(problem_id)]), done)

    # windows ------------------------------------------------------------
    def new_problem(self):
        editor = ProblemEditor(self)
        self.editors.append(editor)

    def open_problem(self, problem_id):
        for editor in self.editors:
            if editor.problem_id == problem_id:
                editor.deiconify()
                editor.lift()
                editor.focus_force()
                return

        def done(replies, error):
            loaded = {}
            errors = []
            for tag, payload in replies or []:
                if tag == "ROW":
                    loaded["row"] = parse_row(payload)
                elif tag == "CODE":
                    loaded["code"] = unescape(payload)
                elif tag == "TESTCASES":
                    loaded["testcases"] = unescape(payload)
                elif tag == "ERR":
                    errors.append(unescape(payload))
                elif tag == "WARN":
                    errors.append(unescape(payload))
            if error or "row" not in loaded:
                messagebox.showerror(APP_NAME, f"Could not open problem {problem_id}:\n"
                                               f"{error or (errors[0] if errors else '?')}",
                                     parent=self.root)
                return
            if any(e.problem_id == problem_id for e in self.editors):
                return  # opened twice quickly
            editor = ProblemEditor(self, loaded)
            self.editors.append(editor)
            for msg in errors:
                editor.terminal.line(msg, "warn")
        self.run_async(lambda: backend_call(["LOAD", str(problem_id)]), done)

    def show_problems(self):
        if self.problems_window:
            self.problems_window.deiconify()
            self.problems_window.lift()
            return self.problems_window
        self.problems_window = ProblemsWindow(self)
        return self.problems_window

    def show_day(self, day):
        self.show_problems().set_date_filter(day)

    def open_folder(self):
        test_dir = self.get_test_dir()
        if test_dir and shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", test_dir], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        elif test_dir:
            messagebox.showinfo(APP_NAME, test_dir, parent=self.root)

    def quit(self):
        for editor in list(self.editors):
            if editor.dirty():
                editor.lift()
                answer = messagebox.askyesnocancel(
                    APP_NAME, f"'{editor.name_var.get() or 'Untitled'}' has unsaved changes."
                              "\n\nClose it without saving?\n(No: go back to it)",
                    parent=editor)
                if not answer:
                    return
            editor.close(force=True)
        self.root.destroy()


def main(argv):
    if any(a in ("-h", "--help") for a in argv[1:]):
        print(f"usage: {os.path.basename(argv[0])}\n\nOpens the {APP_NAME} window. "
              "The backend is taken from $PROBS_MANG_BIN, ../build/probs_mang or PATH.")
        return 0
    app = App()
    app.root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
