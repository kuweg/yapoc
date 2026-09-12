"""Check Books autocomplete without submitting tasks or modifying the library.

Run against a running frontend: poetry run python scripts/check_book_mentions_browser.py
"""
import argparse
from playwright.sync_api import sync_playwright, expect


def check(url):
    cases = [
        ('populated', 200, [{'id': 'fixture', 'title': 'Reading Systems', 'author': 'Reader', 'position': 1, 'total': 8}]),
        ('empty', 200, []),
        ('unavailable', 503, {'detail': 'Unavailable'}),
        ('malformed', 200, {'books': []}),
        ('invalid rows', 200, [None, {'id': 'invalid', 'title': None}]),
    ]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for name, status, payload in cases:
                context = browser.new_context(viewport={'width': 1400, 'height': 1000})
                page = context.new_page()
                errors, mutations = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))

                def api(route):
                    if route.request.method not in ('GET', 'HEAD', 'OPTIONS'):
                        mutations.append(route.request.url)
                        route.abort()
                    elif route.request.url.split('?')[0].endswith('/api/books'):
                        route.fulfill(status=status, json=payload)
                    else:
                        route.continue_()

                page.route('**/api/**', api)
                page.goto(url)
                page.get_by_role('button', name='Conversation', exact=True).click()
                field = page.locator('textarea:visible').first
                field.fill('@b')
                expect(page.get_by_role('option', name='@books Your reading library')).to_be_visible()
                field.press('Enter')
                expect(field).to_have_value('@book:')
                expect(page.get_by_role('listbox', name='Suggestions')).to_be_visible()
                if name == 'populated':
                    row = page.get_by_role('option').filter(has_text='Reading Systems')
                    expect(row).to_be_visible()
                    field.press('ArrowDown')
                    field.press('Enter')
                    expect(field).to_have_value('@book:"Reading Systems" ')
                else:
                    page.wait_for_timeout(400)
                    expect(page.get_by_role('listbox', name='Suggestions').get_by_role('option')).to_have_count(1)
                field.press('Escape')
                field.fill('Chat still works')
                expect(field).to_have_value('Chat still works')
                assert not errors, (name, errors)
                assert not mutations, (name, mutations)
                context.close()
                print(f'PASS: {name}')
        finally:
            browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:5173')
    check(parser.parse_args().url)
