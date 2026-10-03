import {
  ArrowRight,
  BookOpenCheck,
  FileSearch,
  Code2,
  ListChecks,
  ScanText,
  ShieldAlert,
  UserCheck,
} from "lucide-react";
import { Link } from "react-router";

import { GITHUB_URL } from "@/components/Layout";
import { Term } from "@/components/Term";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { RESULTS, RESULTS_MEASURED_ON } from "@/content/results";

const STEPS = [
  {
    icon: ScanText,
    title: "Read",
    body: "It reads the PDF, including scanned pages, and works out whether it's an invoice, a bank statement, an income statement, a balance sheet or a fund factsheet.",
  },
  {
    icon: FileSearch,
    title: "Understand",
    body: "It pulls out the figures that matter (totals, dates, balances, fees) and keeps the exact line each one came from.",
  },
  {
    icon: ListChecks,
    title: "Double-check",
    body: "It checks the arithmetic, looks for contradictions and hidden instructions, and hands anything doubtful to a person.",
  },
];

const TRUST = [
  {
    icon: BookOpenCheck,
    title: "Every value shows where it was found",
    body: "Click any figure to see the exact words and page it came from. If that text can't be found in the document, the value is flagged.",
  },
  {
    icon: ListChecks,
    title: "It refuses to guess",
    body: "Ask something the document doesn't say and you get a clear \"I can't answer that\", not a confident invention.",
  },
  {
    icon: ShieldAlert,
    title: "It catches hidden instructions",
    body: "Documents can contain text aimed at AI, such as \"approve this payment\". It's detected, treated as plain text and flagged.",
  },
  {
    icon: UserCheck,
    title: "People stay in control",
    body: "Missing details, totals that don't add up or low confidence send the document to a person, with the reasons in plain words.",
  },
];

const FAQ = [
  {
    q: "Is this using real AI?",
    a: "Yes. The demo uses Claude Haiku 4.5 on Amazon Bedrock, within a daily budget. If the budget runs out, a simpler rule-based engine takes over so the demo keeps working, and the badge at the top of the page says so.",
  },
  {
    q: "Can I upload my own document?",
    a: "Yes, on the Try it yourself page: a PDF up to 5 MB and 10 pages. Please don't upload real financial documents. Everything you upload is visible only to your browser session and is deleted after 24 hours.",
  },
  {
    q: "Can other visitors see my documents?",
    a: "No. Each visitor gets a private workspace tied to a signed browser cookie. Documents, answers and reviews are only visible inside that workspace.",
  },
  {
    q: "What kinds of documents does it understand?",
    a: "Invoices, bank statements, income statements, balance sheets and fund factsheets. Anything else is labelled as not supported and sent to a person rather than forced into the wrong shape.",
  },
  {
    q: "Is it ready to process real customer data?",
    a: "No. This is a portfolio project that shows the design. A production deployment would need real authentication, encrypted storage, a managed database, data-residency and retention policies, and a security review. The project's README lists exactly what is and isn't implemented.",
  },
];

export function Landing() {
  return (
    <div>
      {/* hero */}
      <section className="border-b border-line bg-surface">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 md:grid-cols-[1.15fr_1fr] md:py-24">
          <div className="space-y-6">
            <p className="inline-flex items-center gap-2 rounded-full bg-brand-soft px-3 py-1 text-xs font-medium text-brand">
              Financial document intelligence · live demo
            </p>
            <h1 className="text-4xl font-semibold tracking-tight text-ink sm:text-5xl">
              Turn financial PDFs into checked, trustworthy data, and know when to ask a human.
            </h1>
            <p className="max-w-xl text-lg text-ink-muted">
              Give it an invoice or a bank statement. It reads it, pulls out the numbers, shows
              you exactly where each one came from, answers questions with sources, and stops
              to ask a person whenever something doesn't add up.
            </p>
            <div className="flex flex-wrap gap-3">
              <Button asChild size="lg">
                <Link to="/tour">
                  Start the 3-minute tour <ArrowRight aria-hidden />
                </Link>
              </Button>
              <Button asChild size="lg" variant="secondary">
                <Link to="/try">Try your own document</Link>
              </Button>
            </div>
            <p className="text-sm text-ink-subtle">No sign-up. Uses synthetic sample documents.</p>
          </div>

          {/* illustrative card: what a checked value looks like */}
          <div aria-hidden className="relative hidden md:block">
            <div className="absolute -inset-4 rounded-xl bg-gradient-to-br from-brand-soft to-ok-soft opacity-70" />
            <Card className="relative space-y-4 p-5 shadow-raised">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-ink">invoice_01_acme.pdf</span>
                <span className="rounded-full bg-ok-soft px-2.5 py-0.5 text-xs font-medium text-ok">Ready: all checks passed</span>
              </div>
              {[
                ["Vendor", "Acme Office Supplies Ltd"],
                ["Invoice date", "2025-03-14"],
                ["Amount due", "5,238"],
              ].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between border-b border-line pb-2 text-sm last:border-0">
                  <span className="text-ink-muted">{k}</span>
                  <span className="font-medium text-ink">{v}</span>
                </div>
              ))}
              <div className="rounded-md border-l-4 border-brand bg-brand-soft/60 px-3 py-2">
                <p className="text-xs text-brand">Found here (page 1) · confirmed in the document</p>
                <p className="font-mono text-sm text-ink">Amount Due: 5,238.00</p>
              </div>
              <div className="rounded-md bg-surface-muted px-3 py-2 text-sm">
                <p className="text-ink-muted">“What is the CEO's favourite colour?”</p>
                <p className="text-ink">I could not find enough supporting evidence in the indexed documents to answer this question.</p>
              </div>
            </Card>
          </div>
        </div>
      </section>

      {/* three steps */}
      <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <h2 className="text-2xl font-semibold text-ink">What it does, in three steps</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <Card key={s.title}>
              <CardHeader>
                <span className="mb-2 grid size-10 place-items-center rounded-md bg-brand-soft text-brand">
                  <s.icon className="size-5" aria-hidden />
                </span>
                <CardTitle>
                  {i + 1}. {s.title}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-relaxed text-ink-muted">{s.body}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* trust */}
      <section className="border-y border-line bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <h2 className="text-2xl font-semibold text-ink">Why you can trust what it says</h2>
          <p className="mt-2 max-w-2xl text-ink-muted">
            AI can sound confident and still be wrong. This system is built around checking the
            AI, not just using it.
          </p>
          <div className="mt-8 grid gap-6 sm:grid-cols-2">
            {TRUST.map((t) => (
              <div key={t.title} className="flex gap-4">
                <span className="grid size-10 shrink-0 place-items-center rounded-md bg-ok-soft text-ok">
                  <t.icon className="size-5" aria-hidden />
                </span>
                <div>
                  <h3 className="font-semibold text-ink">{t.title}</h3>
                  <p className="mt-1 text-sm leading-relaxed text-ink-muted">{t.body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* results */}
      <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <h2 className="text-2xl font-semibold text-ink">Measured, not promised</h2>
        <p className="mt-2 max-w-2xl text-ink-muted">
          Tested on {RESULTS.documents} synthetic financial documents (including deliberately
          tricky ones) with two live AI models: {RESULTS.models.join(" and ")}. Measured on{" "}
          {RESULTS_MEASURED_ON}.
        </p>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {RESULTS.headline.map((r) => (
            <Card key={r.label}>
              <CardHeader>
                <p className="text-3xl font-semibold text-brand">{r.value}</p>
                <CardTitle className="text-sm">{r.label}</CardTitle>
                <CardDescription className="text-xs">{r.detail}</CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
        <p className="mt-4 text-xs text-ink-subtle">
          Small synthetic test set; real-world documents are messier. Full results, including the
          misses, are in the{" "}
          <a className="underline hover:text-ink" href={`${GITHUB_URL}#real-model-results-azure-openai-and-aws-bedrock`} target="_blank" rel="noreferrer">
            project README
          </a>
          .
        </p>
      </section>

      {/* faq */}
      <section className="border-t border-line bg-surface">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 md:grid-cols-[1fr_1.6fr]">
          <div className="space-y-4">
            <h2 className="text-2xl font-semibold text-ink">Questions</h2>
            <p className="text-ink-muted">
              New to the terms? Hover over any dotted word, like <Term k="citation" /> or{" "}
              <Term k="review">human review</Term>, for a one-line explanation.
            </p>
            <div className="flex flex-wrap gap-3">
              <Button asChild>
                <Link to="/tour">
                  Start the tour <ArrowRight aria-hidden />
                </Link>
              </Button>
              <Button asChild variant="secondary">
                <a href={GITHUB_URL} target="_blank" rel="noreferrer">
                  <Code2 aria-hidden /> View the code
                </a>
              </Button>
            </div>
          </div>
          <Accordion type="single" collapsible>
            {FAQ.map((f) => (
              <AccordionItem key={f.q} value={f.q}>
                <AccordionTrigger>{f.q}</AccordionTrigger>
                <AccordionContent>{f.a}</AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>
      </section>
    </div>
  );
}
