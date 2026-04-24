/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        border: "hsl(240 5% 20%)",
        background: "hsl(240 10% 4%)",
        foreground: "hsl(0 0% 98%)",
        muted: {
          DEFAULT: "hsl(240 5% 12%)",
          foreground: "hsl(240 5% 65%)",
        },
        card: {
          DEFAULT: "hsl(240 10% 6%)",
          foreground: "hsl(0 0% 98%)",
        },
        primary: {
          DEFAULT: "hsl(263 80% 65%)",
          foreground: "hsl(0 0% 100%)",
        },
        accent: {
          DEFAULT: "hsl(240 5% 14%)",
          foreground: "hsl(0 0% 98%)",
        },
        destructive: {
          DEFAULT: "hsl(0 72% 51%)",
          foreground: "hsl(0 0% 100%)",
        },
        success: {
          DEFAULT: "hsl(142 70% 45%)",
          foreground: "hsl(0 0% 100%)",
        },
        warning: {
          DEFAULT: "hsl(38 92% 50%)",
          foreground: "hsl(0 0% 100%)",
        },
      },
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
