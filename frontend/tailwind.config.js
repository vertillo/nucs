/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./src/**/*.{ts,tsx}', './index.html'],
  theme: {
    extend: {
      colors: {
        accent: '#1DB954',
        accentHover: '#1ED760',
        accentActive: '#169C46',
        danger: '#E5484D',
        yt: '#FF0000',
        deezer: '#A238FF',
        dark: {
          bg: '#0F0F0F',
          surface: '#181818',
          surface2: '#242424',
          border: '#2C2C2C',
          text: '#F5F5F5',
          textDim: '#A3A3A3',
        },
        light: {
          bg: '#FFFFFF',
          surface: '#F6F6F6',
          surface2: '#FFFFFF',
          border: '#E4E4E4',
          text: '#131313',
          textDim: '#5C5C5C',
        },
      },
      fontFamily: {
        sans: ['-apple-system', 'Segoe UI', 'Roboto', 'Inter', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
