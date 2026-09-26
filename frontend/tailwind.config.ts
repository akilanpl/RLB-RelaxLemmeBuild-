import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        background: 'var(--background)',
        foreground: 'var(--foreground)',
        midnight: {
          DEFAULT: '#0c1c2e',
          800: '#143047',
          700: '#1c3d56',
        },
        skyblue: {
          DEFAULT: '#8ec8e6',
          deep: '#4a90b8',
        },
        cream: '#f6efe4',
        paper: '#fffaf3',
        lavender: '#c9b8e8',
        violet: '#8d7ab8',
        coral: '#e07a5f',
        meadow: '#6a9f7a',
        gold: '#e8c47c',
        ink: '#1a2a38',
      },
      fontFamily: {
        sans: ['var(--font-sans)', 'ui-sans-serif', 'system-ui'],
        hand: ['var(--font-hand)', 'cursive'],
      },
      borderRadius: {
        rlb: '20px',
        'rlb-sm': '12px',
      },
      boxShadow: {
        soft: '0 18px 50px -20px rgba(12, 28, 46, 0.45)',
        float: '0 30px 80px -30px rgba(12, 28, 46, 0.55)',
      },
      transitionTimingFunction: {
        rlb: 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
    },
  },
  plugins: [],
};

export default config;
