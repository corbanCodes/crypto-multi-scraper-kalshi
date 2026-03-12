#!/usr/bin/env python3
"""
MULTI-CRYPTO 15-MINUTE KALSHI SCRAPER
=====================================
Second-by-second logging for BTC, ETH, SOL, XRP markets.

Stores data in CSV files and serves via web interface.
Each crypto has two CSVs:
  - {crypto}_price_log.csv: Second-by-second tick data
  - {crypto}_window_results.csv: Settled window outcomes
"""

import os
import csv
import time
import threading
from datetime import datetime, timezone
from collections import deque
import requests

# Kalshi API
KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"

# Caches to handle API failures gracefully
_strike_cache = {}      # ticker -> strike price
_price_cache = {}       # crypto -> last known price
_price_cache_time = {}  # crypto -> timestamp of last price

# Crypto configurations
CRYPTOS = {
    'BTC': {
        'series_ticker': 'KXBTC15M',
        'kraken_pair': 'XBTUSD',
        'name': 'Bitcoin'
    },
    'ETH': {
        'series_ticker': 'KXETH15M',
        'kraken_pair': 'ETHUSD',
        'name': 'Ethereum'
    },
    'SOL': {
        'series_ticker': 'KXSOL15M',
        'kraken_pair': 'SOLUSD',
        'name': 'Solana'
    },
    'XRP': {
        'series_ticker': 'KXXRP15M',
        'kraken_pair': 'XRPUSD',
        'name': 'XRP'
    }
}

# Data directory - use Railway volume mount if available, otherwise local
# Set DATA_DIR env var in Railway to your volume mount path (e.g., /data)
DATA_DIR = os.environ.get('DATA_DIR', '/data')
os.makedirs(DATA_DIR, exist_ok=True)


def verify_volume_storage():
    """Verify volume storage is working and log detailed status"""
    print("=" * 70)
    print("VOLUME STORAGE CHECK")
    print("=" * 70)

    # 1. Check directory exists
    if os.path.exists(DATA_DIR):
        print(f"[OK] Data directory exists: {DATA_DIR}")
    else:
        print(f"[ERROR] Data directory does NOT exist: {DATA_DIR}")
        return False

    # 2. Check if writable by writing a test file
    test_file = os.path.join(DATA_DIR, '.write_test')
    try:
        with open(test_file, 'w') as f:
            f.write(f"Volume test: {datetime.now().isoformat()}")
        os.remove(test_file)
        print(f"[OK] Directory is writable")
    except Exception as e:
        print(f"[ERROR] Directory is NOT writable: {e}")
        return False

    # 3. Check disk space
    try:
        import shutil
        total, used, free = shutil.disk_usage(DATA_DIR)
        total_gb = total / (1024**3)
        used_gb = used / (1024**3)
        free_gb = free / (1024**3)
        print(f"[OK] Disk space: {free_gb:.2f} GB free / {total_gb:.2f} GB total ({used_gb:.2f} GB used)")
    except Exception as e:
        print(f"[WARN] Could not check disk space: {e}")

    # 4. List existing CSV files and their sizes
    csv_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
    if csv_files:
        print(f"[OK] Found {len(csv_files)} existing CSV files:")
        total_size = 0
        for csv_file in sorted(csv_files):
            file_path = os.path.join(DATA_DIR, csv_file)
            size = os.path.getsize(file_path)
            total_size += size
            row_count = sum(1 for _ in open(file_path)) - 1  # -1 for header
            size_kb = size / 1024
            print(f"     - {csv_file}: {row_count:,} rows ({size_kb:.1f} KB)")
        print(f"[OK] Total data stored: {total_size / (1024*1024):.2f} MB")
    else:
        print(f"[INFO] No existing CSV files (fresh start)")

    # 5. Check if this is a Railway environment
    railway_env = os.environ.get('RAILWAY_ENVIRONMENT')
    if railway_env:
        print(f"[OK] Running on Railway: {railway_env}")
    else:
        print(f"[INFO] Not running on Railway (local environment)")

    print("=" * 70)
    print("VOLUME CHECK COMPLETE - Storage is working!")
    print("=" * 70)
    return True


# Run volume check on startup
verify_volume_storage()

# In-memory buffers for live display (last 100 ticks per crypto)
live_data = {crypto: deque(maxlen=100) for crypto in CRYPTOS}
window_results = {crypto: deque(maxlen=50) for crypto in CRYPTOS}
current_markets = {crypto: None for crypto in CRYPTOS}
stats = {
    'start_time': datetime.now(),
    'total_ticks': {crypto: 0 for crypto in CRYPTOS},
    'windows_completed': {crypto: 0 for crypto in CRYPTOS}
}

# Thread lock for data access
data_lock = threading.Lock()


def get_crypto_price(kraken_pair, crypto=None):
    """Get crypto price from Kraken with caching and retry"""
    global _price_cache, _price_cache_time

    for attempt in range(3):  # Retry up to 3 times
        try:
            resp = requests.get(
                "https://api.kraken.com/0/public/Ticker",
                params={"pair": kraken_pair},
                timeout=5
            )
            resp.raise_for_status()
            result = resp.json().get('result', {})
            # Kraken returns weird key names, get first result
            for key, data in result.items():
                price = float(data['c'][0])
                # Cache the price
                if crypto:
                    _price_cache[crypto] = price
                    _price_cache_time[crypto] = time.time()
                return price
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(0.5)  # Brief wait before retry
            continue

    # If all retries failed, return cached price if recent (within 60 seconds)
    if crypto and crypto in _price_cache:
        age = time.time() - _price_cache_time.get(crypto, 0)
        if age < 60:
            return _price_cache[crypto]

    return None


def api_get(endpoint, params=None, retries=3):
    """Generic Kalshi API call with retry logic"""
    for attempt in range(retries):
        try:
            resp = requests.get(f"{KALSHI_API}/{endpoint}", params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(0.5)  # Brief wait before retry
            continue
    return None


def get_active_market(series_ticker):
    """Get the currently active market for a series - picks the one expiring soonest that's still open"""
    data = api_get("events", {"series_ticker": series_ticker, "status": "open"})
    if not data or not data.get('events'):
        return None
    event = data['events'][0]
    markets = api_get("markets", {"event_ticker": event['event_ticker']})
    if not markets or not markets.get('markets'):
        return None

    now = datetime.now(timezone.utc)

    # Filter to markets that haven't closed yet and sort by close time
    def get_secs_left(m):
        close_str = m.get('close_time', '')
        if not close_str:
            return -9999
        try:
            close = datetime.fromisoformat(close_str.replace('Z', '+00:00'))
            return (close - now).total_seconds()
        except:
            return -9999

    # Get markets that are still open (close_time in future)
    active_markets = [(m, get_secs_left(m)) for m in markets['markets']]
    active_markets = [(m, secs) for m, secs in active_markets if secs > 0]

    if not active_markets:
        return None

    # Sort by secs_left ascending (soonest first)
    active_markets.sort(key=lambda x: x[1])
    return active_markets[0][0]


def get_market_details(ticker):
    """Get full market details"""
    data = api_get(f"markets/{ticker}")
    return data.get('market') if data else None


def get_orderbook(ticker):
    """Get orderbook with depth analysis"""
    data = api_get(f"markets/{ticker}/orderbook")
    if not data:
        return None

    orderbook = data.get('orderbook', {})
    yes_bids = orderbook.get('yes', [])
    no_bids = orderbook.get('no', [])

    def depth_within_cents(bids, cents):
        if not bids:
            return 0
        best = bids[0][0]
        return sum(level[1] for level in bids if abs(level[0] - best) <= cents)

    return {
        'yes_depth_1': depth_within_cents(yes_bids, 1),
        'yes_depth_3': depth_within_cents(yes_bids, 3),
        'yes_depth_all': sum(level[1] for level in yes_bids) if yes_bids else 0,
        'yes_levels': len(yes_bids),
        'no_depth_1': depth_within_cents(no_bids, 1),
        'no_depth_3': depth_within_cents(no_bids, 3),
        'no_depth_all': sum(level[1] for level in no_bids) if no_bids else 0,
        'no_levels': len(no_bids),
    }


def get_settled_markets(series_ticker):
    """Get recently settled markets"""
    data = api_get("markets", {"series_ticker": series_ticker, "status": "settled", "limit": 20})
    return data.get('markets', []) if data else []


def secs_until_close(close_time_str):
    """Calculate seconds until market closes"""
    if not close_time_str:
        return None
    try:
        close = datetime.fromisoformat(close_time_str.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        return (close - now).total_seconds()
    except:
        return None


def get_csv_path(crypto, data_type):
    """Get path to CSV file"""
    return os.path.join(DATA_DIR, f"{crypto.lower()}_{data_type}.csv")


def count_csv_rows(filepath):
    """Count rows in a CSV file (excluding header)"""
    if not os.path.exists(filepath):
        return 0
    try:
        with open(filepath, 'r') as f:
            return max(0, sum(1 for _ in f) - 1)  # -1 for header
    except:
        return 0


def init_csv_files():
    """Initialize CSV files with headers if they don't exist, and load existing counts"""
    price_log_headers = [
        'timestamp', 'ticker', 'strike_price', 'crypto_price', 'mins_left',
        'yes_ask', 'no_ask', 'yes_bid', 'no_bid',
        'yes_depth_1', 'yes_depth_3', 'yes_depth_all',
        'no_depth_1', 'no_depth_3', 'no_depth_all',
        'yes_levels', 'no_levels', 'spread'
    ]

    window_results_headers = [
        'timestamp', 'ticker', 'strike_price', 'result',
        'final_yes_price', 'final_no_price'
    ]

    for crypto in CRYPTOS:
        # Price log
        price_path = get_csv_path(crypto, 'price_log')
        if not os.path.exists(price_path):
            with open(price_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(price_log_headers)

        # Window results
        results_path = get_csv_path(crypto, 'window_results')
        if not os.path.exists(results_path):
            with open(results_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(window_results_headers)

        # Load existing counts into stats
        existing_ticks = count_csv_rows(price_path)
        existing_windows = count_csv_rows(results_path)

        with data_lock:
            stats['total_ticks'][crypto] = existing_ticks
            stats['windows_completed'][crypto] = existing_windows

        if existing_ticks > 0 or existing_windows > 0:
            print(f"[{crypto}] Loaded existing data: {existing_ticks:,} ticks, {existing_windows} windows")


def log_tick(crypto, ticker, strike, crypto_price, secs_left, market, orderbook):
    """Log a tick to CSV and memory"""
    now = datetime.now(timezone.utc)
    mins_left = secs_left / 60 if secs_left else 0

    # Kalshi API now returns prices in dollars with _dollars suffix
    # Convert to cents (multiply by 100) for consistency with existing data
    yes_ask = int(float(market.get('yes_ask_dollars', 0)) * 100)
    no_ask = int(float(market.get('no_ask_dollars', 0)) * 100)
    yes_bid = int(float(market.get('yes_bid_dollars', 0)) * 100)
    no_bid = int(float(market.get('no_bid_dollars', 0)) * 100)
    spread = abs(yes_ask - (100 - no_ask))

    row = [
        now.isoformat(),
        ticker,
        strike,
        crypto_price or 0,
        round(mins_left, 2),
        yes_ask,
        no_ask,
        yes_bid,
        no_bid,
        orderbook.get('yes_depth_1', 0) if orderbook else 0,
        orderbook.get('yes_depth_3', 0) if orderbook else 0,
        orderbook.get('yes_depth_all', 0) if orderbook else 0,
        orderbook.get('no_depth_1', 0) if orderbook else 0,
        orderbook.get('no_depth_3', 0) if orderbook else 0,
        orderbook.get('no_depth_all', 0) if orderbook else 0,
        orderbook.get('yes_levels', 0) if orderbook else 0,
        orderbook.get('no_levels', 0) if orderbook else 0,
        spread
    ]

    # Write to CSV
    with open(get_csv_path(crypto, 'price_log'), 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(row)

    # Update memory
    tick_data = {
        'timestamp': now.isoformat(),
        'ticker': ticker,
        'strike': strike,
        'price': crypto_price,
        'mins_left': round(mins_left, 2),
        'yes_ask': yes_ask,
        'no_ask': no_ask,
        'spread': spread
    }

    with data_lock:
        live_data[crypto].append(tick_data)
        stats['total_ticks'][crypto] += 1


def log_window_result(crypto, ticker, strike, result, final_yes, final_no):
    """Log window result to CSV and memory"""
    now = datetime.now(timezone.utc)

    row = [
        now.isoformat(),
        ticker,
        strike,
        result,
        final_yes,
        final_no
    ]

    # Write to CSV
    with open(get_csv_path(crypto, 'window_results'), 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(row)

    # Update memory
    result_data = {
        'timestamp': now.isoformat(),
        'ticker': ticker,
        'strike': strike,
        'result': result,
        'final_yes': final_yes,
        'final_no': final_no
    }

    with data_lock:
        window_results[crypto].append(result_data)
        stats['windows_completed'][crypto] += 1


def log(msg):
    """Print timestamped log message"""
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}", flush=True)


def scrape_crypto(crypto, config):
    """Scraper thread for a single crypto"""
    global _strike_cache

    series_ticker = config['series_ticker']
    kraken_pair = config['kraken_pair']
    name = config['name']

    log(f"Starting {name} ({crypto}) scraper - Series: {series_ticker}")

    last_ticker = None
    settled_tickers = set()
    no_market_count = 0  # Track consecutive "no market" to reduce log spam

    # Pre-populate settled_tickers with already-settled markets (don't count historical)
    try:
        historical = get_settled_markets(series_ticker)
        for m in historical:
            t = m.get('ticker')
            if t:
                settled_tickers.add(t)
        log(f"[{crypto}] Ignoring {len(settled_tickers)} historical settlements")
    except Exception as e:
        log(f"[{crypto}] Failed to get historical: {e}")

    while True:
        try:
            loop_start = time.time()

            # Check for NEW settlements only
            settled = get_settled_markets(series_ticker)
            for market in settled:
                ticker = market.get('ticker')
                if ticker and ticker not in settled_tickers:
                    result = market.get('result')
                    if result:
                        strike = market.get('floor_strike', 0)
                        final_yes = market.get('yes_ask', 0)
                        final_no = market.get('no_ask', 0)

                        log_window_result(crypto, ticker, strike, result, final_yes, final_no)
                        settled_tickers.add(ticker)

                        outcome = "UP (YES)" if result == 'yes' else "DOWN (NO)"
                        log(f"[{crypto}] SETTLED: {ticker} -> {outcome}")

            # Get current market
            market = get_active_market(series_ticker)
            if not market:
                no_market_count += 1
                # Only log every 10th occurrence to reduce spam
                if no_market_count == 1 or no_market_count % 10 == 0:
                    log(f"[{crypto}] No active market found (x{no_market_count}), waiting...")
                time.sleep(2)
                continue

            # Reset counter when we find a market
            no_market_count = 0

            ticker = market.get('ticker')
            if not ticker:
                time.sleep(1)
                continue

            # Get full details
            details = get_market_details(ticker)
            if not details:
                log(f"[{crypto}] Failed to get details for {ticker}")
                time.sleep(1)
                continue

            secs_left = secs_until_close(details.get('close_time'))

            if secs_left is None or secs_left < -60:
                time.sleep(1)
                continue

            # Get strike price with caching
            strike = details.get('floor_strike', 0)
            if strike and strike > 0:
                # Cache valid strike price
                _strike_cache[ticker] = strike
            elif ticker in _strike_cache:
                # Use cached strike if API returned 0
                strike = _strike_cache[ticker]

            # New window detected
            if ticker != last_ticker:
                price = get_crypto_price(kraken_pair, crypto)

                # Only announce new window if we have valid strike
                if strike > 0:
                    log(f"[{crypto}] NEW WINDOW: {ticker} | Strike: ${strike:,.2f} | {secs_left/60:.1f}m left")
                    last_ticker = ticker

                    with data_lock:
                        current_markets[crypto] = {
                            'ticker': ticker,
                            'strike': strike,
                            'start_time': datetime.now().isoformat()
                        }
                else:
                    # Wait for valid strike data before announcing
                    log(f"[{crypto}] Waiting for strike price for {ticker}...")
                    time.sleep(1)
                    continue

            # Log tick if window is active
            if secs_left >= 0:
                price = get_crypto_price(kraken_pair, crypto)
                orderbook = get_orderbook(ticker)

                # Validate data before logging - skip if critical data is missing
                if strike == 0:
                    log(f"[{crypto}] Skipping tick - no strike price for {ticker}")
                    time.sleep(1)
                    continue

                if price is None or price == 0:
                    log(f"[{crypto}] Skipping tick - no crypto price")
                    time.sleep(1)
                    continue

                log_tick(crypto, ticker, strike, price, secs_left, details, orderbook)

                # Log every 30 ticks
                tick_count = stats['total_ticks'].get(crypto, 0)
                if tick_count % 30 == 0:
                    log(f"[{crypto}] Tick #{tick_count} | {secs_left/60:.1f}m | Price: ${price:,.2f}")

            # Calculate sleep to maintain ~1 second intervals
            elapsed = time.time() - loop_start
            sleep_time = max(0.1, 1.0 - elapsed)
            time.sleep(sleep_time)

        except Exception as e:
            log(f"[{crypto}] ERROR: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)


def get_volume_stats():
    """Get volume/storage statistics"""
    try:
        import shutil
        total, used, free = shutil.disk_usage(DATA_DIR)

        # Calculate total CSV data size
        csv_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
        total_csv_size = sum(
            os.path.getsize(os.path.join(DATA_DIR, f)) for f in csv_files
        )

        return {
            'data_dir': DATA_DIR,
            'total_gb': round(total / (1024**3), 2),
            'used_gb': round(used / (1024**3), 2),
            'free_gb': round(free / (1024**3), 2),
            'csv_count': len(csv_files),
            'csv_size_mb': round(total_csv_size / (1024**2), 2),
            'volume_ok': True
        }
    except Exception as e:
        return {
            'data_dir': DATA_DIR,
            'error': str(e),
            'volume_ok': False
        }


def get_stats():
    """Get current scraper stats"""
    with data_lock:
        runtime = (datetime.now() - stats['start_time']).total_seconds()
        return {
            'runtime_hours': round(runtime / 3600, 2),
            'runtime_seconds': int(runtime),
            'total_ticks': dict(stats['total_ticks']),
            'windows_completed': dict(stats['windows_completed']),
            'current_markets': dict(current_markets),
            'volume': get_volume_stats()
        }


def get_live_data(crypto):
    """Get recent ticks for a crypto"""
    with data_lock:
        return list(live_data.get(crypto, []))


def get_window_results_data(crypto):
    """Get recent window results for a crypto"""
    with data_lock:
        return list(window_results.get(crypto, []))


def start_scrapers():
    """Start scraper threads for all cryptos"""
    init_csv_files()

    threads = []
    for crypto, config in CRYPTOS.items():
        t = threading.Thread(target=scrape_crypto, args=(crypto, config), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.25)  # Stagger starts slightly

    return threads


if __name__ == "__main__":
    print("=" * 70)
    print("MULTI-CRYPTO 15-MINUTE KALSHI SCRAPER")
    print("=" * 70)
    print(f"Tracking: {', '.join(CRYPTOS.keys())}")
    print(f"Data directory: {DATA_DIR}")
    print("=" * 70)

    threads = start_scrapers()

    try:
        while True:
            time.sleep(60)
            s = get_stats()
            log(f"Stats: Runtime {s['runtime_hours']}h | Ticks: {s['total_ticks']} | Windows: {s['windows_completed']}")
    except KeyboardInterrupt:
        print("\nStopping scrapers...")
