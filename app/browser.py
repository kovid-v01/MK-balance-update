import logging
import re
import os
from contextlib import contextmanager

from playwright.sync_api import sync_playwright


logger = logging.getLogger(__name__)


PORTAL_TITLE = "RetailerDashboard"
WHATSAPP_TITLE = "WhatsApp"
DEFAULT_WHATSAPP_URL = "https://web.whatsapp.com/"

BALANCE_SELECTOR = ".balance-amount"

WHATSAPP_SEARCH_TIMEOUT_MS = 15000
WHATSAPP_MESSAGE_TIMEOUT_MS = 10000
WHATSAPP_MENTION_TIMEOUT_MS = 5000

CDP_CONNECT_TIMEOUT_MS = 30000

PORTAL_RELOAD_TIMEOUT_MS = 30000
PORTAL_BALANCE_TIMEOUT_MS = 10000


def _find_page(pages, title_fragment, url_fragment=None):
    for page in pages:
        try:
            title = page.title()
        except Exception:
            title = ""

        if title_fragment and title_fragment in title:
            return page

        if url_fragment and url_fragment in page.url:
            return page

    return None


def _open_page(context, url):
    page = context.new_page()

    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=PORTAL_RELOAD_TIMEOUT_MS,
    )

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


def _get_context(browser):
    try:
        contexts = browser.contexts

        if not contexts:
            logger.error(
                "No browser context found"
            )
            return None

        context = contexts[0]

        # Confirm that the context is still usable.
        _ = context.pages

        return context

    except Exception:
        logger.exception(
            "Browser context is no longer available"
        )
        return None

def _browser_is_alive(browser):
    """
    Check whether the Playwright browser connection
    is still usable.
    """
    try:
        contexts = browser.contexts

        if not contexts:
            logger.warning(
                "Browser is connected but no browser context exists"
            )
            return False

        # Try accessing pages to confirm the context is usable.
        for context in contexts:
            _ = context.pages

        return True

    except Exception:
        logger.exception(
            "Browser connection is no longer usable"
        )
        return False

def reconnect_browser():
    """
    Create a fresh Playwright CDP connection.

    Used when the existing browser connection or
    browser context has been closed.
    """
    logger.info(
        "Attempting to reconnect to browser session"
    )

    try:
        p = sync_playwright().start()

        debug_port = os.getenv(
            "REMOTE_DEBUGGING_PORT",
            "9222",
        )

        debug_url = (
            f"http://localhost:{debug_port}"
        )

        logger.info(
            "Connecting to browser session: %s",
            debug_url,
        )

        browser = p.chromium.connect_over_cdp(
            debug_url,
            timeout=CDP_CONNECT_TIMEOUT_MS,
        )

        logger.info(
            "Browser reconnected successfully"
        )

        return p, browser

    except Exception:
        logger.exception(
            "Failed to reconnect to browser"
        )

        try:
            p.stop()
        except Exception:
            pass

        return None, None

def _get_whatsapp_page(browser):
    context = _get_context(browser)

    if context is None:
        return None

    pages = context.pages

    whatsapp_url = os.getenv(
        "WHATSAPP_URL",
        DEFAULT_WHATSAPP_URL,
    )

    whatsapp_page = _find_page(
        pages,
        WHATSAPP_TITLE,
        whatsapp_url,
    )

    if whatsapp_page is None:
        logger.info(
            "WhatsApp tab not found; opening WhatsApp URL"
        )

        try:
            whatsapp_page = _open_page(
                context,
                whatsapp_url,
            )

        except Exception:
            logger.exception(
                "Failed to open WhatsApp"
            )
            return None

    logger.info("WhatsApp tab found")

    try:
        whatsapp_page.bring_to_front()

    except Exception:
        logger.exception(
            "Failed to bring WhatsApp tab to front"
        )

    return whatsapp_page


def _get_message_box(whatsapp_page):
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
        logger.error(
            "WhatsApp message box not found"
        )
        return None

    try:
        message_box.wait_for(
            state="visible",
            timeout=WHATSAPP_MESSAGE_TIMEOUT_MS,
        )

    except Exception:
        logger.error(
            "WhatsApp message box did not become visible"
        )
        return None

    return message_box


def _insert_everyone_mention(
    whatsapp_page,
    message_box,
):
    """
    Inserts WhatsApp's actual @all mention.
    """

    try:
        logger.info(
            "Starting WhatsApp @all mention insertion"
        )

        message_box.click()
        message_box.type("@")

        logger.info(
            "Typed @, waiting for mention suggestions"
        )

        whatsapp_page.wait_for_timeout(1500)

        mention_option = whatsapp_page.get_by_text(
            "Mention all members in this chat",
            exact=True,
        ).last

        mention_option.wait_for(
            state="visible",
            timeout=WHATSAPP_MENTION_TIMEOUT_MS,
        )

        logger.info(
            "Found WhatsApp 'Mention all members in this chat' option"
        )

        mention_option.click()

        logger.info(
            "Clicked WhatsApp @all mention option"
        )

        whatsapp_page.wait_for_timeout(700)

        logger.info(
            "WhatsApp @all mention inserted successfully"
        )

        return True

    except Exception:
        logger.exception(
            "WhatsApp @all mention could not be inserted"
        )

        return False

@contextmanager
def open_browser_session():
    with sync_playwright() as p:

        # Read the CDP port dynamically from the environment.
        debug_port = os.getenv(
            "REMOTE_DEBUGGING_PORT",
            "9222",
        )

        debug_url = (
            f"http://localhost:{debug_port}"
        )

        logger.info(
            "Connecting to the existing browser session: %s",
            debug_url,
        )

        browser = p.chromium.connect_over_cdp(
            debug_url,
            timeout=CDP_CONNECT_TIMEOUT_MS,
        )

        try:
            logger.info(
                "Connected to browser successfully"
            )

            yield browser

        except Exception:
            logger.exception(
                "Browser session encountered an error"
            )
            raise

        finally:
            logger.info(
                "Closing browser session connection"
            )

            try:
                browser.close()
            except Exception:
                pass

def ensure_browser_connection(browser):
    """
    Check whether the browser connection is still usable.

    Returns:
        True  -> browser is usable
        False -> browser connection is unavailable
    """
    if browser is None:
        return False

    try:
        contexts = browser.contexts

        if not contexts:
            logger.warning(
                "Browser connection has no active context"
            )
            return False

        context = contexts[0]

        # Access pages to verify the context is alive.
        _ = context.pages

        return True

    except Exception:
        logger.exception(
            "Browser connection check failed"
        )
        return False


def ensure_whatsapp_tab_open(browser):
    logger.info(
        "Checking for WhatsApp tab"
    )

    whatsapp_page = _get_whatsapp_page(
        browser
    )

    if whatsapp_page is None:
        return False

    return True


def _find_portal_page(
    context,
    portal_url,
):
    pages = context.pages

    logger.info(
        "Found %s open tab(s)",
        len(pages),
    )

    return _find_page(
        pages,
        PORTAL_TITLE,
        portal_url,
    )


def _read_portal_balance(portal_page):
    balance_element = portal_page.locator(
        BALANCE_SELECTOR
    )

    balance_element.wait_for(
        state="visible",
        timeout=PORTAL_BALANCE_TIMEOUT_MS,
    )

    balance = balance_element.inner_text()

    if balance is None or str(balance).strip() == "":
        raise RuntimeError(
            "Balance element is empty"
        )

    return balance


def get_portal_balance(browser):
    context = _get_context(browser)

    if context is None:
        return None

    portal_url = os.getenv(
        "PORTAL_URL"
    )

    # ---------------------------------------------------------
    # Attempt 1
    # Refresh existing portal tab
    # ---------------------------------------------------------

    portal_page = _find_portal_page(
        context,
        portal_url,
    )

    if portal_page is not None:

        try:
            logger.info(
                "Portal recovery attempt 1: "
                "refreshing existing portal tab"
            )

            portal_page.bring_to_front()

            portal_page.reload(
                wait_until="domcontentloaded",
                timeout=PORTAL_RELOAD_TIMEOUT_MS,
            )

            logger.info(
                "Portal refreshed successfully"
            )

            balance = _read_portal_balance(
                portal_page
            )

            logger.info(
                "Available balance: %s",
                balance,
            )

            return balance

        except Exception:
            logger.exception(
                "Portal recovery attempt 1 failed"
            )

    else:
        logger.warning(
            "RetailerDashboard tab not found "
            "during recovery attempt 1"
        )

    # ---------------------------------------------------------
    # Attempt 2
    # Refresh again
    # ---------------------------------------------------------

    portal_page = _find_portal_page(
        context,
        portal_url,
    )

    if portal_page is not None:

        try:
            logger.info(
                "Portal recovery attempt 2: "
                "refreshing portal again"
            )

            portal_page.bring_to_front()

            portal_page.reload(
                wait_until="domcontentloaded",
                timeout=PORTAL_RELOAD_TIMEOUT_MS,
            )

            logger.info(
                "Portal refreshed successfully "
                "on recovery attempt 2"
            )

            balance = _read_portal_balance(
                portal_page
            )

            logger.info(
                "Available balance: %s",
                balance,
            )

            return balance

        except Exception:
            logger.exception(
                "Portal recovery attempt 2 failed"
            )

    else:
        logger.warning(
            "RetailerDashboard tab not found "
            "during recovery attempt 2"
        )

    # ---------------------------------------------------------
    # Attempt 3
    # Navigate directly to PORTAL_URL
    # ---------------------------------------------------------

    if portal_url:

        portal_page = _find_portal_page(
            context,
            portal_url,
        )

        if portal_page is not None:

            try:
                logger.info(
                    "Portal recovery attempt 3: "
                    "navigating directly to PORTAL_URL"
                )

                portal_page.bring_to_front()

                portal_page.goto(
                    portal_url,
                    wait_until="domcontentloaded",
                    timeout=PORTAL_RELOAD_TIMEOUT_MS,
                )

                logger.info(
                    "Portal navigation successful"
                )

                balance = _read_portal_balance(
                    portal_page
                )

                logger.info(
                    "Available balance: %s",
                    balance,
                )

                return balance

            except Exception:
                logger.exception(
                    "Portal recovery attempt 3 failed"
                )

        else:
            logger.warning(
                "Portal tab unavailable "
                "for recovery attempt 3"
            )

    else:
        logger.warning(
            "PORTAL_URL is not configured; "
            "skipping direct navigation recovery"
        )

    # ---------------------------------------------------------
    # Attempt 4
    # Re-open portal
    # ---------------------------------------------------------

    if portal_url:

        try:
            logger.info(
                "Portal recovery attempt 4: "
                "re-opening portal"
            )

            portal_page = _find_portal_page(
                context,
                portal_url,
            )

            if portal_page is None:

                logger.info(
                    "Portal tab is no longer available. "
                    "Opening a new portal tab."
                )

                portal_page = _open_page(
                    context,
                    portal_url,
                )

            else:

                portal_page.bring_to_front()

                portal_page.goto(
                    portal_url,
                    wait_until="domcontentloaded",
                    timeout=PORTAL_RELOAD_TIMEOUT_MS,
                )

            logger.info(
                "Portal re-opened successfully"
            )

            balance = _read_portal_balance(
                portal_page
            )

            logger.info(
                "Available balance: %s",
                balance,
            )

            return balance

        except Exception:
            logger.exception(
                "Portal recovery attempt 4 failed"
            )

    else:
        logger.warning(
            "PORTAL_URL is not configured; "
            "cannot re-open portal"
        )

    # ---------------------------------------------------------
    # All attempts failed
    # ---------------------------------------------------------

    logger.error(
        "All portal recovery attempts failed. "
        "Balance could not be retrieved. "
        "The application will continue and retry "
        "on the next scheduled check."
    )

    return None


def send_whatsapp_message(
    browser,
    group_name,
    message,
    mention_everyone=False,
):
    whatsapp_page = _get_whatsapp_page(
        browser
    )

    if whatsapp_page is None:
        return False

    search_box = _first_existing_locator(
        whatsapp_page,
        [
            'input[aria-label*="Search"]',
            'div[contenteditable="true"][aria-label*="Search"]',
            'div[role="textbox"][aria-label*="Search"]',
        ],
    )

    if search_box is None:
        logger.error(
            "WhatsApp search box not found"
        )
        return False

    try:
        search_box.wait_for(
            state="visible",
            timeout=WHATSAPP_SEARCH_TIMEOUT_MS,
        )

    except Exception:
        logger.error(
            "WhatsApp search box did not become visible"
        )
        return False

    search_box.click()

    try:
        search_box.fill(
            group_name
        )

    except Exception:
        search_box.type(
            group_name
        )

    whatsapp_page.keyboard.press(
        "Enter"
    )

    logger.info(
        "Searching for WhatsApp group: %s",
        group_name,
    )

    # Find the WhatsApp search result using its title attribute.
    # WhatsApp splits the visible group name across multiple
    # highlighted spans, so get_by_text() is unreliable here.
    chat_title = whatsapp_page.locator(
        f'[title="{group_name}"]'
    ).first

    try:
        chat_title.wait_for(
            state="visible",
            timeout=WHATSAPP_SEARCH_TIMEOUT_MS,
        )

        logger.info(
            "WhatsApp group found: %s",
            group_name,
        )

        chat_title.click()

        logger.info(
            "WhatsApp group opened successfully: %s",
            group_name,
        )

    except Exception:
        logger.exception(
            "WhatsApp group could not be opened: %s",
            group_name,
        )

        return False

    return _send_message_to_current_chat(
        whatsapp_page,
        message,
        mention_everyone=mention_everyone,
    )


def send_whatsapp_current_chat_message(
    browser,
    message,
    mention_everyone=False,
):
    """
    Sends a message to whichever WhatsApp chat is
    currently open.

    This avoids performing another WhatsApp search,
    which is important when sending the second message
    immediately after the balance message.
    """

    whatsapp_page = _get_whatsapp_page(
        browser
    )

    if whatsapp_page is None:
        return False

    return _send_message_to_current_chat(
        whatsapp_page,
        message,
        mention_everyone=mention_everyone,
    )


def _send_message_to_current_chat(
    whatsapp_page,
    message,
    mention_everyone=False,
):
    message_box = _get_message_box(
        whatsapp_page
    )

    if message_box is None:
        return False

    message_box.click()

    # ---------------------------------------------------------
    # Insert real @all mention
    # ---------------------------------------------------------

    if mention_everyone:

        logger.info(
            "Preparing WhatsApp @all mention"
        )

        if not _insert_everyone_mention(
            whatsapp_page,
            message_box,
        ):
            logger.error(
                "Could not insert WhatsApp @all mention"
            )

            return False

        message_prefix = " "

    else:
        message_prefix = ""

    # ---------------------------------------------------------
    # Type message
    # ---------------------------------------------------------

    try:

        message_box.type(
            f"{message_prefix}{message}"
        )

    except Exception:
        logger.exception(
            "Failed to type WhatsApp message"
        )

        return False

    # ---------------------------------------------------------
    # Send
    # ---------------------------------------------------------

    whatsapp_page.keyboard.press(
        "Enter"
    )

    logger.info(
        "WhatsApp message sent"
    )

    return True