from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from io import StringIO
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import NumericProperty, StringProperty
from kivy.utils import platform
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput


class MangoRecorder(BoxLayout):
    record_count = NumericProperty(0)
    status_text = StringProperty("Ready")

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=dp(12), spacing=dp(8), **kwargs)
        self.app = App.get_running_app()
        self.db_path = Path(self.app.user_data_dir) / "mango_lwt.sqlite3"
        self.download_dir = self._download_dir()
        self._init_database()
        self._build_ui()
        self._refresh_count()
        Clock.schedule_once(lambda _dt: setattr(self.block_input, "focus", True), 0.4)
        Clock.schedule_once(lambda _dt: self._request_storage_permissions(), 0.8)

    def _init_database(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    block TEXT NOT NULL,
                    tree_id TEXT NOT NULL,
                    panicle_id TEXT NOT NULL,
                    l REAL NOT NULL,
                    w REAL NOT NULL,
                    t REAL NOT NULL,
                    recorded_at TEXT NOT NULL
                )
                """
            )
            con.commit()

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

        scroll = ScrollView()
        form = GridLayout(cols=2, spacing=dp(8), size_hint_y=None)
        form.bind(minimum_height=form.setter("height"))

        self.block_input = self._field("e.g. B15")
        self.tree_input = self._field("e.g. 12")
        self.panicle_input = self._field("e.g. 1")
        self.l_input = self._field("Length (mm)", input_filter="float")
        self.w_input = self._field("Width (mm)", input_filter="float")
        self.t_input = self._field("Thickness (mm)", input_filter="float")

        rows = [
            ("Block", self.block_input),
            ("TreeID", self.tree_input),
            ("PanicleID", self.panicle_input),
            ("L (mm)", self.l_input),
            ("W (mm)", self.w_input),
            ("T (mm)", self.t_input),
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
        ]
        for index, field in enumerate(focus_order):
            field.bind(
                on_text_validate=lambda _field, i=index:
                self._advance_or_save(i, focus_order)
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
        return f"[b]{self.status_text}[/b]\nSaved records: {self.record_count}"

    def _set_status(self, message):
        self.status_text = message
        self.status.text = self._status_markup()

    def _refresh_count(self):
        with sqlite3.connect(self.db_path) as con:
            self.record_count = con.execute(
                "SELECT COUNT(*) FROM measurements"
            ).fetchone()[0]
        if hasattr(self, "status"):
            self.status.text = self._status_markup()

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

        if not block or not tree_id or not panicle_id:
            raise ValueError("Block, TreeID and PanicleID are required.")

        try:
            l_val = float(self.l_input.text)
            w_val = float(self.w_input.text)
            t_val = float(self.t_input.text)
        except ValueError as exc:
            raise ValueError("L, W and T must be valid numbers.") from exc

        for name, value in (("L", l_val), ("W", w_val), ("T", t_val)):
            if value <= 0 or value > 300:
                raise ValueError(f"{name} must be greater than 0 and no more than 300 mm.")

        return block, tree_id, panicle_id, l_val, w_val, t_val

    def save_record(self):
        try:
            values = self._values()
        except ValueError as exc:
            self._show_message("Check entry", str(exc))
            return

        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                INSERT INTO measurements
                (block, tree_id, panicle_id, l, w, t, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (*values, datetime.now().astimezone().isoformat(timespec="seconds")),
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
        self._set_status(
            f"Saved {values[0]} / Tree {values[1]} / Panicle {values[2]}"
        )
        self.l_input.focus = True

    def clear_measurements(self):
        self.l_input.text = ""
        self.w_input.text = ""
        self.t_input.text = ""
        self.l_input.focus = True

    def undo_last(self):
        with sqlite3.connect(self.db_path) as con:
            row = con.execute(
                """
                SELECT id, block, tree_id, panicle_id
                FROM measurements ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            if not row:
                self._show_message("Undo", "There is no saved record to remove.")
                return
            con.execute("DELETE FROM measurements WHERE id = ?", (row[0],))
            con.commit()

        self._refresh_count()
        self._set_status(
            f"Removed {row[1]} / Tree {row[2]} / Panicle {row[3]}"
        )

    def export_csv(self):
        filename = f"mango_lwt_{datetime.now():%Y%m%d_%H%M%S}.csv"
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
            ["Block", "TreeID", "PanicleID", "L", "W", "T", "Timestamp"]
        )

        with sqlite3.connect(self.db_path) as con:
            writer.writerows(
                con.execute(
                    """
                    SELECT block, tree_id, panicle_id, l, w, t, recorded_at
                    FROM measurements ORDER BY id
                    """
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

    def _show_message(self, title, message):
        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        label = Label(text=message, halign="center", valign="middle")
        label.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        close = Button(text="OK", size_hint_y=None, height=dp(48))
        content.add_widget(label)
        content.add_widget(close)
        popup = Popup(title=title, content=content, size_hint=(0.88, 0.48))
        close.bind(on_release=popup.dismiss)
        popup.open()


class MangoLWTApp(App):
    title = "Mango LWT Recorder"

    def build(self):
        Window.softinput_mode = "below_target"
        return MangoRecorder()


if __name__ == "__main__":
    MangoLWTApp().run()
