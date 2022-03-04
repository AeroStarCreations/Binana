import asyncio
from binance import AsyncClient
from numpy.polynomial.polynomial import Polynomial

class PricePredictor:
    _USD = 'USD'
    _LIMIT = 50
    _X = [x for x in range(_LIMIT)]
    
    def setAsyncClient(self, client: AsyncClient):
        self._client = client
        
    async def get(self, market_symbol: str) -> float:
        assert(self._client != None)
        
        # Oldest trade is at index 0
        agg_trades = await self._client.get_aggregate_trades(symbol=market_symbol, limit=self._LIMIT)
        trade_prices = [float(trade['p']) for trade in agg_trades]
        
        trade_poly = Polynomial.fit(self._X, trade_prices, 5)
        predicted_val = trade_poly(self._LIMIT + 1)
        
        print(f'Predicted price for {market_symbol}: ${predicted_val:,.4f}')
        
        return predicted_val
        