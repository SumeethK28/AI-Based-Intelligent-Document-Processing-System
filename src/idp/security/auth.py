"""Argon2id passwords, opaque expiring sessions and bounded failed-login attempts."""
import hashlib
import json
import re
import secrets
import time
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

ROLES=('Administrator','Operations Manager','Finance Reviewer','Procurement Reviewer','Expense Reviewer','Legal Reviewer','Auditor')
DEPARTMENTS=('Finance','Procurement','Expense Processing','Legal','Document Review','Risk Review','Document Operations')
REVIEW_DEPARTMENT={'Finance Reviewer':'Finance','Procurement Reviewer':'Procurement','Expense Reviewer':'Expense Processing','Legal Reviewer':'Legal'}
HASHER=PasswordHasher()
DUMMY=HASHER.hash(secrets.token_urlsafe(32))


class AccessDenied(PermissionError):
    pass


class AuthenticationError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class AuthService:
    SESSION_SECONDS=3600
    IDLE_SECONDS=900
    def __init__(self,repository,*,clock=time.time):
        self.repository=repository
        self.clock=clock

    def event(self,event,outcome,resource='',user_id=None,db=None):
        values=(event,user_id,outcome,str(resource)[:200],self.repository.timestamp())
        if db is not None:
            return db.execute('INSERT INTO security_events(event_type,user_id,outcome,resource,created_at) VALUES(?,?,?,?,?)',values).lastrowid
        if self.repository._connection_depth:
            self.repository._security_pending.append(values)
            return None
        with self.repository._connect() as connection:
            return connection.execute('INSERT INTO security_events(event_type,user_id,outcome,resource,created_at) VALUES(?,?,?,?,?)',values).lastrowid

    @staticmethod
    def account_values(username,password,role,departments):
        if not isinstance(username,str) or not re.fullmatch('[A-Za-z0-9_.-]{3,64}',username):
            raise ValueError('Use a unique 3–64 character account name with letters, numbers, dot, underscore or dash.')
        if not isinstance(password,str) or not 12<=len(password)<=128:
            raise ValueError('Use a password of 12–128 characters.')
        if role not in ROLES:
            raise ValueError('Select a supported role.')
        if role in REVIEW_DEPARTMENT:
            departments=[REVIEW_DEPARTMENT[role]]
        elif role=='Administrator':
            departments=list(DEPARTMENTS)
        if not isinstance(departments,list) or not departments or any(value not in DEPARTMENTS for value in departments):
            raise ValueError('Select explicit authorized departments.')
        return username.lower(),HASHER.hash(password),role,json.dumps(sorted(set(departments)))

    def bootstrap(self,username,password,*,capability):
        from idp.security import INTERNAL
        if capability is not INTERNAL:
            raise AccessDenied('First administrator setup requires the local server CLI.')
        values=self.account_values(username,password,'Administrator',[])
        with self.repository._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM users').fetchone()[0]:
                raise ValueError('Administrator setup already completed.')
            user_id=db.execute('INSERT INTO users(username,password_hash,role,departments,created_at) VALUES(?,?,?,?,?)',(*values,self.repository.timestamp())).lastrowid
            self.event('administrator_bootstrap','allowed',user_id=user_id,db=db)
        return user_id

    def login(self,username,password):
        username=str(username or '').strip().lower()[:128]
        now=self.clock()
        identifiers=[digest('account:'+username),digest('global-login')]
        # Commit lockout/failure history even when authentication fails.
        token=None
        with self.repository._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            limits=[db.execute('SELECT * FROM login_limits WHERE identifier_hash=?',(key,)).fetchone() for key in identifiers]
            locked=any(row and row['locked_until']>now for row in limits)
            row=db.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
            verified=False
            if not locked and isinstance(password,str) and len(password)<=128:
                try:
                    verified=HASHER.verify(row['password_hash'] if row else DUMMY,password)
                except (VerificationError,InvalidHashError): pass
            if verified and row and row['active'] and not locked:
                token=secrets.token_urlsafe(32)
                db.execute('INSERT INTO auth_sessions VALUES(?,?,?,?,?,0)',(digest(token),row['id'],now,now+self.SESSION_SECONDS,now))
                db.execute('DELETE FROM login_limits WHERE identifier_hash=?',(identifiers[0],))
                if HASHER.check_needs_rehash(row['password_hash']):
                    db.execute('UPDATE users SET password_hash=? WHERE id=?',(HASHER.hash(password),row['id']))
                self.event('login','allowed',user_id=row['id'],db=db)
            else:
                for key,limit,maximum in zip(identifiers,limits,(5,30)):
                    failures=(limit['failures'] if limit and now-limit['window_start']<900 else 0)+1
                    start=limit['window_start'] if limit and now-limit['window_start']<900 else now
                    locked_until=max(limit['locked_until'] if limit else 0,now+900 if failures>=maximum else 0)
                    db.execute('INSERT OR REPLACE INTO login_limits VALUES(?,?,?,?)',(key,failures,start,locked_until))
                self.event('login','denied',user_id=row['id'] if row else None,db=db)
        if token is None:
            raise AuthenticationError('Sign-in failed or temporarily limited. Check credentials or retry later.')
        return token

    def resolve(self,token):
        if not isinstance(token,str) or not token:
            raise AccessDenied('Sign in to continue.')
        return self.resolve_hash(digest(token))

    def resolve_hash(self,token_hash):
        now=self.clock()
        with self.repository._connect() as db:
            row=db.execute('SELECT u.id,u.username,u.role,u.departments,u.active,s.* FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?',(token_hash,)).fetchone()
            if not row or not row['active'] or row['revoked'] or now>=row['expires_at'] or now-row['last_seen']>=self.IDLE_SECONDS:
                raise AccessDenied('Session expired, signed out or account disabled. Sign in again.')
        return {'id':row['user_id'],'username':row['username'],'role':row['role'],'departments':json.loads(row['departments'])}

    def logout(self,token):
        principal=self.resolve(token)
        with self.repository._connect() as db:
            db.execute('UPDATE auth_sessions SET revoked=1 WHERE token_hash=?',(digest(token),))
            self.event('logout','allowed',user_id=principal['id'],db=db)

    def create_user(self,username,password,role,departments):
        actor=self.repository.require('users')
        values=self.account_values(username,password,role,departments)
        with self.repository._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                user_id=db.execute('INSERT INTO users(username,password_hash,role,departments,created_at) VALUES(?,?,?,?,?)',(*values,self.repository.timestamp())).lastrowid
            except __import__('sqlite3').IntegrityError:
                raise ValueError('Account name already exists.') from None
            self.event('account_created','allowed',str(user_id),actor['id'],db)
        return user_id

    def users(self):
        self.repository.require('users')
        with self.repository._connect() as db:
            return [dict(row) for row in db.execute('SELECT id,username,role,departments,active,revision FROM users ORDER BY id')]

    def update_user(self,user_id,expected_revision,*,active,role,departments):
        actor=self.repository.require('users')
        if type(active) is not bool or role not in ROLES:
            raise ValueError('Invalid account configuration.')
        # Validate role/scope without deriving or storing another password.
        if role in REVIEW_DEPARTMENT: departments=[REVIEW_DEPARTMENT[role]]
        if role=='Administrator': departments=list(DEPARTMENTS)
        if not departments or any(value not in DEPARTMENTS for value in departments): raise ValueError('Explicit department scope required.')
        with self.repository._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
            if not row or row['revision']!=expected_revision: raise ValueError('Account changed. Refresh before saving.')
            if row['role']=='Administrator' and row['active'] and (not active or role!='Administrator') and db.execute("SELECT count(*) FROM users WHERE role='Administrator' AND active=1").fetchone()[0]<=1:
                raise ValueError('The last active administrator cannot be disabled or demoted.')
            db.execute('UPDATE users SET active=?,role=?,departments=?,revision=revision+1 WHERE id=?',(int(active),role,json.dumps(sorted(set(departments))),user_id))
            db.execute('UPDATE auth_sessions SET revoked=1 WHERE user_id=?',(user_id,))
            self.event('account_changed','allowed',str(user_id),actor['id'],db)

    def change_password(self,old_password,new_password):
        actor=self.repository.require('account')
        with self.repository._connect() as db:
            row=db.execute('SELECT * FROM users WHERE id=?',(actor['id'],)).fetchone()
            try: HASHER.verify(row['password_hash'],old_password)
            except (VerificationError,InvalidHashError): raise AuthenticationError('Current password was not accepted.') from None
            hashed=self.account_values(row['username'],new_password,row['role'],json.loads(row['departments']))[1]
            db.execute('UPDATE users SET password_hash=?,revision=revision+1 WHERE id=?',(hashed,actor['id']))
            db.execute('UPDATE auth_sessions SET revoked=1 WHERE user_id=?',(actor['id'],))
            self.event('password_changed','allowed',user_id=actor['id'],db=db)
