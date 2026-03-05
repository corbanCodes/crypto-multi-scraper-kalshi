#!/usr/bin/env python3
"""
MULTI-CRYPTO SCRAPER WEB SERVER
===============================
Flask web server to view live data and download CSVs.
"""

import os
from flask import Flask, render_template_string, send_file, jsonify, Response
from scraper import (
    CRYPTOS, DATA_DIR, get_stats, get_live_data, get_window_results_data,
    get_csv_path, start_scrapers
)

app = Flask(__name__)

# HTML template for main page
MAIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Multi-Crypto 15-Min Kalshi Scraper</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0a;
            color: #e0e0e0;
            padding: 20px;
            min-height: 100vh;
        }
        h1 {
            text-align: center;
            margin-bottom: 10px;
            color: #fff;
        }
        .stats {
            text-align: center;
            color: #888;
            margin-bottom: 30px;
            font-size: 14px;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
            max-width: 1600px;
            margin: 0 auto;
        }
        .card {
            background: #1a1a1a;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid #333;
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        .crypto-name {
            font-size: 24px;
            font-weight: bold;
        }
        .btc { color: #f7931a; }
        .eth { color: #627eea; }
        .sol { color: #00ffa3; }
        .xrp { color: #23292f; background: linear-gradient(90deg, #fff 50%, #23292f 50%);
               -webkit-background-clip: text; background-clip: text; }
        .status {
            font-size: 12px;
            padding: 4px 10px;
            border-radius: 20px;
            background: #2a2a2a;
        }
        .status.active { background: #1a4a1a; color: #4ade80; }
        .current-market {
            background: #222;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 15px;
            font-size: 13px;
        }
        .current-market .ticker { color: #888; }
        .current-market .strike { font-size: 18px; font-weight: bold; margin: 5px 0; }
        .prices {
            display: flex;
            gap: 15px;
            margin-bottom: 15px;
        }
        .price-box {
            flex: 1;
            background: #222;
            padding: 12px;
            border-radius: 8px;
            text-align: center;
        }
        .price-label { font-size: 12px; color: #888; }
        .price-value { font-size: 20px; font-weight: bold; margin-top: 5px; }
        .yes { color: #4ade80; }
        .no { color: #f87171; }
        .downloads {
            display: flex;
            gap: 10px;
            margin-top: 15px;
        }
        .btn {
            flex: 1;
            padding: 10px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 13px;
            text-decoration: none;
            text-align: center;
            transition: all 0.2s;
        }
        .btn-primary {
            background: #3b82f6;
            color: white;
        }
        .btn-primary:hover { background: #2563eb; }
        .btn-secondary {
            background: #333;
            color: #fff;
        }
        .btn-secondary:hover { background: #444; }
        .recent-ticks {
            margin-top: 15px;
            max-height: 200px;
            overflow-y: auto;
            font-size: 12px;
            font-family: monospace;
            background: #111;
            border-radius: 8px;
            padding: 10px;
        }
        .tick {
            padding: 4px 0;
            border-bottom: 1px solid #222;
            display: flex;
            justify-content: space-between;
        }
        .tick:last-child { border-bottom: none; }
        .tick-time { color: #666; }
        .tick-price { color: #fbbf24; }
        .footer {
            text-align: center;
            margin-top: 40px;
            color: #555;
            font-size: 12px;
        }
        .stats-row {
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            color: #888;
            padding: 8px 0;
            border-top: 1px solid #333;
            margin-top: 10px;
        }
    </style>
</head>
<body>
    <h1>Multi-Crypto 15-Min Kalshi Scraper</h1>
    <div class="stats" id="global-stats">
        Runtime: <span id="runtime">--</span> |
        Refreshing every 2s
    </div>

    <div class="grid" id="crypto-grid">
        {% for crypto, config in cryptos.items() %}
        <div class="card" id="card-{{ crypto }}">
            <div class="card-header">
                <span class="crypto-name {{ crypto.lower() }}">{{ crypto }}</span>
                <span class="status" id="status-{{ crypto }}">Loading...</span>
            </div>

            <div class="current-market" id="market-{{ crypto }}">
                <div class="ticker">--</div>
                <div class="strike">Strike: --</div>
            </div>

            <div class="prices">
                <div class="price-box">
                    <div class="price-label">YES</div>
                    <div class="price-value yes" id="yes-{{ crypto }}">--c</div>
                </div>
                <div class="price-box">
                    <div class="price-label">NO</div>
                    <div class="price-value no" id="no-{{ crypto }}">--c</div>
                </div>
                <div class="price-box">
                    <div class="price-label">{{ crypto }} Price</div>
                    <div class="price-value tick-price" id="price-{{ crypto }}">--</div>
                </div>
            </div>

            <div class="downloads">
                <a href="/download/{{ crypto }}/price_log" class="btn btn-primary">Download Price Log</a>
                <a href="/download/{{ crypto }}/window_results" class="btn btn-secondary">Download Results</a>
            </div>

            <div class="stats-row">
                <span>Ticks: <span id="ticks-{{ crypto }}">0</span></span>
                <span>Windows: <span id="windows-{{ crypto }}">0</span></span>
            </div>

            <div class="recent-ticks" id="ticks-list-{{ crypto }}">
                <div class="tick"><span class="tick-time">Waiting for data...</span></div>
            </div>
        </div>
        {% endfor %}
    </div>

    <div class="footer">
        Multi-Crypto Kalshi Scraper | Data updates every second
    </div>

    <script>
        function formatPrice(price) {
            if (!price) return '--';
            if (price < 10) return price.toFixed(4);
            if (price < 1000) return price.toFixed(2);
            return price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
        }

        function updateData() {
            fetch('/api/stats')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('runtime').textContent =
                        data.runtime_hours + 'h (' + Math.floor(data.runtime_seconds / 60) + 'm)';

                    for (const crypto of ['BTC', 'ETH', 'SOL', 'XRP']) {
                        // Update stats
                        document.getElementById('ticks-' + crypto).textContent =
                            data.total_ticks[crypto] || 0;
                        document.getElementById('windows-' + crypto).textContent =
                            data.windows_completed[crypto] || 0;

                        // Update current market
                        const market = data.current_markets[crypto];
                        if (market) {
                            document.getElementById('market-' + crypto).innerHTML =
                                '<div class="ticker">' + market.ticker + '</div>' +
                                '<div class="strike">Strike: $' + formatPrice(market.strike) + '</div>';
                            document.getElementById('status-' + crypto).textContent = 'Active';
                            document.getElementById('status-' + crypto).classList.add('active');
                        }
                    }
                });

            // Update live ticks for each crypto
            for (const crypto of ['BTC', 'ETH', 'SOL', 'XRP']) {
                fetch('/api/live/' + crypto)
                    .then(r => r.json())
                    .then(ticks => {
                        if (ticks.length > 0) {
                            const latest = ticks[ticks.length - 1];
                            document.getElementById('yes-' + crypto).textContent = latest.yes_ask + 'c';
                            document.getElementById('no-' + crypto).textContent = latest.no_ask + 'c';
                            document.getElementById('price-' + crypto).textContent = '$' + formatPrice(latest.price);

                            // Update ticks list
                            const ticksList = document.getElementById('ticks-list-' + crypto);
                            let html = '';
                            const recentTicks = ticks.slice(-10).reverse();
                            for (const tick of recentTicks) {
                                const time = tick.timestamp.split('T')[1].split('.')[0];
                                html += '<div class="tick">' +
                                    '<span class="tick-time">' + time + '</span>' +
                                    '<span>Y:' + tick.yes_ask + 'c N:' + tick.no_ask + 'c</span>' +
                                    '<span class="tick-price">$' + formatPrice(tick.price) + '</span>' +
                                    '<span>' + tick.mins_left + 'm</span>' +
                                '</div>';
                            }
                            ticksList.innerHTML = html || '<div class="tick"><span class="tick-time">No data yet...</span></div>';
                        }
                    });
            }
        }

        // Initial load and refresh every 2 seconds
        updateData();
        setInterval(updateData, 2000);
    </script>
</body>
</html>
"""

CRYPTO_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ crypto }} - 15-Min Kalshi Scraper</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0a;
            color: #e0e0e0;
            padding: 20px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        h1 { color: #fff; }
        .nav a {
            color: #3b82f6;
            text-decoration: none;
            margin-left: 15px;
        }
        .nav a:hover { text-decoration: underline; }
        .section {
            background: #1a1a1a;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid #333;
        }
        h2 {
            margin-bottom: 15px;
            color: #fff;
            font-size: 18px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            font-family: monospace;
        }
        th, td {
            padding: 8px;
            text-align: left;
            border-bottom: 1px solid #333;
        }
        th { color: #888; font-weight: normal; }
        .yes { color: #4ade80; }
        .no { color: #f87171; }
        .price { color: #fbbf24; }
        .btn {
            display: inline-block;
            padding: 10px 20px;
            background: #3b82f6;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            margin-right: 10px;
        }
        .btn:hover { background: #2563eb; }
        .btn-secondary { background: #333; }
        .btn-secondary:hover { background: #444; }
    </style>
</head>
<body>
    <div class="header">
        <h1>{{ crypto }} - {{ config.name }}</h1>
        <div class="nav">
            <a href="/">Back to Dashboard</a>
        </div>
    </div>

    <div class="section">
        <h2>Downloads</h2>
        <a href="/download/{{ crypto }}/price_log" class="btn">Download Price Log CSV</a>
        <a href="/download/{{ crypto }}/window_results" class="btn btn-secondary">Download Window Results CSV</a>
    </div>

    <div class="section">
        <h2>Recent Window Results</h2>
        <table id="results-table">
            <thead>
                <tr>
                    <th>Timestamp</th>
                    <th>Ticker</th>
                    <th>Strike</th>
                    <th>Result</th>
                    <th>Final YES</th>
                    <th>Final NO</th>
                </tr>
            </thead>
            <tbody id="results-body">
                <tr><td colspan="6">Loading...</td></tr>
            </tbody>
        </table>
    </div>

    <div class="section">
        <h2>Live Price Log (Last 50 ticks)</h2>
        <table id="ticks-table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Ticker</th>
                    <th>Strike</th>
                    <th>{{ crypto }} Price</th>
                    <th>Mins Left</th>
                    <th>YES</th>
                    <th>NO</th>
                    <th>Spread</th>
                </tr>
            </thead>
            <tbody id="ticks-body">
                <tr><td colspan="8">Loading...</td></tr>
            </tbody>
        </table>
    </div>

    <script>
        const crypto = '{{ crypto }}';

        function formatPrice(price) {
            if (!price) return '--';
            if (price < 10) return price.toFixed(4);
            if (price < 1000) return price.toFixed(2);
            return price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
        }

        function updateData() {
            // Fetch live ticks
            fetch('/api/live/' + crypto)
                .then(r => r.json())
                .then(ticks => {
                    const tbody = document.getElementById('ticks-body');
                    if (ticks.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="8">No data yet...</td></tr>';
                        return;
                    }
                    let html = '';
                    for (const tick of ticks.slice().reverse()) {
                        const time = tick.timestamp.split('T')[1].split('.')[0];
                        html += '<tr>' +
                            '<td>' + time + '</td>' +
                            '<td>' + tick.ticker + '</td>' +
                            '<td>$' + formatPrice(tick.strike) + '</td>' +
                            '<td class="price">$' + formatPrice(tick.price) + '</td>' +
                            '<td>' + tick.mins_left + '</td>' +
                            '<td class="yes">' + tick.yes_ask + 'c</td>' +
                            '<td class="no">' + tick.no_ask + 'c</td>' +
                            '<td>' + tick.spread + '</td>' +
                        '</tr>';
                    }
                    tbody.innerHTML = html;
                });

            // Fetch window results
            fetch('/api/results/' + crypto)
                .then(r => r.json())
                .then(results => {
                    const tbody = document.getElementById('results-body');
                    if (results.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="6">No settled windows yet...</td></tr>';
                        return;
                    }
                    let html = '';
                    for (const r of results.slice().reverse()) {
                        const time = r.timestamp.split('T')[0] + ' ' + r.timestamp.split('T')[1].split('.')[0];
                        const resultClass = r.result === 'yes' ? 'yes' : 'no';
                        html += '<tr>' +
                            '<td>' + time + '</td>' +
                            '<td>' + r.ticker + '</td>' +
                            '<td>$' + formatPrice(r.strike) + '</td>' +
                            '<td class="' + resultClass + '">' + r.result.toUpperCase() + '</td>' +
                            '<td class="yes">' + r.final_yes + 'c</td>' +
                            '<td class="no">' + r.final_no + 'c</td>' +
                        '</tr>';
                    }
                    tbody.innerHTML = html;
                });
        }

        updateData();
        setInterval(updateData, 2000);
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(MAIN_TEMPLATE, cryptos=CRYPTOS)


@app.route('/crypto/<crypto>')
def crypto_page(crypto):
    crypto = crypto.upper()
    if crypto not in CRYPTOS:
        return "Unknown crypto", 404
    return render_template_string(CRYPTO_TEMPLATE, crypto=crypto, config=CRYPTOS[crypto])


@app.route('/api/stats')
def api_stats():
    return jsonify(get_stats())


@app.route('/api/live/<crypto>')
def api_live(crypto):
    crypto = crypto.upper()
    if crypto not in CRYPTOS:
        return jsonify([])
    return jsonify(get_live_data(crypto))


@app.route('/api/results/<crypto>')
def api_results(crypto):
    crypto = crypto.upper()
    if crypto not in CRYPTOS:
        return jsonify([])
    return jsonify(get_window_results_data(crypto))


@app.route('/download/<crypto>/<data_type>')
def download_csv(crypto, data_type):
    crypto = crypto.upper()
    if crypto not in CRYPTOS:
        return "Unknown crypto", 404
    if data_type not in ['price_log', 'window_results']:
        return "Unknown data type", 404

    csv_path = get_csv_path(crypto, data_type)
    if not os.path.exists(csv_path):
        return "No data yet", 404

    return send_file(
        csv_path,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"{crypto.lower()}_{data_type}.csv"
    )


def run_server():
    """Start the web server"""
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting web server on port {port}")
    app.run(host='0.0.0.0', port=port, threaded=True)


# Start scrapers when module loads (for gunicorn --preload)
print("=" * 70)
print("MULTI-CRYPTO 15-MINUTE KALSHI SCRAPER + WEB SERVER")
print("=" * 70)
print(f"Tracking: {', '.join(CRYPTOS.keys())}")
print(f"Data directory: {DATA_DIR}")
print("=" * 70)
print("Starting scraper threads...")
start_scrapers()
print("Scrapers running!")


if __name__ == "__main__":
    # Start web server (scrapers already started above)
    run_server()
