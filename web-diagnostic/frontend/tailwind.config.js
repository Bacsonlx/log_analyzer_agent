/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: '#3dc7f5',
        'bg-dark': '#0a0f12',
        surface: '#16252a',
        'surface-2': '#1a2e35',
        'neon-green': '#00ff9d',
        'neon-purple': '#bc13fe',
        'accent-red': '#ff4d4d',
        'accent-yellow': '#ffb347',
      },
      fontFamily: {
        display: ['Space Grotesk', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
};
