// ============================================================
// E.B.V. — Escola Bolsa de Valores
// Netlify Function: Proxy Yahoo Finance v7 quote (batch, sem auth)
// Usa o mesmo endpoint que o script GitHub Actions (fetch_prices.py)
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

  // Endpoint v7/quote — mesmo usado pelo GitHub Actions (fetch_prices.py)
  // Mais confiável que v8/chart para preços regularMarketPrice
  const url =
    "https://query1.finance.yahoo.com/v7/finance/quote" +
    "?symbols=" + encodeURIComponent(symbols.join(",")) +
    "&fields=regularMarketPrice,regularMarketPreviousClose,regularMarketDayHigh,regularMarketDayLow,regularMarketVolume,marketCap,shortName";

  try {
    const r = await fetch(url, {
      signal: AbortSignal.timeout(12000),
      headers: {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      },
    });

    if (!r.ok) {
      return { statusCode: r.status, headers: cors(), body: JSON.stringify({ error: "Yahoo upstream error" }) };
    }

    const d = await r.json();
    const results = d?.quoteResponse?.result || [];

    const quotes = {};
    for (const q of results) {
      const sym = q.symbol;
      const px  = q.regularMarketPrice || q.regularMarketPreviousClose;
      if (sym && px && px > 0) {
        const prev = q.regularMarketPreviousClose || px;
        quotes[sym] = {
          px,
          prev,
          chgPct:  prev > 0 ? ((px - prev) / prev) * 100 : 0,
          chgAbs:  px - prev,
          high:    q.regularMarketDayHigh  || px,
          low:     q.regularMarketDayLow   || px,
          vol:     q.regularMarketVolume   || 0,
          mktCap:  q.marketCap             || 0,
          name:    q.shortName             || sym,
          src:     "yahoo",
        };
      }
    }

    return {
      statusCode: 200,
      headers: {
        ...cors(),
        "Cache-Control": "public, max-age=55",
        "X-Tickers-Requested": String(symbols.length),
        "X-Tickers-Received":  String(Object.keys(quotes).length),
      },
      body: JSON.stringify(quotes),
    };

  } catch (e) {
    return { statusCode: 500, headers: cors(), body: JSON.stringify({ error: String(e) }) };
  }
};

function cors() {
  return {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET",
  };
}
