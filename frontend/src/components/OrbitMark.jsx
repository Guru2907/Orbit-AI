export default function OrbitMark({ size = 28, spinning = false }) {
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <div className="absolute inset-0 rounded-full border-2 border-brand/30" />
      <div
        className={`absolute left-1/2 top-1/2 h-[6px] w-[6px] -ml-[3px] -mt-[3px] rounded-full bg-accent ${
          spinning ? 'animate-orbitspin' : ''
        }`}
        style={!spinning ? { transform: `translateX(${size * 0.32}px)` } : undefined}
      />
      <div className="absolute left-1/2 top-1/2 h-[7px] w-[7px] -ml-[3.5px] -mt-[3.5px] rounded-full bg-brand" />
    </div>
  )
}