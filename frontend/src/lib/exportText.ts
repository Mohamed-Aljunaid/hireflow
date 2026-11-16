import type { CoverLetter, TailoredBullets } from '../api/client'

export function letterText(letter: CoverLetter): string {
  return [letter.salutation, ...letter.paragraphs.map((p) => p.text), letter.closing].join('\n\n')
}

export function exportText(bullets: TailoredBullets, letter: CoverLetter): string {
  return [
    'TAILORED CV BULLETS',
    ...bullets.bullets.map((b) => `- ${b.text}`),
    '',
    'COVER LETTER',
    letterText(letter),
  ].join('\n')
}
