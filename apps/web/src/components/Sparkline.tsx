export function Sparkline({ values, className = "h-10 w-28", label }: { values: number[]; className?: string; label?: string }) {
  if (values.length < 2) return <div className={className} aria-hidden />;
  const w = 112;
  const h = 40;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * (w - 4) + 2, h - 3 - ((v - min) / span) * (h - 6)] as const);
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const rising = values[values.length - 1] >= values[0];
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={className} role="img" aria-label={label}>
      <path d={d} fill="none" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" className={rising ? "stroke-leaf-600" : "stroke-soil-500"} />
      <circle cx={lx} cy={ly} r={3} className={rising ? "fill-leaf-600" : "fill-soil-500"} />
    </svg>
  );
}
