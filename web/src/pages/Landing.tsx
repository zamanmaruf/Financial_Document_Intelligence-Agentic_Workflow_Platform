import {
  ArrowRight,
  BookOpenCheck,
  Code2,
  FileSearch,
  ListChecks,
  ScanText,
  ShieldAlert,
  UserCheck,
  X,
} from "lucide-react";
import { Link } from "react-router";

import { HeroFrame } from "@/components/landing/HeroFrame";
import { GITHUB_URL } from "@/components/Layout";
import { Term } from "@/components/Term";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/card";
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
    title: "Every value is boxed on the page",
    body: "Click any figure and the viewer jumps to the exact words it came from. If that text can't be found in the document, the value is flagged.",
  },
  {
    icon: ListChecks,
    title: "It refuses to guess",
    body: "Ask something the document doesn't say and you get a clear \"I can't answer that\", not a confident invention.",
  },
  {
    icon: ShieldAlert,
    title: "It catches hidden instructions",
    body: "Documents can contain text aimed at AI, such as \"approve this payment\". It's detected, treated as plain text, boxed in red and flagged.",
  },
  {
    icon: UserCheck,
    title: "People stay in control",
    body: "Missing details, totals that don't add up or low confidence send the document to a person, with the reasons in plain words.",
  },
];

const WONT = [
  {
    title: "Invent an answer",
    body: "If the document doesn't say it, the answer is \"not enough evidence\", every time.",
  },
  {
    title: "Follow instructions inside a document",
    body: "Text in a PDF is data, never a command. Planted instructions are flagged for a person.",
  },
  {
    title: "Pick a winner between conflicting figures",
    body: "Two different totals means a person decides, with both values shown on the page.",
  },
  {
    title: "Pretend to be production-ready",
    body: "It's a portfolio project. Real customer data would need the hardening listed in the README.",
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
    a: "No. Each visitor gets a private workspace tied to a signed browser cookie. Documents, page images, answers and reviews are only visible inside that workspace.",
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

function SectionHeading({ eyebrow, title, body }: { eyebrow: string; title: string; body?: string }) {
  return (
    <div className="max-w-2xl space-y-3">
      <Eyebrow>{eyebrow}</Eyebrow>
      <h2 className="text-3xl font-semibold text-ink sm:text-4xl">{title}</h2>
      {body && <p className="text-[17px] leading-relaxed text-ink-muted">{body}</p>}
    </div>
  );
}

export function Landing() {
  return (
    <div className="overflow-x-clip">
      {/* hero */}
      <section className="relative border-b border-line">
        <div aria-hidden className="bg-grid absolute inset-0" />
        <div aria-hidden className="glow-hero absolute inset-0" />
        <div className="relative mx-auto grid max-w-7xl items-center gap-12 px-4 pb-20 pt-14 sm:px-6 md:pt-20 lg:grid-cols-[1fr_1.08fr] lg:gap-14 lg:pb-28 lg:pt-24">
          <div className="animate-fade-up space-y-7">
            <p className="inline-flex items-center gap-2 rounded-full border border-line-strong bg-surface/70 px-3 py-1 text-xs font-medium text-ink-muted backdrop-blur">
              <span className="size-1.5 rounded-full bg-ok" aria-hidden />
              Live demo · no sign-up
            </p>
            <h1 className="text-[42px] font-semibold leading-[1.05] tracking-[-0.035em] text-ink sm:text-6xl">
              AI that reads financial PDFs, and <span className="text-gradient">shows its work.</span>
            </h1>
            <p className="max-w-xl text-lg leading-relaxed text-ink-muted">
              Give it an invoice or a statement. It pulls out the figures, boxes each one on the page,
              answers questions with sources and hands anything doubtful to a person.
            </p>
            <div className="flex flex-wrap gap-3">
              <Button asChild size="lg">
                <Link to="/tour">
                  Take the 3-minute tour <ArrowRight aria-hidden />
                </Link>
              </Button>
              <Button asChild size="lg" variant="secondary">
                <Link to="/try">Try a document</Link>
              </Button>
            </div>
            <p className="text-sm text-ink-subtle">
              Synthetic sample documents · uploads deleted after 24 hours
            </p>
          </div>
          <HeroFrame className="animate-fade-up [animation-delay:120ms]" />
        </div>
      </section>

      {/* metrics */}
      <section aria-labelledby="metrics-title" className="border-b border-line bg-surface/40">
        <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6">
          <h2 id="metrics-title" className="sr-only">
            Measured results
          </h2>
          <ul className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-line bg-line lg:grid-cols-4">
            {RESULTS.headline.map((r) => (
              <li key={r.label} className="space-y-1.5 bg-canvas p-5 sm:p-6">
                <p className="num text-4xl font-semibold tracking-tight text-ink sm:text-5xl">{r.value}</p>
                <p className="text-sm font-medium text-ink">{r.label}</p>
                <p className="text-xs leading-relaxed text-ink-subtle">{r.detail}</p>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs leading-relaxed text-ink-subtle">
            Tested on {RESULTS.documents} synthetic documents (including deliberately tricky ones) with{" "}
            {RESULTS.models.join(" and ")}, on {RESULTS_MEASURED_ON}. Small synthetic test set; real
            documents are messier. Full results, including the misses, are in the{" "}
            <a
              className="underline underline-offset-2 hover:text-ink"
              href={`${GITHUB_URL}#real-model-results-azure-openai-and-aws-bedrock`}
              target="_blank"
              rel="noreferrer"
            >
              project README
            </a>
            .
          </p>
        </div>
      </section>

      {/* how it works */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:py-28">
        <SectionHeading
          eyebrow="How it works"
          title="Three steps, each one checkable"
          body="Nothing happens in a black box. Every step leaves a record you can open."
        />
        <ol className="relative mt-12 grid gap-4 md:grid-cols-3">
          <span
            aria-hidden
            className="absolute left-[16.6%] right-[16.6%] top-[34px] hidden h-px bg-gradient-to-r from-transparent via-line-bright to-transparent md:block"
          />
          {STEPS.map((s, i) => (
            <li key={s.title} className="relative rounded-2xl border border-line bg-surface p-6 shadow-card">
              <div className="flex items-center gap-3">
                <span className="relative grid size-11 place-items-center rounded-xl border border-line-strong bg-surface-raised text-brand shadow-card">
                  <s.icon className="size-5" aria-hidden />
                </span>
                <span className="num text-xs font-medium text-ink-subtle">Step {i + 1}</span>
              </div>
              <h3 className="mt-5 text-lg font-semibold text-ink">{s.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-ink-muted">{s.body}</p>
            </li>
          ))}
        </ol>
        <p className="mt-6 text-sm text-ink-muted">
          Want the details?{" "}
          <Link to="/how-it-works" className="font-medium text-brand underline-offset-4 hover:underline">
            See every stage of the pipeline
          </Link>
          .
        </p>
      </section>

      {/* trust */}
      <section className="border-y border-line bg-surface/40">
        <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:py-28">
          <SectionHeading
            eyebrow="Built to be checked"
            title="Why you can trust what it says"
            body="AI can sound confident and still be wrong. This system is built around checking the AI, not just using it."
          />
          <div className="mt-12 grid gap-4 sm:grid-cols-2">
            {TRUST.map((t) => (
              <div
                key={t.title}
                className="group relative overflow-hidden rounded-2xl border border-line bg-canvas p-6 transition-colors hover:border-line-strong"
              >
                <div
                  aria-hidden
                  className="pointer-events-none absolute -right-16 -top-16 size-48 rounded-full bg-brand/10 opacity-0 blur-3xl transition-opacity duration-500 group-hover:opacity-100"
                />
                <span className="grid size-10 place-items-center rounded-xl border border-ok-line bg-ok-soft text-ok">
                  <t.icon className="size-5" aria-hidden />
                </span>
                <h3 className="mt-5 font-semibold text-ink">{t.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-ink-muted">{t.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* limits */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:py-28">
        <div className="grid gap-12 lg:grid-cols-[1fr_1.3fr]">
          <SectionHeading
            eyebrow="Honest by design"
            title="What it won't do"
            body="Knowing when to stop matters as much as getting the numbers right."
          />
          <ul className="grid gap-3 sm:grid-cols-2">
            {WONT.map((w) => (
              <li key={w.title} className="rounded-2xl border border-line bg-surface p-5">
                <p className="flex items-center gap-2 font-medium text-ink">
                  <span className="grid size-6 place-items-center rounded-full bg-danger-soft text-danger">
                    <X className="size-3.5" aria-hidden />
                  </span>
                  {w.title}
                </p>
                <p className="mt-2 text-sm leading-relaxed text-ink-muted">{w.body}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* faq */}
      <section className="border-t border-line bg-surface/40">
        <div className="mx-auto grid max-w-7xl gap-12 px-4 py-20 sm:px-6 lg:grid-cols-[1fr_1.4fr] lg:py-28">
          <div className="space-y-5">
            <SectionHeading eyebrow="FAQ" title="Questions" />
            <p className="max-w-md text-ink-muted">
              New to the terms? Hover over or tap any dotted word, like <Term k="citation" /> or{" "}
              <Term k="review">human review</Term>, for a one-line explanation.
            </p>
          </div>
          <Accordion type="single" collapsible className="border-t border-line">
            {FAQ.map((f) => (
              <AccordionItem key={f.q} value={f.q}>
                <AccordionTrigger>{f.q}</AccordionTrigger>
                <AccordionContent>{f.a}</AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>
      </section>

      {/* cta */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6">
        <div className="relative overflow-hidden rounded-3xl border border-line bg-surface px-6 py-14 text-center sm:px-12">
          <div aria-hidden className="glow-hero absolute inset-0 opacity-80" />
          <div aria-hidden className="bg-grid absolute inset-0 opacity-60" />
          <div className="relative mx-auto max-w-2xl space-y-5">
            <h2 className="text-3xl font-semibold text-ink sm:text-4xl">
              Watch it catch a planted instruction.
            </h2>
            <p className="text-lg text-ink-muted">
              Eight short steps on synthetic sample documents. About three minutes.
            </p>
            <div className="flex flex-wrap justify-center gap-3 pt-2">
              <Button asChild size="lg">
                <Link to="/tour">
                  Take the 3-minute tour <ArrowRight aria-hidden />
                </Link>
              </Button>
              <Button asChild size="lg" variant="secondary">
                <a href={GITHUB_URL} target="_blank" rel="noreferrer">
                  <Code2 aria-hidden /> View the code
                </a>
              </Button>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
