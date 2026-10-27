# P41. Electronic evidence is lost for want of a proper s.63 BSA (formerly s.65B) certificate

**Severity:** high · **Size:** small · **Region:** India

**Who has it:** Indian litigators in matrimonial, criminal, commercial and employment matters; clients holding chat or CCTV evidence

## What goes wrong

WhatsApp chats, emails, call recordings and CCTV are central evidence, but copies are admissible only with a s.63(4) BSA certificate (in force from 1 July 2024), except when the original device is produced. Lawyers file screenshots without a certificate, with the wrong format or signatory; the opponent objects and genuine evidence is excluded. Device preservation, hashes and chain of custody are improvised.

## Evidence of scale

- Under BSA s.63, WhatsApp chats need the s.63(4) certificate; screenshots can be refused and a 'no certificate' objection can exclude genuine messages. ([source](https://blog.ipleaders.in/whatsapp-chats-as-evidence-in-india/))
- LiveLaw: the s.63(4) certificate must identify the record, explain how it was produced and show a properly functioning device. ([source](https://www.livelaw.in/amp/articles/whatsapp-chats-reliable-source-of-evidence-indian-law-290734))
- Arjun Panditrao Khotkar (3-judge bench, 2020): the s.65B certificate is a condition precedent for secondary electronic evidence. ([source](https://conventuslaw.com/report/india-supreme-court-on-the-admissibility-of/))

## Why current tools don't solve it

No Indian or global AI tool ingests a phone export or CCTV file, records hashes and metadata, and generates the correct BSA s.63 certificate and an evidence index tied to the pleadings. E-discovery platforms (Relativity etc.) are US-priced and US-rule-based; research tools only explain the case law.

## Panel verdict

**Status:** solved (round 6)

**Effort:** M

### What software can fix

An electronic evidence kit for producing electronic records under s.63 BSA:
- It records the hash and metadata of the copy the firm received for each WhatsApp export, email, call recording or CCTV file, and keeps an append-only custody log.
- It generates the full Schedule certificate (Part A and Part B) and marks an item ready only when both parts are signed.
- It ties the exhibit index to pleading paragraphs.
- It ties the evidence's lifetime to its matter on every path a matter row can take: trash, purge or retention expiry, direct delete, organization delete, and departure through P36's offboarding.

Round 6 makes the custody log record every change of a matter's owner, whether the matter is live or in the trash, and on restore. It does this with one ledger and one recording function fired by triggers on court_cases, case_threads and trash_items. Matters are never erased at offboarding: they always move to P36's custodian.

### What it can't fix

Out of scope:
- Forensic imaging of devices and the expert's own examination.
- Whether the court accepts the evidence.
- Alterations made before the firm received the record, and the hash of the record on the original device. Our hash proves only the integrity of the copy we received, from the moment we received it.
- After erasure only a content-free tombstone remains.
- A Postgres superuser who disables triggers can bypass any database guard. That is an operational control.
- Offboarding, account erasure, choosing the custodian and moving ownership belong to P36. P41 adds no transfer path and no erase disposition. It supplies the evidence summary, the successor-eligibility guard and the custody recording, which fire whatever code changes the owner.

### What the user sees

Unchanged: the per-matter Evidence vault, 'hash of the copy received by the firm on <date>', metadata, custody log, Part A + Part B certificate DOCX, readiness checklist, exhibit index, trash and purge messages, the partners' Erasure record and item-level holds.

Changed in round 6:
(a) In P36's offboarding screen, the 'Electronic evidence' section is informational only. It lists each matter the leaver owns, live or in the trash, with counts of certified, held and uncertified items, and states 'Moves to <custodian> with the rest of Asha Rao's records. The transfer is written into each item's custody log.' There is no 'Erase with matter' option. Matters with certified or held evidence are marked 'needs a successor who is an active member', which P36's custodian satisfies.
(b) Each item's custody log shows one entry per owner change, with where it happened:
- 'Matter owner changed from Asha Rao to Priya Shah by <partner> (offboarding: <reason>)', live or while the matter was in the trash ('while in trash').
- 'Matter owner changed from Priya Shah to Vikram Shah on restore from trash by <partner>' when the restore assigns a different owner.
- Restoring to the same owner adds no entry.
(c) The account-erasure blocker and the Erasure record causes are unchanged from round 5.

### What the system does

Steps 1-17 and 20 are unchanged from round 5: hashing, metadata, append-only custody log, certificate parts, readiness, exhibit index, RLS, purge and tombstones, the delete guard on court_cases and case_threads (trash / refuse / purge branches), the organization delete trigger, P36's ON DELETE RESTRICT user FKs (asserted by test_fk_rule_is_restrict), and the nightly orphan check.

18. The owner ledger (new). Table evidence_matter_owner(matter_kind, matter_id, owner_user_id, owner_label, updated_at), with primary key (matter_kind, matter_id). It has no FK to users or matters, so it survives trashing and user deletion, and owner_label keeps the name at that time.
- A row is created with the matter's current owner when the matter's first evidence item is taken in; the intake custody event records that owner.
- purge_matter_evidence deletes it.
- RLS: no direct access for anon or authenticated. Read through the vault views only.

19. evidence_record_owner_change(p_kind text, p_id uuid, p_new_owner uuid, p_context text). Security definer, executable by no client role, called only by the triggers below.
(a) It locks the ledger row. If there's no row (no evidence) or owner_user_id equals p_new_owner, it returns without doing anything, which makes it idempotent.
(b) If the matter has certified or held evidence (or is on legal_hold), and p_new_owner is not an active member of the matter's org with role owner, partner or associate, it raises 55006 'evidence_requires_successor'.
(c) For every evidence item of the matter, it inserts one custody event {event:'matter_owner_changed', from_user: ledger owner, from_label, to_user, to_label, actor: coalesce(auth.uid(), current_setting('app.actor_id', true)), reason: coalesce(current_setting('app.transfer_reason', true), default for p_context), context: p_context}.
(d) It updates the ledger.

It is fired from three places:
- AFTER UPDATE OF user_id on court_cases and case_threads, when the owner actually changed. context 'live'.
- AFTER INSERT on court_cases and case_threads. This catches restore_trash_item's jsonb_populate_record insert, including P36's restore remap to the custodian or p_new_owner. context 'restore', default reason 'restored from trash'. A brand-new matter has no ledger row, so nothing is recorded.
- AFTER UPDATE on trash_items, for kind in ('court_case', 'case_thread') and NEW.snapshot is not null, when the owner changed: (NEW.snapshot->'row'->>'user_id') differs from OLD's, or NEW.owner_user_id differs from OLD's and is not null. The new owner is the snapshot row's user_id. context 'trash'. This catches P36 step d2's jsonb_set at the moment of offboarding.

Restore and purge both set snapshot to null, so they are excluded from the trash trigger. A user delete sets owner_user_id to NULL (013), and that alone is not a transfer.

The order of events is deterministic. Trash, then d2, records A to custodian once, at offboarding. The later restore to the custodian finds the ledger equal and adds nothing. A restore with p_new_owner records custodian to new owner. A trashed matter whose leaver was deleted before any d2 (should P36 ever allow that) is recorded on restore from the ledger's stored owner, so no gap is possible.

21. Offboarding contract with P36 (no erase). P41 provides:
- evidence_offboarding_summary(p_org, p_user): per matter (live or trashed: kind, id, title, in_trash), certified, held and uncertified counts and requires_successor. Callable by owners and partners only.
- the guard in step 19(b).

P36's offboard_member(p_org, p_user, p_custodian, p_plan) moves every matter to the custodian, or to a p_plan override, by its single transfer path, and may set app.transfer_reason and app.actor_id. It does not need to call any P41 function, because the triggers record and guard every path. 'Erase with matter' is dropped. The 'erase' disposition and test case are gone.

### Where it is built

Migration 018_evidence_vault.sql, ordered after P36's RESTRICT/transfer migration. It adds:
- evidence_matter_owner
- evidence_record_owner_change()
- triggers evidence_owner_change_live (AFTER UPDATE OF user_id) and evidence_owner_change_restore (AFTER INSERT) on court_cases and case_threads
- evidence_owner_change_trash (AFTER UPDATE) on trash_items
- removal of round 5's evidence_owner_change_custody (folded into the above)
- evidence_offboarding_summary() extended to trashed matters
- custody event context column, check in ('intake','live','trash','restore')
- revokes of execute on evidence_record_owner_change from public, anon and authenticated
- the rest as in round 5

Also:
- app/services/evidence_vault.py: summary wrapper.
- app/routers/evidence_vault.py: custody log rendering, including context labels.
- frontend EvidenceOffboardingSection: informational only, no erase control.
- task_storage_deletions and the orphan check: unchanged.

### Why current tools fail and this won't

No Indian or global tool hashes the file at intake and generates both parts of the BSA s.63 Schedule tied to the pleadings. Document stores track files by folder or user, so a departing lawyer's evidence changes hands with no record at all, and a 'restore from recycle bin' silently rewrites who held it.

Here the custody log is fed by a per-matter owner ledger and triggers on every place an owner can change: the live row, the trash snapshot and the restore insert. A transfer is recorded exactly once, whatever code made it. A matter with certified evidence can't be handed to someone outside the firm. The nightly check still proves nothing is orphaned.

### Safeguards

Evidence often holds third parties' personal data. It is stored encrypted under RLS that follows the matter, never sent to AI, and every access is logged. DPDP erasure is real on every deletion path, with content-free tombstones and a nightly orphan check.

Every owner change, whether on a live row, a trash snapshot or a restore, is written to each item's custody log exactly once by triggers that client roles can't call or bypass. Certified or held evidence can only pass to an active owner, partner or associate of the firm, and offboarding never erases matters. Transfer permissions live only in P36's function. The certificate is signed by the person in charge and the expert, never by us. A lawyer approves each exhibit before filing.

### How the panel's objections were answered

Objections 1, 2 and 4: owner changes on trashed matters skip the custody log.
- Owner recording now goes through one function, evidence_record_owner_change, against a per-matter owner ledger (steps 18-19). It is fired by an AFTER UPDATE trigger on trash_items, which catches P36 step d2's snapshot rewrite at the time of offboarding. It is also fired by an AFTER INSERT trigger on court_cases and case_threads, which catches restore_trash_item's re-insert, including P36's remap to the custodian or p_new_owner. The live AFTER UPDATE OF user_id trigger stays.
- The ledger makes the recording idempotent: trash, then offboard, then restore records A to the custodian once, and a restore to a different owner records that hop.
- Restore and purge, which null the snapshot, are excluded, and a SET NULL of owner_user_id alone is not a transfer.
- Tests: test_trashed_matter_owner_change_writes_custody, test_restore_with_new_owner_writes_custody, test_restore_after_leaver_deleted_without_d2 and test_restore_and_purge_do_not_fire_trash_trigger.
- P36 doesn't have to call anything, so its code can't forget to.

Objection 3: 'Erase with matter' contradicts P36.
- It is dropped. P41 defines no erase disposition, and the offboarding section is informational. Every matter moves to P36's custodian through offboard_member(p_org, p_user, p_custodian, p_plan), the signature used in test_offboard_moves_all_matters.
- requires_successor is satisfied by that transfer. The step 19(b) guard refuses only a move of certified or held evidence to someone who isn't an active owner, partner or associate (test_successor_guard).

### Acceptance tests

- tests/db/test_evidence_lifecycle.py::test_trashed_matter_owner_change_writes_custody: A owns court_case M with 3 uncertified items, and M is trashed. P36's offboard_member(org, A, custodian=P, plan) rewrites the snapshot owner (d2): exactly 3 matter_owner_changed events (A to P, context 'trash', reason from app.transfer_reason, actor set). Restoring M to P adds 0 events. The ledger owner is P, and P sees all items. The same holds for a case_thread.
- test_restore_with_new_owner_writes_custody: after the steps above, trash M again and restore with P36's p_new_owner = V. 3 events P to V, context 'restore'. A plain restore by the same owner adds none.
- test_restore_after_leaver_deleted_without_d2: simulate a snapshot still owned by deleted user A (owner_user_id NULL). Restore remapped to custodian P writes 3 events from A's stored label to P. Setting owner_user_id to NULL alone writes 0 events.
- test_owner_change_live: a live update of user_id from A to B (through P36's function, and separately a service-role direct update) writes one event per item, context 'live'. An authenticated direct update is denied by P36's grants. A no-op update of user_id (same value) writes none.
- test_successor_guard: moving a matter with a certified item to a user who is not an active member of the org (through the live update, the trash snapshot rewrite or a restore remap) raises 55006 evidence_requires_successor with nothing changed. Moving it to a paralegal raises the same. Moving a matter with only uncertified items to any active member succeeds.
- test_restore_and_purge_do_not_fire_trash_trigger: restore_trash_item and purge_trash_item, which set snapshot to null, write no owner-change events from the trash trigger.
- test_offboard_moves_all_matters (against P36's offboard_member(p_org, p_user, p_custodian, p_plan)): A owns M1 (2 certified), M2 (1 held), M3 (4 uncertified, in trash). All three move to the custodian. Custody events: 2 + 1 + 4. Tombstones: 0. There is no erase disposition in P41's UI or API. Then the user delete of A succeeds.
- test_record_function_not_client_callable: authenticated rpc evidence_record_owner_change gives 42501, and direct access to evidence_matter_owner is denied.
- test_offboarding_summary: includes trashed matters with in_trash true and the right counts. An associate caller gets 42501.
- Carried over from round 5: test_fk_rule_is_restrict, test_direct_delete_purges_uncertified, test_direct_delete_refused_certified_or_held, test_org_delete_refused_or_purges, test_erase_account_preflight, test_trash_still_keeps_evidence, test_trash_row_cannot_be_forged, test_trashed_matter_survives_owner_delete, test_guard_trigger_coverage (every matter kind now needs the delete guard and both owner triggers, plus the trash_items trigger), test_nightly_orphan_check, and the round 3 suite (hash on intake, both certificate parts, append-only custody, no AI in certificate fill, and the rest).

### Reviewers' minor notes

- coalesce(auth.uid(), current_setting('app.actor_id', true)) mixes uuid and text. Cast with nullif(current_setting('app.actor_id', true), '')::uuid, and record actor NULL with context 'system' when both are absent, rather than failing the trigger.
- The AFTER INSERT trigger fires on every new court_cases and case_threads row, including bulk imports. The 'no ledger row means return' path should be a cheap indexed lookup. Have test_guard_trigger_coverage also assert that the trigger is a no-op for INSERTs outside restore_trash_item.
- The successor guard raises inside an AFTER trigger, which aborts the whole offboard_member transaction. P36's UI should run evidence_offboarding_summary before offboarding and show which matters need an eligible custodian, so the partner sees why the whole offboarding rolled back instead of getting a bare 55006.
- actor: coalesce(auth.uid(), current_setting('app.actor_id', true)) mixes uuid and text, and Postgres rejects that COALESCE. Cast to a common type. When neither is set (for example a direct service-role update), record an explicit 'service_role:<context>' actor instead of NULL. A custody entry with no actor is weak evidence of the chain of custody under s.63 BSA.
- The successor guard raises inside the trash_items trigger during P36's offboard_member. If one matter in p_plan names a paralegal, the whole offboarding rolls back. The offboarding UI should pre-check this with evidence_offboarding_summary so the partner sees which matter blocks the transfer, not just a raw 55006.
- Ledger owner_label keeps departed users' names indefinitely. State in the retention notice that this is retained as a custody record (a legal obligation, DPDP s.8(7)), and that it is purged with the matter's evidence.
- Require app.transfer_reason and app.actor_id to be set with set_config(..., true), which is transaction-local. With is_local false on a pooled PgBouncer connection, a reason and actor from one offboarding leak into the next transaction's custody events. Add a test that a second transaction on the same connection sees neither.
- coalesce(auth.uid(), current_setting('app.actor_id', true)) mixes uuid and text. Cast with nullif(current_setting('app.actor_id', true), '')::uuid, and record actor_kind 'service' when both are null, so a service-role direct update isn't written with a blank actor.
- restore_trash_item's exception block catches only unique_violation and foreign_key_violation. Assert in test_successor_guard that 55006 raised from the AFTER INSERT trigger propagates, and that the trash_items row keeps its snapshot (restored_at stays null).
- Migration ordering: P02 and P08 both claim 014, P24 claims 016, P26 claims 017 and P41 claims 018, and 018 must also follow P36's migration. Fix the numbering once across all proposals before anyone builds.

