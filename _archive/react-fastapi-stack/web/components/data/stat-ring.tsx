import theme from "@/../../packages/branding/theme.json";

const { clinova_cyan, clinova_deep_blue } = theme.colors;

// A real data visualization for a 0-1 measure -- replaces a bare percentage
// with a filled progress ring, the single biggest lever for not looking
// like a spreadsheet of numbers in boxes. Gradient stops read directly
// from branding theme.json (AD-3/NFR-1) -- SVG <linearGradient> can't
// consume a Tailwind utility class, so this is the closest equivalent to
// "sourced from the one config," matching how tailwind.config.ts itself
// derives its box-shadow rgba stops from the same file.
export function StatRing({ value, size = 56 }: { value: number; size?: number }) {
  const clamped = Math.max(0, Math.min(1, value));
  const stroke = 5;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - clamped);

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0 -rotate-90">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={stroke} className="text-border" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="url(#stat-ring-gradient)"
        strokeWidth={stroke}
        strokeDasharray={c}
        strokeDashoffset={offset}
        strokeLinecap="round"
      />
      <defs>
        <linearGradient id="stat-ring-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor={clinova_cyan} />
          <stop offset="100%" stopColor={clinova_deep_blue} />
        </linearGradient>
      </defs>
    </svg>
  );
}
