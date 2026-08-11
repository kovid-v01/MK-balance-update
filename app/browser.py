import logging

from playwright.sync_api import sync_playwright


logger = logging.getLogger(__name__)

DEBUG_URL = "http://localhost:9222"
PORTAL_TITLE = "RetailerDashboard"
BALANCE_SELECTOR = ".balance-amount"


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