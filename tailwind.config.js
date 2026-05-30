/** Ported from the inline `tailwind.config` in base.html / dashboard/base.html / landing/_head.html */
module.exports = {
  content: [
    './myApp/templates/**/*.html',
    './static/**/*.js',
    './myApp/static/**/*.js',
  ],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'sans-serif'] },
      colors: {
        'navy-dark': '#0a0e27',
        'navy-mid': '#1a1f3a',
        'cyan-electric': '#00f0ff',
        'purple-accent': '#a855f7',
        'emerald-glow': '#10b981',
      },
    },
  },
  // Dynamically-composed class names that the content scanner cannot see literally.
  // Found in: generate_lesson_ai.html (addTestMessage), lesson.html / students.html (avatars).
  safelist: [
    { pattern: /(bg|text|border|from|to)-(cyan-electric|purple-accent)(\/(5|10|15|20|30|40|50|70|80))?/, variants: ['hover', 'focus'] },
  ],
}
