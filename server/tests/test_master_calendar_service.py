import json
import os
import unittest
from datetime import date, time
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
import uuid
from sqlalchemy.orm import Session

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('SECRET_KEY', 'test-only')
from app.api_calendar_admin_service import build_admin_calendar_events
from app.models import (Base, Surgeon, Meeting, MeetingAttendee, DayOff, CallGroup, CallRotation,
                        CallCoverage, Location, SurgeonLocationSchedule, SurgicalCase,
                        AprimaCachedAppointment, SurgeonDayItem, ScheduleCardActivity)
from app.schedule_card_service import materialize_master_schedule_cards
from app.schedule_activity_normalization import backfill_normalized_schedule_activity


class MasterCalendarTest(unittest.TestCase):
    def setUp(self):
        self.engine = self.make_engine()
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.florin = Surgeon(first_name='Jorge', last_name='Florin', is_active=True, staff_type='physician')
        self.other = Surgeon(first_name='Lucy', last_name='Woodley', is_active=True, staff_type='physician')
        self.day = date(2026,10,1)
        self.db.add_all([self.florin,self.other]); self.db.commit()
        self.fid,self.oid = self.florin.id,self.other.id

    def make_engine(self):
        return create_engine('sqlite:///:memory:')

    def tearDown(self):
        self.db.close(); self.engine.dispose()
        if hasattr(self, 'admin_engine'):
            with self.admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
            self.admin_engine.dispose()

    def feed(self, owner=None):
        return build_admin_calendar_events(self.db, date(2026,9,28), date(2026,10,4), owner)

    def meeting(self, title, attendees):
        row = Meeting(title=title,date=self.day,start_time=time(8),end_time=time(9))
        self.db.add(row);self.db.flush()
        for sid,status in attendees:
            self.db.add(MeetingAttendee(meeting_id=row.id,surgeon_id=sid,status=status))
        self.db.commit()

    def test_one_read_only_sql_statement_and_no_unrelated_meetings(self):
        self.meeting('Florin only',[(self.fid,'invited')])
        self.meeting('Other only',[(self.oid,'confirmed')])
        self.meeting('Shared',[(self.fid,'confirmed'),(self.oid,'confirmed')])
        self.meeting('Declined',[(self.fid,'declined'),(self.oid,'confirmed')])
        self.meeting('Practice-wide',[])
        statements=[]
        def capture(conn,cursor,statement,parameters,context,executemany): statements.append(statement)
        event.listen(self.engine,'before_cursor_execute',capture)
        result=self.feed(self.fid)
        event.remove(self.engine,'before_cursor_execute',capture)
        self.assertEqual(len(statements),1)
        self.assertTrue(statements[0].lstrip().startswith('-- One read-only'))
        self.assertEqual({e['title'] for e in result},{'Florin only','Shared','Practice-wide'})
        self.assertEqual(len(self.feed()),5)
        self.assertEqual(self.feed(99999),[])

    def test_leave_is_per_person_exact_segment_and_weekend(self):
        self.db.add_all([
            DayOff(surgeon_id=self.fid,start_date=self.day,end_date=date(2026,10,4),status='approved',reason='Florin leave',segments=json.dumps([
                {'date':'2026-10-01','isFullDay':False,'start':'13:00','end':'17:00'},
                {'date':'2026-10-04','isFullDay':True}])),
            DayOff(surgeon_id=self.oid,start_date=self.day,end_date=self.day,status='approved',reason='Other leave'),
        ]);self.db.commit()
        result=self.feed(self.fid)
        self.assertEqual(len(result),2)
        self.assertNotIn('Woodley',json.dumps(result));self.assertNotIn('Other leave',json.dumps(result))
        self.assertEqual(result[0]['start'],'2026-10-01T13:00')
        self.assertEqual(result[0]['end'],'2026-10-01T17:00')
        self.assertEqual(result[1]['start'],'2026-10-04')
        self.assertEqual(len(self.feed()),3)

    def test_weekend_call_owned_by_active_coverer(self):
        group=CallGroup(name='Altamonte Hospital');self.db.add(group);self.db.flush()
        rotation=CallRotation(date=date(2026,10,4),surgeon_id=self.oid,call_group_id=group.id)
        self.db.add(rotation);self.db.flush()
        self.db.add(CallCoverage(call_rotation_id=rotation.id,original_surgeon_id=self.oid,covering_surgeon_id=self.fid,status='active'));self.db.commit()
        self.assertEqual(len(self.feed(self.fid)),1)
        self.assertEqual(self.feed(self.oid),[])

    def test_cards_preserve_all_cases_assistance_and_half_day_off(self):
        hospital=Location(name='Minneola OR',abbreviation='MN-OR',location_type='hospital',is_active=True)
        self.db.add(hospital);self.db.commit()
        self.db.add(SurgeonLocationSchedule(surgeon_id=self.fid,day_of_week=3,session='am',location_id=hospital.id,assignment_type='assigned'));self.db.commit()
        materialize_master_schedule_cards(self.db,start=date(2026,9,28),end=date(2026,10,2))
        self.db.add_all([
            SurgicalCase(surgeon_id=self.fid,date=self.day,start_time=time(8),location_id=hospital.id,patient_name='First test',procedure='First',status='scheduled'),
            SurgicalCase(surgeon_id=self.oid,assisting_surgeon_id=self.fid,date=self.day,start_time=time(10),location_id=hospital.id,patient_name='Assisted test',procedure='Second',status='scheduled'),
            DayOff(surgeon_id=self.fid,start_date=self.day,end_date=self.day,status='approved',is_full_day=False,start_time=time(7),end_time=time(12)),
        ]);self.db.commit()
        backfill_normalized_schedule_activity(self.db)
        result=self.feed(self.fid)
        cards=[e for e in result if e['id'].startswith('card-')]
        self.assertEqual(len(cards),10)
        am=next(e for e in cards if e['start']==str(self.day) and e['extendedProps']['session']=='am')
        pm=next(e for e in cards if e['start']==str(self.day) and e['extendedProps']['session']=='pm')
        self.assertEqual(am['title'],'AM · OFF');self.assertEqual(pm['title'],'PM · NA')
        self.assertTrue(am['extendedProps']['has_conflict'])
        self.assertEqual({r['patient'] for r in am['extendedProps']['roster']},{'First test','Assisted test'})
        self.assertEqual([r['role'] for r in am['extendedProps']['roster']],['','Assisting'])
        self.assertFalse(any(e['id'].startswith('surg-') for e in result))
        self.assertTrue(all(e['extendedProps']['surgeon_id']==self.fid for e in result))
        self.assertFalse(any(date.fromisoformat(e['start']).weekday()>=5 for e in cards))

    def test_api_applies_surgeon_filter_and_exclusive_end_date(self):
        from app.routers.api_calendar import get_events
        from fastapi import HTTPException
        self.db.add_all([
            SurgeonDayItem(surgeon_id=self.fid,date=self.day,title='Florin today'),
            SurgeonDayItem(surgeon_id=self.fid,date=date(2026,10,2),title='Florin tomorrow'),
            SurgeonDayItem(surgeon_id=self.oid,date=self.day,title='Other today'),
        ]);self.db.commit()
        response=get_events('2026-10-01','2026-10-02',db=self.db,admin=object(),surgeon_id=self.fid)
        self.assertEqual([e['title'] for e in json.loads(response.body)],['Florin today'])
        with self.assertRaises(HTTPException):
            get_events('2026-10-02','2026-10-01',db=self.db,admin=object(),surgeon_id=self.fid)

    def test_assistance_projection_preserves_time_reviewed_slots_and_unplaced_cases(self):
        from app.models import ScheduleCard
        materialize_master_schedule_cards(self.db,start=date(2026,9,28),end=date(2026,10,4))
        am=self.db.query(ScheduleCard).filter_by(surgeon_id=self.fid,date=self.day,session='am').one()
        pm=self.db.query(ScheduleCard).filter_by(surgeon_id=self.fid,date=self.day,session='pm').one()
        afternoon=SurgicalCase(surgeon_id=self.oid,assisting_surgeon_id=self.fid,date=self.day,start_time=time(14),patient_name='Afternoon',procedure='Case',status='scheduled')
        reviewed=SurgicalCase(surgeon_id=self.oid,assisting_surgeon_id=self.fid,date=self.day,start_time=time(13),patient_name='Reviewed',procedure='Case',status='scheduled')
        untimed=SurgicalCase(surgeon_id=self.oid,assisting_surgeon_id=self.fid,date=self.day,patient_name='Untimed',procedure='Case',status='scheduled')
        weekend=SurgicalCase(surgeon_id=self.oid,assisting_surgeon_id=self.fid,date=date(2026,10,4),start_time=time(8),patient_name='Weekend',procedure='Case',status='scheduled')
        cancelled=SurgicalCase(surgeon_id=self.oid,assisting_surgeon_id=self.fid,date=self.day,start_time=time(14),patient_name='Cancelled',procedure='Case',status='cancelled')
        self.db.add_all([afternoon,reviewed,untimed,weekend,cancelled]);self.db.flush()
        self.db.add(ScheduleCardActivity(schedule_card_id=am.id,surgeon_id=self.fid,activity_date=self.day,
            session='am',activity_type='surgical',patient_name='Reviewed',procedure='Case',start_time=time(13),
            source_system='surgical_case_assist',source_record_key=str(reviewed.id),identity_key='reviewed',
            surgical_case_id=reviewed.id,is_active=True))
        self.db.commit()
        result=self.feed(self.fid)
        by_id={e['id']:e for e in result}
        self.assertEqual([r['patient'] for r in by_id[f'card-{am.id}']['extendedProps']['roster']],['Reviewed'])
        self.assertEqual([r['patient'] for r in by_id[f'card-{pm.id}']['extendedProps']['roster']],['Afternoon'])
        self.assertEqual({e['extendedProps']['patient_name'] for e in result if e['id'].startswith('surg-')},{'Untimed','Weekend'})
        self.assertNotIn('Cancelled',json.dumps(result))

    def test_normalized_aprima_is_not_repeated_as_a_cached_appointment(self):
        materialize_master_schedule_cards(self.db,start=date(2026,9,28),end=date(2026,10,2))
        self.cached('patient','visit',self.fid,'Office visit',activity_type='clinic')
        from app.models import ScheduleCard
        card=self.db.query(ScheduleCard).filter_by(surgeon_id=self.fid,date=self.day,session='pm').one()
        self.db.add(ScheduleCardActivity(schedule_card_id=card.id,surgeon_id=self.fid,activity_date=self.day,
            session='pm',activity_type='clinic',patient_name='Test visit',procedure='Office visit',
            source_system='aprima',source_record_key='visit',identity_key='visit',aprima_appointment_id='visit',is_active=True))
        self.db.commit()
        result=self.feed(self.fid)
        self.assertNotIn('aprima-visit',{e['id'] for e in result})
        entry=next(e for e in result if e['id']==f'card-{card.id}')
        self.assertEqual(entry['extendedProps']['count_label'],'1 visit')
        self.assertEqual(len(entry['extendedProps']['roster']),1)

    def cached(self,kind,key,sid,reason,**kw):
        self.db.add(AprimaCachedAppointment(appointment_id=key,kind=kind,date=self.day,surgeon_id=sid,
            start_time=time(15),end_time=time(16),reason_text=reason,content_hash=key,payload_json='{}',**kw));self.db.commit()

    def test_unattached_cases_cached_appointments_and_personal_items_do_not_vanish(self):
        materialize_master_schedule_cards(self.db,start=date(2026,9,28),end=date(2026,10,2))
        self.db.add(SurgicalCase(surgeon_id=self.fid,date=self.day,start_time=time(9),patient_name='Unattached',procedure='Case',status='scheduled'))
        self.cached('patient','visit',self.fid,'Visit',activity_type='clinic')
        self.cached('meeting','mine',self.fid,'Florin Aprima meeting')
        self.cached('meeting','other',self.oid,'Other Aprima meeting')
        self.db.add(SurgeonDayItem(surgeon_id=self.fid,date=self.day,title='Florin reminder'));self.db.commit()
        result=self.feed(self.fid)
        self.assertTrue(any(e['id'].startswith('surg-') for e in result))
        self.assertTrue(any(e['id']=='aprima-visit' for e in result))
        self.assertIn('Florin Aprima meeting',{e['title'] for e in result})
        self.assertNotIn('Other Aprima meeting',{e['title'] for e in result})
        self.assertIn('Florin reminder',{e['title'] for e in result})

    def test_na_activity_and_location_mismatch_remain_visible(self):
        hospital=Location(name='Hospital',abbreviation='AL-OR',location_type='hospital',is_active=True)
        clinic=Location(name='Clinic',abbreviation='CL-OV',location_type='clinic',is_active=True)
        self.db.add_all([hospital,clinic]);self.db.commit()
        self.db.add(SurgeonLocationSchedule(surgeon_id=self.fid,day_of_week=3,session='am',location_id=hospital.id,assignment_type='assigned'));self.db.commit()
        materialize_master_schedule_cards(self.db,start=date(2026,9,28),end=date(2026,10,2))
        from app.models import ScheduleCard
        for slot in ('am','pm'):
            card=self.db.query(ScheduleCard).filter_by(surgeon_id=self.fid,date=self.day,session=slot).one()
            self.db.add(ScheduleCardActivity(schedule_card_id=card.id,surgeon_id=self.fid,location_id=clinic.id,
                activity_date=self.day,session=slot,activity_type='clinic',patient_name='Test visit',procedure='Visit',
                source_system='aprima',source_record_key=slot,identity_key=slot,is_active=True))
        self.db.commit()
        cards=[e for e in self.feed(self.fid) if e['start']==str(self.day)]
        am=next(e for e in cards if e['extendedProps']['session']=='am')
        pm=next(e for e in cards if e['extendedProps']['session']=='pm')
        self.assertEqual(am['title'],'AM · AL-OR');self.assertTrue(am['extendedProps']['has_conflict'])
        self.assertEqual(pm['title'],'PM · CL-OV');self.assertFalse(pm['extendedProps']['has_conflict'])
        self.assertEqual(am['extendedProps']['roster'][0]['location'],'CL-OV')


@unittest.skipUnless(os.environ.get('CAL_TEST_POSTGRES_URL'), 'requires disposable CAL_TEST_POSTGRES_URL')
class MasterCalendarPostgresTest(MasterCalendarTest):
    def make_engine(self):
        self.schema = 'cal_calendar_test_' + uuid.uuid4().hex
        self.admin_engine = create_engine(os.environ['CAL_TEST_POSTGRES_URL'])
        with self.admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        url = make_url(os.environ['CAL_TEST_POSTGRES_URL']).update_query_dict({'options':f'-csearch_path={self.schema}'})
        return create_engine(url)


if __name__ == '__main__': unittest.main()
