# cardlister

Turn photos of Pokémon cards into priced eBay listings, with a human review gate.

Drop each card's photos into its own folder, and cardlister will identify the card
(Claude vision), draft an eBay listing title and item specifics, suggest a price from
recent comps, and let you review and confirm every card in a local web UI before it
publishes anything to eBay.

## The problem it solves

Listing ungraded Pokémon singles on eBay is repetitive: research the card, price it
from sold comps, photograph it, crop the images, and fill out eBay's listing form.
cardlister automates the mechanical parts and keeps a human confirmation gate so you
never list the wrong card at the wrong price:

1. **You** photograph each card and drop its photos in a per-card folder.
2. cardlister **identifies** the card and **drafts** the title + item specifics.
3. cardlister **prices** it from recent eBay comps.
4. **You review and confirm** each card in the browser.
5. cardlister **lists** it via eBay's modern REST Sell APIs.

## How it's built

- **eBay REST Sell APIs + OAuth2** (Inventory / Account / Media) — managed-payments
  compatible, unlike the legacy Trading API.
- **Per-card folders** — nothing is coupled by file order, so a misnamed photo can't
  list the wrong image on the wrong card.
- **Claude vision** drafts each listing; **you confirm** in a local web UI.
- Local SQLite state, idempotent/resumable pipeline (the card's eBay **SKU** is the
  idempotency key), secrets in `.env`, OAuth refresh tokens encrypted at rest.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync                 # install dependencies into .venv
cp .env.example .env    # then fill in eBay + Anthropic credentials
uv run cardlister --help
```

See `.env.example` for the full list of configuration variables.

## Status

Under active development. See `docs` / the implementation plan for the phased roadmap:
domain core → eBay sandbox listing → pricing comps → vision identification → web UI.
