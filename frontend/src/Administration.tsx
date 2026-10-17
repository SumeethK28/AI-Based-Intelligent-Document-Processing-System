import { useState, useContext } from "react";

import { ShieldCheck } from "lucide-react";
import { api, RecordData, Session } from "./api";

import {
  words,
  ActionContext,
  allowed,
  useLoad,
  Button,
  TextField,
  Select,
  Confirm,
  Panel,
  Detail,
  State,
  Table,
  Subtabs,
  PageTitle,
} from "./components";

export function Administration() {
  const { permissions } = useContext(ActionContext),
    items = [
      ...(allowed(permissions, "policy") ? ["Policies"] : []),
      ...(allowed(permissions, "users") ? ["People"] : []),
      ...(allowed(permissions, "security_audit") ? ["Audit & settings"] : []),
    ],
    [view, setView] = useState(items[0]);
  return (
    <>
      <PageTitle
        eyebrow="GOVERNANCE & ACCESS"
        title="Administration"
        description="Manage business rules, individual accounts and your audit trail."
      />
      <Subtabs value={view} set={setView} items={items} />
      {view === "Policies" ? (
        <Policies />
      ) : view === "People" ? (
        <People />
      ) : (
        <Audit />
      )}
    </>
  );
}

export function ConfigFields({
  value,
  set,
}: {
  value: RecordData;
  set: (v: RecordData) => void;
}) {
  return (
    <div className="config-fields">
      {Object.entries(value).map(([key, v]) => (
        <div key={key}>
          {typeof v === "object" && v !== null && !Array.isArray(v) ? (
            <Detail title={words(key)}>
              <ConfigFields
                value={v}
                set={(next) => set({ ...value, [key]: next })}
              />
            </Detail>
          ) : typeof v === "boolean" ? (
            <Confirm value={v} set={(next) => set({ ...value, [key]: next })}>
              {words(key)}
            </Confirm>
          ) : (
            <TextField
              label={words(key)}
              value={Array.isArray(v) ? v.join(", ") : String(v ?? "")}
              set={(next) =>
                set({
                  ...value,
                  [key]: Array.isArray(v)
                    ? next
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean)
                    : typeof v === "number"
                      ? Number(next)
                      : next,
                })
              }
              type={typeof v === "number" ? "number" : "text"}
            />
          )}
        </div>
      ))}
    </div>
  );
}

export function Policies() {
  const { data, error } = useLoad("/policies"),
    { run } = useContext(ActionContext),
    [config, setConfig] = useState<RecordData>(),
    [reason, setReason] = useState(""),
    [id, setId] = useState(""),
    [preview, setPreview] = useState<RecordData>(),
    [confirmed, setConfirmed] = useState(false);
  if (!data) return <State error={error} loading={!error} />;
  return (
    <>
      <div className="notice">
        <ShieldCheck size={17} />
        <span>
          Active policy {data.active.id}. Existing documents keep their recorded
          policy. Evidence, validation, unique PO matching and risk guards
          cannot be bypassed.
        </span>
      </div>
      <div className="two-columns">
        <Panel title="Prepare business rules">
          <ConfigFields value={config ?? data.active.config} set={setConfig} />
          <TextField
            label="Reason for this policy"
            value={reason}
            set={setReason}
          />
          <Button
            primary
            disabled={!reason}
            onClick={() =>
              run(async () => {
                const result = await api("/policies", {
                  config: config ?? data.active.config,
                  reason,
                });
                setId(String(result.version_id));
              })
            }
          >
            Save draft
          </Button>
        </Panel>
        <Panel title="Preview & activate">
          <Table
            rows={data.versions}
            keys={["id", "status", "reason", "created_at"]}
          />
          <Select
            label="Policy version (including rollback)"
            value={id}
            set={(v) => {
              setId(v);
              setPreview(undefined);
              setConfirmed(false);
            }}
            options={["", ...data.versions.map((v: any) => String(v.id))]}
          />
          <Button
            disabled={!id}
            onClick={() =>
              run(async () =>
                setPreview(await api("/policies/" + id + "/preview", {})),
              )
            }
          >
            Preview current documents
          </Button>
          {preview && (
            <Table
              rows={preview.documents}
              keys={[
                "document_id",
                "prior_workflow",
                "proposed_workflow",
                "department",
              ]}
            />
          )}
          <Confirm value={confirmed} set={setConfirmed}>
            I reviewed the preview and confirm activation for future processing.
          </Confirm>
          <Button
            primary
            disabled={!preview || !confirmed || !reason}
            onClick={() =>
              run(async () => {
                await api("/policies/" + id + "/activate", {
                  preview_id: preview?.id,
                  reason,
                  confirmed,
                });
                setPreview(undefined);
                setConfirmed(false);
              })
            }
          >
            Activate policy
          </Button>
          <Detail title="Activation history">
            <Table rows={data.history} />
          </Detail>
        </Panel>
      </div>
    </>
  );
}

export function People() {
  const { data, error } = useLoad("/users"),
    { run } = useContext(ActionContext),
    [requestId, setRequestId] = useState(""),
    [approvalRole, setApprovalRole] = useState("Finance Reviewer"),
    [approvalDepartments, setApprovalDepartments] = useState<string[]>([]),
    [approvalConfirmed, setApprovalConfirmed] = useState(false),
    [username, setUsername] = useState(""),
    [password, setPassword] = useState(""),
    [role, setRole] = useState("Finance Reviewer"),
    [departments, setDepartments] = useState<string[]>([]),
    [id, setId] = useState(""),
    [active, setActive] = useState(true),
    [resetPassword, setResetPassword] = useState(""),
    [resetAgain, setResetAgain] = useState(""),
    [resetConfirmed, setResetConfirmed] = useState(false),
    [editRole, setEditRole] = useState("Finance Reviewer"),
    [editDepartments, setEditDepartments] = useState<string[]>([]),
    [confirmed, setConfirmed] = useState(false);
  if (!data) return <State error={error} loading={!error} />;
  const selected = data.users.find((u: any) => String(u.id) === id);
  const scopes = (values: string[], set: (v: string[]) => void) => (
    <fieldset className="scope-list">
      <legend>Authorized departments</legend>
      {data.departments.map((dept: string) => (
        <Confirm
          key={dept}
          value={values.includes(dept)}
          set={(yes) =>
            set(yes ? [...values, dept] : values.filter((v) => v !== dept))
          }
        >
          {dept}
        </Confirm>
      ))}
    </fieldset>
  );
  return (
    <>
      <Panel title="Pending employee registrations">
        <p className="footnote">Requests have no login, document or department access until you approve a role and scope. Passwords are never displayed.</p>
        <Table rows={data.registration_requests ?? []} keys={["username", "status", "created_at"]} />
        {!!data.registration_requests?.length && <>
          <Select label="Registration request" value={requestId} set={(value) => {setRequestId(value); setApprovalConfirmed(false);}} options={["", ...data.registration_requests.map((row: RecordData) => String(row.id))]} labels={Object.fromEntries([["", "Choose a pending employee"], ...data.registration_requests.map((row: RecordData) => [String(row.id), row.username])])} />
          <Select label="Approved employee role" value={approvalRole} set={(value) => {setApprovalRole(value); setApprovalConfirmed(false);}} options={data.roles} />
          {data.role_departments?.[approvalRole] ? <p>Department: {data.role_departments[approvalRole]}</p> : approvalRole === "Administrator" ? <p>Organization-wide administrator scope</p> : scopes(approvalDepartments, setApprovalDepartments)}
          <Confirm value={approvalConfirmed} set={setApprovalConfirmed}>I verified this employee and approve the selected role and department.</Confirm>
          <Button disabled={!requestId || !approvalConfirmed} onClick={() => run(async () => {
            const request = data.registration_requests.find((row: RecordData) => String(row.id) === requestId);
            if (!request) return;
            await api(`/registrations/${requestId}/approve`, { expected_revision: request.revision, role: approvalRole, departments: approvalDepartments, confirmed: approvalConfirmed });
            setRequestId(""); setApprovalConfirmed(false);
          })}>Approve employee registration</Button>
        </>}
      </Panel>
      <Panel title="Individual accounts">
        <p className="account-list-caption">
          {data.users.length} accounts ·{" "}
          {data.users.filter((u: RecordData) => u.active).length} active.
          Department tags show each account’s authorized scope.
        </p>
        <Table
          rows={data.users.map((user: RecordData) => ({
            ...user,
            account_status: user.active ? "Active" : "Disabled",
          }))}
          keys={["username", "role", "departments", "account_status"]}
          cells={{
            username: (user) => (
              <div className="account-identity">
                <span className="account-initials" aria-hidden="true">
                  {user.username.slice(0, 2).toUpperCase()}
                </span>
                <div>
                  <strong>{user.username}</strong>
                  <small>Account #{user.id}</small>
                </div>
              </div>
            ),
            role: (user) => <span className="role-chip">{user.role}</span>,
            departments: (user) => {
              let values: unknown = user.departments;
              if (typeof values === "string") {
                try {
                  values = JSON.parse(values);
                } catch {
                  return <span>{user.departments}</span>;
                }
              }
              return Array.isArray(values) ? (
                <div className="scope-chips">
                  {values.map((dept: string) => (
                    <span className="scope-chip" key={dept}>
                      {dept}
                    </span>
                  ))}
                </div>
              ) : (
                <span>Scope unavailable</span>
              );
            },
            account_status: (user) => (
              <span
                className={`account-state ${user.active ? "enabled" : "disabled"}`}
              >
                <i aria-hidden="true" />
                {user.account_status}
              </span>
            ),
          }}
        />
      </Panel>
      <div className="two-columns">
        <Panel title="Create an account">
          <TextField label="Account name" value={username} set={setUsername} />
          <TextField
            label="Initial password (12–128 characters)"
            value={password}
            set={setPassword}
            type="password"
          />
          <Select
            label="Role"
            value={role}
            set={setRole}
            options={data.roles}
          />
          {data.role_departments?.[role] ? <p>Department: {data.role_departments[role]}</p> : role === "Administrator" ? <p>Organization-wide administrator scope</p> : scopes(departments, setDepartments)}
          <Button
            primary
            disabled={!username || password.length < 12}
            onClick={() =>
              run(async () => {
                await api("/users", { username, password, role, departments });
                setPassword("");
                setUsername("");
              })
            }
          >
            Create account
          </Button>
        </Panel>
        <Panel title="Manage access">
          <Select
            label="Account"
            value={id}
            set={(v) => {
              setId(v);
              const user = data.users.find((u: any) => String(u.id) === v);
              if (user) {
                setActive(!!user.active);
                setEditRole(user.role);
                setEditDepartments(JSON.parse(user.departments));
              }
              setConfirmed(false);
              setResetPassword(""); setResetAgain(""); setResetConfirmed(false);
            }}
            options={["", ...data.users.map((u: any) => String(u.id))]}
            labels={Object.fromEntries([["", "Choose an employee"], ...data.users.map((u: any) => [String(u.id), u.username])])}
          />
          {selected && (
            <>
              <p>{selected.username}</p>
              <Confirm value={active} set={setActive}>
                Account active
              </Confirm>
              <Select
                label="Updated role"
                value={editRole}
                set={setEditRole}
                options={data.roles}
              />
              {data.role_departments?.[editRole] ? <p>Department: {data.role_departments[editRole]}</p> : editRole === "Administrator" ? <p>Organization-wide administrator scope</p> : scopes(editDepartments, setEditDepartments)}
              <Confirm value={confirmed} set={setConfirmed}>
                I confirm this access change and revocation of existing
                sessions.
              </Confirm>
              <Button
                disabled={!confirmed}
                onClick={() =>
                  run(() =>
                    api("/users/" + id, {
                      expected_revision: selected.revision,
                      role: editRole,
                      departments: editDepartments,
                      active,
                      confirmed,
                    }),
                  )
                }
              >
                Save account access
              </Button>
              <Detail title="Reset employee credentials">
                <p className="footnote">Verify the employee identity outside this application. Share the new password privately; existing sessions will be revoked. Employees can change it from My account. For your own account, use Change your password.</p>
                <TextField label="New employee password" value={resetPassword} set={setResetPassword} type="password" />
                <TextField label="Repeat employee password" value={resetAgain} set={setResetAgain} type="password" />
                <Confirm value={resetConfirmed} set={setResetConfirmed}>I verified the employee and confirm the credential reset.</Confirm>
                <Button disabled={!resetConfirmed || resetPassword.length < 12 || resetPassword !== resetAgain} onClick={() => run(async () => {
                  await api(`/users/${id}/credentials`, {expected_revision: selected.revision, new_password: resetPassword, confirmed: resetConfirmed});
                  setResetPassword(""); setResetAgain(""); setResetConfirmed(false);
                })}>Reset credentials & revoke sessions</Button>
              </Detail>
            </>
          )}
        </Panel>
      </div>
    </>
  );
}

export function Audit() {
  const { data, error } = useLoad<RecordData[]>("/audit"),
    retention = useLoad<RecordData[]>("/retention"),
    [confirmed, setConfirmed] = useState(false),
    [id, setId] = useState(""),
    { run } = useContext(ActionContext);
  return (
    <>
      <Panel title="Data handling">
        <p>
          OCR runs locally. Processing sends document text to the configured
          Groq service. SQLite stores extracted information and decisions; batch
          sources are retained locally.
        </p>
        <p className="footnote">
          This research prototype has no MFA, encrypted SQLite or compliance
          certification. Operating-system administrators remain privileged.
        </p>
      </Panel>
      <Panel title="Security event history">
        <State error={error} loading={!data && !error} />
        {data && <Table rows={data} />}
      </Panel>
      <Detail title="Source retention">
        <Table rows={retention.data ?? []} />
        {retention.data?.some((row) => row.eligible) && (
          <>
            <Select
              label="Expired unlinked source"
              value={id}
              set={setId}
              options={[
                "",
                ...retention.data
                  .filter((r) => r.eligible)
                  .map((r) => String(r.id)),
              ]}
            />
            <Confirm value={confirmed} set={setConfirmed}>
              I confirm deletion of this expired source with no document or
              audit reference.
            </Confirm>
            <Button
              disabled={!confirmed || !id}
              onClick={() => run(() => api("/retention/" + id, { confirmed }))}
            >
              Clean up expired source
            </Button>
          </>
        )}
      </Detail>
    </>
  );
}

export function Account() {
  const { run } = useContext(ActionContext),
    [current, setCurrent] = useState(""),
    [next, setNext] = useState(""),
    [again, setAgain] = useState("");
  return (
    <Detail title="Change your password">
      <TextField
        label="Current password"
        value={current}
        set={setCurrent}
        type="password"
      />
      <TextField
        label="New password"
        value={next}
        set={setNext}
        type="password"
      />
      <TextField
        label="Repeat new password"
        value={again}
        set={setAgain}
        type="password"
      />
      <Button
        disabled={next !== again || next.length < 12}
        onClick={() =>
          run(async () => {
            await api("/password", { current, new: next });
            window.dispatchEvent(new Event("idp-session-ended"));
          })
        }
      >
        Change password & sign out
      </Button>
    </Detail>
  );
}


export function AccessScreen({ onSignedIn, error }: { onSignedIn: (value: Session) => void; error: string }) {
  const { run, busy } = useContext(ActionContext);
  const { data: onboarding } = useLoad("/onboarding");
  const [mode, setMode] = useState("sign-in");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [notice, setNotice] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const choose = (value: string) => {
    setMode(value); setPassword(""); setAgain(""); setSetupToken(""); setNotice("");
  };
  const registration = mode === "register";
  const setup = mode === "setup" && onboarding?.setup_required && onboarding?.setup_authorized;
  return <div className="signin-form">
    <div className="brand mobile-brand"><span className="brand-mark">d</span>Document Operations</div>
    <h2>{setup ? "Create administrator account" : registration ? "Create account" : "Sign in"}</h2>
    <div className="access-options">
      {registration ? <Button onClick={() => choose("sign-in")}>Sign in</Button> : <Button onClick={() => choose("register")}>Create account</Button>}
      {onboarding?.setup_required && onboarding?.setup_authorized && !setup && <Button onClick={() => choose("setup")}>First-time setup</Button>}
      {setup && <Button onClick={() => choose("sign-in")}>Sign in</Button>}
    </div>
    {notice && <p className="notice" role="status">{notice}</p>}
    {error && <p className="notice error" role="alert">{error}</p>}
    <form onSubmit={(event) => {
      event.preventDefault();
      run(async () => {
        try {
          if (setup) {
            await api("/setup", { username, password, setup_token: setupToken });
            setMode("sign-in"); setNotice("Account created. You can now sign in.");
            window.dispatchEvent(new Event("idp-refresh"));
          } else if (registration) {
            await api("/registrations", { username, password });
            setMode("sign-in"); setNotice("Request received. Sign in after your administrator approves your account.");
          } else {
            await api("/login", { username, password });
            onSignedIn(await api<Session>("/session"));
          }
        } finally { setPassword(""); setAgain(""); setSetupToken(""); }
      });
    }}>
      {setup && <TextField label="Setup code" value={setupToken} set={setSetupToken} name="setup_token" type="password" autoComplete="off" required />}
      <TextField label="Account name" value={username} set={setUsername} name="username" autoComplete="username" required />
      <TextField label={registration || setup ? "Password (12–128 characters)" : "Password"} value={password} set={setPassword} name="password" type="password" autoComplete={mode === "sign-in" ? "current-password" : "new-password"} required />
      {mode !== "sign-in" && <TextField label="Repeat password" value={again} set={setAgain} name="repeat_password" type="password" autoComplete="new-password" required />}
      <Button primary type="submit" disabled={busy || !username || !password || ((registration || setup) && (password.length < 12 || password.length > 128 || password !== again)) || (setup && !setupToken)}>
        {busy ? "Please wait..." : registration || setup ? "Create account" : "Sign in"}
      </Button>
    </form>
  </div>;
}
