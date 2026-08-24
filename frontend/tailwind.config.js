/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: "#0f1420",
          raised: "#161d2e",
          border: "#232c42",
        },
      },
    },
  },
  plugins: [],
};
