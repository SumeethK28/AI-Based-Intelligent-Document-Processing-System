import { useState, useContext } from "react";

import {
  ArrowUpRight,
  Upload,
  Files,
  ShieldCheck,
  CircleAlert,
  ClipboardCheck,
} from "lucide-react";
import { RecordData, Session } from "./api";

import {
  ActionContext,
  allowed,
  useLoad,
  Button,
  Panel,
  Detail,
  State,
  Table,
  Metric,
} from "./components";
import { Filters } from "./Documents";

export function Overview({ navigate, session }: { navigate: (v: string) => void; session: Session }) {
  const [filters, setFilters] = useState<RecordData>({});
  const { data, error, loading } = useLoad(
      "/overview?" + new URLSearchParams(filters),
      true,
    ),
    { permissions } = useContext(ActionContext);
  if (error)
    return (
      <>
        <h1>Workspace overview</h1>
        <Filters filters={filters} set={setFilters} />
        <State error={error} loading={false} />
      </>
    );
  if (!data) return <State loading />;
  return (
    <>
      <div className="intro">
        <div>
          <span className="eyebrow">YOUR OPERATION, AT A GLANCE</span>
          <h1>Workspace overview</h1>
          <p>
            Know what is ready, what needs attention, and where work is waiting.
          </p>
        </div>
        {allowed(permissions, "intake") && (
          <Button primary onClick={() => navigate("Documents")}>
            <Upload size={17} />
            Open documents
          </Button>
        )}
      </div>
      <Panel title={`Welcome, ${session.username}`}>
        <p>{session.role} · {session.departments.join(", ")}</p>
        {data.employee_work && <>
          <div className="metrics secondary">
            <Metric label="Assigned to me" value={data.employee_work.assigned_to_me} />
            <Metric label="Unclaimed department cases" value={data.employee_work.unclaimed} />
            <Metric label="Department awaiting action" value={data.employee_work.department_cases} />
            <Metric label="Reconciliation issues" value={data.employee_work.reconciliation_issues} />
          </div>
          {data.employee_work.department_cases === 0 && <p className="empty">You have no department cases awaiting action. New work will appear when routed or assigned; this does not mean the organization has no documents.</p>}
          <Button onClick={() => navigate("My Work")}>Open my work</Button>
          <Detail title="Recent department decisions"><Table rows={data.employee_work.recent_decisions} /></Detail>
          {data.employee_work.previous_sign_in && <Detail title="Changes since your previous sign-in">
            <p className="footnote">Since {data.employee_work.previous_sign_in} · recorded updates only</p>
            <Table rows={data.employee_work.recent_changes} />
          </Detail>}
        </>}
      </Panel>
      <Filters filters={filters} set={setFilters} />
      {loading && (
        <p className="loading" role="status">
          Updating the filtered overview…
        </p>
      )}
      {allowed(permissions, "review") && (
        <div className="actions">
          <Button onClick={() => navigate("My Work")}>
            <ClipboardCheck size={16} />
            Open review queue
          </Button>
        </div>
      )}
      <div className="workspace-summary">
        <div className="summary-symbol">
          <ShieldCheck size={22} />
        </div>
        <div>
          <span className="eyebrow">DOCUMENT READINESS</span>
          <p>
            <strong>{data.unique_documents} unique documents</strong> in the
            current view. {data.review_exceptions} pending exceptions and{" "}
            {data.pending_decisions} documents awaiting a human decision.
          </p>
          <small>
            Based on saved records and current filters. Preliminary validation
            is separate from human approval.
          </small>
        </div>
      </div>
      <div className="metrics">
        <Metric
          label="Unique documents"
          tone="blue"
          icon={<Files size={21} />}
          value={data.unique_documents}
          note="Each document counted once"
        />
        <Metric
          label="Checks passed"
          icon={<ShieldCheck size={21} />}
          tone="good"
          value={data.validated}
          note="Preliminary validation"
        />
        <Metric
          label="Needs attention"
          icon={<CircleAlert size={21} />}
          tone={data.review_exceptions > 0 ? "warning" : "neutral"}
          value={data.review_exceptions}
          note="Pending exceptions"
        />
        <Metric
          label="Awaiting a decision"
          tone="violet"
          icon={<ClipboardCheck size={21} />}
          value={data.pending_decisions}
          note="Across authorized teams"
        />
      </div>
      <Panel
        title="Processing activity"
        action={
          <span className="chart-key">
            <i /> Submissions <i className="duplicate-key" /> Duplicate
            submissions
          </span>
        }
      >
        {(data.daily ?? []).length ? (
          <div
            className="activity-chart"
            role="img"
            aria-label="Submission counts by recorded UTC date. Exact values follow in the table."
          >
            {data.daily.map((row: RecordData) => {
              const maximum = Math.max(
                1,
                ...data.daily.map((r: RecordData) => Number(r.submissions)),
              );
              return (
                <div className="activity-day" key={row.day}>
                  <div className="activity-columns">
                    <div
                      style={{
                        height: `${(Number(row.submissions) / maximum) * 100}%`,
                      }}
                    >
                      <span>{row.submissions}</span>
                    </div>
                    <div
                      className="duplicate-column"
                      style={{
                        height: `${(Number(row.duplicates) / maximum) * 100}%`,
                      }}
                    >
                      <span>{row.duplicates}</span>
                    </div>
                  </div>
                  <small>{row.day}</small>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="empty">No processing activity in the current view.</p>
        )}
        <p className="footnote">
          Recorded dates only · counts include duplicate submissions · UTC
        </p>
        <details>
          <summary>Exact activity counts</summary>
          <div className="detail-body">
            <Table rows={data.daily ?? []} />
          </div>
        </details>
      </Panel>
      <div className="two-columns">
        <Panel title="Team workload">
          <Table rows={data.departments} />
        </Panel>
        <Panel title="Invoice values">
          <Table rows={data.invoice_values} />
          <p className="footnote">
            Extracted values by currency and decision. These are not payments or
            revenue.
          </p>
        </Panel>
      </div>
      <Panel
        title="Recent activity"
        action={
          allowed(permissions, "documents") ? (
            <Button onClick={() => navigate("Documents")}>
              View documents
              <ArrowUpRight size={15} />
            </Button>
          ) : undefined
        }
      >
        <Table rows={data.activity} />
      </Panel>
      <div className="metrics secondary">
        <Metric label="Submissions" value={data.submissions} />
        <Metric label="Duplicates reused" value={data.duplicate_submissions} />
        <Metric label="PO mismatches" value={data.po_mismatches} />
        <Metric label="Department queue" value={data.department_pending} />
      </div>
    </>
  );
}
