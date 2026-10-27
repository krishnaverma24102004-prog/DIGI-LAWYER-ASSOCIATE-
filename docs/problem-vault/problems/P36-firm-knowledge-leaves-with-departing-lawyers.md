# P36. Firm knowledge leaves with departing lawyers

**Severity:** high · **Size:** big · **Region:** Global; India

**Who has it:** Mid-size and large firms with associate turnover; Indian chambers dependent on one senior; in-house teams

## What goes wrong

Associates leave within a few years, taking precedents, client preferences, matter history and know-how. Often one person knows a matter type or a client's quirks, and successors rerun research, redraft or miss deadlines only the leaver tracked. In India know-how sits in seniors' heads, personal email and WhatsApp, usually with no DMS.

## Evidence of scale

- NALP Foundation CY25: associate attrition 19% (4,442 departures across 141 firms); 83% left within 5 years; firms of 100 or fewer attorneys had 24%. ([source](https://www.nalpfoundation.org/news/the-nalp-foundation-releases-latest-update-on-associate-attrition-and-hiring-(cy-25)))
- LEAP Global Report 2026 (700 professionals): 53% of firms have limited or no documentation to retain knowledge when staff leave. ([source](https://www.lawyersweekly.com.au/sme-law/44540-aussie-law-firms-risk-knowledge-drain-from-lack-of-documentation))

## Why current tools don't solve it

iManage, NetDocuments and Harvey Vault search documents already filed; they don't capture tacit reasoning (why a clause was conceded, judge preferences, failed arguments). Litera and Intapp index deal metadata. Most Indian firms have no DMS. No tool builds a persistent, permissioned matter memory from consultations, calls, drafts and hearing outcomes that a successor can query.

## Panel verdict

**Status:** solved (round 5)

**Effort:** M

### What software can fix

Make matter knowledge and records belong to the firm, while respecting that in India the vakalatnama is personal to the advocate and clients may follow the lawyer out. Departure never destroys a firm record, including records sitting in the 30-day trash. Erasing a departed lawyer's account leaves no reference to their id anywhere: not in live tables, not in trash snapshots, and not one restored by a trigger. Removal ends with a verified sweep driven by a classified registry of every foreign key to users and every user reference inside trash snapshots. A client who leaves gets their file promptly, sent only to them or to an advocate they have named in writing. Know-how is captured at the moment of work, and approved drafts are reused only as code-anonymised templates.

### What it can't fix

Know-how that never entered the system can't be recovered. Filing the vakalatnama or NOC, the client's choice of advocate, and handing over original paper documents are human acts; we create and track the tasks. We can't verify that an uploaded client instruction is genuine; the lawyer confirms it and the record says so. Code anonymisation can miss an unusual identifying fact written in prose, which is why a partner confirms every template. Fee disputes are legal matters outside the app, and the app doesn't let them hold up a file. Snapshots already purged by the retention job are gone by design (only the tombstone remains), and departure doesn't change that. Historic data in personal channels belongs to P35/P37.

### What the user sees

Unchanged from round 4: 'Hand over first' on /team (records custodian, matter dispositions, number choices), followed by the 'Complete removal' summary.

The summary now also counts the trash, for example '412 records will move to Priya Shah, including 3 items in the trash (restorable until 14 Nov)'.

A restored record shows 'Restored, now owned by Priya Shah (records custodian for A. Mehta)'. An approved draft shows 'Approved by A. Mehta (former member)' even after Mehta's account is erased, and the approval date is kept.

The client-file release, Handover Pack, knowledge cards and template leak check are as in round 3.

### What the system does

1. Migration 014 changes owner foreign keys to RESTRICT and adds author_name snapshots, as before. NEW: drafts.approved_by_name. stamp_draft_approval fills it from public.users.full_name whenever it stamps approved_by, and clears it whenever approval lapses.

2. The registry public.member_owned_tables(table_name, column_name, org_column, class) is as before (owned_record | membership | identity | actor_set_null). NEW class snapshot_owner covers trash_items.owner_user_id. It is SET NULL in 013, but it is rewritten at offboarding (step d2), not left alone.

NEW registry public.member_snapshot_paths(kind, path, class) covers user references inside trash_items.snapshot:
- owned_record: ('transcript','row.user_id'), ('document','row.user_id'), ('draft','row.user_id'), ('review_grid','row.user_id'), ('court_case','row.user_id'), ('case_thread','row.user_id')
- actor_set_null: ('draft','row.approved_by'), ('case_thread','row.legal_hold_by'), ('case_thread','row.ai_consent_by'), ('court_case','row.legal_hold_by'), ('document','children[].reviewed_by'), ('review_grid','children[].reviewed_by'), ('knowledge_source','children[].created_by'), plus any further columns found by the test.

3. offboard_member(p_org, p_user, p_custodian, p_plan) keeps steps (a) to (f) from round 4. NEW step (d2), the trash: it locks this org's live trash_items (restored_at and purged_at null, snapshot not null) FOR UPDATE. For each item:
- if owner_user_id = p_user, set it to p_custodian;
- for each owned_record snapshot path of that kind whose value is p_user, jsonb_set it to p_custodian;
- then recompute snapshot_sha256 the same way trash_item computes it, and add {trash_id, kind, old_sha256, new_sha256, paths_changed} to the audit details.
It also inserts offboardings(org_id, departed_user_id, departed_name, custodian_id, at) for later lookups.
Step (g), the post-condition, now also asserts that no live trash item in p_org has owner_user_id = p_user or an owned_record snapshot path equal to p_user.

4. erase_account(user) is a security definer function, in one transaction:
(a) Preconditions as before: it deletes the sole-member personal workspace, and refuses, naming the firm, if the person is still in any firm.
(b) NEW: it sets set_config('app.erasing_user', uid, true) and set_config('app.legal_hold_change','on', true).
(c) NEW: for every actor_set_null registry row, it runs UPDATE <table> SET <col> = null WHERE <col> = uid, collecting {table, column, row ids} into the audit details with the person's name. For every actor_set_null snapshot path in live trash items, it nulls the value and recomputes the sha (also recorded).
(d) NEW trigger change: stamp_draft_approval's final else branch keeps old.approved_by unless all three hold: new.approved_by is null, current_setting('app.erasing_user', true) = old.approved_by::text, and current_user is not anon or authenticated. In that case approved_by stays null while approved_at and approved_by_name are kept. Ordinary user updates still can't blank an approver. stamp_ai_consent needs no change, because it only acts when ai_consent_at changes. guard_legal_hold passes because of the GUC and because it runs as definer.
(e) It deletes public.users and auth.users.
(f) NEW post-condition, over every registry row of every class: SELECT 1 FROM <table> WHERE <col> = uid returns nothing. No trash snapshot in any org contains uid at a registered path, and, as a backstop, snapshot::text doesn't contain the uid string. Otherwise it raises and rolls back everything.
(g) One audit_logs row, which keeps attribution (name, former roles and nulled stamps) after the identity is gone.

5. NEW: restore_trash_item gets a defensive mapping before the insert:
- For each owned_record snapshot path whose user isn't a current member of the org (or no longer exists), it maps the owner to the custodian from offboardings for that org and user. If there's no offboarding record, it raises 'choose a new owner' (P0001), and a partner can call restore_trash_item(p_id, p_new_owner), where p_new_owner must be a current member.
- For each actor_set_null path whose user no longer exists, it sets null.
- trash_items.owner_user_id is updated to match.
This covers a record trashed by the departing person concurrently with offboarding, and legacy departures from before migration 014.

6-8 (client-file release, knowledge cards, template leak check, retrieval walls and Handover Pack) are unchanged.

### Where it is built

Extend:
- supabase/migrations/013 functions, redefined in 014: stamp_draft_approval (the erasure branch and approved_by_name) and restore_trash_item (the owner and actor mapping, optional p_new_owner). trash_item is unchanged; its sha recipe is reused.
- app/services/org_service.py remove_member, which calls the offboard_member rpc with the user's JWT.
- app/routers/organizations.py
- app/services/safety_service.py: the trash restore route passes p_new_owner.
- app/services/handover_service.py
- the P13 deadline engine
- app/worker.py
- frontend/src/app/team/page.tsx (trash counts in the summary)
- the trash UI's restored-owner label

New in migration 014:
- the member_owned_tables class snapshot_owner
- member_snapshot_paths
- offboardings
- drafts.approved_by_name
- the updated offboard_member and erase_account

Tests: tests/db/test_member_registry.py, extended with snapshot-path completeness and trigger coverage, and tests/db/test_offboarding_trash.py.

### Why current tools fail and this won't

iManage, NetDocuments and Harvey Vault store documents but don't capture reasoning, rely on manual precedent scrubbing, and assume the firm owns the client relationship. Their deletion and retention features treat a departed user's items as orphans. Most Indian firms have no DMS at all.

We model Indian practice: a personal vakalatnama, an NOC, clients following the advocate, and the client's right to the file with no lien. Ownership transfer is one verified transaction. It covers live rows and trash snapshots, its registry classifies every user reference including those inside jsonb snapshots, and schema tests fail CI on any unclassified one. Erasure proves its own completeness with a post-condition, so a trigger or a snapshot can't leave a dangling reference.

### Safeguards

Records:
- No firm record is destroyed when someone leaves, live or trashed. RESTRICT foreign keys and a transactional sweep cover live rows and trash snapshots, with post-conditions, all audit-logged with before and after snapshot hashes.
- Memberships are deleted, never reassigned.
- The custodian must be an existing owner or partner.

Erasure:
- Erasure (DPDP) is complete and provable. Explicit nulling under a definer-only GUC, which no client path can set, is followed by a post-condition over every registered column and snapshot path.
- Attribution survives in author_name, approved_by_name and the audit row, not in a live foreign key.
- Ordinary users still can't blank an approver.

Access and clients:
- Restoring a departed person's record goes to the custodian or to a partner-named member, never to a non-member.
- Client files go only to the client or a client-named advocate, can't be held for fees (R.D. Saxena), and escalate when overdue.
- offboard_member runs with the caller's JWT, with no service role in the user path (invariant 2).

### How the panel's objections were answered

Objection 1 (the SET NULL on drafts.approved_by was undone by stamp_draft_approval): erase_account no longer relies on foreign-key actions.
- Before deleting the user, it sets app.erasing_user (and app.legal_hold_change) with set_config(..., true), then explicitly nulls every actor_set_null column, and every actor path inside trash snapshots, recording each nulled stamp in the audit row.
- stamp_draft_approval's else branch lets approved_by become null only when the GUC equals old.approved_by and current_user is not anon or authenticated, so ordinary edits still can't blank an approver.
- The new drafts.approved_by_name, stamped by the same trigger, keeps the approval attributed as 'A. Mehta (former member)', and approved_at is kept.
- A post-condition over every registry row of every class, plus all trash snapshots, proves no reference to the erased uuid remains, or it rolls back.
Tests: an approved-draft erasure, a trigger-reverting test table that forces rollback, and a check that the trigger still blocks client-side blanking.

Objection 2 (the trash was never swept): offboard_member gains step d2. It locks the org's live trash_items, rewrites owner_user_id and every owned_record snapshot path from the departed user to the custodian, recomputes snapshot_sha256 with trash_item's recipe, and logs the old and new hashes. The post-condition now includes the trash.
As a second layer, restore_trash_item maps any owner who is no longer a member, or no longer exists, to the custodian recorded in the new offboardings table, or to a partner-chosen current member, and nulls actor paths whose user no longer exists. A record trashed in a race, or under a pre-014 departure, therefore still restores.
A snapshot-path registry, with a pg_constraint completeness test, keeps new tables from reopening the gap.
Tests: trash, offboard, erase, restore gives a record owned by Priya; restore after offboarding but before erasure gives the same; knowledge-source children restore with created_by null; and the race fallback works.

### Acceptance tests

- Approved draft survives erasure: Mehta approves a draft and is offboarded (custodian Priya), then erased with erase_account. drafts.approved_by is null, approved_at is unchanged, approved_by_name is 'A. Mehta', and the erase audit row lists the draft id under drafts.approved_by. No row anywhere references Mehta's uuid, checked over every registry row of all classes
- Trigger still protects approvals: an authenticated user's update that sets approved_by to null with approved_at unchanged keeps the old approver. The same update with app.erasing_user set through a client-callable path is impossible (current_user is authenticated), so the approver is kept
- Erasure post-condition: a test-only table with an actor_set_null column and a BEFORE UPDATE trigger that restores old values makes erase_account raise and roll back. public.users and auth.users still hold Mehta and nothing is nulled
- Trash before offboarding: Mehta trashes their own draft and Priya approves trashing their transcript. offboard_member, then erase_account, then Priya restores both: each comes back with user_id Priya, readable under RLS by Priya and by matter associates. The draft's approved_by is null and approved_by_name is kept. The audit rows record old and new snapshot_sha256
- Trash restored before erasure: after offboarding but before erasure, a restored transcript is owned by Priya, not Mehta, and the round-4 post-condition holds
- Knowledge-source children: a knowledge source created_by Mehta in the trash restores after erase_account with created_by null and no 23503
- Race fallback: a trash row inserted with owner Mehta after offboarding (simulated by direct insert) restores owned by the custodian found in offboardings. With no offboarding record, restore raises P0001 'choose a new owner', and restore_trash_item(p_id, Priya) succeeds while a non-member p_new_owner is refused
- Snapshot-path completeness: for each trash kind, the test reads the kind's table and child tables from pg_constraint. It fails if any FK column to public.users is missing from member_snapshot_paths, or if its class disagrees with the FK delete rule (cascade/restrict owner gives owned_record, set null gives actor_set_null)
- Classification completeness from round 4 still holds, now accepting class snapshot_owner only for trash_items.owner_user_id
- Round-4 tests still pass: custodian already a member, owned records move, actor stamps untouched at offboarding, other orgs untouched, active org reset, custodian preconditions 409, post-condition rollback, numbers, multi-org refusal naming firm B, associate caller refused, audit counts
- Round-3 client-file release, fee-reason rejection, overdue escalation, template leak, client_preference constraint and retrieval wall tests all still pass

### Reviewers' minor notes

- Step d2 (rewriting trash snapshot owners) and the owner remap in restore_trash_item change who owns a matter without an UPDATE of court_cases.user_id, so P41's custody trigger never fires on them. Emit the custody event from these paths, or call a shared function. This seam must be closed on one side.
- Race and legacy rows: erase_account nulls only actor_set_null paths. A live trash row whose owned_record path still names the person (a pre-014 departure, or a race) makes the generic post-condition roll back the erasure without saying why. Make this an explicit precondition that names the trash item, or apply the offboardings remap during erasure. Also say how a legacy-departed non-member, who still owns live rows under RESTRICT, gets offboarded.
- The phrase 'no reference to their id anywhere' is overstated. audit_logs.user_id (a plain uuid, no FK), audit details and offboardings.departed_user_id keep the uuid, and approved_by_name, author_name and departed_name keep the name. Keeping them is defensible as a legal and professional record, so state it as a documented retention exception instead of claiming total erasure.
- approved_by_name is missing from snapshots of drafts trashed before migration 014. Backfill it in the migration, or accept that those approvals lose attribution.
- The claim that erasure 'leaves no reference to their id anywhere' is too strong. audit_logs.user_id (migration 004) is a plain uuid with no FK and an append-only trigger, so it falls outside the FK-driven registry and keeps the erased uid. So will P41's custody events and P36's own offboardings/erase audit rows, which also keep the name. That retention is lawful under DPDP (compliance and legal-claims purposes), but the erasure confirmation shown to the data principal must list what is kept and why. Otherwise it is a misleading statement. Reword it and add a retained_references list to the erase audit row.
- erase_account's post-condition, 'no trash snapshot in any org contains uid at a registered path', will refuse erasure for a person who left a firm before migration 014 and whose trashed records there still name them as owner, until the 30-day purge. Either sweep owned_record paths in former orgs using the restore-time custodian fallback, or tell the user the earliest erasure date.
- The snapshot::text uid backstop could false-fail if a uid appears in free text, for example a pasted log or a link. Keep it, but report the matching path so an operator can classify it rather than face a bare rollback.
- Step d2 rewrites court_case/case_thread snapshots. Coordinate with P41 so the evidence custody log records that owner change (see the P41 objection).
- Migration 014 number collides with P02 and P08.
- 'Erasing ... leaves no reference to their id anywhere' isn't true as stated. audit_logs.user_id (004) has no FK, so the FK-driven registry and its post-condition never cover it. It is append-only, so it can't be nulled, and details jsonb in other orgs can also carry the uid. Retaining it is lawful as a compliance record, but state the exception explicitly, and exclude audit_logs from the 'anywhere' claim and from any backstop text scan.
- Rewriting trash snapshots changes snapshot_sha256, which weakens its value as a record of what was trashed. Keep the original sha in a separate column, alongside the old/new pair in the audit row.
- Coordinate with P41: offboard_member's signature (p_custodian, p_plan) differs from the one P41 calls, and P41 assumes an 'erase' matter disposition, which conflicts with 'departure never destroys a firm record'. P36 should also call evidence_offboarding_summary, or a custody hook, from d2 and restore, so evidence custody events aren't skipped for trashed matters.
- Migration 014 clashes with P02 and P08.

