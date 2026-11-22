"""E2E browser tests for Universal API Keys dashboard and Universal Default Model."""

import pytest
from playwright.sync_api import Page, expect


def test_universal_keys_dashboard_rendering(page: Page, admin_base_url: str):
    """Navigate to Universal Keys tab and verify all 4 required sections render properly."""
    page.goto(f"{admin_base_url}/admin/universal_keys")

    # Verify Universal Keys view is active and visible
    uk_view = page.locator("#view-universal_keys")
    expect(uk_view).to_be_visible()

    # SECTION A: Universal API Connection Details
    expect(page.locator(".uk-connection-card")).to_be_visible()
    base_url_elem = page.locator("#ukApiBaseUrl")
    expect(base_url_elem).to_be_visible()
    expect(base_url_elem).to_contain_text("/v1")

    # Verify Copy Base URL button
    copy_url_btn = page.locator("#ukCopyBaseUrlBtn")
    expect(copy_url_btn).to_be_visible()
    copy_url_btn.click()
    page.wait_for_timeout(300)
    expect(copy_url_btn).to_contain_text("Copied")

    # Verify Supported Endpoints Table
    expect(page.locator(".uk-endpoints-table")).to_be_visible()
    expect(page.locator(".uk-endpoints-table")).to_contain_text("/v1/chat/completions")
    expect(page.locator(".uk-endpoints-table")).to_contain_text("/v1/messages")

    # Verify cURL box
    expect(page.locator("#ukCurlSnippet")).to_be_visible()
    expect(page.locator("#ukCurlSnippet")).to_contain_text("curl -X POST")

    # SECTION B: Universal Default Model
    expect(page.locator(".uk-universal-model-card")).to_be_visible()
    alias_input = page.locator("#ukModelAliasInput")
    expect(alias_input).to_be_visible()
    expect(alias_input).to_have_value("free-claude-universal")

    target_select = page.locator("#ukModelTargetSelect")
    expect(target_select).to_be_visible()

    save_model_btn = page.locator("#ukSaveModelBtn")
    expect(save_model_btn).to_be_visible()

    status_pill = page.locator("#ukModelStatusText")
    expect(status_pill).to_be_visible()
    expect(status_pill).to_contain_text("free-claude-universal")

    # SECTION C: Generate New Universal Key
    create_form = page.locator("#ukCreateForm")
    expect(create_form).to_be_visible()
    expect(page.locator("#ukInputName")).to_be_visible()
    expect(page.locator("#ukInputModel")).to_be_visible()
    expect(page.locator("#ukInputRpm")).to_be_visible()
    expect(page.locator("#ukInputExpiry")).to_be_visible()
    expect(page.locator("#ukCreateBtn")).to_be_visible()

    # SECTION D: Existing Keys Table
    expect(page.locator(".uk-table")).to_be_visible()
    expect(page.locator("#ukTableBody")).to_be_visible()


def test_universal_key_creation_and_deletion_in_browser(page: Page, admin_base_url: str):
    """Generate a key through the UI form and verify no TypeError is raised."""
    page.goto(f"{admin_base_url}/admin/universal_keys")

    name_input = page.locator("#ukInputName")
    expect(name_input).to_be_visible()
    name_input.fill("E2E Test Key")

    # Generate key
    page.locator("#ukCreateBtn").click()

    # Verify one-time secret banner appears without JavaScript exceptions
    secret_banner = page.locator("#ukBannerSecret")
    expect(secret_banner).to_be_visible(timeout=10000)
    expect(page.locator("#ukSecretKeyName")).to_have_text("E2E Test Key")
    expect(page.locator("#ukSecretKeyValue")).to_contain_text("fcc_uk_")

    # Dismiss banner
    page.locator("#ukDismissBannerBtn").click()
    expect(secret_banner).not_to_be_visible()

    # Verify key appears in active keys table
    table_body = page.locator("#ukTableBody")
    expect(table_body).to_contain_text("E2E Test Key")

    # Delete the created key
    page.on("dialog", lambda dialog: dialog.accept())
    delete_btn = page.locator(".uk-delete-btn[data-name='E2E Test Key']").first
    if delete_btn.is_visible():
        delete_btn.click()
        page.wait_for_timeout(1000)

