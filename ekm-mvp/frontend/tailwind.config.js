/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        navy: {
          50: '#f0f4f8',
          100: '#d9e2ec',
          600: '#2d5a8e',
          700: '#1e3a5f',
          800: '#162d4a',
          900: '#0d1b2e',
        },
        teal: {
          400: '#2dd4c4',
          500: '#028090',
          600: '#026f7a',
        }
      }
    }
  },
  plugins: []
}
