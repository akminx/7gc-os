import type { Money } from "./contracts";

/**
 * Value-preserving presentation only. SPEC §5.3 permits locale formatting and
 * display ordering in `web/**`, and nothing else.
 *
 * Why the digits are grouped by string surgery rather than by
 * `Intl.NumberFormat`: `Intl` formats a `number`, so using it means
 * `Number(amount)` first, and $8,000,000.0000 is only safe there by luck — a
 * figure past 2^53, or any amount with the four decimal places the schema
 * allows, is silently re-rounded on the way to the screen. The whole ledger is
 * built to keep money out of binary floating point, so the browser is the last
 * place to put it back in. `parseFloat` appears nowhere in this file.
 *
 * The rule below is therefore: the digits that arrive are the digits that
 * render, in the same order, with separators inserted BETWEEN them. Nothing is
 * rounded, padded, trimmed or reordered.
 */

const THOUSANDS = /\B(?=(\d{3})+(?!\d))/g;

/** A plain decimal string: optional sign, digits, optional fractional part. */
const PLAIN_DECIMAL = /^-?\d+(\.\d+)?$/;

export function groupDigits(digits: string): string {
  return digits.replace(THOUSANDS, ",");
}

/**
 * Group the integer part of a decimal string.
 *
 * An amount that is not a plain decimal — a `Decimal` serialised in exponent
 * form such as `5E+7`, which Python will produce if it is ever constructed that
 * way — is returned VERBATIM rather than guessed at. Rendering it unformatted
 * is ugly; rendering it as a number that has been through an exponent parser is
 * a different figure, and only one of those two failures is recoverable by
 * looking at the screen.
 */
export function formatAmount(amount: string): string {
  if (!PLAIN_DECIMAL.test(amount)) return amount;
  const sign = amount.startsWith("-") ? "-" : "";
  const unsigned = sign === "" ? amount : amount.slice(1);
  const dot = unsigned.indexOf(".");
  const whole = dot === -1 ? unsigned : unsigned.slice(0, dot);
  const fraction = dot === -1 ? "" : unsigned.slice(dot);
  return `${sign}${groupDigits(whole)}${fraction}`;
}

/**
 * The currency travels with the amount, always. INV-11 exists because a bare
 * number invites a cross-currency comparison the type system refused to make.
 */
export function formatMoney(money: Money): string {
  return `${formatAmount(money.amount)} ${money.currency}`;
}

/**
 * Dates arrive ISO-8601 and stay ISO-8601. A locale re-format would turn
 * `2025-12-31` into either 12/31 or 31/12 depending on who opens the packet,
 * and an auditor reading a measurement date must not have to know which.
 */
export function formatDate(iso: string): string {
  return iso;
}
