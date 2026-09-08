import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink:    '#0a0a0a',
        panel:  '#121014',
        panel2: '#1a1a1f',
        neon:   '#bb00ff',
        neon2:  '#7a00b3',
        // Higgsfield brand colors
        lime:   '#c4f542',  // Generate button (bright lime-green/yellow)
        higyel: '#ffd700',  // "HIGGSFIELD GENJUTSU" text (bright yellow)
        higstar:'#22c55e',  // green star icon next to model name
      },
      boxShadow: {
        neon: '0 0 24px rgba(187,0,255,0.45)',
        glow: '0 0 60px rgba(187,0,255,0.25)',
        lime: '0 0 24px rgba(196,245,66,0.35)',
      },
      backgroundImage: {
        'grad-neon': 'linear-gradient(135deg,#bb00ff 0%,#7a00b3 100%)',
        'grad-dark': 'radial-gradient(ellipse at top,#1a0a22 0%,#0a0a0a 60%)',
        'grad-lime': 'linear-gradient(135deg,#c4f542 0%,#a3d136 100%)',
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
        pulseLime: {
          '0%,100%': { boxShadow: '0 0 24px rgba(196,245,66,0.35)' },
          '50%':     { boxShadow: '0 0 48px rgba(196,245,66,0.65)' },
        },
      },
      animation: {
        pulseGlow: 'pulseGlow 2.4s ease-in-out infinite',
        shimmer:   'shimmer 1.6s linear infinite',
        pulseLime: 'pulseLime 2.4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
export default config;
