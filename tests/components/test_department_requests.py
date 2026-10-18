"""Department preferences remain untrusted; isolated SQLite, no model/network calls."""
import sqlite3
from contextlib import closing

from _test_support import PipelineFixture
from idp.security import INTERNAL
from idp.security.auth import AuthService, AccessDenied, AuthenticationError, REQUEST_DEPARTMENTS
from idp.storage.repository import DocumentRepository
from idp.batch.service import safe_failure

PASSWORD='Disposable-component-only-2026!'


class DepartmentRequestTests(PipelineFixture):
    def setUp(self):
        super().setUp()
        self.repo=self.pipeline.repository
        AuthService(self.repo).create_user('request-admin',PASSWORD,'Administrator',[])
        token=AuthService(self.repo).login('request-admin',PASSWORD)
        self.admin=DocumentRepository(self.repo.db_path,session_token=token)

    def test_each_department_is_only_a_pending_preference(self):
        auth=AuthService(self.repo)
        for index,department in enumerate(REQUEST_DEPARTMENTS):
            username=f'applicant-{index}'
            auth.register(username,PASSWORD,department)
            with self.assertRaises(AuthenticationError): auth.login(username,PASSWORD)
        with self.repo.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0],1)
        requests=AuthService(self.admin).registrations()
        self.assertEqual({r['requested_department'] for r in requests},set(REQUEST_DEPARTMENTS))
        self.assertTrue(all('password_hash' not in r for r in requests))
        for invalid in ('Administrator','Auditor','Finance Reviewer','Unknown'):
            with self.assertRaises(ValueError): auth.register('invalid',PASSWORD,invalid)

    def test_duplicate_cannot_overwrite_preference_or_credentials_and_admin_overrides(self):
        auth=AuthService(self.repo)
        first=auth.register('preference',PASSWORD,'Finance')
        self.assertEqual(first,auth.register('preference','Different-disposable-password!','Legal'))
        request=AuthService(self.admin).registrations()[0]
        self.assertEqual(request['requested_department'],'Finance')
        user_id=AuthService(self.admin).approve_registration(request['id'],0,'Legal Reviewer',['Finance'])
        token=auth.login('preference',PASSWORD)
        self.assertEqual(auth.resolve(token)['departments'],['Legal'])
        approved=next(user for user in AuthService(self.admin).users() if user['id']==user_id)
        self.assertEqual(approved['requested_department'],'Finance')
        self.assertEqual(approved['role'],'Legal Reviewer')
        self.assertEqual(approved['departments'],'["Legal"]')
        self.assertNotIn('password_hash',approved)
        with self.assertRaises(AuthenticationError): auth.login('preference','Different-disposable-password!')
        with self.repo.connect() as db:
            row=db.execute("SELECT * FROM security_events WHERE event_type='registration_approved'").fetchone()
            self.assertEqual(row['resource'],str(user_id))
            self.assertEqual(row['user_id'],self.admin.require('users')['id'])

    def test_decline_requires_admin_revision_and_cannot_be_approved_later(self):
        auth=AuthService(self.repo)
        auth.register('declined',PASSWORD,'Operations / Other')
        request=AuthService(self.admin).registrations()[0]
        auth.create_user('ordinary',PASSWORD,'Finance Reviewer',[])
        other=DocumentRepository(self.repo.db_path,session_token=auth.login('ordinary',PASSWORD))
        with self.assertRaises(AccessDenied): AuthService(other).reject_registration(request['id'],0)
        with self.assertRaises(ValueError): AuthService(self.admin).reject_registration(request['id'],99)
        AuthService(self.admin).reject_registration(request['id'],0)
        self.assertEqual(AuthService(self.admin).registrations(),[])
        with self.assertRaises(AuthenticationError): auth.login('declined',PASSWORD)
        with self.assertRaises(ValueError): AuthService(self.admin).approve_registration(request['id'],1,'Administrator',[])
        auth.register('declined','New-disposable-password!','Finance')
        self.assertEqual(AuthService(self.admin).registrations(),[])
        with self.repo.connect() as db:
            row=db.execute('SELECT * FROM registration_requests').fetchone()
            self.assertIsNone(row['password_hash'])
            self.assertEqual(row['revision'],1)
            self.assertEqual(row['rejected_by'],self.admin.require('users')['id'])
            self.assertEqual(db.execute("SELECT count(*) FROM security_events WHERE event_type='registration_declined'").fetchone()[0],1)

    def test_additive_legacy_migration_preserves_rows_and_backup(self):
        path=self.root/'legacy_departments.db'
        with self.repo.connect() as source:
            with closing(sqlite3.connect(path)) as destination: source.backup(destination)
        with closing(sqlite3.connect(path)) as db:
            db.execute('ALTER TABLE registration_requests DROP COLUMN requested_department')
            db.execute('ALTER TABLE registration_requests DROP COLUMN rejected_by')
            db.execute('ALTER TABLE registration_requests DROP COLUMN rejected_at')
            db.execute("INSERT INTO registration_requests(username,password_hash,created_at) VALUES('legacy-pending','preserved-hash','2026-10-01')")
            tables=('users','auth_sessions','documents','review_events','policy_versions','registration_requests')
            before={table:db.execute('SELECT * FROM '+table).fetchall() for table in tables}
            db.commit()
        migrated=DocumentRepository(path,_capability=INTERNAL)
        DocumentRepository(path,_capability=INTERNAL)
        with migrated.connect() as db:
            for table,records in before.items():
                after=[tuple(row) for row in db.execute('SELECT * FROM '+table)]
                if table=='registration_requests': after=[row[:-3] for row in after]
                self.assertEqual(records,after,table)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
        backups=list(self.root.glob('legacy_departments.db.before_department_requests_v1.*.db'))
        self.assertEqual(len(backups),1)
        with closing(sqlite3.connect(backups[0])) as db:
            self.assertEqual(db.execute('SELECT * FROM registration_requests').fetchall(),before['registration_requests'])

    def test_processing_failure_guidance_is_safe_and_distinct(self):
        self.assertEqual(safe_failure(ValueError('GROQ_API_KEY is missing. Add it to local configuration.'))[0],'configuration')
        for error in (RuntimeError('gsk_private-example C:/private/source.pdf'),ValueError('private source /tmp/example')):
            category,message=safe_failure(error)
            for secret in ('gsk_private','C:/private','/tmp/example'): self.assertNotIn(secret,message)
        error=RuntimeError('provider diagnostic')
        error.status_code=429
        self.assertEqual(safe_failure(error)[0],'rate_limit')
