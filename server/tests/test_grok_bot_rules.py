import json
import os
import unittest
from datetime import date, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.grok_bot_rules import (
    GROK_NOTICE_DATE_PASSED,
    add_grok_bot_rule,
    ensure_grok_bot_rules_seeded,
    grok_rule_enabled,
    list_grok_bot_rules,
    match_plain_language,
)
from app.grok_lookahead_service import run_grok_rules
from app.models import AdminNotification, AdminUser, Base, GrokBotRule


class GrokBotRulesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_seed_lists_builtin_rules(self):
        db = self.Session()
        try:
            rows = list_grok_bot_rules(db)
            ids = [row.rule_id for row in rows]
            self.assertIn(GROK_NOTICE_DATE_PASSED, ids)
            self.assertTrue(all(row.enabled for row in rows if row.is_builtin))
        finally:
            db.close()

    def test_plain_language_matches_past_notice_rule(self):
        self.assertEqual(
            match_plain_language("If a notice has a date that has already passed, take it off the board."),
            GROK_NOTICE_DATE_PASSED,
        )

    def test_custom_english_is_a_standing_note(self):
        db = self.Session()
        try:
            row = add_grok_bot_rule(db, "Always say the covering doctor's initials first.")
            self.assertFalse(row.is_builtin)
            self.assertTrue(row.rule_id.startswith("GROK_CUSTOM_"))
        finally:
            db.close()

    def test_toggle_off_stops_past_notice_drop(self):
        db = self.Session()
        try:
            ensure_grok_bot_rules_seeded(db)
            admin = AdminUser(username="don", email="don@example.com", password_hash="x", is_active=True)
            db.add(admin)
            db.commit()
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            db.add(AdminNotification(
                admin_user_id=admin.id,
                title="Old notice",
                body="past",
                kind="schedule_flag",
                payload=json.dumps({"date": yesterday, "blockId": 9, "surgeonId": 1}),
            ))
            db.commit()
            row = db.query(GrokBotRule).filter(GrokBotRule.rule_id == GROK_NOTICE_DATE_PASSED).one()
            row.enabled = False
            db.commit()
            self.assertFalse(grok_rule_enabled(db, GROK_NOTICE_DATE_PASSED))
            run_grok_rules(db, today=date.today())
            self.assertEqual(db.query(AdminNotification).count(), 1)

            row.enabled = True
            db.commit()
            run_grok_rules(db, today=date.today())
            self.assertEqual(db.query(AdminNotification).count(), 0)
        finally:
            db.close()
