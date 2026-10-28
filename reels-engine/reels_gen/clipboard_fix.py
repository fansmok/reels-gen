"""
Копирование/вставка в CustomTkinter при русской раскладке.

Tk по умолчанию слушает только Control-c/v/x/a (латиница).
На RU-раскладке те же физические клавиши дают «с/м/ч/ф» — и буфер «молчит».
"""

from __future__ import annotations

import sys
import tkinter as tk


# Windows virtual-key codes (раскладка не влияет)
_VK = {
    65: "select_all",  # A
    67: "copy",        # C
    86: "paste",       # V
    88: "cut",         # X
}

# Keysym при русской раскладке (физические A/C/V/X)
_CYR = {
    "ф": "select_all",
    "с": "copy",
    "м": "paste",
    "ч": "cut",
    "cyrillic_ef": "select_all",
    "cyrillic_es": "copy",
    "cyrillic_em": "paste",
    "cyrillic_che": "cut",
}

_LATIN = {"a", "c", "v", "x"}


def _is_ctrl(event) -> bool:
    # Control = 0x4; на macOS Command = 0x8 / 0x10
    state = int(getattr(event, "state", 0) or 0)
    if sys.platform == "darwin":
        return bool(state & 0x8) or bool(state & 0x10) or bool(state & 0x4)
    return bool(state & 0x4)


def _action_from_event(event) -> str | None:
    if not _is_ctrl(event):
        return None

    keysym = (getattr(event, "keysym", "") or "").lower()
    # Латиница уже обрабатывается стандартными биндами Tk — не дублируем
    if keysym in _LATIN:
        return None

    keycode = int(getattr(event, "keycode", 0) or 0)
    if keycode in _VK:
        return _VK[keycode]

    if keysym in _CYR:
        return _CYR[keysym]

    char = (getattr(event, "char", "") or "").lower()
    if char in _CYR:
        return _CYR[char]

    return None


def _do_select_all(widget) -> str | None:
    try:
        # tk.Entry / CTkEntry._entry
        widget.select_range(0, "end")
        widget.icursor("end")
        return "break"
    except tk.TclError:
        pass
    try:
        # tk.Text / CTkTextbox._textbox
        widget.tag_add("sel", "1.0", "end-1c")
        widget.mark_set("insert", "1.0")
        widget.see("insert")
        return "break"
    except tk.TclError:
        pass
    try:
        widget.event_generate("<<SelectAll>>")
        return "break"
    except tk.TclError:
        return None


def _do_action(widget, action: str) -> str | None:
    if action == "select_all":
        return _do_select_all(widget)
    mapping = {
        "copy": "<<Copy>>",
        "paste": "<<Paste>>",
        "cut": "<<Cut>>",
    }
    virtual = mapping.get(action)
    if not virtual:
        return None
    try:
        widget.event_generate(virtual)
        return "break"
    except tk.TclError:
        return None


def _on_ctrl_key(event):
    action = _action_from_event(event)
    if not action:
        return None
    return _do_action(event.widget, action)


def _show_context_menu(event):
    widget = event.widget
    menu = tk.Menu(widget, tearoff=0)
    menu.add_command(label="Вырезать", command=lambda: _do_action(widget, "cut"))
    menu.add_command(label="Копировать", command=lambda: _do_action(widget, "copy"))
    menu.add_command(label="Вставить", command=lambda: _do_action(widget, "paste"))
    menu.add_separator()
    menu.add_command(label="Выделить всё", command=lambda: _do_action(widget, "select_all"))
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()
    return "break"


def _inner_tk(widget):
    """Возвращает реальный tk Entry/Text внутри CustomTkinter."""
    if hasattr(widget, "_entry"):
        return widget._entry
    if hasattr(widget, "_textbox"):
        return widget._textbox
    return widget


def enable_clipboard(root) -> None:
    """Глобальные бинды Ctrl+C/V/X/A для русской раскладки."""
    root.bind_all("<KeyPress>", _on_ctrl_key, add="+")
    # На всякий случай — явные бинды кириллических keysym
    for seq, action in (
        ("<Control-KeyPress-с>", "copy"),
        ("<Control-KeyPress-С>", "copy"),
        ("<Control-KeyPress-м>", "paste"),
        ("<Control-KeyPress-М>", "paste"),
        ("<Control-KeyPress-ч>", "cut"),
        ("<Control-KeyPress-Ч>", "cut"),
        ("<Control-KeyPress-ф>", "select_all"),
        ("<Control-KeyPress-Ф>", "select_all"),
        ("<Control-Cyrillic_es>", "copy"),
        ("<Control-Cyrillic_ES>", "copy"),
        ("<Control-Cyrillic_em>", "paste"),
        ("<Control-Cyrillic_EM>", "paste"),
        ("<Control-Cyrillic_che>", "cut"),
        ("<Control-Cyrillic_CHE>", "cut"),
        ("<Control-Cyrillic_ef>", "select_all"),
        ("<Control-Cyrillic_EF>", "select_all"),
    ):
        def _make(a=action):
            return lambda e: _do_action(e.widget, a)

        try:
            root.bind_all(seq, _make(), add="+")
        except tk.TclError:
            pass


def attach_context_menu(*widgets) -> None:
    """ПКМ: Вырезать / Копировать / Вставить / Выделить всё."""
    for w in widgets:
        inner = _inner_tk(w)
        if sys.platform == "darwin":
            inner.bind("<Button-2>", _show_context_menu, add="+")
            inner.bind("<Control-Button-1>", _show_context_menu, add="+")
        else:
            inner.bind("<Button-3>", _show_context_menu, add="+")
