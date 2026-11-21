import { fileURLToPath } from "node:url";

// Point Tailwind at this folder's config explicitly: by default it looks in the current
// working directory, so starting Vite from the repo root (`vite apps/web`) lost the theme.
export default {
  plugins: {
    tailwindcss: { config: fileURLToPath(new URL("./tailwind.config.js", import.meta.url)) },
    autoprefixer: {},
  },
};
