import logging
import re

from playwright.sync_api import sync_playwright


logger = logging.getLogger(__name__)

DEBUG_URL = "http://localhost:9222"
PORTAL_TITLE = "RetailerDashboard"
WHATSAPP_TITLE = "WhatsApp"
BALANCE_SELECTOR = ".balance-amount"
WHATSAPP_SEARCH_TIMEOUT_MS = 15000
WHATSAPP_MESSAGE_TIMEOUT_MS = 10000


def _find_page(pages, title_fragment, url_fragment=None):
    for page in pages:
        title = page.title()
        if title_fragment and title_fragment in title:
            return page
        if url_fragment and url_fragment in page.url:
            return page

    return None


def get_portal_balance():
    with sync_playwright() as p:
        logger.info("Connecting to existing Chrome browser")

        browser = p.chromium.connect_over_cdp(DEBUG_URL)

        logger.info("Connected to Chrome successfully")

        contexts = browser.contexts

        if not contexts:
            logger.error("No browser context found")
            return None

        context = contexts[0]
        pages = context.pages

        logger.info("Found %s open tab(s)", len(pages))

        portal_page = None

        for page in pages:
            if PORTAL_TITLE in page.title():
                portal_page = page
                break

        if portal_page is None:
            logger.error("RetailerDashboard tab not found")
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


def send_whatsapp_message(group_name, message):
    with sync_playwright() as p:
        logger.info("Connecting to existing Chrome browser")

        browser = p.chromium.connect_over_cdp(DEBUG_URL)

        logger.info("Connected to Chrome successfully")

        contexts = browser.contexts

        if not contexts:
            logger.error("No browser context found")
            return False

        context = contexts[0]
        pages = context.pages

        logger.info("Found %s open tab(s)", len(pages))

        whatsapp_page = _find_page(pages, WHATSAPP_TITLE, "web.whatsapp.com")

        if whatsapp_page is None:
            logger.error("WhatsApp tab not found")
            return False

        logger.info("WhatsApp tab found")
        whatsapp_page.bring_to_front()

        search_box = (
            whatsapp_page.locator('div[contenteditable="true"][aria-label*="Search"]')
            .first
        )

        search_box.wait_for(state="visible", timeout=WHATSAPP_SEARCH_TIMEOUT_MS)
        search_box.click()
        search_box.fill(group_name)
        whatsapp_page.keyboard.press("Enter")

        logger.info("Searching for WhatsApp group: %s", group_name)

        chat_title = whatsapp_page.get_by_text(re.compile(re.escape(group_name), re.I)).first
        chat_title.wait_for(state="visible", timeout=WHATSAPP_SEARCH_TIMEOUT_MS)
        chat_title.click()

        message_box = (
            whatsapp_page.locator('div[contenteditable="true"][aria-label*="message"]')
            .first
        )

        message_box.wait_for(state="visible", timeout=WHATSAPP_MESSAGE_TIMEOUT_MS)
        message_box.click()
        message_box.fill(message)
        whatsapp_page.keyboard.press("Enter")

        logger.info("WhatsApp message sent to %s", group_name)
        return True
