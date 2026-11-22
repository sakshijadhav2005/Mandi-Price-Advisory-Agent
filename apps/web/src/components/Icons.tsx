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
export const UserIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21a8 8 0 0 1 16 0" />
  </svg>
);
export const GlobeIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <circle cx="12" cy="12" r="9" />
    <path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3Z" />
  </svg>
);
export const SunIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>
);
export const MoonIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z" />
  </svg>
);
export const PhoneIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <rect x="7" y="2.5" width="10" height="19" rx="2.5" />
    <path d="M11 18.5h2" />
  </svg>
);
export const SlidersIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
    <circle cx="16" cy="7" r="2" />
    <circle cx="10" cy="17" r="2" />
  </svg>
);
export const ServerIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <rect x="3" y="4" width="18" height="7" rx="2" />
    <rect x="3" y="13" width="18" height="7" rx="2" />
    <path d="M7 7.5h.01M7 16.5h.01" />
  </svg>
);
export const ShieldIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <path d="M12 3 5 6v5c0 4.5 3 8.3 7 10 4-1.7 7-5.5 7-10V6l-7-3Z" />
    <path d="m9 12 2 2 4-4" />
  </svg>
);
export const InfoIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5M12 8h.01" />
  </svg>
);
export const ChevronRightIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <path d="m9 6 6 6-6 6" />
  </svg>
);
export const ChevronDownIcon = ({ className = "h-4 w-4" }: P) => (
  <svg {...base} className={className}>
    <path d="m6 9 6 6 6-6" />
  </svg>
);
export const LogOutIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l-5-5 5-5M5 12h11" />
  </svg>
);
export const MapIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <path d="m3 6 6-2 6 2 6-2v14l-6 2-6-2-6 2V6Z" />
    <path d="M9 4v14M15 6v14" />
  </svg>
);
export const MailIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <path d="m3 7 9 6 9-6" />
  </svg>
);
export const LockIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <rect x="4" y="11" width="16" height="10" rx="2" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" />
  </svg>
);
export const EyeIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);
export const EyeOffIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <path d="M10.6 5.1A10.8 10.8 0 0 1 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-2.4 3.3M6.6 6.6C3.9 8.3 2 12 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6" />
    <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M3 3l18 18" />
  </svg>
);
export const ArrowRightIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);
export const SparkleIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z" />
    <path d="M19 15v4M17 17h4" />
  </svg>
);
export const BoltIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" />
  </svg>
);
export const TractorIcon = ({ className = "h-6 w-6" }: P) => (
  <svg {...base} className={className}>
    <path d="M3 15V9h7l2 4h6a2 2 0 0 1 2 2v1" />
    <path d="M5 9V5h4v4M16 13V8" />
    <circle cx="7" cy="17" r="3" />
    <circle cx="18" cy="18" r="2" />
  </svg>
);
export const CalendarIcon = ({ className = "h-5 w-5" }: P) => (
  <svg {...base} className={className}>
    <rect x="3.5" y="5" width="17" height="15.5" rx="2" />
    <path d="M3.5 10h17M8 3v4M16 3v4" />
  </svg>
);
