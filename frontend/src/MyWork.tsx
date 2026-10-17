import { useState } from "react";

import { ArrowLeft, Search } from "lucide-react";
import { Session, RecordData } from "./api";

import {
  useLoad,
  Button,
  Select,
  Confirm,
  Panel,
  State,
  Table,
  Badge,
  Detail,
  words,
  Subtabs,
  PageTitle,
} from "./components";
import { DocumentDetail } from "./Documents";

export function MyWork({ session }: { session: Session }) {
  const [view, setView] = useState("My department"),
    [id, setId] = useState<number>(),
    [search, setSearch] = useState(""),
    [team, setTeam] = useState(""),
    [risk, setRisk] = useState(""),
    [caseStatus, setCaseStatus] = useState(""),
    [closed, setClosed] = useState(false),
    [page, setPage] = useState(1);
  const { data, error } = useLoad(
    "/review?" +
      new URLSearchParams({
        search,
        team: view === "My department" ? team : "",
        view: view === "Assigned to me" ? "mine" : view === "Unclaimed" ? "unclaimed" : view === "Related documents" ? "related" : "department",
        risk,
        case_status: caseStatus,
        include_closed: String(closed),
        page: String(page),
      }),
  );
  return (
    <>
      <PageTitle
        eyebrow="REVIEW & RESOLUTION"
        title="My Work"
        description="Turn document exceptions into clear, traceable decisions."
      />
      <Subtabs
        value={view}
        set={(v) => {
          setView(v);
          setId(undefined);
          setPage(1);
        }}
        items={["Assigned to me", "My department", "Unclaimed", "Related documents"]}
      />
      {id ? (
        <>
          <Button onClick={() => setId(undefined)}>
            <ArrowLeft size={15} />
            Back to queue
          </Button>
          <DocumentDetail id={id} review={view !== "Related documents"} key={id} />
        </>
      ) : (
        <>
          <label className="search">
            <Search size={18} />
            <input
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              placeholder="Search your queue"
              aria-label="Search review queue"
            />
          </label>
          {view !== "Related documents" && <div className="form-grid">
            {view === "My department" && (
              <Select
                label="Department"
                value={team}
                set={setTeam}
                options={["", ...session.departments]}
              />
            )}
            <Select
              label="Risk"
              value={risk}
              set={setRisk}
              options={["", "high", "medium", "low"]}
            />
            <Select
              label="Case status"
              value={caseStatus}
              set={setCaseStatus}
              options={[
                "",
                "open",
                "in_review",
                "on_hold",
                "awaiting_correction",
                "escalated",
                "approved",
                "rejected",
              ]}
            />
          </div>}
          {view !== "Related documents" && <Confirm value={closed} set={setClosed}>
            Include approved and rejected cases
          </Confirm>}
          {view === "Related documents" && <p className="notice">Authorized references from other departments. Viewing these records does not grant review or approval permission.</p>}
          <Panel title={data ? `${data.total} ${view === "Related documents" ? "related documents" : "cases"}` : "Your queue"}>
            {data?.total === 0 && <p className="empty">No cases in this view. You are assigned to {session.departments.join(", ")}. Work appears here when routed, assigned or claimed; other organizational records may still exist.</p>}
            <State error={error} loading={!data && !error} />
            {data && (
              <CaseList rows={data.rows} onOpen={setId} related={view === "Related documents"} />
            )}
          </Panel>
          <div className="pagination">
            <Button disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <span>Page {page}</span>
            <Button
              disabled={page * 20 >= (data?.total ?? 0)}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </>
      )}
    </>
  );
}


const reviewerName = (value: unknown) => {
  const name=String(value ?? "");
  return name.startsWith("user:") ? name.split(":").slice(2).join(":") : name || "Unclaimed";
};

export function CaseList({ rows, onOpen, related }: { rows: RecordData[]; onOpen: (id: number) => void; related: boolean }) {
  if (!rows.length) return null;
  return <div className="case-list">
    <div className="case-table">
      <Table rows={rows} onOpen={onOpen} cells={{assignee: (row) => reviewerName(row.assignee)}} keys={related ? ["filename", "team", "case_status", "assignee", "updated_at"] : ["filename", "team", "case_status", "risk", "priority", "assignee"]} />
    </div>
    <div className="case-cards" aria-label={related ? "Related document cards" : "Department case cards"}>
      {rows.map((row) => <article className="case-card" key={row.id}>
        <h3 className="case-card-filename" title={row.filename}>{row.filename}</h3>
        <p className="footnote">{words(row.document_type)} · {related ? "Read-only reference" : "Department case"}</p>
        <dl className="case-card-fields">
          <div><dt>Department</dt><dd>{row.team ?? "Not recorded"}</dd></div>
          <div><dt>Status</dt><dd><Badge value={row.case_status ?? row.workflow_status} /></dd></div>
          {row.risk != null && <div><dt>Risk</dt><dd><Badge value={row.risk} /></dd></div>}
          {row.priority != null && <div><dt>Priority</dt><dd>{words(row.priority)}</dd></div>}
          <div><dt>Assigned reviewer</dt><dd>{reviewerName(row.assignee)}</dd></div>
          {row.updated_at && <div><dt>Last updated</dt><dd>{row.updated_at}</dd></div>}
        </dl>
        <Detail title="Full filename"><p className="case-full-filename">{row.filename}</p></Detail>
        <Button onClick={() => onOpen(row.id)} aria-label={"Open " + row.filename}>Open document</Button>
      </article>)}
    </div>
  </div>;
}
