"""Local server administrator setup; passwords are entered with getpass, never arguments."""
import argparse
import getpass
from idp.storage.repository import DocumentRepository
from idp.security import INTERNAL
from idp.security.auth import AuthService

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',default='data/idp.db')
    parser.add_argument('action',choices=['bootstrap'])
    args=parser.parse_args()
    username=input('First administrator account name: ').strip()
    password=getpass.getpass('Choose a password (12–128 characters): ')
    confirm=getpass.getpass('Repeat password: ')
    if password!=confirm: raise SystemExit('Passwords do not match.')
    try:
        AuthService(DocumentRepository(args.database)).bootstrap(username,password,capability=INTERNAL)
    except ValueError as error: raise SystemExit(str(error)) from None
    print('Administrator created. Start the localhost application and sign in.')
