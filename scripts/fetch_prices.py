#!/usr/bin/env python3
"""
EBV Cross-Validation — Auto price updater
Runs via GitHub Actions after NYSE close (Mon-Fri 17:35 ET)
Updates data.json with fresh prices from Yahoo Finance + FRED + CNN
"""
import json
import time
import requests
from datetime import datetime, timezone, timedelta
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH  = os.path.join(SCRIPT_DIR, '..', 'data.json')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# data.json tk → Yahoo Finance symbol
YAHOO_MAP = {
    '^GSPC':'^GSPC', '^IXIC':'^IXIC', '^DJI':'^DJI', '^RUT':'^RUT',
    'SPY':'SPY', 'QQQ':'QQQ', 'DIA':'DIA', 'IWM':'IWM',
    'XLK':'XLK', 'XLF':'XLF', 'XLV':'XLV', 'XLY':'XLY', 'XLI':'XLI',
    'XLC':'XLC', 'XLE':'XLE', 'XLP':'XLP', 'XLB':'XLB', 'XLRE':'XLRE', 'XLU':'XLU',
    'SOXX':'SOXX', 'AIQ':'AIQ', 'CIBR':'CIBR', 'WCLD':'WCLD',
    'XBI':'XBI', 'URA':'URA', 'ITA':'ITA',
    'AAPL':'AAPL', 'MSFT':'MSFT', 'NVDA':'NVDA', 'AMZN':'AMZN',
    'META':'META', 'GOOGL':'GOOGL', 'TSLA':'TSLA', 'AVGO':'AVGO',
    'NFLX':'NFLX', 'AMD':'AMD', 'PANW':'PANW',
    'MU':'MU', 'MRVL':'MRVL', 'CRDO':'CRDO', 'ALAB':'ALAB', 'ARM':'ARM',
    'TSM':'TSM', 'AMAT':'AMAT', 'LRCX':'LRCX', 'LSCC':'LSCC', 'COHR':'COHR',
    'LITE':'LITE', 'ANET':'ANET', 'PLTR':'PLTR', 'APP':'APP',
    'NBIS':'NBIS', 'CRWV':'CRWV',
    'VRT':'VRT', 'ETN':'ETN', 'IREN':'IREN', 'WULF':'WULF', 'BE':'BE',
    'WDC':'WDC', 'SNDK':'SNDK', 'STX':'STX', 'HPE':'HPE', 'APH':'APH',
    'TER':'TER', 'FORM':'FORM', 'SHOP':'SHOP', 'MELI':'MELI', 'NU':'NU',
    'AFRM':'AFRM', 'RDDT':'RDDT', 'AXON':'AXON', 'CIEN':'CIEN',
    'RKLB':'RKLB', 'KTOS':'KTOS', 'ASTS':'ASTS', 'SYM':'SYM',
    'FTAI':'FTAI', 'MP':'MP',
    'O':'O', 'AMT':'AMT', 'PLD':'PLD', 'EQIX':'EQIX', 'WELL':'WELL',
    'SPG':'SPG', 'PSA':'PSA', 'VICI':'VICI', 'DLR':'DLR', 'EXR':'EXR',
    'AVB':'AVB', 'VNQ':'VNQ',
    '^VIX':'^VIX',
    'DXY':'DX-Y.NYB',
    'US10Y':'^TNX',
    'BTC-USD':'BTC-USD',
    'GC=F':'GC=F', 'CL=F':'CL=F', 'SI=F':'SI=F',
    'EURUSD':'EURUSD=X',
    'USDBRL':'USDBRL=X',
    'USDJPY':'USDJPY=X',
}

# Tickers skipped (macro updated from FRED/CNN separately)
MACRO_TK = {'FED', 'CPI', 'UNEMP', 'GDP', 'F&G'}


def fetch_yahoo_batch(symbols):
    joined = ','.join(symbols)
    url = (
        'https://query1.finance.yahoo.com/v7/finance/quote'
        f'?symbols={joined}'
        '&fields=regularMarketPrice,regularMarketPreviousClose'
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        results = r.json().get('quoteResponse', {}).get('result', [])
        out = {}
        for q in results:
            sym = q.get('symbol')
            px  = q.get('regularMarketPrice') or q.get('regularMarketPreviousClose')
            if sym and px:
                out[sym] = float(px)
        return out
    except Exception as e:
        print(f'  [Yahoo error] {symbols[:3]}...: {e}', file=sys.stderr)
        return {}


def fetch_fred_latest(series_id):
    """Get latest non-missing value from FRED (no API key needed)."""
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        lines = r.text.strip().split('\n')
        for line in reversed(lines):
            if line.startswith('DATE'):
                continue
            parts = line.split(',')
            if len(parts) == 2 and parts[1].strip() not in ('', '.'):
                return float(parts[1].strip())
    except Exception as e:
        print(f'  [FRED error] {series_id}: {e}', file=sys.stderr)
    return None


def fetch_cpi_yoy():
    """Calculate CPI YoY% from FRED CPIAUCSL monthly series."""
    url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL'
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        vals = []
        for line in r.text.strip().split('\n'):
            if line.startswith('DATE'):
                continue
            parts = line.split(',')
            if len(parts) == 2 and parts[1].strip() not in ('', '.'):
                vals.append(float(parts[1].strip()))
        if len(vals) >= 13:
            return round((vals[-1] - vals[-13]) / vals[-13] * 100, 1)
    except Exception as e:
        print(f'  [CPI error]: {e}', file=sys.stderr)
    return None


def fetch_fear_greed():
    """Fetch CNN Fear & Greed current score."""
    url = 'https://production.dataviz.cnn.io/index/fearandgreed/graphdata'
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        score = r.json()['fear_and_greed']['score']
        return round(float(score), 1)
    except Exception as e:
        print(f'  [F&G error]: {e}', file=sys.stderr)
    return None


def round_price(p):
    if p >= 100:
        return round(p, 2)
    if p >= 1:
        return round(p, 3)
    return round(p, 4)


def main():
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assets = data['assets']

    # Collect unique Yahoo symbols
    yahoo_syms = list(dict.fromkeys(
        YAHOO_MAP[a['tk']] for a in assets
        if a['tk'] in YAHOO_MAP and a['tk'] not in MACRO_TK
    ))

    print(f'Fetching {len(yahoo_syms)} Yahoo symbols in batches of 20...')
    yahoo_prices = {}
    for i in range(0, len(yahoo_syms), 20):
        batch = yahoo_syms[i:i+20]
        prices = fetch_yahoo_batch(batch)
        yahoo_prices.update(prices)
        print(f'  Batch {i//20+1}: {len(prices)}/{len(batch)} ok')
        time.sleep(0.8)

    print('Fetching macro from FRED...')
    macro = {}

    fed = fetch_fred_latest('FEDFUNDS')
    if fed is not None:
        macro['FED'] = round(fed, 2)

    cpi = fetch_cpi_yoy()
    if cpi is not None:
        macro['CPI'] = cpi

    unemp = fetch_fred_latest('UNRATE')
    if unemp is not None:
        macro['UNEMP'] = round(unemp, 1)

    # Real GDP QoQ annualized growth rate
    gdp = fetch_fred_latest('A191RL1Q225SBEA')
    if gdp is not None:
        macro['GDP'] = round(gdp, 1)

    print('Fetching Fear & Greed from CNN...')
    fg = fetch_fear_greed()
    if fg is not None:
        macro['FG'] = fg

    print(f'Macro fetched: {macro}')

    updated, kept, failed = 0, 0, []

    for asset in assets:
        tk = asset['tk']

        # ── Macro indicators ──
        if tk == 'FED':
            if 'FED' in macro:
                asset['ebv'] = asset['off'] = macro['FED']
                updated += 1
            else:
                kept += 1
            continue
        if tk == 'CPI':
            if 'CPI' in macro:
                asset['ebv'] = asset['off'] = macro['CPI']
                updated += 1
            else:
                kept += 1
            continue
        if tk == 'UNEMP':
            if 'UNEMP' in macro:
                asset['ebv'] = asset['off'] = macro['UNEMP']
                updated += 1
            else:
                kept += 1
            continue
        if tk == 'GDP':
            if 'GDP' in macro:
                asset['ebv'] = asset['off'] = macro['GDP']
                updated += 1
            else:
                kept += 1
            continue
        if tk == 'F&G':
            if 'FG' in macro:
                asset['ebv'] = asset['off'] = macro['FG']
                updated += 1
            else:
                kept += 1
            continue

        # ── Yahoo-sourced assets ──
        yt = YAHOO_MAP.get(tk)
        if not yt:
            failed.append(tk)
            continue

        px = yahoo_prices.get(yt)
        if px is None:
            failed.append(tk)
            kept += 1
            continue

        asset['ebv'] = round_price(px)
        asset['off'] = round_price(px)
        asset['ok']  = True
        asset['src'] = 'Yahoo Finance'
        updated += 1

    # Timestamp in ET (EDT = UTC-4, EST = UTC-5)
    now_utc = datetime.now(timezone.utc)
    et_offset = timedelta(hours=-4)  # EDT (Mar–Nov); script runs after US summer clock
    now_et = now_utc + et_offset
    data['lastUpdated']   = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    data['lastUpdatedET'] = now_et.strftime('%d %b %Y, %H:%M ET')
    data['updatedBy']     = 'github-actions'

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'\n✅ Updated: {updated} | Kept unchanged: {kept}')
    if failed:
        print(f'⚠️  No price for: {", ".join(failed)}')
    print(f'📅 {data["lastUpdatedET"]}')


if __name__ == '__main__':
    main()
