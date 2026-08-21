/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        base: {
          900: '#0a0e1a',
          800: '#131826',
          700: '#1c2333',
        },
        cyan: '#22d3ee',
        ok: '#10b981',
        warn: '#f59e0b',
        bad: '#ef4444',
      },
      animation: {
        breathe: 'breathe 2s ease-in-out infinite',
      },
      keyframes: {
        breathe: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
      },
    },
  },
  plugins: [],
}
