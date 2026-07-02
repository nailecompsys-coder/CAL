/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/templates/**/*.html'],
  theme: {
    extend: {
      colors: {
        clinical: {
          ink: '#102B31',
          muted: '#62777D',
          mist: '#F3FAF7',
          card: '#FCFFFD',
          strong: '#FFFFF7',
          teal: '#087967',
          tealSoft: '#C2EDE6',
          scrub: '#D1F0D6',
          scrubInk: '#1A6B4C',
          porcelain: '#F7FAF2',
          mint: '#E1F7E1',
          amber: '#FFEABA',
          lavender: '#F0E8FF',
          stroke: '#B3D1D1',
        },
        slate: {
          50:  '#EAF0F8',
          100: '#F4F6F9',
          200: '#D1DCE8',
          300: '#B0C4D8',
          400: '#7A90A8',
          500: '#4A6080',
          600: '#2D4A6A',
          700: '#1E3A5A',
          800: '#14305A',
          900: '#0D2040',
        },
        blue: {
          50:  '#E8F0FC',
          100: '#D4E4F8',
          200: '#A8C8F0',
          300: '#7AB0E8',
          400: '#4D98E0',
          500: '#2080D8',
          600: '#0066CC',
          700: '#0050AA',
          800: '#003A88',
          900: '#002466',
        }
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', "'DM Sans'", 'sans-serif'],
      }
    }
  },
  plugins: [],
}
