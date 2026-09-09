# Model pricing

Pricing was checked on **2026-09-09** against official sources. The provider
catalogs in `app/utils/adapters/models/` are the shared registry used by adapters
and exposed through `GET /models`. The chat usage bar reads this endpoint;
it no longer maintains a separate Claude-only price table.

All rates use **USD per million tokens**. This refresh verified 51 hosted-model
entries, plus local inference entries with no provider token charge.

| Provider | Source | Verified hosted entries |
| --- | --- | ---: |
| OpenAI | [Standard API pricing](https://developers.openai.com/api/docs/pricing) | 23 |
| Codex | [GPT-5.3-Codex](https://developers.openai.com/api/docs/models/gpt-5.3-codex) | 1 |
| Anthropic | [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing) | 12 |
| DeepSeek | [Models and pricing](https://api-docs.deepseek.com/quick_start/pricing/) | 3 |
| Google | [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) | 4 |
| Moonshot | [Kimi API platform](https://platform.kimi.ai/) | 1 |
| OpenRouter | [Public model catalog](https://openrouter.ai/api/v1/models) | 7 |

Notable corrected input/output rates: GPT-4.1 $2/$8, GPT-5.6 Sol $4/$20,
GPT-5.4 Nano $0.20/$1.25, and GPT-5.3-Codex $1.75/$14.

## DeepSeek

| Model | Peak input | Peak output | Off-peak input | Off-peak output |
| --- | ---: | ---: | ---: | ---: |
| V4 Pro | 1.32 | 3.96 | 0.66 | 1.98 |
| V4 Flash / Flash Vision Exp | 0.44 | 1.32 | 0.22 | 0.66 |

Peak periods are Monday–Friday, 01:00–04:00 and 06:00–10:00 UTC.
All other times are off-peak. Cache-hit rates are stored separately.

## What the chat estimate means

The chat shows an **uncached base-rate estimate for the latest model response**,
not a provider invoice or cumulative session bill. DeepSeek uses the peak-rate
baseline. Long-context rates and off-peak rates are recorded in the registry
but are not automatically applied by this estimate. Hover over the cost to see
the rate assumptions, source, and verification date.

Cache writes, cache discounts, long-context premiums, service tiers, audio,
grounding, tools, taxes, and regional surcharges can change the actual charge.
OpenRouter catalog rates may differ from a specific routed endpoint. Local
inference has no provider token charge; hardware/electricity are excluded.

Entries absent from current source tables retain their historical catalog
values for compatibility, with an empty `pricing_verified_at`. The chat displays
`Cost —` for these entries, unknown models, unavailable API data, or missing input
usage. It never guesses an alias or treats unknown pricing as free.

## Updating rates

Check the official source, select the correct standard inference table, and
update the provider's `ModelInfo` entry with rates, source, verification date,
and applicable tier notes. OpenRouter prices are per token; multiply by one
million before storing them. Do not use fine-tuning or batch prices as standard
inference rates. These are reviewed snapshots, not an automatic web scraper.

Run `poetry run pytest app/backend/tests/test_model_pricing.py`, build the
frontend, and run `scripts/check_chat_column_browser.py --dist <build-directory>`
through Poetry. Reload the backend after changing its imported catalog.
