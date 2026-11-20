export function Sparkline({ values, className = "h-10 w-28", label }: { values: number[]; className?: string; label?: string }) {
  if (values.length < 2) return <div className={className} aria-hidden />;
  const w = 112;
  const h = 40;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * (w - 4) + 2, h - 3 - ((v - min) / span) * (h - 6)] as const);
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${d} L${pts[pts.length - 1][0].toFixed(1)},${h} L${pts[0][0].toFixed(1)},${h} Z`;
  // Rising prices are good news for a seller; falling ones are a warning.
  const rising = values[values.length - 1] >= values[0];
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={`shrink-0 ${className}`} role="img" aria-label={label}>
      <path d={area} className={rising ? "fill-leaf/10" : "fill-chilli/10"} />
      <path d={d} fill="none" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" className={rising ? "stroke-leaf" : "stroke-chilli"} />
      <circle cx={lx} cy={ly} r={3} className={rising ? "fill-leaf" : "fill-chilli"} />
    </svg>
  );
}
