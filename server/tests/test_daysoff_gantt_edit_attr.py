"""Days Off Gantt edit must not embed |tojson inside quoted onclick attrs."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


DAYSOFF_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "app" / "templates" / "admin" / "daysoff.html"
)


class DaysoffGanttEditAttrTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = DAYSOFF_TEMPLATE.read_text()

    def test_gantt_bars_use_data_attributes_not_tojson_onclick(self):
        self.assertIn("js-edit-dayoff", self.src)
        self.assertIn('data-surgeon="{{ row.surgeon.full_name|e }}"', self.src)
        self.assertIn("openEditModalFromEl", self.src)
        self.assertIn("closest('.js-edit-dayoff')", self.src)
        self.assertIsNone(
            re.search(r"onclick=['\"].*openEditModal", self.src),
            "openEditModal must not be wired via onclick+|tojson (breaks HTML attrs)",
        )

    def test_edit_modal_includes_delete(self):
        self.assertIn('id="edit-dayoff-delete-form"', self.src)
        self.assertIn("Delete day off", self.src)
        self.assertIn(
            "document.getElementById('edit-dayoff-delete-form').action",
            self.src,
        )


if __name__ == "__main__":
    unittest.main()
