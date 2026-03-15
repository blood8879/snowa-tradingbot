/** Market-aware currency formatting utilities. */

export function formatPrice(value: number | null, market: string): string {
  if (value == null) return '—';
  if (market === 'KR') return `₩${Math.round(value).toLocaleString()}`;
  return `$${value.toFixed(2)}`;
}

export function formatCurrency(value: number | null, market: string): string {
  if (value == null) return '—';
  if (market === 'KR') return `₩${Math.round(value).toLocaleString()}`;
  return `$${value.toLocaleString()}`;
}

export function formatPnlValue(value: number, market: string): string {
  const sign = value > 0 ? '+' : '';
  const sym = market === 'KR' ? '₩' : '$';
  return `${sign}${sym}${value.toLocaleString()}`;
}

export function currencySymbol(market: string): string {
  return market === 'KR' ? '₩' : '$';
}
