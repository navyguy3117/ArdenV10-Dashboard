/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          deep: '#020212',
          nav: '#05061a',
        },
        neon: {
          cyan: '#4FF2F2',
          magenta: '#FF4BE1',
          purple: '#7C3AED',
          orange: '#F97316',
        },
      },
    },
  },
  plugins: [],
}
