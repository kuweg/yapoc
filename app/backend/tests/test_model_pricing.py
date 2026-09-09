"""The public catalog must deliver the same sourced rates used by adapters."""
import asyncio

import pytest

from app.backend.routers.models import list_models
from app.utils.adapters.models import ALL_PRICING, MODEL_REGISTRY


def test_catalog_exposes_provider_prices_without_credentials():
    payload = asyncio.run(list_models()).model_dump()
    provider = next(a for a in payload['adapters'] if a['name'] == 'deepseek')
    pro = next(m for m in provider['models'] if m['id'] == 'deepseek-v4-pro')
    assert (pro['input_price'], pro['output_price']) == ALL_PRICING[pro['id']]
    assert pro['pricing_verified_at'] == '2026-09-09'
    assert pro['pricing_source'].startswith('https://api-docs.deepseek.com/')
    assert pro['off_peak_input_price'] == pro['input_price'] / 2
    assert pro['off_peak_output_price'] == pro['output_price'] / 2
    assert pro['cached_input_price'] < pro['input_price']
    assert set(provider) == {'name', 'has_key', 'models'}


@pytest.mark.parametrize('model,prices', [
    ('deepseek-v4-pro', (1.32, 3.96)),
    ('deepseek-v4-flash', (.44, 1.32)),
    ('gpt-4.1', (2.0, 8.0)),
    ('gpt-5.6-sol', (4.0, 20.0)),
    ('gpt-5.4-nano', (.2, 1.25)),
    ('gpt-5.3-codex', (1.75, 14.0)),
])
def test_rates_use_standard_inference_units(model, prices):
    # Protect against taking batch/fine-tuning columns or per-token router rates.
    assert ALL_PRICING[model] == prices


def test_unverified_models_are_not_promoted_to_verified():
    assert MODEL_REGISTRY['deepseek-chat'].pricing_verified_at == ''
    assert MODEL_REGISTRY['gemini-2.5-pro'].long_context_output_price == 15
