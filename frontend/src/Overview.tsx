import { useState, useContext } from "react";

import {
  ArrowUpRight,
  Upload,
  Files,
  ShieldCheck,
  CircleAlert,
  ClipboardCheck,
} from "lucide-react";
import { RecordData } from "./api";

import {
  ActionContext,
  allowed,
  useLoad,
  Button,
  Panel,
  State,
  Table,
  Metric,
} from "./components";
import { Filters } from "./Documents";

export function Overview({ navigate }: { navigate: (v: string) => void }) {
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
        {allowed(permissions, "process") && (
          <Button primary onClick={() => navigate("Documents")}>
            <Upload size={17} />
            Open documents
          </Button>
        )}
      </div>
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
