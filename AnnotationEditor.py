import os
import sys
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk

try:
    import yaml
except ImportError:
    yaml = None

# --- CONFIGURATION & CONSTANTS ---
CONFIG_FILENAME = "config.yaml"
LEGACY_CONFIG_FILENAME = "config.json"  # fallback
DEFAULT_WINDOW_SIZE = "1280x820"

LABELS_DIR_NAME = "labels"
LABELS_PID_DIR_NAME = "labels_with_person_id"
DATASET_YAML_NAME = "labels_with_person_id.yaml"

RESERVED_KEYS = {"Tab", "Left", "Right", "F1", "Return", "Escape",
                 "Control_L", "Control_R", "Delete", "BackSpace"}

# Default keyboard keys when auto-mapping a flat {id: name} yaml.
_DEFAULT_CLASS_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]
_DEFAULT_PERSON_KEYS = ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p",
                       "a", "s", "d", "f", "g", "h", "j", "k", "l",
                       "z", "x", "c", "v", "b", "n", "m"]

NAV_REPEAT_INITIAL_DELAY_MS = 120
NAV_REPEAT_INTERVAL_MS = 75
UNPICKED_BOX_VISIBILITY_DEFAULT = 78
UNPICKED_BOX_VISIBILITY_MIN = 40
UNPICKED_BOX_COLOR_DEFAULT = "Auto"
UNPICKED_BOX_COLOR_PRESETS = {
    "Auto": None,
    "White": "#f8fafc",
    "Cyan": "#38bdf8",
    "Yellow": "#facc15",
    "Orange": "#fb923c",
    "Magenta": "#e879f9",
    "Red": "#f87171",
    "Green": "#86efac",
}


def _strip_yaml_comment(line):
    in_quote = None
    escaped = False
    out = []
    for ch in line:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\" and in_quote:
            out.append(ch)
            escaped = True
            continue
        if ch in ("'", '"'):
            if in_quote == ch:
                in_quote = None
            elif in_quote is None:
                in_quote = ch
            out.append(ch)
            continue
        if ch == "#" and in_quote is None:
            break
        out.append(ch)
    return "".join(out).rstrip()


def _unquote_yaml_scalar(value):
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value[1:-1]
        return value[1:-1].replace("''", "'")
    return value


def _parse_yaml_scalar(value):
    value = _unquote_yaml_scalar(value)
    lowered = value.lower()
    if lowered in ("null", "~"):
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        if value and all(ch not in value for ch in ".eE"):
            return int(value)
        return float(value)
    except (TypeError, ValueError):
        return value


def _split_inline_yaml_items(value):
    items = []
    current = []
    in_quote = None
    escaped = False
    for ch in value:
        if escaped:
            current.append(ch)
            escaped = False
            continue
        if ch == "\\" and in_quote:
            current.append(ch)
            escaped = True
            continue
        if ch in ("'", '"'):
            if in_quote == ch:
                in_quote = None
            elif in_quote is None:
                in_quote = ch
            current.append(ch)
            continue
        if ch == "," and in_quote is None:
            items.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    tail = "".join(current).strip()
    if tail:
        items.append(tail)
    return items


def _parse_inline_yaml_dict(value):
    value = value.strip()
    if not (value.startswith("{") and value.endswith("}")):
        return _parse_yaml_scalar(value)
    value = value[1:-1].strip()
    parsed = {}
    if not value:
        return parsed
    for item in _split_inline_yaml_items(value):
        if ":" not in item:
            continue
        key, raw = item.split(":", 1)
        parsed[_unquote_yaml_scalar(key)] = _parse_yaml_scalar(raw)
    return parsed


def _fallback_yaml_load(text):
    """Small YAML reader for this app's config/mapping files.

    This intentionally supports only the mapping shapes the editor uses:
    top-level keys with one nested mapping level, plus inline dictionaries such
    as { id: 0, name: "Person 1" }. PyYAML is still used when installed.
    """
    data = {}
    current_key = None
    for raw_line in text.splitlines():
        line = _strip_yaml_comment(raw_line)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if ":" not in stripped:
            continue

        key, raw_value = stripped.split(":", 1)
        key = _unquote_yaml_scalar(key)
        raw_value = raw_value.strip()

        if indent == 0:
            if raw_value:
                data[key] = _parse_inline_yaml_dict(raw_value)
                current_key = None
            else:
                data[key] = {}
                current_key = key
            continue

        if current_key is None:
            continue
        if not isinstance(data.get(current_key), dict):
            data[current_key] = {}
        data[current_key][key] = (
            _parse_inline_yaml_dict(raw_value) if raw_value else {}
        )
    return data


def _format_yaml_scalar(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _format_yaml_key(value):
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if text.replace("_", "").replace("-", "").isalnum():
        return text
    return json.dumps(text, ensure_ascii=False)


def _fallback_yaml_dump(data):
    lines = []
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{_format_yaml_key(key)}:")
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, dict):
                    inline = ", ".join(
                        f"{_format_yaml_key(k)}: {_format_yaml_scalar(v)}"
                        for k, v in sub_value.items()
                    )
                    lines.append(f"  {_format_yaml_key(sub_key)}: {{ {inline} }}")
                else:
                    lines.append(
                        f"  {_format_yaml_key(sub_key)}: {_format_yaml_scalar(sub_value)}"
                    )
        else:
            lines.append(f"{_format_yaml_key(key)}: {_format_yaml_scalar(value)}")
    return "\n".join(lines) + "\n"


def _hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(
        *(max(0, min(255, int(round(channel)))) for channel in rgb)
    )


def _mix_hex_color(start, end, amount):
    amount = max(0.0, min(1.0, float(amount)))
    sr, sg, sb = _hex_to_rgb(start)
    er, eg, eb = _hex_to_rgb(end)
    return _rgb_to_hex((
        sr + (er - sr) * amount,
        sg + (eg - sg) * amount,
        sb + (eb - sb) * amount,
    ))


def _safe_yaml_load(stream):
    if yaml is not None:
        return yaml.safe_load(stream) or {}
    return _fallback_yaml_load(stream.read())


def _safe_yaml_dump(data, stream):
    if yaml is not None:
        yaml.safe_dump(data, stream, sort_keys=False, allow_unicode=True)
    else:
        stream.write(_fallback_yaml_dump(data))


def _flat_to_keyboard_mapping(flat, default_keys):
    """Convert {id: name} (or {id_str: name}) into {key: {id, name}}.

    Keys are taken from ``default_keys`` in order. If the source dict has more
    entries than available default keys, the remaining items are dropped (with
    a printed warning) — the user can extend the mapping by editing
    ``config.yaml`` manually.
    """
    if not isinstance(flat, dict):
        return {}
    # Sort by numeric id (stringified ids tolerated)
    def _key(item):
        try:
            return int(item[0])
        except (TypeError, ValueError):
            return 10 ** 9
    items = sorted(flat.items(), key=_key)

    out = {}
    for i, (raw_id, name) in enumerate(items):
        if i >= len(default_keys):
            print(f"[config] dropping extra entry id={raw_id!r} name={name!r} "
                  f"(out of default keyboard keys)")
            break
        try:
            iid = int(raw_id)
        except (TypeError, ValueError):
            iid = i
        out[default_keys[i]] = {"id": iid, "name": str(name)}
    return out


def resource_path(relative):
    """Resolve a path that works for both source and PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def find_config_path():
    """Locate config.yaml beside the script/exe, with fallback to bundle."""
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    for name in (CONFIG_FILENAME, LEGACY_CONFIG_FILENAME):
        local = os.path.join(here, name)
        if os.path.exists(local):
            return local
    # bundle fallback
    bundled = resource_path(CONFIG_FILENAME)
    if os.path.exists(bundled):
        return bundled
    bundled_legacy = resource_path(LEGACY_CONFIG_FILENAME)
    if os.path.exists(bundled_legacy):
        return bundled_legacy
    return os.path.join(here, CONFIG_FILENAME)


# Color palette for class / person legend
CLASS_PALETTE = [
    '#64748b', '#2563eb', '#16a34a', '#ca8a04',
    '#ea580c', '#dc2626', '#7c3aed', '#0891b2',
    '#0f766e', '#4f46e5'
]
PERSON_PALETTE = [
    '#d97706', '#059669', '#0284c7', '#7c3aed',
    '#4338ca', '#c2410c', '#0e7490', '#a16207',
    '#15803d', '#b91c1c'
]

DEFAULT_THEME = "dark"
THEME_COLORS = {
    "dark": {
        "bg": "#0f172a",
        "panel": "#111827",
        "panel_alt": "#1f2937",
        "control": "#243447",
        "control_hover": "#334155",
        "neutral": "#475569",
        "neutral_hover": "#64748b",
        "accent": "#2563eb",
        "accent_hover": "#1d4ed8",
        "success": "#16a34a",
        "success_hover": "#15803d",
        "danger": "#dc2626",
        "danger_hover": "#b91c1c",
        "warning": "#f59e0b",
        "border": "#334155",
        "text": "#f8fafc",
        "text_dim": "#94a3b8",
        "canvas_bg": "#020617",
        "input_bg": "#0f172a",
        "autosave_bg": "#14532d",
        "autosave_fg": "#bbf7d0",
        "progress": "#86efac",
        "status_success": "#4ade80",
        "status_warning": "#fbbf24",
        "status_error": "#fca5a5",
        "draw_preview": "#22d3ee",
    },
    "light": {
        "bg": "#e5e7eb",
        "panel": "#ffffff",
        "panel_alt": "#f1f5f9",
        "control": "#e2e8f0",
        "control_hover": "#cbd5e1",
        "neutral": "#64748b",
        "neutral_hover": "#475569",
        "accent": "#2563eb",
        "accent_hover": "#1d4ed8",
        "success": "#16a34a",
        "success_hover": "#15803d",
        "danger": "#dc2626",
        "danger_hover": "#b91c1c",
        "warning": "#d97706",
        "border": "#cbd5e1",
        "text": "#0f172a",
        "text_dim": "#475569",
        "canvas_bg": "#f8fafc",
        "input_bg": "#ffffff",
        "autosave_bg": "#dcfce7",
        "autosave_fg": "#166534",
        "progress": "#15803d",
        "status_success": "#16a34a",
        "status_warning": "#d97706",
        "status_error": "#dc2626",
        "draw_preview": "#0891b2",
    },
}


class AnnotationEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("YOLO Annotation Editor - Dataset Labeling")
        self.root.geometry(DEFAULT_WINDOW_SIZE)

        # --- Config ---
        self.config_path = find_config_path()
        self.config = self.load_config()
        self.class_key_map, self.classes = self._parse_mapping(self.config.get("classes", {}))
        self.person_key_map, self.persons = self._parse_mapping(self.config.get("persons", {}))

        # State
        self.image_dir = ""
        self.label_dir = ""               # 5-col labels
        self.label_pid_dir = ""           # 6-col labels (with person_id)
        self.dataset_root = ""
        self.image_files = []
        self.filtered_image_indices = []
        self.file_filter_text = ""
        self._updating_file_list = False
        self.current_index = 0
        self.current_image = None
        self.tk_image = None
        # Each box: [person_id, class_id, cx, cy, w, h]
        self.boxes = []
        self.prev_boxes = []
        self.prev_selected_box_index = -1
        self.prev_class_checkpoint_index = -1
        self.prev_person_checkpoint_index = -1
        self.prev_class_checkpoint_manual = False
        self.prev_person_checkpoint_manual = False
        self.selected_box_index = -1
        self.class_checkpoint_index = -1
        self.person_checkpoint_index = -1
        self.class_checkpoint_manual = False
        self.person_checkpoint_manual = False
        self.scale_factor = 1.0
        self.img_offset = (0, 0, 0, 0)
        self.visited_images = set()
        self.unpicked_box_visibility = UNPICKED_BOX_VISIBILITY_DEFAULT
        self.unpicked_box_color_name = UNPICKED_BOX_COLOR_DEFAULT

        # Edit cache: {filename: [[person_id, class_id], ...]}
        self.edit_cache = {}
        self.cache_file_path = ""

        # Undo stack: list of (filename, boxes_snapshot, selected_index_snapshot)
        # Setiap entry adalah state SEBELUM aksi destruktif (delete / set_class /
        # set_person / draw new box). Dibatasi MAX_UNDO untuk hemat memori.
        self.undo_stack = []
        self.MAX_UNDO = 50

        # Manual draw-box state
        self.draw_mode = False          # True saat user sedang dalam mode menggambar
        self.draw_start = None          # (canvas_x, canvas_y) titik awal drag
        self.draw_preview_id = None     # canvas item id untuk preview rectangle
        self._nav_repeat_after_id = None
        self._nav_repeat_direction = 0

        # GUI Setup
        self.theme_name = DEFAULT_THEME
        self._setup_ui()

        # Static bindings
        self.root.bind("<KeyPress-Left>", lambda e: self._start_nav_repeat(-1))
        self.root.bind("<KeyRelease-Left>", lambda e: self._stop_nav_repeat(-1))
        self.root.bind("<KeyPress-Right>", lambda e: self._start_nav_repeat(1))
        self.root.bind("<KeyRelease-Right>", lambda e: self._stop_nav_repeat(1))
        self.root.bind("<Control-s>", lambda e: self.save_current())
        self.root.bind("<Tab>", self.cycle_box)
        self.root.bind("<F1>", lambda e: self.show_help())
        self.root.bind("<Delete>", lambda e: self.delete_selected_box())
        self.root.bind("<BackSpace>", lambda e: self.delete_selected_box())
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("<Control-Z>", lambda e: self.undo())
        self.root.bind("<Control-b>", lambda e: self.toggle_draw_mode())
        self.root.bind("<Control-B>", lambda e: self.toggle_draw_mode())
        self.root.bind("<Escape>", lambda e: self._on_escape())
        # Dynamic hotkeys from config
        self._bind_hotkeys()

    # ---------------------------------------------------------------- config
    def load_config(self):
        if not os.path.exists(self.config_path):
            messagebox.showerror(
                "Error",
                f"Config file not found: {self.config_path}\n\n"
                f"Buat file '{CONFIG_FILENAME}' berisi mapping classes dan persons."
            )
            return {"classes": {}, "persons": {}}

        ext = os.path.splitext(self.config_path)[1].lower()
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                if ext in (".yaml", ".yml"):
                    return _safe_yaml_load(f)
                else:
                    data = json.load(f)
                    # Convert legacy JSON (list of class names) to new shape
                    if isinstance(data.get("classes"), list):
                        converted = {}
                        for i, name in enumerate(data["classes"]):
                            converted[str(i + 1)] = {"id": i, "name": name}
                        data["classes"] = converted
                    if "persons" not in data:
                        data["persons"] = {}
                    return data
        except Exception as e:
            messagebox.showerror("Error", f"Gagal load config:\n{e}")
            return {"classes": {}, "persons": {}}

    def _parse_mapping(self, raw):
        """Parse {key: {id, name}} mapping into (key_map, list_sorted_by_id).

        Returns:
            key_map: {keyboard_key: {"id": int, "name": str, "key": str}}
            items:   [(id, name, key), ...] sorted by id
        """
        key_map = {}
        items = []
        if not isinstance(raw, dict):
            return key_map, items

        for key, val in raw.items():
            key_str = str(key)
            if isinstance(val, dict):
                try:
                    item_id = int(val.get("id", len(items)))
                except (TypeError, ValueError):
                    item_id = len(items)
                name = str(val.get("name", f"Item {item_id}"))
            else:
                # plain "key: name" form
                item_id = len(items)
                name = str(val)
            key_map[key_str] = {"id": item_id, "name": name, "key": key_str}
            items.append((item_id, name, key_str))

        items.sort(key=lambda x: x[0])
        return key_map, items

    def _bind_hotkeys(self):
        for key in list(self.class_key_map.keys()):
            self.root.bind(key, self._make_class_handler(self.class_key_map[key]["id"]))
        for key in list(self.person_key_map.keys()):
            if key in RESERVED_KEYS:
                continue
            self.root.bind(key, self._make_person_handler(self.person_key_map[key]["id"]))
        # Track keys we've bound so we can unbind them on config reload
        self._bound_hotkeys = set(self.class_key_map.keys()) | (
            set(self.person_key_map.keys()) - RESERVED_KEYS
        )

    def _unbind_hotkeys(self):
        """Remove previously bound class/person hotkeys (used before reloading config)."""
        for key in getattr(self, "_bound_hotkeys", set()):
            try:
                self.root.unbind(key)
            except tk.TclError:
                pass
        self._bound_hotkeys = set()

    def _make_class_handler(self, class_id):
        def handler(event=None):
            self.set_class(class_id)
        return handler

    def _make_person_handler(self, person_id):
        def handler(event=None):
            self.set_person(person_id)
        return handler

    def _maybe_load_dataset_config(self, folder):
        """If a config file exists inside the dataset folder, load it.

        Search order (first hit wins):
            1. <folder>/config.yaml
            2. <folder>/config.yml
            3. <folder>/classes_and_persons.yaml
            4. <folder>/labels_with_person_id.yaml

        For files (3) and (4) which use a flat {id: name} style, this method
        auto-converts them into the keyboard-mapping shape expected by the
        editor by assigning '1','2','3'... to classes and 'q','w','e'... to
        persons. If the user wants different keys, they should drop a
        proper 'config.yaml' into the folder.
        """
        candidates = [
            ("config.yaml", "explicit"),
            ("config.yml", "explicit"),
            ("classes_and_persons.yaml", "flat"),
            ("labels_with_person_id.yaml", "flat"),
        ]
        chosen_path = None
        chosen_kind = None
        for fname, kind in candidates:
            p = os.path.join(folder, fname)
            if os.path.exists(p):
                chosen_path = p
                chosen_kind = kind
                break

        if not chosen_path:
            self.lbl_config_src.config(
                text=f"config: (default — {os.path.basename(self.config_path)})"
            )
            return

        try:
            with open(chosen_path, "r", encoding="utf-8") as f:
                raw = _safe_yaml_load(f)
        except Exception as e:
            messagebox.showwarning("Config", f"Gagal baca config dataset:\n{chosen_path}\n{e}")
            return

        # Decide whether the file uses keyboard mapping ("explicit") or flat
        # {id: name} ("flat"). Detect by inspecting one entry.
        def is_keyboard_shaped(d):
            if not isinstance(d, dict) or not d:
                return False
            sample = next(iter(d.values()))
            return isinstance(sample, dict) and ("id" in sample or "name" in sample)

        classes_raw = raw.get("classes", {}) or {}
        persons_raw = raw.get("persons", {}) or {}

        if chosen_kind == "explicit" and (
            is_keyboard_shaped(classes_raw) or is_keyboard_shaped(persons_raw)
        ):
            # Use as-is; merge missing side from globals if absent.
            new_cfg = {
                "classes": classes_raw if classes_raw else self.config.get("classes", {}),
                "persons": persons_raw if persons_raw else self.config.get("persons", {}),
            }
        else:
            # Flat shape -> auto-assign keyboard keys.
            new_cfg = {
                "classes": _flat_to_keyboard_mapping(classes_raw, _DEFAULT_CLASS_KEYS),
                "persons": _flat_to_keyboard_mapping(persons_raw, _DEFAULT_PERSON_KEYS),
            }

        # Apply
        self.config = new_cfg
        self.class_key_map, self.classes = self._parse_mapping(new_cfg["classes"])
        self.person_key_map, self.persons = self._parse_mapping(new_cfg["persons"])

        self._unbind_hotkeys()
        self._bind_hotkeys()
        self._render_legends()
        try:
            rel = os.path.relpath(chosen_path, folder)
        except ValueError:
            rel = chosen_path
        self.lbl_config_src.config(text=f"config: {rel}")
        print(f"[config] using dataset config: {chosen_path}")

    def _render_legends(self):
        """(Re)render the class & person legend panels from current state."""
        # Clear existing children
        for w in self.class_legend_frame.winfo_children():
            w.destroy()
        for w in self.person_legend_frame.winfo_children():
            w.destroy()

        if not self.classes:
            self._muted_label(self.class_legend_frame, "(belum ada class di config)")
        for idx, (cid, name, key) in enumerate(self.classes):
            color = CLASS_PALETTE[idx % len(CLASS_PALETTE)]
            self._legend_row(self.class_legend_frame, color, key, cid, name)

        if not self.persons:
            self._muted_label(self.person_legend_frame, "(belum ada person di config)")
        for idx, (pid, name, key) in enumerate(self.persons):
            color = PERSON_PALETTE[idx % len(PERSON_PALETTE)]
            self._legend_row(self.person_legend_frame, color, key, pid, name)

    def _button_colors(self, variant):
        palettes = {
            "primary": ("accent", "accent_hover"),
            "secondary": ("control", "control_hover"),
            "success": ("success", "success_hover"),
            "danger": ("danger", "danger_hover"),
            "neutral": ("neutral", "neutral_hover"),
        }
        base_key, hover_key = palettes.get(variant, palettes["secondary"])
        return self.colors[base_key], self.colors[hover_key]

    def _button_text_color(self, variant):
        if self.theme_name == "light" and variant == "secondary":
            return self.colors["text"]
        return "white"

    def _set_button_variant(self, button, variant):
        base, hover = self._button_colors(variant)
        fg = self._button_text_color(variant)
        button._base_bg = base
        button._hover_bg = hover
        button.configure(bg=base, fg=fg, activebackground=hover, activeforeground=fg)

    def _make_button(self, parent, text, command, variant="secondary", font=None,
                     padx=12, pady=6, repeatdelay=None, repeatinterval=None):
        base, hover = self._button_colors(variant)
        fg = self._button_text_color(variant)
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=base,
            fg=fg,
            activebackground=hover,
            activeforeground=fg,
            disabledforeground=self.colors["text_dim"],
            font=font or ("Segoe UI", 10, "bold"),
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            padx=padx,
            pady=pady,
            cursor="hand2",
        )
        if repeatdelay is not None:
            button.configure(repeatdelay=repeatdelay)
        if repeatinterval is not None:
            button.configure(repeatinterval=repeatinterval)
        button._base_bg = base
        button._hover_bg = hover
        button.bind("<Enter>", lambda _e, b=button: b.configure(bg=b._hover_bg))
        button.bind("<Leave>", lambda _e, b=button: b.configure(bg=b._base_bg))
        return button

    def _theme_button_text(self):
        return "Light Mode" if self.theme_name == "dark" else "Dark Mode"

    def toggle_theme(self):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self._rebuild_ui()

    def _bind_canvas_events(self):
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)

    def _rebuild_ui(self):
        status_text = getattr(self, "lbl_status", None).cget("text") if hasattr(self, "lbl_status") else "No folder loaded"
        config_text = getattr(self, "lbl_config_src", None).cget("text") if hasattr(self, "lbl_config_src") else "config: (default)"
        jump_text = getattr(self, "entry_jump", None).get() if hasattr(self, "entry_jump") else ""
        file_filter_text = (
            getattr(self, "file_filter_var", None).get()
            if hasattr(self, "file_filter_var") else self.file_filter_text
        )

        self._cancel_draw_preview()
        for child in self.root.winfo_children():
            child.destroy()

        self.file_filter_text = file_filter_text
        self._setup_ui()
        self.lbl_status.config(text=status_text, fg=self.colors["text_dim"])
        self.lbl_config_src.config(text=config_text)
        if jump_text:
            self.entry_jump.insert(0, jump_text)

        self._refresh_file_list()

        self.update_selected_box_label()
        self.update_progress()
        self._sync_draw_button()
        self.root.after_idle(self._refresh_canvas_after_theme_change)

    def _sync_draw_button(self):
        if self.draw_mode:
            self.canvas.config(cursor="crosshair")
            self.btn_draw.config(text="Draw Box: ON")
            self._set_button_variant(self.btn_draw, "success")
        else:
            self.canvas.config(cursor="")
            self.btn_draw.config(text="Draw Box (Ctrl+B)")
            self._set_button_variant(self.btn_draw, "primary")

    def _refresh_canvas_after_theme_change(self):
        if self.current_image is None:
            self._draw_empty_state()
        else:
            self.draw_canvas()

    def _on_unpicked_visibility_changed(self, value):
        try:
            self.unpicked_box_visibility = int(float(value))
        except (TypeError, ValueError):
            self.unpicked_box_visibility = UNPICKED_BOX_VISIBILITY_DEFAULT
        if hasattr(self, "lbl_unpicked_visibility"):
            self.lbl_unpicked_visibility.config(text=f"{self.unpicked_box_visibility}%")
        self._update_unpicked_color_swatch()
        if self.current_image is not None:
            self.draw_canvas()

    def _on_unpicked_color_changed(self, value=None):
        self.unpicked_box_color_name = value or self.unpicked_color_var.get()
        self._update_unpicked_color_swatch()
        if self.current_image is not None:
            self.draw_canvas()

    def _update_unpicked_color_swatch(self):
        if hasattr(self, "lbl_unpicked_color_swatch"):
            self.lbl_unpicked_color_swatch.config(bg=self._unpicked_box_color())

    def _on_control_panel_configure(self, _event=None):
        if hasattr(self, "control_canvas"):
            self.control_canvas.configure(scrollregion=self.control_canvas.bbox("all"))

    def _on_control_canvas_configure(self, event):
        if hasattr(self, "control_window_id"):
            self.control_canvas.itemconfigure(self.control_window_id, width=event.width)

    def _widget_inside(self, widget, parent):
        while widget is not None:
            if widget == parent:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _on_sidebar_mousewheel(self, event):
        if not hasattr(self, "right_panel") or not self._widget_inside(event.widget, self.right_panel):
            return None
        if hasattr(self, "listbox") and event.widget == self.listbox:
            return None
        if getattr(event, "num", None) == 4:
            direction = -1
        elif getattr(event, "num", None) == 5:
            direction = 1
        else:
            direction = -1 if event.delta > 0 else 1
        self.control_canvas.yview_scroll(direction, "units")
        return "break"

    def _make_section(self, title, subtitle=None):
        section = tk.Frame(
            self.control_panel,
            bg=self.colors["panel"],
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["border"],
            highlightthickness=1,
            bd=0,
        )
        section.pack(fill=tk.X, padx=10, pady=(0, 6))

        header = tk.Frame(section, bg=self.colors["panel"])
        header.pack(fill=tk.X, padx=10, pady=(6, 2))
        tk.Label(
            header,
            text=title,
            bg=self.colors["panel"],
            fg=self.colors["text"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(fill=tk.X)
        if subtitle:
            tk.Label(
                header,
                text=subtitle,
                bg=self.colors["panel"],
                fg=self.colors["text_dim"],
                font=("Segoe UI", 8),
                anchor="w",
            ).pack(fill=tk.X, pady=(1, 0))

        body = tk.Frame(section, bg=self.colors["panel"])
        body.pack(fill=tk.X, padx=10, pady=(0, 6))
        return body

    def _subheading(self, parent, text):
        tk.Label(
            parent,
            text=text,
            bg=self.colors["panel"],
            fg=self.colors["text_dim"],
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).pack(fill=tk.X, pady=(4, 2))

    def _muted_label(self, parent, text):
        tk.Label(
            parent,
            text=text,
            bg=self.colors["panel"],
            fg=self.colors["text_dim"],
            font=("Segoe UI", 9, "italic"),
            anchor="w",
        ).pack(fill=tk.X)

    def _legend_row(self, parent, color, key, item_id, name):
        row = tk.Frame(parent, bg=self.colors["panel"])
        row.pack(fill=tk.X, pady=1)
        row.columnconfigure(2, weight=1)
        tk.Label(row, text="", bg=color, width=2).grid(row=0, column=0, sticky="nsw")
        tk.Label(
            row,
            text=str(key).upper(),
            bg=self.colors["control"],
            fg=self.colors["text"],
            font=("Consolas", 8, "bold"),
            width=3,
        ).grid(row=0, column=1, padx=(5, 6), sticky="w")
        tk.Label(
            row,
            text=f"id={item_id}  {name}",
            bg=self.colors["panel"],
            fg=self.colors["text"],
            font=("Segoe UI", 8),
            anchor="w",
        ).grid(row=0, column=2, sticky="ew")

    # ---------------------------------------------------------------- UI
    def _setup_ui(self):
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        self.colors = dict(THEME_COLORS.get(self.theme_name, THEME_COLORS[DEFAULT_THEME]))
        self.root.configure(bg=self.colors['bg'])
        style.configure("TSeparator", background=self.colors["border"])

        # Top Toolbar
        toolbar = tk.Frame(
            self.root,
            bd=0,
            bg=self.colors['panel'],
            height=64,
            highlightbackground=self.colors["border"],
            highlightthickness=0,
        )
        toolbar.pack(side=tk.TOP, fill=tk.X)
        toolbar.pack_propagate(False)
        toolbar.grid_columnconfigure(1, weight=1)
        toolbar.grid_rowconfigure(0, weight=1)

        title_frame = tk.Frame(toolbar, bg=self.colors["panel"])
        title_frame.grid(row=0, column=0, sticky="w", padx=(16, 24))
        tk.Label(title_frame, text="YOLO Annotation Editor",
                 bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 14, "bold"), anchor="w").pack(anchor="w")
        tk.Label(title_frame, text="Dataset labeling workspace",
                 bg=self.colors["panel"], fg=self.colors["text_dim"],
                 font=("Segoe UI", 9), anchor="w").pack(anchor="w")

        self.lbl_status = tk.Label(toolbar, text="No folder loaded", bg=self.colors['panel'],
                                   fg=self.colors['text_dim'], font=("Segoe UI", 10),
                                   anchor="w")
        self.lbl_status.grid(row=0, column=1, sticky="ew", padx=(0, 16))

        actions_frame = tk.Frame(toolbar, bg=self.colors["panel"])
        actions_frame.grid(row=0, column=2, sticky="e", padx=(0, 14))
        self.lbl_autosave = tk.Label(actions_frame, text="Auto-save on",
                                     fg=self.colors["autosave_fg"], bg=self.colors["autosave_bg"],
                                     font=("Segoe UI", 9, "bold"),
                                     padx=10, pady=6)
        self.lbl_autosave.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_theme = self._make_button(actions_frame, self._theme_button_text(), self.toggle_theme,
                                           "secondary", font=("Segoe UI", 9, "bold"),
                                           padx=12, pady=7)
        self.btn_theme.pack(side=tk.LEFT, padx=(0, 8))
        self._make_button(actions_frame, "Help", self.show_help, "secondary",
                          font=("Segoe UI", 9, "bold"), padx=12, pady=7).pack(side=tk.LEFT, padx=(0, 8))
        self._make_button(actions_frame, "Load Folder", self.load_folder, "primary",
                          font=("Segoe UI", 9, "bold"), padx=14, pady=7).pack(side=tk.LEFT)

        # Main layout
        main_frame = tk.Frame(self.root, bg=self.colors['bg'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        self.canvas_frame = tk.Frame(
            main_frame,
            bg=self.colors['canvas_bg'],
            highlightbackground=self.colors["border"],
            highlightthickness=1,
        )
        self.canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 12))

        self.canvas = tk.Canvas(self.canvas_frame, bg=self.colors['canvas_bg'], highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._bind_canvas_events()

        # Right control panel
        right_outer = tk.Frame(
            main_frame,
            width=420,
            bg=self.colors['panel_alt'],
            highlightbackground=self.colors["border"],
            highlightthickness=1,
        )
        self.right_panel = right_outer
        right_outer.pack(side=tk.RIGHT, fill=tk.Y)
        right_outer.pack_propagate(False)

        self.control_scrollbar = tk.Scrollbar(right_outer, orient=tk.VERTICAL)
        self.control_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.control_canvas = tk.Canvas(
            right_outer,
            bg=self.colors['panel_alt'],
            highlightthickness=0,
            bd=0,
            yscrollcommand=self.control_scrollbar.set,
        )
        self.control_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.control_scrollbar.config(command=self.control_canvas.yview)
        self.control_panel = tk.Frame(self.control_canvas, bg=self.colors['panel_alt'])
        self.control_window_id = self.control_canvas.create_window(
            (0, 8), window=self.control_panel, anchor="nw"
        )
        self.control_panel.bind("<Configure>", self._on_control_panel_configure)
        self.control_canvas.bind("<Configure>", self._on_control_canvas_configure)
        self.root.bind_all("<MouseWheel>", self._on_sidebar_mousewheel)
        self.root.bind_all("<Button-4>", self._on_sidebar_mousewheel)
        self.root.bind_all("<Button-5>", self._on_sidebar_mousewheel)

        # Files
        files_body = self._make_section("Files", "Image list")

        filter_row = tk.Frame(files_body, bg=self.colors["panel"])
        filter_row.pack(fill=tk.X, pady=(0, 5))
        self.file_filter_var = tk.StringVar(value=self.file_filter_text)
        self.entry_file_filter = tk.Entry(
            filter_row,
            textvariable=self.file_filter_var,
            bg=self.colors["input_bg"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            font=("Segoe UI", 9),
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["accent"],
        )
        self.entry_file_filter.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self._make_button(
            filter_row, "Clear", self._clear_file_filter, "secondary",
            font=("Segoe UI", 8, "bold"), padx=9, pady=4,
        ).pack(side=tk.RIGHT)

        listbox_frame = tk.Frame(
            files_body,
            bg=self.colors["border"],
            highlightthickness=0,
            bd=0,
        )
        listbox_frame.pack(fill=tk.BOTH)
        listbox_frame.grid_rowconfigure(0, weight=1)
        listbox_frame.grid_columnconfigure(0, weight=1)

        yscroll = tk.Scrollbar(listbox_frame, orient=tk.VERTICAL)
        xscroll = tk.Scrollbar(listbox_frame, orient=tk.HORIZONTAL)
        self.listbox = tk.Listbox(
            listbox_frame,
            height=8,
            bg=self.colors["input_bg"],
            fg=self.colors["text"],
            selectbackground=self.colors['accent'],
            selectforeground='white',
            font=("Consolas", 9),
            relief=tk.FLAT,
            highlightthickness=0,
            activestyle="none",
            bd=0,
            exportselection=False,
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set,
        )
        yscroll.config(command=self.listbox.yview)
        xscroll.config(command=self.listbox.xview)
        self.listbox.grid(row=0, column=0, sticky="nsew", padx=(1, 0), pady=(1, 0))
        yscroll.grid(row=0, column=1, sticky="ns", padx=(0, 1), pady=(1, 0))
        xscroll.grid(row=1, column=0, sticky="ew", padx=(1, 0), pady=(0, 1))
        self.listbox.bind("<<ListboxSelect>>", self.on_file_select)
        self.entry_file_filter.bind("<Return>", lambda _e: self._open_first_filtered_file())
        self.entry_file_filter.bind("<Escape>", lambda _e: self._clear_file_filter())
        self.file_filter_var.trace_add("write", self._on_file_filter_changed)

        self.lbl_file_count = tk.Label(
            files_body,
            text="0 images",
            font=("Segoe UI", 8),
            bg=self.colors['panel'],
            fg=self.colors['text_dim'],
            anchor="w",
        )
        self.lbl_file_count.pack(fill=tk.X, pady=(4, 0))

        # Active config indicator
        self.lbl_config_src = tk.Label(files_body, text="config: (default)",
                                       font=("Segoe UI", 9, "italic"),
                                       bg=self.colors['panel'], fg=self.colors['text_dim'],
                                       wraplength=310, justify="left", anchor="w")
        self.lbl_config_src.pack(fill=tk.X, pady=(8, 0))

        # Class legend (re-rendered when config changes)
        labels_body = self._make_section("Label Mapping", "Keyboard shortcuts and ids")
        legend_grid = tk.Frame(labels_body, bg=self.colors["panel"])
        legend_grid.pack(fill=tk.X)
        legend_grid.columnconfigure(0, weight=1, uniform="legend")
        legend_grid.columnconfigure(1, weight=1, uniform="legend")

        class_column = tk.Frame(legend_grid, bg=self.colors["panel"])
        class_column.grid(row=0, column=0, sticky="new", padx=(0, 8))
        self._subheading(class_column, "CLASSES")
        self.class_legend_frame = tk.Frame(class_column, bg=self.colors['panel'])
        self.class_legend_frame.pack(fill=tk.X)

        # Person legend (re-rendered when config changes)
        person_column = tk.Frame(legend_grid, bg=self.colors["panel"])
        person_column.grid(row=0, column=1, sticky="new", padx=(8, 0))
        self._subheading(person_column, "PERSONS")
        self.person_legend_frame = tk.Frame(person_column, bg=self.colors['panel'])
        self.person_legend_frame.pack(fill=tk.X)

        # Initial legend draw
        self._render_legends()

        # Selected Box Info
        selection_body = self._make_section("Selection", "Current bounding box")
        self.lbl_selected_box = tk.Label(selection_body, text="None", font=("Segoe UI", 11, "bold"),
                                         bg=self.colors['panel'], fg=self.colors['accent'],
                                         wraplength=310, justify="left", anchor="w")
        self.lbl_selected_box.pack(fill=tk.X)

        tk.Label(selection_body,
                 text="Tab/klik pilih box, hotkey ubah class/person.",
                 font=("Segoe UI", 8),
                 bg=self.colors['panel'], fg=self.colors['text_dim'],
                 anchor="w", justify="left", wraplength=380).pack(fill=tk.X, pady=(4, 6))

        dim_row = tk.Frame(selection_body, bg=self.colors["panel"])
        dim_row.pack(fill=tk.X, pady=(0, 6))
        tk.Label(
            dim_row,
            text="Other boxes",
            font=("Segoe UI", 8),
            bg=self.colors["panel"],
            fg=self.colors["text_dim"],
            anchor="w",
        ).pack(side=tk.LEFT, padx=(0, 6))
        self.unpicked_visibility_var = tk.IntVar(value=self.unpicked_box_visibility)
        self.scale_unpicked_visibility = tk.Scale(
            dim_row,
            from_=UNPICKED_BOX_VISIBILITY_MIN,
            to=100,
            orient=tk.HORIZONTAL,
            variable=self.unpicked_visibility_var,
            command=self._on_unpicked_visibility_changed,
            showvalue=False,
            resolution=1,
            sliderlength=14,
            length=92,
            bg=self.colors["panel"],
            fg=self.colors["text"],
            troughcolor=self.colors["input_bg"],
            activebackground=self.colors["accent"],
            highlightthickness=0,
            bd=0,
        )
        self.scale_unpicked_visibility.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.lbl_unpicked_visibility = tk.Label(
            dim_row,
            text=f"{self.unpicked_box_visibility}%",
            font=("Segoe UI", 8, "bold"),
            bg=self.colors["panel"],
            fg=self.colors["text"],
            width=4,
            anchor="e",
        )
        self.lbl_unpicked_visibility.pack(side=tk.LEFT, padx=(5, 6))
        self.lbl_unpicked_color_swatch = tk.Label(
            dim_row,
            text="",
            bg=self._unpicked_box_color(),
            width=2,
            relief=tk.FLAT,
            bd=0,
        )
        self.lbl_unpicked_color_swatch.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4))
        self.unpicked_color_var = tk.StringVar(value=self.unpicked_box_color_name)
        self.menu_unpicked_color = tk.OptionMenu(
            dim_row,
            self.unpicked_color_var,
            *UNPICKED_BOX_COLOR_PRESETS.keys(),
            command=self._on_unpicked_color_changed,
        )
        self.menu_unpicked_color.configure(
            bg=self.colors["control"],
            fg=self._button_text_color("secondary"),
            activebackground=self.colors["control_hover"],
            activeforeground=self._button_text_color("secondary"),
            font=("Segoe UI", 8, "bold"),
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            width=7,
        )
        self.menu_unpicked_color["menu"].configure(
            bg=self.colors["panel"],
            fg=self.colors["text"],
            activebackground=self.colors["accent"],
            activeforeground="white",
        )
        self.menu_unpicked_color.pack(side=tk.RIGHT)

        # Draw new box (manual annotation)
        self.btn_draw = self._make_button(selection_body, "Draw Box (Ctrl+B)",
                                          self.toggle_draw_mode, "primary", pady=5)
        self.btn_draw.pack(fill=tk.X, pady=(0, 5))

        # Delete selected box button
        edit_actions = tk.Frame(selection_body, bg=self.colors["panel"])
        edit_actions.pack(fill=tk.X)
        self._make_button(edit_actions, "Delete Box (Del)",
                          self.delete_selected_box, "danger", pady=5).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4)
        )

        # Undo button (Ctrl+Z)
        self._make_button(edit_actions, "Undo (Ctrl+Z)",
                          self.undo, "neutral", pady=5).pack(
            side=tk.RIGHT, expand=True, fill=tk.X, padx=(4, 0)
        )

        # Progress
        navigation_body = self._make_section("Navigation", "Dataset progress and jump")
        nav_top = tk.Frame(navigation_body, bg=self.colors["panel"])
        nav_top.pack(fill=tk.X)
        self.lbl_progress = tk.Label(nav_top, text="0 / 0 (Visited: 0)",
                                     font=("Segoe UI", 11, "bold"),
                                     bg=self.colors['panel'], fg=self.colors["progress"],
                                     anchor="w")
        self.lbl_progress.pack(side=tk.LEFT, fill=tk.X, expand=True)

        jump_frame = tk.Frame(nav_top, bg=self.colors['panel'])
        jump_frame.pack(side=tk.RIGHT)
        tk.Label(jump_frame, text="Go to:", bg=self.colors['panel'], fg=self.colors['text'],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.entry_jump = tk.Entry(jump_frame, width=8, bg=self.colors["input_bg"], fg=self.colors["text"],
                                   insertbackground=self.colors["text"], font=("Segoe UI", 9),
                                   relief=tk.FLAT, bd=0, highlightthickness=1,
                                   highlightbackground=self.colors["border"],
                                   highlightcolor=self.colors["accent"])
        self.entry_jump.pack(side=tk.LEFT, padx=5)
        self._make_button(jump_frame, "Go", self.jump_to_image, "primary",
                          font=("Segoe UI", 9, "bold"), padx=12, pady=4).pack(side=tk.LEFT)
        self.entry_jump.bind("<Return>", lambda e: self.jump_to_image())
        # Prevent jump entry from stealing hotkeys back to root focus
        self.entry_jump.bind("<FocusOut>", lambda e: None)

        # Nav buttons
        nav_frame = tk.Frame(navigation_body, bg=self.colors['panel'])
        nav_frame.pack(fill=tk.X)
        self._make_button(
            nav_frame, "Prev", self.prev_image, "secondary",
            repeatdelay=NAV_REPEAT_INITIAL_DELAY_MS,
            repeatinterval=NAV_REPEAT_INTERVAL_MS,
        ).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5)
        )
        self._make_button(
            nav_frame, "Next", self.next_image, "secondary",
            repeatdelay=NAV_REPEAT_INITIAL_DELAY_MS,
            repeatinterval=NAV_REPEAT_INTERVAL_MS,
        ).pack(
            side=tk.RIGHT, expand=True, fill=tk.X, padx=(5, 0)
        )

    def _on_canvas_resize(self, event):
        if event.width <= 1 or event.height <= 1:
            return
        if self.current_image is None:
            self._draw_empty_state(event.width, event.height)
        else:
            self.draw_canvas()

    def _draw_empty_state(self, width=None, height=None):
        if self.current_image is not None:
            return
        c_w = width or self.canvas.winfo_width()
        c_h = height or self.canvas.winfo_height()
        if c_w <= 1 or c_h <= 1:
            return
        self.canvas.delete("all")
        x = c_w // 2
        y = max(80, c_h // 2 - 18)
        self.canvas.create_text(
            x, y,
            text="No dataset loaded",
            fill=self.colors["text"],
            font=("Segoe UI", 18, "bold"),
        )
        self.canvas.create_text(
            x, y + 34,
            text="Use Load Folder to open an image dataset.",
            fill=self.colors["text_dim"],
            font=("Segoe UI", 10),
        )

    # ---------------------------------------------------------------- folder
    def load_folder(self):
        folder = filedialog.askdirectory(title="Select Dataset Root (contains images/ and labels/)")
        if not folder:
            return

        self.dataset_root = folder
        self.image_dir = os.path.join(folder, "images")
        self.label_dir = os.path.join(folder, LABELS_DIR_NAME)
        self.label_pid_dir = os.path.join(folder, LABELS_PID_DIR_NAME)

        # Reset undo stack saat ganti dataset — snapshot lama sudah tidak relevan
        self.undo_stack = []

        # If a per-dataset config exists, load it (overrides global config until next folder)
        self._maybe_load_dataset_config(folder)

        images_exists = os.path.isdir(self.image_dir)
        labels_exists = os.path.isdir(self.label_dir)
        labels_pid_exists = os.path.isdir(self.label_pid_dir)

        if not images_exists or not (labels_exists or labels_pid_exists):
            missing = []
            if not images_exists:
                missing.append("images")
            if not labels_exists and not labels_pid_exists:
                missing.append(f"{LABELS_DIR_NAME} atau {LABELS_PID_DIR_NAME}")
            messagebox.showwarning(
                "Folder Structure Warning",
                f"Folder '{os.path.basename(folder)}' tidak memiliki subfolder:\n\n"
                f"Missing: {', '.join(missing)}\n\n"
                f"Struktur yang diharapkan:\n"
                f"{os.path.basename(folder)}/\n"
                f"   images/\n"
                f"   {LABELS_DIR_NAME}/\n"
                f"   {LABELS_PID_DIR_NAME}/\n\n"
                f"Akan mencoba load dari folder root..."
            )
            self.image_dir = folder
            self.label_dir = folder
            self.label_pid_dir = folder

        # Ensure output dirs exist
        try:
            os.makedirs(self.label_dir, exist_ok=True)
            os.makedirs(self.label_pid_dir, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Error", f"Gagal membuat folder output:\n{e}")
            return

        self.image_files = [f for f in os.listdir(self.image_dir)
                            if f.lower().endswith(('.jpg', '.png', '.jpeg', '.bmp'))]
        self.image_files.sort()

        self.file_filter_text = ""
        if hasattr(self, "file_filter_var"):
            self.file_filter_var.set("")
        self._refresh_file_list()

        self.cache_file_path = os.path.join(folder, ".annotation_cache.json")
        self.load_cache()

        # Write/refresh dataset YAML mapping (Old Fixed Dataset style)
        self._write_dataset_yaml()

        if self.image_files:
            self.current_index = 0
            self.prev_boxes = []
            self.prev_selected_box_index = -1
            self.prev_class_checkpoint_index = -1
            self.prev_person_checkpoint_index = -1
            self.prev_class_checkpoint_manual = False
            self.prev_person_checkpoint_manual = False
            self._reset_label_checkpoints(-1)
            self.visited_images = set()
            self.load_image(0)
            self._sync_file_list_selection()
            self.lbl_status.config(text=f"Loaded {len(self.image_files)} images",
                                   fg=self.colors['text_dim'])
        else:
            messagebox.showinfo("Info", "No images found in folder.")

    def _write_dataset_yaml(self):
        """Write a labels_with_person_id.yaml summary into the dataset root."""
        if not self.dataset_root:
            return
        try:
            data = {
                "persons": {pid: name for pid, name, _ in self.persons},
                "classes": {cid: name for cid, name, _ in self.classes},
                "label_format": "person_id class_id x_center y_center width height",
                "note": ("This dual-format dataset was produced by the YOLO Annotation Editor. "
                         f"'{LABELS_DIR_NAME}/' uses 5 columns (standard YOLO), "
                         f"'{LABELS_PID_DIR_NAME}/' uses 6 columns including person_id."),
            }
            with open(os.path.join(self.dataset_root, DATASET_YAML_NAME), "w", encoding="utf-8") as f:
                _safe_yaml_dump(data, f)
        except Exception as e:
            print(f"Failed to write dataset yaml: {e}")

    # ---------------------------------------------------------------- cache
    def load_cache(self):
        self.edit_cache = {}
        if not os.path.exists(self.cache_file_path):
            return
        try:
            with open(self.cache_file_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            print(f"Failed to load cache: {e}")
            return

        # Migrate legacy cache shape ({filename: [class_id, ...]})
        migrated = {}
        for fname, entries in raw.items():
            new_entries = []
            for item in entries:
                if isinstance(item, list) and len(item) >= 2:
                    new_entries.append([int(item[0]), int(item[1])])
                elif isinstance(item, (int, float)):
                    # legacy: only class_id, default person 0
                    new_entries.append([0, int(item)])
            migrated[fname] = new_entries
        self.edit_cache = migrated
        print(f"Loaded cache with {len(self.edit_cache)} entries")

    def save_cache(self):
        if not self.cache_file_path:
            return
        try:
            with open(self.cache_file_path, "w", encoding="utf-8") as f:
                json.dump(self.edit_cache, f, indent=2)
        except Exception as e:
            print(f"Failed to save cache: {e}")

    def update_cache(self, filename):
        if self.boxes:
            self.edit_cache[filename] = [[int(b[0]), int(b[1])] for b in self.boxes]
            self.save_cache()

    # -------------------------------------------------------------- selection
    def _valid_box_index(self, index):
        return 0 <= index < len(self.boxes)

    def _default_box_index(self):
        return 0 if self.boxes else -1

    def _reset_label_checkpoints(self, index=None):
        """Reset class/person checkpoints to the same default selected box."""
        if index is None or not self._valid_box_index(index):
            index = self._default_box_index()
        self.class_checkpoint_index = index
        self.person_checkpoint_index = index
        self.class_checkpoint_manual = False
        self.person_checkpoint_manual = False

    def _set_selected_box(self, index, reset_checkpoints=False):
        if not self.boxes:
            self.selected_box_index = -1
            self._reset_label_checkpoints(-1)
            return

        if not self._valid_box_index(index):
            index = self._default_box_index()
        self.selected_box_index = index

        if reset_checkpoints:
            self._reset_label_checkpoints(index)
            return

        # Before the user sets class/person separately, selection behaves like
        # the old single checkpoint. Once a label side is set by hotkey, only
        # that side's hotkey moves its checkpoint.
        if not self.class_checkpoint_manual:
            self.class_checkpoint_index = index
        if not self.person_checkpoint_manual:
            self.person_checkpoint_index = index

    def _handle_deleted_checkpoint(self, checkpoint_index, deleted_index):
        if checkpoint_index == -1:
            return -1
        if checkpoint_index == deleted_index:
            return self.selected_box_index
        if checkpoint_index > deleted_index:
            return checkpoint_index - 1
        return checkpoint_index

    def _format_checkpoint(self, checkpoint_index):
        if self._valid_box_index(checkpoint_index):
            return f"Box {checkpoint_index + 1}"
        return "-"

    def _focus_is_text_input(self):
        try:
            focused = self.root.focus_get()
        except tk.TclError:
            return False
        return isinstance(focused, (tk.Entry, ttk.Entry, tk.Text))

    def _start_nav_repeat(self, direction):
        if self._focus_is_text_input():
            return None
        if self._nav_repeat_direction == direction:
            return "break"
        self._stop_nav_repeat()
        self._nav_repeat_direction = direction
        if self._step_nav(direction):
            self._schedule_nav_repeat(NAV_REPEAT_INITIAL_DELAY_MS)
        else:
            self._nav_repeat_direction = 0
        return "break"

    def _stop_nav_repeat(self, direction=None):
        if direction is not None and self._nav_repeat_direction not in (0, direction):
            return "break"
        if self._nav_repeat_after_id is not None:
            try:
                self.root.after_cancel(self._nav_repeat_after_id)
            except tk.TclError:
                pass
        self._nav_repeat_after_id = None
        self._nav_repeat_direction = 0
        return "break"

    def _schedule_nav_repeat(self, delay_ms):
        self._nav_repeat_after_id = self.root.after(delay_ms, self._run_nav_repeat)

    def _run_nav_repeat(self):
        self._nav_repeat_after_id = None
        direction = self._nav_repeat_direction
        if not direction:
            return
        if self._step_nav(direction):
            self._schedule_nav_repeat(NAV_REPEAT_INTERVAL_MS)
        else:
            self._nav_repeat_direction = 0

    def _step_nav(self, direction):
        before = self.current_index
        if direction > 0:
            self.next_image()
        else:
            self.prev_image()
        return self.current_index != before

    def _on_file_filter_changed(self, *_args):
        self.file_filter_text = self.file_filter_var.get()
        self._refresh_file_list()

    def _clear_file_filter(self):
        if hasattr(self, "file_filter_var"):
            self.file_filter_var.set("")
        else:
            self.file_filter_text = ""
        self.root.focus_set()
        return "break"

    def _open_first_filtered_file(self):
        if not self.filtered_image_indices:
            return "break"
        target_index = self.filtered_image_indices[0]
        if target_index == self.current_index:
            self._sync_file_list_selection()
            self.root.focus_set()
            return "break"
        self._open_image_index(target_index)
        return "break"

    def _format_file_list_item(self, index):
        width = max(4, len(str(len(self.image_files))))
        return f"{index + 1:>{width}}  {self.image_files[index]}"

    def _refresh_file_list(self):
        if not hasattr(self, "listbox"):
            return
        query = self.file_filter_text.strip().lower()
        if query:
            self.filtered_image_indices = [
                i for i, filename in enumerate(self.image_files)
                if query in filename.lower()
            ]
        else:
            self.filtered_image_indices = list(range(len(self.image_files)))

        self._updating_file_list = True
        try:
            self.listbox.delete(0, tk.END)
            for index in self.filtered_image_indices:
                self.listbox.insert(tk.END, self._format_file_list_item(index))
            self._sync_file_list_selection()
        finally:
            self._updating_file_list = False
        self._update_file_count_label()

    def _update_file_count_label(self):
        if not hasattr(self, "lbl_file_count"):
            return
        total = len(self.image_files)
        shown = len(self.filtered_image_indices)
        if not total:
            text = "0 images"
        elif self.file_filter_text.strip():
            text = f"{shown} / {total} shown"
            if self.current_index not in self.filtered_image_indices:
                text += f" | current #{self.current_index + 1}"
        else:
            text = f"{total} images"
        self.lbl_file_count.config(text=text)

    def _sync_file_list_selection(self):
        if not hasattr(self, "listbox"):
            return
        was_updating = self._updating_file_list
        self._updating_file_list = True
        try:
            self.listbox.selection_clear(0, tk.END)
            try:
                visible_row = self.filtered_image_indices.index(self.current_index)
            except ValueError:
                self._update_file_count_label()
                return
            self.listbox.selection_set(visible_row)
            self.listbox.activate(visible_row)
            self.listbox.see(visible_row)
            self._update_file_count_label()
        finally:
            self._updating_file_list = was_updating

    def _open_image_index(self, target_index, inherit_from_prev=False, preserve_selection=None):
        if not (0 <= target_index < len(self.image_files)):
            return
        self.save_current(silent=True)
        self.prev_boxes = []
        self.prev_selected_box_index = -1
        self.prev_class_checkpoint_index = -1
        self.prev_person_checkpoint_index = -1
        self.prev_class_checkpoint_manual = False
        self.prev_person_checkpoint_manual = False
        self.current_index = target_index
        self._sync_file_list_selection()
        self.load_image(
            self.current_index,
            inherit_from_prev=inherit_from_prev,
            preserve_selection=preserve_selection,
        )
        self.root.focus_set()

    # ---------------------------------------------------------------- nav
    def on_file_select(self, event):
        if self._updating_file_list:
            return
        sel = self.listbox.curselection()
        if sel:
            row = sel[0]
            if not (0 <= row < len(self.filtered_image_indices)):
                return
            target_index = self.filtered_image_indices[row]
            if target_index == self.current_index:
                self.root.focus_set()
                return
            self._open_image_index(target_index)

    def next_image(self):
        if self.current_index < len(self.image_files) - 1:
            self.save_current(silent=True)
            self.prev_boxes = [box[:] for box in self.boxes]
            self.prev_selected_box_index = self.selected_box_index
            self.prev_class_checkpoint_index = self.class_checkpoint_index
            self.prev_person_checkpoint_index = self.person_checkpoint_index
            self.prev_class_checkpoint_manual = self.class_checkpoint_manual
            self.prev_person_checkpoint_manual = self.person_checkpoint_manual
            self.current_index += 1
            self._sync_file_list_selection()
            self.load_image(self.current_index, inherit_from_prev=True)

    def prev_image(self):
        if self.current_index > 0:
            self.save_current(silent=True)
            self.prev_boxes = [box[:] for box in self.boxes]
            self.prev_selected_box_index = self.selected_box_index
            self.prev_class_checkpoint_index = self.class_checkpoint_index
            self.prev_person_checkpoint_index = self.person_checkpoint_index
            self.prev_class_checkpoint_manual = self.class_checkpoint_manual
            self.prev_person_checkpoint_manual = self.person_checkpoint_manual
            self.current_index -= 1
            self._sync_file_list_selection()
            self.load_image(self.current_index, inherit_from_prev=True)

    def jump_to_image(self):
        try:
            target = int(self.entry_jump.get())
            target_index = target - 1
            if 0 <= target_index < len(self.image_files):
                self._open_image_index(target_index)
                self.entry_jump.delete(0, tk.END)
            else:
                messagebox.showwarning("Invalid",
                                       f"Please enter a number between 1 and {len(self.image_files)}")
        except ValueError:
            messagebox.showwarning("Invalid", "Please enter a valid number")

    # ---------------------------------------------------------------- load
    def _read_label_file(self, path):
        """Read a label file. Auto-detects 5- vs 6-column format.

        Returns list of [person_id, class_id, cx, cy, w, h].
        """
        boxes = []
        if not os.path.exists(path):
            return boxes
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 6:
                        # person_id class_id cx cy w h
                        boxes.append([
                            int(float(parts[0])), int(float(parts[1])),
                            float(parts[2]), float(parts[3]),
                            float(parts[4]), float(parts[5]),
                        ])
                    elif len(parts) >= 5:
                        # class_id cx cy w h -> assume person 0
                        boxes.append([
                            0, int(float(parts[0])),
                            float(parts[1]), float(parts[2]),
                            float(parts[3]), float(parts[4]),
                        ])
        except Exception as e:
            print(f"Error reading label {path}: {e}")
        return boxes

    def load_image(self, index, inherit_from_prev=False, preserve_selection=None):
        if not self.image_files:
            return

        filename = self.image_files[index]
        image_path = os.path.join(self.image_dir, filename)
        try:
            self.current_image = Image.open(image_path)
        except Exception as e:
            print(f"Error loading image: {e}")
            return

        self.visited_images.add(index)

        # Prefer 6-col file in labels_with_person_id/, else fallback to 5-col labels/
        label_name = os.path.splitext(filename)[0] + ".txt"
        path_pid = os.path.join(self.label_pid_dir, label_name) if self.label_pid_dir else ""
        path_cls = os.path.join(self.label_dir, label_name) if self.label_dir else ""

        if path_pid and os.path.exists(path_pid):
            self.boxes = self._read_label_file(path_pid)
        elif path_cls and os.path.exists(path_cls):
            self.boxes = self._read_label_file(path_cls)
        else:
            self.boxes = []

        # Apply cache (overrides person_id and class_id from file)
        if filename in self.edit_cache:
            cached = self.edit_cache[filename]
            for i, box in enumerate(self.boxes):
                if i < len(cached):
                    box[0] = int(cached[i][0])
                    box[1] = int(cached[i][1])

        if inherit_from_prev and self.prev_boxes:
            self._inherit_from_prev()
        elif preserve_selection is not None and self.boxes:
            target = preserve_selection if 0 <= preserve_selection < len(self.boxes) else 0
            self._set_selected_box(target, reset_checkpoints=True)
        else:
            self._set_selected_box(0 if self.boxes else -1, reset_checkpoints=True)

        self.draw_canvas()
        self.update_selected_box_label()
        self.update_progress()

    def update_progress(self):
        total = len(self.image_files)
        visited = len(self.visited_images)
        current = self.current_index + 1 if total else 0
        self.lbl_progress.config(text=f"{current} / {total} (Visited: {visited})")

    # --------------------------------------------------------- inheritance
    def _inherit_from_prev(self):
        """Carry class/person checkpoints and selected box with conservative matching."""
        MATCH_MIN_SCORE = 0.42
        PICKED_MIN_SCORE = 0.50
        AMBIGUITY_MARGIN = 0.07

        if not self.boxes:
            self._set_selected_box(-1, reset_checkpoints=True)
            return

        class_source_idx = self.prev_class_checkpoint_index
        person_source_idx = self.prev_person_checkpoint_index

        if not (0 <= class_source_idx < len(self.prev_boxes)):
            class_source_idx = self.prev_selected_box_index
        if not (0 <= person_source_idx < len(self.prev_boxes)):
            person_source_idx = self.prev_selected_box_index

        class_target_idx = -1
        person_target_idx = -1

        if 0 <= class_source_idx < len(self.prev_boxes):
            prev_class_box = self.prev_boxes[class_source_idx]
            class_target_idx = self._find_best_match(
                prev_class_box,
                min_score=MATCH_MIN_SCORE,
                ambiguity_margin=AMBIGUITY_MARGIN,
            )
            if class_target_idx >= 0:
                self.boxes[class_target_idx][1] = prev_class_box[1]

        if 0 <= person_source_idx < len(self.prev_boxes):
            prev_person_box = self.prev_boxes[person_source_idx]
            person_target_idx = self._find_best_match(
                prev_person_box,
                min_score=MATCH_MIN_SCORE,
                ambiguity_margin=AMBIGUITY_MARGIN,
            )
            if person_target_idx >= 0:
                self.boxes[person_target_idx][0] = prev_person_box[0]

        selected_target_idx = -1
        if 0 <= self.prev_selected_box_index < len(self.prev_boxes):
            selected_target_idx = self._find_best_match(
                self.prev_boxes[self.prev_selected_box_index],
                min_score=PICKED_MIN_SCORE,
                ambiguity_margin=AMBIGUITY_MARGIN,
            )

        if selected_target_idx >= 0:
            self.selected_box_index = selected_target_idx
        else:
            # Matching algorithm not confident — fall back to the physically closest box
            # instead of an arbitrary array index, so the selection doesn't jump randomly.
            if self.boxes and 0 <= self.prev_selected_box_index < len(self.prev_boxes):
                prev_box = self.prev_boxes[self.prev_selected_box_index]
                closest_idx = 0
                min_dist = float('inf')
                for i, box in enumerate(self.boxes):
                    dist = (box[2] - prev_box[2])**2 + (box[3] - prev_box[3])**2
                    if dist < min_dist:
                        min_dist = dist
                        closest_idx = i
                self.selected_box_index = closest_idx
            else:
                self.selected_box_index = 0 if self.boxes else -1

        self.class_checkpoint_manual = self.prev_class_checkpoint_manual
        self.person_checkpoint_manual = self.prev_person_checkpoint_manual

        if class_target_idx >= 0:
            self.class_checkpoint_index = class_target_idx
        elif self.class_checkpoint_manual:
            self.class_checkpoint_index = -1
        else:
            self.class_checkpoint_index = self.selected_box_index

        if person_target_idx >= 0:
            self.person_checkpoint_index = person_target_idx
        elif self.person_checkpoint_manual:
            self.person_checkpoint_index = -1
        else:
            self.person_checkpoint_index = self.selected_box_index

    def _find_best_match(self, prev_box, min_score=0.42, ambiguity_margin=0.07):
        """Find a stable box match using overlap, center distance, size, and labels.

        Returns -1 when the best candidate is weak or too close to another
        candidate. This prevents the selected/PICKED border from jumping to a
        nearby person when detections overlap or cross.
        """
        candidates = []
        for i, box in enumerate(self.boxes):
            score, iou, center_score, label_score = self._match_score(prev_box, box)
            # Reject candidates that are both visually far and barely overlap.
            if iou < 0.08 and center_score < 0.35:
                continue
            candidates.append((score, iou, label_score, i))

        if not candidates:
            return -1

        candidates.sort(reverse=True)
        best_score, best_iou, best_label_score, best_idx = candidates[0]
        if best_score < min_score:
            return -1

        if len(candidates) > 1:
            second_score, second_iou, second_label_score, _ = candidates[1]
            too_close = (best_score - second_score) < ambiguity_margin
            second_is_plausible = second_score >= (min_score * 0.85) or second_iou >= 0.25
            label_breaks_tie = best_label_score > second_label_score and best_iou >= 0.12
            if too_close and second_is_plausible and not label_breaks_tie:
                return -1

        return best_idx

    @staticmethod
    def _match_score(prev_box, box):
        iou = AnnotationEditor._calculate_iou(box, prev_box)

        prev_cx, prev_cy, prev_w, prev_h = prev_box[2], prev_box[3], prev_box[4], prev_box[5]
        cx, cy, bw, bh = box[2], box[3], box[4], box[5]

        dx = cx - prev_cx
        dy = cy - prev_cy
        center_dist = (dx * dx + dy * dy) ** 0.5
        center_tolerance = max(prev_w, prev_h, 0.08) * 2.5
        center_score = max(0.0, 1.0 - (center_dist / center_tolerance))

        prev_area = max(prev_w * prev_h, 1e-9)
        area = max(bw * bh, 1e-9)
        area_score = min(prev_area, area) / max(prev_area, area)

        prev_aspect = prev_w / max(prev_h, 1e-9)
        aspect = bw / max(bh, 1e-9)
        aspect_score = min(prev_aspect, aspect) / max(prev_aspect, aspect)
        size_score = (area_score + aspect_score) / 2

        label_score = 0.0
        prev_pid, prev_cid = int(prev_box[0]), int(prev_box[1])
        pid, cid = int(box[0]), int(box[1])
        if prev_pid != 0 and pid == prev_pid:
            label_score += 0.12
        elif prev_pid != 0 and pid != 0 and pid != prev_pid:
            label_score -= 0.14
        if cid == prev_cid:
            label_score += 0.04

        score = (iou * 0.50) + (center_score * 0.30) + (size_score * 0.16) + label_score
        return score, iou, center_score, label_score

    @staticmethod
    def _calculate_iou(box1, box2):
        # box format: [person_id, class_id, cx, cy, w, h]
        cx1, cy1, w1, h1 = box1[2], box1[3], box1[4], box1[5]
        cx2, cy2, w2, h2 = box2[2], box2[3], box2[4], box2[5]
        x1_1, y1_1, x2_1, y2_1 = cx1 - w1/2, cy1 - h1/2, cx1 + w1/2, cy1 + h1/2
        x1_2, y1_2, x2_2, y2_2 = cx2 - w2/2, cy2 - h2/2, cx2 + w2/2, cy2 + h2/2
        xi1, yi1 = max(x1_1, x1_2), max(y1_1, y1_2)
        xi2, yi2 = min(x2_1, x2_2), min(y2_1, y2_2)
        if xi2 <= xi1 or yi2 <= yi1:
            return 0.0
        inter = (xi2 - xi1) * (yi2 - yi1)
        union = w1 * h1 + w2 * h2 - inter
        return inter / union if union > 0 else 0.0

    # ---------------------------------------------------------------- draw
    def _unpicked_box_color(self):
        span = max(1, 100 - UNPICKED_BOX_VISIBILITY_MIN)
        amount = (self.unpicked_box_visibility - UNPICKED_BOX_VISIBILITY_MIN) / span
        preset_color = UNPICKED_BOX_COLOR_PRESETS.get(self.unpicked_box_color_name)
        if preset_color is None:
            return _mix_hex_color(self.colors["text_dim"], self.colors["text"], amount)
        muted_color = _mix_hex_color(self.colors["canvas_bg"], preset_color, 0.50)
        return _mix_hex_color(muted_color, preset_color, amount)

    def draw_canvas(self):
        if self.current_image is None:
            return

        c_w = self.canvas.winfo_width()
        c_h = self.canvas.winfo_height()
        if c_w <= 1 or c_h <= 1:
            c_w, c_h = 800, 600

        img_w, img_h = self.current_image.size
        ratio = min(c_w / img_w, c_h / img_h)
        self.scale_factor = ratio
        new_w, new_h = int(img_w * ratio), int(img_h * ratio)
        resized = self.current_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(resized)
        self.canvas.delete("all")

        x_off = (c_w - new_w) // 2
        y_off = (c_h - new_h) // 2
        self.img_offset = (x_off, y_off, new_w, new_h)
        self.canvas.create_image(x_off, y_off, anchor=tk.NW, image=self.tk_image)

        def draw_box(i, is_selected):
            box = self.boxes[i]
            pid, cid, cx, cy, bw, bh = box
            x1 = int((cx - bw / 2) * new_w) + x_off
            y1 = int((cy - bh / 2) * new_h) + y_off
            x2 = int((cx + bw / 2) * new_w) + x_off
            y2 = int((cy + bh / 2) * new_h) + y_off

            color = "lime" if is_selected else self._unpicked_box_color()
            width = 3 if is_selected else 2
            dash = None if is_selected else (5, 4)
            self.canvas.create_rectangle(
                x1, y1, x2, y2,
                outline=color,
                width=width,
                dash=dash,
            )

            cls_name = self._class_name_by_id(cid)
            person_name = self._person_name_by_id(pid)
            label_text = f"P{pid}:{person_name} | C{cid}:{cls_name}"

            if is_selected:
                text_w = max(60, len(label_text) * 7 + 6)
                label_y0 = max(0, y1 - 20)
                self.canvas.create_rectangle(
                    x1, label_y0, x1 + text_w, label_y0 + 20,
                    fill=color,
                    outline=color,
                )
                self.canvas.create_text(
                    x1 + 3, label_y0 + 10,
                    text=label_text,
                    fill="black",
                    anchor="w",
                    font=("Arial", 9, "bold"),
                )
                self.canvas.create_text((x1 + x2) // 2, (y1 + y2) // 2,
                                        text="PICKED", fill="yellow",
                                        font=("Arial", 14, "bold"))
            else:
                self.canvas.create_text(
                    x1 + 3,
                    max(10, y1 - 6),
                    text=f"{i + 1}",
                    fill=color,
                    anchor="w",
                    font=("Arial", 8),
                )

        for i in range(len(self.boxes)):
            if i != self.selected_box_index:
                draw_box(i, False)
        if 0 <= self.selected_box_index < len(self.boxes):
            draw_box(self.selected_box_index, True)

    def _class_name_by_id(self, cid):
        for c_id, name, _ in self.classes:
            if c_id == cid:
                return name
        return f"Unknown({cid})"

    def _person_name_by_id(self, pid):
        for p_id, name, _ in self.persons:
            if p_id == pid:
                return name
        return f"Unknown({pid})"

    # ---------------------------------------------------------------- input
    def on_canvas_click(self, event):
        # Saat draw mode aktif, klik = mulai menggambar box baru
        if self.draw_mode:
            self._begin_draw(event)
            return

        if not self.boxes:
            return
        x_off, y_off, new_w, new_h = self.img_offset
        for i, box in enumerate(self.boxes):
            _, _, cx, cy, bw, bh = box
            x1 = int((cx - bw / 2) * new_w) + x_off
            y1 = int((cy - bh / 2) * new_h) + y_off
            x2 = int((cx + bw / 2) * new_w) + x_off
            y2 = int((cy + bh / 2) * new_h) + y_off
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self._set_selected_box(i)
                self.draw_canvas()
                self.update_selected_box_label()
                self.root.focus_set()
                return

    # ---------------------------------------------------------------- draw mode
    def toggle_draw_mode(self, event=None):
        """Aktif/non-aktifkan mode menggambar box manual.

        Saat aktif, klik-drag di kanvas akan membuat bounding box baru. Class &
        person dari box baru bisa langsung di-set lewat hotkey biasa
        (1-0 untuk class, q-w-e-… untuk person).
        """
        if not self.image_files or self.current_image is None:
            self.lbl_status.config(text="Load folder dulu sebelum draw", fg=self.colors["status_warning"])
            return
        self.draw_mode = not self.draw_mode
        self._cancel_draw_preview()
        if self.draw_mode:
            self.canvas.config(cursor="crosshair")
            try:
                self.btn_draw.config(text="Draw Box: ON")
                self._set_button_variant(self.btn_draw, "success")
            except (AttributeError, tk.TclError):
                pass
            self.lbl_status.config(text="Draw mode ON — klik-drag di gambar untuk buat box (Esc batal)",
                                   fg=self.colors["status_success"])
        else:
            self.canvas.config(cursor="")
            try:
                self.btn_draw.config(text="Draw Box (Ctrl+B)")
                self._set_button_variant(self.btn_draw, "primary")
            except (AttributeError, tk.TclError):
                pass
            self.lbl_status.config(text="Draw mode OFF", fg=self.colors['text_dim'])
        self.root.focus_set()

    def _on_escape(self):
        """ESC: batalkan draw mode atau preview rectangle yang sedang dibuat."""
        if self.draw_mode:
            self._cancel_draw_preview()
            self.toggle_draw_mode()

    def _cancel_draw_preview(self):
        if self.draw_preview_id is not None:
            try:
                self.canvas.delete(self.draw_preview_id)
            except tk.TclError:
                pass
            self.draw_preview_id = None
        self.draw_start = None

    def _clamp_to_image(self, x, y):
        """Clamp koordinat kanvas ke kotak gambar (img_offset)."""
        x_off, y_off, new_w, new_h = self.img_offset
        x = max(x_off, min(x_off + new_w, x))
        y = max(y_off, min(y_off + new_h, y))
        return x, y

    def _begin_draw(self, event):
        if self.current_image is None:
            return
        x_off, y_off, new_w, new_h = self.img_offset
        # Hanya mulai drag kalau klik berada di area gambar
        if not (x_off <= event.x <= x_off + new_w and y_off <= event.y <= y_off + new_h):
            return
        self._cancel_draw_preview()
        self.draw_start = (event.x, event.y)
        self.draw_preview_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline=self.colors["draw_preview"], width=2, dash=(4, 2)
        )

    def _on_canvas_drag(self, event):
        if not self.draw_mode or self.draw_start is None or self.draw_preview_id is None:
            return
        x0, y0 = self.draw_start
        x1, y1 = self._clamp_to_image(event.x, event.y)
        try:
            self.canvas.coords(self.draw_preview_id, x0, y0, x1, y1)
        except tk.TclError:
            pass

    def _on_canvas_release(self, event):
        if not self.draw_mode or self.draw_start is None:
            return
        x0, y0 = self.draw_start
        x1, y1 = self._clamp_to_image(event.x, event.y)
        self._cancel_draw_preview()

        # Convert canvas px -> normalized (cx, cy, w, h) sesuai image_offset/scale
        x_off, y_off, new_w, new_h = self.img_offset
        if new_w <= 0 or new_h <= 0:
            return
        # Order corners
        ax, bx = sorted([x0, x1])
        ay, by = sorted([y0, y1])
        # Clamp ke gambar lagi (jaga-jaga)
        ax = max(x_off, min(x_off + new_w, ax))
        bx = max(x_off, min(x_off + new_w, bx))
        ay = max(y_off, min(y_off + new_h, ay))
        by = max(y_off, min(y_off + new_h, by))

        bw_px = bx - ax
        bh_px = by - ay
        # Abaikan klik tunggal / box super kecil (mungkin tidak sengaja)
        if bw_px < 3 or bh_px < 3:
            return

        cx = ((ax + bx) / 2 - x_off) / new_w
        cy = ((ay + by) / 2 - y_off) / new_h
        bw = bw_px / new_w
        bh = bh_px / new_h
        # Final clamp normalized
        cx = min(max(cx, 0.0), 1.0)
        cy = min(max(cy, 0.0), 1.0)
        bw = min(max(bw, 0.0), 1.0)
        bh = min(max(bh, 0.0), 1.0)

        # Default class/person diambil dari box yang sebelumnya terpilih (kalau ada),
        # supaya user bisa cepat menggambar serial box dengan tagging sama.
        default_pid = 0
        default_cid = 0
        if 0 <= self.selected_box_index < len(self.boxes):
            default_pid = int(self.boxes[self.selected_box_index][0])
            default_cid = int(self.boxes[self.selected_box_index][1])

        # Snapshot SEBELUM menambah supaya bisa di-undo
        self._push_undo(action_label="draw box")

        self.boxes.append([default_pid, default_cid, cx, cy, bw, bh])
        self._set_selected_box(len(self.boxes) - 1)

        self.draw_canvas()
        self.update_selected_box_label()

        if self.image_files:
            filename = self.image_files[self.current_index]
            self.update_cache(filename)
            self.save_current(silent=True)

        self.lbl_status.config(
            text=(f"Box baru ditambahkan (P{default_pid} C{default_cid}) — "
                  f"tekan hotkey class/person untuk re-tag"),
            fg=self.colors["status_success"]
        )
        self.root.after(2500, lambda: self.lbl_status.config(
            text=f"Image {self.current_index + 1}/{len(self.image_files)}",
            fg=self.colors['text_dim']))

    def cycle_box(self, event=None):
        if not self.boxes:
            return "break"
        self._set_selected_box((self.selected_box_index + 1) % len(self.boxes))
        self.draw_canvas()
        self.update_selected_box_label()
        return "break"

    # ---------------------------------------------------------------- undo
    def _push_undo(self, action_label=""):
        """Snapshot state SEBELUM perubahan, agar bisa dipulihkan oleh ``undo()``.

        Snapshot berisi: nama file aktif, deep-copy ``self.boxes``, dan
        ``self.selected_box_index`` saat itu. Stack dibatasi ``MAX_UNDO``.
        """
        if not self.image_files:
            return
        filename = self.image_files[self.current_index]
        snap = {
            "filename": filename,
            "boxes": [list(b) for b in self.boxes],
            "selected": self.selected_box_index,
            "class_checkpoint": self.class_checkpoint_index,
            "person_checkpoint": self.person_checkpoint_index,
            "class_checkpoint_manual": self.class_checkpoint_manual,
            "person_checkpoint_manual": self.person_checkpoint_manual,
            "label": action_label,
        }
        self.undo_stack.append(snap)
        if len(self.undo_stack) > self.MAX_UNDO:
            # Buang yang paling lama (FIFO trim)
            del self.undo_stack[0:len(self.undo_stack) - self.MAX_UNDO]

    def undo(self):
        """Kembalikan state terakhir dari undo stack.

        Kalau snapshot teratas berasal dari frame yang berbeda, otomatis pindah
        ke frame tersebut sebelum me-restore boxes-nya.
        """
        # Hindari undo saat user sedang mengetik di entry widget
        if isinstance(self.root.focus_get(), tk.Entry):
            return
        if not self.undo_stack:
            self.lbl_status.config(text="Nothing to undo", fg=self.colors['text_dim'])
            return
        snap = self.undo_stack.pop()

        # Pindah frame kalau snapshot bukan untuk gambar yang sedang dibuka
        target_filename = snap["filename"]
        if target_filename in self.image_files:
            target_idx = self.image_files.index(target_filename)
            if target_idx != self.current_index:
                # Simpan dulu frame saat ini supaya state-nya tidak hilang,
                # tapi JANGAN dorong ke undo stack (itu akan jadi loop).
                self.save_current(silent=True)
                self.current_index = target_idx
                self._sync_file_list_selection()
                # Reload image (tanpa inheritance) — boxes akan ditimpa setelah ini.
                self.load_image(self.current_index)

        # Restore boxes & selection
        self.boxes = [list(b) for b in snap["boxes"]]
        sel = snap["selected"]
        if self.boxes:
            self.selected_box_index = sel if 0 <= sel < len(self.boxes) else 0
        else:
            self.selected_box_index = -1

        self.class_checkpoint_index = snap.get("class_checkpoint", self.selected_box_index)
        self.person_checkpoint_index = snap.get("person_checkpoint", self.selected_box_index)
        if not self._valid_box_index(self.class_checkpoint_index):
            self.class_checkpoint_index = self.selected_box_index
        if not self._valid_box_index(self.person_checkpoint_index):
            self.person_checkpoint_index = self.selected_box_index
        self.class_checkpoint_manual = bool(snap.get("class_checkpoint_manual", False))
        self.person_checkpoint_manual = bool(snap.get("person_checkpoint_manual", False))

        # Sinkronkan cache untuk file ini berdasarkan boxes yang dipulihkan
        if self.boxes:
            self.edit_cache[target_filename] = [
                [int(b[0]), int(b[1])] for b in self.boxes
            ]
        else:
            self.edit_cache.pop(target_filename, None)
        self.save_cache()

        # Tulis ulang file label dari boxes yang dipulihkan
        self.save_current(silent=True)

        self.draw_canvas()
        self.update_selected_box_label()

        action = snap.get("label") or "edit"
        self.lbl_status.config(
            text=f"Undid {action} — {len(self.undo_stack)} undo tersisa",
            fg=self.colors["status_warning"]
        )
        self.root.after(2000, lambda: self.lbl_status.config(
            text=f"Image {self.current_index + 1}/{len(self.image_files)}",
            fg=self.colors['text_dim']))

    def set_class(self, class_id):
        if self.selected_box_index == -1 or not self.boxes:
            return
        # Skip if focus is in entry widget (so jump field doesn't trigger hotkeys)
        if isinstance(self.root.focus_get(), tk.Entry):
            return
        # Skip kalau nilainya tidak berubah supaya undo stack tidak penuh dengan no-op
        if int(self.boxes[self.selected_box_index][1]) == int(class_id):
            self.class_checkpoint_index = self.selected_box_index
            self.class_checkpoint_manual = True
            self.update_selected_box_label()
            return
        self._push_undo(action_label=f"set class={int(class_id)}")
        self.class_checkpoint_index = self.selected_box_index
        self.class_checkpoint_manual = True
        self.boxes[self.selected_box_index][1] = int(class_id)
        self.draw_canvas()
        self.update_selected_box_label()
        if self.image_files:
            self.update_cache(self.image_files[self.current_index])
        self.save_current(silent=True)

    def set_person(self, person_id):
        if self.selected_box_index == -1 or not self.boxes:
            return
        if isinstance(self.root.focus_get(), tk.Entry):
            return
        if int(self.boxes[self.selected_box_index][0]) == int(person_id):
            self.person_checkpoint_index = self.selected_box_index
            self.person_checkpoint_manual = True
            self.update_selected_box_label()
            return
        self._push_undo(action_label=f"set person={int(person_id)}")
        self.person_checkpoint_index = self.selected_box_index
        self.person_checkpoint_manual = True
        self.boxes[self.selected_box_index][0] = int(person_id)
        self.draw_canvas()
        self.update_selected_box_label()
        if self.image_files:
            self.update_cache(self.image_files[self.current_index])
        self.save_current(silent=True)

    def delete_selected_box(self):
        """Hapus bounding box yang sedang dipilih dari frame saat ini.

        Menghapus dari list ``self.boxes``, mensinkronkan cache, lalu menulis
        ulang file label (5-col & 6-col). Jika fokus sedang di entry widget
        (misal kotak "Go to") aksi diabaikan agar tidak terpicu lewat keystroke.
        """
        # Hindari delete saat user sedang mengetik di entry widget
        if isinstance(self.root.focus_get(), tk.Entry):
            return
        if not self.boxes or self.selected_box_index == -1:
            return
        if not (0 <= self.selected_box_index < len(self.boxes)):
            return

        # Snapshot SEBELUM perubahan supaya bisa di-undo (Ctrl+Z)
        self._push_undo(action_label="delete box")

        idx = self.selected_box_index
        deleted_class_checkpoint = self.class_checkpoint_index == idx
        deleted_person_checkpoint = self.person_checkpoint_index == idx
        removed = self.boxes.pop(idx)

        # Atur ulang index terpilih
        if self.boxes:
            self.selected_box_index = min(idx, len(self.boxes) - 1)
            self.class_checkpoint_index = self._handle_deleted_checkpoint(
                self.class_checkpoint_index, idx
            )
            self.person_checkpoint_index = self._handle_deleted_checkpoint(
                self.person_checkpoint_index, idx
            )
            if deleted_class_checkpoint:
                self.class_checkpoint_manual = False
            if deleted_person_checkpoint:
                self.person_checkpoint_manual = False
        else:
            self.selected_box_index = -1
            self._reset_label_checkpoints(-1)

        # Pastikan inheritance ke frame berikutnya tidak menunjuk box yang sudah hilang
        if self.prev_selected_box_index >= len(self.boxes):
            self.prev_selected_box_index = -1
        if self.prev_class_checkpoint_index >= len(self.boxes):
            self.prev_class_checkpoint_index = -1
        if self.prev_person_checkpoint_index >= len(self.boxes):
            self.prev_person_checkpoint_index = -1

        self.draw_canvas()
        self.update_selected_box_label()

        if self.image_files:
            filename = self.image_files[self.current_index]
            # Update cache: drop the deleted entry untuk file ini
            if filename in self.edit_cache:
                cached = self.edit_cache[filename]
                if 0 <= idx < len(cached):
                    cached.pop(idx)
                if cached:
                    self.edit_cache[filename] = cached
                else:
                    # Tidak ada box tersisa -> bersihkan entri cache
                    del self.edit_cache[filename]
                self.save_cache()
            # Persist langsung ke file label (otomatis menulis ulang dengan box terbaru)
            self.save_current(silent=True)
            self.lbl_status.config(
                text=f"Deleted box (P{int(removed[0])} C{int(removed[1])}) — sisa {len(self.boxes)}",
                fg=self.colors["status_error"]
            )
            self.root.after(2000, lambda: self.lbl_status.config(
                text=f"Image {self.current_index + 1}/{len(self.image_files)}",
                fg=self.colors['text_dim']))

    def update_selected_box_label(self):
        if self.selected_box_index == -1 or not self.boxes:
            self.lbl_selected_box.config(text="None")
            return
        box = self.boxes[self.selected_box_index]
        pid, cid = box[0], box[1]
        cls_name = self._class_name_by_id(cid)
        person_name = self._person_name_by_id(pid)
        self.lbl_selected_box.config(
            text=(f"Box {self.selected_box_index + 1}/{len(self.boxes)}\n"
                  f"Person [{pid}] {person_name}\n"
                  f"Class  [{cid}] {cls_name}\n"
                  f"Class checkpoint: {self._format_checkpoint(self.class_checkpoint_index)}\n"
                  f"Person checkpoint: {self._format_checkpoint(self.person_checkpoint_index)}")
        )

    # ---------------------------------------------------------------- save
    def save_current(self, silent=False):
        if not self.image_files:
            return
        filename = self.image_files[self.current_index]
        label_name = os.path.splitext(filename)[0] + ".txt"

        path_cls = os.path.join(self.label_dir, label_name)
        path_pid = os.path.join(self.label_pid_dir, label_name)

        try:
            os.makedirs(self.label_dir, exist_ok=True)
            os.makedirs(self.label_pid_dir, exist_ok=True)

            # 5-col: class_id cx cy w h
            with open(path_cls, "w", encoding="utf-8") as f:
                for box in self.boxes:
                    pid, cid, cx, cy, bw, bh = box
                    f.write(f"{int(cid)} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")

            # 6-col: person_id class_id cx cy w h
            with open(path_pid, "w", encoding="utf-8") as f:
                for box in self.boxes:
                    pid, cid, cx, cy, bw, bh = box
                    f.write(f"{int(pid)} {int(cid)} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")

            if not silent:
                self.lbl_status.config(text=f"Saved {label_name} (2 formats)", fg=self.colors["status_success"])
                self.root.after(2000, lambda: self.lbl_status.config(
                    text=f"Image {self.current_index + 1}/{len(self.image_files)}",
                    fg=self.colors['text_dim']))
        except Exception as e:
            if not silent:
                messagebox.showerror("Error", f"Failed to save: {e}")

    # ---------------------------------------------------------------- help
    def show_help(self):
        cls_lines = "\n".join([f"   [{key}] id={cid:<2} {name}"
                               for cid, name, key in self.classes]) or "   (none)"
        pers_lines = "\n".join([f"   [{key}] id={pid:<2} {name}"
                                for pid, name, key in self.persons]) or "   (none)"
        help_text = f"""
YOLO ANNOTATION EDITOR - PANDUAN
=====================================================
MEMULAI
   - "Load Folder" -> pilih folder dataset (root)
   - Struktur yang diharapkan:
       <root>/
           images/
           labels/                  (5 kolom)
           labels_with_person_id/   (6 kolom)
   - Folder labels_*/ akan dibuat otomatis kalau belum ada.

CLASS HOTKEYS (ubah class box terpilih)
{cls_lines}

PERSON HOTKEYS (ubah person_id box terpilih)
{pers_lines}

NAVIGATION & EDITING
   - Left / Right    : prev / next image (tahan untuk cepat)
   - Tab             : cycle bounding box pada gambar
   - Click           : pilih box langsung
   - Ctrl+B          : toggle DRAW mode (manual annotation)
   - Saat draw ON    : klik-drag di gambar untuk buat box baru
   - Esc             : keluar dari DRAW mode
   - Delete / BackSp : hapus bounding box terpilih
   - Ctrl+Z          : undo aksi terakhir (draw / delete / set class / set person)
   - Ctrl+S          : save manual (auto-save aktif)
   - F1              : panduan

MANUAL ANNOTATION
   1. Tekan Ctrl+B (atau klik tombol "Draw Box") untuk masuk DRAW mode.
   2. Klik & drag di area gambar untuk membuat bounding box baru.
   3. Box baru otomatis terpilih - tekan hotkey class (1-0) dan person
      (q,w,e,...) untuk memberi label, sama seperti box biasa.
   4. Tekan Ctrl+B atau Esc lagi untuk keluar dari DRAW mode.

OUTPUT
   - labels/<name>.txt                -> class_id cx cy w h
   - labels_with_person_id/<name>.txt -> person_id class_id cx cy w h
   - labels_with_person_id.yaml       -> metadata mapping di root dataset
   - .annotation_cache.json           -> cache edit (person_id + class_id)

INHERITANCE
   - Class dan person punya checkpoint terpisah.
   - Hotkey class menetapkan class checkpoint.
   - Hotkey person menetapkan person checkpoint.
   - Saat Next image, tiap checkpoint diteruskan ke box overlap terbaik.
   - Jika match PICKED ambigu, border dikosongkan agar tidak salah orang.

CONFIG
   - Mapping class & person ada di {CONFIG_FILENAME}
"""
        messagebox.showinfo("Help - Panduan Penggunaan", help_text)


def _show_splash():
    splash = tk.Tk()
    splash.overrideredirect(True)
    sw, sh = 400, 250
    x = (splash.winfo_screenwidth() - sw) // 2
    y = (splash.winfo_screenheight() - sh) // 2
    splash.geometry(f"{sw}x{sh}+{x}+{y}")
    splash_bg = "#0f172a"
    splash_accent = "#2563eb"
    splash_text = "#f8fafc"
    splash_dim = "#94a3b8"
    splash.configure(bg=splash_bg)
    tk.Label(splash, text="YOLO", font=("Segoe UI", 30, "bold"),
             bg=splash_bg, fg=splash_accent).pack(pady=(34, 2))
    tk.Label(splash, text="Annotation Editor", font=("Segoe UI", 20, "bold"),
             bg=splash_bg, fg=splash_text).pack()
    tk.Label(splash, text="Class and person labeling workspace", font=("Segoe UI", 11),
             bg=splash_bg, fg=splash_dim).pack(pady=(16, 0))
    tk.Label(splash, text="Loading...", font=("Segoe UI", 10),
             bg=splash_bg, fg="#64748b").pack(pady=(10, 0))
    splash.update()
    import time
    time.sleep(1)
    splash.destroy()


if __name__ == "__main__":
    _show_splash()
    root = tk.Tk()
    try:
        root.state('zoomed')
    except tk.TclError:
        pass
    app = AnnotationEditor(root)
    root.mainloop()
