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
  // Fixed USDC per accepted transcript; capacity is a shared budget checked by reservation.
  bounty: number | null;
  campaignStatus: "planned" | "source_validation" | "open";
  maxContributorOrganizations: number | null;
};

// Mercury stays first; banks.json keeps Chase, Bank of America and Wells Fargo next.
const PINNED_ADAPTERS = ["us/mercury"];
const PINNED_BANKS = 3;
type Campaign = {
  name: string;
  country: string;
  currency: string;
  logo: string;
  adapter: string;
  url: string;
  amount: number;
  status?: string;
  campaign?: string;
  maxContributorOrganizations?: number;
};
const campaignStatus = (campaign?: Campaign): Integration["campaignStatus"] =>
  campaign?.status === "source_validation" || campaign?.status === "open"
    ? campaign.status
    : "planned";
const bountyByUrl = new Map<string, Campaign>(bounties.map((bounty) => [bounty.url, bounty]));
const bountyByAdapter = new Map<string, Campaign>(
  bounties.map((bounty) => [bounty.adapter, bounty]),
);
const normalize = (name: string) => name.toLowerCase().replace(/[^a-z0-9]/g, "");

const list = document.querySelector("#provider-list");
const countryNames = new Intl.DisplayNames(["en"], { type: "region" });
const catalogStatus = document.querySelector<HTMLElement>("#catalog-status");

function fromProvider(provider: Provider, bank?: Bank): Integration {
  const campaign = bountyByAdapter.get(provider.id);
  return {
    name: bank?.name ?? provider.name,
    country: provider.country,
    currency: provider.currencies.join(", "),
    href: campaign?.url ?? provider.source,
    logo: provider.logo ?? bank?.logo ?? null,
    mark: provider.name.slice(0, 2).toUpperCase(),
    hasAdapter: true,
    bounty: campaign?.amount ?? null,
    campaignStatus: campaignStatus(campaign),
    maxContributorOrganizations: campaign?.maxContributorOrganizations ?? null,
  };
}

function fromBank(bank: Bank): Integration {
  const campaign = bountyByUrl.get(bank.issue);
  return {
    name: bank.name,
    country: bank.country,
    currency: bank.currency,
    href: bank.issue,
    logo: bank.logo,
    mark: bank.mark,
    hasAdapter: false,
    bounty: campaign?.amount ?? null,
    campaignStatus: campaignStatus(campaign),
    maxContributorOrganizations: campaign?.maxContributorOrganizations ?? null,
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
  // Local campaign discovery survives an unavailable or incomplete adapter catalog.
  const missingPinned = PINNED_ADAPTERS.filter(
    (adapter) => !pinned.some((provider) => provider.id === adapter),
  ).flatMap((adapter) => {
    const campaign = bountyByAdapter.get(adapter);
    return campaign
      ? [
          fromBank({
            name: campaign.name,
            country: campaign.country,
            currency: campaign.currency,
            issue: campaign.url,
            logo: campaign.logo,
            mark: campaign.name.slice(0, 2).toUpperCase(),
          }),
        ]
      : [];
  });
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
    ...missingPinned,
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
    const organizationLimit = integration.maxContributorOrganizations
      ? ` Limit: ${integration.maxContributorOrganizations} contributor organization.`
      : "";
    const rewardDescription =
      integration.campaignStatus === "source_validation"
        ? `First-contributor source validation: $${integration.bounty} per accepted contribution.${organizationLimit} A verified release and funded reservation are required; availability is not guaranteed.`
        : integration.campaignStatus === "open"
          ? `Open transcript campaign: $${integration.bounty} per accepted contribution. All banks share one funded budget; a reservation admits a job and availability is not guaranteed.`
          : `Planned $${integration.bounty} per accepted transcript.${organizationLimit} This bank’s campaign is planned.`;
    card.setAttribute(
      "aria-label",
      integration.name === "Wise"
        ? `${integration.name}, ${place}. View the existing Wise reference; no transcript reward recruitment.`
        : integration.bounty
          ? `${integration.name}, ${place}. ${rewardDescription}`
          : integration.hasAdapter
            ? `${integration.name}, ${place}. View experimental adapter.`
            : `${integration.name}, ${place}. View bank integration discussion.`,
    );
    const logo = document.createElement("span");
    logo.className = "integration-logo";
    if (integration.logo) {
      const img = document.createElement("img");
      img.src = integration.logo;
      img.alt = "";
      // Bank cards stay light; preserve official SVGs with adaptive dark-mode fills.
      img.style.colorScheme = "light";
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
