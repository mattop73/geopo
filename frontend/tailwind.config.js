/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: '#0f1117',
        panel: '#1a1d27',
        border: '#2a2d3a',
        accent: '#3b82f6',
        green: { 500: '#22c55e', 400: '#4ade80' },
        red: { 500: '#ef4444', 400: '#f87171' },
        yellow: { 400: '#facc15', 500: '#eab308' },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
  plugins: [],
}
