import { useState } from "react";

import { ArrowLeft, Search } from "lucide-react";
import { Session } from "./api";

import {
  useLoad,
  Button,
  TextField,
  Select,
  Confirm,
  Panel,
  State,
  Table,
  Subtabs,
  PageTitle,
} from "./components";
import { DocumentDetail } from "./Documents";

export function MyWork({ session }: { session: Session }) {
  const [view, setView] = useState("Review queue"),
    [id, setId] = useState<number>(),
    [search, setSearch] = useState(""),
    [team, setTeam] = useState(""),
    [risk, setRisk] = useState(""),
    [caseStatus, setCaseStatus] = useState(""),
    [closed, setClosed] = useState(false),
    [page, setPage] = useState(1),
    [owner, setOwner] = useState("");
  const { data, error } = useLoad(
    "/review?" +
      new URLSearchParams({
        search,
        team: view === "Department work" ? team : "",
        risk,
        case_status: caseStatus,
        include_closed: String(closed),
        page: String(page),
        assignee: owner,
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
        }}
        items={["Review queue", "Department work"]}
      />
      {id ? (
        <>
          <Button onClick={() => setId(undefined)}>
            <ArrowLeft size={15} />
            Back to queue
          </Button>
          <DocumentDetail id={id} review key={id} />
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
          <div className="form-grid">
            {view === "Department work" && (
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
            <TextField
              label="Assigned reviewer identity"
              value={owner}
              set={setOwner}
            />
          </div>
          <Confirm value={closed} set={setClosed}>
            Include approved and rejected cases
          </Confirm>
          <Panel title={data ? `${data.total} cases` : "Your queue"}>
            <State error={error} loading={!data && !error} />
            {data && (
              <Table
                rows={data.rows}
                onOpen={setId}
                keys={[
                  "filename",
                  "team",
                  "case_status",
                  "risk",
                  "priority",
                  "assignee",
                ]}
              />
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
