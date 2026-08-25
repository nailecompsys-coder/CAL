/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/templates/**/*.html'],
  theme: {
    extend: {
      colors: {
        clinical: {
          ink: '#1C2430',
          muted: '#6B7A8D',
          mist: '#F4F6FA',
          card: '#FFFFFF',
          strong: '#F8FAFC',
          teal: '#007AFF',
          tealSoft: '#D6EBFF',
          scrub: '#DFF5EA',
          scrubInk: '#1F6B4E',
          porcelain: '#F0F4FB',
          mint: '#E8F8F0',
          amber: '#FFE8C2',
          lavender: '#EBE4FF',
          purple: '#6D28D9',
          purpleMid: '#8B5CF6',
          purpleSoft: '#EDE9FE',
          stroke: '#B4C4DC',
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
