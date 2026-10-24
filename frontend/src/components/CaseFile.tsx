import type { Analysis, Citation, LegalIssue, WebSource } from "@/lib/types";

const SEVERITY_STYLES: Record<LegalIssue["severity"], string> = {
  high: "border-red-500 bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300",
  medium: "border-amber-500 bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  low: "border-emerald-500 bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300",
};
const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 };

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <h2 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
        {title}
        {count ? (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">{count}</span>
        ) : null}
      </h2>
      {children}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-slate-400 dark:text-slate-500">{children}</p>;
}

function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function CaseFile({
  analysis,
  citations,
  webSources,
  webQueries,
}: {
  analysis: Analysis;
  citations: Citation[];
  webSources: WebSource[];
  webQueries: string[];
}) {
  const risks = [...analysis.legal_issues].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
  const sortedCitations = [...citations].sort((a, b) => b.similarity - a.similarity);

  return (
    <div className="flex flex-col gap-4">
      <Section title="Legal risks" count={risks.length}>
        {risks.length === 0 ? (
          <Empty>Risks the agents identify appear here, most severe first.</Empty>
        ) : (
          <ul className="flex flex-col gap-2">
            {risks.map((risk) => (
              <li key={risk.issue} className={`rounded-lg border-l-4 px-3 py-2 ${SEVERITY_STYLES[risk.severity]}`}>
                <div className="text-[11px] font-bold uppercase tracking-wide">
                  {risk.severity}
                  {risk.area_of_law ? ` · ${risk.area_of_law}` : ""}
                </div>
                <div className="font-medium text-slate-900 dark:text-slate-100">{risk.issue}</div>
                {risk.rationale ? <p className="text-sm text-slate-600 dark:text-slate-300">{risk.rationale}</p> : null}
                {risk.authority ? (
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    § {risk.authority}
                    {risk.authority_status === "verified" ? (
                      <span className="ml-1.5 text-emerald-600 dark:text-emerald-400" title="Found in the sources the AI was given">✓ in sources</span>
                    ) : risk.authority_status === "known" ? (
                      <span className="ml-1.5" title={risk.authority_note ?? undefined}>· real judgment, not in this matter&apos;s sources</span>
                    ) : risk.authority_status === "statute" ? (
                      <span className="ml-1.5" title={risk.authority_note ?? "The section exists in this act; check its text"}>· section exists</span>
                    ) : null}
                  </p>
                ) : null}
                {risk.authority_status === "flagged" ? (
                  <p className="mt-1 text-xs text-amber-700 dark:text-amber-400" title={risk.authority_note ?? undefined}>
                    ⚠ An unsupported citation was removed
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Firm knowledge base" count={sortedCitations.length}>
        {sortedCitations.length === 0 ? (
          <Empty>Statutes and precedents from your firm&apos;s knowledge base that match the conversation.</Empty>
        ) : (
          <ul className="flex flex-col gap-3">
            {sortedCitations.map((c) => (
              <li key={c.id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-medium text-slate-900 dark:text-slate-100">{c.title}</span>
                  <span className="shrink-0 text-xs text-slate-500">{Math.round(c.similarity * 100)}% match</span>
                </div>
                {c.citation || c.jurisdiction ? (
                  <div className="text-xs text-slate-500">{[c.citation, c.jurisdiction].filter(Boolean).join(" · ")}</div>
                ) : null}
                <p className="mt-1 line-clamp-3 text-sm text-slate-600 dark:text-slate-300">{c.excerpt}</p>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Web sources" count={webSources.length}>
        {webSources.length === 0 ? (
          <Empty>When the knowledge base has nothing confident, the researcher searches the public web. Sources appear here.</Empty>
        ) : (
          <>
            <p className="mb-3 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
              Public web results: verify before relying on them.
            </p>
            <ul className="flex flex-col gap-3">
              {webSources.map((s) => (
                <li key={s.url}>
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-indigo-700 hover:underline dark:text-indigo-300"
                  >
                    {s.title}
                  </a>
                  <div className="text-xs text-slate-500">
                    {hostname(s.url)}
                    {s.published_date ? ` · ${s.published_date.slice(0, 10)}` : ""}
                  </div>
                  <p className="mt-1 line-clamp-3 text-sm text-slate-600 dark:text-slate-300">{s.snippet}</p>
                </li>
              ))}
            </ul>
            {webQueries.length ? (
              <p className="mt-3 text-xs text-slate-400">Searched for: {webQueries.map((q) => `“${q}”`).join(", ")}</p>
            ) : null}
          </>
        )}
      </Section>

      <Section title="Key facts" count={analysis.key_facts.length}>
        {analysis.key_facts.length === 0 ? (
          <Empty>Facts established in the conversation.</Empty>
        ) : (
          <ul className="flex flex-col gap-1.5 text-sm">
            {analysis.key_facts.map((f) => (
              <li key={f.fact} className="flex items-start gap-2">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-400" />
                <span className="text-slate-800 dark:text-slate-200">
                  {f.fact}
                  {f.category ? <span className="ml-2 rounded border border-slate-200 px-1 text-[11px] text-slate-500 dark:border-slate-700">{f.category}</span> : null}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Open questions" count={analysis.follow_up_questions.length}>
        {analysis.follow_up_questions.length === 0 ? (
          <Empty>Questions that would help clarify the matter.</Empty>
        ) : (
          <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-800 dark:text-slate-200">
            {analysis.follow_up_questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ol>
        )}
      </Section>
    </div>
  );
}
