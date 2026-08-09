const cards = [
  { title: 'Design onboarding flow', tag: 'In Progress', color: 'bg-progress' },
  { title: 'Fix teammate invite bug', tag: 'To Do', color: 'bg-todo' },
  { title: 'Ship v2 dashboard', tag: 'Done', color: 'bg-success' },
]

export default function KanbanHero() {
  return (
    <div className="relative h-[280px] w-full max-w-sm mx-auto md:mx-0">
      {cards.map((card, i) => (
        <div
          key={card.title}
          className="absolute w-64 rounded-2xl border border-line bg-surface p-4 shadow-xl animate-floatslow"
          style={{
            top: `${i * 46}px`,
            left: `${i * 28}px`,
            zIndex: cards.length - i,
            transform: `rotate(${i === 0 ? -6 : i === 1 ? 2 : -2}deg)`,
            animationDelay: `${i * 0.4}s`,
          }}
        >
          <span className={`inline-block rounded-full ${card.color} px-2.5 py-0.5 text-[11px] font-mono text-white`}>
            {card.tag}
          </span>
          <p className="mt-3 font-display text-[15px] font-medium text-ink leading-snug">
            {card.title}
          </p>
          <div className="mt-3 h-1.5 w-10 rounded-full bg-line" />
        </div>
      ))}
    </div>
  )
}