/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      fontFamily: {
        sans: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "Noto Sans", "Noto Sans Devanagari", "Mangal", "sans-serif"],
      },
      colors: {
        leaf: { 50: "#f1f8f2", 100: "#dcefdf", 500: "#2f8a46", 600: "#25713a", 700: "#1d5a2e", 900: "#0f2f18" },
        soil: { 50: "#faf6f1", 100: "#f1e8dc", 500: "#9a6b3c", 700: "#6b4826" },
      },
    },
  },
  plugins: [],
};
