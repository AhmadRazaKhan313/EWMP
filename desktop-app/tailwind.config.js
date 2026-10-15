/** @type {import('tailwindcss').Config} */
const tokens = require("./tailwind.tokens.js");

module.exports = {
  darkMode: ["class"],
  content: ["./src/renderer/index.html", "./src/renderer/src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      ...tokens,
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui"],
        heading: ["var(--font-heading)", "ui-sans-serif", "system-ui"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
