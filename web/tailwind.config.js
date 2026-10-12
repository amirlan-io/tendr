/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", ".dark"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#10b981", // emerald-500
          dark: "#059669", // emerald-600
          light: "#34d399", // emerald-400
        },
        // shadcn-токены для компонентов из /components/ui.
        // Значения — RGB-триплеты, чтобы работали модификаторы прозрачности (/50 и т.п.).
        background: "rgb(var(--background) / <alpha-value>)",
        foreground: "rgb(var(--foreground) / <alpha-value>)",
        card: "rgb(var(--card) / <alpha-value>)",
        border: "rgb(var(--border-token) / <alpha-value>)",
        primary: {
          DEFAULT: "rgb(var(--primary) / <alpha-value>)",
          foreground: "rgb(var(--primary-foreground) / <alpha-value>)",
        },
        muted: {
          foreground: "rgb(var(--muted-foreground) / <alpha-value>)",
        },
        ink: {
          50: "#fafafa",
          100: "#f4f4f5",
          200: "#e4e4e7",
          300: "#d4d4d8",
          400: "#a1a1aa",
          500: "#71717a",
          600: "#52525b",
          700: "#3f3f46",
          800: "#27272a",
          900: "#18181b",
          950: "#09090b",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        display: ["Inter", "system-ui", "sans-serif"],
      },
      letterSpacing: {
        tightest: "-0.04em",
        wider: "0.05em",
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(16, 185, 129, 0.2), 0 8px 32px -8px rgba(16, 185, 129, 0.1)",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
