import { afterEach, expect, it, vi } from "vitest";

class Element {
  children: Element[] = [];
  attributes: Record<string, string> = {};
  textContent = "";
  href = "";
  title = "";
  style = { colorScheme: "" };
  classList = { add: vi.fn(), toggle: vi.fn() };
  append(...nodes: Element[]) {
    this.children.push(...nodes);
  }
  replaceChildren() {
    this.children = [];
  }
  setAttribute(key: string, value: string) {
    this.attributes[key] = value;
  }
  addEventListener() {}
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

it("keeps the Mercury campaign and Wise reference when the adapter catalog fails", async () => {
  const list = new Element();
  const catalogStatus = new Element();
  vi.stubGlobal("document", {
    querySelector: (selector: string) =>
      selector === "#provider-list" ? list : selector === "#catalog-status" ? catalogStatus : null,
    createElement: () => new Element(),
  });
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("catalog unavailable")));
  await import("../app/main");
  await vi.dynamicImportSettled();

  expect(list.children.slice(0, 4).map((card) => card.children[1].textContent)).toEqual([
    "Mercury",
    "Chase",
    "Bank of America",
    "Wells Fargo",
  ]);
  const mercury = list.children[0];
  expect(mercury.href).toBe("https://github.com/zkp2p/peer-link/issues/1");
  expect(mercury.children.at(-1)?.textContent).toBe("$10");
  expect(mercury.attributes["aria-label"]).toContain("First-contributor source validation");
  expect(mercury.attributes["aria-label"]).toContain("1 contributor organization");
  expect(mercury.children[0].children[0].style.colorScheme).toBe("light");
  const wise = list.children.find((card) => card.children[1].textContent === "Wise");
  expect(wise?.href).toBe("https://wise.com/");
  expect(wise?.children).toHaveLength(3);
  expect(wise?.attributes["aria-label"]).toContain("no transcript reward recruitment");
  expect(catalogStatus.textContent).toContain("catalog could not load");
});
