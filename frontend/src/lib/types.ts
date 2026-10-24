// Shapes shared with the backend (see app/routers/audio_stream.py for the event protocol).

export type Organization = { id: string; name: string; role: string; is_active: boolean };
export type PracticeArea = { id: string; name: string };
export type CaseThread = {
  id: string;
  title: string;
  status: string;
  legal_hold?: boolean;
  ai_consent_at?: string | null;
  ai_consent_method?: string | null;
};

export type Severity = "low" | "medium" | "high";

export type KeyFact = { fact: string; category?: string | null };
export type LegalIssue = {
  issue: string;
  area_of_law?: string | null;
  severity: Severity;
  rationale?: string | null;
  authority?: string | null;
  // Set by the backend's citation check: in the sources, a real statute section, or unsupported (removed).
  authority_status?: "verified" | "known" | "statute" | "flagged" | null;
  authority_note?: string | null;
};
export type CitationCheck = {
  text: string;
  kind: "statute" | "case";
  status: "grounded" | "known_case" | "statute" | "repealed" | "invalid" | "unverified";
  note?: string | null;
  // What the check did and didn't establish, e.g. "Section exists · its wording isn't checked".
  label?: string;
};
export type Citation = {
  id: string;
  title: string;
  citation?: string | null;
  jurisdiction?: string | null;
  url?: string | null;
  similarity: number;
  excerpt: string;
};
export type WebSource = {
  title: string;
  url: string;
  snippet: string;
  published_date?: string | null;
  score: number;
};
export type Analysis = {
  key_facts: KeyFact[];
  legal_issues: LegalIssue[];
  follow_up_questions: string[];
};

export type AgentStage = "intake_analyzer" | "legal_researcher" | "external_researcher" | "risk_evaluator" | "drafter" | "idle";

export type ServerEvent =
  | { type: "session_started"; session_id: string; mode: string; voice: boolean }
  | { type: "chunk_received"; index: number; text: string; speaker: string | null; source: string; redactions: string[] }
  | { type: "transcript_interim"; text: string }
  | { type: "agent_status"; stage: AgentStage; message: string }
  | { type: "agent_response"; message: string; disclaimer_appended: boolean; spoken: boolean; citations?: CitationCheck[] }
  | { type: "agent_speaking"; state: "start" | "stop" }
  | { type: "analysis"; data: Analysis }
  | { type: "citations"; items: Citation[] }
  | { type: "web_sources"; items: WebSource[]; queries: string[] }
  | { type: "case_memory_loaded"; title: string; previous_sessions: number }
  | { type: "practice_area_selected"; name: string }
  | { type: "session_ended"; transcript_id: string | null; summary: string | null }
  | { type: "consent_required"; message: string; methods: string[] }
  | { type: "consent_status"; consent: Consent }
  | { type: "consent_recorded"; consent: Consent }
  | { type: "error"; code: string; message: string };

export type Consent = { method: string; at: string; by?: string | null; source: "case_thread" | "this_session" };

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  redactions?: string[];
  disclaimer?: boolean;
  citations?: CitationCheck[];
};

// ----------------------------------------------------------------------------- Document Studio

export type StoredDocument = { id: string; filename: string; page_count: number | null; char_count: number; created_at: string };

export type DiffOp = { op: "equal" | "insert" | "delete"; text: string };
export type RiskImpact = "increased" | "decreased" | "neutral";

export type ClauseAnalysis = {
  clause_id: string;
  change_summary: string;
  risk_impact: RiskImpact;
  categories: string[];
  severity: Severity;
  explanation: string;
  recommended_counter_clause: string | null;
};

export type ClauseChange = {
  id: string;
  status: "unchanged" | "renumbered" | "modified" | "added" | "deleted";
  label: string | null;
  original_text: string | null;
  revised_text: string | null;
  inline_diff: DiffOp[];
  analysis: ClauseAnalysis | null;
  // Set when the contract's own law differs from the one analysed and this conclusion depends on it.
  jurisdiction_caveat?: string;
};

export type GoverningLaw = {
  detected: { code: string | null; law: string; quote: string; basis: "clause" | "courts" } | null;
  selected: string | null;
  mismatch: boolean;
  caveat: string | null;
};

export type CompareReport = {
  original: { id: string; filename: string };
  revised: { id: string; filename: string };
  clauses: ClauseChange[];
  risk_delta: "Increased" | "Decreased" | "Neutral" | "Not analyzed";
  risk_score: number;
  summary: string;
  key_concerns: string[];
  stats: Record<string, number>;
  governing_law?: { original: GoverningLaw; revised: GoverningLaw };
  jurisdiction_caveat?: string | null;
};

export type DraftSection = { heading: string | null; paragraphs: string[] };
export type DraftContent = { sections: DraftSection[]; signature_block: string[] };
export type Draft = {
  id: string;
  doc_type: string;
  jurisdiction: string | null;
  title: string;
  content: DraftContent;
  missing: string[];
  status: "draft" | "final";
  thread_id: string | null;
  updated_at: string;
  approved_by?: string | null;
  approved_at?: string | null;
};

export type DraftMismatch = { kind: "amount" | "date" | "reference" | "provided_value"; value: string; message: string };
export type DraftChecklist = {
  approved: boolean;
  approved_by: string | null;
  approved_at: string | null;
  missing: string[];
  citations: CitationCheck[];
  unresolved_citations: CitationCheck[];
  mismatches: DraftMismatch[];
  fact_basis_recorded: boolean;
  clear: boolean;
};

// ----------------------------------------------------------------------------- approvals and trash

export type ApprovalRequest = {
  id: string;
  action: "delete" | "enable_intake" | "make_owner" | "purge";
  target_kind: string;
  target_id: string;
  target_label: string | null;
  reason: string | null;
  requested_by: string | null;
  requested_at: string;
  expires_at: string;
  status: "pending" | "approved" | "rejected" | "cancelled" | "executed" | "failed";
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  error: string | null;
};

export type TrashItem = {
  id: string;
  kind: string;
  item_id: string;
  title: string | null;
  owner_user_id: string | null;
  reason: string | null;
  deleted_by: string | null;
  deleted_at: string;
  requested_by: string | null;
  purge_after: string;
  restored_at: string | null;
  restored_by?: string | null;
  purged_at: string | null;
  purged_by: string | null;
};

export type IntakeState = {
  enabled: boolean;
  changed_by: string | null;
  changed_at: string | null;
  pending_request: ApprovalRequest | null;
};
export type DraftSummary = Pick<Draft, "id" | "doc_type" | "title" | "status" | "updated_at" | "jurisdiction">;
export type DraftTemplate = { doc_type: string; label: string; family: string; name: string; variables: Record<string, string> };
export type ClauseRevisionResult = { revised_text: string; explanation: string; inline_diff: DiffOp[] };
