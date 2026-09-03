/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0f14",
        panel: "#121821",
        panel2: "#171f2b",
        border: "#232c3a",
        accent: "#3ba7ff",
        accent2: "#22c55e",
        warn: "#f5a524",
        crit: "#f5424a",
        muted: "#7c8aa0",
      },
    },
  },
  plugins: [],
};
