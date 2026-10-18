/** Display only: never change persisted decisions, evidence or routing. */
export const accountTypes = [
  { department: "Finance", label: "Finance employee", description: "Work with invoices, purchase order comparisons and Finance review cases." },
  { department: "Procurement", label: "Procurement employee", description: "Manage purchase orders and investigate purchasing discrepancies." },
  { department: "Expense Processing", label: "Expense processing employee", description: "Review receipts and expense-related documents." },
  { department: "Legal", label: "Legal employee", description: "Review contracts and resolve legal-document exceptions." },
  { department: "Document Review", label: "Document review employee", description: "Verify extracted document information and resolve processing exceptions." },
  { department: "Operations / Other", label: "Operations / General employee", description: "Request access for general operations. Your Administrator will assign appropriate permissions." },
] as const;
export function accountTypeLabel(department: unknown): string {
  return accountTypes.find(type => type.department === department)?.label ?? "Not requested";
}

const checkMessages: Record<string,string> = {
  PO_REFERENCE_MISMATCH: "The invoice does not match its referenced purchase order.",
  PO_NOT_FOUND: "No stored purchase order matches the invoice reference.",
  MULTIPLE_PO_MATCHES: "More than one purchase order matches this reference. A reviewer must identify the correct one.",
  VENDOR_MISMATCH: "The invoice seller differs from the purchase order vendor.",
  CURRENCY_MISMATCH: "The invoice and purchase order use different currencies.",
  TOTAL_MISMATCH: "The invoice total differs from its purchase order total.",
  INCOMPLETE_COMPARISON: "The purchase order comparison is incomplete. Check the recorded information.",
  UNVERIFIED_EVIDENCE: "Some extracted information is not supported by the source and requires review.",
  VALIDATION_FAILURE: "Required document checks failed. Review the missing or incorrect information.",
  NEGATIVE_TOTAL: "The document total is negative and requires review.",
  LARGE_AMOUNT: "The amount exceeds the configured review threshold.",
  SAME_SELLER_CLIENT: "The seller and client appear to be the same party. Verify their roles.",
  SAME_VENDOR_BUYER: "The vendor and buyer appear to be the same party. Verify their roles.",
};
const labels: Record<string, string> = {
  pending_department_review: "Awaiting department review", manual_review: "Needs additional verification",
  pending: "Awaiting review", approved: "Approved", rejected: "Rejected", needs_correction: "Correction required",
  escalated: "Escalated for review", queued: "Waiting to process", processing: "Processing document",
  completed: "Processing complete", duplicate: "Existing result reused", failed: "Processing failed",
  review_required: "Review needed", interrupted: "Processing interrupted", open: "Ready for review",
  in_review: "In review", on_hold: "On hold", awaiting_correction: "Correction required",
  matched: "Purchase order matched", mismatch: "Purchase order discrepancy", unmatched: "Purchase order not found",
  ambiguous: "Multiple possible matches", incomplete: "Comparison incomplete", not_checked: "No purchase order reference",
  not_applicable: "Not required for this document", low: "Low", medium: "Medium", high: "High",
  normal: "Normal", urgent: "Urgent", unknown: "Unsupported document", configuration: "Administrator help needed",
  invoice: "Invoice", purchase_order: "Purchase order", receipt: "Receipt", contract: "Contract",
  True: "Checks passed", False: "Failed validation",
  authenticated_user: "Signed-in employee", prototype_operator: "Historical operator", system: "Automatic check",
};
const fieldLabels: Record<string,string> = {
  po_reference: "Purchase order reference", po_number: "Purchase order number", tax_id: "Seller tax ID",
  workflow_status: "Workflow", cross_document_status: "Purchase order check", validation_passed: "Required checks",
  safe_error: "What needs attention", state: "Status", requested_department: "Requested account type",
  approved_role: "Approved role", approved_departments: "Approved departments",
  actor: "Performed by", actor_kind: "Identity", actor_context: "Recorded employee",
  escalates: "Requires review", outcome: "Check result",
  model: "Processing service", ocr_confidence: "Source recognition confidence", classification_confidence: "Document classification confidence",
  mandatory_fields: "Required information", field_validation: "Information checks", verified_evidence: "Supporting evidence",
  po_reconciliation: "Purchase order verification", supplier_consistency: "Supplier consistency", contract_requirements: "Required contract information",
  contract_expiration: "Contract end date", high_value: "High value review", duplicate_identifier: "Duplicate document number",
  additional_review: "Additional review", risk_guard: "Risk review", department_routing: "Department routing", policy_engine_failure: "Unavailable policy checks",
  party_a: "First party", party_b: "Second party", assignee: "Assigned reviewer", team: "Responsible department",
};
export function words(value: unknown): string {
  const raw=String(value ?? "Not recorded");
  return mappedText(checkMessages,raw) ?? mappedText(fieldLabels,raw) ?? raw.replaceAll("_", " ").replace(/^./, s=>s.toUpperCase());
}
function mappedText(values: Record<string,string>,key: string): string | undefined {
  return Object.hasOwn(values,key) ? values[key] : undefined;
}
export function statusLabel(value: unknown, department?: string): string {
  if(value==="pending_department_review" && department) return `Awaiting ${department} review`;
  const raw=String(value ?? "Not recorded");
  return mappedText(labels,raw) ?? (raw.includes("_") ? "Status unavailable" : words(raw));
}
export function optionLabel(value: string): string {
  return mappedText(labels,value) ?? words(value);
}
export function historyValue(field: string,value: unknown): unknown {
  if(typeof value !== "string") return value;
  if(field === "assignee") return /^user:\d+:(.+)$/.exec(value)?.[1] ?? value;
  if(["case_status","workflow_status","review_decision","cross_document_status","risk_level","priority"].includes(field)) return statusLabel(value);
  return value;
}
export function businessText(value: unknown): string {
  const raw=String(value ?? "");
  if(Object.hasOwn(checkMessages,raw)) return checkMessages[raw];
  // Free-form diagnostic data must never become an employee-facing exception.
  if(/gsk_[\w-]+|sk-proj-[\w-]+|[A-Z]:[\\/]|\/(?:home|Users|tmp|var)\/|Traceback|SELECT\s+.+\s+FROM|INSERT\s+INTO|Bearer\s+\S+/i.test(raw))
    return "Details could not be displayed safely. Contact your administrator.";
  if(/GROQ_API_KEY|API key.*missing|Provider authorization|check local configuration/i.test(raw))
    return "Document processing is not configured. Contact your administrator.";
  if(/Provider quota|Provider or connection|Groq API|LangGraph.*fail|Failed to fetch|NetworkError|Network request failed/i.test(raw))
    return "Document processing is temporarily unavailable. Retry later or contact your administrator.";
  if(/(?:sqlite3?\.)?(?:OperationalError|IntegrityError)|database (?:is )?(?:locked|busy)|SQLITE_BUSY/i.test(raw))
    return "Saved work is temporarily unavailable. Please try again shortly. Contact your administrator if the problem continues.";
  if(/\b(?:TypeError|ReferenceError|RuntimeError|ValueError|KeyError|PermissionError|FileNotFoundError|SyntaxError)\b|\b(?:SELECT|UPDATE|DELETE)\s+.+\s+(?:FROM|SET|WHERE)\b|\bIDP_[A-Z_]+\b|\/(?:api|srv|opt|mnt)\//i.test(raw))
    return "The operation could not be completed. Saved work is retained. Retry or contact your administrator.";
  return raw.replace(/\bGroq\b/g,"external processing service")
    .replace(/\bLLM\b/g,"AI processing")
    .replace(/\bLangGraph\b/g,"document processing")
    .replace(/\bOCR\b/g,"source text")
    .replace(/\b(?:openai|meta-llama|qwen)[/][\w./-]+/gi,"configured processing service")
    .replace(/\b(?:llama|gemma|mixtral|qwen)[-_][\w.-]+/gi,"configured processing service")
    .replace(/\b(?:PO_REFERENCE_MISMATCH|PO_NOT_FOUND|MULTIPLE_PO_MATCHES|VENDOR_MISMATCH|CURRENCY_MISMATCH|TOTAL_MISMATCH|INCOMPLETE_COMPARISON|UNVERIFIED_EVIDENCE|VALIDATION_FAILURE|NEGATIVE_TOTAL|LARGE_AMOUNT|SAME_SELLER_CLIENT|SAME_VENDOR_BUYER)\b/g,code=>checkMessages[code])
    .replace(/\b(?:invoice_number|po_reference|po_number|issue_date|order_date|party_a|party_b|effective_date|contract_title|contract_value|tax_id|mandatory_fields|field_validation|verified_evidence|po_reconciliation|supplier_consistency|contract_requirements|contract_expiration|high_value|duplicate_identifier|additional_review|risk_guard|department_routing|policy_engine_failure)\b/g,word=>words(word).toLowerCase());
}
export function failureGuidance(category: unknown, recorded: unknown): string {
  const known: Record<string,string> = {
    configuration:"Processing is not configured. Contact your administrator before retrying.",
    credentials:"Processing cannot start. Contact your administrator before retrying.",
    rate_limit:"Processing is temporarily unavailable. Retry later.",
    transient:"Processing is temporarily unavailable. Retry later.",
    request:"This document could not be processed. Check its format or contact your administrator.",
  };
  return mappedText(known,String(category)) ?? businessText(recorded || "Processing failed. Check the source and retry; contact your administrator if it continues.");
}
export function documentOutcome(state: Record<string, any>, decision: unknown, canReview: boolean) {
  const human=String(decision ?? "pending"), workflow=state.workflow_status;
  const title=["approved","rejected","needs_correction","escalated"].includes(human)
    ? statusLabel(human) : statusLabel(workflow,state.assigned_department);
  let next="Inspect the recorded checks and supporting source before taking action.";
  if(human==="approved" || human==="rejected") next="See the recorded decision and review history.";
  else if(human==="needs_correction") next="Resolve the recorded issue using the source, then request another review.";
  else if(workflow==="pending_department_review") next=canReview ? "Review the supporting evidence and record your decision." : "The responsible department will review this document. You have read-only access.";
  else if(["mismatch","unmatched","ambiguous","incomplete"].includes(state.cross_document_status)) next="Check the purchase order reference and discrepancy. Ask the responsible department to investigate before approval.";
  else if(state.validation_passed===false) next="Check the missing or unsupported information against the source. Only supported corrections can be accepted.";
  return {title,reason:businessText(state.routing_reason || "No processing explanation was recorded."),next};
}
export const destinations = [
  {name:"Overview",permission:"analytics"},{name:"Documents",permission:"documents"},
  {name:"My Work",permission:"review"},{name:"Insights",permission:"analytics"},
  {name:"Administration",permission:"security_audit"},
];
export function roleHome(role: string) {
  const homes: Record<string,{title:string; description:string; action:string; destination:string}> = {
    Administrator:{title:"Organization overview",description:"Monitor document intake, account requests and work awaiting a department decision.",action:"Manage employee requests",destination:"Administration"},
    "Finance Reviewer":{title:"Finance workspace",description:"Review assigned invoices, investigate purchase order discrepancies and follow related Procurement work.",action:"Open Finance work",destination:"My Work"},
    "Procurement Reviewer":{title:"Procurement workspace",description:"Review purchase orders and investigate purchase-related issues referred by Finance.",action:"Open Procurement work",destination:"My Work"},
    "Expense Reviewer":{title:"Expense workspace",description:"Review receipts, expense discrepancies and cases assigned to you.",action:"Open expense work",destination:"My Work"},
    "Legal Reviewer":{title:"Legal workspace",description:"Review contracts and their required information before recording a decision.",action:"Open Legal work",destination:"My Work"},
    "Document Reviewer":{title:"Document review workspace",description:"Resolve missing information, evidence conflicts and verification exceptions using supported source details.",action:"Open correction work",destination:"My Work"},
    Auditor:{title:"Read-only oversight",description:"Inspect authorized document history and trace decisions. Your account cannot change records.",action:"Inspect document history",destination:"Documents"},
    "Operations Manager":{title:"Operations overview",description:"Monitor workload and operational summaries within your approved scope.",action:"Open operational insights",destination:"Insights"},
  };
  return Object.hasOwn(homes,role) ? homes[role] : {title:"Workspace overview",description:"See the work available within your approved responsibilities.",action:"Open insights",destination:"Insights"};
}
