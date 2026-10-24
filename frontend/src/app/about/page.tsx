import Link from "next/link";

export const metadata = { title: "About · Digi Lawyer" };

const h2 = "mt-8 text-lg font-semibold text-slate-900 dark:text-slate-100";
const p = "mt-2 text-sm leading-relaxed text-slate-700 dark:text-slate-300";

export default function About() {
  return (
    <main className="flex-1 overflow-y-auto bg-slate-50 px-4 py-10 dark:bg-slate-950">
      <article className="mx-auto max-w-2xl">
        <Link href="/" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Back
        </Link>
        <h1 className="mt-4 text-2xl font-semibold text-slate-900 dark:text-slate-100">About Digi Lawyer</h1>
        <p className={p}>
          An AI legal associate for law firms: live consultation notes, bulk document review, matter workflows with statutory deadlines,
          contract redlining, contradiction checks and first drafts, for lawyers to review.
        </p>

        <h2 className={h2}>Not legal advice</h2>
        <p className={p}>
          Digi Lawyer provides legal information and draft analysis to lawyers. It is not a substitute for a lawyer&apos;s judgment, and
          its output must be reviewed before it is relied on or sent to anyone.
        </p>

        <h2 className={h2}>How client data is handled</h2>
        <ul className={`${p} list-disc pl-5`}>
          <li>Identifiers such as Aadhaar, PAN, bank account, card and phone numbers are masked before any text is sent to an AI model.</li>
          <li>Each firm&apos;s data is isolated in the database: members only see their own organization&apos;s matters, by role.</li>
          <li>Viewing, exporting and deleting records is written to an audit log that owners and partners can read.</li>
          <li>Every statute and case the AI cites is checked against the sources it was given; anything unsupported is marked.</li>
        </ul>

        <h2 className={h2}>Data sources and attribution</h2>
        <p className={p}>
          Supreme Court of India judgments: <em>Indian Supreme Court Judgments</em>, compiled by Dattam Labs from the Supreme Court of
          India website, accessed from{" "}
          <a className="text-indigo-700 underline dark:text-indigo-300" href="https://registry.opendata.aws/indian-supreme-court-judgments/">
            registry.opendata.aws/indian-supreme-court-judgments
          </a>
          , licensed under{" "}
          <a className="text-indigo-700 underline dark:text-indigo-300" href="https://creativecommons.org/licenses/by/4.0/">
            CC BY 4.0
          </a>
          . Judgments are reproduced for reference; check the official text before citing.
        </p>
        <p className={p}>
          Case law search and citation checks for High Court and tribunal judgments are{" "}
          <a className="text-indigo-700 underline dark:text-indigo-300" href="https://indiankanoon.org">
            powered by IKanoon
          </a>
          .
        </p>
        <p className={p}>Court case status and hearing dates are provided by the eCourtsIndia API from eCourts data.</p>
      </article>
    </main>
  );
}
