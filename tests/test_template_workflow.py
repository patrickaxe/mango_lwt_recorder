import gc
import sqlite3
import sys
import tempfile
import types
import unittest
import warnings
from pathlib import Path
from unittest import mock


class _Widget:
    def __init__(self, *args, **kwargs):
        pass


def _module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


# These tests exercise the non-visual workflow without requiring Kivy in CI.
_module("kivy")
_module("kivy.uix")
_module("kivy.app", App=type("App", (), {}))
_module("kivy.clock", Clock=types.SimpleNamespace(schedule_once=lambda *args: None))
_module("kivy.core")
_module("kivy.core.window", Window=types.SimpleNamespace())
_module("kivy.metrics", dp=lambda value: value)
_module(
    "kivy.properties",
    NumericProperty=lambda value: value,
    StringProperty=lambda value: value,
)
_module("kivy.utils", escape_markup=lambda value: value, platform="win")
_module("kivy.uix.boxlayout", BoxLayout=_Widget)
_module("kivy.uix.button", Button=_Widget)
_module("kivy.uix.filechooser", FileChooserListView=_Widget)
_module("kivy.uix.gridlayout", GridLayout=_Widget)
_module("kivy.uix.label", Label=_Widget)
_module("kivy.uix.popup", Popup=_Widget)
_module("kivy.uix.scrollview", ScrollView=_Widget)
_module("kivy.uix.spinner", Spinner=_Widget)
_module("kivy.uix.textinput", TextInput=_Widget)

import main as app_module
from main import MangoRecorder


class _Field:
    def __init__(self, text=""):
        self.text = text
        self.focus = False
        self.readonly = False
        self.disabled = False


class TemplateWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._cleanup_temp_dir)
        self.recorder = MangoRecorder.__new__(MangoRecorder)
        self.recorder.db_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.recorder._active_template_row_id = None
        self.recorder.collection_mode = self.recorder.MODE_LWT
        self.recorder._init_database()
        self.recorder._load_active_worksheet()
        self.recorder._refresh_worksheet_selector = lambda: None
        self.recorder._refresh_count = lambda: None
        self.recorder._set_status = lambda _message: None
        self.recorder._show_message = lambda *_args, **_kwargs: None

    def _cleanup_temp_dir(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            gc.collect()
        self.temp_dir.cleanup()

    def _add_form_fields(self):
        for name in (
            "block_input",
            "tree_input",
            "panicle_input",
            "l_input",
            "w_input",
            "t_input",
            "k_input",
            "weight_input",
            "predicted_weight_input",
            "brix_input",
            "comment_input",
            "voice_command_input",
            "cultivar_spinner",
            "sampling_role_spinner",
            "template_status",
        ):
            setattr(self.recorder, name, _Field())

    def test_database_contains_template_storage_and_measurement_link(self):
        with sqlite3.connect(self.recorder.db_path) as con:
            tables = {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            measurement_columns = {
                row[1] for row in con.execute("PRAGMA table_info(measurements)")
            }

        self.assertIn("worksheet_template_rows", tables)
        self.assertIn("template_row_id", measurement_columns)
        self.assertIn("predicted_weight", measurement_columns)

    def test_legacy_predicated_weight_is_renamed_and_rescaled(self):
        with sqlite3.connect(self.recorder.db_path) as con:
            con.execute(
                "ALTER TABLE measurements ADD COLUMN predicated_weight REAL"
            )
            con.execute(
                """
                INSERT INTO measurements
                    (worksheet_id, predicated_weight, recorded_at)
                VALUES (?, ?, ?)
                """,
                (self.recorder.active_worksheet_id, 336000, "2026-10-08T00:00:00"),
            )
            con.commit()

        self.recorder._init_database()
        self.recorder._init_database()

        with sqlite3.connect(self.recorder.db_path) as con:
            migrated = con.execute(
                "SELECT predicted_weight FROM measurements"
            ).fetchone()[0]
        self.assertEqual(migrated, 336.0)

    def test_identifiers_are_required_but_other_values_are_optional(self):
        self._add_form_fields()
        self.recorder.block_input.text = "21"
        self.recorder.tree_input.text = "1"
        self.recorder.panicle_input.text = "1"

        values = self.recorder._values()

        self.assertEqual(values[:3], ("21", "1", "1"))
        self.assertEqual(values[3:], ("",) * 9)

        self.recorder.tree_input.text = ""
        with self.assertRaisesRegex(ValueError, "TreeID"):
            self.recorder._values()

    def test_predicted_weight_is_calculated_from_dimensions_and_custom_k(self):
        self._add_form_fields()
        self.recorder.block_input.text = "21"
        self.recorder.tree_input.text = "1"
        self.recorder.panicle_input.text = "1"
        self.recorder.l_input.text = "100"
        self.recorder.w_input.text = "80"
        self.recorder.t_input.text = "70"
        self.recorder.k_input.text = "0.6"

        values = self.recorder._values()

        self.assertEqual(values[7], "")
        self.assertEqual(values[8], 336.0)
        self.assertEqual(self.recorder.weight_input.text, "")
        self.assertEqual(self.recorder.predicted_weight_input.text, "336")

    def test_calculated_weight_text_requires_four_positive_numbers(self):
        self.assertEqual(
            MangoRecorder._calculated_weight_text("100", "80", "70", "0.6"),
            "336",
        )
        self.assertEqual(
            MangoRecorder._calculated_weight_text("100", "", "70", "0.6"),
            "",
        )
        self.assertEqual(
            MangoRecorder._calculated_weight_text("100", "80", "70", "-1"),
            "",
        )

    def test_invalid_custom_k_is_rejected(self):
        self._add_form_fields()
        self.recorder.block_input.text = "21"
        self.recorder.tree_input.text = "1"
        self.recorder.panicle_input.text = "1"
        self.recorder.k_input.text = "0"

        with self.assertRaisesRegex(ValueError, "k must be greater than 0"):
            self.recorder._values()

    def test_weight_only_mode_enables_only_weight_measurement(self):
        self._add_form_fields()
        self.recorder.collection_mode = self.recorder.MODE_WEIGHT

        self.recorder._apply_collection_mode_state()

        self.assertTrue(self.recorder.k_input.disabled)
        self.assertTrue(self.recorder.l_input.disabled)
        self.assertTrue(self.recorder.w_input.disabled)
        self.assertTrue(self.recorder.t_input.disabled)
        self.assertFalse(self.recorder.weight_input.disabled)
        self.assertTrue(self.recorder.predicted_weight_input.disabled)
        self.assertTrue(self.recorder.brix_input.disabled)

    def test_brix_only_mode_enables_only_brix_measurement(self):
        self._add_form_fields()
        self.recorder.collection_mode = self.recorder.MODE_BRIX

        self.recorder._apply_collection_mode_state()

        self.assertTrue(self.recorder.k_input.disabled)
        self.assertTrue(self.recorder.l_input.disabled)
        self.assertTrue(self.recorder.w_input.disabled)
        self.assertTrue(self.recorder.t_input.disabled)
        self.assertTrue(self.recorder.weight_input.disabled)
        self.assertTrue(self.recorder.predicted_weight_input.disabled)
        self.assertFalse(self.recorder.brix_input.disabled)

    def test_only_modes_ignore_values_from_disabled_measurements(self):
        self._add_form_fields()
        self.recorder.collection_mode = self.recorder.MODE_BRIX
        self.recorder.block_input.text = "21"
        self.recorder.tree_input.text = "1"
        self.recorder.panicle_input.text = "1"
        self.recorder.k_input.text = "-1"
        self.recorder.l_input.text = "100"
        self.recorder.w_input.text = "80"
        self.recorder.t_input.text = "70"
        self.recorder.weight_input.text = "350"
        self.recorder.brix_input.text = "14.5"
        self.recorder._apply_collection_mode_state()

        values = self.recorder._values()

        self.assertEqual(values[4:9], ("", "", "", "", ""))
        self.assertEqual(values[9], 14.5)

    def test_return_skips_disabled_fields_and_saves_after_only_field(self):
        self._add_form_fields()
        self.recorder.collection_mode = self.recorder.MODE_WEIGHT
        self.recorder._apply_collection_mode_state()
        fields = [
            self.recorder.block_input,
            self.recorder.tree_input,
            self.recorder.panicle_input,
            self.recorder.k_input,
            self.recorder.l_input,
            self.recorder.w_input,
            self.recorder.t_input,
            self.recorder.weight_input,
            self.recorder.brix_input,
        ]
        saved = []
        self.recorder.save_record = lambda: saved.append(True)

        self.recorder._advance_or_save(2, fields)
        self.assertTrue(self.recorder.weight_input.focus)
        self.assertEqual(self.recorder._focused_data_index, 7)

        self.recorder._advance_or_save(7, fields)
        self.assertEqual(saved, [True])

    def test_voice_entry_retargets_from_a_disabled_field(self):
        self._add_form_fields()
        self.recorder.collection_mode = self.recorder.MODE_BRIX
        self.recorder.data_fields = [
            self.recorder.block_input,
            self.recorder.tree_input,
            self.recorder.panicle_input,
            self.recorder.k_input,
            self.recorder.l_input,
            self.recorder.w_input,
            self.recorder.t_input,
            self.recorder.weight_input,
            self.recorder.brix_input,
        ]
        self.recorder.data_field_names = [
            "Block",
            "TreeID",
            "PanicleID",
            "k",
            "L",
            "W",
            "T",
            "Weight",
            "Brix",
        ]
        self.recorder._focused_data_index = 3
        self.recorder._apply_collection_mode_state()

        self.assertTrue(self.recorder._enter_spoken_value("14.5"))

        self.assertEqual(self.recorder._focused_data_index, 8)
        self.assertEqual(self.recorder.brix_input.text, "14.5")

    def test_template_save_advances_to_next_unfinished_row(self):
        self.recorder._load_template_target = lambda: None
        self.recorder.import_template_text(
            "Block,TreeID,PanicleID,SamplingRole\n"
            "21,1,1,Core\n"
            "21,1,2,Drop\n",
            "Field plan",
        )
        self._add_form_fields()
        self.recorder._load_template_target = types.MethodType(
            MangoRecorder._load_template_target, self.recorder
        )

        self.recorder._load_template_target()
        self.assertEqual(self.recorder.panicle_input.text, "1")
        self.assertTrue(self.recorder.panicle_input.readonly)
        self.assertEqual(self.recorder.sampling_role_spinner.text, "Core")

        self.assertTrue(self.recorder.save_record())
        self.assertEqual(self.recorder.panicle_input.text, "2")
        self.assertEqual(self.recorder.sampling_role_spinner.text, "Drop")

        with sqlite3.connect(self.recorder.db_path) as con:
            saved = con.execute(
                "SELECT panicle_id, template_row_id FROM measurements"
            ).fetchone()
        self.assertEqual(saved[0], "1")
        self.assertIsNotNone(saved[1])

        self.recorder.undo_last()
        self.assertEqual(self.recorder.panicle_input.text, "1")
        with sqlite3.connect(self.recorder.db_path) as con:
            remaining = con.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
        self.assertEqual(remaining, 0)

    def test_refresh_error_does_not_report_a_committed_import_as_failed(self):
        messages = []
        self.recorder._show_message = (
            lambda title, message: messages.append((title, message))
        )
        self.recorder._activate_template_worksheet = (
            lambda *_args: (_ for _ in ()).throw(RuntimeError("refresh failed"))
        )

        self.recorder._finish_android_template_import(
            "Block,TreeID,PanicleID\n21,1,1\n", "Field plan"
        )

        self.assertEqual(messages[0][0], "Template imported")
        with sqlite3.connect(self.recorder.db_path) as con:
            imported = con.execute(
                "SELECT COUNT(*) FROM worksheet_template_rows"
            ).fetchone()[0]
        self.assertEqual(imported, 1)

    def test_android_activity_result_defers_import_to_kivy_clock(self):
        scheduled = []
        finished = []
        fake_activity = types.SimpleNamespace(unbind=lambda **_kwargs: None)
        android_module = types.ModuleType("android")
        android_module.activity = fake_activity
        jnius_module = types.ModuleType("jnius")
        jnius_module.autoclass = lambda _name: types.SimpleNamespace(RESULT_OK=1)
        intent = types.SimpleNamespace(getData=lambda: object())
        self.recorder._android_template_picker_bound = True
        self.recorder._read_android_document = (
            lambda _uri: ("Block,TreeID,PanicleID\n21,1,1\n", "Field plan.csv")
        )
        self.recorder._finish_android_template_import = (
            lambda *args: finished.append(args)
        )
        fake_clock = types.SimpleNamespace(
            schedule_once=lambda callback, _delay: scheduled.append(callback)
        )

        with mock.patch.dict(
            sys.modules, {"android": android_module, "jnius": jnius_module}
        ), mock.patch.object(app_module, "Clock", fake_clock):
            self.recorder._on_android_template_result(
                self.recorder.ANDROID_TEMPLATE_REQUEST_CODE, 1, intent
            )

        self.assertEqual(finished, [])
        self.assertEqual(len(scheduled), 1)
        scheduled[0](0)
        self.assertEqual(finished[0][1], "Field plan")


if __name__ == "__main__":
    unittest.main()
