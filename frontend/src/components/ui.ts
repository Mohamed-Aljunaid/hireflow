// Shared Tailwind class strings (no component library: a handful of buttons and cards).
export const card = 'rounded-xl border border-slate-200 bg-white p-5 shadow-sm'
export const btn =
  'inline-flex items-center justify-center rounded-lg px-4 py-2 text-sm font-medium ' +
  'transition disabled:cursor-not-allowed disabled:opacity-50'
export const btnPrimary = `${btn} bg-indigo-600 text-white hover:bg-indigo-700`
export const btnSecondary = `${btn} border border-slate-300 bg-white text-slate-700 hover:bg-slate-50`
export const btnDanger = `${btn} border border-red-300 bg-white text-red-700 hover:bg-red-50`
// Says why a button is disabled.
export const hint = 'mt-2 text-sm text-amber-700'
export const input =
  'w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 ' +
  'focus:outline-none focus:ring-2 focus:ring-indigo-200'

export const verdictStyle: Record<string, string> = {
  met: 'bg-emerald-100 text-emerald-800',
  partial: 'bg-amber-100 text-amber-800',
  not_met: 'bg-red-100 text-red-800',
}
