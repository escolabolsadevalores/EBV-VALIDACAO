// ============================================================
// E.B.V. — Escola Bolsa de Valores
// Netlify Function: Proxy Yahoo Finance v8 (sem crumb/auth)
// Busca até 20 tickers em paralelo via endpoint de chart
// ============================================================

exports.handler = async function (event) {
  if (event.httpMethod !== "GET") {
    return { statusCode: 405, headers: cors(), body: "Method Not Allowed" };
  }

  const params = event.queryStringParameters || {};
  const raw = params.symbols || "";

  if (!raw) {
    return {
      statusCode: 400,
      headers: cors(),
      body: JSON.stringify({ error: "Parâmetro 'symbols' obrigatório. Ex: ?symbols=AAPL,MSFT" }),
    };
  }

  // Sanitiza: permite letras, números, ponto, hífen, circunflexo e sinal de igual
  const symbols = raw
    .split(",")
    .map(s => s.trim().toUpperCase().replace(/[^A-Z0-9.\-\^=]/g, ""))
    .filter(s => s.length > 0)
    .slice(0, 20);

  if (symbols.length === 0) {
    return {
      statusCode: 400,
      headers: cors(),
      body: JSON.stringify({ error: "Nenhum símbolo válido encontrado." }),
    };
  }

  // Busca cada símbolo via v8/chart em paralelo (sem autenticação)
  const promises = symbols.map(async (symbol) => {
    const url =
      "https://query1.finance.yahoo.com/v8/finance/chart/" +
      encodeURIComponent(symbol) +
      "?interval=1d&range=2d&includePrePost=false";
    try {
      const r = await fetch(url, {
        signal: AbortSignal.timeout(8000),
        headers: {
          "Accept": "application/json",
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        },
      });
      if (!r.ok) return { symbol, data: null };

      const d = await r.json();
      const res = d?.chart?.result?.[0];
      if (!res?.meta) return { symbol, data: null };

      const meta = res.meta;
      const px   = meta.regularMarketPrice || meta.previousClose || 0;
      const prev = meta.previousClose || meta.chartPreviousClose || px;

      return {
        symbol,
        data: {
          px,
          prev,
          chgPct:  prev > 0 ? ((px - prev) / prev) * 100 : 0,
          chgAbs:  px - prev,
          high:    meta.regularMarketDayHigh  || px,
          low:     meta.regularMarketDayLow   || px,
          vol:     meta.regularMarketVolume   || 0,
          mktCap:  meta.marketCap             || 0,
          name:    meta.shortName             || symbol,
          src:     "yahoo",
        },
      };
    } catch (e) {
      return { symbol, data: null };
    }
  });

  const settled = await Promise.all(promises);

  const quotes = {};
  for (const { symbol, data } of settled) {
    if (data && data.px > 0) quotes[symbol] = data;
  }

  const total    = symbols.length;
  const received = Object.keys(quotes).length;

  return {
    statusCode: 200,
    headers: {
      ...cors(),
      "Cache-Control": "public, max-age=55",
      "X-Tickers-Requested": String(total),
      "X-Tickers-Received":  String(received),
    },
    body: JSON.stringify(quotes),
  };
};

function cors() {
  return {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET",
  };
}
