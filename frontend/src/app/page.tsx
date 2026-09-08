import Link from "next/link";
import {
  Users,
  Clock,
  CalendarCheck,
  Wallet,
  Laptop,
  Sparkles,
  Check,
  ArrowRight,
} from "lucide-react";

// ── Landing page token system ─────────────────────────────────────────────────
// Scoped to this page only (dashboard keeps its own neutral theme in
// styles/globals.css). Brand: indigo, matching the approved reference design.
//   --brand        : primary indigo — CTAs, links, active states
//   --brand-dark    : hover / pressed indigo
//   --brand-soft    : pale indigo tint — icon chips, highlighted card border
//   --ink           : near-black for headings/body
//   --muted         : slate gray for secondary text
//   --surface       : off-white section background (alternates with white)
const brand = {
  "--brand": "#4F46E5",
  "--brand-dark": "#4338CA",
  "--brand-soft": "#EEF2FF",
  "--brand-ring": "#C7D2FE",
  "--ink": "#0F172A",
  "--muted": "#64748B",
  "--surface": "#F8FAFC",
} as React.CSSProperties;

const features = [
  {
    icon: Users,
    title: "Employee Management",
    body: "Org charts, employee records, document management, and a full HR profile for every hire — from day one to offboarding.",
  },
  {
    icon: Clock,
    title: "Time & Attendance",
    body: "QR check-in and geo-fenced attendance, with automatic late and overtime calculation against each employee's shift.",
  },
  {
    icon: CalendarCheck,
    title: "Leave Management",
    body: "Configurable leave types, accrual balances, and an approval workflow your managers actually want to use.",
  },
  {
    icon: Wallet,
    title: "Payroll & Compliance",
    body: "Build salary structures once, then generate payslips automatically — prorated by attendance, exportable as PDF.",
  },
  {
    icon: Laptop,
    title: "Device & Asset Management",
    body: "Enroll company laptops and IT assets, track who has what, and lock or restart a device remotely when someone leaves.",
  },
  {
    icon: Sparkles,
    title: "AI-Powered Insights",
    body: "Ask your HR data questions in plain language — headcount trends, attrition risk, payroll anomalies — answered instantly.",
  },
];

const plans = [
  {
    name: "Starter",
    price: "$5",
    unit: "per user/month",
    cta: "Get Started",
    highlighted: false,
    features: [
      "Employee directory",
      "Time & attendance",
      "Leave management",
      "Basic reporting",
      "Email support",
    ],
  },
  {
    name: "Professional",
    price: "$12",
    unit: "per user/month",
    cta: "Get Started",
    highlighted: true,
    features: [
      "Everything in Starter",
      "Payroll & payslip generation",
      "Recruitment pipeline",
      "Device & asset management",
      "AI-powered insights",
      "Priority support",
    ],
  },
  {
    name: "Enterprise",
    price: "Custom",
    unit: "contact sales",
    cta: "Contact Sales",
    highlighted: false,
    features: [
      "Everything in Professional",
      "Custom workflows & automation",
      "API access & webhooks",
      "SSO & advanced security",
      "Dedicated success manager",
    ],
  },
];

export default function LandingPage() {
  return (
    <div style={brand} className="bg-white font-sans">
      {/* ── Nav ─────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-20 border-b border-[color:var(--brand-ring)]/40 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[color:var(--brand)] font-heading text-sm font-bold text-white">
              E
            </div>
            <span className="font-heading text-lg font-bold text-[color:var(--ink)]">EWMP</span>
          </div>
          <nav className="hidden items-center gap-8 text-sm font-medium text-[color:var(--ink)] md:flex">
            <a href="#features" className="hover:text-[color:var(--brand)]">Features</a>
            <a href="#pricing" className="hover:text-[color:var(--brand)]">Pricing</a>
            <a href="#security" className="hover:text-[color:var(--brand)]">Security</a>
            <a href="#contact" className="hover:text-[color:var(--brand)]">Contact</a>
          </nav>
          <div className="flex items-center gap-4">
            <Link href="/login" className="hidden text-sm font-medium text-[color:var(--ink)] hover:text-[color:var(--brand)] sm:block">
              Sign In
            </Link>
            <Link
              href="/register"
              className="rounded-lg bg-[color:var(--brand)] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[color:var(--brand-dark)]"
            >
              Start Free Trial
            </Link>
          </div>
        </div>
      </header>

      {/* ── Hero ────────────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-4xl px-6 pb-20 pt-24 text-center">
        <h1 className="font-heading text-4xl font-bold leading-[1.1] tracking-tight text-[color:var(--ink)] sm:text-6xl">
          Run your whole workforce —
          <br />
          not just your headcount
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-lg text-[color:var(--muted)]">
          HR, payroll, device fleet, and AI-driven insights in one platform. EWMP
          replaces the spreadsheet-and-five-tools mess with a single system that
          scales from your first hire to your thousandth.
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Link
            href="/register"
            className="flex items-center gap-2 rounded-lg bg-[color:var(--brand)] px-6 py-3 text-sm font-semibold text-white transition hover:bg-[color:var(--brand-dark)]"
          >
            Start Free 14-Day Trial <ArrowRight size={16} />
          </Link>
          <a
            href="#contact"
            className="rounded-lg border border-slate-300 px-6 py-3 text-sm font-semibold text-[color:var(--ink)] transition hover:border-[color:var(--brand)] hover:text-[color:var(--brand)]"
          >
            Schedule a Demo
          </a>
        </div>
        <p className="mt-4 text-xs text-[color:var(--muted)]">
          No credit card required · Setup in minutes · Cancel anytime
        </p>
      </section>

      {/* ── Features ────────────────────────────────────────────────────── */}
      <section id="features" className="border-y border-[color:var(--brand-ring)]/40 bg-[color:var(--surface)] px-6 py-24">
        <div className="mx-auto max-w-6xl">
          <div className="mx-auto max-w-2xl text-center">
            <h2 className="font-heading text-3xl font-bold text-[color:var(--ink)] sm:text-4xl">
              Everything you need to run HR
            </h2>
            <p className="mt-3 text-[color:var(--muted)]">
              Six modules, one login, zero duct tape between them.
            </p>
          </div>
          <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {features.map((f) => (
              <div
                key={f.title}
                className="rounded-2xl border border-slate-200 bg-white p-6 transition hover:border-[color:var(--brand-ring)] hover:shadow-[0_8px_24px_-12px_rgba(79,70,229,0.25)]"
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[color:var(--brand-soft)]">
                  <f.icon size={20} className="text-[color:var(--brand)]" />
                </div>
                <h3 className="mt-4 font-heading text-base font-semibold text-[color:var(--ink)]">
                  {f.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-[color:var(--muted)]">
                  {f.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Pricing ─────────────────────────────────────────────────────── */}
      <section id="pricing" className="px-6 py-24">
        <div className="mx-auto max-w-6xl">
          <div className="mx-auto max-w-2xl text-center">
            <h2 className="font-heading text-3xl font-bold text-[color:var(--ink)] sm:text-4xl">
              Simple, transparent pricing
            </h2>
            <p className="mt-3 text-[color:var(--muted)]">
              Choose the plan that fits your team — upgrade anytime.
            </p>
          </div>
          <div className="mt-14 grid gap-6 lg:grid-cols-3">
            {plans.map((plan) => (
              <div
                key={plan.name}
                className={`relative rounded-2xl border p-8 ${
                  plan.highlighted
                    ? "border-[color:var(--brand)] shadow-[0_16px_40px_-16px_rgba(79,70,229,0.35)]"
                    : "border-slate-200"
                }`}
              >
                {plan.highlighted && (
                  <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-[color:var(--brand)] px-3 py-1 text-xs font-semibold text-white">
                    Most Popular
                  </span>
                )}
                <h3 className="font-heading text-lg font-semibold text-[color:var(--ink)]">{plan.name}</h3>
                <div className="mt-3 flex items-baseline gap-1.5">
                  <span className="font-heading text-3xl font-bold text-[color:var(--ink)]">{plan.price}</span>
                  <span className="text-sm text-[color:var(--muted)]">{plan.unit}</span>
                </div>
                <Link
                  href="/register"
                  className={`mt-6 block rounded-lg px-4 py-2.5 text-center text-sm font-semibold transition ${
                    plan.highlighted
                      ? "bg-[color:var(--brand)] text-white hover:bg-[color:var(--brand-dark)]"
                      : "border border-slate-300 text-[color:var(--ink)] hover:border-[color:var(--brand)] hover:text-[color:var(--brand)]"
                  }`}
                >
                  {plan.cta}
                </Link>
                <ul className="mt-6 space-y-3">
                  {plan.features.map((feat) => (
                    <li key={feat} className="flex items-start gap-2 text-sm text-[color:var(--ink)]">
                      <Check size={16} className="mt-0.5 shrink-0 text-[color:var(--brand)]" />
                      {feat}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA banner ──────────────────────────────────────────────────── */}
      <section id="contact" className="bg-[color:var(--brand)] px-6 py-20 text-center">
        <h2 className="font-heading text-3xl font-bold text-white sm:text-4xl">
          Ready to transform your workforce?
        </h2>
        <p className="mx-auto mt-3 max-w-xl text-[color:var(--brand-soft)]">
          Join growing teams running HR, payroll, and IT on EWMP.
        </p>
        <Link
          href="/register"
          className="mt-8 inline-block rounded-lg bg-white px-6 py-3 text-sm font-semibold text-[color:var(--brand)] transition hover:bg-[color:var(--brand-soft)]"
        >
          Start Your Free Trial
        </Link>
      </section>

      {/* ── Footer ──────────────────────────────────────────────────────── */}
      <footer className="px-6 py-14">
        <div className="mx-auto grid max-w-6xl gap-10 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <div className="flex items-center gap-2.5">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[color:var(--brand)] font-heading text-xs font-bold text-white">
                E
              </div>
              <span className="font-heading text-base font-bold text-[color:var(--ink)]">EWMP</span>
            </div>
            <p className="mt-3 text-sm text-[color:var(--muted)]">
              The complete workforce platform for modern teams.
            </p>
          </div>
          <FooterCol title="Product" links={["Features", "Pricing", "Security"]} />
          <FooterCol title="Company" links={["About", "Contact", "Careers"]} />
          <FooterCol title="Legal" links={["Privacy Policy", "Terms of Service", "Security"]} />
        </div>
        <div className="mx-auto mt-10 max-w-6xl border-t border-slate-200 pt-6 text-center text-xs text-[color:var(--muted)]">
          © {new Date().getFullYear()} EWMP. All rights reserved.
        </div>
      </footer>
    </div>
  );
}

function FooterCol({ title, links }: { title: string; links: string[] }) {
  return (
    <div>
      <h4 className="font-heading text-sm font-semibold text-[color:var(--ink)]">{title}</h4>
      <ul className="mt-3 space-y-2">
        {links.map((l) => (
          <li key={l}>
            <a href="#" className="text-sm text-[color:var(--muted)] hover:text-[color:var(--brand)]">
              {l}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
