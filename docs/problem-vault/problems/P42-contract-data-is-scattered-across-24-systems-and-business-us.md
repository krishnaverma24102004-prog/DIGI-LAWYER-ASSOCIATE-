# P42. Contract data is scattered across ~24 systems and business users can't read their own contracts, so every simple question becomes a ticket to legal

**Severity:** high · **Size:** big · **Region:** Global

**Who has it:** In-house legal, finance and procurement; law firms running diligence; sales teams

## What goes wrong

'Can we terminate this vendor?', 'What's our liability cap with X?', 'Which contracts have change-of-control before this fundraise?' each mean a lawyer opening PDFs one by one across email, Drive, ERP, CRM and e-sign tools. M&A diligence and audits become weeks of manual extraction.

## Evidence of scale

- WorldCC (Aug 2025): contract data spread across 24 systems on average; almost 90% of business users find contracts difficult or impossible to understand; 83% of executives say contracts are too rigid. ([source](https://info.worldcc.com/contract-management-aug-2025))
- Deloitte: in large organisations contract data sits in 24 systems on average. ([source](https://www.deloitte.com/us/en/services/tax/articles/contract-management-lifecycle-insights.html))

## Why current tools don't solve it

Harvey and CoCounsel beat the lawyer baseline on extraction in VLAIR but only on documents a lawyer uploads, not a company's whole messy corpus of scanned Indian stamp papers, vernacular annexures and amendments. They don't give non-lawyers answers with verified source quotes and an 'ask legal' escalation. CLM repositories only hold what was migrated.

## Panel verdict

**Status:** open (round -)

**Effort:** L

### What software can fix

One searchable contract repository built from the places contracts already live:
- forwarded email (SES receiving, verified only through P37's signed-SNS inbound_auth);
- PDFs staff send on WhatsApp (Meta-signed webhook);
- Google Drive files and folders the admin explicitly picks or shares;
- SharePoint libraries an admin grants;
- direct and bulk ZIP uploads;
- scans.

PDF, DOCX, images, .eml and ZIP are extracted. Every document, from any source, enters as 'pending'. Only the background classifier or the database's confirm_execution function can move it on from there.

Code gives each document an execution status from evidence: executed, partially_executed, stamped_unconfirmed, unsigned_draft or unknown. Code sets 'executed' only when every party in the execution block is matched to a distinct signer whose identity comes from a recognised source:
- a certificate that chains to the CCA India root (DSC or Aadhaar eSign); or
- a completed signer in the sealed audit trail of an allowlisted e-sign platform (DocuSign, Adobe Acrobat Sign, Zoho Sign, Leegality, Digio).

Otherwise a paralegal confirms each party's signature page and records corroborating evidence. That happens through a SECURITY DEFINER Postgres function called with the paralegal's own JWT.

Duplicates are merged only within the same status, amendments are linked to their parent, and standard fields are extracted with verified quotes. Business users get answers only from lawyer-confirmed fields of executed contracts that have no pending amendment links and no IT Act First Schedule flag. Everything else shows the quote marked 'not yet confirmed by legal', with an 'Ask legal' button.

### What it can't fix

Not connected yet:
- ERP and CRM APIs come later.
- Paper contracts nobody scans aren't covered.
- Legacy .doc and .pages files are rejected with 'save as DOCX or PDF' and counted in the coverage report.

Limits of what code can detect:
- Code can't reliably detect wet-ink signatures on scans. A scanned contract reaches 'executed' only when a paralegal confirms each party.
- A platform audit trail proves what the vendor recorded (for example, email-only authentication). It doesn't prove who was at the keyboard.
- Vendor layouts without golden samples aren't parsed. They go to the paralegal.
- Revocation can't always be checked offline.
- A paralegal's confirmation is only as good as their review. The system enforces that every party is ticked and corroboration is recorded, not that the paralegal looked carefully.
- We don't claim to have found 'all' contracts. Coverage is reported as what was ingested and what was rejected.

Decisions that stay with legal, because software can't make them:
- whether a signatory had authority to bind (board resolution, POA);
- whether a partially executed contract binds by conduct;
- whether a platform click-signature is enforceable for this contract. It is an electronic record under IT Act s.10A, not a s.3A electronic signature, and we label it that way;
- whether a First Schedule document signed electronically is valid.

Operational limits:
- Without background jobs (no REDIS_URL), contract upload and ingestion return 503. Nothing is stored or classified inline.
- A file uploaded while the queue is briefly down stays 'pending' until the sweep picks it up (at most about 5 minutes after Redis returns). The user sees 'Processing' meanwhile.
- A document restored from the trash goes back to 'pending' and is re-classified. A prior paralegal confirmation is re-applied only if the bytes are identical.

Owned by other problems: translation of vernacular annexures (P23/P24) and stamp-duty adequacy (P45).

### What the user sees

/contracts lists each contract with:
- counterparty and type;
- status (active, expired, superseded);
- execution status and its evidence;
- value, term end and next confirmed obligation;
- stamp status and source.

Newly uploaded files show 'Processing: checking signatures and extracting terms' until the classifier finishes. A pending file never appears in answers, portfolio totals or the Execution tray.

The Upload button (owners, partners, associates and paralegals) accepts PDF, DOCX, images, .eml or a ZIP. It returns at once with one 'Processing' row per file, or per ZIP that the worker expands. If background jobs are off, the page says 'Contract upload is unavailable: background jobs are not configured' and stores nothing.

Execution evidence is shown by signature type. Examples:
- 'Executed: 2 of 2 parties signed. DSC (CCA-chained, e-Mudhra): R. Mehta for Acme Logistics Pvt Ltd. Aadhaar eSign (ESP NSDL): A. Rao for Client Co. Signatures intact.'
- 'Executed via DocuSign envelope 3F2A…: 2 of 2 signers completed per the sealed Certificate of Completion. Authentication: email only. Platform e-signature: electronic record (s.10A), not a s.3A electronic signature.'
- 'Signature present, identity unverified: certificate is self-issued.'
- 'Partially executed: 1 of 2 parties signed (Acme only).'
- 'Stamped, signatures not confirmed: e-stamp IN-KA… dated 28 Mar 2024. Stamp paper is bought before signing, so this alone doesn't show execution.'
- 'Executed (paralegal-confirmed): signatures of both parties seen on p. 14, corroborated by the original held in the Mumbai office, confirmed by S. Iyer (paralegal), 4 Oct.'
- 'Electronic execution of a First Schedule document (Power of Attorney): legal review needed.'
- 'Uploaded file differs from what the browser reported (hash mismatch). Classified on the stored bytes.'

When everything is confirmed on an executed copy, a business user who asks 'Can we terminate the Acme logistics contract?' sees: 'cl. 18.1 of the executed Services Agreement dated 1 Apr 2024 provides: "Either party may terminate this Agreement for convenience by giving sixty (60) days' written notice" (confirmed by legal, A. Rao, 3 Oct). Earliest end if notice is served today: <computed date> (computed, confirmed rule). This is information from your contract, not legal advice.'

In every other case the card shows the quote under a banner that names the reason, with no computed date and no conclusion. 'Ask legal' creates a P15 request. If nothing supports an answer, the card says 'The executed contracts we hold don't answer this'. Portfolio questions return a grid with execution-status, signature-type and confirmed columns, exportable as CSV. Only executed rows count toward an answer, and pending rows are listed separately as 'Processing'.

The Execution tray at /contracts/execution:
- Who can act: owners, partners, paralegals, and associates that an owner or partner has granted 'execution confirmer'. Others see it read-only, with 'You can't confirm execution. Ask a partner to grant you execution confirmer.'
- What it lists: stamped_unconfirmed, unknown and partially_executed copies, unparsed platform envelopes, and signatures whose identity is unverified.
- Per party: a checkbox, the page thumbnail and a signature-page field. Audit-trail pages appear as counterpart evidence.
- Corroboration selector: counterpart linked; platform audit trail; executed copy received from the counterparty's verified domain; original held (location); other with a note.
- 'Confirm executed' is enabled only when every party is ticked and a corroboration is recorded. If the database refuses, the tray shows the database's reason verbatim. Self-issued certificates show a red warning.

Admins see the Ingest page, with per-source coverage, rejections and a 'pending for more than 10 minutes' counter, and the 'Execution confirmers' list.

### What the system does

1. Extraction (unchanged).
- document_service.extract_text handles DOCX: body, tables, headers, footers and footnotes. Comments, tracked changes and hidden runs are flagged.
- It also handles .eml and ZIP, applying the ZIP guards.
- Unsupported types go to ingest_rejections.

2. Intake. Every row is born 'pending', whatever its source.

(a) User uploads: POST /contracts/upload.
- The router first checks queue_service.available(). If REDIS_URL is unset it returns 503 before writing anything.
- file_inspector (P15) validates the type and size: 10 MB per file, 200 MB per ZIP. The router computes the sha256.
- It stores the bytes with the caller's own client, ctx.db().storage (get_supabase_for_user), at contracts/<org_id>/<auth.uid()>/<uuid>/<filename>.
- Migration 018 creates a private bucket 'contracts'. Its storage.objects INSERT policy for authenticated requires all of:
  - bucket_id = 'contracts';
  - foldername[1] = public.active_org_id()::text;
  - foldername[2] = auth.uid()::text;
  - has_org_role(active_org_id(), array['owner','partner','associate','paralegal']).
- There is no UPDATE or DELETE policy for authenticated on that bucket, so stored bytes can't be swapped after registration.
- The SELECT policy allows an object only when its contract_documents row passes can_read_contract.

(b) The router then calls ctx.db().rpc('register_contract_upload', {p_storage_path, p_sha256, p_filename, p_tags, p_contract_id}). This is a new SECURITY DEFINER plpgsql function in migration 018 (set search_path = '', errcode 42501 for authorization failures, the pattern of request_approval in 013). Inside it:
- v_org := public.active_org_id(). auth.uid() and v_org must both be non-null, and the caller must pass has_org_role(v_org, array['owner','partner','associate','paralegal']). Otherwise 42501.
- It selects from storage.objects where bucket_id = 'contracts' and name = p_storage_path. The object must exist (else 22023 'Upload not found'). (storage.foldername(name))[1] must equal v_org::text and [2] must equal auth.uid()::text, and owner_id must equal auth.uid()::text. Otherwise 42501 'Upload not found', worded the same so nothing leaks.
- metadata->>'size' must be within the limits.
- p_storage_path must not already be registered (22023).
- p_sha256 must match ^[0-9a-f]{64}$. It is stored only as claimed_sha256, an untrusted hint.
- p_filename must be 1–255 characters, with no path separators.
- p_tags must be a subset of the department tags the caller can see (can_use_tag). p_contract_id, if given, must be a contract in v_org that the caller can read.
- It inserts with fixed values, and the function has no parameters for any of them:
  - org_id = v_org;
  - uploaded_by = auth.uid();
  - execution_status = 'pending';
  - execution_evidence = null;
  - signature_types = '{}';
  - required_parties = null;
  - first_schedule_flag = false;
  - sha256 = null;
  - provenance = {source:'upload', by, at};
  - kind = 'zip' or 'file'.
- It inserts a contract_ingest_queue outbox row and returns the document id.

(c) After the RPC succeeds, the router enqueues task_ingest_contract(document_id). If that enqueue fails, the router still returns 202 'Processing'. The worker's cron task_sweep_pending_contracts runs every 5 minutes and picks up outbox rows older than 2 minutes that have no job. The worker re-checks that the uploader is still a member with an upload role before processing, as invariant 2 requires of ARQ jobs.

(d) Connector deliveries:
- Email is accepted only through P37's inbound_auth (verify_sns plus email_verdict). It must come from a DNS-verified From domain and be addressed to the org's contract-intake address. No headers are trusted.
- Drive (drive.file / Picker or a shared service account), Graph Sites.Selected and the Meta-signed WhatsApp webhook are the other connectors.
- The ingest worker inserts these rows as service_role, scoped to the org of the intake address or connection. They are also 'pending', with sha256 null.
- ZIP entries are expanded by the worker into child rows (parent_upload_id) in the ZIP row's org, again as pending.

3. Insert and update guard: trigger contract_documents_guard, BEFORE INSERT OR UPDATE.
- On INSERT, for every role including service_role and the definer: execution_status must be 'pending', execution_evidence null, signature_types empty, required_parties null, first_schedule_flag false and sha256 null. Anything else raises 42501 'Contract documents are created pending'. No path, the worker's included, can create a row already classified, so a forged 'executed' insert is impossible even if a grant is later misconfigured.
- On UPDATE, the columns execution_status, execution_evidence, signature_types, required_parties, parties_entered_by, first_schedule_flag and sha256 may change only when current_setting('app.contract_write', true) is 'classify' or 'confirm'. That setting is applied with set_config(..., true) inside record_classification and confirm_execution only, the app.legal_hold_change pattern from 013. authenticated has no UPDATE grant at all.
- The round-4 check stays: 'executed' requires execution_evidence.method in ('signatures', 'platform_envelope', 'paralegal') with the required keys, and evidence.sha256 equal to the row's sha256. That sha256 can now only have been written by the classifier from the stored bytes.
- The trash restore (restore_trash_item, 013) re-inserts contract documents through this same guard, so they come back pending with sha256 null and are re-queued.

4. Execution status, in app/services/execution_status.py (unchanged in substance). classify(evidence) -> (status, reasons, signers) is a pure function over:
- the parties;
- pyHanko-validated certificate signatures against the pinned app/trust/ stores (cca_india, vendor_seals, and opt-in aatl and eutl), typed DSC, AADHAAR_ESIGN, PLATFORM_SEAL, FOREIGN_TRUSTED or UNTRUSTED;
- golden-tested vendor envelope parsers;
- P45 stamp evidence;
- draft signals.
The nine ordered rules, the First Schedule flag and stamp_after_execution are as in round 4.

The worker downloads the stored bytes, computes sha256 itself and writes only through public.record_classification(p_document_id, p_sha256, p_status, p_reasons, p_evidence, p_signature_types, p_required_parties, p_first_schedule_flag). EXECUTE on it is granted to service_role only.
- On a pending row it sets sha256 := p_sha256, the worker-computed value. If claimed_sha256 differs, it adds the reason 'upload hash mismatch'. If an unsuperseded execution_confirmations row exists for this document and the same sha256 (a trash restore), it re-applies that paralegal confirmation. Otherwise it writes the classifier's result.
- On a non-pending row it refuses a p_sha256 that differs from the stored one.
- It never overwrites a paralegal confirmation of the same bytes, except to downgrade to 'unknown' on an integrity failure. In that case it supersedes the confirmation and records why.
- p_status = 'pending' is refused.

5. Human promotion: public.confirm_execution(p_document_id, p_per_party, p_corroboration, p_parties default null). This is unchanged from round 5, a SECURITY DEFINER function called with the user's JWT:
(a) It checks identity and org.
(b) It checks can_confirm_execution: owner, partner or paralegal, or an associate with a contract_execution_confirmers grant.
(c) It takes a row lock, scoped by org_id = v_org and can_read_contract(id). A miss raises 'Document not found'.
(d) State: 'pending' is refused with 22023 'Document is still being processed', and 'unsigned_draft' and 'executed' are refused. Only partially_executed, stamped_unconfirmed and unknown qualify.
(e) Every required party must be ticked exactly once, with a valid page.
(f) The corroboration type and its reference are validated in SQL.
(g) It sets app.contract_write = 'confirm', writes execution_evidence {method:'paralegal', by, at, sha256, pages, corroboration}, and inserts an append-only execution_confirmations row.

The router POST /contracts/documents/{id}/confirm-execution calls ctx.db().rpc and maps 42501 to 403 and 22023 to 422, passing through the database's message. It then writes the audit log.

6. Privileges in migration 018:
- revoke insert, update and delete on contract_documents, contract_fields, execution_confirmations, contract_execution_confirmers and contract_ingest_queue from anon and authenticated;
- grant execute to authenticated on register_contract_upload, confirm_execution, grant_execution_confirmer, revoke_execution_confirmer, confirm_contract_field, unconfirm_contract_field, resolve_amendment_link, add_counterparty_domain and set_contract_tags;
- revoke execute on record_classification from public, anon and authenticated, and grant it to service_role;
- the select policy is can_read_contract(id), or uploaded_by = auth.uid() while the row is pending, so uploaders see their own 'Processing' rows;
- execution_confirmations is append-only, apart from the 013 retention purge.

7. Dedup (unchanged). Files are matched by SHA-256, then by shingle similarity of 0.95 or more, and merged only within the same status. Pending rows never take part.

8. Grouping and field extraction (unchanged).
- Amendments are linked by code, or through the linking tray.
- The 'contract record' preset runs on PII-masked text, and every quote is verified by quote_found.
- Confirmation lapses on a quote change, an amendment, or a change of execution_status or first_schedule_flag.

9. Q&A gate (unchanged, with pending made explicit). can_show_confirmed_card() is pure and requires all of:
- status executed (pending and every other status fail);
- first_schedule_flag false;
- every field confirmed;
- every date from a confirmed P16 rule;
- no pending amendment links.
Portfolio queries filter execution_status = 'executed' for answers and list pending rows as 'Processing'.

10. Rows are visible by department tags through can_read_contract, and exportable via P43.

### Where it is built

Existing code to extend:
- app/services/document_service.py;
- P15 app/services/file_inspector.py (type and size checks for contract upload);
- the app/routers/documents.py upload pipeline (bytes handling);
- app/services/ocr_service.py;
- app/services/review_service.py;
- app/services/evidence_service.quote_found;
- app/services/whatsapp_service.py;
- app/services/rag_service.py;
- app/services/audit_service.py;
- app/worker.py: task_ingest_contract, task_classify_execution, and the cron task_sweep_pending_contracts every 5 minutes;
- app/services/queue_service.py: an available() check, giving 503 without REDIS_URL as app/routers/jobs.py does;
- app/core/rbac.py: Permission.CONTRACT_UPLOAD = owner, partner, associate, paralegal; Permission.CONTRACT_CONFIRM_EXECUTION = owner, partner, paralegal;
- P16 obligation_dates;
- the P45 stamp detector;
- P37 app/services/inbound_auth.py;
- migration 004 helpers has_org_role and active_org_id;
- migration 013's SECURITY DEFINER RPC pattern, its app.* set_config guard pattern (guard_legal_hold), and trash_item / restore_trash_item (contract documents added as a trashable kind);
- migration 007's storage-bucket policy pattern;
- tests/db/conftest.py fixtures firm, as_user and denied.

New dependency: pyHanko (with pyhanko-certvalidator).

New migration, supabase/migrations/018_contracts_repository.sql:
- the enum execution_status: pending, executed, partially_executed, stamped_unconfirmed, unsigned_draft, unknown;
- tables: contracts; contract_documents (adds claimed_sha256, uploaded_by, storage_path unique, kind, parent_upload_id); contract_fields; contract_ingest_queue (outbox); ingest_sources; ingest_rejections; org_mail_domains; counterparty_domains; execution_confirmations (append-only); contract_execution_confirmers;
- the private storage bucket 'contracts' with INSERT and SELECT policies only;
- functions: register_contract_upload, can_read_contract, can_use_tag, can_confirm_execution, confirm_execution, grant_execution_confirmer, revoke_execution_confirmer, record_classification (service_role only), confirm_contract_field, unconfirm_contract_field, resolve_amendment_link, add_counterparty_domain, set_contract_tags;
- the triggers contract_documents_guard (insert-pending plus the guarded update) and field-lapse;
- the revoke and grant statements.

Other new code:
- app/trust/;
- app/services/signature_validator.py;
- app/services/esign_vendors/;
- app/services/execution_status.py;
- app/services/ingest_connectors/;
- app/services/contract_repository.py, with register_upload() calling the RPC on the user client;
- app/services/contract_qa.py;
- app/routers/contracts.py: POST /contracts/upload, POST /contracts/documents/{id}/confirm-execution, GET routes;
- frontend/src/app/contracts/page.tsx (Upload button, Processing rows), frontend/src/app/contracts/ingest/page.tsx, frontend/src/app/contracts/execution/page.tsx.

Tests:
- tests/test_signature_trust.py, tests/test_esign_vendors.py, tests/test_execution_status.py;
- tests/test_email_in.py, tests/test_extract_formats.py, tests/test_zip_guards.py;
- tests/test_contract_repository.py, tests/test_contract_qa.py, tests/test_connector_scopes.py;
- tests/test_contracts_no_service_role.py, tests/test_contract_upload_router.py;
- database: tests/db/test_contract_execution_rls.py and tests/db/test_contract_upload_rls.py;
- fixtures: tests/fixtures/execution/ and tests/fixtures/esign_golden/.

### Why current tools fail and this won't

Harvey and CoCounsel extract well, but only from documents a lawyer uploads, and they answer in prose a business user can't check. Neither knows whether the file is the signed version.

CLM repositories treat whatever file is attached as 'the contract'. Their e-sign integrations know only envelopes sent through their own module. They miss the DocuSign PDF a counterparty emailed, the Aadhaar-eSigned NDA on WhatsApp and the stamped scan. Indian tools (Leegality, SignDesk, Zoho) know only their own envelopes.

Indian practice adds traps that generic tools ignore. Stamp paper is bought before signing, so 'it's on e-stamp' gets mistaken for 'it's signed'. The IT Act treats DSC, Aadhaar eSign and platform click-signing differently, and excludes First Schedule documents.

In ours, status is decided by tested code from checkable evidence: identities that are CCA-chained or sealed by an allowlisted vendor, matched party by party. Self-issued IDs never count, and everything else goes to a paralegal. Postgres enforces the lifecycle itself:
- every row, from any source, is created 'pending', with its hash computed by our worker, not by the uploader;
- only the service-role classifier or the paralegal's checked confirm_execution can move it to 'executed';
- users hold no INSERT or UPDATE rights on the table at all.
Most CLMs let their app tier write with a superuser connection, so a forged 'signed' record is one bad request away. Here it isn't.

### Safeguards

Invariant 2:
- Every user-initiated write goes through a SECURITY DEFINER function called with the user's JWT and org header (get_supabase_for_user). That covers upload registration, execution confirmation, field confirmation, amendment links, counterparty domains, tags and confirmer grants. Each function checks auth.uid(), active_org_id(), role, department visibility and evidence in SQL.
- Users write the bytes to Storage with their own JWT, under a policy bound to their org and user folder. There is no update or delete policy.
- authenticated holds no INSERT, UPDATE or DELETE on the contract tables.
- The service role is used only by the ARQ worker and the connector webhooks. These are server-side jobs scoped to one org, the worker re-checks the uploader's membership, and they write status only through record_classification.
- With no Redis there is a 503 and no inline fallback.
- An AST test bans get_supabase_admin from the user paths.

Integrity of status:
- Every row is created 'pending', enforced for all roles by the guard trigger.
- sha256 is computed by the worker from stored bytes, never taken from the uploader.
- Status columns change only inside record_classification or confirm_execution, via a transaction-local app.contract_write flag.
- Pending rows are excluded from Q&A, portfolio answers, dedup and confirmation.
- Paralegal promotion is bound to sha256 and recorded append-only.
- Trash restores come back pending.

Signatures:
- Only CCA-chained or allowlisted vendor-sealed identities count, and self-issued certificates never do.
- The legal character is labelled: s.3A signature versus s.10A electronic record.
- First Schedule documents are blocked from confirmed cards.
- Trust-store fingerprints are pinned and CI-gated.

Data protection and the no-advice rule (UPL):
- Email intake trusts only AWS-signed verdicts.
- Text is PII-masked before it reaches Claude.
- Connector scopes are minimal (drive.file, Sites.Selected), for DPDP minimisation.
- Employment and personal-data contracts are visible to legal only by default.
- Stored signer data is limited to name, email, organisation, issuer, serial, time and authentication method. Aadhaar numbers are never stored.
- Business users see only lawyer-confirmed clauses, phrased as 'cl. X provides', with the disclaimer and an Ask-legal path to a lawyer.
- Retention follows the 013 trash flow.

### How the panel's objections were answered

All three blocking objections found the same contradiction. Authenticated users had INSERT revoked on contract_documents, yet step 2 inserted user uploads with the user's JWT. And 'pending' was missing from the enum. They also pointed to the forged-insert risk if INSERT were simply re-granted. Fixed as follows.

(1) There is a new SECURITY DEFINER RPC: public.register_contract_upload(p_storage_path, p_sha256, p_filename, p_tags, p_contract_id default null). It is called by POST /contracts/upload with ctx.db() = get_supabase_for_user(jwt, org_id). It:
- derives org from active_org_id();
- requires role owner, partner, associate or paralegal (42501 otherwise);
- checks that the storage object exists in the 'contracts' bucket, under <active_org>/<auth.uid()>/, with owner_id = auth.uid(), within the size limit, and not already registered;
- validates the filename, tags and optional contract against the caller's org and visibility;
- forces execution_status='pending', execution_evidence null, signature_types '{}', required_parties null, first_schedule_flag false and sha256 null, setting org_id and uploaded_by itself, with no parameters for those columns;
- writes a contract_ingest_queue outbox row.
The router enqueues the ARQ job after the RPC. A 5-minute sweep recovers any job whose enqueue failed. INSERT stays revoked from authenticated.

(2) The claimed sha256 is treated as untrusted, which closes the hole where 'the inserter chose both hashes'. It is stored as claimed_sha256 only. The row's sha256 is null until the worker downloads the bytes, hashes them and writes the hash through record_classification (service_role only). A mismatch is recorded as a reason. Bytes can't be swapped afterwards, because the bucket has no UPDATE or DELETE policy for authenticated.

(3) 'pending' is added to the execution_status enum. It is excluded from Q&A cards (can_show_confirmed_card requires executed), portfolio answers (listed as 'Processing'), dedup, the Execution tray and confirm_execution, which refuses it with 22023 'Document is still being processed'. record_classification refuses to set 'pending'.

(4) The guard trigger goes further than asked. On INSERT it rejects any non-pending status, non-null evidence or sha256, non-empty signature_types, required_parties, or a true first_schedule_flag, for every role, service_role and the table owner included. Worker connector deliveries, ZIP children and trash restores therefore all enter as pending. On UPDATE, the status, evidence and hash columns change only under the transaction-local app.contract_write flag, which only record_classification and confirm_execution set (the 013 guard_legal_hold pattern).

(5) The requested tests are in tests/db/test_contract_upload_rls.py:
- a direct authenticated INSERT with execution_status='executed' and forged paralegal evidence is denied, and so is a pending one;
- an RPC upload always lands pending, with null evidence and hash and the caller's org;
- the RPC is refused for paths in another org or user folder, for missing objects and for non-members;
- storage upsert and delete are denied;
- the guard rejects non-pending inserts even as service_role and the table owner;
- the trash restore comes back pending.
There are also router tests: 503 before any write without Redis, and the enqueue-failure sweep. A migration-parsing test asserts the enum contains 'pending' and that the RPC has no status or evidence parameters.

### Acceptance tests

- tests/db/test_contract_upload_rls.py: as an authenticated associate of firm A, a direct INSERT into contract_documents with execution_status='executed', execution_evidence={method:'paralegal', sha256:<x>, corroboration:{type:'other', note:'forged forged'}} and sha256=<x> is denied (42501 permission denied). A direct INSERT with execution_status='pending' is also denied. Zero rows are written.
- tests/db/test_contract_upload_rls.py: an associate of firm A uploads an object to contracts/<A>/<uid>/<uuid>/nda.pdf as authenticated and calls register_contract_upload. The returned row has execution_status='pending', execution_evidence null, signature_types '{}', first_schedule_flag false, sha256 null, claimed_sha256 = the passed value, org_id = A, uploaded_by = the caller, and a contract_ingest_queue row exists. A test parses the migration and asserts register_contract_upload has no parameter for status, evidence, signature types, parties or first-schedule flag.
- tests/db/test_contract_upload_rls.py: register_contract_upload is refused with 42501 'Upload not found' when the path is in firm B's prefix, in another user's folder of firm A, or owned by another user. It is refused with 22023 when the object doesn't exist, the path is already registered, the sha256 is not 64 hex characters, the filename contains '/', or the size is over the limit. A user who is not a member of B, sending x-org-id of B, gets 42501. A p_contract_id from firm B or a tag the caller can't see is refused.
- tests/db/test_contract_upload_rls.py: as authenticated, a storage UPDATE (upsert) and a DELETE of an object in the contracts bucket are denied, so registered bytes can't be swapped. Inserting an object into another org's prefix is denied by the storage policy.
- tests/db/test_contract_upload_rls.py, guard trigger: as service_role and as the table owner, an INSERT with execution_status 'executed', 'unknown' or any non-pending value is rejected ('Contract documents are created pending'), and so is an INSERT with non-null execution_evidence or sha256. An UPDATE of execution_status as the table owner without app.contract_write set is rejected. The same UPDATE via record_classification succeeds.
- tests/db/test_contract_upload_rls.py, record_classification on a pending row: it sets sha256 to the worker-computed value. When that differs from claimed_sha256 it records the reason 'upload hash mismatch'. p_status='pending' is refused. On a non-pending row a different p_sha256 is refused.
- tests/db/test_contract_upload_rls.py, trash round trip: trash a paralegal-confirmed document, then restore it. It returns as 'pending' with sha256 null. record_classification with the same bytes re-applies the confirmation (method 'paralegal', the original confirmed_by). With different bytes it doesn't.
- tests/db/test_contract_execution_rls.py: confirm_execution on a 'pending' row is refused with 22023 'Document is still being processed', and no execution_confirmations row is written. All round-5 tests are kept: cross-org 'Document not found' under either x-org-id; associate grant, revoke and refusal; owner, partner and paralegal success with method 'paralegal' and a matching sha256; direct UPDATE, INSERT and DELETE denied; record_classification denied to authenticated; department-tag hiding; the in-SQL party and corroboration validation; and guard-trigger evidence checks.
- tests/test_contract_upload_router.py: with REDIS_URL unset, POST /contracts/upload returns 503, and the mocked user client records no storage write and no rpc call. With Redis available, the router uploads via the client built from the caller's JWT and org, calls rpc('register_contract_upload'), then enqueues task_ingest_contract. If enqueue raises, it still returns 202. A test then runs task_sweep_pending_contracts with a frozen clock and asserts the job is enqueued once.
- tests/test_contract_upload_router.py: task_ingest_contract for an uploader who has since been removed from the org marks the outbox row 'abandoned', classifies nothing and writes an audit entry.
- tests/test_contracts_no_service_role.py: an AST check that app/routers/contracts.py, contract_repository.register_upload, the confirm path in execution_status.py and contract_qa.py never reference get_supabase_admin.
- tests/test_contract_qa.py: a pending row with confirmed-looking fields injected in fixtures never yields a confirmed card. Portfolio answers exclude it and list it under 'Processing'. can_show_confirmed_card returns False for every status except executed.
- tests/test_rbac.py: Permission.CONTRACT_UPLOAD equals {owner, partner, associate, paralegal} and Permission.CONTRACT_CONFIRM_EXECUTION equals {owner, partner, paralegal}. Each matches the role arrays in register_contract_upload, the storage insert policy and can_confirm_execution (the test parses migration 018). The enum is asserted to contain 'pending'.
- Round-4 suites are kept: test_signature_trust (self-signed CN match gives unknown/UNTRUSTED, CCA DSC plus Aadhaar eSign gives executed, expired, revoked or indeterminate revocation don't count, a fingerprint change fails CI); test_esign_vendors (completed envelope, pending signer, envelope-ID mismatch, CoC seal root, a fake 'DocuSign, Inc.' self-signed seal rejected); test_execution_status (e-stamp-only gives stamped_unconfirmed, a First Schedule POA is flagged, stamp_after_execution); test_email_in (SNS signature, cert host, TopicArn, forged Authentication-Results ignored, replay ingested once); test_extract_formats; test_zip_guards (ZIP children inserted pending in the ZIP's org); test_connector_scopes; and RLS isolation between Sales and Procurement and across orgs.

### Still blocking

- Trash restore cannot work as specified. Migration 013's restore_trash_item (supabase/migrations/013_approvals_trash_and_intake.sql, lines 627-705) re-inserts the snapshot with `insert ... select * from jsonb_populate_record(null::<table>, v_row)`. For a contract document that row still carries execution_status='executed', execution_evidence, signature_types and sha256. The new contract_documents_guard rejects any non-pending INSERT with 42501. It raises; it does not coerce. restore_trash_item's exception block only catches unique_violation and foreign_key_violation, so the restore aborts. The proposal says rows 'come back pending with sha256 null and are re-queued', but nothing does that: restore never writes a contract_ingest_queue outbox row, so even a pending row would never be re-classified. The sweep only picks up outbox rows. trash_item is also unspecified for this kind. Deleting a contract_documents row either breaks the append-only execution_confirmations rows (cascade) or is blocked by them (restrict). contract_fields lawyer confirmations would also be lost unless they are snapshotted as children. Fix I would accept: (1) add an explicit 'contract_document' branch to trash_item that snapshots contract_fields as children, and leaves execution_confirmations in place with no FK (or with an FK to a stable document id that is never deleted). (2) Add a branch to restore_trash_item that inserts the row with the classification columns overwritten to their pending defaults (status 'pending', evidence null, signature_types '{}', required_parties null, first_schedule_flag false, sha256 null), keeps storage_path, uploaded_by and claimed_sha256, and inserts a contract_ingest_queue row in the same transaction. (3) Have the trash round-trip test assert the outbox row exists and that no 42501 is raised.
- The trash round trip, which has its own acceptance test, cannot work as specified. restore_trash_item (013, lines 627-706) re-inserts the snapshot with `insert ... select * from jsonb_populate_record(null::<table>, v_row)`. For a classified contract document, that snapshot carries execution_status='executed', non-null execution_evidence, signature_types and sha256. The proposal's own contract_documents_guard raises 42501 'Contract documents are created pending' on any such INSERT; it does not coerce the row. So every restore of a classified or paralegal-confirmed document fails instead of 'coming back pending with sha256 null'. Two further gaps: (a) nothing in restore writes a new contract_ingest_queue row, so the row is never re-queued; and (b) the re-apply depends on execution_confirmations surviving trash_item's DELETE of the contract_documents row, but the FK behaviour is unspecified. With ON DELETE CASCADE the 'append-only' confirmations are destroyed. With RESTRICT, trash_item fails. Fix I would accept: add a 'contract_document' branch to restore_trash_item that overwrites v_row with execution_status='pending', execution_evidence=null, signature_types='{}', required_parties=null, first_schedule_flag=false and sha256=null before the insert, and that inserts a fresh outbox row. Declare execution_confirmations.document_id with no FK, or ON DELETE NO ACTION handled by keeping a tombstone, so confirmations survive trash. Then test that the restore succeeds as the definer and that the guard still rejects a non-pending insert.

