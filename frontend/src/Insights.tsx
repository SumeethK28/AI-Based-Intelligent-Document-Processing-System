import { useState, useContext } from "react";
import { Files, ShieldCheck, CircleAlert } from "lucide-react";

import { RecordData } from "./api";

import {
  words,
  ActionContext,
  allowed,
  useLoad,
  Select,
  Panel,
  Detail,
  State,
  Table,
  Subtabs,
  Export,
  Metric,
  PageTitle,
} from "./components";
import { Filters } from "./Documents";

export function Insights() {
  const [filters, setFilters] = useState<RecordData>({}),
    [area, setArea] = useState("Financial"),
    [dimension, setDimension] = useState("currency"),
    [currency, setCurrency] = useState("");
  const { data, error, loading } = useLoad(
      "/analytics?" + new URLSearchParams(filters),
      true,
    ),
    { permissions } = useContext(ActionContext);
  if (!data || error)
    return (
      <>
        <PageTitle
          eyebrow="BUSINESS INTELLIGENCE"
          title="Insights"
          description="Understand your workload, exceptions and extracted invoice values."
        />
        <Filters filters={filters} set={setFilters} />
        <State error={error} loading={!error} />
      </>
    );
  const currencies = [
    ...new Set<string>(
      Object.values(data.financial as RecordData)
        .flat()
        .map((row: any) => row.currency),
    ),
  ].sort();
  const selectedCurrency = currencies.includes(currency)
    ? currency
    : currencies[0] || "";
  const rows =
    area === "Financial"
      ? (data.financial[dimension] ?? []).filter(
          (r: any) => r.currency === selectedCurrency,
        )
      : Object.entries(data[dimension] ?? {}).map(([category, count]) => ({
          category,
          count,
        }));
  const max = Math.max(
    1,
    ...rows.map((row: any) => Number(row.extracted_value ?? row.count)),
  );
  return (
    <>
      <PageTitle
        eyebrow="BUSINESS INTELLIGENCE"
        title="Insights"
        description="Understand your workload, exceptions and extracted invoice values."
      />
      <Filters filters={filters} set={setFilters} />
      {loading && (
        <p className="loading" role="status">
          Updating filtered insights…
        </p>
      )}
      <div className="metrics">
        <Metric
          label="Unique documents"
          value={data.unique_documents}
          tone="blue"
          icon={<Files size={21} />}
          note="Within the current filters"
        />
        <Metric
          label="Department eligible"
          value={data.eligible_documents}
          tone="good"
          icon={<ShieldCheck size={21} />}
          note="Eligible for departmental review"
        />
        <Metric
          label="Manual review"
          value={data.manual_review_documents}
          tone={data.manual_review_documents > 0 ? "warning" : "violet"}
          icon={<CircleAlert size={21} />}
          note="Exceptions requiring attention"
        />
      </div>
      <Subtabs
        value={area}
        set={(v) => {
          setArea(v);
          setDimension(v === "Financial" ? "currency" : "types");
        }}
        items={["Financial", "Operations"]}
      />
      <Panel
        title={
          area === "Financial"
            ? "Extracted invoice values"
            : "Operational workload"
        }
        action={
          allowed(permissions, "analytics_export") && (
            <Export
              kind="analytics_json"
              resource={{ filters }}
              label="Export insights"
            />
          )
        }
      >
        <div className="form-grid">
          {area === "Financial" && (
            <Select
              label="Currency"
              value={selectedCurrency}
              set={setCurrency}
              options={currencies}
            />
          )}
          <Select
            label="Breakdown"
            value={dimension}
            set={setDimension}
            options={
              area === "Financial"
                ? ["currency", "supplier", "day", "po", "high_value"]
                : [
                    "types",
                    "department_backlog",
                    "backlog_age",
                    "validation_patterns",
                    "anomaly_patterns",
                    "policy_patterns",
                  ]
            }
          />
        </div>
        <div
          className={`bars insight-bars ${area === "Financial" ? "financial" : "operational"}`}
        >
          {!rows.length && (
            <p className="empty">
              No recorded values match this breakdown and the current filters.
            </p>
          )}
          <div className="chart-key">
            <i className={area === "Financial" ? "" : "duplicate-key"} />
            {area === "Financial"
              ? "Extracted value in the selected currency"
              : "Document / occurrence count"}
          </div>
          {rows.map((r: any, i: number) => (
            <div className="bar-row" key={i}>
              <span>{words(r.category)}</span>
              <div>
                <i
                  style={{
                    width: `${(Math.max(0, Number(r.extracted_value ?? r.count)) / max) * 100}%`,
                  }}
                />
              </div>
              <strong>
                {area === "Financial"
                  ? `${r.currency} ${r.extracted_value}`
                  : r.count}
              </strong>
            </div>
          ))}
        </div>
        <Detail title="Exact values">
          <Table rows={rows} />
        </Detail>
        <p className="footnote">
          Values remain separated by currency. Extracted invoice values are not
          paid balances, revenue or measured human savings.
        </p>
      </Panel>
      {area === "Operations" && (
        <Panel title="Performance & interventions">
          <Table
            rows={[
              {
                corrected_documents: data.corrected_documents,
                intervened_documents: data.intervened_documents,
                duplicate_submission_rate: data.duplicate_submission_rate,
              },
            ]}
          />
          <Detail title="Measured processing time">
            <Table rows={[data.processing_time, data.batch_attempt_time]} />
          </Detail>
          <Detail title="Batch outcomes">
            <pre>{JSON.stringify(data.batches, null, 2)}</pre>
          </Detail>
        </Panel>
      )}
      <Detail title="Definitions and limitations">
        {Object.entries(data.definitions ?? {}).map(([k, v]) => (
          <p key={k}>{String(v)}</p>
        ))}
      </Detail>
    </>
  );
}
