"""Small local launcher; reuse dotenv, application startup and local authorization.

Never prints configuration values other than the database path and port. Inspection
uses read-only SQLite, never the repository initializer or a historical fallback.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
import threading
import time
import urllib.request
import webbrowser

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ('GROQ_MODEL', 'IDP_DATABASE_PATH', 'IDP_WEB_PORT')


def configuration(root=ROOT):
    path = root / '.env'
    if not path.is_file():
        raise ValueError('Run setup.cmd first to create your private .env file.')
    values = dotenv_values(path, interpolate=False)
    effective = {key: os.environ.get(key, values.get(key)) for key in (*REQUIRED, 'GROQ_API_KEY')}
    if any(not str(effective[key] or '').strip() for key in REQUIRED):
        raise ValueError('In .env, set GROQ_MODEL, IDP_DATABASE_PATH and IDP_WEB_PORT using .env.example as your guide.')
    try:
        port = int(effective['IDP_WEB_PORT'])
        if not 1 <= port <= 65535:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('Set IDP_WEB_PORT in .env to a number from 1 to 65535, for example 8000.') from None
    database = Path(effective['IDP_DATABASE_PATH']).expanduser()
    database = (root / database).resolve()
    if database.exists() and not database.is_file():
        raise ValueError('IDP_DATABASE_PATH must name a database file, not a folder.')
    return {'database': str(database), 'port': port,
            'has_key': bool(str(effective['GROQ_API_KEY'] or '').strip())}


def needs_setup(path):
    path = Path(path)
    if not path.exists():
        return True
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'users' not in tables:
                return True
            initialized = db.execute('SELECT 1 FROM users LIMIT 1').fetchone()
            if 'security_events' in tables:
                initialized = initialized or db.execute("SELECT 1 FROM security_events WHERE event_type='administrator_bootstrap' LIMIT 1").fetchone()
            return not bool(initialized)
    except sqlite3.Error:
        raise ValueError('The selected database cannot be inspected safely. Ask your maintainer; do not delete it.') from None


def available_port(port):
    try:
        with socket.socket() as listener:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(('127.0.0.1', port))
    except OSError:
        raise ValueError('The website port is already in use. Stop the other copy with Ctrl+C, or change IDP_WEB_PORT in .env and restart.') from None


def configure(root=ROOT):
    # Exclusive creation avoids overwriting a concurrent setup or existing file.
    try:
        with (root / '.env').open('xb') as target, (root / '.env.example').open('rb') as source:
            shutil.copyfileobj(source, target)
    except FileExistsError:
        pass
    config = configuration(root)
    print('Private .env is ready; existing configuration and databases were preserved.')
    print('Web app and optional worker use IDP_DATABASE_PATH from this same .env.')
    print('Database: ' + config['database'])
    if any(key in os.environ for key in (*REQUIRED, 'GROQ_API_KEY')):
        print('Existing process environment settings take precedence over .env. Check them privately if unexpected.')
    if not config['has_key']:
        print('Add your own Groq key in .env for AI processing. The website and account setup work without it.')


def open_when_ready(url):
    for _ in range(60):
        try:
            with urllib.request.urlopen(url + '/api/onboarding', timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except OSError:
            time.sleep(.5)
    print('If the browser did not open, open the website URL shown above yourself.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('configure', 'status', 'start'))
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    try:
        if Path.cwd().resolve() != ROOT:
            raise ValueError('Open the project folder in PowerShell first.')
        if args.action == 'configure':
            configure()
            return
        config = configuration()
        if not (ROOT / 'frontend/dist/index.html').is_file() or not (ROOT / 'frontend/dist/assets').is_dir():
            raise ValueError('The React website is not built. Run setup.cmd first.')
        available_port(config['port'])
        if args.action == 'status':
            print(json.dumps({**config, 'setup_required': needs_setup(config['database'])}))
            return
        load_dotenv(ROOT / '.env', interpolate=False)
        # Pin the already validated selection for this process only. No .env edits.
        os.environ['IDP_DATABASE_PATH'] = config['database']
        os.environ['IDP_WEB_PORT'] = str(config['port'])
        if not args.no_browser:
            threading.Thread(target=open_when_ready, args=(f"http://127.0.0.1:{config['port']}",), daemon=True).start()
        from idp.web.api import main as serve
        serve()
    except (ValueError, OSError):
        # Only our fixed actionable messages are safe; raw OS errors may contain
        # private paths. Configuration parsing is never echoed.
        error = sys.exception()
        print(str(error) if isinstance(error, ValueError) else 'Could not access installation files. Check folder permissions and rerun setup.cmd.', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
