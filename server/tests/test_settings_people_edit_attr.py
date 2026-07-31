"""Users settings Edit buttons must not embed |tojson inside quoted onclick attrs."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


PEOPLE_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "app" / "templates" / "admin" / "settings_people.html"
)
SETTINGS_NAV = (
    Path(__file__).resolve().parents[1] / "app" / "templates" / "admin" / "_settings_nav.html"
)


class SettingsPeopleEditAttrTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = PEOPLE_TEMPLATE.read_text()
        cls.nav = SETTINGS_NAV.read_text()

    def test_nav_renames_people_to_users(self):
        self.assertIn("> Users", self.nav)
        self.assertNotIn("> People", self.nav)

    def test_users_filters_include_positions(self):
        self.assertIn("filter=surgeons", self.src)
        self.assertIn("filter=pas", self.src)
        self.assertIn("filter=schedulers", self.src)
        self.assertIn("filter=staff", self.src)
        self.assertIn(">Admins<", self.src.replace(" ", "").replace("\n", ""))
        self.assertIn(">PAs<", self.src.replace(" ", "").replace("\n", ""))
        self.assertNotIn("PA / APP", self.src)
        self.assertNotIn("Support staff", self.src)
        self.assertNotIn("Support Staff", self.src)
        self.assertNotIn(">Staff<", self.src)
        self.assertIn("{% block title %}Users{% endblock %}", self.src)

    def test_unified_edit_uses_data_attributes_not_tojson_onclick(self):
        self.assertIn('class="edit-user', self.src)
        self.assertIn('data-kind="clinical"', self.src)
        self.assertIn('data-kind="portal"', self.src)
        self.assertIn('data-first-name="{{ s.first_name|e }}"', self.src)
        self.assertIn("querySelectorAll('.edit-user')", self.src)
        self.assertIsNone(
            re.search(r"onclick=['\"].*openEdit", self.src),
            "openEdit* must not be wired via onclick+|tojson (breaks HTML attrs)",
        )
        self.assertNotIn("edit-clinical-user", self.src)
        self.assertNotIn("edit-admin-user", self.src)
        self.assertNotIn("edit-clinical-modal", self.src)
        self.assertNotIn("Edit mobile user", self.src)
        self.assertNotIn("Edit portal user", self.src)

    def test_password_uses_data_attributes_not_tojson_onclick(self):
        self.assertIn('class="set-admin-password', self.src)
        self.assertIn('data-username="{{ u.username|e }}"', self.src)
        self.assertIn("querySelectorAll('.set-admin-password')", self.src)
        self.assertIsNone(
            re.search(r"onclick=['\"].*openPasswordModal", self.src),
            "openPasswordModal must not be wired via onclick+|tojson",
        )

    def test_unified_edit_posts_to_people_edit(self):
        self.assertIn('action="/admin/settings/people/edit"', self.src)
        self.assertIn('id="edit-user-modal"', self.src)
        self.assertIn(">Edit user<", self.src)
        self.assertIn('name="user_kind"', self.src)
        self.assertIn('name="user_id"', self.src)
        self.assertIn('name="position"', self.src)
        edit_block = self.src.split('id="edit-user-modal"', 1)[1].split("password-modal", 1)[0]
        self.assertIn('option value="surgeon"', edit_block)
        self.assertIn('option value="pa"', edit_block)
        self.assertIn('option value="scheduler"', edit_block)
        self.assertIn('option value="staff"', edit_block)
        self.assertIn(">Admin</option>", edit_block)
        self.assertIn(">PA</option>", edit_block)
        self.assertNotIn('name="username"', edit_block)
        self.assertNotIn('name="password"', edit_block)
        self.assertNotIn('name="new_password"', edit_block)
        self.assertIn("Sign-in (OTP)", edit_block)
        self.assertIn('name="email"', edit_block)
        self.assertIn('name="phone"', edit_block)

    def test_access_level_options_include_admin_and_superadmin(self):
        self.assertIn('option value="scheduler"', self.src)
        self.assertIn('option value="superadmin"', self.src)
        self.assertIn('option value="admin"', self.src)
        self.assertNotIn(
            "this.dataset.role === 'scheduler' ? 'scheduler' : 'admin'",
            self.src,
        )

    def test_unified_add_user_form_no_chooser_no_password(self):
        self.assertIn("openAddUser()", self.src)
        self.assertIn('id="add-user-modal"', self.src)
        self.assertIn('name="position"', self.src)
        self.assertIn('option value="surgeon"', self.src)
        self.assertIn('option value="pa"', self.src)
        self.assertIn('option value="scheduler"', self.src)
        self.assertIn('option value="staff"', self.src)
        self.assertIn(">Admin</option>", self.src)
        self.assertIn(">PA</option>", self.src)
        self.assertNotIn(">Staff</option>", self.src)
        self.assertIn('action="/admin/settings/people/add"', self.src)
        self.assertNotIn("openAddChooser", self.src)
        self.assertNotIn("add-chooser", self.src)
        self.assertNotIn("openAddClinical", self.src)
        self.assertNotIn("openAddPortal", self.src)
        # Add form must not ask for username/password credentials
        add_block = self.src.split('id="add-user-modal"', 1)[1].split("Edit user", 1)[0]
        self.assertNotIn('name="username"', add_block)
        self.assertNotIn('name="password"', add_block)
        self.assertIn("Sign-in (OTP)", add_block)
        self.assertIn('name="email"', add_block)
        self.assertIn('name="phone"', add_block)


if __name__ == "__main__":
    unittest.main()
