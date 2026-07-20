"""People settings Edit buttons must not embed |tojson inside quoted onclick attrs."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


PEOPLE_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "app" / "templates" / "admin" / "settings_people.html"
)


class SettingsPeopleEditAttrTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = PEOPLE_TEMPLATE.read_text()

    def test_clinical_edit_uses_data_attributes_not_tojson_onclick(self):
        self.assertIn('class="edit-clinical-user', self.src)
        self.assertIn('data-first-name="{{ s.first_name|e }}"', self.src)
        self.assertIn("querySelectorAll('.edit-clinical-user')", self.src)
        self.assertIsNone(
            re.search(r"onclick=['\"].*openEditClinical", self.src),
            "openEditClinical must not be wired via onclick+|tojson (breaks HTML attrs)",
        )

    def test_password_uses_data_attributes_not_tojson_onclick(self):
        self.assertIn('class="set-admin-password', self.src)
        self.assertIn('data-username="{{ u.username|e }}"', self.src)
        self.assertIn("querySelectorAll('.set-admin-password')", self.src)
        self.assertIsNone(
            re.search(r"onclick=['\"].*openPasswordModal", self.src),
            "openPasswordModal must not be wired via onclick+|tojson",
        )

    def test_portal_edit_keeps_data_attribute_pattern(self):
        self.assertIn('class="edit-admin-user', self.src)
        self.assertIn("querySelectorAll('.edit-admin-user')", self.src)
        self.assertIn("/admin/settings/people/users/' + this.dataset.userId + '/edit'", self.src)

    def test_portal_role_dropdown_includes_scheduler_and_superadmin(self):
        self.assertIn('option value="scheduler"', self.src)
        self.assertIn('option value="superadmin"', self.src)
        self.assertIn('option value="admin"', self.src)
        self.assertNotIn(
            "this.dataset.role === 'scheduler' ? 'scheduler' : 'admin'",
            self.src,
        )


if __name__ == "__main__":
    unittest.main()
