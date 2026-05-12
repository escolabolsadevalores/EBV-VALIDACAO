const https = require('https');

const FINNHUB_KEY  = process.env.FINNHUB_KEY;
const FINNHUB_BASE = 'https://finnhub.io/api/v1';

// Finnhub só funciona bem com ações/ETFs americanos padrão
// Excluir: índices com ^, futures, crypto, forex, macro
const SKIP_PATTERN = /^\^|=F$|=X$|USD$|BRL$|JPY$|DXY|US10Y|BTC/i;

function fetchOne(sym) {
  return new Promise((resolve) => {
    const url = `${FINNHUB_BASE}/quote?symbol=${encodeURIComponent(sym)}&token=${FINNHUB_KEY}`;
    https.get(url, { timeout: 8000 }, res => {
      let raw = '';
      res.on('data', c => raw += c);
      res.on('end', () => {
        try {
          const d = JSON.parse(raw);
          resolve({ sym, price: d.c > 0 ? d.c : null });
        } catch { resolve({ sym, price: null }); }
      });
    }).on('error', () => resolve({ sym, price: null }))
      .on('timeout', () => resolve({ sym, price: null }));
  });
}

exports.handler = async (event) => {
  if (!FINNHUB_KEY) return { statusCode: 500, body: 'FINNHUB_KEY not set' };

  const symbols = (event.queryStringParameters?.symbols || '')
    .split(',')
    .filter(s => s && !SKIP_PATTERN.test(s))
    .slice(0, 20); // máx 20 por chamada

  if (!symbols.length) return { statusCode: 200, body: '{}' };

  const results = await Promise.allSettled(symbols.map(fetchOne));
  const out = {};
  results.forEach(r => {
    if (r.status === 'fulfilled' && r.value.price != null) {
      out[r.value.sym] = r.value.price;
    }
  });

  return {
    statusCode: 200,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
    body: JSON.stringify(out)
  };
};
