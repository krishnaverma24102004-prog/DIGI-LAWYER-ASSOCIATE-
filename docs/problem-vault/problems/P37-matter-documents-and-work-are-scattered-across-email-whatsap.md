# P37. Matter documents and work are scattered across email, WhatsApp, drives, portals and disconnected point tools

**Severity:** high · **Size:** big · **Region:** Global; India (acute)

**Who has it:** Solo advocates and small/mid firms (acute in India); fee earners using several unconnected systems; in-house teams with 3+ tools per matter

## What goes wrong

A matter's documents and facts are spread across Gmail, WhatsApp images, local folders, court portals, e-filing receipts and Excel diaries, and scans are often unsearchable. Each part of the work uses a separate tool (Word-centred drafting, research-only AI, contract-only platforms), so intake notes, research and drafts live apart and the lawyer copies context by hand. Switching between disconnected apps is a top daily frustration, and licences alone don't change how work is done.

## Evidence of scale

- iManage/Metia research (1,068 US/UK businesses): 28% say most or all documents are spread across multiple systems; 30% receive documents through five or more channels. ([source](https://www.legalfutures.co.uk/associate-news/less-than-a-quarter-of-businesses-adequately-support-knowledge-work))
- Tooliverse review aggregate: Spellbook 'restricted primarily to Microsoft Word' (29 reviews); 52 reviews mention hallucinations or incorrect citations; 41 opaque pricing. ([source](https://tooliverse.ai/tools/spellbook))
- G2 SpotDraft reviews: constant UI changes, bulk download limits, minor bugs, no notice of updates. ([source](https://ai.g2.com/product/spotdraft))

## Why current tools don't solve it

iManage and NetDocuments are enterprise-priced and heavy for small Indian firms. Harvey Vault and CoCounsel need uploads first. Practice-management tools store files but don't ingest WhatsApp media, OCR Indian-language scans or auto-file to a matter. Each incumbent covers one slice (Spellbook drafting, Lexis/Westlaw research, Clio practice management, SpotDraft CLM); Harvey is broader but enterprise-only. No tool carries one matter's context from client call through research, citation check and draft to the hearing date, or answers 'where is the latest X' across all channels.

## Panel verdict

**Status:** solved (round 3)

**Effort:** L

### What software can fix

One matter file that fills itself. Documents arriving by WhatsApp (images, PDFs, voice notes), by email to an unguessable matter address, by upload, and from the court tracker (orders) land in the right matter: OCR'd, de-duplicated, versioned, on a timeline, and labelled with their provenance. 'Where is the latest X' is answered by search that returns the documents themselves, not an AI guess. Email is auto-filed only when it reaches us through one pinned receiving provider whose deliveries are cryptographically signed (Amazon SES receiving, notified via signed SNS), the provider's own DMARC/DKIM/SPF verdicts show the sender is authenticated and aligned, and the sender is on the allowlist. Everything else waits in quarantine for a human.

### What it can't fix

We won't scrape court portals behind captchas, read the lawyer's whole Gmail or personal WhatsApp, or sync every cloud drive in round 1 (a Google Drive import can follow). Documents a client never sends us stay scattered. Physical files need scanning by someone. Email authentication proves the sending domain, not that a member's mailbox wasn't compromised. Senders whose domains publish no DMARC record and fail our aligned-DKIM/SPF check will always need a manual release. A document calling itself a court order is not proof it exists: only the eCourts-sourced copy is marked verified. Round 1 supports exactly one inbound provider, Amazon SES. Mailgun (HMAC-signed routes) is a possible second adapter. Postmark and SendGrid Inbound Parse don't sign deliveries, so they are not supported for auto-filing. We depend on AWS's signing and verdicts being correct, and on the region the firm chooses for SES receiving (a DPDP cross-border question we disclose; we can't fix it in code).

### What the user sees

Each matter has a 'File' tab: a timeline of everything in it, including the client's WhatsApp photos of the FIR, the forwarded email with the notice, the order downloaded from eCourts, drafts and transcripts. Each item shows its source, date, type (order, notice, agreement, evidence, receipt), version group and a provenance badge: 'eCourts (verified source)', 'WhatsApp from client', 'Email - authenticated (DMARC pass via SES, partner@firm.in)', 'Uploaded by A. Rao'. Orders from anywhere but eCourts are labelled 'order - not verified against eCourts'.

The matter email address ('m-k7q2x9fh3w4tzr6bny5c8dj2ma@in.<firm receiving domain>') is shown with a copy button, plus 'Rotate address' and 'Revoke' buttons for owners and partners, and the date of the last rotation. Settings shows the receiving setup as 'Inbound email: Amazon SES (<region>), signed delivery verified', with the last verified delivery time, or a red 'Not configured - email filing off'.

An 'Unfiled' tray lists items the system couldn't match, with suggested matters filed in one click. A 'Quarantine' tray lists emails that failed authentication or came from unknown senders, with the reason ('DMARC fail (SES verdict); From claims partner@firm.in', 'Sender domain has no DMARC (GRAY) and no aligned DKIM'). Each shows a plain-text preview (no HTML, no live links) and 'Release to matter' or 'Discard'. Releasing needs a lawyer's click and is audit-logged.

The search box takes queries like 'latest order in Sharma', 'lease agreement' or 'e-filing receipt' and returns ranked documents with snippets and dates.

### What the system does

1. Migration 018_matter_file.sql adds:
   * columns on documents: thread_id, source (upload|whatsapp|email|ecourts|draft), source_ref, sha256 (unique per org), doc_class, doc_date, version_group, received_from, provenance jsonb, source_verified
   * inbound_items (Unfiled and Quarantine trays, with a reason)
   * matter_addresses (thread_id, token_hash bytea unique, token_prefix, created_at, rotated_from, revoked_at)
   * inbound_events (sns_message_id primary key, ses_message_id unique, received_at), for replay and duplicate protection like stripe_events
2. Pinned inbound channel: Amazon SES email receiving for the firm's receiving subdomain (MX to SES). A receipt rule (a) stores the raw MIME in a private S3 bucket (SSE-KMS, lifecycle delete after 1 day) and (b) publishes the SES notification to one SNS topic, configured with SignatureVersion 2. Our endpoint POST /api/v1/inbound/ses is subscribed to that topic over HTTPS. Config: SES_INBOUND_TOPIC_ARN, SES_INBOUND_BUCKET, SES_INBOUND_PREFIX, SES_REGION. Without them, email filing is off and the endpoint returns 404.
3. services/inbound_auth.py (deterministic; shared with P42), verify_sns(request) -> SnsEnvelope or reject (401, nothing written):
   * The body must parse as an SNS JSON message. Type must be Notification or SubscriptionConfirmation, TopicArn must equal SES_INBOUND_TOPIC_ARN exactly, and SignatureVersion must be '2' (SHA256withRSA; version 1/SHA1 is refused).
   * SigningCertURL must be https, with a host matching ^sns\.[a-z0-9-]+\.amazonaws\.com$ and a path ending .pem, and no userinfo, port or query. Any other URL is refused before anything is fetched. The certificate is fetched with redirects disabled and cached by URL. It must chain to the system trust store, be within its validity period, and have subject CN sns.amazonaws.com.
   * The canonical string is built per the SNS spec (for Notification: Message, MessageId, Subject if present, Timestamp, TopicArn, Type, each as 'key\nvalue\n'), and the RSA signature is verified with the certificate's key.
   * Timestamp must be within 1 hour of now (replay window). MessageId is inserted into inbound_events, and a conflict means a duplicate, answered 200 and ignored.
   * SubscriptionConfirmation is honoured only for the configured topic, and SubscribeURL must pass the same host check. As defence in depth, the endpoint path also carries a basic-auth secret, but that is never treated as authentication of the mail.
4. Email verdicts come only from the signed envelope, never from the message headers. services/inbound_auth.email_verdict(ses_notification, raw_mime):
   * The ses_notification is the 'Message' field of the verified SNS envelope.
   * receipt.virusVerdict FAIL means reject and discard. receipt.spamVerdict FAIL means quarantine.
   * AUTHENTICATED if receipt.dmarcVerdict.status == PASS. SES evaluates DMARC against the RFC5322.From domain, so PASS includes alignment.
   * Otherwise (dmarcVerdict GRAY, no DMARC record), it is AUTHENTICATED only if:
     - receipt.dkimVerdict == PASS and our own DKIM check of the raw MIME (dkimpy) finds a valid signature whose d= has the same organizational domain as From (vendored Public Suffix List); or
     - receipt.spfVerdict == PASS and mail.source (the envelope MAIL FROM recorded by SES) has the same organizational domain as From.
   * dmarcVerdict FAIL is always NOT_AUTHENTICATED, even if other checks pass.
   * Multiple From addresses, a missing From, or a From that doesn't match mail.commonHeaders.from also give NOT_AUTHENTICATED.
   * Any Authentication-Results, Received-SPF or X-* verdict headers inside the MIME are ignored for authentication.
5. Raw message retrieval: the notification's receipt.action must be S3, with bucketName == SES_INBOUND_BUCKET and an objectKey under SES_INBOUND_PREFIX; otherwise reject. The object is fetched with the server's IAM role (read-only on that prefix). Its message id must match mail.messageId, and it is deleted after ingestion. For messages under 150 KB, SES's Base64 SNS content may be used instead, but only from the verified envelope.
6. Filing decision for email:
   * The matter token is taken from the envelope recipients in receipt.recipients, not from To/Cc headers. It is hashed and looked up.
   * Auto-file only if AUTHENTICATED, the token is active, and From is an org member's verified email or a client email already on that matter.
   * Everything else goes to quarantine with a reason: not authenticated (with the SES verdicts), unknown sender, a rotated token in its 7-day grace period, a token whose matter the sender has no relation to, or a spam verdict.
   * Unknown or revoked tokens get the same 200 response as valid ones and are dropped. Attempts are counted per envelope sender and source IP (mail.source and receipt data) and rate-limited through core/rate_limiter.
   * Release from quarantine is a lawyer's click, recorded in audit_logs, and the provenance keeps the failure reason.
7. Matter tokens are secrets.token_bytes(16), base32 (26 characters). Only sha256(token) is stored; the full address is kept in an encrypted column readable only by RLS-scoped members. Rotation and revocation are unchanged from round 2.
8. WhatsApp media: whatsapp_intake is extended to download image and document messages (download_media), OCR them and attach them to the conversation's thread, behind the existing consent gate. The vision fallback is used only with OCR_VISION_FALLBACK on and the thread's ai_consent_at set.
9. eCourts orders: new order entries with a provider PDF link are filed as doc_class 'order' with source_verified=true. Orders from any other source are unverified and never change hearing dates.
10. Filing rules in code, in order: matter token (email); CNR regex; case number + court; sender equals the matter's client contact; otherwise Unfiled. The AI may suggest a matter from the masked first page, but only a human click files it.
11. De-duplication by sha256; versioning by normalised filename stem + doc_class within a thread. Classification is rule-based first, with a haiku fallback that returns a label only, from masked text.
12. Untrusted content: extracted text is stored with its provenance and wrapped as quoted source data when agents or RAG use it. Quarantined items are excluded from RAG and search.
13. Search: Postgres full-text plus the existing pgvector embeddings, filtered by thread and RLS. 'Latest' is parsed in code and sorts by doc_date descending. It returns documents, not generated prose.

### Where it is built

Extend:
* app/services/whatsapp_intake.py and whatsapp_service.download_media
* app/routers/documents.py, app/services/document_service.py, app/services/ocr_service.py
* app/services/ecourts_service.py sync
* app/services/rag_service.py (provenance wrapper, quarantine exclusion)
* core/rate_limiter.py (token-guess throttling)
* app/services/audit_service.py (releases, rotation, revocation)
* the stripe_events idempotency pattern from app/services/stripe_service.py (inbound_events)
* supabase/migrations/003_documents.sql (new columns)
* 013 legal hold (filed documents inherit it)

New:
* supabase/migrations/018_matter_file.sql
* app/services/inbound_auth.py: verify_sns, email_verdict and org-domain alignment with a vendored public_suffix_list.dat. It is shared with P42, whose contract-intake mailbox should call the same two functions.
* app/services/inbound_ses.py (S3 fetch, recipient-token extraction)
* app/services/matter_file.py, app/services/doc_classifier.py
* app/routers/inbound_email.py (POST /api/v1/inbound/ses), app/routers/matter_file.py
* infra/ses_inbound.md plus a Terraform/CloudFormation snippet for the receipt rule, bucket, KMS and SNS topic (SignatureVersion 2)
* frontend/src/components/MatterFile.tsx, UnfiledTray.tsx, QuarantineTray.tsx
* tests/test_matter_file.py, tests/test_inbound_auth.py with SNS-envelope and .eml fixtures

New dependencies: cryptography (already transitive), dkimpy, boto3 (S3 read only).

### Why current tools fail and this won't

iManage and NetDocuments are enterprise-priced and heavy for small Indian firms. Harvey Vault and CoCounsel need manual uploads. Clio stores files but doesn't ingest WhatsApp media, OCR Indian-language scans or file court orders automatically. Spellbook lives in Word, SpotDraft in CLM. Mail-to-matter features elsewhere usually trust the From header, or an unsigned parse webhook whose fields anyone who learns the URL can forge. Our trust root is a delivery signed by AWS: SNS's RSA signature from a pinned certificate host, a fixed topic, and a replay window, with SES's own DMARC/DKIM/SPF verdicts inside the signed payload. Nothing an attacker can put in a POST body or a mail header changes the verdict. Documents are then filed by deterministic keys (a 128-bit matter token from the envelope recipient, CNR, client contact) into the same matter that holds the consultation, research, drafts, hearings and bills, each with its provenance, so a forged 'order' can never pose as a verified one.

### Safeguards

Authenticity:
* One pinned inbound provider (SES via SNS). Every delivery is verified by SNS RSA-SHA256 signature from a pinned certificate host, an exact topic ARN, a 1-hour replay window and MessageId de-duplication.
* Mail verdicts come only from SES's receipt inside the signed payload: DMARC PASS, or DKIM/SPF aligned to the From organizational domain when DMARC is absent. Message headers never count.
* Raw MIME is fetched only from the pinned bucket/prefix and deleted after ingestion.
* Unsigned providers (Postmark, SendGrid parse) are not supported for auto-filing.
* Auto-filing also needs an allowlisted sender. Everything else is quarantined, excluded from RAG and search, and released only by an audited lawyer click.
* Matter tokens are 128-bit, taken from envelope recipients, stored hashed, rotatable and revocable, with no existence oracle, and rate-limited.
* Only eCourts-sourced orders are marked verified.

DPDP and privilege:
* Nothing from a client channel is processed before consent.
* The SES receiving region is disclosed in Settings and on the About page as a cross-border transfer where it is outside India. The S3 copy is encrypted and deleted within a day.
* Documents are RLS-scoped. PII is masked before any model call.
* The vision fallback respects OCR_VISION_FALLBACK and per-matter consent.

Prompt injection: email and document text is data, wrapped with provenance. The quarantine preview is plain text with links disabled.

Service role: the SES endpoint is a server-side job, signature-verified and scoped to the token's org (to be listed under CLAUDE.md invariant 2).

### How the panel's objections were answered

Objection (the trust root named providers that don't sign inbound webhooks): fixed as the reviewer proposed, by pinning one provider that signs deliveries and reports verdicts itself.

* Postmark and SendGrid are dropped. Round 1 supports only Amazon SES receiving with SNS notification. They are not offered even as a weak quarantine-only channel, so no unsigned path to the matter file exists. Mailgun (HMAC-SHA256 timestamp/token signature plus a replay window) is named as a possible later adapter behind the same interface.
* services/inbound_auth.verify_sns checks the SNS envelope:
  - SignatureVersion 2 RSA-SHA256 over the spec's canonical string;
  - SigningCertURL limited to https on ^sns\.[a-z0-9-]+\.amazonaws\.com$ with a .pem path, checked before any fetch, no redirects, and the certificate chaining to the system trust store with CN sns.amazonaws.com;
  - TopicArn equal to the configured topic;
  - Timestamp within 1 hour;
  - MessageId de-duplicated in inbound_events.
  An attacker who learns the URL can no longer POST a fabricated message: without AWS's signing key the request gets 401 and nothing is fetched or written.
* email_verdict uses only SES's receipt.dmarcVerdict, dkimVerdict, spfVerdict, spamVerdict and virusVerdict from inside the signed payload. DMARC PASS counts directly, since SES evaluates DMARC against the From domain. When DMARC is GRAY, we require organizational-domain alignment (our own dkimpy check of d=, or SES's mail.source for SPF). The authserv-id header parsing is removed: no header in the MIME can affect the verdict.
* The matter token is read from the signed receipt.recipients, not from the To header. The raw MIME is fetched only from the pinned S3 bucket/prefix.
* inbound_auth is one shared module with P42 (a note has been sent to P42's owner).
* Tests: test_unsigned_webhook_rejected (now buildable: an unsigned, mis-signed or attacker-signed SES-shaped body gives 401), test_sns_signature_valid, test_sns_cert_url_pinning, test_sns_topic_and_replay, test_subscription_confirmation, test_dmarc_fail_quarantined, test_dmarc_gray_alignment, test_forged_auth_header_ignored, test_virus_and_spam_verdicts, test_s3_location_pinned, test_token_from_envelope_recipient and test_not_configured.

The round-2 fixes (128-bit hashed tokens, quarantine, provenance) are unchanged.

### Acceptance tests

- test_unsigned_webhook_rejected: a POST to /inbound/ses with an SES-shaped JSON body (with dmarcVerdict PASS) but no SNS signature, a bad signature, or a body re-signed with an attacker key returns 401, fetches nothing from S3 and writes nothing.
- test_sns_signature_valid: with a test CA and an 'sns.amazonaws.com' certificate injected as the trust anchor and certificate fetcher, a correctly signed SignatureVersion 2 Notification is accepted. Changing any canonical field (Message, Timestamp, TopicArn) after signing makes it fail.
- test_sns_cert_url_pinning: SigningCertURL values 'http://sns.us-east-1.amazonaws.com/x.pem', 'https://sns.us-east-1.amazonaws.com.evil.com/x.pem', 'https://evil.com/sns.pem', 'https://user@sns.ap-south-1.amazonaws.com/x.pem' and a redirecting URL are each refused before any network fetch (the mocked fetcher is not called). SignatureVersion '1' is refused.
- test_sns_topic_and_replay: a valid signature on a different TopicArn gives 401. A Timestamp 2 hours old gives 401. The same MessageId twice is processed once (the second gets 200, no new rows).
- test_subscription_confirmation: confirmation for the configured topic calls SubscribeURL once (host-checked). For another topic or a bad SubscribeURL host, nothing is called.
- test_email_authenticated_member_filed: a signed envelope with receipt.dmarcVerdict PASS, From partner@firm.in, envelope recipient m-<token>@ and raw MIME in the fixture S3 bucket files its two attachments to the token's thread with provenance 'authenticated (DMARC pass via SES)', and deletes the S3 object.
- test_dmarc_fail_quarantined: the same message with dmarcVerdict FAIL (and dkimVerdict PASS for a third-party domain) lands in quarantine with reason 'not authenticated', creates no document, and is absent from search and RAG.
- test_dmarc_gray_alignment: with dmarcVerdict GRAY, a dkimVerdict PASS plus a DKIM signature d=mail.firm.in valid under dkimpy (test DNS resolver) and From partner@firm.in is filed. d=mailer.example is quarantined. spfVerdict PASS with mail.source bounce@firm.in is filed; with mail.source bounce@esp.example it is quarantined.
- test_forged_auth_header_ignored: raw MIME carrying 'Authentication-Results: mx.firm.in; dkim=pass; dmarc=pass' inside a signed envelope whose dmarcVerdict is FAIL is quarantined. Header contents never change the verdict.
- test_virus_and_spam_verdicts: virusVerdict FAIL is discarded with nothing stored. spamVerdict FAIL from an otherwise authenticated member goes to quarantine.
- test_s3_location_pinned: a signed notification whose receipt.action.bucketName or objectKey lies outside the configured bucket/prefix is rejected and not fetched. A raw object whose Message-ID doesn't match mail.messageId is rejected.
- test_token_from_envelope_recipient: a message whose To header names a valid matter token but whose receipt.recipients contain only an unknown token is dropped with the same 200 response. Writes nothing to any thread.
- test_token_entropy_and_rotation: tokens decode to 16 bytes, 10,000 are distinct, and only sha256 is stored. After rotate(), the old token goes to quarantine for 7 days and is dropped after revoke(). Unknown tokens get an identical response. Repeated attempts from one envelope sender are rate-limited.
- test_not_configured: with no SES_INBOUND_TOPIC_ARN, /inbound/ses returns 404 and Settings shows 'email filing off'.
- test_quarantine_release_audited: release files the item and writes an audit_logs row with the user and the original SES verdicts in provenance.
- test_order_provenance: an 'ORDER' PDF by authenticated email is classified 'order' with source_verified=false and leaves court_cases hearing dates unchanged. The eCourts-synced order is source_verified=true.
- test_whatsapp_pdf_filed: a consented conversation's PDF is filed once with source='whatsapp'. Before consent nothing is downloaded.
- test_cnr_filing, test_dedup_and_versions, test_latest_order_search (RLS across orgs), test_vision_fallback_gated and test_legal_hold_inherited are as in round 2.

### Reviewers' minor notes

- Configuration is platform-level (one SES_INBOUND_TOPIC_ARN, one bucket), yet the text says 'the region the firm chooses'. State that the platform operates SES receiving in one region, and disclose that region. Also check that SES email receiving is offered in the region you pick: it isn't available in every region, including possibly ap-south-1. If it isn't, the cross-border disclosure is mandatory, not conditional.
- SNS signing certificate CNs and hosts in some partitions differ (for example amazonaws.com.cn). Treat that as unsupported explicitly rather than silently refusing it.
- Opposing counsel's notices reach the firm from senders who aren't on the allowlist, so they will always go to quarantine unless a lawyer forwards them. That's correct, but tell users plainly that forwarding is the normal path.
- P42 still describes trusting Authentication-Results headers. Make sure P42 actually uses this module, because otherwise the forgeable path P37 closed still exists.
- SES email receiving is offered only in a few AWS regions. Today that likely excludes ap-south-1, so in practice every firm's mail will be stored outside India. Say so plainly in Settings and on the About page, not only 'if outside India'.
- A client email auto-filed to a matter runs OCR and classification. The haiku classification fallback should go through the P20 matter and consent gate, the same way the WhatsApp media path is gated on ai_consent_at.
- Migration 018 collides with P42's 018_contracts_repository.sql. Renumber.
- SES email receiving is available only in a subset of AWS regions. Confirm the regions the firms are likely to pick, since ap-south-1 may not be offered, and state the cross-border consequence in the setup docs.
- The SES notification carries mail.source (the envelope MAIL FROM) but no sending IP in a dependable field. Rate-limit by envelope sender and token-guess counts, not by 'source IP'.
- P42's proposal still trusts provider Authentication-Results headers. The shared inbound_auth module only helps if P42 actually adopts it (raised as a blocker on P42).
- Migration 018 collides with P42's 018_contracts_repository.sql.

