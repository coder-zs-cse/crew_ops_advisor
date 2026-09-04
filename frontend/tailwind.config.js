/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Dark cockpit: the default view is quiet. Colour is a signal, not decoration.
        ink: {
          950: '#070a10',
          900: '#0a0e17',
          850: '#0d1220',
          800: '#111827',
          750: '#151c2c',
          700: '#1e293b',
          600: '#293548',
          500: '#3b4a63',
        },
        mute: {
          400: '#7d8da8',
          300: '#9fb0c8',
          200: '#c3cfe0',
        },
        // Semantic status. Legal/illegal is the single most important read.
        legal: '#34d399',
        breach: '#f87171',
        caution: '#fbbf24',
        advisory: '#a78bfa',
        // Cyan = operational intelligence; violet = system internals.
        signal: '#22d3ee',
        deep: '#0ea5e9',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      animation: {
        'fade-in': 'fadeIn 200ms ease-out',
        'slide-up': 'slideUp 240ms cubic-bezier(0.16, 1, 0.3, 1)',
        'pulse-soft': 'pulseSoft 2.4s ease-in-out infinite',
        shimmer: 'shimmer 1.6s linear infinite',
      },
      keyframes: {
        fadeIn: { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pulseSoft: { '0%,100%': { opacity: '0.45' }, '50%': { opacity: '1' } },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
    },
  },
  plugins: [],
}
