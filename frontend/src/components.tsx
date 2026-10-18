import {
  useState,
  useEffect,
  useContext,
  createContext,
  ReactNode,
} from "react";

import * as Tabs from "@radix-ui/react-tabs";
import { ArrowUpRight, ChevronRight, Download, FileText } from "lucide-react";
import { api, download, RecordData } from "./api";
import { words, statusLabel, businessText, optionLabel } from "./presentation";
export { words } from "./presentation";

export const message = (error: unknown) =>
  error instanceof Error
    ? businessText(error.message)
    : "The operation could not be completed.";
export const ActionContext = createContext({
  run: async (job: () => Promise<unknown>) => {
    await job();
  },
  busy: false,
  permissions: [] as string[],
});
export const allowed = (permissions: string[], key: string) =>
  permissions.includes(key);

export function useLoad<T = RecordData>(path: string, keepPrevious = false) {
  const [data, setData] = useState<T>(),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [revision, setRevision] = useState(0);
  useEffect(() => {
    const refresh = () => setRevision((n) => n + 1);
    window.addEventListener("idp-refresh", refresh);
    return () => window.removeEventListener("idp-refresh", refresh);
  }, []);
  useEffect(() => {
    let current = true;
    setError("");
    setLoading(true);
    if (!keepPrevious) setData(undefined);
    api<T>(path)
      .then((v) => {
        if (current) setData(v);
      })
      .catch((e) => {
        if (current) setError(message(e));
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [path, revision, keepPrevious]);
  return { data, error, loading, reload: () => setRevision((n) => n + 1) };
}

export function Button({
  children,
  onClick,
  primary = false,
  disabled = false,
  type = "button",
  ...props
}: {
  children: ReactNode;
  onClick?: () => void;
  primary?: boolean;
  disabled?: boolean;
  type?: "button" | "submit";
  [key: string]: unknown;
}) {
  const { busy } = useContext(ActionContext);
  return (
    <button
      {...props}
      type={type}
      disabled={busy || disabled}
      className={"button " + (primary ? "primary" : "")}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function TextField({
  label,
  value,
  set,
  type = "text",
  required = false,
  name,
  autoComplete,
}: {
  label: string;
  value: string;
  set: (v: string) => void;
  type?: string;
  required?: boolean;
  name?: string;
  autoComplete?: string;
}) {
  return (
    <Field label={label}>
      <input
        type={type}
        name={name}
        autoComplete={autoComplete}
        value={value}
        onChange={(e) => set(e.target.value)}
        required={required}
      />
    </Field>
  );
}

export function Select({
  label,
  value,
  set,
  options,
  labels,
  describedBy,
}: {
  label: string;
  value: string;
  set: (v: string) => void;
  options: string[];
  labels?: Record<string,string>;
  describedBy?: string;
}) {
  return (
    <Field label={label}>
      <select aria-label={label} aria-describedby={describedBy} value={value} onChange={(e) => set(e.target.value)}>
        {options.map((v) => (
          <option key={v} value={v}>
            {labels?.[v] ?? (v ? optionLabel(v) : "All")}
          </option>
        ))}
      </select>
    </Field>
  );
}

export function Confirm({
  value,
  set,
  children,
}: {
  value: boolean;
  set: (v: boolean) => void;
  children: ReactNode;
}) {
  return (
    <label className="confirm">
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => set(e.target.checked)}
      />
      {children}
    </label>
  );
}

export function Panel({
  title,
  children,
  action,
}: {
  title?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="panel">
      {title && (
        <div className="panel-heading">
          <h2>{title}</h2>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Detail({
  title,
  children,
  open = false,
}: {
  title: string;
  children: ReactNode;
  open?: boolean;
}) {
  return (
    <details open={open || undefined}>
      <summary>
        {title}
        <ChevronRight size={16} />
      </summary>
      <div className="detail-body">{children}</div>
    </details>
  );
}

export function Badge({ value, department }: { value: unknown; department?: string }) {
  let text = statusLabel(value,department),
    tone =
      /mismatch|high|medium|reject|failed|manual|correction|escalat|anomaly|incomplete|unmatched|ambiguous/i.test(
        String(value),
      )
        ? "warning"
        : /passed|approved|matched|completed|low/i.test(String(value))
          ? "good"
          : "";
  return <span className={"badge " + tone}>{text}</span>;
}

export function State({
  error,
  loading,
}: {
  error?: string;
  loading: boolean;
}) {
  return error ? (
    <p className="notice error" role="alert">
      {businessText(error)}
    </p>
  ) : loading ? (
    <p className="loading" role="status">
      Loading workspace…
    </p>
  ) : null;
}

function DisplayValue({value,depth=0}:{value:unknown;depth?:number}): ReactNode {
  if(value == null) return "—";
  if(typeof value === "boolean") return value ? "Yes" : "No";
  if(typeof value !== "object") return businessText(value);
  if(depth >= 8) return "Additional nested details are available in the authorized export.";
  if(Array.isArray(value)) return value.length ? <ul className="structured-list">{value.map((item,index)=><li key={index}><DisplayValue value={item} depth={depth+1} /></li>)}</ul> : "None recorded";
  return <dl className="structured-value">{Object.entries(value).filter(([key])=>!/(?:password|secret|token|api_key|source_path|raw_response|raw_model|stack_trace)/i.test(key)).map(([key,item])=><div key={key}><dt>{words(key)}</dt><dd><DisplayValue value={item} depth={depth+1} /></dd></div>)}</dl>;
}

export function Table({
  rows,
  onOpen,
  keys,
  cells = {},
}: {
  rows: RecordData[];
  onOpen?: (id: number) => void;
  keys?: string[];
  cells?: Record<string, (row: RecordData) => ReactNode>;
}) {
  if (!rows.length)
    return (
      <div className="empty">
        <FileText size={28} />
        <h3>Nothing here yet</h3>
        <p>
          No records match this view. Adjust the filters or choose another view.
        </p>
      </div>
    );
  const cols =
    keys ??
    Object.keys(rows[0]).filter(
      (k) => !["full_result", "source_path", "file_hash"].includes(k),
    );
  return (
    <div className="table-scroll" tabIndex={0} aria-label="Scrollable records">
      <table>
        <thead>
          <tr>
            {cols.map((k) => (
              <th key={k}>{words(k)}</th>
            ))}
            {onOpen && (
              <th>
                <span className="sr-only">Open record</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.id ?? i}>
              {cols.map((k) => (
                <td key={k}>
                  {cells[k] ? (
                    cells[k](row)
                  ) : k === "filename" ? (
                    <div className="record-identity">
                      <span className="record-mark" aria-hidden="true">
                        <FileText size={18} />
                      </span>
                      <div>
                        <strong>{String(row[k] ?? "—")}</strong>
                        {row.document_type && (
                          <small>
                            {words(row.document_type)}
                            {row.id ? ` · #${row.id}` : ""}
                          </small>
                        )}
                      </div>
                    </div>
                  ) : k === "validation_passed" ? (
                    <Badge
                      value={
                        row[k] === 1 || row[k] === true
                          ? "Checks passed"
                          : row[k] === 0 || row[k] === false
                            ? "Failed validation"
                            : "Not recorded"
                      }
                    />
                  ) : k === "outcome" ? (
                    <Badge value={row[k] === "failed" ? "Check failed" : row[k]} />
                  ) : /status|decision|risk/.test(k) || k === "state" ? (
                    <Badge value={row[k]} department={row.assigned_department ?? row.department} />
                  ) : ["safe_error","reason","description","message","notes"].includes(k) ? (
                    businessText(row[k])
                  ) : k === "event_type" ? (
                    words(row[k])
                  ) : k === "actor_kind" ? (
                    optionLabel(row[k] ?? "Not recorded")
                  ) : k === "actor" ? (
                    String(row[k] ?? "").startsWith("user:") ? String(row[k]).split(":").slice(2).join(":") : String(row[k] ?? "").startsWith("system:") ? "Automatic check" : row[k]
                  ) : row[k] == null ? (
                    "—"
                  ) : typeof row[k] === "boolean" ? (
                    row[k] ? "Yes" : "No"
                  ) : typeof row[k] === "object" ? (
                    <DisplayValue value={row[k]} />
                  ) : (
                    String(row[k] ?? "—")
                  )}
                </td>
              ))}
              {onOpen && (
                <td>
                  <Button
                    onClick={() => onOpen(row.id)}
                    aria-label={"Open " + row.filename}
                  >
                    <ArrowUpRight size={16} />
                  </Button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Subtabs({
  value,
  set,
  items,
}: {
  value: string;
  set: (v: string) => void;
  items: string[];
}) {
  return (
    <Tabs.Root value={value} onValueChange={set}>
      <Tabs.List className="subtabs" aria-label="Workspace view">
        {items.map((item) => (
          <Tabs.Trigger key={item} value={item}>
            {item}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
    </Tabs.Root>
  );
}

export function Export({
  kind,
  resource = {},
  label = "Download JSON",
}: {
  kind: string;
  resource?: RecordData;
  label?: string;
}) {
  const { run } = useContext(ActionContext);
  return (
    <Button onClick={() => run(() => download(kind, resource))}>
      <Download size={15} />
      {label}
    </Button>
  );
}

export function Metric({
  label,
  value,
  note,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: unknown;
  note?: string;
  icon?: ReactNode;
  tone?: "neutral" | "good" | "warning" | "blue" | "violet";
}) {
  return (
    <div className={`metric metric-${tone}`}>
      {icon && (
        <div className="metric-icon" aria-hidden="true">
          {icon}
        </div>
      )}
      <span>{label}</span>
      <strong>{String(value ?? "—")}</strong>
      {note && <small>{note}</small>}
    </div>
  );
}

export function PageTitle({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <div className="page-title">
      <span className="eyebrow">{eyebrow}</span>
      <h1>{title}</h1>
      <p>{description}</p>
    </div>
  );
}
