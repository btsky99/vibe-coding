/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#0a0a0f',
        surface: '#12121c',
        surfaceHover: '#1a1a26',
        primary: '#3b82f6',
        accent: '#8b5cf6',
        textMain: '#e2e8f0',
        textMuted: '#94a3b8',
        success: '#10b981',
        error: '#ef4444',
      },
    },
  },
  plugins: [],
}
