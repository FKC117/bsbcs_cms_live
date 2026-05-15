/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./pages/*.{html,js}",
    "./index.html",
    "./components/**/*.{html,js}",
    "./src/**/*.{html,js}"
  ],
  theme: {
    extend: {
      colors: {
        // Primary Colors - Medical Authority and Trust Foundation
        primary: {
          DEFAULT: "#1976D2", // blue-600
          50: "#E3F2FD", // blue-50
          100: "#BBDEFB", // blue-100
          200: "#90CAF9", // blue-200
          300: "#64B5F6", // blue-300
          400: "#42A5F5", // blue-400
          500: "#2196F3", // blue-500
          600: "#1976D2", // blue-600
          700: "#1565C0", // blue-700
          800: "#0D47A1", // blue-800
          900: "#0A3D91", // blue-900
        },
        // Secondary Colors - Breast Cancer Awareness Accent Moments
        secondary: {
          DEFAULT: "#E91E63", // pink-600
          50: "#FCE4EC", // pink-50
          100: "#F8BBD0", // pink-100
          200: "#F48FB1", // pink-200
          300: "#F06292", // pink-300
          400: "#EC407A", // pink-400
          500: "#E91E63", // pink-500
          600: "#D81B60", // pink-600
          700: "#C2185B", // pink-700
          800: "#AD1457", // pink-800
          900: "#880E4F", // pink-900
        },
        // Accent Colors - Success States and Progress Indicators
        accent: {
          DEFAULT: "#00695C", // teal-800
          50: "#E0F2F1", // teal-50
          100: "#B2DFDB", // teal-100
          200: "#80CBC4", // teal-200
          300: "#4DB6AC", // teal-300
          400: "#26A69A", // teal-400
          500: "#009688", // teal-500
          600: "#00897B", // teal-600
          700: "#00796B", // teal-700
          800: "#00695C", // teal-800
          900: "#004D40", // teal-900
        },
        // Background Colors
        background: "#FAFAFA", // gray-50 - Clean research environment canvas
        surface: "#FFFFFF", // white - Content containers and card surfaces
        // Text Colors
        text: {
          primary: "#212121", // gray-900 - Extended reading and medical content
          secondary: "#616161", // gray-700 - Supporting information and metadata
          tertiary: "#9E9E9E", // gray-500
          disabled: "#BDBDBD", // gray-400
        },
        // Semantic Colors
        success: {
          DEFAULT: "#2E7D32", // green-800 - Positive confirmations and achievements
          light: "#A5D6A7", // green-200
          dark: "#1B5E20", // green-900
        },
        warning: {
          DEFAULT: "#F57C00", // orange-700 - Important notices without alarm
          light: "#FFE0B2", // orange-100
          dark: "#E65100", // orange-900
        },
        error: {
          DEFAULT: "#C62828", // red-800 - Clear problem identification and guidance
          light: "#FFCDD2", // red-100
          dark: "#B71C1C", // red-900
        },
        // Border Colors
        border: {
          DEFAULT: "#E0E0E0", // gray-300
          light: "#F5F5F5", // gray-100
          dark: "#BDBDBD", // gray-400
        },
      },
      fontFamily: {
        headline: ['Inter', 'sans-serif'], // Modern medical professionalism
        body: ['Source Sans Pro', 'sans-serif'], // Optimized for extended reading
        cta: ['Inter', 'sans-serif'], // Consistent action hierarchy
        accent: ['Source Serif Pro', 'serif'], // Subtle sophistication for quotes
        sans: ['Source Sans Pro', 'sans-serif'],
        serif: ['Source Serif Pro', 'serif'],
      },
      fontSize: {
        'xs': ['0.75rem', { lineHeight: '1rem' }],
        'sm': ['0.875rem', { lineHeight: '1.25rem' }],
        'base': ['1rem', { lineHeight: '1.75rem' }],
        'lg': ['1.125rem', { lineHeight: '1.75rem' }],
        'xl': ['1.25rem', { lineHeight: '1.75rem' }],
        '2xl': ['1.5rem', { lineHeight: '2rem' }],
        '3xl': ['1.875rem', { lineHeight: '2.25rem' }],
        '4xl': ['2.25rem', { lineHeight: '2.5rem' }],
        '5xl': ['3rem', { lineHeight: '1.2' }],
        '6xl': ['3.75rem', { lineHeight: '1.2' }],
      },
      boxShadow: {
        'sm': '0 1px 3px rgba(0, 0, 0, 0.08)', // Minimal elevation
        'DEFAULT': '0 2px 8px rgba(0, 0, 0, 0.1)', // Floating elements
        'md': '0 2px 8px rgba(0, 0, 0, 0.1)', // Navigation and modals
        'lg': '0 4px 16px rgba(0, 0, 0, 0.12)',
        'xl': '0 8px 24px rgba(0, 0, 0, 0.15)',
        'none': 'none',
      },
      borderRadius: {
        'sm': '0.25rem', // 4px
        'DEFAULT': '0.5rem', // 8px
        'md': '0.5rem', // 8px
        'lg': '0.75rem', // 12px
        'xl': '1rem', // 16px
        'full': '9999px',
      },
      spacing: {
        'xs': '0.25rem', // 4px
        'sm': '0.5rem', // 8px
        'md': '1rem', // 16px
        'lg': '1.5rem', // 24px
        'xl': '2rem', // 32px
        '2xl': '3rem', // 48px
        '3xl': '4rem', // 64px
      },
      transitionDuration: {
        'fast': '150ms', // Quick feedback
        'DEFAULT': '300ms', // Smooth responsive transitions
        'slow': '500ms', // Deliberate animations
      },
      transitionTimingFunction: {
        'DEFAULT': 'cubic-bezier(0, 0, 0.2, 1)', // ease-out
      },
      borderWidth: {
        'DEFAULT': '1px',
        '0': '0',
        '2': '2px',
        '3': '3px', // Strategic colored left borders
        '4': '4px',
      },
      maxWidth: {
        'container': '1280px',
      },
      zIndex: {
        'dropdown': '1000',
        'sticky': '1020',
        'fixed': '1030',
        'modal-backdrop': '1040',
        'modal': '1050',
        'popover': '1060',
        'tooltip': '1070',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms')({
      strategy: 'class',
    }),
    require('@tailwindcss/typography'),
  ],
}