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

# Data directory
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

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


def get_crypto_price(kraken_pair):
    """Get crypto price from Kraken"""
    try:
        resp = requests.get(
            "https://api.kraken.com/0/public/Ticker",
            params={"pair": kraken_pair},
            timeout=3
        )
        resp.raise_for_status()
        result = resp.json().get('result', {})
        # Kraken returns weird key names, get first result
        for key, data in result.items():
            return float(data['c'][0])
        return None
    except Exception as e:
        return None


def api_get(endpoint, params=None):
    """Generic Kalshi API call"""
    try:
        resp = requests.get(f"{KALSHI_API}/{endpoint}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except:
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


def init_csv_files():
    """Initialize CSV files with headers if they don't exist"""
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


def log_tick(crypto, ticker, strike, crypto_price, secs_left, market, orderbook):
    """Log a tick to CSV and memory"""
    now = datetime.now(timezone.utc)
    mins_left = secs_left / 60 if secs_left else 0

    yes_ask = market.get('yes_ask', 0)
    no_ask = market.get('no_ask', 0)
    yes_bid = market.get('yes_bid', 0)
    no_bid = market.get('no_bid', 0)
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
    series_ticker = config['series_ticker']
    kraken_pair = config['kraken_pair']
    name = config['name']

    log(f"Starting {name} ({crypto}) scraper - Series: {series_ticker}")

    last_ticker = None
    settled_tickers = set()

    while True:
        try:
            loop_start = time.time()

            # Check for settlements
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
                time.sleep(1)
                continue

            details = get_market_details(market['ticker'])
            if not details:
                time.sleep(0.5)
                continue

            ticker = details['ticker']
            secs_left = secs_until_close(details.get('close_time'))

            if secs_left is None or secs_left < -60:
                time.sleep(1)
                continue

            # New window
            if ticker != last_ticker:
                strike = details.get('floor_strike', 0)
                price = get_crypto_price(kraken_pair)

                log(f"[{crypto}] NEW WINDOW: {ticker} | Strike: ${strike:,.2f}")
                last_ticker = ticker

                with data_lock:
                    current_markets[crypto] = {
                        'ticker': ticker,
                        'strike': strike,
                        'start_time': datetime.now().isoformat()
                    }

            # Log tick if window is active
            if secs_left >= 0:
                strike = details.get('floor_strike', 0)
                price = get_crypto_price(kraken_pair)
                orderbook = get_orderbook(ticker)

                log_tick(crypto, ticker, strike, price, secs_left, details, orderbook)

            # Calculate sleep to maintain ~1 second intervals
            elapsed = time.time() - loop_start
            sleep_time = max(0.1, 1.0 - elapsed)
            time.sleep(sleep_time)

        except Exception as e:
            log(f"[{crypto}] ERROR: {e}")
            time.sleep(5)


def get_stats():
    """Get current scraper stats"""
    with data_lock:
        runtime = (datetime.now() - stats['start_time']).total_seconds()
        return {
            'runtime_hours': round(runtime / 3600, 2),
            'runtime_seconds': int(runtime),
            'total_ticks': dict(stats['total_ticks']),
            'windows_completed': dict(stats['windows_completed']),
            'current_markets': dict(current_markets)
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
