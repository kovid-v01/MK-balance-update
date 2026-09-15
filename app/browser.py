import logging
import re
import os
from contextlib import contextmanager

from playwright.sync_api import sync_playwright


logger = logging.getLogger(__name__)

DEBUG_URL = f"http://localhost:{os.getenv('REMOTE_DEBUGGING_PORT', '9222')}"
PORTAL_TITLE = "RetailerDashboard"
WHATSAPP_TITLE = "WhatsApp"
DEFAULT_WHATSAPP_URL = "https://web.whatsapp.com/"
BALANCE_SELECTOR = ".balance-amount"
WHATSAPP_SEARCH_TIMEOUT_MS = 15000
WHATSAPP_MESSAGE_TIMEOUT_MS = 10000
WHATSAPP_MENTION_TIMEOUT_MS = 5000
CDP_CONNECT_TIMEOUT_MS = 30000


def _find_page(pages, title_fragment, url_fragment=None):
    for page in pages:
        title = page.title()
        if title_fragment and title_fragment in title:
            return page
        if url_fragment and url_fragment in page.url:
            return page

    return None


def _open_page(context, url):
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded")
    return page


def _first_existing_locator(page, selectors):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() > 0:
                return locator
        except Exception:
            continue

    return None


def _insert_everyone_mention(whatsapp_page, message_box):
    """Insert WhatsApp's @all mention, returning False if it is unavailable."""
    message_box.type("@all")
    mention_option = whatsapp_page.get_by_text(
        re.compile(r"^(?:@all|all|everyone)$", re.I)
    ).last

    try:
        mention_option.wait_for(
            state="visible", timeout=WHATSAPP_MENTION_TIMEOUT_MS
        )
        mention_option.click()
    except Exception:
        logger.error("WhatsApp @all mention option was not available")
        return False

    return True


@contextmanager
def open_browser_session():
    with sync_playwright() as p:
        logger.info("Connecting to the existing browser session")
        browser = p.chromium.connect_over_cdp(DEBUG_URL, timeout=CDP_CONNECT_TIMEOUT_MS)
        try:
            logger.info("Connected to browser successfully")
            yield browser
        finally:
            logger.info("Closing browser session connection")


def _get_context(browser):
    contexts = browser.contexts
    if not contexts:
        logger.error("No browser context found")
        return None

    return contexts[0]


def ensure_whatsapp_tab_open(browser):
    logger.info("Checking for WhatsApp tab")

    context = _get_context(browser)
    if context is None:
        return False

    pages = context.pages

    whatsapp_url = os.getenv("WHATSAPP_URL", DEFAULT_WHATSAPP_URL)
    whatsapp_page = _find_page(pages, WHATSAPP_TITLE, whatsapp_url)

    if whatsapp_page is None:
        logger.info("WhatsApp tab not found; opening WhatsApp URL")
        whatsapp_page = _open_page(context, whatsapp_url)
    else:
        logger.info("WhatsApp tab already open")

    whatsapp_page.bring_to_front()
    return True


def get_portal_balance(browser):
    context = _get_context(browser)
    if context is None:
        return None

    pages = context.pages

    logger.info("Found %s open tab(s)", len(pages))

    portal_url = os.getenv("PORTAL_URL")
    portal_page = _find_page(pages, PORTAL_TITLE, portal_url)

    if portal_page is None and portal_url:
        logger.info("RetailerDashboard tab not found; opening portal URL")
        portal_page = _open_page(context, portal_url)

    if portal_page is None:
        logger.error("RetailerDashboard tab not found and PORTAL_URL is not set")
        return None

    logger.info("RetailerDashboard tab found")
    logger.info("Refreshing portal")

    portal_page.reload(wait_until="domcontentloaded")

    logger.info("Portal refreshed successfully")

    balance_element = portal_page.locator(BALANCE_SELECTOR)

    balance_element.wait_for(state="visible", timeout=10000)

    balance = balance_element.inner_text()

    logger.info("Available balance: %s", balance)

    return balance


def send_whatsapp_message(browser, group_name, message, mention_everyone=False):
    context = _get_context(browser)
    if context is None:
        return False

    pages = context.pages

    logger.info("Found %s open tab(s)", len(pages))

    whatsapp_url = os.getenv("WHATSAPP_URL", DEFAULT_WHATSAPP_URL)
    whatsapp_page = _find_page(pages, WHATSAPP_TITLE, whatsapp_url)

    if whatsapp_page is None:
        logger.info("WhatsApp tab not found; opening WhatsApp URL")
        whatsapp_page = _open_page(context, whatsapp_url)

    logger.info("WhatsApp tab found")
    whatsapp_page.bring_to_front()

    search_box = _first_existing_locator(
        whatsapp_page,
        [
            'input[aria-label*="Search"]',
            'div[contenteditable="true"][aria-label*="Search"]',
            'div[role="textbox"][aria-label*="Search"]',
        ],
    )

    if search_box is None:
        logger.error("WhatsApp search box not found")
        return False

    search_box.wait_for(state="visible", timeout=WHATSAPP_SEARCH_TIMEOUT_MS)
    search_box.click()
    try:
        search_box.fill(group_name)
    except Exception:
        search_box.type(group_name)
    whatsapp_page.keyboard.press("Enter")

    logger.info("Searching for WhatsApp group: %s", group_name)

    chat_title = whatsapp_page.get_by_text(re.compile(re.escape(group_name), re.I)).first
    chat_title.wait_for(state="visible", timeout=WHATSAPP_SEARCH_TIMEOUT_MS)
    chat_title.click()

    message_box = _first_existing_locator(
        whatsapp_page,
        [
            'footer [contenteditable="true"]',
            'footer [role="textbox"]',
            'div[contenteditable="true"][aria-label*="message"]',
            'div[contenteditable="true"][data-tab="10"]',
            'div[aria-label*="Type a message"]',
        ],
    )

    if message_box is None:
        logger.error("WhatsApp message box not found")
        return False

    message_box.wait_for(state="visible", timeout=WHATSAPP_MESSAGE_TIMEOUT_MS)
    message_box.click()

    if mention_everyone and not _insert_everyone_mention(whatsapp_page, message_box):
        return False

    message_prefix = " " if mention_everyone else ""
    try:
        message_box.type(f"{message_prefix}{message}")
    except Exception:
        message_box.type(message)
    whatsapp_page.keyboard.press("Enter")

    logger.info("WhatsApp message sent to %s", group_name)
    return True
