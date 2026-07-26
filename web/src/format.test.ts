import { describe, expect, it } from "vitest";

import { formatAmount, formatDate, formatMoney, groupDigits } from "./format";

/**
 * The property under test is not "it looks nice". It is that the digits which
 * arrive are the digits which leave. A formatter that rounds is indistinguishable
 * from a correct one on small numbers, which is why the cases below are chosen
 * to break a `parseFloat` implementation rather than to exercise the happy path.
 */

describe("formatAmount", () => {
  it("groups the integer part", () => {
    expect(formatAmount("5000000")).toBe("5,000,000");
    expect(formatAmount("999")).toBe("999");
    expect(formatAmount("1000")).toBe("1,000");
  });

  it("keeps the fractional part exactly as it arrived", () => {
    expect(formatAmount("1234.5678")).toBe("1,234.5678");
    expect(formatAmount("0.0001")).toBe("0.0001");
    expect(formatAmount("1109.9999")).toBe("1,109.9999");
  });

  it("carries the sign", () => {
    expect(formatAmount("-1234567.25")).toBe("-1,234,567.25");
  });

  it("survives amounts a double cannot represent", () => {
    // 9007199254740993 is 2^53 + 1: Number() rounds it down to 2^53, and any
    // formatter that touches a float loses the final digit here.
    expect(formatAmount("9007199254740993")).toBe("9,007,199,254,740,993");
    expect(formatAmount("0.1000000000000000055511151231")).toBe("0.1000000000000000055511151231");
  });

  it("returns an amount it does not recognise verbatim rather than guessing", () => {
    // 1234567E+2 rather than 5E+7: both are exponent form, but only this one
    // has a run of digits long enough for the grouping regex to touch. Deleting
    // the PLAIN_DECIMAL guard turns it into "1,234,567E+2" — a mantissa dressed
    // as a total. With 5E+7 and NaN alone, grouping was a no-op either way and
    // the guard could be deleted without a single case going red.
    expect(formatAmount("1234567E+2")).toBe("1234567E+2");
    expect(formatAmount("-9876543.21E-4")).toBe("-9876543.21E-4");
    expect(formatAmount("5E+7")).toBe("5E+7");
    expect(formatAmount("NaN")).toBe("NaN");
  });

  it("groups a bare digit string", () => {
    expect(groupDigits("1234567")).toBe("1,234,567");
  });
});

describe("formatMoney", () => {
  it("never renders an amount without its currency", () => {
    expect(formatMoney({ amount: "5000000", currency: "USD" })).toBe("5,000,000 USD");
    expect(formatMoney({ amount: "950000", currency: "EUR" })).toBe("950,000 EUR");
  });
});

describe("formatDate", () => {
  it("leaves ISO dates alone so 12/31 and 31/12 cannot both mean this", () => {
    expect(formatDate("2025-12-31")).toBe("2025-12-31");
  });
});
