"""Launcher checks use temporary folders only; no provider calls or active DB."""
import importlib.util
from contextlib import closing
import os
from pathlib import Path
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('student_start', Path(__file__).resolve().parents[2] / 'scripts/student_start.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class StudentSetupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.template = 'GROQ_API_KEY=\nGROQ_MODEL=openai/gpt-oss-120b\nIDP_DATABASE_PATH=data/operational/organization.db\nIDP_WEB_PORT=8000\n'
        (self.root / '.env.example').write_text(self.template)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_new_setup_creates_configuration_not_database(self):
        launcher.configure(self.root)
        self.assertEqual((self.root / '.env').read_text(), self.template)
        config = launcher.configuration(self.root)
        self.assertFalse(config['has_key'])
        self.assertTrue(launcher.needs_setup(config['database']))
        self.assertFalse(Path(config['database']).exists())

    def test_repeat_setup_preserves_private_configuration_byte_for_byte(self):
        original = self.template.replace('8000', '8555') + '# private custom settings\n'
        (self.root / '.env').write_text(original)
        launcher.configure(self.root)
        launcher.configure(self.root)
        self.assertEqual((self.root / '.env').read_text(), original)

    def test_process_environment_precedence_matches_application(self):
        launcher.configure(self.root)
        with patch.dict(os.environ, {'IDP_DATABASE_PATH': 'custom.db', 'IDP_WEB_PORT': '8556'}):
            config = launcher.configuration(self.root)
        self.assertEqual(config['port'], 8556)
        self.assertEqual(config['database'], str((self.root / 'custom.db').resolve()))

    def test_missing_configuration_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, 'setup.cmd'):
            launcher.configuration(self.root)

    def test_missing_database_selection_never_uses_historical_fallback(self):
        (self.root / '.env').write_text('GROQ_API_KEY=\n')
        with self.assertRaisesRegex(ValueError, 'IDP_DATABASE_PATH'):
            launcher.configuration(self.root)

    def test_invalid_ports_are_rejected(self):
        for value in ('0', '65536', 'not-a-port'):
            with self.subTest(value=value):
                (self.root / '.env').write_text(self.template.replace('8000', value))
                with self.assertRaisesRegex(ValueError, '65535'):
                    launcher.configuration(self.root)

    def test_occupied_port_is_actionable(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            with self.assertRaisesRegex(ValueError, 'already in use'):
                launcher.available_port(listener.getsockname()[1])

    def test_existing_database_inspection_does_not_write(self):
        path = self.root / 'existing.db'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE users(id INTEGER)')
            db.execute('INSERT INTO users VALUES(1)')
        before = path.read_bytes()
        self.assertFalse(launcher.needs_setup(path))
        self.assertEqual(path.read_bytes(), before)

    def test_prior_bootstrap_is_not_reauthorized_after_account_removal(self):
        path = self.root / 'existing.db'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE users(id INTEGER)')
            db.execute('CREATE TABLE security_events(event_type TEXT)')
            db.execute("INSERT INTO security_events VALUES('administrator_bootstrap')")
        self.assertFalse(launcher.needs_setup(path))

    def test_damaged_database_is_preserved(self):
        path = self.root / 'damaged.db'
        path.write_bytes(b'not a database')
        with self.assertRaisesRegex(ValueError, 'do not delete'):
            launcher.needs_setup(path)
        self.assertEqual(path.read_bytes(), b'not a database')
