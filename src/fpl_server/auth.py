import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Optional, List

from playwright.async_api import async_playwright

# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fpl_auth")


def _chromium_launch_options(playwright_executable: str) -> dict[str, str]:
    """Prefer Playwright's managed browser, then fall back to an installed Chrome."""
    override = os.environ.get("FPL_BROWSER_EXECUTABLE", "").strip()
    if override:
        executable = Path(override).expanduser()
        if not executable.is_file():
            raise RuntimeError(
                f"FPL_BROWSER_EXECUTABLE does not point to a browser: {executable}"
            )
        return {"executable_path": str(executable)}

    if Path(playwright_executable).is_file():
        return {}

    for command in (
        "google-chrome-stable",
        "google-chrome",
        "chromium",
        "chromium-browser",
    ):
        executable = shutil.which(command)
        if executable:
            logger.info("Using system browser for FPL authentication: %s", executable)
            return {"executable_path": executable}

    raise RuntimeError(
        "No Chromium browser is available for FPL authentication. Run "
        "`uv run playwright install chromium` in fpl-mcp-server, or set "
        "FPL_BROWSER_EXECUTABLE to an installed Chrome/Chromium binary."
    )


def _headless_browser_enabled() -> bool:
    configured = os.environ.get("FPL_BROWSER_HEADLESS", "").strip().lower()
    if configured:
        if configured in {"1", "true", "yes", "on"}:
            return True
        if configured in {"0", "false", "no", "off"}:
            return False
        raise RuntimeError("FPL_BROWSER_HEADLESS must be true or false when set.")
    return not bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


async def _visible_login_failure(page) -> str | None:
    known_failures = (
        (
            "Invalid username and/or password",
            "The Premier League rejected the email or password.",
        ),
        (
            "account has been locked",
            "The Premier League account is temporarily locked.",
        ),
        (
            "too many attempts",
            "The Premier League temporarily blocked further login attempts.",
        ),
    )
    for page_text, safe_message in known_failures:
        matches = page.get_by_text(page_text, exact=False)
        for index in range(await matches.count()):
            if await matches.nth(index).is_visible():
                return safe_message
    return None



async def _launch_browser(playwright):
    """Launch local Chromium, or connect to Browserbase when configured."""
    api_key = os.environ.get("BROWSERBASE_API_KEY", "").strip()
    project_id = os.environ.get("BROWSERBASE_PROJECT_ID", "").strip()

    if api_key:
        import httpx

        payload = {}
        if project_id:
            payload["projectId"] = project_id

        logger.info("Creating Browserbase session for FPL login...")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://www.browserbase.com/v1/sessions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload or {},
            )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Browserbase session failed ({resp.status_code}): {resp.text[:300]}"
                )
            data = resp.json()
            connect_url = (
                data.get("connectUrl")
                or data.get("connect_url")
                or data.get("wsUrl")
                or data.get("ws_url")
            )
            if not connect_url:
                raise RuntimeError(
                    f"Browserbase response missing connect URL: {list(data.keys())}"
                )

        logger.info("Connecting Playwright to Browserbase session...")
        browser = await playwright.chromium.connect_over_cdp(connect_url)
        return browser, True  # remote

    launch_options = _chromium_launch_options(playwright.chromium.executable_path)
    headless = _headless_browser_enabled()
    browser_args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-networking",
    ]
    if not headless:
        browser_args.extend(
            [
                "--start-minimized",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
            ]
        )
    logger.info(
        "Launching local FPL authentication browser in %s mode.",
        "headless" if headless else "local graphical",
    )
    browser = await playwright.chromium.launch(
        headless=headless,
        args=browser_args,
        **launch_options,
    )
    return browser, False  # local


class FPLAutomation:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.api_token: Optional[str] = None
        self.failure_reason: str | None = None
        self.base_url = "https://fantasy.premierleague.com"

    async def login_and_get_token(self) -> Optional[str]:
        async with async_playwright() as p:
            browser, is_remote = await _launch_browser(p)
            # Browserbase CDP often already has a default context
            if is_remote and browser.contexts:
                context = browser.contexts[0]
            else:
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    locale="en-GB",
                )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = await context.new_page()

            # 1. Setup Token Listener
            async def handle_response(response):
                if "/as/token" in response.url and response.request.method == "POST":
                    try:
                        data = await response.json()
                        if "access_token" in data:
                            self.api_token = f"Bearer {data['access_token']}"
                            logger.info("Captured API Token!")
                    except Exception:
                        pass

            page.on("response", handle_response)
            
            try:

                login_entry_urls = [
                    f"{self.base_url}/",
                    f"{self.base_url}/?login",
                    "https://fantasy.premierleague.com/",
                ]

                email_selectors = [
                    'input[name="username"]',
                    'input[name="email"]',
                    'input[type="email"]',
                    '#username',
                    '#email',
                    'input[id*="email" i]',
                    'input[placeholder*="email" i]',
                    'input[placeholder*="Email" i]',
                    'input[autocomplete="username"]',
                    'input[autocomplete="email"]',
                    '[data-cy="email"]',
                    'input[type="text"]',
                ]

                async def _accept_cookies():
                    for sel in (
                        '#onetrust-accept-btn-handler',
                        'button:has-text("Accept All Cookies")',
                        'button:has-text("Accept all")',
                        'button:has-text("I Accept")',
                        'button:has-text("Accept")',
                    ):
                        try:
                            btn = await page.wait_for_selector(sel, state="visible", timeout=2000)
                            if btn:
                                await btn.click()
                                await page.wait_for_timeout(500)
                                logger.info("Accepted cookies via %s", sel)
                                return
                        except Exception:
                            continue

                async def _find_email_input(timeout_ms: int = 4000):
                    for sel in email_selectors:
                        try:
                            el = await page.wait_for_selector(sel, state="visible", timeout=timeout_ms)
                            if el:
                                return el, sel
                        except Exception:
                            continue
                    return None, None

                email_input = None
                email_sel = None

                for entry in login_entry_urls:
                    logger.info("Navigating to %s", entry)
                    await page.goto(entry, wait_until="domcontentloaded", timeout=45000)
                    await _accept_cookies()

                    # Already on a login form?
                    email_input, email_sel = await _find_email_input(2500)
                    if email_input:
                        break

                    # Click Sign in / Log in
                    login_selectors = [
                        'a:has-text("Sign In")',
                        'button:has-text("Sign In")',
                        'a:has-text("Sign in")',
                        'button:has-text("Sign in")',
                        'a:has-text("Log In")',
                        'button:has-text("Log In")',
                        'a:has-text("Log in")',
                        'button:has-text("Log in")',
                        'a[href*="login"]',
                        'a[href*="sign-in"]',
                        'a[href*="signin"]',
                        '[data-testid*="login"]',
                        '[data-cy="login"]',
                    ]
                    for selector in login_selectors:
                        try:
                            btn = await page.wait_for_selector(selector, state="visible", timeout=1500)
                            if btn:
                                await btn.click()
                                logger.info("Clicked login control: %s", selector)
                                try:
                                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                                except Exception:
                                    pass
                                await page.wait_for_timeout(1500)
                                await _accept_cookies()
                                email_input, email_sel = await _find_email_input(5000)
                                if email_input:
                                    break
                        except Exception:
                            continue
                    if email_input:
                        break

                    # Try opening login in a new navigation if SPA route exists
                    for path in ("/login", "/sign-in", "/account/login"):
                        try:
                            await page.goto(self.base_url + path, wait_until="domcontentloaded", timeout=20000)
                            await _accept_cookies()
                            email_input, email_sel = await _find_email_input(3000)
                            if email_input:
                                break
                        except Exception:
                            continue
                    if email_input:
                        break

                if not email_input:
                    logger.error("Failed to find email field on %s", page.url)
                    title = await page.title()
                    self.failure_reason = (
                        "Could not reach the Premier League login form "
                        f"(page title: {title!r}). The site may be blocking "
                        "automated browsers on this server."
                    )
                    try:
                        await page.screenshot(path="email_fail.png")
                    except Exception:
                        pass
                    return None

                logger.info("Found email input using: %s on %s", email_sel, page.url)
                await email_input.fill(self.email)

                # Password
                pass_input = None
                pass_selectors = [
                    'input[name="password"]', 
                    'input[type="password"]', 
                    '#password', 
                    '[data-cy="password"]',
                    'input[placeholder*="password" i]'
                ]
                for sel in pass_selectors:
                    try:
                        pass_input = await page.wait_for_selector(sel, state="visible", timeout=3000)
                        if pass_input:
                            await pass_input.fill(self.password)
                            logger.info(f"Filled password using {sel}")
                            break
                    except: continue

                if not pass_input:
                    logger.error("Failed to find password field")
                    self.failure_reason = "The current Premier League login page did not expose its password field."
                    return None

                # 5. Submit (Try Multiple Buttons)
                submit_selectors = [
                    '#btnSignIn',
                    'button[data-skbuttonvalue="SIGNON"]',
                    'button:has-text("Sign in")',
                    'button:has-text("Log in")',
                    'input[type="submit"]',
                    '[data-cy="signin"]',
                    'button[class*="signin"]',
                    'button[class*="login"]',
                ]
                submit_clicked = False
                for sel in submit_selectors:
                    try:
                        btn = await page.wait_for_selector(sel, state="visible", timeout=3000)
                        if btn:
                            await btn.click()
                            logger.info(f"Clicked Submit using {sel}")
                            submit_clicked = True
                            break
                    except: continue

                if not submit_clicked:
                    self.failure_reason = "The current Premier League login page did not expose its Sign In action."
                    return None

                # 6. Wait for Token Capture
                logger.info("Waiting for token capture...")
                # Observe an explicit, sanitised rejection rather than masking it as a token timeout.
                for _ in range(30):
                    if self.api_token:
                        return self.api_token
                    failure = await _visible_login_failure(page)
                    if failure:
                        self.failure_reason = failure
                        logger.warning("FPL authentication was rejected by the account page.")
                        return None
                    await asyncio.sleep(0.5)
                
                logger.error("Login flow finished but no token captured.")
                self.failure_reason = (
                    "The Premier League login completed without returning an FPL session. "
                    "Its browser security check may have interrupted the redirect."
                )
                return None

            except Exception as e:
                logger.error(f"Auth Critical Error: {e}")
                self.failure_reason = "The local authentication browser could not complete the FPL login flow."
                return None
            finally:
                await browser.close()
