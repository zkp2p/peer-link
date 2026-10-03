/** Deterministic robustness probes, not guesses about bank-specific payment semantics. */
export function* malformedInputs(input: unknown): Generator<{ label: string; input: unknown }> {
  type Path = (string | number)[];
  function* paths(value: unknown, path: Path = []): Generator<Path> {
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      const next = [...path, Array.isArray(value) ? Number(key) : key];
      yield next;
      yield* paths(child, next);
    }
  }
  // JSON primitives/containers and finite extreme numbers expose unsafe property
  // access, coercion and date/amount overflow without requiring any bank field names.
  const replacements: [string, unknown][] = [
    ["missing", undefined],
    ["null", null],
    ["object", {}],
    ["array", []],
    ["boolean", true],
    ["empty string", ""],
    ["large number", 1e308],
    ["negative large number", -1e308],
  ];
  for (const path of paths(input)) {
    for (const [kind, value] of replacements) {
      const copy = structuredClone(input);
      let parent = copy as Record<string | number, unknown>;
      for (const part of path.slice(0, -1)) parent = parent[part] as typeof parent;
      const key = path[path.length - 1];
      if (value === undefined) {
        // JSON cannot contain sparse arrays. Removing an entry compacts the array.
        if (Array.isArray(parent)) parent.splice(Number(key), 1);
        else delete parent[key];
      } else parent[key] = structuredClone(value);
      // Labels identify a field and mutation, never echo banking values.
      yield { label: `${path.join(".")} (${kind})`, input: copy };
    }
  }
}
