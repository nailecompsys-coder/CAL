"""Regression coverage for reliable admin-notification dismissal controls."""
from pathlib import Path
import unittest


APP_ROOT = Path(__file__).resolve().parents[1] / "app"


class AdminNotificationDismissControlTest(unittest.TestCase):
    def test_dashboard_uses_post_backed_dismiss_button(self):
        template = (APP_ROOT / "templates/admin/dashboard.html").read_text()
        self.assertIn('method="post" action="/admin/notifications/{{ row.id }}/ack"', template)
        self.assertIn('>Dismiss</span>', template)

    def test_notifications_page_uses_post_backed_dismiss_button(self):
        template = (APP_ROOT / "templates/admin/notifications.html").read_text()
        self.assertIn('method="post" action="/admin/notifications/{{ row.id }}/ack"', template)
        self.assertIn('>Dismiss</button>', template)

    def test_ack_route_accepts_post(self):
        source = (APP_ROOT / "routers/admin_settings.py").read_text()
        self.assertIn('@router.post("/notifications/{notification_id}/ack")', source)


if __name__ == "__main__":
    unittest.main()
