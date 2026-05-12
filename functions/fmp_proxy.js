const https = require('https');

const FMP_KEY  = process.env.FMP_KEY;
const FMP_BASE = 'https://financialmodelingprep.com/api/v3';

// Mapa: nosso ticker → símbolo FMP
const FMP_MAP = {
  'GC=F':    'GCUSD',
  'CL=F':    'CLUSD',
  'SI=F':    'SIUSD',
  'BTC-USD': 'BTCUSD',
  'DXY':     'DXYUSD',
  'US10Y':   '^TNX',
};

function fetchJSON(url) {
  return new Promise((resolve, reject) => {
    https.get(url, { timeout: 15000 }, res => {
      let raw = '';
      res.on('data', c => raw += c);
      res.on('end', () => {
        try { resolve(JSON.parse(raw)); } catch(e) { reject(e); }
      });
    }).on('error', reject).on('timeout', () => reject(new Error('timeout')));
  });
}

exports.handler = async (event) => {
  if (!FMP_KEY) return { statusCode: 500, body: 'FMP_KEY not set' };

  const raw = (event.queryStringParameters?.symbols || '').split(',').filter(Boolean);
  if (!raw.length) return { statusCode: 400, body: 'Missing symbols' };

  // Constrói mapa reverso: fmpSym → nosso ticker
  const reverse = {};
  const fmpSyms = raw.map(tk => {
    const fs = FMP_MAP[tk] || tk;
    reverse[fs] = tk;
    return fs;
  });

  try {
    const url = `${FMP_BASE}/quote/${fmpSyms.join(',')}?apikey=${FMP_KEY}`;
    const data = await fetchJSON(url);

    const result = {};
    if (Array.isArray(data)) {
      data.forEach(q => {
        if (q.symbol && q.price != null) {
          const orig = reverse[q.symbol] || q.symbol;
          result[orig] = q.price;
        }
      });
    }

    return {
      statusCode: 200,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
      body: JSON.stringify(result)
    };
  } catch(e) {
    return { statusCode: 500, body: JSON.stringify({ error: e.message }) };
  }
};
