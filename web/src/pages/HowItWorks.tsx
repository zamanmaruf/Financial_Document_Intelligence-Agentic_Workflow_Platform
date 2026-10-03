import {
  ArrowDown,
  ClipboardCheck,
  FileSearch,
  FileText,
  MessageSquareText,
  ScrollText,
  ShieldCheck,
  Tags,
  UserCheck,
} from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { GITHUB_URL } from "@/components/Layout";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { GLOSSARY } from "@/content/glossary";

interface Stage {
  icon: ReactNode;
  title: string;
  body: string;
  ai: boolean;
}

const STAGES: Stage[] = [
  {
    icon: <FileText aria-hidden />,
    title: "Read the PDF",
    body: "The text and tables are pulled out of each page. Scanned pages can be read with optical character recognition. Nothing here uses AI.",
    ai: false,
  },
  {
    icon: <ShieldCheck aria-hidden />,
    title: "Scan for hidden instructions",
    body: "The text is checked for sentences that try to give orders to an AI. Anything suspicious is flagged and the document will go to a person.",
    ai: false,
  },
  {
    icon: <Tags aria-hidden />,
    title: "Identify the document",
    body: "The AI decides which of five supported types it is: invoice, bank statement, income statement, balance sheet or fund factsheet. Anything else is rejected rather than guessed at.",
    ai: true,
  },
  {
    icon: <FileSearch aria-hidden />,
    title: "Pull out the figures",
    body: "The AI fills in a fixed list of fields for that type, and must quote the exact text each value came from. Code then confirms each quote is really in the document.",
    ai: true,
  },
  {
    icon: <ClipboardCheck aria-hidden />,
    title: "Check the numbers",
    body: "Plain code, not AI, checks the results: are required fields present, do subtotals add up, do the same figures agree across pages, are dates and currencies valid.",
    ai: false,
  },
  {
    icon: <UserCheck aria-hidden />,
    title: "Decide: ready or ask a person",
    body: "If everything checks out, the document is ready. If anything is missing, inconsistent, uncertain or suspicious, it goes to a review queue with the reasons in plain words.",
    ai: false,
  },
  {
    icon: <MessageSquareText aria-hidden />,
    title: "Answer questions",
    body: "The document is split into passages so questions can be answered from it. Answers must cite passages, and a separate check blocks any number that isn't in the cited text.",
    ai: true,
  },
  {
    icon: <ScrollText aria-hidden />,
    title: "Record everything",
    body: "Every processing step, review decision and answer is written to an append-only, fingerprinted audit trail. Each AI call is logged separately with its prompt version, timing and estimated cost.",
    ai: false,
  },
];

export function HowItWorks() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <header className="mb-10 max-w-2xl space-y-3">
        <h1 className="text-3xl font-semibold text-ink">How it works</h1>
        <p className="leading-relaxed text-ink-muted">
          The AI does the reading. Plain code does the checking. A person makes the call whenever the
          system isn't sure. Here's what happens to a document, step by step.
        </p>
      </header>

      <section aria-labelledby="flow-heading" className="mb-14">
        <h2 id="flow-heading" className="sr-only">
          Processing steps
        </h2>
        <ol className="space-y-2">
          {STAGES.map((s, i) => (
            <li key={s.title}>
              <Card className="flex gap-4 p-4 sm:p-5">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand [&_svg]:size-5">
                  {s.icon}
                </span>
                <div className="space-y-1">
                  <h3 className="flex flex-wrap items-center gap-2 font-medium text-ink">
                    <span className="text-ink-subtle">{i + 1}.</span> {s.title}
                    <span
                      className={
                        s.ai
                          ? "rounded-full bg-info-soft px-2 py-0.5 text-xs font-medium text-info"
                          : "rounded-full bg-surface-muted px-2 py-0.5 text-xs font-medium text-ink-muted"
                      }
                    >
                      {s.ai ? "Uses AI" : "No AI"}
                    </span>
                  </h3>
                  <p className="text-sm leading-relaxed text-ink-muted">{s.body}</p>
                </div>
              </Card>
              {i < STAGES.length - 1 && (
                <ArrowDown className="mx-auto my-1 size-4 text-ink-subtle" aria-hidden />
              )}
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="ai-heading" className="mb-14 space-y-3">
        <h2 id="ai-heading" className="text-xl font-semibold text-ink">
          Which AI does this demo use?
        </h2>
        <p className="leading-relaxed text-ink-muted">
          When live, the AI steps run on Claude, hosted on AWS Bedrock. The demo has a small daily
          budget. Once it's used up, a simple rule-based engine takes over so the site keeps working.
          The badge at the top of every page tells you which one is answering. The same system can
          also run on Azure OpenAI; that's a configuration setting, not a code change.
        </p>
      </section>

      <section aria-labelledby="glossary-heading" className="mb-14 space-y-4">
        <h2 id="glossary-heading" className="text-xl font-semibold text-ink">
          Glossary
        </h2>
        <dl className="grid gap-3 sm:grid-cols-2">
          {Object.entries(GLOSSARY).map(([key, entry]) => (
            <Card key={key} className="p-4">
              <dt className="font-medium text-ink">{entry.term}</dt>
              <dd className="mt-1 text-sm leading-relaxed text-ink-muted">{entry.long}</dd>
            </Card>
          ))}
        </dl>
      </section>

      <section aria-labelledby="limits-heading" className="mb-14 space-y-3">
        <h2 id="limits-heading" className="text-xl font-semibold text-ink">
          What it doesn't do
        </h2>
        <ul className="list-disc space-y-1.5 pl-5 leading-relaxed text-ink-muted">
          <li>It isn't certified for any regulation, and this demo isn't meant for real financial data.</li>
          <li>Confidence is a practical signal for when to ask a person, not a statistical guarantee.</li>
          <li>Scanning for hidden instructions reduces risk; it can't catch every possible attack.</li>
          <li>The tamper check makes edits detectable, not impossible.</li>
          <li>It only understands five document types and rejects everything else.</li>
        </ul>
      </section>

      <div className="flex flex-wrap gap-3">
        <Button asChild size="lg">
          <Link to="/tour">Take the guided tour</Link>
        </Button>
        <Button asChild size="lg" variant="secondary">
          <a href={GITHUB_URL} target="_blank" rel="noreferrer">
            Read the code
          </a>
        </Button>
      </div>
    </div>
  );
}
