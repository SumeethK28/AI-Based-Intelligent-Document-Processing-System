"""Session-scoped login and authenticated account administration."""
import streamlit as st
from idp.security.auth import AuthService,AccessDenied,AuthenticationError,ROLES,DEPARTMENTS
from idp.security.access import PERMISSIONS

PAGE_PERMISSION={'Overview':'analytics','Process Documents':'process','Bulk Processing':'batches','Document Repository':'documents',
    'Review Center':'review','Department Workspaces':'review','Business Analytics':'analytics','Business Rules':'policy','Audit & Settings':'account','Accounts':'users'}


def allowed(repository,permission):
    if repository.internal: return True
    principal=repository.access.principal()
    return permission in PERMISSIONS.get(principal['role'],set())


def gate(repository):
    if repository.internal: return repository,None
    auth=AuthService(repository)
    token=st.session_state.get('auth_token')
    if token:
        try:
            principal=auth.resolve(token)
            from idp.storage.repository import DocumentRepository
            scoped=DocumentRepository(repository.db_path,session_token=token)
            scoped.require('account')
            return scoped,principal
        except AccessDenied:
            st.session_state.clear()
            st.warning('Your session ended or account changed. Sign in again.')
    st.title('Sign in to Document Operations')
    st.caption('Local research prototype · individual accounts · department access enforced on the server')
    with repository._connect() as db: configured=db.execute('SELECT count(*) FROM users').fetchone()[0]>0
    if not configured:
        st.info('First-time setup is required before the sign-in form is available. Create your administrator account in a terminal on this computer.')
        st.write('Open a terminal in the project folder and run:')
        st.code('uv run --python 3.14.6 python scripts/manage_security.py bootstrap',language='powershell')
        st.caption('If the application uses a custom database, pass --database followed by that same database path before bootstrap.')
        st.write('Choose your account name and a password of 12–128 characters at the prompts, then refresh this page to sign in. Keep your password private.')
        st.caption('Setup preserves existing records and creates backups before migrations. There is no shared default password or browser administrator registration.')
        st.stop()
    with st.form('login_form',clear_on_submit=True):
        username=st.text_input('Account name',key='login_username',max_chars=64)
        password=st.text_input('Password',type='password',key='login_password',max_chars=128)
        submit=st.form_submit_button('Sign in')
    if submit:
        try: token=auth.login(username,password)
        except AuthenticationError as error: st.error(str(error))
        else:
            st.session_state.clear()
            st.session_state['auth_token']=token
            st.rerun()
    st.caption('Sessions expire after 15 minutes without activity or one hour in total. Refreshing the page may require a new sign-in. Passwords and session tokens are never displayed.')
    st.stop()


def account_controls(repository,principal):
    if repository.internal: return
    st.caption(f"Signed in as {principal['username']} · {principal['role']}")
    st.caption('Authorized departments: '+', '.join(principal['departments']))
    with st.expander('My account'):
        password_form(repository)
    if st.button('Sign out',key='logout'):
        try: AuthService(repository).logout(st.session_state['auth_token'])
        except AccessDenied: pass
        st.session_state.clear(); st.rerun()


def accounts(repository):
    from idp.ui.presentation import record_table
    repository.require('users')
    service=AuthService(repository)
    st.caption('Only active, individually assigned accounts can sign in. Account changes revoke all existing sessions. Never share temporary passwords; have the user change it immediately.')
    with st.form('create_account',clear_on_submit=True):
        username=st.text_input('New account name',key='new_username')
        password=st.text_input('Initial password',type='password',key='new_password')
        role=st.selectbox('Account role',ROLES,key='new_role')
        departments=st.multiselect('Authorized departments',DEPARTMENTS,key='new_departments',help='Reviewer scope is fixed by role. Managers and auditors need explicit departments.')
        submit=st.form_submit_button('Create account')
    if submit:
        try: service.create_user(username,password,role,departments)
        except ValueError as error: st.error(str(error))
        else: st.success('Account created with a hashed password.')
    users=service.users(); record_table([{**row,'departments':row['departments']} for row in users])
    if not users:
        st.info('No accounts yet. Create an individual account using the form above.')
        return
    by_id={row['id']:row for row in users}
    selected=st.selectbox('Manage account',list(by_id),format_func=lambda key:by_id[key]['username'],key='manage_account')
    user=by_id[selected]
    import json
    stamp=f"account_{user['id']}_{user['revision']}"
    active=st.checkbox('Account active',value=bool(user['active']),key=stamp+'_active')
    role=st.selectbox('Updated role',ROLES,index=ROLES.index(user['role']),key=stamp+'_role')
    departments=st.multiselect('Updated authorized departments',DEPARTMENTS,default=json.loads(user['departments']),key=stamp+'_departments')
    confirm=st.checkbox('I confirm this account access change and session revocation.',key=stamp+'_confirm')
    if st.button('Save account access',disabled=not confirm,key=stamp+'_save'):
        try: service.update_user(selected,user['revision'],active=active,role=role,departments=departments)
        except ValueError as error: st.error(str(error))
        else: st.rerun()


def password_form(repository):
    if repository.internal: return
    with st.form('change_password',clear_on_submit=True):
        st.subheader('Change your password')
        old=st.text_input('Current password',type='password')
        new=st.text_input('New password',type='password')
        again=st.text_input('Repeat new password',type='password')
        submit=st.form_submit_button('Change password and sign out')
    if submit:
        try:
            if new!=again: raise ValueError('New passwords do not match.')
            AuthService(repository).change_password(old,new)
        except (ValueError,AuthenticationError) as error: st.error(str(error))
        else: st.session_state.clear(); st.rerun()


def download_control(repository,label,kind,resource,key):
    # Generate on explicit action, not during page render. Never cache export bytes.
    from idp.security.downloads import DownloadService,start_download_server
    permission='source' if kind=='source' else 'analytics_export' if kind=='analytics_json' else 'export'
    if not allowed(repository,permission): return
    if st.button(label,key=key):
        try:
            server=start_download_server(repository.db_path)
            grant=DownloadService(repository).grant(kind,resource)
        except Exception:
            st.error('Download unavailable. Refresh and request a new authorized download.')
        else:
            st.link_button('Open secure download (one use, 30 seconds)',f'http://127.0.0.1:{server.server_port}/download?grant={grant}')
