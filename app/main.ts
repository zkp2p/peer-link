import banks from "./banks.json";

const prompt = document.querySelector<HTMLElement>("#agent-prompt");
const copyStatus = document.querySelector<HTMLElement>("#copy-status");
document.querySelector("#copy-prompt")?.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(prompt?.textContent ?? "");
    if (copyStatus) copyStatus.textContent = "Copied. Paste it into your coding agent.";
  } catch {
    if (copyStatus) copyStatus.textContent = "Select the prompt above and copy it manually.";
  }
});

type Provider = {
  name: string;
  id: string;
  country: string;
  currencies: string[];
  source: string;
};
type Integration = {
  name: string;
  country: string;
  currency: string;
  href: string;
  logo: string | null;
  mark: string;
  hasAdapter: boolean;
};

const list = document.querySelector("#provider-list");
const countryNames = new Intl.DisplayNames(["en"], { type: "region" });
const catalogStatus = document.querySelector<HTMLElement>("#catalog-status");

function render(providers: Provider[], catalogUnavailable = false) {
  if (!list) return;
  list.replaceChildren();
  const integrations: Integration[] = [
    ...providers.map((provider) => ({
      name: provider.name,
      country: provider.country,
      currency: provider.currencies.join(", "),
      href: provider.source,
      logo: provider.id === "us/mercury" ? "/logos/mercury.svg" : null,
      mark: provider.name.slice(0, 2).toUpperCase(),
      hasAdapter: true,
    })),
    ...banks
      .filter(
        (bank) =>
          !providers.some(
            (provider) => provider.name === bank.name && provider.country === bank.country,
          ),
      )
      .map((bank) => ({
        name: bank.name,
        country: bank.country,
        currency: bank.currency,
        href: bank.issue,
        logo: bank.logo,
        mark: bank.mark,
        hasAdapter: false,
      })),
  ];

  if (catalogStatus) {
    catalogStatus.classList.toggle("sr-only", !catalogUnavailable);
    catalogStatus.textContent = catalogUnavailable
      ? "The adapter catalog could not load. Reload to see all integrations."
      : `${integrations.length} banks`;
  }
  for (const integration of integrations) {
    const card = document.createElement("a");
    card.className = "integration-tile";
    card.href = integration.href;
    const place = countryNames.of(integration.country) ?? integration.country;
    card.setAttribute(
      "aria-label",
      integration.hasAdapter
        ? `${integration.name}, ${place}. View experimental adapter.`
        : `${integration.name}, ${place}. View bank integration discussion.`,
    );
    const logo = document.createElement("span");
    logo.className = "integration-logo";
    if (integration.logo) {
      const img = document.createElement("img");
      img.src = integration.logo;
      img.alt = "";
      img.loading = "lazy";
      img.addEventListener("error", () => {
        img.remove();
        logo.textContent = integration.mark;
      });
      logo.append(img);
    } else {
      logo.textContent = integration.mark;
    }
    const name = document.createElement("strong");
    name.className = "integration-name";
    name.textContent = integration.name;
    const meta = document.createElement("span");
    meta.className = "integration-meta";
    meta.textContent = `${place} / ${integration.currency}`;
    card.append(logo, name, meta);
    list.append(card);
  }
}

fetch("/catalog.json")
  .then((response) => {
    if (!response.ok) throw new Error("Catalog unavailable");
    return response.json();
  })
  .then((data: { providers: Provider[] }) => {
    if (!Array.isArray(data.providers)) throw new Error("Invalid catalog");
    render(data.providers);
  })
  .catch(() => render([], true));
