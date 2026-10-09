import banks from "./banks.json";
import bounties from "./bounties.json";

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
  logo?: string;
};
type Bank = (typeof banks)[number];
type Integration = {
  name: string;
  country: string;
  currency: string;
  href: string;
  logo: string | null;
  mark: string;
  hasAdapter: boolean;
  // Planned USDC per accepted transcript; the bank's issue holds live availability.
  bounty: number | null;
};

// Mercury stays first; banks.json keeps Chase, Bank of America and Wells Fargo next.
const PINNED_ADAPTERS = ["us/mercury"];
const PINNED_BANKS = 3;
const bountyByUrl = new Map(bounties.map((bounty) => [bounty.url, bounty]));
const normalize = (name: string) => name.toLowerCase().replace(/[^a-z0-9]/g, "");

const list = document.querySelector("#provider-list");
const countryNames = new Intl.DisplayNames(["en"], { type: "region" });
const catalogStatus = document.querySelector<HTMLElement>("#catalog-status");

function fromProvider(provider: Provider, bank?: Bank): Integration {
  return {
    name: bank?.name ?? provider.name,
    country: provider.country,
    currency: provider.currencies.join(", "),
    href: provider.source,
    logo: provider.logo ?? bank?.logo ?? null,
    mark: provider.name.slice(0, 2).toUpperCase(),
    hasAdapter: true,
    bounty: null,
  };
}

function fromBank(bank: Bank): Integration {
  return {
    name: bank.name,
    country: bank.country,
    currency: bank.currency,
    href: bank.issue,
    logo: bank.logo,
    mark: bank.mark,
    hasAdapter: false,
    bounty: bountyByUrl.get(bank.issue)?.amount ?? null,
  };
}

function render(providers: Provider[], catalogUnavailable = false) {
  if (!list) return;
  list.replaceChildren();
  // A merged adapter replaces its bank card (matched by bounty folder or name + country)
  // so it keeps its place and logo; adapters for unlisted banks follow the pinned cards.
  const used = new Set<string>();
  const pinned = providers.filter((provider) => PINNED_ADAPTERS.includes(provider.id));
  for (const provider of pinned) used.add(provider.id);
  const bankCards = banks.map((bank) => {
    const folder = bountyByUrl.get(bank.issue)?.adapter;
    const provider = providers.find(
      (candidate) =>
        !used.has(candidate.id) &&
        (candidate.id === folder ||
          (candidate.country === bank.country &&
            normalize(candidate.name) === normalize(bank.name))),
    );
    if (!provider) return fromBank(bank);
    used.add(provider.id);
    return fromProvider(provider, bank);
  });
  const unlisted = providers
    .filter((provider) => !used.has(provider.id))
    .map((p) => fromProvider(p));
  const integrations: Integration[] = [
    ...pinned.map((provider) => fromProvider(provider)),
    ...bankCards.slice(0, PINNED_BANKS),
    ...unlisted,
    ...bankCards.slice(PINNED_BANKS),
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
    const isWiseCampaign = integration.href === "https://github.com/zkp2p/peer-link/issues/239";
    const rewardDescription = isWiseCampaign
      ? "$5 per accepted transcript. Release approval and a successful reservation are required; availability can change."
      : `Planned $${integration.bounty} per accepted transcript. View the campaign issue for availability.`;
    card.setAttribute(
      "aria-label",
      integration.hasAdapter
        ? `${integration.name}, ${place}. View experimental adapter.`
        : integration.bounty
          ? `${integration.name}, ${place}. ${rewardDescription}`
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
    if (integration.bounty) {
      card.classList.add("has-bounty");
      const tag = document.createElement("span");
      tag.className = "bounty-tag";
      tag.setAttribute("aria-hidden", "true");
      tag.textContent = `$${integration.bounty}`;
      card.title = rewardDescription;
      card.append(tag);
    }
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
