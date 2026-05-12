#!/usr/bin/env python3
"""
EBV Cross-Validation — Auto price updater
Roda via GitHub Actions após fechamento NYSE (Seg-Sex 17:35 ET)
  ebv = Yahoo Finance  (o que o Heatmap mostra)
  off = FMP            (verificação independente) → Finnhub → Yahoo fallback
"""
import json, time, requests, os, sys
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH  = os.path.join(SCRIPT_DIR, '..', 'data.json')
HEADERS    = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

FMP_KEY     = os.environ.get('FMP_KEY', '')
FINNHUB_KEY = os.environ.get('FINNHUB_KEY', '')

MACRO_TK = {'FED', 'CPI', 'UNEMP', 'GDP', 'F&G'}

# ── Mapa Yahoo: nosso ticker → símbolo Yahoo ──────────────────────────────
YAHOO_MAP = {
    '^GSPC':'^GSPC', '^IXIC':'^IXIC', '^DJI':'^DJI', '^RUT':'^RUT',
    'SPY':'SPY','QQQ':'QQQ','DIA':'DIA','IWM':'IWM',
    'XLK':'XLK','XLF':'XLF','XLV':'XLV','XLY':'XLY','XLI':'XLI',
    'XLC':'XLC','XLE':'XLE','XLP':'XLP','XLB':'XLB','XLRE':'XLRE','XLU':'XLU',
    'SOXX':'SOXX','AIQ':'AIQ','CIBR':'CIBR','WCLD':'WCLD',
    'XBI':'XBI','URA':'URA','ITA':'ITA',
    'AAPL':'AAPL','MSFT':'MSFT','NVDA':'NVDA','AMZN':'AMZN',
    'META':'META','GOOGL':'GOOGL','TSLA':'TSLA','AVGO':'AVGO',
    'NFLX':'NFLX','AMD':'AMD','PANW':'PANW',
    'MU':'MU','MRVL':'MRVL','CRDO':'CRDO','ALAB':'ALAB','ARM':'ARM',
    'TSM':'TSM','AMAT':'AMAT','LRCX':'LRCX','LSCC':'LSCC','COHR':'COHR',
    'LITE':'LITE','ANET':'ANET','PLTR':'PLTR','APP':'APP','NBIS':'NBIS','CRWV':'CRWV',
    'VRT':'VRT','ETN':'ETN','IREN':'IREN','WULF':'WULF','BE':'BE',
    'WDC':'WDC','SNDK':'SNDK','STX':'STX','HPE':'HPE','APH':'APH',
    'TER':'TER','FORM':'FORM','SHOP':'SHOP','MELI':'MELI','NU':'NU',
    'AFRM':'AFRM','RDDT':'RDDT','AXON':'AXON','CIEN':'CIEN',
    'RKLB':'RKLB','KTOS':'KTOS','ASTS':'ASTS','SYM':'SYM','FTAI':'FTAI','MP':'MP',
    'O':'O','AMT':'AMT','PLD':'PLD','EQIX':'EQIX','WELL':'WELL',
    'SPG':'SPG','PSA':'PSA','VICI':'VICI','DLR':'DLR','EXR':'EXR','AVB':'AVB','VNQ':'VNQ',
    '^VIX':'^VIX',
    'DXY':'DX-Y.NYB',
    'US10Y':'^TNX',
    'BTC-USD':'BTC-USD',
    'GC=F':'GC=F','CL=F':'CL=F','SI=F':'SI=F',
    'EURUSD':'EURUSD=X','USDBRL':'USDBRL=X','USDJPY':'USDJPY=X',
}

# ── Mapa FMP: nosso ticker → símbolo FMP ─────────────────────────────────
FMP_MAP = {
    'GC=F':'GCUSD','CL=F':'CLUSD','SI=F':'SIUSD',
    'BTC-USD':'BTCUSD',
    'DXY':'DXYUSD',
    'US10Y':'^TNX',
    'EURUSD':'EURUSD','USDBRL':'USDBRL','USDJPY':'USDJPY',
}

# Finnhub não suporta bem estes (índices, futures, crypto, forex, macro)
FINNHUB_SKIP = {'^GSPC','^IXIC','^DJI','^RUT','^VIX','GC=F','CL=F','SI=F',
                'BTC-USD','EURUSD','USDBRL','USDJPY','DXY','US10Y'}


def round_px(p):
    if p >= 100: return round(p, 2)
    if p >= 1:   return round(p, 3)
    return round(p, 4)


# ── Fetch Yahoo ──────────────────────────────────────────────────────────
def fetch_yahoo_batch(syms):
    url = ('https://query1.finance.yahoo.com/v7/finance/quote'
           f'?symbols={",".join(syms)}'
           '&fields=regularMarketPrice,regularMarketPreviousClose')
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        out = {}
        for q in r.json().get('quoteResponse', {}).get('result', []):
            px = q.get('regularMarketPrice') or q.get('regularMarketPreviousClose')
            if q.get('symbol') and px:
                out[q['symbol']] = float(px)
        return out
    except Exception as e:
        print(f'  [Yahoo] erro: {e}', file=sys.stderr)
        return {}


# ── Fetch FMP ────────────────────────────────────────────────────────────
def fetch_fmp_batch(tickers):
    """tickers = nossos tickers; retorna {nosso_ticker: price}"""
    reverse = {}
    fmp_syms = []
    for tk in tickers:
        fs = FMP_MAP.get(tk, tk)
        fmp_syms.append(fs)
        reverse[fs] = tk

    url = (f'https://financialmodelingprep.com/api/v3/quote'
           f'/{",".join(fmp_syms)}?apikey={FMP_KEY}')
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        out = {}
        if isinstance(data, list):
            for q in data:
                sym = q.get('symbol', '')
                px  = q.get('price')
                if sym and px is not None:
                    orig = reverse.get(sym, sym)
                    out[orig] = float(px)
        return out
    except Exception as e:
        print(f'  [FMP] erro: {e}', file=sys.stderr)
        return {}


# ── Fetch Finnhub (sequencial, respeita 60 req/min) ─────────────────────
def fetch_finnhub(tickers):
    out = {}
    for sym in tickers:
        if sym in FINNHUB_SKIP:
            continue
        url = f'https://finnhub.io/api/v1/quote?symbol={sym}&token={FINNHUB_KEY}'
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            d = r.json()
            if d.get('c', 0) > 0:
                out[sym] = float(d['c'])
        except Exception as e:
            print(f'  [Finnhub] {sym}: {e}', file=sys.stderr)
        time.sleep(1.1)   # ≤ 55 req/min (limite free = 60/min)
    return out


# ── Fetch macro FRED ─────────────────────────────────────────────────────
def fred_latest(series):
    try:
        r = requests.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}',
                         headers=HEADERS, timeout=20)
        for line in reversed(r.text.strip().split('\n')):
            if line.startswith('DATE'): continue
            parts = line.split(',')
            if len(parts) == 2 and parts[1].strip() not in ('', '.'):
                return float(parts[1].strip())
    except Exception as e:
        print(f'  [FRED] {series}: {e}', file=sys.stderr)
    return None


def cpi_yoy():
    try:
        r = requests.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL',
                         headers=HEADERS, timeout=20)
        vals = [float(l.split(',')[1]) for l in r.text.strip().split('\n')
                if not l.startswith('DATE') and l.split(',')[1].strip() not in ('','.')]
        if len(vals) >= 13:
            return round((vals[-1] - vals[-13]) / vals[-13] * 100, 1)
    except Exception as e:
        print(f'  [CPI YoY]: {e}', file=sys.stderr)
    return None


def fear_greed():
    try:
        r = requests.get('https://production.dataviz.cnn.io/index/fearandgreed/graphdata',
                         headers=HEADERS, timeout=15)
        return round(float(r.json()['fear_and_greed']['score']), 1)
    except Exception as e:
        print(f'  [F&G]: {e}', file=sys.stderr)
    return None


# ── Main ─────────────────────────────────────────────────────────────────
def main():
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assets = data['assets']

    live = [a['tk'] for a in assets if a['tk'] not in MACRO_TK]

    # 1) Yahoo → ebv (o que o Heatmap mostra)
    print(f'[1/3] Yahoo Finance — {len(live)} ativos...')
    yahoo_syms = list(dict.fromkeys(YAHOO_MAP.get(tk, tk) for tk in live))
    y_prices_raw = {}
    for i in range(0, len(yahoo_syms), 20):
        batch = yahoo_syms[i:i+20]
        y_prices_raw.update(fetch_yahoo_batch(batch))
        print(f'  lote {i//20+1}: {len(y_prices_raw)} ok até agora')
        time.sleep(0.8)

    # Mapeia de volta para nossos tickers
    yh_rev = {v: k for k, v in YAHOO_MAP.items()}
    y_prices = {}
    for ysym, px in y_prices_raw.items():
        orig = yh_rev.get(ysym, ysym)
        y_prices[orig] = px

    # 2) FMP → off (verificação independente)
    fmp_prices = {}
    if FMP_KEY:
        print(f'[2/3] FMP — {len(live)} ativos...')
        for i in range(0, len(live), 20):
            batch = live[i:i+20]
            fmp_prices.update(fetch_fmp_batch(batch))
            print(f'  lote {i//20+1}: {len(fmp_prices)} ok até agora')
            time.sleep(0.4)
    else:
        print('[2/3] FMP — sem chave, pulando')

    # 3) Finnhub → off fallback para os que FMP não cobriu
    fmp_missed = [tk for tk in live if tk not in fmp_prices]
    fh_prices = {}
    if FINNHUB_KEY and fmp_missed:
        fh_targets = [tk for tk in fmp_missed if tk not in FINNHUB_SKIP]
        print(f'[3/3] Finnhub — {len(fh_targets)} ativos não cobertos pelo FMP...')
        fh_prices = fetch_finnhub(fh_targets)
        print(f'  Finnhub: {len(fh_prices)} ok')
    else:
        print('[3/3] Finnhub — pulando')

    # 4) Macro via FRED / CNN
    print('[Macro] FRED + CNN...')
    macro = {}
    v = fred_latest('FEDFUNDS');    macro['FED']   = round(v,2)   if v else None
    v = cpi_yoy();                  macro['CPI']   = v            if v else None
    v = fred_latest('UNRATE');      macro['UNEMP'] = round(v,1)   if v else None
    v = fred_latest('A191RL1Q225SBEA'); macro['GDP'] = round(v,1) if v else None
    v = fear_greed();               macro['F&G']   = v            if v else None
    print(f'  {macro}')

    # 5) Atualiza assets
    updated, kept, failed = 0, 0, []
    for a in assets:
        tk = a['tk']

        # Macro
        if tk in MACRO_TK:
            val = macro.get(tk if tk != 'F&G' else 'F&G')
            if tk == 'FED':   val = macro.get('FED')
            elif tk == 'CPI': val = macro.get('CPI')
            elif tk == 'UNEMP': val = macro.get('UNEMP')
            elif tk == 'GDP':   val = macro.get('GDP')
            elif tk == 'F&G':   val = macro.get('F&G')
            if val is not None:
                a['ebv'] = a['off'] = val
                updated += 1
            else:
                kept += 1
            continue

        # ebv = Yahoo
        if tk in y_prices:
            a['ebv'] = round_px(y_prices[tk])
        else:
            failed.append(f'{tk}(Y)')

        # off = FMP → Finnhub → Yahoo fallback
        if tk in fmp_prices:
            a['off'] = round_px(fmp_prices[tk])
            a['src'] = 'FMP'
            a['ok']  = True
            updated += 1
        elif tk in fh_prices:
            a['off'] = round_px(fh_prices[tk])
            a['src'] = 'Finnhub'
            a['ok']  = True
            updated += 1
        elif tk in y_prices:
            a['off'] = round_px(y_prices[tk])
            a['src'] = 'Yahoo Finance'
            a['ok']  = True
            updated += 1
            kept += 1
        else:
            failed.append(f'{tk}(off)')

    # Timestamp ET (EDT = UTC-4)
    now_utc = datetime.now(timezone.utc)
    now_et  = now_utc + timedelta(hours=-4)
    data['lastUpdated']   = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    data['lastUpdatedET'] = now_et.strftime('%d %b %Y, %H:%M ET')
    data['updatedBy']     = 'github-actions'

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'\n✅ Atualizado: {updated} | Mantido: {kept}')
    if failed: print(f'⚠️  Falhou: {", ".join(failed)}')
    print(f'📅 {data["lastUpdatedET"]}')


if __name__ == '__main__':
    main()
