/**
 * Pure contribution rules shared by `npm run validate`, the adapter contract test and the
 * scaffolding script. Nothing here reads the network, credentials or banking data.
 *
 * Error messages are written for coding agents: each says what is wrong, where, and how to fix
 * it, and none of them echo file contents (a failed check must not become a second leak).
 */
import ts from "typescript";

export const HANDLE = /^[a-z\d](?:[a-z\d-]{0,37}[a-z\d])?$/i;
export const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const IDENTIFIER = /^[A-Za-z_$][\w$]*$/;
const SHA = /^[a-f\d]{40}$/;
const UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/;
const PLACEHOLDER = /\bTODO\b/;
const regionNames = new Intl.DisplayNames(["en"], { type: "region", fallback: "none" });

export const OUTCOMES = ["supported", "insufficient_evidence", "unsupported"] as const;
export const SUPPORTED_EXPECTED_REQUIRED = [
  "payerId",
  "payeeId",
  "amountMinor",
  "currency",
  "status",
  "timestamp",
] as const;
export const SUPPORTED_EXPECTED_OPTIONAL = [
  "payerScheme",
  "payeeScheme",
  "currencyExponent",
  "direction",
  "timestampMeaning",
] as const;
export const MAX_TRANSFORMER_BYTES = 65536;

/** A bank folder is `banks/<iso-3166 alpha-2, lowercase>/<kebab-case slug>/`. */
export type BankPath = { bank: string; id: string; country: string; rest: string };

/** Classify a tracked path below `banks/`; returns an error string for disallowed paths. */
export function classifyBankPath(file: string): BankPath | { error: string } | null {
  if (!file.startsWith("banks/")) return null;
  if (file === "banks/adapter-contract.test.ts") return null;
  const parts = file.split("/");
  if (parts.length < 4)
    return {
      error: `${file}: files must live inside a bank folder banks/<country>/<bank>/ (see skills/contribute-bank/SKILL.md)`,
    };
  const [, country, slug] = parts;
  const region = /^[a-z]{2}$/.test(country) ? regionNames.of(country.toUpperCase()) : undefined;
  if (!region || region === "Unknown Region")
    return {
      error: `banks/${country}/: "${country}" is not a lowercase ISO 3166-1 alpha-2 country code (for example us, ua, vn)`,
    };
  if (!SLUG.test(slug) || slug.length > 40)
    return {
      error: `banks/${country}/${slug}/: bank folder names must be lowercase kebab-case ([a-z0-9-], at most 40 characters)`,
    };
  const bank = parts.slice(0, 3).join("/");
  const rest = parts.slice(3).join("/");
  const allowed =
    /^(README\.md|manifest\.json|transformer\.js|[a-z0-9-]+\.test\.ts)$/.test(rest) ||
    /^fixtures\/[a-z0-9]+(?:-[a-z0-9]+)*\.(synthetic|sanitized)\.json$/.test(rest) ||
    /^reports\/\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.json$/.test(rest);
  if (/^(transformer|index|adapter|parser)\.(ts|mjs|cjs|tsx)$/.test(rest))
    return {
      error: `${file}: name the adapter transformer.js (plain JavaScript with JSDoc types, checked by TypeScript). The verifier bundles exactly one self-contained transformer.js.`,
    };
  if (/^fixtures\/[^/]+\.json$/.test(rest) && !/\.(synthetic|sanitized)\.json$/.test(rest))
    return {
      error: `${file}: name fixtures fixtures/<case>.synthetic.json or fixtures/<case>.sanitized.json (lowercase kebab-case case name)`,
    };
  if (!allowed)
    return {
      error: `${file}: unexpected file. A bank folder may contain only README.md, manifest.json, transformer.js (one self-contained file), <name>.test.ts, fixtures/<case>.synthetic.json or fixtures/<case>.sanitized.json, and reports/YYYY-MM-DD-<github-handle>.json. Screenshots, HAR files, PDFs and helper modules are not accepted.`,
    };
  return { bank, id: `${country}/${slug}`, country, rest };
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v);
const nonEmptyString = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;
const hasPlaceholder = (v: unknown): boolean =>
  typeof v === "string"
    ? PLACEHOLDER.test(v)
    : Array.isArray(v)
      ? v.some(hasPlaceholder)
      : isRecord(v) && Object.values(v).some(hasPlaceholder);

const MANIFEST_REQUIRED = [
  "schemaVersion",
  "id",
  "name",
  "country",
  "status",
  "version",
  "surface",
  "capability",
  "entrypoint",
  "maintainers",
  "currencies",
  "unsupported",
] as const;
const MANIFEST_OPTIONAL = ["fixtureProvenance", "logo"] as const;

/** Validate manifest.json. `logoExists` resolves `/logos/...` against app/public. */
export function validateManifest(
  file: string,
  data: unknown,
  bank: BankPath,
  logoExists: (path: string) => boolean,
): string[] {
  const errors: string[] = [];
  const err = (message: string) => errors.push(`${file}: ${message}`);
  if (!isRecord(data)) return [`${file}: manifest must be a JSON object`];
  for (const key of Object.keys(data))
    if (![...MANIFEST_REQUIRED, ...MANIFEST_OPTIONAL].includes(key as never))
      err(
        `unknown field "${key}". Allowed: ${[...MANIFEST_REQUIRED, ...MANIFEST_OPTIONAL].join(", ")}`,
      );
  for (const key of MANIFEST_REQUIRED) if (!(key in data)) err(`missing required field "${key}"`);
  const present = (key: string) => key in data;
  if (present("schemaVersion") && data.schemaVersion !== "1") err('schemaVersion must be "1"');
  if (present("id") && data.id !== bank.id)
    err(`id must be "${bank.id}" (the folder path below banks/)`);
  if (present("name") && !nonEmptyString(data.name)) err("name must be the bank's public name");
  if (present("country") && data.country !== bank.country.toUpperCase())
    err(`country must be "${bank.country.toUpperCase()}" (uppercase form of the folder code)`);
  if (present("status") && data.status !== "experimental") err('status must be "experimental"');
  if (
    present("version") &&
    (typeof data.version !== "string" || !/^\d+\.\d+\.\d+$/.test(data.version))
  )
    err('version must be semantic, for example "0.1.0"; bump it when behavior changes');
  if (present("surface") && (typeof data.surface !== "string" || !SLUG.test(data.surface)))
    err('surface must be a kebab-case name of the bank surface, for example "web-history"');
  if (present("capability") && (!nonEmptyString(data.capability) || data.capability.length > 200))
    err("capability must be one sentence (at most 200 characters) naming the payment type");
  if (
    present("entrypoint") &&
    (typeof data.entrypoint !== "string" || !IDENTIFIER.test(data.entrypoint))
  )
    err('entrypoint must name the exported function in transformer.js, e.g. "interpretMonobank"');
  if (
    present("maintainers") &&
    (!Array.isArray(data.maintainers) ||
      !data.maintainers.length ||
      !data.maintainers.every((h) => typeof h === "string" && HANDLE.test(h)))
  )
    err("maintainers must be a non-empty array of public GitHub handles");
  if (
    present("currencies") &&
    (!Array.isArray(data.currencies) ||
      !data.currencies.length ||
      !data.currencies.every((c) => typeof c === "string" && /^[A-Z]{3}$/.test(c)) ||
      new Set(data.currencies).size !== data.currencies.length)
  )
    err('currencies must be a non-empty array of unique ISO 4217 codes, e.g. ["UAH"]');
  if (
    present("unsupported") &&
    (!Array.isArray(data.unsupported) ||
      !data.unsupported.length ||
      !data.unsupported.every(nonEmptyString))
  )
    err("unsupported must list at least one payment type or claim this adapter does not cover");
  if (
    "fixtureProvenance" in data &&
    !["synthetic", "sanitized", "mixed"].includes(data.fixtureProvenance as string)
  )
    err('fixtureProvenance must be "synthetic", "sanitized" or "mixed"');
  if ("logo" in data) {
    if (
      typeof data.logo !== "string" ||
      !/^\/logos\/[a-z0-9-]+\.(svg|png|jpg|jpeg|webp)$/.test(data.logo)
    )
      err('logo must be a local path such as "/logos/monobank.png"');
    else if (!logoExists(data.logo))
      err(`logo ${data.logo} does not exist in app/public/logos/ (see AGENTS.md logo rules)`);
  }
  if (hasPlaceholder(data)) err("replace every TODO placeholder");
  return errors;
}

/** Validate fixtures/<case>.<provenance>.json. */
export function validateFixture(file: string, data: unknown): string[] {
  const errors: string[] = [];
  const err = (message: string) => errors.push(`${file}: ${message}`);
  if (!isRecord(data)) return [`${file}: fixture must be a JSON object`];
  const allowed = ["provenance", "description", "input", "transactionId", "expected"];
  for (const key of Object.keys(data))
    if (!allowed.includes(key)) err(`unknown field "${key}". Allowed: ${allowed.join(", ")}`);
  const suffix = /\.(synthetic|sanitized)\.json$/.exec(file)?.[1];
  if (data.provenance !== suffix)
    err(`provenance must be "${suffix}" to match the file name (synthetic or sanitized)`);
  if (!nonEmptyString(data.description))
    err("description must say what was invented or how values were sanitized");
  else if (hasPlaceholder(data.description))
    err("replace the TODO in description with what was invented or how values were sanitized");
  if (!("input" in data)) err('missing "input" (the bank response shape the adapter receives)');
  if (typeof data.transactionId !== "string")
    err('transactionId must be a string (the selected transaction; "" for a selection test)');
  const expected = data.expected;
  if (!isRecord(expected) || !OUTCOMES.includes(expected.outcome as never)) {
    err(`expected.outcome must be one of ${OUTCOMES.join(", ")}`);
    return errors;
  }
  if (expected.outcome === "supported") {
    for (const key of Object.keys(expected))
      if (
        key !== "outcome" &&
        ![...SUPPORTED_EXPECTED_REQUIRED, ...SUPPORTED_EXPECTED_OPTIONAL].includes(key as never)
      )
        err(`unknown expected field "${key}"`);
    for (const key of SUPPORTED_EXPECTED_REQUIRED)
      if (typeof expected[key] !== "string")
        err(`expected.${key} is required for a supported fixture and must be a string`);
    if (typeof expected.amountMinor === "string" && !/^[1-9]\d*$/.test(expected.amountMinor))
      err("expected.amountMinor must be positive integer minor units without leading zeros");
    if (typeof expected.currency === "string" && !/^[A-Z]{3}$/.test(expected.currency))
      err("expected.currency must be an ISO 4217 code");
    if (typeof expected.timestamp === "string" && !UTC.test(expected.timestamp))
      err("expected.timestamp must be an explicit UTC ISO-8601 string ending in Z");
    if (
      "currencyExponent" in expected &&
      (!Number.isInteger(expected.currencyExponent) ||
        (expected.currencyExponent as number) < 0 ||
        (expected.currencyExponent as number) > 6)
    )
      err("expected.currencyExponent must be an integer from 0 to 6");
    if ("direction" in expected && !["incoming", "outgoing"].includes(expected.direction as never))
      err('expected.direction must be "incoming" or "outgoing"');
  } else {
    for (const key of Object.keys(expected))
      if (!["outcome", "reason"].includes(key))
        err(`a ${expected.outcome} fixture may only set expected.outcome and expected.reason`);
    if ("reason" in expected && !nonEmptyString(expected.reason))
      err("expected.reason must be a non-empty string when present");
  }
  return errors;
}

const REPORT_FIELDS = [
  "schemaVersion",
  "provider",
  "adapterRevision",
  "harnessRevision",
  "testedAt",
  "reporter",
  "surface",
  "capability",
  "outcome",
  "evidenceClass",
  "fixtureRefs",
  "limitations",
  "summary",
] as const;

export type ReportContext = {
  manifestSurface?: string;
  fixtureExists: (ref: string) => boolean;
  /** "ok" when the commit is an ancestor of HEAD and contains the bank's manifest. */
  revision: (sha: string) => "ok" | "missing-commit" | "not-ancestor" | "missing-bank";
  now: number;
};

/** Validate reports/YYYY-MM-DD-<handle>.json against docs/evidence.md. */
export function validateReport(
  file: string,
  data: unknown,
  bank: BankPath,
  ctx: ReportContext,
): string[] {
  const errors: string[] = [];
  const err = (message: string) => errors.push(`${file}: ${message}`);
  if (!isRecord(data)) return [`${file}: report must be a JSON object`];
  for (const key of Object.keys(data))
    if (!REPORT_FIELDS.includes(key as never))
      err(`unexpected field "${key}" (see docs/evidence.md)`);
  for (const key of REPORT_FIELDS)
    if (!["fixtureRefs", "limitations"].includes(key) && !nonEmptyString(data[key]))
      err(`missing ${key}`);
  if (data.schemaVersion !== "1") err('schemaVersion must be "1"');
  if (data.provider !== bank.id) err(`provider must be "${bank.id}"`);
  if (typeof data.reporter === "string" && !HANDLE.test(data.reporter))
    err("reporter must be a public GitHub handle");
  if (
    typeof data.reporter === "string" &&
    !file.toLowerCase().endsWith(`-${data.reporter.toLowerCase()}.json`) &&
    !file.toLowerCase().includes(`-${data.reporter.toLowerCase()}-`)
  )
    err("file name must be reports/YYYY-MM-DD-<reporter>.json (reporter handle in lowercase)");
  if (!["pass", "fail", "partial", "blocked", "not-tested"].includes(data.outcome as never))
    err("outcome must be pass, fail, partial, blocked or not-tested");
  if (!["contributor-live", "fixture-only", "reviewer-live"].includes(data.evidenceClass as never))
    err("evidenceClass must be contributor-live, fixture-only or reviewer-live");
  if (
    typeof data.testedAt !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/.test(data.testedAt) ||
    !Number.isFinite(Date.parse(data.testedAt)) ||
    Date.parse(data.testedAt) > ctx.now + 300000
  )
    err("testedAt must be a past UTC timestamp such as 2026-10-02T12:00:00Z");
  if (typeof data.capability === "string" && !SLUG.test(data.capability))
    err('capability must be a kebab-case slug, e.g. "outgoing-domestic-usd-wire"');
  if (ctx.manifestSurface !== undefined && data.surface !== ctx.manifestSurface)
    err(`surface must equal the manifest surface "${ctx.manifestSurface}"`);
  for (const key of ["adapterRevision", "harnessRevision"]) {
    const sha = data[key];
    if (typeof sha !== "string" || !SHA.test(sha)) {
      err(`${key} must be a full 40-character lowercase commit SHA`);
      continue;
    }
    const state = ctx.revision(sha);
    if (state === "missing-commit")
      err(
        `${key} is not in this repository's history. Reports must reference a commit that is already on main (see the two-PR flow in docs/evidence.md)`,
      );
    else if (state === "not-ancestor")
      err(
        `${key} is not in this branch's history. Do not rebase or squash after writing a report; merge main instead, or rerun the live check and cite the new commit`,
      );
    else if (state === "missing-bank" && key === "adapterRevision")
      err(`adapterRevision does not contain ${bank.bank}/ at that commit`);
  }
  if (
    !Array.isArray(data.limitations) ||
    !data.limitations.length ||
    !data.limitations.every(nonEmptyString)
  )
    err("limitations must be a non-empty array of strings");
  if (!Array.isArray(data.fixtureRefs)) err("fixtureRefs must be an array");
  else
    for (const ref of data.fixtureRefs)
      if (
        typeof ref !== "string" ||
        !/^fixtures\/[a-z0-9]+(?:-[a-z0-9]+)*\.(synthetic|sanitized)\.json$/.test(ref) ||
        !ctx.fixtureExists(ref)
      )
        err("each fixtureRefs entry must name an existing fixtures/<case>.<provenance>.json");
  if (typeof data.summary === "string" && data.summary.length > 2000)
    err("summary must be at most 2000 characters; never paste transcripts");
  if (hasPlaceholder(data)) err("replace every TODO placeholder");
  return errors;
}

const FORBIDDEN_GLOBALS = new Set([
  "fetch",
  "XMLHttpRequest",
  "WebSocket",
  "EventSource",
  "navigator",
  "require",
  "module",
  "exports",
  "process",
  "globalThis",
  "global",
  "window",
  "self",
  "document",
  "localStorage",
  "sessionStorage",
  "indexedDB",
  "caches",
  "eval",
  "Function",
  "setTimeout",
  "setInterval",
  "setImmediate",
  "queueMicrotask",
  "importScripts",
  "postMessage",
  "Worker",
  "WebAssembly",
  "SharedArrayBuffer",
  "Atomics",
  "crypto",
  "performance",
  "console",
  "Deno",
  "Bun",
]);
/** Local-time and locale methods change results with the runner's timezone or language. */
const NONDETERMINISTIC_METHODS = new Set([
  "getFullYear",
  "getMonth",
  "getDate",
  "getDay",
  "getHours",
  "getMinutes",
  "getSeconds",
  "getMilliseconds",
  "getTimezoneOffset",
  "setFullYear",
  "setMonth",
  "setDate",
  "setHours",
  "setMinutes",
  "setSeconds",
  "setMilliseconds",
  "toLocaleString",
  "toLocaleDateString",
  "toLocaleTimeString",
  "toDateString",
  "toTimeString",
  "localeCompare",
]);

function isReference(node: ts.Identifier): boolean {
  const parent = node.parent;
  if (ts.isPropertyAccessExpression(parent) && parent.name === node) return false;
  if (
    (ts.isPropertyAssignment(parent) ||
      ts.isMethodDeclaration(parent) ||
      ts.isPropertyDeclaration(parent) ||
      ts.isGetAccessorDeclaration(parent) ||
      ts.isSetAccessorDeclaration(parent)) &&
    parent.name === node
  )
    return false;
  if (ts.isBindingElement(parent) && parent.propertyName === node) return false;
  if (ts.isJSDoc(parent) || ts.isJSDocTypeExpression(parent)) return false;
  return true;
}

/**
 * Static guard for honest mistakes, not a sandbox. Hostile code can evade static checks; the
 * real boundaries are credential-free CI, human review and the verifier's Wasm sandbox.
 */
export function checkTransformerSource(file: string, source: string, entrypoint: unknown) {
  const problems = new Set<string>();
  const add = (message: string) => problems.add(`${file}: ${message}`);
  if (Buffer.byteLength(source) > MAX_TRANSFORMER_BYTES)
    add(`transformer.js must be at most ${MAX_TRANSFORMER_BYTES} bytes (verifier build limit)`);
  if (PLACEHOLDER.test(source)) add("replace every TODO placeholder");
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.ES2022, true, ts.ScriptKind.JS);
  const diagnostics = (sf as unknown as { parseDiagnostics?: unknown[] }).parseDiagnostics;
  if (diagnostics?.length) add("JavaScript does not parse");
  let exported = false;
  const visit = (node: ts.Node) => {
    if (ts.isImportDeclaration(node) || ts.isImportEqualsDeclaration(node))
      add("imports are not allowed: keep the adapter one self-contained file");
    else if (ts.isExportDeclaration(node) && node.moduleSpecifier)
      add("re-exports from other modules are not allowed");
    else if (ts.isExportAssignment(node)) add("use a named export for the entrypoint");
    else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword)
      add("dynamic import() is not allowed");
    else if (ts.isMetaProperty(node)) add("import.meta/new.target are not allowed");
    else if (ts.isAwaitExpression(node)) add("await is not allowed: interpretation is synchronous");
    else if (ts.isIdentifier(node) && FORBIDDEN_GLOBALS.has(node.text) && isReference(node))
      add(`"${node.text}" is not allowed: adapters are pure (no network, I/O, timers or logging)`);
    else if (ts.isPropertyAccessExpression(node)) {
      const owner = node.expression.getText(sf);
      const name = node.name.text;
      if ((owner === "Math" && name === "random") || (owner === "Date" && name === "now"))
        add(`${owner}.${name} is nondeterministic`);
      if (NONDETERMINISTIC_METHODS.has(name))
        add(`.${name}() depends on the runner's timezone or locale; use UTC/ISO methods`);
    } else if (ts.isNewExpression(node) && node.expression.getText(sf) === "Date") {
      const count = node.arguments?.length ?? 0;
      if (count === 0) add("new Date() reads the clock; parse a timestamp from the evidence");
      if (count > 1) add("new Date(y, m, ...) uses local time; use Date.UTC or ISO strings");
    } else if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === "Date"
    )
      add("Date() reads the clock");
    if (
      (ts.isFunctionDeclaration(node) ||
        ts.isFunctionExpression(node) ||
        ts.isArrowFunction(node)) &&
      node.modifiers?.some((m) => m.kind === ts.SyntaxKind.AsyncKeyword)
    )
      add("async functions are not allowed: interpretation is synchronous");
    if (
      ts.isFunctionDeclaration(node) &&
      node.modifiers?.some((m) => m.kind === ts.SyntaxKind.DefaultKeyword)
    )
      add("use a named export for the entrypoint, not export default");
    else if (
      ts.isFunctionDeclaration(node) &&
      node.name?.text === entrypoint &&
      node.modifiers?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword)
    )
      exported = true;
    if (
      ts.isVariableStatement(node) &&
      node.modifiers?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword) &&
      node.declarationList.declarations.some(
        (d) => ts.isIdentifier(d.name) && d.name.text === entrypoint,
      )
    )
      exported = true;
    ts.forEachChild(node, visit);
  };
  visit(sf);
  if (typeof entrypoint === "string" && !exported)
    add(`must export function ${entrypoint} (the manifest entrypoint)`);
  return [...problems];
}

export const README_HEADINGS = ["Semantics", "Local acquisition"] as const;

/** Adapter READMEs document semantics and contributor-local acquisition. */
export function checkReadme(file: string, markdown: string): string[] {
  const errors: string[] = [];
  for (const heading of README_HEADINGS)
    if (!new RegExp(`^##\\s+${heading}\\s*$`, "mi").test(markdown))
      errors.push(`${file}: missing section "## ${heading}" (see banks/us/mercury/README.md)`);
  if (PLACEHOLDER.test(markdown)) errors.push(`${file}: replace every TODO placeholder`);
  return errors;
}

/** Parse JSON without echoing file contents; V8 syntax errors quote the offending text. */
export function parseJson(file: string, text: string): { value?: unknown; error?: string } {
  try {
    return { value: JSON.parse(text) };
  } catch {
    return { error: `${file}: invalid JSON (contents not shown); run it through a JSON linter` };
  }
}

/**
 * Where files may live. New top-level files, unknown directories and scripts in content
 * folders fail. Maintainers extend this list in a reviewed change when the layout grows.
 */
export const REPOSITORY_LAYOUT: RegExp[] = [
  /^(\.dockerignore|\.gitignore|\.npmrc|\.vercelignore|AGENTS\.md|CLAUDE\.md|CONTRIBUTING\.md|LICENSE|README\.md|SECURITY\.md|biome\.json|package-lock\.json|package\.json|tsconfig\.json|vercel\.json|vitest\.config\.ts)$/,
  /^\.github\/(CODEOWNERS|FUNDING\.yml|pull_request_template\.md|ISSUE_TEMPLATE\/[a-z0-9-]+\.(md|yml)|workflows\/[a-z0-9-]+\.yml)$/,
  /^app\/[a-z0-9-]+\.(html|ts|css|json|md)$/i,
  /^app\/public\/([a-z0-9-]+\.(json|txt|xml|svg|ico|png|webmanifest)|\.well-known\/[a-z0-9-]+\.json|logos\/[A-Za-z0-9-]+\.(png|svg|jpe?g|webp|md))$/,
  /^docs\/[a-z0-9-]+\.md$/,
  /^lib\/[a-z0-9-]+(\.test)?\.ts$/,
  /^scripts\/[a-z0-9-]+(\.test)?\.ts$/,
  /^skills\/[a-z0-9-]+\/SKILL\.md$/,
  /^verification\/[A-Za-z0-9_./-]+$/,
];
export const CONTRIBUTION_SHAPE =
  "A bank contribution adds files only under banks/<country>/<bank>/ (README.md, manifest.json, transformer.js, transformer.test.ts, fixtures/<case>.synthetic.json, reports/YYYY-MM-DD-<handle>.json) plus at most its logo in app/public/logos/. Restating an issue, adding top-level files or adding scripts is not a contribution. See CONTRIBUTING.md.";

/** Every tracked or new file outside banks/ must match REPOSITORY_LAYOUT. */
export function checkRepositoryLayout(files: string[]): string[] {
  return files
    .filter((file) => !file.startsWith("banks/"))
    .filter((file) => !REPOSITORY_LAYOUT.some((pattern) => pattern.test(file)))
    .map(
      (file) => `${file}: not part of the repository layout (no new top-level files or folders)`,
    );
}

/**
 * Pull requests from forks may add files only in contributor zones. Changes to existing
 * files still go through code-owner review; maintainers add new tooling from the main repo.
 */
export function checkContributorAdditions(added: string[]): string[] {
  const inBankFolder = (file: string) => {
    const kind = file.startsWith("banks/") ? classifyBankPath(file) : null;
    return kind !== null && !("error" in kind);
  };
  return added
    .filter(
      (file) =>
        !inBankFolder(file) && !/^app\/public\/logos\/[a-z0-9-]+\.(png|svg|jpe?g|webp)$/.test(file),
    )
    .map(
      (file) =>
        `${file}: pull requests from forks may only add bank folder files and a bank logo; propose other new files in an issue`,
    );
}

/** Existing check-defining files whose modification by a fork deserves maintainer attention. */
export const CHECK_DEFINITIONS =
  /^(package(-lock)?\.json|vitest\.config\.ts|tsconfig\.json|biome\.json|\.github\/|scripts\/|lib\/|verification\/|banks\/adapter-contract\.test\.ts)/;
