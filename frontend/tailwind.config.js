export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#F7F7F5',
        surface: '#FFFFFF',
        ink: '#15171B',
        inksoft: '#5B5F6B',
        line: '#E4E4E0',
        brand: '#362FD9',
        brandsoft: '#EEEDFC',
        accent: '#FF5B36',
        success: '#1C8A4B',
        progress: '#D98B12',
        todo: '#6B7280',
      },
      fontFamily: {
        display: ['"Space Grotesk"', 'sans-serif'],
        body: ['Inter', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      keyframes: {
        orbitspin: {
          '0%': { transform: 'rotate(0deg) translateX(11px) rotate(0deg)' },
          '100%': { transform: 'rotate(360deg) translateX(11px) rotate(-360deg)' },
        },
        floatslow: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-6px)' },
        },
      },
      animation: {
        orbitspin: 'orbitspin 1.6s linear infinite',
        floatslow: 'floatslow 4.5s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}