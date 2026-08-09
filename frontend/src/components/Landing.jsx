import OrbitMark from './OrbitMark.jsx'
import KanbanHero from './KanbanHero.jsx'

const features = [
  { title: 'Task boards', body: "Kanban-style columns your team already knows — To Do, In Progress, Done." },
  { title: 'Assignments & deadlines', body: "Give every task an owner and a due date. Nothing slips through quietly." },
  { title: 'Reporting, built in', body: "See tasks completed per week and what's overdue, without a separate tool." },
]

export default function Landing({ onNavigate }) {
  return (
    <div className="min-h-screen bg-bg">
      <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2">
          <OrbitMark size={24} />
          <span className="font-display text-lg font-semibold tracking-tight">Flowspace</span>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={() => onNavigate('auth', 'login')} className="rounded-full px-4 py-2 text-sm font-medium text-ink hover:bg-surface transition">
            Log in
          </button>
          <button onClick={() => onNavigate('auth', 'signup')} className="rounded-full bg-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90 transition">
            Sign up free
          </button>
        </div>
      </nav>

      <header className="mx-auto grid max-w-6xl items-center gap-12 px-6 pb-24 pt-12 md:grid-cols-2 md:pt-20">
        <div>
          <span className="inline-block rounded-full bg-brandsoft px-3 py-1 font-mono text-[12px] text-brand">
            Project management, minus the bloat
          </span>
          <h1 className="mt-5 font-display text-4xl font-semibold leading-[1.1] tracking-tight text-ink md:text-5xl">
            Work moves in a flow.
            <br />
            Your tools should too.
          </h1>
          <p className="mt-5 max-w-md text-[17px] leading-relaxed text-inksoft">
            Flowspace is where small teams track work, hit deadlines, and actually know what's going on — without the enterprise setup tax.
          </p>
          <div className="mt-8 flex items-center gap-4">
            <button onClick={() => onNavigate('auth', 'signup')} className="rounded-full bg-ink px-6 py-3 text-sm font-medium text-white hover:bg-brand transition">
              Start free — no card needed
            </button>
            <a href="#orbit" className="text-sm font-medium text-inksoft hover:text-ink transition">
              Meet Orbit, our AI support →
            </a>
          </div>
        </div>
        <KanbanHero />
      </header>

      <section className="mx-auto max-w-6xl px-6 py-16">
        <div className="grid gap-8 md:grid-cols-3">
          {features.map((f) => (
            <div key={f.title} className="rounded-2xl border border-line bg-surface p-6">
              <h3 className="font-display text-[17px] font-semibold text-ink">{f.title}</h3>
              <p className="mt-2 text-[14.5px] leading-relaxed text-inksoft">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="orbit" className="mx-auto max-w-6xl px-6 py-20">
        <div className="rounded-3xl border border-line bg-surface p-10 text-center md:p-14">
          <div className="mx-auto flex h-14 w-14 items-center justify-center">
            <OrbitMark size={40} />
          </div>
          <h2 className="mt-4 font-display text-2xl font-semibold text-ink md:text-3xl">
            Ask Orbit anything about Flowspace
          </h2>
          <p className="mx-auto mt-3 max-w-md text-[15px] leading-relaxed text-inksoft">
            Pricing, cancellations, invites, API limits — Orbit answers straight from Flowspace's real support docs, with sources, or tells you honestly when it doesn't know.
          </p>
          <button onClick={() => onNavigate('auth', 'login')} className="mt-6 rounded-full bg-brand px-6 py-3 text-sm font-medium text-white hover:opacity-90 transition">
            Sign in to chat with Orbit
          </button>
        </div>
      </section>

      <footer className="mx-auto max-w-6xl px-6 py-10 text-[13px] text-inksoft">
        Flowspace is a fictional product built for a portfolio project.
      </footer>
    </div>
  )
}