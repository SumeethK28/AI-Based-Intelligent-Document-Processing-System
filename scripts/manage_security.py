"""Local server administrator setup; passwords are entered with getpass, never arguments."""
import argparse
import getpass
import os
import secrets
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from idp.storage.repository import DocumentRepository
from idp.security import INTERNAL
from idp.security.auth import AuthService

if __name__=='__main__':
    load_dotenv()
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',default=os.getenv('IDP_DATABASE_PATH','data/idp.db'))
    parser.add_argument('action',choices=['bootstrap','authorize-setup'])
    args=parser.parse_args()
    if args.action=='authorize-setup':
        try:
            token=AuthService(DocumentRepository(args.database)).authorize_setup(capability=INTERNAL)
            # Use a fresh private directory; never inherit a previous credential file.
            directory=Path(args.database).resolve().parent/'.idp-setup'/secrets.token_hex(8)
            directory.mkdir(parents=True,mode=0o700)
            if os.name=='nt':
                identity=os.environ.get('USERDOMAIN','')+'\\'+getpass.getuser()
                if not os.environ.get('USERDOMAIN'): identity=getpass.getuser()
                result=subprocess.run(['icacls',str(directory),'/inheritance:r','/grant:r',identity+':(OI)(CI)F'],capture_output=True)
                if result.returncode: raise ValueError('Could not protect setup credential directory. Use the existing CLI bootstrap instead.')
            path=directory/'setup-token.txt'
            descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,'w',encoding='utf-8') as target:
                target.write(token+'\n')
        except (ValueError,OSError) as error: raise SystemExit(str(error)) from None
        print('Setup authorized for 15 minutes. Open this credential file privately:')
        print(path)
        print('Enter its value in Organization setup. The credential is one-use; never share or commit it.')
        raise SystemExit(0)
    username=input('First administrator account name: ').strip()
    password=getpass.getpass('Choose a password (12–128 characters): ')
    confirm=getpass.getpass('Repeat password: ')
    if password!=confirm: raise SystemExit('Passwords do not match.')
    try:
        AuthService(DocumentRepository(args.database)).bootstrap(username,password,capability=INTERNAL)
    except ValueError as error: raise SystemExit(str(error)) from None
    print('Administrator created. Start the localhost application and sign in.')
