"""Persisted, editable keyboard and canvas controls."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from ui import help_label, scroll_form, entry_undo

KEYS = {
    'save': ('Save current tab', 'Ctrl+S'), 'export': ('Export all changes', 'Ctrl+E'),
    'edit': ('New item/edit recipe', 'Ctrl+T'), 'item': ('New flowchart (alternate)', 'Ctrl+N'),
    'tech': ('Edit technology tree', 'Ctrl+G'), 'close': ('Close current tab', 'Ctrl+W'),
    'settings': ('Open settings', 'Ctrl+comma'), 'find': ('Focus search', 'Ctrl+F'),
    'machine': ('Create machine', 'Ctrl+M'),
    'undo': ('Undo last change', 'Ctrl+Z'),
}
DEFAULTS = {'keys': {k: v[1] for k, v in KEYS.items()}, 'zoom_modifier': 'Ctrl', 'multi_select_modifier': 'Ctrl',
            'pan_button': 'Left', 'alternate_pan': 'Middle', 'select_button': 'Left', 'context_button': 'Right',
            'picker_button': 'Left', 'picker_accept': 'Return', 'dialog_dismiss': 'Escape'}
BUTTONS = {'Left': 1, 'Middle': 2, 'Right': 3}
MODIFIERS = {'Ctrl': 4, 'Shift': 1, 'Alt': 8 | 0x20000}


def sequence(value):
    parts = value.strip().split('+')
    modifiers = {'ctrl': 'Control', 'control': 'Control', 'shift': 'Shift', 'alt': 'Alt'}
    if not parts[-1] or any(p.lower() not in modifiers for p in parts[:-1]):
        raise ValueError('Use a key such as Ctrl+S, Alt+E, F2, Return or Escape.')
    key = parts[-1]
    key = key.lower() if len(key) == 1 else key
    return '<' + '-'.join([modifiers[p.lower()] for p in parts[:-1]] + [key]) + '>'


def load_controls(path):
    data = json.loads(json.dumps(DEFAULTS))
    if Path(path).exists():
        try:
            saved = json.loads(Path(path).read_text())
            data.update({k: v for k, v in saved.items() if k in data and k != 'keys'})
            data['keys'].update({k: v for k, v in saved.get('keys', {}).items() if k in KEYS})
        except (OSError, ValueError, TypeError):
            pass
    return data


def settings_dialog(app):
    dialog = tk.Toplevel(app)
    dialog.title('Settings')
    dialog.geometry('650x730')
    ttk.Label(dialog, text='Settings', font=('Segoe UI', 18, 'bold'), padding=16).pack(anchor='w')
    keyboard = ttk.Frame(dialog)
    def show_keyboard():
        keyboard.pack(fill='both', expand=True)
        button.pack_forget()
    button = ttk.Button(dialog, text='Keyboard', command=show_keyboard)
    button.pack(anchor='w', padx=16)
    footer = ttk.Frame(keyboard, padding=12)
    footer.pack(side='bottom', fill='x')
    body = scroll_form(keyboard)
    variables = {}
    ttk.Label(body, text='Keyboard shortcuts', font=('Segoe UI', 13, 'bold'), padding=12).pack(anchor='w')
    for action, (title, _) in KEYS.items():
        row = ttk.Frame(body)
        row.pack(fill='x', padx=16, pady=3)
        ttk.Label(row, text=title, width=26).pack(side='left')
        var = tk.StringVar(value=app.controls['keys'][action])
        variables[action] = var
        entry = ttk.Entry(row, textvariable=var, width=20)
        entry.pack(side='left', fill='x', expand=True)
        entry_undo(entry, var)
        help_label(body, 'Shortcut for ' + title.lower() + '. Example: Ctrl+S or F2.', wraplength=540)
    mouse_vars = {}
    options = {'zoom_modifier': ('Zoom with wheel while holding', list(MODIFIERS)),
               'multi_select_modifier': ('Select multiple technologies', list(MODIFIERS)),
               'pan_button': ('Drag empty space to pan', list(BUTTONS)),
               'alternate_pan': ('Additional pan button', list(BUTTONS)),
               'select_button': ('Select / edit a chart node', list(BUTTONS)),
               'context_button': ('Open chart context menu', list(BUTTONS)),
               'picker_button': ('Confirm list item by double-click', list(BUTTONS))}
    for key, (label, values) in options.items():
        row = ttk.Frame(body)
        row.pack(fill='x', padx=16, pady=3)
        ttk.Label(row, text=label, width=30).pack(side='left')
        mouse_vars[key] = tk.StringVar(value=app.controls[key])
        ttk.Combobox(row, textvariable=mouse_vars[key], values=values, state='readonly').pack(side='left', fill='x', expand=True)
        help_label(body, 'Used on recipe and technology flowcharts. Panning starts only on empty space; node clicks keep their edit action.', wraplength=540)
    for key, title in [('picker_accept', 'Accept a picker selection'), ('dialog_dismiss', 'Dismiss a dialog')]:
        row = ttk.Frame(body)
        row.pack(fill='x', padx=16, pady=3)
        ttk.Label(row, text=title, width=30).pack(side='left')
        mouse_vars[key] = tk.StringVar(value=app.controls[key])
        entry = ttk.Entry(row, textvariable=mouse_vars[key])
        entry.pack(side='left', fill='x', expand=True)
        entry_undo(entry, mouse_vars[key])
        help_label(body, 'Key used in item and name-selection dialogs. For example: Return or Escape.', wraplength=540)
    help_label(body, 'Wheel alone scrolls. Left-click buttons and tabs; the tab’s × closes it. In text fields, standard copy, cut, paste and selection controls follow Windows. Use the search/chooser buttons to filter and select entries.', wraplength=540)
    def save():
        try:
            result = {'keys': {k: v.get().strip() for k, v in variables.items()}, **{k: v.get() for k, v in mouse_vars.items()}}
            sequences = [sequence(v) for v in result['keys'].values()]
            if len(sequences) != len(set(sequences)):
                raise ValueError('Each application shortcut must be unique.')
            if result['context_button'] == result['select_button']:
                raise ValueError('Select/edit and context menu must use different buttons.')
            if result['context_button'] in (result['pan_button'], result['alternate_pan']):
                raise ValueError('The context menu must use a different button from panning.')
            for seq in sequences + [sequence(result['picker_accept']), sequence(result['dialog_dismiss'])]:
                app.bind_class('ShortcutValidation', seq, '')
            app.controls_path.parent.mkdir(exist_ok=True, parents=True)
            app.controls_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
            app.controls = result
            app.apply_controls()
            dialog.destroy()
        except (ValueError, OSError, tk.TclError) as exc:
            messagebox.showerror('Cannot save controls', str(exc), parent=dialog)
    def defaults():
        for key, var in variables.items():
            var.set(DEFAULTS['keys'][key])
        for key, var in mouse_vars.items():
            var.set(DEFAULTS[key])
    ttk.Button(footer, text='Restore defaults', command=defaults).pack(side='left')
    ttk.Button(footer, text='Save controls', command=save).pack(side='right')
