import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink:   '#0a0a0a',
        panel: '#121014',
        neon:  '#bb00ff',
        neon2: '#7a00b3',
      },
      boxShadow: {
        neon: '0 0 24px rgba(187,0,255,0.45)',
        glow: '0 0 60px rgba(187,0,255,0.25)',
      },
      backgroundImage: {
        'grad-neon': 'linear-gradient(135deg,#bb00ff 0%,#7a00b3 100%)',
        'grad-dark': 'radial-gradient(ellipse at top,#1a0a22 0%,#0a0a0a 60%)',
      },
      keyframes: {
        pulseGlow: {
          '0%,100%': { boxShadow: '0 0 24px rgba(187,0,255,0.45)' },
          '50%':     { boxShadow: '0 0 48px rgba(187,0,255,0.75)' },
        },
        shimmer: {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
      animation: {
        pulseGlow: 'pulseGlow 2.4s ease-in-out infinite',
        shimmer:   'shimmer 1.6s linear infinite',
      },
    },
  },
  plugins: [],
};
export default config;
