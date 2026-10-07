import logging
import re
import os
import time
from contextlib import contextmanager
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import Error as PlaywrightError


logger = logging.getLogger(__name__)


PORTAL_TITLE = "RetailerDashboard"
WHATSAPP_TITLE = "WhatsApp"
DEFAULT_WHATSAPP_URL = "https://web.whatsapp.com/"

BALANCE_SELECTOR = ".balance-amount"

WHATSAPP_SEARCH_TIMEOUT_MS = 20000
WHATSAPP_MESSAGE_TIMEOUT_MS = 15000
WHATSAPP_MENTION_TIMEOUT_MS = 5000
WHATSAPP_UI_TIMEOUT_MS = 30000

WHATSAPP_SEARCH_SELECTORS = [
    '[data-testid="chat-list-search-container"] input',
    '#side input[data-tab="3"]',
    '#side input[type="text"]',
    '#side div[contenteditable="true"][data-tab="3"]',
    '#side div[contenteditable="true"][aria-label="Search input textbox"]',
    '#side div[contenteditable="true"]',
    '#side div[role="textbox"]',
]

WHATSAPP_MESSAGE_SELECTORS = [
    '#main footer [contenteditable="true"]',
    'footer [contenteditable="true"]',
    'footer [role="textbox"]',
    'div[contenteditable="true"][aria-placeholder="Type a message"]',
    'div[contenteditable="true"][data-tab="10"]',
    'div[contenteditable="true"][aria-label*="message"]',
    'div[aria-label*="Type a message"]',
]

CDP_CONNECT_TIMEOUT_MS = 30000
CDP_HEALTH_CHECK_TIMEOUT_SECONDS = 3

PORTAL_RELOAD_TIMEOUT_MS = 30000
PORTAL_BALANCE_TIMEOUT_MS = 10000


def cdp_endpoint_is_ready(port, timeout_seconds=CDP_HEALTH_CHECK_TIMEOUT_SECONDS):
    """Return True only when Chrome's DevTools HTTP endpoint responds."""
    endpoint = f"http://127.0.0.1:{port}/json/version"

    try:
        with urlopen(endpoint, timeout=timeout_seconds) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def wait_for_cdp_endpoint(port, timeout_seconds=30, poll_seconds=1):
    """Wait for the DevTools endpoint before attempting a CDP connection."""
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        if cdp_endpoint_is_ready(port):
            logger.info("Chrome DevTools endpoint is ready on port %s", port)
            return True

        time.sleep(poll_seconds)

    logger.error(
        "Chrome DevTools endpoint did not become ready on port %s within %s seconds",
        port,
        timeout_seconds,
    )
    return False


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


def _is_blank_url(url):
    current = (url or "").strip().lower()
    return (
        current in ("", "about:blank")
        or current.startswith("chrome://newtab")
        or current.startswith("chrome://new-tab-page")
        or current.startswith("edge://newtab")
    )


def _page_is_usable(page):
    try:
        _ = page.title()
        _ = page.url
        return True
    except Exception:
        return False


def _close_page_quietly(page, reason):
    if page is None:
        return

    try:
        page.close(run_before_unload=False)
        logger.info("%s", reason)
    except Exception:
        logger.exception("Unable to close a disconnected browser tab/window")


def _iter_pages(browser):
    try:
        for context in browser.contexts:
            for page in list(context.pages):
                yield page
    except Exception:
        logger.exception("Unable to list browser pages")


def close_unusable_pages(browser):
    """Close tabs/windows that no longer have a live connection."""
    for page in list(_iter_pages(browser)):
        if not _page_is_usable(page):
            _close_page_quietly(
                page,
                "Closed a disconnected browser tab/window",
            )


def _open_tab_in_same_window(context, url):
    """Open a tab in the current Chrome window. Playwright new_page() opens a window."""
    source_page = None
    for page in list(context.pages):
        if _page_is_usable(page):
            source_page = page
            break

    if source_page is None:
        return None

    existing_ids = {id(page) for page in context.pages}

    try:
        cdp = context.new_cdp_session(source_page)
        cdp.send(
            "Target.createTarget",
            {
                "url": url,
                "newWindow": False,
                "background": True,
            },
        )
    except Exception:
        logger.exception(
            "Could not open a tab in the existing Chrome window"
        )
        return None

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        for page in context.pages:
            if id(page) not in existing_ids:
                logger.info(
                    "Opened a tab in the existing Chrome window"
                )
                return page
        time.sleep(0.2)

    logger.warning("A same-window tab was requested but did not appear")
    return None


def _open_page(context, url):
    for page in list(context.pages):
        if not _page_is_usable(page):
            _close_page_quietly(
                page,
                "Closed a disconnected browser tab/window before replacement",
            )
            continue

        try:
            current_url = page.url
        except Exception:
            _close_page_quietly(
                page,
                "Closed a disconnected browser tab/window before replacement",
            )
            continue

        if _is_blank_url(current_url):
            logger.info(
                "Reusing an existing browser tab instead of opening a new window"
            )
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=PORTAL_RELOAD_TIMEOUT_MS,
            )
            return page

    same_window_tab = _open_tab_in_same_window(context, url)
    if same_window_tab is not None:
        return same_window_tab

    logger.warning(
        "Falling back to Playwright new_page(); this may open a separate window"
    )
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


def _wait_for_first_visible(page, selectors, timeout_ms):
    """Wait for the first matching visible element instead of failing immediately."""
    if not selectors:
        return None

    per_selector_timeout = max(1000, int(timeout_ms / len(selectors)))
    deadline = time.monotonic() + (timeout_ms / 1000)

    while time.monotonic() < deadline:
        for selector in selectors:
            locator = page.locator(selector).first
            remaining_ms = max(200, int((deadline - time.monotonic()) * 1000))
            try:
                locator.wait_for(
                    state="visible",
                    timeout=min(per_selector_timeout, remaining_ms),
                )
                logger.info("Found visible element with selector: %s", selector)
                return locator
            except Exception:
                continue

    return None


def _click_without_raising_window(locator):
    """Click in the page DOM so Windows does not activate Chrome."""
    locator.evaluate("element => element.click()")


def _focus_without_raising_window(locator):
    """Focus an element in the page without raising the Chrome window."""
    locator.evaluate("element => element.focus()")


def _insert_text_without_raising_window(locator, text):
    """Insert text in-page without raising the Chrome window."""
    locator.evaluate(
        """(element, value) => {
            element.focus();
            document.execCommand('insertText', false, value);
        }""",
        text,
    )


def _press_enter_without_raising_window(locator):
    """Send Enter from the page so Chrome does not steal OS focus."""
    locator.evaluate(
        """element => {
            element.dispatchEvent(
                new KeyboardEvent('keydown', {
                    key: 'Enter',
                    code: 'Enter',
                    keyCode: 13,
                    which: 13,
                    bubbles: true,
                    cancelable: true,
                })
            );
            element.dispatchEvent(
                new KeyboardEvent('keyup', {
                    key: 'Enter',
                    code: 'Enter',
                    keyCode: 13,
                    which: 13,
                    bubbles: true,
                    cancelable: true,
                })
            );
        }"""
    )


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

    p = None

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

        if p is not None:
            try:
                p.stop()
            except Exception:
                pass

        return None, None

def _preferred_context(browser):
    """Use the window that already has WhatsApp or the portal, if one exists."""
    whatsapp_url = os.getenv(
        "WHATSAPP_URL",
        DEFAULT_WHATSAPP_URL,
    )
    existing = _find_page(
        list(_iter_pages(browser)),
        WHATSAPP_TITLE,
        whatsapp_url,
    )
    if existing is not None:
        return existing.context

    portal = _find_page(
        list(_iter_pages(browser)),
        PORTAL_TITLE,
        os.getenv("PORTAL_URL"),
    )
    if portal is not None:
        return portal.context

    return _get_context(browser)


def _get_whatsapp_page(browser):
    whatsapp_url = os.getenv(
        "WHATSAPP_URL",
        DEFAULT_WHATSAPP_URL,
    )

    whatsapp_page = _find_page(
        list(_iter_pages(browser)),
        WHATSAPP_TITLE,
        whatsapp_url,
    )

    if whatsapp_page is None:
        context = _preferred_context(browser)

        if context is None:
            return None
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

    if not _wait_for_whatsapp_ready(whatsapp_page):
        return None

    logger.info("WhatsApp tab found")
    return whatsapp_page


def _whatsapp_needs_login(whatsapp_page):
    login_markers = [
        'canvas[aria-label*="scan" i]',
        '[data-testid="qrcode"]',
        'div[aria-label*="QR code"]',
        'text=Log in to WhatsApp Web',
    ]

    for selector in login_markers:
        try:
            if whatsapp_page.locator(selector).first.count() > 0:
                return True
        except Exception:
            continue

    return False


def _wait_for_whatsapp_ready(whatsapp_page):
    """Wait until WhatsApp Web has finished loading its chat UI."""
    search_box = _wait_for_first_visible(
        whatsapp_page,
        WHATSAPP_SEARCH_SELECTORS,
        WHATSAPP_UI_TIMEOUT_MS,
    )

    if search_box is not None:
        return True

    if _whatsapp_needs_login(whatsapp_page):
        logger.error(
            "WhatsApp Web is showing a login/QR screen. "
            "Sign in in the dedicated Chrome window, then wait for the next cycle."
        )
        return False

    logger.error(
        "WhatsApp search box not found. "
        "The WhatsApp tab may still be loading."
    )
    return False


def _get_message_box(whatsapp_page):
    message_box = _wait_for_first_visible(
        whatsapp_page,
        WHATSAPP_MESSAGE_SELECTORS,
        WHATSAPP_MESSAGE_TIMEOUT_MS,
    )

    if message_box is None:
        logger.error(
            "WhatsApp message box not found. "
            "The group chat may not have opened."
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

        _focus_without_raising_window(message_box)
        _insert_text_without_raising_window(message_box, "@")

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

        _click_without_raising_window(mention_option)

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
    p = None

    try:
        p = sync_playwright().start()

        # Read the CDP port dynamically from the environment.
        debug_port = os.getenv("REMOTE_DEBUGGING_PORT", "9222")
        debug_url = f"http://127.0.0.1:{debug_port}"

        logger.info(
            "Connecting to the existing browser session: %s",
            debug_url,
        )

        browser = p.chromium.connect_over_cdp(
            debug_url,
            timeout=CDP_CONNECT_TIMEOUT_MS,
        )

        logger.info("Connected to browser successfully")
        yield browser

    except Exception:
        logger.exception("Browser session encountered an error")
        raise

    finally:
        # Do not call browser.close(): this is an attachment to Chrome, not a
        # browser launched by Playwright. Stopping Playwright only disconnects
        # this client and leaves the dedicated Chrome profile running.
        if p is not None:
            logger.info("Disconnecting Playwright from browser session")
            try:
                p.stop()
            except Exception:
                logger.exception("Failed to stop Playwright cleanly")

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
    close_unusable_pages(browser)
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
    browser,
    portal_url,
):
    pages = list(_iter_pages(browser))

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


def _close_portal_page(portal_page):
    """Close only an unusable portal tab before opening a clean replacement."""
    _close_page_quietly(
        portal_page,
        "Closed unusable portal tab before replacement",
    )


def get_portal_balance(browser):
    close_unusable_pages(browser)
    context = _get_context(browser)

    if context is None:
        logger.error(
            "Browser context is unavailable. "
            "The browser/CDP session may have been closed."
        )

        raise RuntimeError(
            "Browser context is no longer available"
        )

    portal_url = os.getenv(
        "PORTAL_URL"
    )

    # ---------------------------------------------------------
    # Attempt 1
    # Refresh existing portal tab
    # ---------------------------------------------------------

    portal_page = _find_portal_page(
        browser,
        portal_url,
    )

    if portal_page is not None:

        try:
            logger.info(
                "Portal recovery attempt 1: "
                "refreshing existing portal tab"
            )

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
        browser,
        portal_url,
    )

    if portal_page is not None:

        try:
            logger.info(
                "Portal recovery attempt 2: "
                "refreshing portal again"
            )

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
            browser,
            portal_url,
        )

        if portal_page is not None:

            try:
                logger.info(
                    "Portal recovery attempt 3: "
                    "navigating directly to PORTAL_URL"
                )

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
    # Replace the portal tab. A tab that only responds after a person clicks
    # it can remain stuck through reload() and goto(), so reuse is unsafe.
    # ---------------------------------------------------------

    if portal_url:

        try:
            logger.info(
                "Portal recovery attempt 4: "
                "re-opening portal"
            )

            portal_page = _find_portal_page(
                browser,
                portal_url,
            )

            _close_portal_page(portal_page)

            logger.info("Opening a clean portal replacement tab")
            portal_page = _open_page(
                _preferred_context(browser) or context,
                portal_url,
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
        "The browser session may have been closed."
    )

    raise RuntimeError(
        "Browser session is no longer available"
    )


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

    search_box = _wait_for_first_visible(
        whatsapp_page,
        WHATSAPP_SEARCH_SELECTORS,
        WHATSAPP_SEARCH_TIMEOUT_MS,
    )

    if search_box is None:
        if _whatsapp_needs_login(whatsapp_page):
            logger.error(
                "WhatsApp search box not found because WhatsApp Web is not signed in"
            )
        else:
            logger.error(
                "WhatsApp search box not found"
            )
        return False

    _focus_without_raising_window(search_box)

    try:
        search_box.fill(
            group_name
        )

    except Exception:
        _insert_text_without_raising_window(
            search_box,
            group_name,
        )

    try:
        search_box.press("Enter")
    except Exception:
        logger.exception(
            "WhatsApp search Enter via locator failed; trying in-page Enter"
        )
        _press_enter_without_raising_window(search_box)

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

        _click_without_raising_window(chat_title)

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

    _focus_without_raising_window(message_box)

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
        if mention_everyone:
            # fill() would replace the @all mention chip.
            _insert_text_without_raising_window(
                message_box,
                f"{message_prefix}{message}",
            )
        else:
            message_box.fill(
                f"{message_prefix}{message}"
            )

    except Exception:
        try:
            _insert_text_without_raising_window(
                message_box,
                f"{message_prefix}{message}",
            )
        except Exception:
            logger.exception(
                "Failed to type WhatsApp message"
            )

            return False

    # ---------------------------------------------------------
    # Send
    # ---------------------------------------------------------

    send_button = _first_existing_locator(
        whatsapp_page,
        [
            'button[aria-label="Send"]',
            'span[data-icon="send"]',
        ],
    )

    if send_button is not None:
        _click_without_raising_window(send_button)
    else:
        _press_enter_without_raising_window(message_box)

    logger.info(
        "WhatsApp message sent"
    )

    return True
