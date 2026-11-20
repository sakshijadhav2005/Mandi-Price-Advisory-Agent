/** @type {import('tailwindcss').Config} */
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      fontFamily: {
        // Anek covers Latin and Devanagari with one voice, so Marathi and Hindi
        // answers look as deliberate as English ones.
        sans: ["Anek Latin Variable", "Anek Devanagari Variable", "Noto Sans Devanagari", "Mangal", "system-ui", "sans-serif"],
        display: ["Anek Latin Variable", "Anek Devanagari Variable", "system-ui", "sans-serif"],
        // Prices read like an APMC rate board.
        mono: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular", "Consolas", "monospace"],
      },
      colors: {
        // Semantic tokens; values live in index.css and flip for dark mode.
        paper: token("paper"),
        surface: token("surface"),
        sunken: token("sunken"),
        ink: token("ink"),
        muted: token("muted"),
        line: token("line"),
        board: token("board"),
        "board-ink": token("board-ink"),
        leaf: {
          DEFAULT: token("leaf"),
          ink: token("leaf-ink"),
          soft: token("leaf-soft"),
        },
        turmeric: {
          DEFAULT: token("turmeric"),
          ink: token("turmeric-ink"),
          soft: token("turmeric-soft"),
        },
        chilli: {
          DEFAULT: token("chilli"),
          ink: token("chilli-ink"),
          soft: token("chilli-soft"),
        },
      },
      letterSpacing: {
        label: "0.12em",
      },
    },
  },
  plugins: [],
};
