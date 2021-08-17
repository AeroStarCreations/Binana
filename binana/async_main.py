import asyncio
import json
from time import perf_counter
from dotenv import load_dotenv
from os import environ
from binance import AsyncClient, BinanceSocketManager
from binance.enums import *
from binance.exceptions import *
from binance.helpers import round_step_size
from portfolio_manager.objects.asset import Asset
from portfolio_manager.objects.allocation import Allocation
from portfolio_manager.objects.allocation_category import AllocationCategory
from portfolio_manager.objects.account_details import AccountDetails
from portfolio_manager.objects.portfolio import Portfolio

ACCOUNT_ID = 'binance'
ACCOUNT_NAME = 'Binance.US'
ALLOCATION = (Allocation()
    .with_category(
        AllocationCategory('Large Cap')
            .with_asset('ETH', 0.25)
            .with_asset('BTC', 0.2)
            .with_asset('ADA', 0.15)
            .with_asset('UNI', 0.1)
    ).with_category(
        AllocationCategory('Mid Cap')
            .with_asset('LINK', 0.15)
            .with_asset('MATIC', 0.15)
    ).with_category(
        AllocationCategory('Other')
            .with_asset('BNB', 0)
    )
).verify()
SYMBOLS = ALLOCATION.get_list_of_symbols()

account = None
client = None

async def configure_client():
    global client
    load_dotenv()
    client = await AsyncClient.create(environ.get('binana_api'), environ.get('binana_secret'), tld='us', testnet=False)

async def get_account_balances():
    balances = (await client.get_account())['balances']
    for balance in balances:
        balance['total'] = float(balance['free']) + float(balance['locked'])
        if balance['asset'] == 'USD':
            balance['total'] = max(balance['total'] - 10, 0)
    return [b for b in balances if b['total'] > 0 or b['asset'] == 'USD']

async def get_avg_price(asset_symbol):
    if asset_symbol == 'USD':
        return asset_symbol, 1.0
    market_symbol = f'{asset_symbol}USD'
    order_book_bids = (await client.get_order_book(symbol=market_symbol, limit=15))['bids']
    avg_price = sum([float(bid[0]) for bid in order_book_bids]) / len(order_book_bids)
    return asset_symbol, avg_price

async def get_avg_prices():
    return dict(await asyncio.gather(*[get_avg_price(s) for s in SYMBOLS + ['USD']]))

async def get_all_symbol_info():
    all_symbol_info = await asyncio.gather(*[client.get_symbol_info(f'{s}USD') for s in SYMBOLS])
    result = {}
    for info in all_symbol_info:
        d = {}
        for filt in info['filters']:
            if filt['filterType'] == 'PRICE_FILTER':
                d['tickSize'] = float(filt['tickSize'])
                d['minPrice'] = float(filt['minPrice'])
                d['maxPrice'] = float(filt['maxPrice'])
            elif filt['filterType'] == 'LOT_SIZE':
                d['stepSize'] = float(filt['stepSize'])
                d['minQty'] = float(filt['minQty'])
                d['maxQty'] = float(filt['maxQty'])
        result[info['baseAsset']] = d
    return result

def get_portfolio_assets(account_balances, avg_prices):
    assets = []
    for balance in account_balances:
        total = balance['total']
        symbol = balance['asset']
        asset = Asset()
        asset.account_id = ACCOUNT_ID
        asset.symbol = symbol
        asset.quantity = total
        asset.initial_balance = avg_prices[symbol] * total * 100 #cents
        assets.append(asset)
    return assets

async def submit_buy_orders(assets, avg_prices, all_symbol_info):
    tasks = []
    for asset in assets:
        if asset.amount_invested <= 0:
            continue
        symbol_info = all_symbol_info[asset.symbol]
        quantity = round_step_size(asset.amount_invested / avg_prices[asset.symbol], symbol_info['stepSize'])
        price = round_step_size(avg_prices[asset.symbol], symbol_info['tickSize'])
        if (price < symbol_info['minPrice'] or price > symbol_info['maxPrice']
        or quantity < symbol_info['minQty']or quantity > symbol_info['maxQty']):
            continue
        tasks.append(
            client.create_test_order(
                symbol = f'{asset.symbol}USD',
                side = SIDE_BUY,
                type = ORDER_TYPE_LIMIT,
                timeInForce = TIME_IN_FORCE_GTC,
                quantity = quantity,
                price = str(price)
            )
        )
    try:
        results = await asyncio.gather(*tasks)
        print(json.dumps(results))
    except BinanceAPIException as e:
        print(e)

async def main():
    # Configure the Binance client
    await configure_client()

    # Run all the initial async IO requests
    results = await asyncio.gather(
        get_account_balances(),
        get_avg_prices(),
        get_all_symbol_info()
    )
    account_balances = results[0]
    avg_prices = results[1]
    all_symbol_info = results[2]

    # Get all the information needed
    account_details = AccountDetails(ACCOUNT_ID, ACCOUNT_NAME, ALLOCATION)
    assets = get_portfolio_assets(account_balances, avg_prices)
    portfolio = Portfolio(assets, [account_details])

    # Invest USD in portfolio and get resulting assets
    portfolio.invest_balanced(account_details)
    assets = portfolio.get_assets(account_details)

    # Submit buy orders to Binance
    await submit_buy_orders(assets, avg_prices, all_symbol_info)

    ## print account summary (optional)
    portfolio.print_categories(account_details)
    portfolio.print_assets(account_details)

    # Close the Binance client
    await client.close_connection()

if __name__ == '__main__':
    start = perf_counter()
    asyncio.run(main())
    runtime = perf_counter() - start
    print(f'\nRuntime: {runtime}')