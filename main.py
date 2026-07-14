from __future__ import annotations

import csv
import math
import re
import sqlite3
from datetime import datetime
from io import StringIO
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import NumericProperty, StringProperty
from kivy.utils import escape_markup, platform
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

if platform == "android":
    from android.runnable import run_on_ui_thread
else:
    def run_on_ui_thread(function):
        return function


def create_android_recognition_listener(
    on_ready, on_results, on_partial_results, on_error, on_end
):
    """Build a Java RecognitionListener without importing PyJNIus on desktop."""
    from jnius import PythonJavaClass, java_method

    class AndroidRecognitionListener(PythonJavaClass):
        __javainterfaces__ = ["android/speech/RecognitionListener"]
        __javacontext__ = "app"

        def __init__(self):
            super().__init__()

        @staticmethod
        def _phrases(bundle):
            if bundle is None:
                return []
            matches = bundle.getStringArrayList("results_recognition")
            if matches is None:
                return []
            return [str(matches.get(index)) for index in range(matches.size())]

        @java_method("(Landroid/os/Bundle;)V")
        def onReadyForSpeech(self, _params):
            on_ready()

        @java_method("()V")
        def onBeginningOfSpeech(self):
            pass

        @java_method("(F)V")
        def onRmsChanged(self, _rms_db):
            pass

        @java_method("([B)V")
        def onBufferReceived(self, _buffer):
            pass

        @java_method("()V")
        def onEndOfSpeech(self):
            on_end()

        @java_method("(I)V")
        def onError(self, error_code):
            on_error(error_code)

        @java_method("(Landroid/os/Bundle;)V")
        def onResults(self, bundle):
            on_results(self._phrases(bundle))

        @java_method("(Landroid/os/Bundle;)V")
        def onPartialResults(self, bundle):
            on_partial_results(self._phrases(bundle))

        @java_method("(ILandroid/os/Bundle;)V")
        def onEvent(self, _event_type, _params):
            pass

    return AndroidRecognitionListener()


class MangoRecorder(BoxLayout):
    VOICE_DELETE_COMMANDS = {"delete last record", "delete the last record"}
    VOICE_NEXT_FIELD_COMMANDS = {"next field"}
    VOICE_NEXT_FRUIT_COMMANDS = {"next fruit", "save and next", "save next"}
    VOICE_STOP_COMMANDS = {"stop listening", "stop voice", "voice off"}

    record_count = NumericProperty(0)
    status_text = StringProperty("Ready")

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=dp(12), spacing=dp(8), **kwargs)
        self.app = App.get_running_app()
        self.db_path = Path(self.app.user_data_dir) / "mango_lwt.sqlite3"
        self.download_dir = self._download_dir()
        self._voice_delete_pending = False
        self._typed_command_pending = False
        self._voice_starting = False
        self._voice_permission_pending = False
        self._voice_control_enabled = False
        self._speech_listening = False
        self._speech_recognizer = None
        self._speech_intent = None
        self._speech_listener = None
        self._speech_error_count = 0
        self._voice_restart_event = None
        self._audio_permission_callback = None
        self._focused_data_index = 0
        self._updating_worksheet_spinner = False
        self._init_database()
        self._load_active_worksheet()
        self._build_ui()
        self._refresh_count()
        Clock.schedule_once(lambda _dt: setattr(self.block_input, "focus", True), 0.4)
        Clock.schedule_once(lambda _dt: self._request_storage_permissions(), 0.8)

    def _init_database(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("PRAGMA foreign_keys = ON")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS worksheets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worksheet_id INTEGER NOT NULL REFERENCES worksheets(id),
                    block TEXT,
                    tree_id TEXT,
                    panicle_id TEXT,
                    l REAL,
                    w REAL,
                    t REAL,
                    weight REAL,
                    brix REAL,
                    recorded_at TEXT NOT NULL
                )
                """
            )

            columns = {
                row[1] for row in con.execute("PRAGMA table_info(measurements)")
            }
            if "worksheet_id" not in columns:
                con.execute(
                    "ALTER TABLE measurements ADD COLUMN worksheet_id INTEGER "
                    "REFERENCES worksheets(id)"
                )
            if "weight" not in columns:
                con.execute("ALTER TABLE measurements ADD COLUMN weight REAL")
            if "brix" not in columns:
                con.execute("ALTER TABLE measurements ADD COLUMN brix REAL")

            default_row = con.execute(
                "SELECT id FROM worksheets ORDER BY id LIMIT 1"
            ).fetchone()
            if default_row is None:
                cursor = con.execute(
                    "INSERT INTO worksheets (name, created_at) VALUES (?, ?)",
                    ("Worksheet 1", self._timestamp()),
                )
                default_worksheet_id = cursor.lastrowid
            else:
                default_worksheet_id = default_row[0]

            # Migrate records created by versions that pre-date worksheets.
            con.execute(
                "UPDATE measurements SET worksheet_id = ? "
                "WHERE worksheet_id IS NULL",
                (default_worksheet_id,),
            )

            active_row = con.execute(
                """
                SELECT w.id
                FROM settings AS s
                JOIN worksheets AS w ON CAST(w.id AS TEXT) = s.value
                WHERE s.key = 'active_worksheet_id'
                """
            ).fetchone()
            active_worksheet_id = (
                active_row[0] if active_row is not None else default_worksheet_id
            )
            con.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                ("active_worksheet_id", str(active_worksheet_id)),
            )
            con.commit()

    @staticmethod
    def _timestamp():
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _record_description(block, tree_id, panicle_id):
        parts = []
        if block:
            parts.append(f"Block {block}")
        if tree_id:
            parts.append(f"Tree {tree_id}")
        if panicle_id:
            parts.append(f"Panicle {panicle_id}")
        return " / ".join(parts) if parts else "partial record"

    def _load_active_worksheet(self):
        with sqlite3.connect(self.db_path) as con:
            row = con.execute(
                """
                SELECT w.id, w.name
                FROM worksheets AS w
                JOIN settings AS s ON s.value = CAST(w.id AS TEXT)
                WHERE s.key = 'active_worksheet_id'
                """
            ).fetchone()
            if row is None:
                row = con.execute(
                    "SELECT id, name FROM worksheets ORDER BY id LIMIT 1"
                ).fetchone()

        self.active_worksheet_id, self.active_worksheet_name = row

    def _field(self, hint, multiline=False, input_filter=None):
        field = TextInput(
            hint_text=hint,
            multiline=multiline,
            input_filter=input_filter,
            font_size="22sp",
            size_hint_y=None,
            height=dp(54),
            padding=[dp(12), dp(12), dp(12), dp(8)],
            write_tab=False,
        )
        return field

    def _build_ui(self):
        title = Label(
            text="[b]Mango LWT Recorder[/b]",
            markup=True,
            font_size="26sp",
            size_hint_y=None,
            height=dp(46),
        )
        self.add_widget(title)

        subtitle = Label(
            text="Offline field data collection",
            font_size="15sp",
            size_hint_y=None,
            height=dp(28),
        )
        self.add_widget(subtitle)

        worksheet_bar = BoxLayout(
            orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(50)
        )
        worksheet_label = Label(
            text="[b]Worksheet[/b]",
            markup=True,
            font_size="17sp",
            size_hint_x=0.25,
        )
        self.worksheet_spinner = Spinner(
            text=self.active_worksheet_name,
            font_size="17sp",
            size_hint_x=0.43,
        )
        self.worksheet_spinner.bind(text=self._switch_worksheet)
        new_worksheet_btn = Button(
            text="NEW", font_size="17sp", size_hint_x=0.32
        )
        new_worksheet_btn.bind(
            on_release=lambda *_: self.show_new_worksheet_dialog()
        )
        worksheet_bar.add_widget(worksheet_label)
        worksheet_bar.add_widget(self.worksheet_spinner)
        worksheet_bar.add_widget(new_worksheet_btn)
        self.add_widget(worksheet_bar)
        self._refresh_worksheet_selector()

        scroll = ScrollView()
        form = GridLayout(cols=2, spacing=dp(8), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        self.block_input = self._field("e.g. B15")
        self.tree_input = self._field("e.g. 12")
        self.panicle_input = self._field("e.g. 1")
        self.l_input = self._field("Length (mm)", input_filter="float")
        self.w_input = self._field("Width (mm)", input_filter="float")
        self.t_input = self._field("Thickness (mm)", input_filter="float")
        self.weight_input = self._field("Weight (g)", input_filter="float")
        self.brix_input = self._field("Brix (degrees)", input_filter="float")
        self.voice_command_input = self._field("Type/dictate command")
        self.voice_command_input.font_size = "14sp"
        self.voice_command_input.size_hint_x = 0.58
        self.voice_command_input.bind(text=self._on_voice_command_text)
        self.voice_command_input.bind(on_text_validate=self._submit_voice_command)
        self.voice_toggle_btn = Button(
            text="START VOICE", font_size="13sp", size_hint_x=0.42
        )
        self.voice_toggle_btn.bind(on_release=lambda *_: self.toggle_voice_control())
        voice_controls = BoxLayout(
            orientation="horizontal", spacing=dp(6), size_hint_y=None, height=dp(54)
        )
        voice_controls.add_widget(self.voice_command_input)
        voice_controls.add_widget(self.voice_toggle_btn)

        rows = [
            ("Block", self.block_input),
            ("TreeID", self.tree_input),
            ("PanicleID", self.panicle_input),
            ("L (mm)", self.l_input),
            ("W (mm)", self.w_input),
            ("T (mm)", self.t_input),
            ("Weight (g)", self.weight_input),
            ("Brix (°)", self.brix_input),
            ("Voice control", voice_controls),
        ]
        for text, widget in rows:
            label = Label(
                text=f"[b]{text}[/b]",
                markup=True,
                font_size="18sp",
                size_hint_y=None,
                height=dp(54),
                halign="left",
                valign="middle",
            )
            label.bind(size=lambda inst, value: setattr(inst, "text_size", value))
            form.add_widget(label)
            form.add_widget(widget)

        scroll.add_widget(form)
        self.add_widget(scroll)

        # Return/Next on the software keyboard advances through fields.
        focus_order = [
            self.block_input,
            self.tree_input,
            self.panicle_input,
            self.l_input,
            self.w_input,
            self.t_input,
            self.weight_input,
            self.brix_input,
        ]
        self.data_fields = focus_order
        self.data_field_names = [
            "Block",
            "TreeID",
            "PanicleID",
            "L",
            "W",
            "T",
            "Weight",
            "Brix",
        ]
        for index, field in enumerate(focus_order):
            field.bind(
                on_text_validate=lambda _field, i=index:
                self._advance_or_save(i, focus_order)
            )
            field.bind(
                focus=lambda _field, focused, i=index:
                self._remember_focused_field(i, focused)
            )

        buttons = GridLayout(cols=2, spacing=dp(8), size_hint_y=None, height=dp(116))
        save_btn = Button(text="SAVE & NEXT", font_size="20sp")
        save_btn.bind(on_release=lambda *_: self.save_record())

        undo_btn = Button(text="UNDO LAST", font_size="18sp")
        undo_btn.bind(on_release=lambda *_: self.undo_last())

        export_btn = Button(text="EXPORT CSV", font_size="18sp")
        export_btn.bind(on_release=lambda *_: self.export_csv())

        clear_btn = Button(text="CLEAR FORM", font_size="18sp")
        clear_btn.bind(on_release=lambda *_: self.clear_measurements())

        for btn in (save_btn, undo_btn, export_btn, clear_btn):
            buttons.add_widget(btn)
        self.add_widget(buttons)

        delete_all_btn = Button(
            text="DELETE ALL HISTORY",
            font_size="17sp",
            size_hint_y=None,
            height=dp(50),
        )
        delete_all_btn.bind(on_release=lambda *_: self.request_delete_all_history())
        self.add_widget(delete_all_btn)

        self.status = Label(
            text=self._status_markup(),
            markup=True,
            size_hint_y=None,
            height=dp(62),
            font_size="15sp",
            halign="center",
            valign="middle",
        )
        self.status.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        self.add_widget(self.status)

    def _advance_or_save(self, index, fields):
        fields[index].focus = False
        if index < len(fields) - 1:
            fields[index + 1].focus = True
        else:
            self.save_record()

    def _status_markup(self):
        status = escape_markup(self.status_text)
        worksheet = escape_markup(self.active_worksheet_name)
        return (
            f"[b]{status}[/b]\n"
            f"Worksheet: {worksheet} | Saved records: {self.record_count}"
        )

    def _set_status(self, message):
        self.status_text = message
        self.status.text = self._status_markup()

    def _refresh_count(self):
        with sqlite3.connect(self.db_path) as con:
            self.record_count = con.execute(
                "SELECT COUNT(*) FROM measurements WHERE worksheet_id = ?",
                (self.active_worksheet_id,),
            ).fetchone()[0]
        if hasattr(self, "status"):
            self.status.text = self._status_markup()

    def _worksheet_rows(self):
        with sqlite3.connect(self.db_path) as con:
            return con.execute(
                "SELECT id, name FROM worksheets ORDER BY id"
            ).fetchall()

    def _refresh_worksheet_selector(self):
        rows = self._worksheet_rows()
        self._worksheet_ids_by_name = {name: worksheet_id for worksheet_id, name in rows}
        self._updating_worksheet_spinner = True
        self.worksheet_spinner.values = tuple(name for _, name in rows)
        self.worksheet_spinner.text = self.active_worksheet_name
        self._updating_worksheet_spinner = False

    def _switch_worksheet(self, _spinner, worksheet_name):
        if self._updating_worksheet_spinner:
            return

        worksheet_id = self._worksheet_ids_by_name.get(worksheet_name)
        if worksheet_id is None or worksheet_id == self.active_worksheet_id:
            return

        self.active_worksheet_id = worksheet_id
        self.active_worksheet_name = worksheet_name
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                ("active_worksheet_id", str(worksheet_id)),
            )
            con.commit()

        self.clear_all_fields()
        self._refresh_count()
        self._set_status(f"Switched to {worksheet_name}")

    def _next_worksheet_name(self):
        existing = {name.casefold() for _, name in self._worksheet_rows()}
        number = 1
        while f"worksheet {number}" in existing:
            number += 1
        return f"Worksheet {number}"

    def show_new_worksheet_dialog(self):
        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        prompt = Label(
            text="Name the new worksheet. Existing worksheets will be preserved.",
            halign="center",
            valign="middle",
        )
        prompt.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        name_input = self._field("Worksheet name")
        name_input.text = self._next_worksheet_name()
        actions = BoxLayout(
            orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(48)
        )
        cancel = Button(text="CANCEL")
        create = Button(text="CREATE")
        actions.add_widget(cancel)
        actions.add_widget(create)
        content.add_widget(prompt)
        content.add_widget(name_input)
        content.add_widget(actions)
        popup = Popup(
            title="New worksheet", content=content, size_hint=(0.9, 0.52)
        )

        def create_from_input(*_args):
            try:
                self.create_worksheet(name_input.text)
            except ValueError as exc:
                popup.dismiss()
                self._show_message("Cannot create worksheet", str(exc))
                return
            popup.dismiss()

        cancel.bind(on_release=popup.dismiss)
        create.bind(on_release=create_from_input)
        name_input.bind(on_text_validate=create_from_input)
        popup.open()
        Clock.schedule_once(lambda _dt: setattr(name_input, "focus", True), 0.2)

    def create_worksheet(self, worksheet_name):
        name = " ".join(worksheet_name.strip().split())
        if not name:
            raise ValueError("Enter a worksheet name.")
        if len(name) > 60:
            raise ValueError("Worksheet names must be 60 characters or fewer.")

        with sqlite3.connect(self.db_path) as con:
            duplicate = con.execute(
                "SELECT 1 FROM worksheets WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
            if duplicate is not None:
                raise ValueError("A worksheet with that name already exists.")
            cursor = con.execute(
                "INSERT INTO worksheets (name, created_at) VALUES (?, ?)",
                (name, self._timestamp()),
            )
            worksheet_id = cursor.lastrowid
            con.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                ("active_worksheet_id", str(worksheet_id)),
            )
            con.commit()

        self.active_worksheet_id = worksheet_id
        self.active_worksheet_name = name
        self.clear_all_fields()
        self._refresh_worksheet_selector()
        self._refresh_count()
        self._set_status(f"Created {name}")

    def _download_dir(self):
        if platform == "android":
            return Path("/storage/emulated/0/Download")
        return Path.home() / "Downloads"

    def _request_storage_permissions(self):
        if platform != "android":
            return

        try:
            from android.permissions import Permission, request_permissions
        except ImportError:
            return

        permissions = [
            permission
            for permission in (
                getattr(Permission, "READ_EXTERNAL_STORAGE", None),
                getattr(Permission, "WRITE_EXTERNAL_STORAGE", None),
            )
            if permission
        ]
        if permissions:
            request_permissions(permissions)

    def _values(self):
        block = self.block_input.text.strip()
        tree_id = self.tree_input.text.strip()
        panicle_id = self.panicle_input.text.strip()

        raw_numbers = {
            "L": self.l_input.text.strip(),
            "W": self.w_input.text.strip(),
            "T": self.t_input.text.strip(),
            "Weight": self.weight_input.text.strip(),
            "Brix": self.brix_input.text.strip(),
        }
        if not any((block, tree_id, panicle_id, *raw_numbers.values())):
            raise ValueError("Enter at least one value before saving.")

        def optional_number(name):
            raw_value = raw_numbers[name]
            if not raw_value:
                # An empty string is compatible with both new nullable columns and
                # legacy databases whose original L/W/T columns were NOT NULL.
                return ""
            try:
                value = float(raw_value)
            except ValueError as exc:
                raise ValueError(f"{name} must be a valid number.") from exc
            if not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number.")
            return value

        l_val = optional_number("L")
        w_val = optional_number("W")
        t_val = optional_number("T")
        weight_val = optional_number("Weight")
        brix_val = optional_number("Brix")

        for name, value in (("L", l_val), ("W", w_val), ("T", t_val)):
            if value != "" and (value <= 0 or value > 300):
                raise ValueError(
                    f"{name} must be greater than 0 and no more than 300 mm."
                )
        if weight_val != "" and weight_val <= 0:
            raise ValueError("Weight must be greater than 0 g.")
        if brix_val != "" and not 0 <= brix_val <= 100:
            raise ValueError("Brix must be between 0 and 100 degrees.")

        return (
            block,
            tree_id,
            panicle_id,
            l_val,
            w_val,
            t_val,
            weight_val,
            brix_val,
        )

    def save_record(self, on_error_dismiss=None):
        try:
            values = self._values()
        except ValueError as exc:
            self._show_message(
                "Check entry", str(exc), on_dismiss=on_error_dismiss
            )
            return False

        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                INSERT INTO measurements
                (worksheet_id, block, tree_id, panicle_id, l, w, t,
                 weight, brix, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (self.active_worksheet_id, *values, self._timestamp()),
            )
            con.commit()

        old_panicle = self.panicle_input.text.strip()
        self.clear_measurements()

        # Auto-increment numeric PanicleID; otherwise retain it for manual editing.
        try:
            self.panicle_input.text = str(int(old_panicle) + 1)
        except ValueError:
            self.panicle_input.text = old_panicle

        self._refresh_count()
        self._set_status(f"Saved {self._record_description(*values[:3])}")
        self.l_input.focus = True
        return True

    def clear_measurements(self):
        self.l_input.text = ""
        self.w_input.text = ""
        self.t_input.text = ""
        self.weight_input.text = ""
        self.brix_input.text = ""
        self.l_input.focus = True

    def clear_all_fields(self):
        for field in (
            self.block_input,
            self.tree_input,
            self.panicle_input,
            self.l_input,
            self.w_input,
            self.t_input,
            self.weight_input,
            self.brix_input,
            self.voice_command_input,
        ):
            field.text = ""
        self.block_input.focus = True

    @staticmethod
    def _normalize_voice_command(command):
        return re.sub(r"[^a-z0-9]+", " ", command.casefold()).strip()

    def _voice_command_action(self, command):
        normalized = self._normalize_voice_command(command)
        if normalized in self.VOICE_DELETE_COMMANDS:
            return "delete"
        if normalized in self.VOICE_NEXT_FIELD_COMMANDS:
            return "next_field"
        if normalized in self.VOICE_NEXT_FRUIT_COMMANDS:
            return "next_fruit"
        if normalized in self.VOICE_STOP_COMMANDS:
            return "stop"
        return None

    def _on_voice_command_text(self, _field, command):
        if self._voice_command_action(command) and not self._typed_command_pending:
            self._typed_command_pending = True
            Clock.schedule_once(
                lambda _dt, phrase=command: self._run_typed_voice_command(phrase),
                0,
            )

    def _submit_voice_command(self, _field):
        if self._typed_command_pending:
            return

        command = self.voice_command_input.text
        if self._voice_command_action(command):
            self._typed_command_pending = True
            self._run_typed_voice_command(command)
            return

        self.voice_command_input.text = ""
        self._show_message(
            "Voice command not recognized",
            "Available commands: next field, next fruit, delete last record, "
            "and stop listening.",
        )

    def _run_typed_voice_command(self, command):
        self.voice_command_input.text = ""
        self._typed_command_pending = False
        self._execute_voice_command(command, continuous=False)

    def _execute_voice_command(self, command, continuous):
        action = self._voice_command_action(command)
        if action == "next_field":
            self.move_to_next_field()
            if continuous:
                self._schedule_voice_restart()
            return True
        if action == "next_fruit":
            resume = self._schedule_voice_restart if continuous else None
            saved = self.save_record(on_error_dismiss=resume)
            if saved and continuous:
                self._schedule_voice_restart()
            return True
        if action == "delete":
            if self._voice_delete_pending:
                return True
            self._voice_delete_pending = True
            self.request_voice_delete(resume_voice=continuous)
            return True
        if action == "stop":
            self.stop_voice_control()
            return True
        return False

    def _remember_focused_field(self, index, focused):
        if focused:
            self._focused_data_index = index

    def move_to_next_field(self):
        index = min(self._focused_data_index, len(self.data_fields) - 1)
        if index >= len(self.data_fields) - 1:
            self._set_status('Brix is the last field; say "next fruit" to save')
            return False

        self.data_fields[index].focus = False
        self._focused_data_index = index + 1
        self.data_fields[self._focused_data_index].focus = True
        self._set_status(
            f"Voice moved to {self.data_field_names[self._focused_data_index]}"
        )
        return True

    @staticmethod
    def _spoken_number(text):
        compact = text.strip().replace(",", "")
        if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", compact):
            value = float(compact)
            return format(value, ".12g") if math.isfinite(value) else None

        tokens = re.findall(r"[a-z]+|\d+", text.casefold())
        if not tokens:
            return None

        sign = -1 if tokens and tokens[0] in {"minus", "negative"} else 1
        if sign == -1:
            tokens = tokens[1:]

        if "point" in tokens:
            point_index = tokens.index("point")
            whole_tokens = tokens[:point_index]
            decimal_tokens = tokens[point_index + 1:]
        else:
            whole_tokens = tokens
            decimal_tokens = []

        small = {
            "zero": 0,
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "eleven": 11,
            "twelve": 12,
            "thirteen": 13,
            "fourteen": 14,
            "fifteen": 15,
            "sixteen": 16,
            "seventeen": 17,
            "eighteen": 18,
            "nineteen": 19,
            "twenty": 20,
            "thirty": 30,
            "forty": 40,
            "fifty": 50,
            "sixty": 60,
            "seventy": 70,
            "eighty": 80,
            "ninety": 90,
        }

        total = 0
        current = 0
        for token in whole_tokens or ["zero"]:
            if token == "and":
                continue
            if token.isdigit():
                current += int(token)
            elif token in small:
                current += small[token]
            elif token == "hundred":
                current = max(current, 1) * 100
            elif token == "thousand":
                total += max(current, 1) * 1000
                current = 0
            else:
                return None
        whole = total + current

        decimal_digits = ""
        digit_words = {word: str(number) for word, number in small.items() if number < 10}
        for token in decimal_tokens:
            if token.isdigit():
                decimal_digits += token
            elif token in digit_words:
                decimal_digits += digit_words[token]
            else:
                return None

        value = float(f"{whole}.{decimal_digits}") if decimal_digits else float(whole)
        return format(sign * value, ".12g")

    def _enter_spoken_value(self, phrase):
        index = min(self._focused_data_index, len(self.data_fields) - 1)
        if index < 3:
            value = phrase.strip()
        else:
            value = self._spoken_number(phrase)
            if value is None:
                self._set_status(
                    f'Could not enter "{phrase}" in {self.data_field_names[index]}'
                )
                return False

        self.data_fields[index].text = value
        self._set_status(f"Voice entered {value} in {self.data_field_names[index]}")
        return True

    def toggle_voice_control(self):
        if platform != "android":
            self.voice_command_input.focus = True
            self._show_message(
                "Android voice control",
                "Continuous voice sessions require the Android APK. On this "
                "platform, type or dictate a command in the Voice control field.",
            )
            return
        if self._voice_control_enabled:
            self.stop_voice_control()
            return
        if self._voice_starting or self._voice_permission_pending:
            return
        self._request_audio_permission()

    def _request_audio_permission(self):
        from android.permissions import (
            Permission,
            check_permission,
            request_permissions,
        )

        if check_permission(Permission.RECORD_AUDIO):
            self._voice_starting = True
            self._start_android_voice_control()
            return

        def permission_result(_permissions, grants):
            granted = bool(grants) and all(grants)
            self._voice_starting = granted
            self._voice_permission_pending = False
            self._audio_permission_callback = None
            Clock.schedule_once(
                lambda _dt: self._after_audio_permission(granted), 0
            )

        # Keep a strong reference until Android returns the permission result.
        self._voice_permission_pending = True
        self._audio_permission_callback = permission_result
        request_permissions([Permission.RECORD_AUDIO], permission_result)

    def _after_audio_permission(self, granted):
        if granted and self._voice_starting:
            self._start_android_voice_control()
        else:
            self._voice_starting = False
            if not granted:
                self._show_message(
                    "Microphone permission required",
                    "Allow microphone access in Android Settings to use voice control.",
                )

    @run_on_ui_thread
    def _start_android_voice_control(self):
        from jnius import autoclass

        SpeechRecognizer = autoclass("android.speech.SpeechRecognizer")
        RecognizerIntent = autoclass("android.speech.RecognizerIntent")
        Intent = autoclass("android.content.Intent")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")

        activity = PythonActivity.mActivity
        if not SpeechRecognizer.isRecognitionAvailable(activity):
            Clock.schedule_once(
                lambda _dt: self._voice_control_start_failed(
                    "This device has no compatible Android speech recognition service."
                ),
                0,
            )
            return

        try:
            if self._speech_recognizer is None:
                self._speech_recognizer = (
                    SpeechRecognizer.createSpeechRecognizer(activity)
                )
                self._speech_listener = create_android_recognition_listener(
                    lambda: Clock.schedule_once(
                        lambda _dt: self._on_speech_ready(), 0
                    ),
                    lambda phrases: Clock.schedule_once(
                        lambda _dt, values=tuple(phrases):
                        self._on_speech_results(values),
                        0,
                    ),
                    lambda phrases: Clock.schedule_once(
                        lambda _dt, values=tuple(phrases):
                        self._on_speech_partial_results(values),
                        0,
                    ),
                    lambda error_code: Clock.schedule_once(
                        lambda _dt, code=error_code: self._on_speech_error(code),
                        0,
                    ),
                    lambda: Clock.schedule_once(
                        lambda _dt: self._on_speech_end(), 0
                    ),
                )
                self._speech_recognizer.setRecognitionListener(
                    self._speech_listener
                )

                self._speech_intent = Intent(
                    RecognizerIntent.ACTION_RECOGNIZE_SPEECH
                )
                self._speech_intent.putExtra(
                    RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                    RecognizerIntent.LANGUAGE_MODEL_FREE_FORM,
                )
                self._speech_intent.putExtra(
                    RecognizerIntent.EXTRA_LANGUAGE, "en-AU"
                )
                self._speech_intent.putExtra(
                    RecognizerIntent.EXTRA_PARTIAL_RESULTS, True
                )
                self._speech_intent.putExtra(
                    RecognizerIntent.EXTRA_MAX_RESULTS, 3
                )
        except Exception as exc:
            message = str(exc)
            Clock.schedule_once(
                lambda _dt, detail=message:
                self._voice_control_start_failed(detail),
                0,
            )
            return

        Clock.schedule_once(
            lambda _dt: self._finish_android_voice_control_start(), 0
        )

    def _finish_android_voice_control_start(self):
        if not self._voice_starting:
            self._stop_android_recognizer(True)
            return
        self._voice_starting = False
        self._voice_control_enabled = True
        self.voice_toggle_btn.text = "STOP VOICE"
        self._set_status(
            'Voice control on; speak a value, "next field", or "next fruit"'
        )
        self._start_speech_cycle()

    def _voice_control_start_failed(self, message):
        self._voice_starting = False
        self._voice_control_enabled = False
        self.voice_toggle_btn.text = "START VOICE"
        self._show_message("Voice control unavailable", message)

    @run_on_ui_thread
    def _start_speech_cycle(self, _dt=0):
        self._voice_restart_event = None
        if not self._voice_control_enabled or self._speech_recognizer is None:
            return
        try:
            self._speech_recognizer.startListening(self._speech_intent)
            self._speech_listening = True
        except Exception as exc:
            self._speech_listening = False
            message = str(exc)
            Clock.schedule_once(
                lambda _delay, detail=message:
                self._speech_cycle_start_failed(detail),
                0,
            )

    def _speech_cycle_start_failed(self, message):
        self.stop_voice_control()
        self._show_message(
            "Voice control stopped",
            f"Could not start speech recognition:\n{message}",
        )

    def _schedule_voice_restart(self, delay=0.45):
        if not self._voice_control_enabled:
            return
        if self._voice_restart_event is not None:
            self._voice_restart_event.cancel()
        self._voice_restart_event = Clock.schedule_once(
            self._start_speech_cycle, delay
        )

    def _on_speech_ready(self):
        if self._voice_control_enabled:
            self._set_status("Voice listening...")

    def _on_speech_end(self):
        self._speech_listening = False
        if self._voice_control_enabled:
            self._set_status("Voice processing...")

    def _on_speech_partial_results(self, _phrases):
        pass

    def _on_speech_results(self, phrases):
        self._speech_listening = False
        if not self._voice_control_enabled:
            return
        self._speech_error_count = 0

        if phrases:
            top_phrase = phrases[0]
            if self._voice_command_action(top_phrase):
                self._execute_voice_command(top_phrase, continuous=True)
                return
            self._enter_spoken_value(top_phrase)
        else:
            self._set_status("No speech recognized; listening again")
        self._schedule_voice_restart()

    def _on_speech_error(self, error_code):
        self._speech_listening = False
        if not self._voice_control_enabled:
            return

        # 6 = speech timeout, 7 = no match. Both are normal during silence.
        if error_code in (6, 7):
            self._schedule_voice_restart(0.6)
            return
        # 9 = insufficient permission.
        if error_code == 9:
            self.stop_voice_control()
            self._show_message(
                "Voice control stopped", "Microphone permission was denied."
            )
            return

        self._speech_error_count += 1
        if self._speech_error_count >= 3:
            self.stop_voice_control()
            self._show_message(
                "Voice control stopped",
                f"Speech recognition repeatedly failed (error {error_code}).",
            )
            return

        self._set_status(f"Speech recognition error {error_code}; retrying")
        self._schedule_voice_restart(1.0)

    def stop_voice_control(self, destroy=False):
        self._voice_starting = False
        self._voice_permission_pending = False
        self._voice_control_enabled = False
        if self._voice_restart_event is not None:
            self._voice_restart_event.cancel()
            self._voice_restart_event = None
        self._stop_android_recognizer(destroy)
        self._speech_listening = False
        if hasattr(self, "voice_toggle_btn"):
            self.voice_toggle_btn.text = "START VOICE"
        if hasattr(self, "status"):
            self._set_status("Voice control stopped")

    @run_on_ui_thread
    def _stop_android_recognizer(self, destroy=False):
        if self._speech_recognizer is None:
            return
        try:
            self._speech_recognizer.cancel()
        except Exception:
            pass
        if destroy:
            try:
                self._speech_recognizer.destroy()
            except Exception:
                pass
            self._speech_recognizer = None
            self._speech_listener = None
            self._speech_intent = None

    def _last_record(self):
        with sqlite3.connect(self.db_path) as con:
            return con.execute(
                """
                SELECT id, block, tree_id, panicle_id
                FROM measurements
                WHERE worksheet_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (self.active_worksheet_id,),
            ).fetchone()

    def _delete_record(self, record_id):
        with sqlite3.connect(self.db_path) as con:
            cursor = con.execute(
                "DELETE FROM measurements WHERE id = ? AND worksheet_id = ?",
                (record_id, self.active_worksheet_id),
            )
            con.commit()
        return cursor.rowcount > 0

    def undo_last(self):
        row = self._last_record()
        if not row:
            self._show_message("Undo", "There is no saved record to remove.")
            return
        self._delete_record(row[0])

        self._refresh_count()
        self._set_status(f"Removed {self._record_description(*row[1:])}")

    def request_voice_delete(self, resume_voice=False):
        self.voice_command_input.text = ""
        self.voice_command_input.focus = False
        row = self._last_record()
        if row is None:
            self._voice_delete_pending = False
            self._show_message(
                "Voice delete",
                "There is no saved record in this worksheet.",
                on_dismiss=(
                    self._schedule_voice_restart if resume_voice else None
                ),
            )
            return

        message = (
            "Delete the last record?\n\n"
            f"{self._record_description(*row[1:])}\n\n"
            "This action cannot be undone."
        )
        self._show_confirmation(
            "Confirm voice delete",
            message,
            "DELETE",
            lambda: self._confirm_voice_delete(row),
            on_dismiss=lambda: self._finish_voice_delete(resume_voice),
        )

    def _finish_voice_delete(self, resume_voice):
        self._voice_delete_pending = False
        if resume_voice:
            self._schedule_voice_restart()

    def _confirm_voice_delete(self, row):
        if not self._delete_record(row[0]):
            self._show_message(
                "Voice delete", "That record has already been removed."
            )
            return
        self._refresh_count()
        self._set_status(
            f"Voice deleted {self._record_description(*row[1:])}"
        )

    def request_delete_all_history(self):
        with sqlite3.connect(self.db_path) as con:
            record_total = con.execute(
                "SELECT COUNT(*) FROM measurements"
            ).fetchone()[0]
            worksheet_total = con.execute(
                "SELECT COUNT(*) FROM worksheets"
            ).fetchone()[0]

        if record_total == 0 and worksheet_total == 1:
            self._show_message("Delete all history", "There is no history to delete.")
            return

        self._show_confirmation(
            "Delete all history",
            (
                f"Permanently delete {record_total} saved record(s) across "
                f"{worksheet_total} worksheet(s)?\n\n"
                "All worksheets will be removed and a new empty Worksheet 1 "
                "will be created. This action cannot be undone."
            ),
            "DELETE ALL",
            self.delete_all_history,
        )

    def delete_all_history(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("PRAGMA foreign_keys = ON")
            con.execute("DELETE FROM measurements")
            con.execute("DELETE FROM worksheets")
            cursor = con.execute(
                "INSERT INTO worksheets (name, created_at) VALUES (?, ?)",
                ("Worksheet 1", self._timestamp()),
            )
            worksheet_id = cursor.lastrowid
            con.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                ("active_worksheet_id", str(worksheet_id)),
            )
            con.commit()

        self.active_worksheet_id = worksheet_id
        self.active_worksheet_name = "Worksheet 1"
        self.clear_all_fields()
        self._refresh_worksheet_selector()
        self._refresh_count()
        self._set_status("All history deleted")

    def export_csv(self):
        worksheet_name = re.sub(
            r"[^\w.-]+", "_", self.active_worksheet_name, flags=re.UNICODE
        ).strip("._") or "worksheet"
        filename = (
            f"mango_lwt_{worksheet_name}_{datetime.now():%Y%m%d_%H%M%S}.csv"
        )
        try:
            csv_text = self._csv_text()
            if platform == "android":
                output_path = self._write_android_download(filename, csv_text)
            else:
                output_path = self._write_download_file(filename, csv_text)
        except Exception as exc:
            self._set_status("CSV export failed")
            self._show_message(
                "CSV export failed",
                f"Could not save to Downloads:\n{exc}",
            )
            return

        self._set_status(f"CSV exported: {filename}")
        self._show_message(
            "CSV exported",
            f"Saved to Downloads:\n{output_path}",
        )

    def _csv_text(self):
        output = StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(
            [
                "Block",
                "TreeID",
                "PanicleID",
                "L",
                "W",
                "T",
                "Weight",
                "Brix",
                "Timestamp",
            ]
        )

        with sqlite3.connect(self.db_path) as con:
            writer.writerows(
                con.execute(
                    """
                    SELECT block, tree_id, panicle_id, l, w, t,
                           weight, brix, recorded_at
                    FROM measurements
                    WHERE worksheet_id = ?
                    ORDER BY id
                    """,
                    (self.active_worksheet_id,),
                )
            )

        return output.getvalue()

    def _write_download_file(self, filename, csv_text):
        self.download_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.download_dir / filename
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            handle.write(csv_text)
        return output_path

    def _write_android_download(self, filename, csv_text):
        from jnius import autoclass

        BuildVersion = autoclass("android.os.Build$VERSION")
        if BuildVersion.SDK_INT < 29:
            return self._write_download_file(filename, csv_text)

        ContentValues = autoclass("android.content.ContentValues")
        Downloads = autoclass("android.provider.MediaStore$Downloads")
        MediaColumns = autoclass("android.provider.MediaStore$MediaColumns")
        Environment = autoclass("android.os.Environment")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")

        activity = PythonActivity.mActivity
        resolver = activity.getContentResolver()
        values = ContentValues()
        values.put(MediaColumns.DISPLAY_NAME, filename)
        values.put(MediaColumns.MIME_TYPE, "text/csv")
        values.put(MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)

        uri = resolver.insert(Downloads.EXTERNAL_CONTENT_URI, values)
        if uri is None:
            raise OSError("Android could not create a file in Downloads.")

        stream = None
        try:
            stream = resolver.openOutputStream(uri)
            if stream is None:
                raise OSError("Android could not open the Downloads file.")
            stream.write(csv_text.encode("utf-8"))
        except Exception:
            try:
                resolver.delete(uri, None, None)
            except Exception:
                pass
            raise
        finally:
            if stream is not None:
                stream.close()

        return self.download_dir / filename

    def _show_message(self, title, message, on_dismiss=None):
        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        label = Label(text=message, halign="center", valign="middle")
        label.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        close = Button(text="OK", size_hint_y=None, height=dp(48))
        content.add_widget(label)
        content.add_widget(close)
        popup = Popup(title=title, content=content, size_hint=(0.88, 0.48))
        close.bind(on_release=popup.dismiss)
        if on_dismiss is not None:
            popup.bind(on_dismiss=lambda *_: on_dismiss())
        popup.open()
        return popup

    def _show_confirmation(
        self, title, message, confirm_text, on_confirm, on_dismiss=None
    ):
        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        label = Label(text=message, halign="center", valign="middle")
        label.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        actions = BoxLayout(
            orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(48)
        )
        cancel = Button(text="CANCEL")
        confirm = Button(text=confirm_text)
        actions.add_widget(cancel)
        actions.add_widget(confirm)
        content.add_widget(label)
        content.add_widget(actions)
        popup = Popup(title=title, content=content, size_hint=(0.9, 0.58))

        def confirm_action(*_args):
            popup.dismiss()
            on_confirm()

        cancel.bind(on_release=popup.dismiss)
        confirm.bind(on_release=confirm_action)
        if on_dismiss is not None:
            popup.bind(on_dismiss=lambda *_: on_dismiss())
        popup.open()


class MangoLWTApp(App):
    title = "Mango LWT Recorder"

    def build(self):
        Window.softinput_mode = "below_target"
        return MangoRecorder()

    def on_pause(self):
        if (
            self.root is not None
            and not self.root._voice_permission_pending
        ):
            self.root.stop_voice_control()
        return True

    def on_stop(self):
        if self.root is not None:
            self.root.stop_voice_control(destroy=True)


if __name__ == "__main__":
    MangoLWTApp().run()
