import unittest
from pathlib import Path

from template_csv import parse_template_csv


class ParseTemplateCsvTests(unittest.TestCase):
    def test_only_identifiers_are_required(self):
        rows = parse_template_csv("Block,TreeID,PanicleID\n21,1,1\n")

        self.assertEqual(rows[0]["Block"], "21")
        self.assertEqual(rows[0]["Cultivar"], "")
        self.assertEqual(rows[0]["SamplingRole"], "")

    def test_optional_values_are_preserved(self):
        rows = parse_template_csv(
            "Block,TreeID,PanicleID,Cultivar,SamplingRole,Comment\n"
            '32,10,2p,Calypso,Replaced,"replacement fruit"\n'
        )

        self.assertEqual(rows[0]["PanicleID"], "2p")
        self.assertEqual(rows[0]["SamplingRole"], "Replaced")
        self.assertEqual(rows[0]["Comment"], "replacement fruit")

    def test_missing_required_header_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "PanicleID"):
            parse_template_csv("Block,TreeID\n21,1\n")

    def test_missing_required_row_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "CSV row 2.*TreeID"):
            parse_template_csv("Block,TreeID,PanicleID\n21,,1\n")

    def test_blank_rows_are_ignored(self):
        rows = parse_template_csv(
            "Block,TreeID,PanicleID\n\n21,1,1\n,,\n"
        )

        self.assertEqual(len(rows), 1)

    def test_bundled_example_is_valid(self):
        example_path = Path(__file__).resolve().parents[1] / "FruitSizingTemp.csv"
        rows = parse_template_csv(example_path.read_text(encoding="utf-8-sig"))

        self.assertEqual(len(rows), 108)
        self.assertIn("Replaced", {row["SamplingRole"] for row in rows})


if __name__ == "__main__":
    unittest.main()
