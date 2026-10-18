import { test } from 'node:test';
import assert from 'node:assert/strict';
import { accountTypes, accountTypeLabel, historyValue, optionLabel, words, businessText, statusLabel, documentOutcome, failureGuidance, roleHome, destinations } from '../src/presentation.ts';

test('six employee account labels map to existing unprivileged department preferences',()=>{
  assert.deepEqual(accountTypes.map(type=>[type.department,type.label]),[
    ['Finance','Finance employee'],['Procurement','Procurement employee'],
    ['Expense Processing','Expense processing employee'],['Legal','Legal employee'],
    ['Document Review','Document review employee'],['Operations / Other','Operations / General employee'],
  ]);
  for(const type of accountTypes) {
    assert.equal(accountTypeLabel(type.department),type.label);
    assert.ok(type.description.length>30);
    assert.doesNotMatch(type.label,/Administrator|Auditor|Reviewer/);
  }
  assert.equal(accountTypeLabel(null),'Not requested');
  assert.equal(accountTypeLabel('Administrator'),'Not requested');
});

test('remaining technical errors are safe while business checks retain specific meanings',()=>{
  for(const original of ['sqlite3.OperationalError: database is locked','SQLITE_BUSY','RuntimeError: private diagnostic','IDP_DATABASE_PATH is invalid','Request failed at /api/internal','TypeError: Failed to fetch']) {
    const cleaned=businessText(original);
    assert.doesNotMatch(cleaned,/sqlite|SQLITE|RuntimeError|IDP_|\/api\/|TypeError|fetch/);
    assert.match(cleaned,/temporarily unavailable|Retry|try again/i);
  }
  assert.match(businessText('Missing GROQ_API_KEY'),/not configured/);
  assert.doesNotMatch(businessText('Missing GROQ_API_KEY'),/source|damaged|format/);
  assert.equal(businessText('PO_REFERENCE_MISMATCH'),'The invoice does not match its referenced purchase order.');
  assert.match(words('UNVERIFIED_EVIDENCE'),/not supported by the source/);
  assert.equal(businessText('constructor'),'constructor');
  assert.equal(words('constructor'),'Constructor');
  assert.equal(optionLabel('authenticated_user'),'Signed-in employee');
  assert.equal(historyValue('case_status','in_review'),'In review');
  assert.equal(historyValue('assignee','user:2:fictional-finance'),'fictional-finance');
  assert.equal(historyValue('total','INR 100.00'),'INR 100.00');
  const original={username:'fictional-finance',role:'Finance Reviewer'};
  assert.equal(historyValue('actor_context',original),original);
  assert.match(businessText('Approval blocked: resolve mandatory fields, evidence, PO and risk issues or escalate the case.'),/Approval blocked.*mandatory fields.*risk/);
  assert.equal(businessText('Invoice INV-22 total INR 200 differs from PO PO-22 total INR 100.'),'Invoice INV-22 total INR 200 differs from PO PO-22 total INR 100.');
});

test('recorded failures and PO discrepancy remain distinct, never labeled successful',()=>{
  const values=['failed','incomplete','mismatch','unmatched','ambiguous','manual_review','needs_correction','rejected','escalated'];
  const labels=values.map(v=>statusLabel(v));
  assert.equal(new Set(labels).size,values.length);
  assert.equal(statusLabel('pending_department_review','Finance'),'Awaiting Finance review');
  assert.equal(statusLabel('not_checked'),'No purchase order reference');
  assert.equal(statusLabel('not_applicable'),'Not required for this document');
});
test('business reason and next action preserve immutable state and approval distinction',()=>{
  const state={workflow_status:'manual_review',validation_passed:false,cross_document_status:'mismatch',routing_reason:'Invoice total INR 200 differs from Purchase Order INR 100.'};
  const before=JSON.stringify(state), outcome=documentOutcome(state,'pending',true);
  assert.match(outcome.reason,/INR 200.*INR 100/);
  assert.match(outcome.next,/before approval/);
  assert.equal(outcome.title,'Needs additional verification');
  assert.equal(JSON.stringify(state),before);
  assert.equal(documentOutcome(state,'approved',false).title,'Approved');
  assert.match(documentOutcome({...state,workflow_status:'pending_department_review'},'pending',false).next,/read-only/);
});
test('provider failures and sensitive diagnostics use safe retry/admin guidance',()=>{
  for(const text of ['gsk_disposable-example','C:\\private\\file.pdf','Traceback: secret','SELECT password FROM users','Bearer private-token']) {
    const result=businessText(text);assert.doesNotMatch(result,/gsk_|Traceback|SELECT|Bearer|private/);
    assert.match(result,/administrator/);
  }
  assert.match(businessText('GROQ_API_KEY is missing.'),/not configured/);
  assert.match(failureGuidance('rate_limit','private provider response'),/Retry later/);
  assert.match(failureGuidance('credentials','private provider response'),/administrator before retrying/);
  assert.equal(businessText('Mandatory invoice_number is missing.'),'Mandatory invoice number is missing.');
  assert.equal(businessText('Policy rules requiring review: po_reconciliation, risk_guard.'),'Policy rules requiring review: purchase order verification, risk review.');
  assert.doesNotMatch(businessText('Failed using llama-3.3-70b-versatile'),/llama/);
});
test('all eight role home actions lead to permitted destinations only',()=>{
  const roles={Administrator:['analytics','documents','review','security_audit'],Auditor:['analytics','documents'],'Operations Manager':['analytics']};
  for(const role of ['Finance Reviewer','Procurement Reviewer','Expense Reviewer','Legal Reviewer','Document Reviewer']) roles[role]=['analytics','documents','review'];
  for(const [role,permissions] of Object.entries(roles)) {
    const visible=destinations.filter(d=>permissions.includes(d.permission)).map(d=>d.name);
    assert.ok(visible.includes(roleHome(role).destination),role);
    assert.equal(visible.includes('Administration'),role==='Administrator');
    assert.equal(visible.includes('My Work'),role==='Administrator'||role.endsWith('Reviewer'));
  }
  assert.match(roleHome('Auditor').description,/cannot change/);
  assert.equal(roleHome('Operations Manager').destination,'Insights');
});
