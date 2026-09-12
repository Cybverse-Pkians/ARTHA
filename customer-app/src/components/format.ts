/** Indian number formatting, shared by every surface.
 *
 * ₹1,00,000 rather than ₹100,000 — the grouping is not cosmetic, it is how the
 * number is read aloud. `en-IN` gives the lakh/crore grouping natively.
 */

const INR = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

export function formatPaise(paise: number): string {
  return INR.format(Math.round(paise / 100));
}

export function formatCompactPaise(paise: number): string {
  const rupees = Math.round(paise / 100);
  const abs = Math.abs(rupees);
  if (abs >= 10_000_000) return `₹${(rupees / 10_000_000).toFixed(1)}Cr`;
  if (abs >= 100_000) return `₹${(rupees / 100_000).toFixed(1)}L`;
  if (abs >= 1_000) return `₹${(rupees / 1_000).toFixed(0)}k`;
  return `₹${rupees}`;
}

export function formatPercent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function titleCase(value: string): string {
  return value
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
