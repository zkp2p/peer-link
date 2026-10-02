/**
 * Pre-publication privacy heuristics. They catch common leaks; they do not certify redaction.
 * Findings name the file, line or JSON path and rule, never the matching value.
 */
import { createHash } from "node:crypto";

export const TRUST_ANCHOR = "verification/trust/aws-nitro-root.pem";
const TRUST_ANCHOR_SHA256 = "6eb9688305e4bbca67f44b59c29a0661ae930f09b5945b5d1d9ae01125c8d6c0";
export const MAX_SCAN_BYTES = 5_000_000;

const RAW_CAPTURE =
  /(^|\/)(\.env[^/]*|\.local)(\/|$)|\.(har|saz|pcap|pcapng|mhtml?|pem|key|p12|pfx|jks|keystore|kdbx|sqlite3?|db|ofx|qfx|qif|mt940|sta|csv|xlsx?)$|(^|\/)cookies(\.[a-z]+)?$/i;
const BANK_MEDIA =
  /^banks\/.*\.(png|jpe?g|gif|webp|heic|bmp|tiff?|pdf|docx?|zip|gz|7z|txt|html?)$/i;

const SECRET_RULES: [string, RegExp][] = [
  ["private key", /-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----/],
  ["GitHub token", /\b(?:gh[pousr]_[a-zA-Z0-9]{30,}|github_pat_[a-zA-Z0-9_]{30,})\b/],
  [
    "credential header",
    /"(?:cookie|set-cookie|authorization|proxy-authorization|x-csrf-token|x-csrf-protect|x-xsrf-token|x-api-key|x-auth-token|x-session-token)"\s*:\s*"[^"\n]+"/i,
  ],
  [
    "HAR credential header",
    /"name"\s*:\s*"(?:cookie|set-cookie|authorization|x-csrf-token|x-csrf-protect|x-xsrf-token|x-api-key)"\s*,\s*"value"\s*:\s*"[^"\n]+"/i,
  ],
  [
    "raw HTTP credential header",
    /^\s*(?:cookie|set-cookie|authorization|proxy-authorization|x-csrf-token|x-api-key)\s*:\s*(?![<$`{]|\.\.\.|REDACTED)[^\s].*$/im,
  ],
  ["bearer token", /\bBearer\s+(?![<$`{])[A-Za-z0-9\-._~+/]{20,}=*/],
  ["JWT", /\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}/],
  ["AWS access key", /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/],
  ["Slack token", /\bxox[abprs]-[A-Za-z0-9-]{10,}/],
  ["Stripe live key", /\b(?:sk|rk)_live_[A-Za-z0-9]{16,}/],
  ["Google API key", /\bAIza[0-9A-Za-z_-]{35}\b/],
  ["model provider API key", /\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}/],
  [
    "session cookie value",
    /\b(?:session|sessionid|sid|connect\.sid|__Secure-[A-Za-z-]+|__Host-[A-Za-z-]+)=[A-Za-z0-9%._-]{16,}/,
  ],
];

const BANK_RULES: [string, RegExp][] = [
  [
    "credential-bearing URL",
    /https?:\/\/[^\s"']+[?&#](?:token|access_token|id_token|refresh_token|key|api_key|apikey|session|sessionid|code|sig|signature|auth|password|X-Amz-Signature|X-Amz-Credential)=/i,
  ],
  ["US social security number", /\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b/],
];

const RESERVED_EMAIL_DOMAIN = /(^|\.)(example\.(com|net|org)|example|test|invalid|localhost)$/i;
/** Published registry/documentation IBANs and card-network test numbers are not personal. */
const EXAMPLE_IBANS = new Set([
  "GB82WEST12345698765432",
  "GB33BUKB20201555555555",
  "DE89370400440532013000",
  "FR1420041010050500013M02606",
  "NL91ABNA0417164300",
  "ES9121000418450200051332",
  "IT60X0542811101000000123456",
  "BE68539007547034",
  "CH9300762011623852957",
  "AT611904300234573201",
  "PL61109010140000071219812874",
  "LT121000011101001000",
  "UA213223130000026007233566001",
  "GE29NB0000000101904917",
  "TR330006100519786457841326",
  "AE070331234567890123456",
  "SA0380000000608010167519",
  "KZ86125KZT5004100100",
]);
const TEST_PANS = new Set([
  "4111111111111111",
  "4242424242424242",
  "4000056655665556",
  "4012888888881881",
  "4222222222222",
  "5555555555554444",
  "5200828282828210",
  "5105105105105100",
  "2223003122003222",
  "378282246310005",
  "371449635398431",
  "6011111111111117",
  "6011000990139424",
  "3056930009020004",
  "36227206271667",
  "3566002020360505",
  "6200000000000005",
]);
const SYNTHETIC_MARKER =
  /synthetic|example|test|fictional|sample|redacted|placeholder|dummy|demo|fake|invented|anonymous/i;
const PERSON_NAME_KEY =
  /^(?!bank|institution|currency|file|host|product|method|status|type|kind|event|field)[a-z_]*name$|^(holder|beneficiary|counterparty|recipient|sender|payer|payee|owner|customer)$/i;

export function luhn(digits: string) {
  let sum = 0;
  for (let i = 0; i < digits.length; i++) {
    let d = Number(digits[digits.length - 1 - i]);
    if (i % 2) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    sum += d;
  }
  return sum % 10 === 0;
}

export function ibanValid(iban: string) {
  const rearranged = iban.slice(4) + iban.slice(0, 4);
  let remainder = 0;
  for (const ch of rearranged) {
    const value = /\d/.test(ch) ? ch : String(ch.charCodeAt(0) - 55);
    for (const digit of value) remainder = (remainder * 10 + Number(digit)) % 97;
  }
  return remainder === 1;
}

const lineOf = (content: string, index: number) => content.slice(0, index).split("\n").length;

function walk(
  value: unknown,
  path: string,
  visit: (path: string, key: string, v: unknown) => void,
) {
  if (Array.isArray(value)) for (const [i, v] of value.entries()) walk(v, `${path}[${i}]`, visit);
  else if (value && typeof value === "object")
    for (const [k, v] of Object.entries(value)) {
      visit(`${path}.${k}`, k, v);
      walk(v, `${path}.${k}`, visit);
    }
}

export type Scan = { findings: string[]; warnings: string[] };

/** `content` is null for binary or oversized files; only path rules apply then. */
export function scanFile(file: string, content: string | null, bytes = 0): Scan {
  const findings: string[] = [];
  const warnings: string[] = [];
  const find = (rule: string, where?: string) =>
    findings.push(`${file}${where ? `:${where}` : ""}: possible ${rule}`);
  if (file === TRUST_ANCHOR) {
    if (
      content === null ||
      createHash("sha256").update(content).digest("hex") !== TRUST_ANCHOR_SHA256
    )
      findings.push(`${file}: unexpected public trust anchor contents`);
    return { findings, warnings };
  }
  if (RAW_CAPTURE.test(file)) {
    findings.push(`${file}: raw capture, statement export or credential file type`);
    return { findings, warnings };
  }
  if (BANK_MEDIA.test(file)) {
    findings.push(`${file}: screenshots, statements and documents never belong in banks/`);
    return { findings, warnings };
  }
  if (bytes > MAX_SCAN_BYTES) {
    findings.push(`${file}: too large to scan (${bytes} bytes); do not commit large captures`);
    return { findings, warnings };
  }
  if (content === null) return { findings, warnings };
  for (const [rule, pattern] of SECRET_RULES) {
    const match = pattern.exec(content);
    if (match) find(rule, `${lineOf(content, match.index)}`);
  }
  if (!file.startsWith("banks/")) return { findings, warnings };
  for (const [rule, pattern] of BANK_RULES) {
    const match = pattern.exec(content);
    if (match) find(rule, `${lineOf(content, match.index)}`);
  }
  for (const match of content.matchAll(/[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})/g))
    if (!RESERVED_EMAIL_DOMAIN.test(match[1]))
      find(
        "email address (use example.com, .example or .test domains)",
        `${lineOf(content, match.index)}`,
      );
  for (const match of content.matchAll(/\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b/g)) {
    const iban = match[0].replaceAll(" ", "");
    if (!EXAMPLE_IBANS.has(iban) && ibanValid(iban))
      find(
        "IBAN with a valid checksum (use a registry example IBAN or check digits 00)",
        `${lineOf(content, match.index)}`,
      );
  }
  for (const match of content.matchAll(/(?<![\dA-Za-z])\d(?:[ -]?\d){12,18}(?![\dA-Za-z])/g)) {
    const digits = match[0].replace(/[ -]/g, "");
    if (
      /^[2-6]/.test(digits) &&
      !/^(\d)\1+$/.test(digits) &&
      !TEST_PANS.has(digits) &&
      luhn(digits)
    )
      find(
        "payment card number (use a network test number or break the Luhn checksum)",
        `${lineOf(content, match.index)}`,
      );
  }
  if (/^banks\/[^/]+\/[^/]+\/fixtures\/[^/]+\.json$/.test(file)) {
    for (const match of content.matchAll(/\+\d{1,3}[ -]?\d(?:[ -]?\d){6,13}\b/g))
      if (!match[0].replace(/\D/g, "").includes("0000"))
        find(
          "phone number (use an obviously fictional number containing 0000)",
          `${lineOf(content, match.index)}`,
        );
    let data: unknown;
    try {
      data = JSON.parse(content);
    } catch {
      findings.push(`${file}: invalid JSON (contents not shown)`);
      return { findings, warnings };
    }
    if (
      !data ||
      typeof data !== "object" ||
      !["synthetic", "sanitized"].includes((data as { provenance?: unknown }).provenance as string)
    )
      findings.push(`${file}: missing fixture provenance (synthetic or sanitized)`);
    walk(data, "$", (path, key, value) => {
      if (
        typeof value === "string" &&
        value.trim() &&
        PERSON_NAME_KEY.test(key) &&
        !SYNTHETIC_MARKER.test(value)
      )
        findings.push(
          `${file}:${path}: possible real name; invented names must contain a marker such as "Synthetic" or "Example"`,
        );
      const digits =
        typeof value === "number" && Number.isInteger(value) ? String(Math.abs(value)) : value;
      if (
        typeof digits === "string" &&
        /^\d{8,}$/.test(digits) &&
        !digits.includes("0000") &&
        !/^(\d)\1+$/.test(digits) &&
        !/^1[5-9]\d{8}(\d{3})?$/.test(digits)
      )
        warnings.push(
          `${file}:${path}: long numeric identifier; confirm it is invented (prefer runs of zeros)`,
        );
    });
  }
  return { findings, warnings };
}
