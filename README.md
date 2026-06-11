# cardlister

Turn photos of Pokémon cards into priced eBay listings, with a human review gate.

Drop each card's photos into its own folder and cardlister will identify the card
(Claude vision), draft an eBay title and item specifics, suggest a price from recent
comps, and let you review and confirm every card in a local web UI before it publishes
anything to eBay's modern REST Sell APIs.

## The problem it solves

Listing ungraded Pokémon singles on eBay is repetitive: research the card, price it
from sold comps, photograph it, crop the images, and fight eBay's listing form.
cardlister automates the mechanical parts and keeps a human confirmation gate so you
never list the wrong card at the wrong price:

1. **You** photograph each card and drop its photos into a per-card folder.
2. cardlister **identifies** the card and **drafts** the title + item specifics.
3. cardlister **prices** it from recent eBay comps.
4. **You review and confirm** each card in the browser.
5. cardlister **lists** it via eBay's REST Sell APIs.

## How it's built

- **eBay REST Sell APIs + OAuth2** (Inventory / Account / Media) — managed-payments
  compatible, unlike the legacy Trading API.
- **Per-card folders** — nothing is coupled by file order, so a misnamed photo can't
  list the wrong image on the wrong card.
- **Claude vision** drafts each listing; **you confirm** in a local web UI.
- Local SQLite state and an idempotent, resumable pipeline. Each card's eBay **SKU**
  (derived from its folder) is the idempotency key, so a failed list can be retried
  without creating duplicate items or offers.
- Secrets live in `.env`; eBay OAuth refresh tokens are encrypted at rest.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync                 # install dependencies into .venv
cp .env.example .env    # then fill in eBay + Anthropic credentials
uv run cardlister --help
```

Generate the token-encryption key once and put it in `.env`:

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Credentials you'll need

| What | Where | Used for |
| --- | --- | --- |
| eBay App ID / Cert ID / RuName (sandbox and/or production) | [developer.ebay.com](https://developer.ebay.com/my/keys) | OAuth2 + listing |
| Anthropic API key | [platform.claude.com](https://platform.claude.com) | vision identification |

Before listing for real, your eBay **seller account** must be opted into Business
Policies and have a payment, return, and fulfillment policy plus an inventory location.
`cardlister account` checks this and tells you what's missing.

## Workflow

```sh
# One-time: authorize cardlister to sell on your eBay account (opens a browser).
uv run cardlister auth login --env sandbox

# 1. Ingest a directory of per-card folders (each subfolder = one card).
uv run cardlister ingest ~/cards

# 2. (optional) Crop photos to the card, non-destructively.
uv run cardlister crop

# 3. Identify cards with Claude vision (drafts title + item specifics).
uv run cardlister identify

# 4. Price each card from recent eBay comps.
uv run cardlister price PKM-charizard-4-102-xxxxxx

# 5. Review and confirm in the browser, then list from the UI.
uv run cardlister serve   # http://127.0.0.1:8000

# …or list from the CLI once a card is confirmed:
uv run cardlister list PKM-charizard-4-102-xxxxxx
```

`cardlister status` prints every card and its state. `cardlister review <sku>
--title ... --price ...` sets a title/price and marks a card reviewed without the UI.

### Per-card folders

```
~/cards/
  Charizard 4-102/
    front.jpg
    back.jpg
  Pikachu 58-102/
    1.jpg
    2.jpg
```

Photo roles (front/back/extra) are inferred from filenames (`front`/`back`) or order,
and are editable per photo in the web UI.

## Configuration

All settings are environment variables prefixed `CARDLISTER_` (see `.env.example`).
Notable ones:

- `CARDLISTER_EBAY_ENV` — `sandbox` or `production`.
- `CARDLISTER_VISION_MODEL` — defaults to `claude-haiku-4-5`.
- `CARDLISTER_EBAY_USE_INSIGHTS` — use sold comps via Marketplace Insights (requires
  eBay approval); otherwise pricing uses active-listing stats from the Browse API.

## Development

```sh
uv run pytest          # unit + mocked-integration tests
uv run ruff check .
uv run mypy
uv run alembic upgrade head   # apply database migrations
```

The eBay sandbox end-to-end test is opt-in and skipped unless sandbox credentials are
present: `uv run pytest -m e2e`.

## Migrating from the original version

The original tool was a set of scripts on eBay's legacy Trading API with a PayPal
payment model (rejected since eBay's 2021 managed-payments move) and an Excel sheet
coupled to a flat image folder by row order. This rewrite replaces all of it: provide
per-card folders instead of an Excel sheet, run `cardlister auth login` once, and use
the commands above. There is no automated data migration — re-ingest your card folders.
