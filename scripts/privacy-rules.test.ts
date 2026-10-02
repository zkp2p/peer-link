import { describe, expect, it } from "vitest";
import { ibanValid, luhn, scanFile } from "./privacy-rules";

/** Split literals so this file never matches the rules it tests. */
const j = (...parts: string[]) => parts.join("");
const fixture = "banks/us/mercury/fixtures/case.synthetic.json";
const json = (input: unknown) => JSON.stringify({ provenance: "synthetic", input }, null, 2);
const findings = (file: string, content: string | null, bytes = 0) =>
  scanFile(file, content, bytes).findings.join("\n");

describe("file types", () => {
  it.each([
    ".env",
    ".env.local",
    "app/.local/x.json",
    "capture.har",
    "session.saz",
    "trace.pcapng",
    "page.mhtml",
    "key.pem",
    "id.key",
    "cert.p12",
    "vault.kdbx",
    "cookies",
    "Cookies.sqlite",
    "statement.ofx",
    "export.csv",
    "history.xlsx",
  ])("rejects %s", (file) => expect(findings(file, "x")).toContain("raw capture"));
  it.each([
    "banks/us/mercury/screen.png",
    "banks/us/mercury/statement.pdf",
    "banks/us/mercury/page.html",
  ])("rejects %s", (file) => expect(findings(file, null)).toContain("never belong in banks"));
  it("accepts only the exact public trust anchor", () => {
    expect(findings("verification/trust/aws-nitro-root.pem", "tampered")).toContain("trust anchor");
    expect(findings("verification/trust/aws-nitro-root.pem", null)).toContain("trust anchor");
  });
  it("rejects files too large to scan", () =>
    expect(findings("docs/a.md", null, 6_000_000)).toContain("too large"));
  it("skips binary content outside banks", () => expect(findings("app/logo.png", null)).toBe(""));
});

describe("secrets anywhere in the repository", () => {
  it.each([
    [j("-----BEGIN ENCRYPTED PRIVATE", " KEY-----"), "private key"],
    [j("-----BEGIN PGP PRIVATE", " KEY BLOCK-----"), "private key"],
    [`ghp_${"a".repeat(36)}`, "GitHub token"],
    [j('{"Authorization"', ': "Basic abc"}'), "credential header"],
    [j('{"x-csrf-token"', ': "abc"}'), "credential header"],
    [j('{"name": "cookie"', ', "value": "a=b"}'), "HAR credential header"],
    ["Cookie: session=abc", "raw HTTP credential header"],
    ["authorization: Bearer abc", "raw HTTP credential header"],
    [`curl -H "Bearer ${"a".repeat(30)}"`, "bearer token"],
    [`eyJ${"a".repeat(12)}.${"b".repeat(12)}.${"c".repeat(12)}`, "JWT"],
    [j("AKIA", "ABCDEFGHIJKLMNOP"), "AWS access key"],
    [j("xoxb", "-1234567890-abc"), "Slack token"],
    [`sk_live_${"a".repeat(24)}`, "Stripe"],
    [`AIza${"a".repeat(35)}`, "Google API key"],
    [`sk-ant-${"a".repeat(40)}`, "model provider"],
    [`connect.sid=${"a".repeat(24)}`, "session cookie"],
  ])("finds %s", (content, rule) => expect(findings("docs/notes.md", content)).toContain(rule));
  it("reports the line and never the value", () => {
    const result = findings("docs/notes.md", j("line one\nAKIA", "ABCDEFGHIJKLMNOP"));
    expect(result).toBe("docs/notes.md:2: possible AWS access key");
  });
  it.each([
    "Authorization: <token>",
    "Cookie: $COOKIE",
    "Authorization: REDACTED",
    "Bearer <token>",
  ])("allows documented placeholder %s", (content) =>
    expect(findings("docs/notes.md", content)).toBe(""),
  );
});

describe("personal data in bank folders", () => {
  it.each([
    ["jane.doe@gmail.com", "email"],
    ["GB29NWBK60161331926819", "IBAN"],
    ["UA27 3052 9900 0002 6006 0160 7154 1", "IBAN"],
    ["4539 1488 0343 6467", "payment card"],
    ["4539-1488-0343-6467", "payment card"],
    ["123-45-6789", "social security"],
    ["https://bank.example/tx?access_token=abc", "credential-bearing URL"],
  ])("finds %s", (value, rule) =>
    expect(findings("banks/us/mercury/README.md", value)).toContain(rule),
  );
  it.each([
    "payer@example.com",
    "payer@bank.example",
    "payer@mail.test",
    "GB82WEST12345698765432",
    "UA213223130000026007233566001",
    "GB00WEST12345698765432",
    "4111111111111111",
    "4539148803436468",
    "1768478400000",
    "0000000000000000",
    "2026-01-15T12:00:00.000Z",
  ])("allows synthetic %s", (value) =>
    expect(findings("banks/us/mercury/README.md", value)).toBe(""),
  );
  it("does not apply bank PII rules outside banks/", () =>
    expect(findings("docs/a.md", "jane.doe@gmail.com 123-45-6789")).toBe(""));
});

describe("fixture-specific rules", () => {
  it("requires provenance and valid JSON", () => {
    expect(findings(fixture, JSON.stringify({ input: {} }))).toContain("provenance");
    expect(findings(fixture, "{bad")).toContain("invalid JSON");
  });
  it.each([
    [{ name: "Jane Realperson" }, "$.input.name"],
    [{ parties: [{ displayName: "Jane" }] }, "$.input.parties[0].displayName"],
    [{ beneficiary: "Jane" }, "$.input.beneficiary"],
  ])("flags real-looking names %j", (input, path) =>
    expect(findings(fixture, json(input))).toContain(`${path}: possible real name`),
  );
  it.each([
    { name: "Synthetic account" },
    { counterpartyName: "Example Payee" },
    { bankName: "Mercury" },
    { holder: { id: "x" } },
    { name: "" },
  ])("allows marked names and non-person fields %j", (input) =>
    expect(findings(fixture, json(input))).toBe(""),
  );
  it("flags real-looking phone numbers but allows obvious fictional ones", () => {
    expect(findings(fixture, json({ phone: "+380 67 123 4567" }))).toContain("phone number");
    expect(findings(fixture, json({ phone: "+380670000001" }))).toBe("");
  });
  it("warns about unexplained long numeric identifiers without failing", () => {
    const result = scanFile(
      fixture,
      json({ account: "40817810", n: 12345678, ok: "000000000001", time: 1768478400 }),
    );
    expect(result.findings).toEqual([]);
    expect(result.warnings).toEqual([
      `${fixture}:$.input.account: long numeric identifier; confirm it is invented (prefer runs of zeros)`,
      `${fixture}:$.input.n: long numeric identifier; confirm it is invented (prefer runs of zeros)`,
    ]);
  });
});

it("implements Luhn and IBAN mod-97 checks", () => {
  expect(luhn("4111111111111111")).toBe(true);
  expect(luhn("4111111111111112")).toBe(false);
  expect(ibanValid("GB82WEST12345698765432")).toBe(true);
  expect(ibanValid("GB00WEST12345698765432")).toBe(false);
});
