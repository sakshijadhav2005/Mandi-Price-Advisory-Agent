type P = { className?: string };
const base = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, viewBox: "0 0 24 24", "aria-hidden": true };

export const MicIcon = ({ className = "h-6 w-6" }: P) => (
  <svg {...base} className={className}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
  </svg>
);
export const SendIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <path d="M4 12 20 4l-6 16-3-7-7-1Z" />
  </svg>
);
export const SpeakerIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <path d="M4 9v6h4l5 4V5L8 9H4Z" />
    <path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11" />
  </svg>
);
export const StopIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <rect x="6" y="6" width="12" height="12" rx="2" />
  </svg>
);
export const ChatIcon = ({ className = "h-6 w-6" }: P) => (
  <svg {...base} className={className}>
    <path d="M4 5h16v11H8l-4 4V5Z" />
  </svg>
);
export const ChartIcon = ({ className = "h-6 w-6" }: P) => (
  <svg {...base} className={className}>
    <path d="M4 19h16M6 15l4-5 4 3 5-7" />
  </svg>
);
export const ClockIcon = ({ className = "h-6 w-6" }: P) => (
  <svg {...base} className={className}>
    <circle cx="12" cy="12" r="8" />
    <path d="M12 8v4l3 2" />
  </svg>
);
export const GearIcon = ({ className = "h-6 w-6" }: P) => (
  <svg {...base} className={className}>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4" />
  </svg>
);
export const PinIcon = ({ className = "h-4 w-4" }: P) => (
  <svg {...base} className={className}>
    <path d="M12 21s-6-5.5-6-11a6 6 0 0 1 12 0c0 5.5-6 11-6 11Z" />
    <circle cx="12" cy="10" r="2" />
  </svg>
);
