import logging
import os
import time
import requests

# ---------------- CONFIGURATION ----------------
DISCORD_WEBHOOK_MARKET_1 = os.getenv("DISCORD_WEBHOOK_MARKET_1", "").strip()
DISCORD_WEBHOOK_MARKET_2 = os.getenv("DISCORD_WEBHOOK_MARKET_2", "").strip()

# MuhRO MarketDB Endpoints
ACTIVE_VENDING_API = "https://flux.muhro.eu/?module=marketdb&action=api&name=v_vending"
LAST_SALES_API = "https://flux.muhro.eu/?module=marketdb&action=api&name=vending_last_sales_latest"

CHECK_INTERVAL_SECONDS = max(15, int(os.getenv("MARKET_CHECK_INTERVAL_SECONDS", "300")))
PING_DELAY_SECONDS = max(0, float(os.getenv("PING_DELAY_SECONDS", "2")))
REQUEST_TIMEOUT_SECONDS = max(3, int(os.getenv("MARKET_REQUEST_TIMEOUT_SECONDS", "10")))

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("muhro-market")
# -----------------------------------------------

# Memory tracking to avoid duplicate pings
alerted_listings = set()
alerted_sales = set()

# Global flags to control initial silent warm-ups
is_initial_listings_warmup = True
is_initial_sales_warmup = True


def send_discord_alert(content_text, title, color, price, amount, datetime_str):
    """Sends a formatted embed message to both Discord webhooks with Rate Limit protection."""
    payload = {
        "content": content_text,
        "embeds": [
            {
                "title": title,
                "color": color,
                "fields": [
                    {"name": "Price", "value": f"{price:,} Zeny", "inline": True},
                    {"name": "Quantity", "value": str(amount), "inline": True},
                    {"name": "Date & Time", "value": str(datetime_str), "inline": True}
                ],
                "footer": {"text": "MuhRO MVP Market Tracker"}
            }
        ]
    }
    
    webhooks = [url for url in (DISCORD_WEBHOOK_1, DISCORD_WEBHOOK_2) if url]

    for webhook_url in webhooks:
        retries = 0
        while retries < 5:
            try:
                response = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
                if response.status_code in (200, 204):
                    log.info("Discord alert sent successfully")
                    break
                elif response.status_code == 429:
                    retry_after = response.json().get("retry_after", 2)
                    retries += 1
                    log.warning("Discord rate limit; retry %s/5 in %ss", retries, retry_after)
                    time.sleep(min(float(retry_after), 60))
                else:
                    log.error("Discord webhook returned HTTP %s", response.status_code)
                    break
            except requests.RequestException:
                retries += 1
                log.exception("Failed to post to Discord webhook (attempt %s/5)", retries)
                if retries < 5:
                    time.sleep(min(2 ** retries, 30))


def parse_zeny(raw_price, currency="zeny"):
    if raw_price is None:
        return 0
    try:
        clean_str = str(raw_price).replace(",", "").strip()
        parsed = int(float(clean_str))
        if "1m" in str(currency).lower() or (parsed < 1000000 and "zeny" not in str(currency).lower() and parsed > 0):
            return parsed * 1000000
        return parsed
    except (ValueError, TypeError):
        return 0


def parse_sale_data(sale_dict):
    amount = 1
    for key in ["amount", "count", "qty", "quantity", "num"]:
        val = sale_dict.get(key)
        if val is not None:
            try:
                parsed_val = int(str(val).replace(",", "").strip())
                if parsed_val > 0:
                    amount = parsed_val
                    break
            except ValueError:
                pass

    raw_price = (
        sale_dict.get("price") or sale_dict.get("total_price") or 
        sale_dict.get("cost") or sale_dict.get("total") or 
        sale_dict.get("zeny") or sale_dict.get("unit_price") or 0
    )
    currency = sale_dict.get("currency") or sale_dict.get("type") or "zeny"
    total_zeny = parse_zeny(raw_price, currency)

    if sale_dict.get("unit_price") and not (sale_dict.get("price") or sale_dict.get("total_price")):
        unit_price = parse_zeny(sale_dict.get("unit_price"), currency)
        if unit_price > 0:
            total_zeny = unit_price * amount

    return total_zeny, amount


def is_watched_item(item_name):
    name_lower = item_name.lower()
    return "[mvp]" in name_lower or "mvp card ticket" in name_lower


def process_active_listings():
    global is_initial_listings_warmup
    timestamp = time.strftime('%H:%M:%S')
    current_datetime = time.strftime('%Y-%m-%d %H:%M:%S')
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        res = requests.get(ACTIVE_VENDING_API, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        res.raise_for_status()
        data = res.json()
    except (requests.RequestException, ValueError):
        log.exception("Could not fetch or parse active market listings")
        return

    items = data if isinstance(data, list) else data.get("items", [])
    current_scan_ids = set()

    for item in items:
        name = item.get("name") or item.get("item_name") or ""
        total_zeny = parse_zeny(item.get("price"), item.get("currency"))
        
        amount = 1
        for key in ["amount", "count", "qty", "quantity"]:
            val = item.get(key)
            if val is not None:
                try:
                    amount = int(str(val).replace(",", "").strip())
                    break
                except ValueError:
                    pass

        listing_time = item.get("date") or item.get("created_at") or item.get("time") or current_datetime
        listing_id = f"{name}-{total_zeny}-{amount}"

        if is_watched_item(name):
            current_scan_ids.add(listing_id)
            if listing_id not in alerted_listings:
                if not is_initial_listings_warmup:
                    log.info("NEW LISTING: %s (x%s) for %s Zeny", name, amount, f"{total_zeny:,}")
                    send_discord_alert(
                        content_text="🚨 **NEW MATCHED ITEM LISTED ON MARKET!**",
                        title=f"👑 {name}", color=15158332, price=total_zeny, amount=amount, datetime_str=listing_time
                    )
                    time.sleep(PING_DELAY_SECONDS)
                alerted_listings.add(listing_id)

    alerted_listings.intersection_update(current_scan_ids)
    if is_initial_listings_warmup:
        log.info("Active listings warm-up complete; cached %s existing listings silently", len(alerted_listings))
        is_initial_listings_warmup = False


def process_recent_sales():
    global is_initial_sales_warmup
    timestamp = time.strftime('%H:%M:%S')
    current_datetime = time.strftime('%Y-%m-%d %H:%M:%S')
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        res = requests.get(LAST_SALES_API, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        res.raise_for_status()
        data = res.json()
    except (requests.RequestException, ValueError):
        log.exception("Could not fetch or parse recent market sales")
        return

    sales = data if isinstance(data, list) else data.get("items", [])

    for sale in sales:
        name = sale.get("name") or sale.get("item_name") or ""
        total_zeny, amount = parse_sale_data(sale)
        sold_time = sale.get("date") or sale.get("sold_at") or sale.get("time") or current_datetime
        sale_id = f"{name}-{total_zeny}-{amount}-{sold_time}"

        if is_watched_item(name):
            if sale_id not in alerted_sales:
                if not is_initial_sales_warmup:
                    log.info("ITEM SOLD: %s (x%s) for %s Zeny at %s", name, amount, f"{total_zeny:,}", sold_time)
                    send_discord_alert(
                        content_text="💰 **MATCHED ITEM HAS BEEN SOLD!**",
                        title=f"💸 SOLD: {name}", color=3066993, price=total_zeny, amount=amount, datetime_str=sold_time
                    )
                    time.sleep(PING_DELAY_SECONDS)
                alerted_sales.add(sale_id)

    if is_initial_sales_warmup:
        log.info("Sales history warm-up complete; cached %s historical sales silently", len(alerted_sales))
        is_initial_sales_warmup = False

    if len(alerted_sales) > 500:
        # Trim only a portion; clearing the whole set can re-alert recent sales.
        while len(alerted_sales) > 400:
            alerted_sales.pop()


def run():
    """Entry point function called by main.py"""
    print("==================================================")
    print(" MuhRO [MVP] & MVP Card Ticket Tracker Started")
    print(f" Checking every {CHECK_INTERVAL_SECONDS} seconds...")
    print(f"==================================================")
    
    while True:
        process_active_listings()
        process_recent_sales()
        time.sleep(CHECK_INTERVAL_SECONDS)
