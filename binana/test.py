import asyncio
import numpy as np
from numpy.polynomial import Polynomial
from numpy.polynomial.polynomial import polyval
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from os import environ
from binance.client import Client

LIMIT = 50

load_dotenv()
client = Client(environ.get('binana_api'), environ.get('binana_secret'), tld='us', testnet=False)

x = [x for x in range(LIMIT)]

# Oldest trade is at index 0
agg_trades = client.get_aggregate_trades(symbol='BTCUSD', limit=LIMIT)
trade_prices = [float(x['p']) for x in agg_trades]

# Highest bid and lowest ask are at index 0
order_book = client.get_order_book(symbol='BTCUSD', limit=LIMIT)
bid_prices = [float(x[0]) for x in order_book['bids']][::-1]
ask_prices = [float(x[0]) for x in order_book['asks']][::-1]

avg_price_info = client.get_avg_price(symbol='BTCUSD')
avg_price = float(avg_price_info['price'])
print(f'Avg price: ${avg_price:,.2f}')

trade_poly = Polynomial.fit(x, trade_prices, 5)
predicted_val = trade_poly(LIMIT+1)

# bid_poly = Polynomial.fit(x, bid_prices, 5)
# ask_poly = Polynomial.fit(x, ask_prices, 5)

plt.plot(x, trade_prices, 'o', label='Trades', markersize=5)
plt.plot(*trade_poly.linspace(), 'r', label='Fitted line (trades)')
plt.plot(x, bid_prices, 'x', label='Bids', markersize=5)
# plt.plot(*bid_poly.linspace(), 'g', label='Fitted line (bids)')
plt.plot(x, ask_prices, '^', label='Asks', markersize=5)
# plt.plot(*ask_poly.linspace(), 'm', label='Fitted line (asks)', markersize=10)
plt.plot([LIMIT-1], [avg_price], 'x', label="Avg Price (5 min)")
plt.plot([LIMIT+1], [predicted_val], 'o', label="Prediction")
plt.legend()
plt.show()


###
# NOTES
###
#
# The most recent trades seem to closely follow the lowest Ask price