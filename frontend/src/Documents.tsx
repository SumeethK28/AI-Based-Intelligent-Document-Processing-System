import { useState, useEffect, useContext } from "react";

import {
  ArrowLeft,
  Search,
  Upload,
  RefreshCw,
  FileText,
  ShieldCheck,
  Check,
  AlertTriangle,
} from "lucide-react";
import { api, download, RecordData } from "./api";

import {
  words,
  ActionContext,
  allowed,
  useLoad,
  Button,
  Field,
  TextField,
  Select,
  Confirm,
  Panel,
  Detail,
  Badge,
  State,
  Table,
  Subtabs,
  Export,
  Metric,
  PageTitle,
} from "./components";

export function Filters({
  filters,
  set,
}: {
  filters: RecordData;
  set: (v: RecordData) => void;
}) {
  const { data } = useLoad("/options");
  const { permissions } = useContext(ActionContext);
  const update = (key: string, value: string) =>
    set({ ...filters, [key]: value });
  return (
    <div className="filters">
      <label className="search">
        <Search size={18} />
        <input
          aria-label="Search documents"
          placeholder="Search documents, numbers or business parties"
          value={filters.search ?? ""}
          onChange={(e) => update("search", e.target.value)}
        />
      </label>
      <Detail title="Filter documents">
        <div className="form-grid">
          {["document_type", "department", "status", "review_decision"].map(
            (key) => (
              <Select
                key={key}
                label={words(key)}
                value={filters[key] ?? ""}
                set={(value) => update(key, value)}
                options={["", ...(data?.[key] ?? [])]}
              />
            ),
          )}
          <TextField
            label="Received from (UTC)"
            type="date"
            value={filters.start_date ?? ""}
            set={(value) => update("start_date", value)}
          />
          <TextField
            label="Received through (UTC)"
            type="date"
            value={filters.end_date ?? ""}
            set={(value) => update("end_date", value)}
          />
          <TextField
            label="Currency code"
            value={filters.currency ?? ""}
            set={(value) => update("currency", value.toUpperCase())}
          />
          <TextField
            label="Minimum extracted amount"
            type="number"
            value={filters.min_amount ?? ""}
            set={(value) => update("min_amount", value)}
          />
          <TextField
            label="Maximum extracted amount"
            type="number"
            value={filters.max_amount ?? ""}
            set={(value) => update("max_amount", value)}
          />
          {allowed(permissions, "intake") && (
            <BatchFilter
              value={filters.batch_id ?? ""}
              set={(value) => update("batch_id", value)}
            />
          )}
        </div>
      </Detail>
    </div>
  );
}

export function BatchFilter({
  value,
  set,
}: {
  value: string;
  set: (v: string) => void;
}) {
  const { data } = useLoad<RecordData[]>("/batches");
  return (
    <Field label="Batch membership">
      <select value={value} onChange={(e) => set(e.target.value)}>
        <option value="">All batches</option>
        {data?.map((job) => (
          <option key={job.id} value={job.id}>
            {job.name}
          </option>
        ))}
      </select>
    </Field>
  );
}

export function Documents({
  initialView = "Repository",
  initialSearch = "",
}: {
  initialView?: string;
  initialSearch?: string;
}) {
  const { permissions } = useContext(ActionContext),
    [view, setView] = useState(initialView),
    [id, setId] = useState<number>(),
    [jobId, setJobId] = useState(""),
    [filters, setFilters] = useState<RecordData>({ search: initialSearch }),
    [page, setPage] = useState(1),
    [sort, setSort] = useState("Newest first");
  const params = new URLSearchParams({ ...filters, page: String(page), sort });
  const { data, error } = useLoad("/documents?" + params);
  useEffect(() => {
    setView(initialView);
    setId(undefined);
    setFilters((v) => ({ ...v, search: initialSearch }));
    setPage(1);
  }, [initialView, initialSearch]);
  return (
    <>
      <PageTitle
        eyebrow="DOCUMENT OPERATIONS"
        title="Documents"
        description="One place for your documents, their evidence, and their progress."
      />
      <Subtabs
        value={view}
        set={(v) => {
          setView(v);
          setId(undefined);
        }}
        items={[
          "Repository",
          ...(allowed(permissions, "intake") ? ["Upload"] : []),
          ...(allowed(permissions, "intake") ? ["Processing jobs"] : []),
        ]}
      />
      {view === "Repository" &&
        (id ? (
          <>
            <Button onClick={() => setId(undefined)}>
              <ArrowLeft size={15} />
              Back to repository
            </Button>
            <DocumentDetail id={id} />
          </>
        ) : (
          <>
            <Filters
              filters={filters}
              set={(v) => {
                setFilters(v);
                setPage(1);
              }}
            />
            <Panel
              title={data ? `${data.total} documents` : "Document repository"}
              action={
                allowed(permissions, "export") && (
                  <div className="actions">
                    <Export
                      kind="filtered_json"
                      resource={{ filters }}
                      label="JSON"
                    />
                    <Export
                      kind="filtered_csv"
                      resource={{ filters }}
                      label="CSV"
                    />
                  </div>
                )
              }
            >
              <Select
                label="Sort documents"
                value={sort}
                set={(value) => {
                  setSort(value);
                  setPage(1);
                }}
                options={["Newest first", "Oldest first", "Filename"]}
              />
              <State error={error} loading={!data && !error} />
              {data && (
                <Table
                  rows={data.rows}
                  onOpen={setId}
                  keys={[
                    "filename",
                    "assigned_department",
                    "validation_passed",
                    "cross_document_status",
                    "workflow_status",
                    "review_decision",
                  ]}
                />
              )}
            </Panel>
            <div className="pagination">
              <Button
                disabled={page === 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </Button>
              <span>
                Page {page} of {Math.max(1, Math.ceil((data?.total ?? 0) / 20))}
              </span>
              <Button
                disabled={page * 20 >= (data?.total ?? 0)}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </>
        ))}
      {view === "Upload" && (
        <UploadForm
          onSaved={(job) => {
            setJobId(job);
            setView("Processing jobs");
          }}
        />
      )}
      {view === "Processing jobs" && (
        <Batches initialId={jobId} navigate={setView} />
      )}
    </>
  );
}

export function Issues({ state }: { state: RecordData }) {
  const checks = [
    ...(state.validation_errors ?? []),
    ...(state.validation_warnings ?? []),
    ...(state.cross_document_issues ?? []),
    ...(state.anomalies ?? []),
  ];
  const messages = [
    ...new Set(
      checks.map((item: any) =>
        typeof item === "string" ? item : (item.description ?? item.code),
      ),
    ),
  ];
  return (
    <>
      {messages.map((text, i) => (
        <div key={i} className="notice warning">
          <AlertTriangle size={17} />
          <span>{text}</span>
        </div>
      ))}
    </>
  );
}

export function DocumentDetail({
  id,
  review = false,
}: {
  id: number;
  review?: boolean;
}) {
  const { data, error } = useLoad("/documents/" + id),
    { permissions, run } = useContext(ActionContext),
    [source, setSource] = useState("");
  useEffect(() => {
    setSource("");
    return () => {};
  }, [id]);
  useEffect(
    () => () => {
      if (source) URL.revokeObjectURL(source);
    },
    [source],
  );
  if (!data) return <State error={error} loading={!error} />;
  const state = data.full_result,
    fields = state.extracted_fields ?? {};
  const groups: RecordData = {
    "Document identity": [
      "invoice_number",
      "po_number",
      "receipt_number",
      "contract_number",
      "contract_title",
    ],
    "Business parties": [
      "seller",
      "client",
      "vendor",
      "buyer",
      "party_a",
      "party_b",
      "tax_id",
      "iban",
    ],
    "Dates & terms": [
      "issue_date",
      "order_date",
      "effective_date",
      "expiration_date",
      "governing_law",
      "payment_method",
      "po_reference",
    ],
    Amounts: ["total", "subtotal", "tax", "contract_value"],
  };
  return (
    <div className="document-detail">
      <div className="document-heading">
        <div className="document-icon">
          <FileText size={24} />
        </div>
        <div>
          <span className="eyebrow">
            {words(state.document_type)} · DOCUMENT {id}
          </span>
          <h2>{data.filename}</h2>
          <p>
            {state.assigned_department} · Revision {data.revision}
          </p>
        </div>
        {allowed(permissions, "export") && (
          <Export
            kind="document_json"
            resource={{ document_id: id }}
            label="Export"
          />
        )}
      </div>
      <Panel title="Responsibility & collaboration">
        <div className="status-strip">
          <div><small>Originally routed to</small><strong>{data.collaboration?.original_department ?? "Not recorded"}</strong></div>
          <div><small>Current owner</small><strong>{data.case?.team ?? "Not recorded"}</strong></div>
          <div><small>Assigned reviewer</small><strong>{data.case?.assignee ? String(data.case.assignee).split(":").slice(2).join(":") : "Unclaimed"}</strong></div>
          <div><small>Uploaded by</small><strong>{data.collaboration?.uploaded_by?.username ?? "Not recorded"}</strong></div>
          <div><small>Processed by</small><strong>{data.collaboration?.processed_by?.username ?? "Not recorded"}</strong></div>
          <div><small>Last updated</small><strong>{data.collaboration?.last_updated ?? data.updated_at}</strong></div>
        </div>
        <p className="footnote">{data.collaboration?.can_review ? "This case is in your authorized work scope. Review safeguards still apply." : "Read-only access. Your account cannot change or approve this case."} Workflow routing and current case ownership are shown separately.</p>
        {!!data.collaboration?.related_documents?.length && <Detail title="Related documents">
          <Table rows={data.collaboration.related_documents} keys={["filename", "team", "assignee", "case_status", "review_decision", "last_updated"]} />
          {data.collaboration.related_documents.map((linked: RecordData) => <Detail key={linked.id} title={`${linked.filename} · read-only reference`}><LinkedDocument id={linked.id} /></Detail>)}
        </Detail>}
      </Panel>
      <div className="status-strip">
        {[
          ["Workflow", state.workflow_status],
          [
            "Validation",
            state.validation_passed ? "Passed" : "Needs attention",
          ],
          ["PO verification", state.cross_document_status],
          ["Risk", state.risk_level],
          ["Human decision", data.review_decision],
        ].map(([label, value]) => (
          <div key={label}>
            <small>{label}</small>
            <Badge value={value} />
          </div>
        ))}
      </div>
      <div className="notice">
        <ShieldCheck size={18} />
        <span>
          {state.routing_reason ?? "Routing explanation unavailable."}{" "}
          Preliminary checks never authorize a payment or legal agreement.
        </span>
      </div>
      <Issues state={state} />
      {(state.rule_outcomes ?? [])
        .filter((r: any) => r.escalates)
        .map((r: any, i: number) => (
          <p key={i} className="notice warning">
            {r.description}
          </p>
        ))}
      <div className="document-columns">
        <div>
          <Panel title="Extracted information">
            {Object.entries(groups).map(([title, names]) => {
              const found = names.filter((name: string) => name in fields);
              return found.length ? (
                <div className="field-group" key={title}>
                  <h3>{title}</h3>
                  <dl>
                    {found.map((name: string) => (
                      <div key={name}>
                        <dt>
                          {words(name === "tax_id" ? "seller tax ID" : name)}
                        </dt>
                        <dd>
                          {fields[name] || (
                            <span className="muted">Not extracted</span>
                          )}
                        </dd>
                        {state.field_evidence?.[name] && (
                          <p className="field-evidence">
                            <span>Source evidence</span>
                            {String(state.field_evidence[name])}
                          </p>
                        )}
                      </div>
                    ))}
                  </dl>
                </div>
              ) : null;
            })}
            {!Object.keys(fields).length && (
              <p>No structured fields were extracted.</p>
            )}
            {!!state.missing_optional_fields?.length && (
              <p className="footnote">
                Optional information unavailable:{" "}
                {state.missing_optional_fields.map(words).join(", ")}.
              </p>
            )}
            <Detail title="Additional extracted fields">
              <Table
                rows={Object.entries(fields)
                  .filter(
                    ([name]) => !Object.values(groups).flat().includes(name),
                  )
                  .map(([field, value]) => ({ field, value }))}
              />
            </Detail>
          </Panel>
          <Panel title="Evidence & verification">
            <Detail title="Field evidence and provenance">
              <dl>
                {Object.entries(state.field_evidence ?? {}).map(
                  ([field, quote]) => (
                    <div key={field}>
                      <dt>{words(field)}</dt>
                      <dd className="quote">{String(quote)}</dd>
                      <small>
                        {state.field_provenance?.[field]?.source ===
                        "human_correction"
                          ? "Recorded human correction"
                          : state.fallback_used?.includes(field)
                            ? "Verified OCR/layout recovery"
                            : "Model extraction"}
                      </small>
                    </div>
                  ),
                )}
              </dl>
              <Issues
                state={{
                  validation_errors: state.unsupported_contract_reasons,
                }}
              />
            </Detail>
            <Detail title="Purchase order comparison">
              <Badge value={state.cross_document_status} />
              {state.matched_document_id && (
                <>
                  <p>
                    Linked Purchase Order · document {state.matched_document_id}
                  </p>
                  <LinkedDocument id={state.matched_document_id} />
                </>
              )}
              <Issues
                state={{ cross_document_issues: state.cross_document_issues }}
              />
            </Detail>
            <Detail title="Recognized text and technical details">
              <pre>{state.ocr_text || "No recognized text recorded."}</pre>
              <pre>
                {JSON.stringify(
                  {
                    agent_history: state.agent_history,
                    rule_outcomes: state.rule_outcomes,
                    field_provenance: state.field_provenance,
                    ocr_confidence: state.ocr_confidence,
                    classification_confidence: state.classification_confidence,
                    extraction_confidence: state.extraction_confidence,
                    policy_version_id: state.policy_version_id,
                  },
                  null,
                  2,
                )}
              </pre>
            </Detail>
          </Panel>
        </div>
        <div>
          <Panel title="Original source">
            {data.sources.length && allowed(permissions, "source") ? (
              <>
                <p className="muted">
                  Retained source · verified against its stored hash.
                </p>
                <div className="actions">
                  <Button
                    onClick={() =>
                      run(async () =>
                        setSource(
                          await download(
                            "source",
                            { item_id: data.sources[0].id },
                            true,
                          ),
                        ),
                      )
                    }
                  >
                    Open preview
                  </Button>
                  <Export
                    kind="source"
                    resource={{ item_id: data.sources[0].id }}
                    label="Download source"
                  />
                </div>
                {source && (
                  <iframe
                    className="source-preview"
                    title="Authorized original source"
                    src={source}
                    sandbox=""
                  />
                )}
              </>
            ) : (
              <div className="empty small">
                <FileText />
                <p>No retained source is available for this document.</p>
                <small>
                  Single uploads are temporary. Extracted data and processing
                  history remain preserved.
                </small>
              </div>
            )}
          </Panel>
          {review && data.collaboration?.can_review && (
            <ReviewActions document={data} />
          )}
          <Panel title="History & audit">
            <Detail title="Review and case events">
              <Table
                rows={data.events}
                keys={[
                  "event_type",
                  "actor",
                  "actor_kind",
                  "decision",
                  "reason",
                  "created_at",
                ]}
              />
              <Detail title="Full event details">
                <pre>{JSON.stringify(data.events, null, 2)}</pre>
              </Detail>
            </Detail>
            <Detail title="Processing history">
              <Table
                rows={data.runs}
                keys={["id", "processed_at", "is_duplicate"]}
              />
              <pre>{JSON.stringify(data.runs, null, 2)}</pre>
            </Detail>
            <Detail title="Preserved processing originals">
              <pre>{JSON.stringify(data.versions, null, 2)}</pre>
            </Detail>
            <Detail title="Recorded policy checks">
              <pre>{JSON.stringify(state.rule_outcomes, null, 2)}</pre>
            </Detail>
          </Panel>
        </div>
      </div>
    </div>
  );
}

export function LinkedDocument({ id }: { id: number }) {
  const { data, error } = useLoad("/documents/" + id);
  return data ? (
    <div><p className="footnote">Read-only reference · {data.case?.team} · {words(data.review_decision)}. Last updated: {data.collaboration?.last_updated}.</p><dl>
      {Object.entries(data.extracted_data ?? {}).map(([k, v]) => (
        <div key={k}>
          <dt>{words(k)}</dt>
          <dd>{String(v ?? "—")}</dd>
        </div>
      ))}
    </dl><Detail title="Previous reviewer activity"><Table rows={data.events} keys={["actor", "event_type", "decision", "reason", "created_at"]} /></Detail></div>
  ) : (
    <State error={error} loading={!error} />
  );
}

export function ReviewActions({ document: doc }: { document: RecordData }) {
  const { run, permissions } = useContext(ActionContext),
    [decision, setDecision] = useState("needs_correction"),
    [reason, setReason] = useState(""),
    [notes, setNotes] = useState(""),
    [confirmed, setConfirmed] = useState(false);
  const [changes, setChanges] = useState<RecordData>({
      ...doc.editable_fields,
    }),
    [evidence, setEvidence] = useState<RecordData>({
      ...doc.full_result.field_evidence,
    }),
    [preview, setPreview] = useState<RecordData>(),
    [action, setAction] = useState("claim"),
    [team, setTeam] = useState(doc.case?.team ?? "Finance"),
    [assignee, setAssignee] = useState(""),
    [status, setStatus] = useState("in_review"),
    [priority, setPriority] = useState("normal"),
    [version, setVersion] = useState("1");
  const stamp = JSON.stringify([changes, evidence]);
  const mutate = (path: string, body: RecordData) =>
    run(async () => {
      await api("/documents/" + doc.id + "/" + path, {
        ...body,
        expected_revision: doc.revision,
        reason,
        confirmed,
      });
      setConfirmed(false);
    });
  return (
    <Panel title="Your review">
      <p className="footnote">
        Only a fresh, evidence-supported result can be approved. Every saved
        action records your authenticated identity.
      </p>
      <TextField
        label="Reason for this action"
        value={reason}
        set={setReason}
        required
      />
      <Confirm value={confirmed} set={setConfirmed}>
        I have checked the evidence and confirm this action.
      </Confirm>
      <Select
        label="Review decision"
        value={decision}
        set={setDecision}
        options={["approved", "rejected", "needs_correction", "escalated"]}
      />
      <Field label="Review notes">
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
      <Button
        primary
        disabled={!confirmed || !reason.trim()}
        onClick={() => mutate("decision", { decision, notes })}
      >
        <Check size={16} />
        Save review decision
      </Button>
      <Detail title="Correct extracted fields">
        {Object.keys(changes).map((field) => (
          <div key={field} className="correction-field">
            <TextField
              label={words(field)}
              value={String(changes[field] ?? "")}
              set={(v) => {
                setChanges({ ...changes, [field]: v });
                setPreview(undefined);
              }}
            />
            <Field label="Original OCR evidence quote">
              <textarea
                value={evidence[field] ?? ""}
                onChange={(e) => {
                  setEvidence({ ...evidence, [field]: e.target.value });
                  setPreview(undefined);
                }}
              />
            </Field>
          </div>
        ))}
        <Button
          onClick={() =>
            run(async () =>
              setPreview({
                ...(await api("/documents/" + doc.id + "/correction-preview", {
                  changes,
                  evidence,
                })),
                stamp,
              }),
            )
          }
        >
          Preview checks
        </Button>
        {preview && (
          <>
            <Issues state={preview.state} />
            <Badge
              value={
                preview.state.validation_passed ? "Passed" : "Needs attention"
              }
            />
            <pre>{JSON.stringify(preview.state.rule_outcomes, null, 2)}</pre>
          </>
        )}
        <Button
          disabled={!confirmed || !reason || preview?.stamp !== stamp}
          onClick={() => mutate("correction", { changes, evidence })}
        >
          Save corrections
        </Button>
      </Detail>
      <Detail title="Claim, assign or update case">
        <Select
          label="Case action"
          value={action}
          set={setAction}
          options={[
            "claim",
            "handoff",
            ...(allowed(permissions, "assign") ? ["assign"] : []),
            "status",
            "priority",
          ]}
        />
        {action === "handoff" && <Select label="Send to responsible department" value={team} set={setTeam} options={["", ...(doc.collaboration?.handoff_departments ?? [])]} />}
        {action === "assign" && (
          <>
            <Select
              label="Team"
              value={team}
              set={setTeam}
              options={[
                "Finance",
                "Procurement",
                "Expense Processing",
                "Legal",
                "Document Review",
                "Risk Review",
                "Document Operations",
              ]}
            />
            <AssigneeField team={team} value={assignee} set={setAssignee} />
          </>
        )}
        {action === "status" && (
          <Select
            label="Working status"
            value={status}
            set={setStatus}
            options={["open", "in_review", "on_hold"]}
          />
        )}
        {action === "priority" && (
          <Select
            label="Priority"
            value={priority}
            set={setPriority}
            options={["normal", "high", "urgent"]}
          />
        )}
        <Button
          disabled={!confirmed || !reason}
          onClick={() =>
            mutate("case", { action, team, assignee, status, priority })
          }
        >
          Save case action
        </Button>
      </Detail>
      {allowed(permissions, "policy") && (
        <Detail title="Reevaluate with a policy version">
          <TextField
            label="Policy version"
            value={version}
            set={setVersion}
            type="number"
          />
          <p className="footnote">
            Reevaluation records a new revision. Original processing remains
            preserved.
          </p>
          <Button
            disabled={!confirmed || !reason}
            onClick={() =>
              mutate("reevaluate", { version_id: Number(version) })
            }
          >
            Reevaluate policy
          </Button>
        </Detail>
      )}
    </Panel>
  );
}

export function AssigneeField({
  team,
  value,
  set,
}: {
  team: string;
  value: string;
  set: (v: string) => void;
}) {
  const { data } = useLoad("/users");
  const users = (data?.users ?? []).filter(
    (u: any) =>
      u.active &&
      (u.role === "Administrator" ||
        (u.role.endsWith("Reviewer") &&
          JSON.parse(u.departments).includes(team))),
  );
  return (
    <Field label="Assign to reviewer">
      <select value={value} onChange={(e) => set(e.target.value)}>
        <option value="">Unassigned</option>
        {users.map((u: any) => (
          <option key={u.id} value={`user:${u.id}:${u.username}`}>
            {u.username}
          </option>
        ))}
      </select>
    </Field>
  );
}

export function UploadForm({ onSaved }: { onSaved: (id: string) => void }) {
  const { run, permissions } = useContext(ActionContext),
    [files, setFiles] = useState<File[]>([]),
    [name, setName] = useState("Document upload"),
    [description, setDescription] = useState(""),
    [consent, setConsent] = useState(false),
    [force, setForce] = useState(false),
    [preview, setPreview] = useState<RecordData>(),
    [key, setKey] = useState(crypto.randomUUID());
  const form = () => {
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    body.append("name", name);
    body.append("description", description);
    body.append("consent", String(consent));
    body.append("force", String(force));
    body.append("request_key", key);
    return body;
  };
  return (
    <Panel title="Upload documents">
      <ol className="upload-steps" aria-label="Document processing workflow">
        <li>
          <strong>1</strong>Select documents
        </li>
        <li>
          <strong>2</strong>Check files
        </li>
        <li>
          <strong>3</strong>Process & verify
        </li>
        <li>
          <strong>4</strong>Review & analyse
        </li>
      </ol>
      <p className="muted">
        Upload the document types handled by your department. Administrators can select mixed invoices, purchase orders, receipts or contracts
        together. PDF, PNG or JPEG · 20 MB per file · up to 50 files / 100 MB
        per upload.
      </p>
      <Detail title="Upload name and description (optional)">
        <TextField
          label="Upload name"
          value={name}
          set={(v) => {
            setName(v);
            setKey(crypto.randomUUID());
          }}
        />
        <TextField
          label="Description (optional)"
          value={description}
          set={setDescription}
        />
      </Detail>
      <label className="upload-zone">
        <div className="upload-art" aria-hidden="true">
          <span>PDF</span>
          <FileText size={38} />
          <span>IMG</span>
        </div>
        <strong>
          {files.length
            ? `${files.length} document${files.length === 1 ? "" : "s"} selected`
            : "Choose documents to upload"}
        </strong>
        <span>
          Choose a source. We’ll extract, verify and route it for review.
        </span>
        <input
          aria-label="Choose documents"
          type="file"
          accept=".pdf,.png,.jpg,.jpeg"
          multiple
          onChange={(e) => {
            setFiles(Array.from(e.target.files ?? []));
            setPreview(undefined);
            setKey(crypto.randomUUID());
          }}
        />
      </label>
      <ul className="file-list">
        {files.map((f) => (
          <li key={f.name}>
            {f.name}
            <small>{(f.size / 1024).toFixed(0)} KB</small>
          </li>
        ))}
      </ul>
      {allowed(permissions, "process") && (
      <Confirm
        value={force}
        set={(v) => {
          setForce(v);
          setKey(crypto.randomUUID());
        }}
      >
        Force reprocessing of existing documents. This uses API quota and resets
        review decisions.
      </Confirm>
      )}
      <Confirm value={consent} set={setConsent}>
        I authorize sending these documents’ OCR text to Groq and retaining
        their sources locally under the configured retention policy.
      </Confirm>
      <div className="actions">
        <Button
          disabled={!files.length}
          onClick={() =>
            run(async () => setPreview(await api("/uploads/preview", form())))
          }
        >
          Check selected files
        </Button>
        {preview && (
          <Table
            rows={preview.rows}
            keys={["filename", "accepted", "duplicate", "message"]}
            cells={{
              accepted: (row) => (
                <Badge value={row.accepted ? "Ready" : "Not accepted"} />
              ),
              duplicate: (row) => (
                <span>{row.duplicate ? "Already stored" : "New document"}</span>
              ),
            }}
          />
        )}
      </div>
      <Button
        primary
        disabled={
          !files.length ||
          !consent ||
          !preview?.rows.some((r: any) => r.accepted)
        }
        onClick={() =>
          run(async () => {
            const result = await api("/uploads/batch", form());
            onSaved(result.batch_id);
            await api("/batches/" + result.batch_id + "/run", {
              consent: true,
            });
          })
        }
      >
        <Upload size={17} />
        Process documents
      </Button>
      <p className="footnote">
        Originals and progress are saved before processing starts. Exact
        duplicates reuse existing results unless forced reprocessing is
        selected. Completed records appear in the repository, exceptions in My
        Work, and saved results in Insights. No payment or legal action is
        executed.
      </p>
    </Panel>
  );
}

export function Batches({
  initialId = "",
  navigate,
}: {
  initialId?: string;
  navigate: (view: string) => void;
}) {
  const [id, setId] = useState(initialId),
    [documentId, setDocumentId] = useState<number>(),
    [consent, setConsent] = useState(false),
    { run, permissions, busy } = useContext(ActionContext),
    { data, error } = useLoad<RecordData[]>("/batches");
  const details = useLoad(id ? "/batches/" + id : "/batches");
  const pending =
    !!details.data &&
    !Array.isArray(details.data) &&
    (details.data.counts?.queued ?? 0) +
      (details.data.counts?.processing ?? 0) >
      0;
  useEffect(() => {
    setId(initialId);
    setDocumentId(undefined);
    setConsent(false);
  }, [initialId]);
  useEffect(() => {
    if (!id || !pending) return;
    const timer = window.setInterval(details.reload, 2000);
    return () => window.clearInterval(timer);
  }, [id, pending]);
  return (
    <>
      <Panel
        title="Processing jobs"
        action={
          <Button
            onClick={() => window.dispatchEvent(new Event("idp-refresh"))}
          >
            <RefreshCw size={15} />
            Refresh
          </Button>
        }
      >
        <State error={error} loading={!data && !error} />
        {data && (
          <Field label="Open an upload job">
            <select
              value={id}
              onChange={(e) => {
                setId(e.target.value);
                setDocumentId(undefined);
                setConsent(false);
              }}
            >
              <option value="">Choose an upload</option>
              {data.map((job) => (
                <option key={job.id} value={job.id}>
                  {job.name} · {job.created_at}
                </option>
              ))}
            </select>
          </Field>
        )}
      </Panel>
      <div className="notice">
        <ShieldCheck size={18} />
        <span>
          Each upload is saved as a processing job, whether it contains one file
          or many. Sources, attempts and results remain traceable. Use the
          repository for ongoing document work, My Work for review decisions,
          and Insights for analysis.
        </span>
      </div>
      <Button onClick={() => navigate("Repository")}>
        Open document repository
      </Button>
      {id && details.data && !Array.isArray(details.data) && (
        <Panel title="Processing progress">
          <div className="metrics">
            {Object.entries(details.data.counts ?? {}).map(([label, value]) => (
              <Metric key={label} label={words(label)} value={value} />
            ))}
          </div>
          {pending && !busy && (
            <Confirm value={consent} set={setConsent}>
              I authorize external Groq processing to resume this saved upload.
            </Confirm>
          )}
          <div className="actions">
            {pending && !busy && (
              <Button
                primary
                disabled={!consent}
                onClick={() =>
                  run(() => api("/batches/" + id + "/run", { consent }))
                }
              >
                Resume processing
              </Button>
            )}
            <Button onClick={details.reload}>
              <RefreshCw size={15} />
              Refresh progress
            </Button>
            {allowed(permissions, "export") && (
              <>
                <Export
                  kind="batch_json"
                  resource={{ batch_id: id }}
                  label="JSON"
                />
                <Export
                  kind="batch_csv"
                  resource={{ batch_id: id }}
                  label="CSV"
                />
              </>
            )}
          </div>
          <p className="footnote">
            Progress refreshes while files are queued or processing. Keep the
            local server running. If processing is interrupted, open this saved
            job and resume; completed items are reused. Processing is serial,
            and invoice/PO checks are reconciled after the job completes.
          </p>
          <Table
            rows={details.data.items ?? []}
            keys={["id", "filename", "state", "attempts", "safe_error"]}
          />
          <Field label="Inspect a completed document">
            <select
              value={documentId ?? ""}
              onChange={(e) =>
                setDocumentId(Number(e.target.value) || undefined)
              }
            >
              <option value="">Choose a document</option>
              {(details.data.items ?? [])
                .filter((item: any) => item.document_id)
                .map((item: any) => (
                  <option key={item.id} value={item.document_id}>
                    {item.filename}
                  </option>
                ))}
            </select>
          </Field>
          {documentId && <DocumentDetail id={documentId} />}
          {(details.data.items ?? [])
            .filter((item: any) => item.state === "failed")
            .map((item: any) => (
              <Button
                key={item.id}
                disabled={item.attempts >= 5}
                onClick={() =>
                  run(() => api("/batch-items/" + item.id + "/retry", {}))
                }
              >
                Retry {item.filename}
              </Button>
            ))}
          <Detail title="Attempt history">
            <pre>{JSON.stringify(details.data.attempts, null, 2)}</pre>
          </Detail>
          <Detail title="Outcomes and financial totals">
            <Table rows={details.data.financial_totals ?? []} />
            <pre>{JSON.stringify(details.data.distributions, null, 2)}</pre>
          </Detail>
        </Panel>
      )}
    </>
  );
}
