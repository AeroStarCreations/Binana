"""Binance.US script that submits orders with an attempt to maintain portfolio balance.

Resources:
    Binance Python API: 
        Github: https://github.com/sammchardy/python-binance
        Docs:  https://python-binance.readthedocs.io/en/latest/
"""

import asyncio
import json
from time import perf_counter
from dotenv import load_dotenv
from os import environ
from numpy import mean
from binance import AsyncClient, BinanceSocketManager
from binance.enums import *
from binance.exceptions import *
from binance.helpers import round_step_size
from portfolio_manager.objects.asset import Asset
from portfolio_manager.objects.allocation import Allocation
from portfolio_manager.objects.allocation_category import AllocationCategory
from portfolio_manager.objects.account_details import AccountDetails
from portfolio_manager.objects.portfolio import Portfolio

from price_predictor import PricePredictor

ACCOUNT_ID = 'binance'
ACCOUNT_NAME = 'Binance.US'
USD_SYMBOL = 'USD'
ALLOCATION = (Allocation()
    .with_category(
        AllocationCategory('Large Cap')
            .with_asset('ETH', 0.23)
            .with_asset('BTC', 0.18)
            .with_asset('ADA', 0.14)
            .with_asset('SOL', 0.05)
    ).with_category(
        AllocationCategory('Mid Cap')
            .with_asset('LINK', 0.13)
            .with_asset('MATIC', 0.13)
            .with_asset('UNI', 0.09)
            .with_asset('DOT', 0.05)
    ).with_category(
        AllocationCategory('Other')
            .with_asset('BNB', 0)
    )
).verify()
SYMBOLS = ALLOCATION.get_list_of_symbols()
PRICE_PREDICTOR = PricePredictor()

account = None
client = None
is_testing = True
investment_amount = 200

async def configure_client():
    """Initializes the Binance.US client
    """
    global client
    load_dotenv()
    client = await AsyncClient.create(environ.get('binana_api'), environ.get('binana_secret'), tld='us', testnet=False)
    PRICE_PREDICTOR.setAsyncClient(client)

def get_cash_investment_amount(usd_balance: float) -> float:
    """Determines the amount of cash to use in buy orders.

    Args:
        usd_balance (float): Amount of available cash in dollars 

    Returns:
        float: 200 or usd_balance - 10 (whichever is smaller)
    """
    global investment_amount
    return min(investment_amount, usd_balance - 10)
 
async def get_account_balances() -> list:
    """Gets the balances of all assets in the current user's Binance.US account.

    Returns:
        list: Asset balances by shares (free + locked) including USD
    """
    # get_account(): https://python-binance.readthedocs.io/en/latest/binance.html?highlight=get_account#binance.client.AsyncClient.get_account
    balances = (await client.get_account())['balances']
    for balance in balances:
        total = float(balance['free']) + float(balance['locked'])
        if balance['asset'] == USD_SYMBOL:
            total = get_cash_investment_amount(total)
        if total > 0:
            balance['total'] = total
    return [b for b in balances if 'total' in b]

async def get_avg_price(asset_symbol: str) -> tuple:
    """Gets average symbol price based on 15 most-recent bids.
    
    USD exchange is used for all prices because I only intend on purchasing
    crypto using USD. So, if 'BTC' is passed, 'BTCUSD' will be used as the
    market symbol.

    Args:
        asset_symbol (str): The symbol/marker of the asset (e.g. 'BTC')

    Returns:
        tuple: @asset_symbol, average exchange price
    """
    # get_order_book(): https://python-binance.readthedocs.io/en/latest/binance.html?highlight=get_order_book#binance.client.AsyncClient.get_order_book
    if asset_symbol == USD_SYMBOL:
        return asset_symbol, 1.0
    market_symbol = f'{asset_symbol}{USD_SYMBOL}'
    order_book_bids = (await client.get_order_book(symbol=market_symbol, limit=15))['bids']
    avg_price = mean([float(bid[0]) for bid in order_book_bids])
    return asset_symbol, avg_price


async def get_avg_prices() -> dict:
    """Gets dictionary of short-term symbol bid prices.

    Returns:
        dict: Dictonary with asset symbols as keys (e.g. 'BTC') and avg price as key
    """
    return dict(await asyncio.gather(*[get_avg_price(s) for s in SYMBOLS + [USD_SYMBOL]]))

async def get_predicted_price(asset_symbol: str) -> tuple:
    if asset_symbol == USD_SYMBOL:
        return asset_symbol, 1.0
    market_symbol = f'{asset_symbol}{USD_SYMBOL}'
    return asset_symbol, await PRICE_PREDICTOR.get(market_symbol)

async def get_predicted_prices() -> dict:
    return dict(await asyncio.gather(*[get_predicted_price(s) for s in SYMBOLS + [USD_SYMBOL]]))
    
async def get_all_symbol_info() -> dict:
    """Gets necessary symbol information such as filters for all assets in portfolio.
    
    This method returns important information about symbols that is used for
    configuring bids. Two filter types are needed: PRICE_FILTER and LOT_SIZE.

    Returns:
        dict: Symbol info with symbol as key (e.g. 'BTC')
    """
    # get_symbol_info(): https://python-binance.readthedocs.io/en/latest/binance.html?highlight=get_symbol_info#binance.client.AsyncClient.get_symbol_info
    portfolio_symbol_info = await asyncio.gather(*[client.get_symbol_info(f'{s}{USD_SYMBOL}') for s in SYMBOLS])
    result = {}
    for info in portfolio_symbol_info:
        d = {}
        for filter in info['filters']:
            filterType = filter['filterType']
            if filterType == 'PRICE_FILTER':
                d['tickSize'] = float(filter['tickSize'])
                d['minPrice'] = float(filter['minPrice'])
                d['maxPrice'] = float(filter['maxPrice'])
            elif filterType == 'LOT_SIZE':
                d['stepSize'] = float(filter['stepSize'])
                d['minQty'] = float(filter['minQty'])
                d['maxQty'] = float(filter['maxQty'])
            elif filterType == 'MIN_NOTIONAL':
                d['minNotional'] = float(filter['minNotional'])
        result[info['baseAsset']] = d
    return result

def get_portfolio_assets(account_balances: dict, avg_prices: dict) -> list:
    """Gets Asset objects for all portfolio assets/coins.

    Args:
        account_balances (dict): Dictionary of current account balances. (see get_account_balances())
        avg_prices (dict): Dictionary of market average bid amounts. (see get_average_prices())

    Returns:
        list: Asset objects for portfolio
    """
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

async def order(symbol: str, quantity: float, price: float) -> dict:
    """Places a bid via Binance.USD for a crypto currency.

    Args:
        symbol (str): The symbol of the coin for the bid
        quantity (float): The quantity of coins for the bid
        price (float): The price of the bid to be ordered

    Returns:
        dict: The order response, which indicates the result (success / failure)
    """
    # create_test_order(): https://python-binance.readthedocs.io/en/latest/binance.html?highlight=create_test_order#binance.client.AsyncClient.create_test_order
    # create_order(): https://python-binance.readthedocs.io/en/latest/binance.html?highlight=create_test_order#binance.client.AsyncClient.create_order
    global is_testing
    order_function = client.create_test_order
    if not is_testing:
        order_function = client.create_order
    notional = price * quantity
    result = {
        'symbol': symbol,
        'quantity': quantity,
        'price': price,
        'notional': notional
    }
    try:
        response = await order_function(
            symbol = f'{symbol}USD',
            quantity = quantity,
            price = str(price),
            side = SIDE_BUY,
            type = ORDER_TYPE_LIMIT,
            timeInForce = TIME_IN_FORCE_GTC
        )
        result['result'] = 'SUCCESS'
        result['response'] = response
        result['message'] = f'Ordered {quantity} {symbol} at ${price:,.3f} (Total: ${notional:,.3f})'
    except Exception as e:
        result['result'] = 'FAILURE'
        result['exception_type'] = type(e).__name__
        result['message'] = str(e)
    return result

async def submit_buy_orders(assets: list, avg_prices: dict, all_symbol_info: dict) -> None:
    """Submits valid bids to Binance.US. 

    Args:
        assets (list): List of Asset objects representing the user's portfolio.
        avg_prices (dict): Averages prices of assets (see: get_avg_prices()).
        all_symbol_info (dict): Important info such as filters for symbols (see: get_all_symbol_info()).
    """
    tasks = []
    for asset in assets:
        if asset.amount_invested <= 0:
            continue
        
        symbol_info = all_symbol_info[asset.symbol]
        dollar_investment = asset.amount_invested / 100 #dollar
        quantity = round_step_size(dollar_investment / avg_prices[asset.symbol], symbol_info['stepSize'])
        price = round_step_size(avg_prices[asset.symbol], symbol_info['tickSize'])
        notional = price * quantity
        
        failureReason = None
        if (price < symbol_info['minPrice']):
            failureReason = f'price {price} < minPrice {symbol_info["minPrice"]}'
        elif (price > symbol_info['maxPrice']):
            failureReason = f'price {price} > maxPrice {symbol_info["maxPrice"]}'
        elif (quantity < symbol_info['minQty']):
            failureReason = f'quantity {quantity} < minQty {symbol_info["minQty"]}'
        elif (quantity > symbol_info['maxQty']):
            failureReason = f'quantity {quantity} > maxQty {symbol_info["maxQty"]}'
        elif (notional < symbol_info['minNotional']):
            failureReason = f'notional {notional} < minNotional {symbol_info["minNotional"]}'
            
        if (failureReason):
            print(f'\n*!* Could not submit {asset.symbol} order: {failureReason} *!*\n')
            continue
        
        tasks.append(order(asset.symbol, quantity, price))
    try:
        results = await asyncio.gather(*tasks)
        print(json.dumps(results, indent=2))
        cash_spent = sum([result['notional'] for result in results if result['result'] == 'SUCCESS'])
        print(f'\nCash spent: ${cash_spent:,.3f}')
    except Exception as e:
        print('Failed to complete asyncio.gather() of orders')
        print(e)

def get_test_intentions_from_user() -> None:
    """Asks user if current execution is a test run and sets global variable `is_testing`."""
    global is_testing
    is_testing = input('Is this a test run? (y/n) > ') == 'y'
    if not is_testing:
        is_testing = input('Are you sure you want to submit real orders? (y/n) > ') != 'y'
        
async def get_investment_amount_from_user() -> None:
    global investment_amount
    asset = await client.get_asset_balance(asset=USD_SYMBOL)
    available_cash = float(asset['free']) + float(asset['locked'])
    user_input = input(f'\nAvailable USD: ${available_cash:,.2f}\nHow much USD do you want to invest? Press Return to choose ${investment_amount:,.2f}.\n\n> ')
    investment_amount = float(user_input)

async def main():
    # Ask user if this is a test run
    get_test_intentions_from_user()
    
    # Configure the Binance client
    await configure_client()

    # Ask user how much money they want to invest
    await get_investment_amount_from_user()
    
    # Start timer
    start = perf_counter()

    # Run all the initial async IO requests
    results = await asyncio.gather(
        get_account_balances(),
        # get_avg_prices(),
        get_predicted_prices(),
        get_all_symbol_info()
    )
    account_balances = results[0]
    # avg_prices = results[1]
    predicted_prices = results[1]
    all_symbol_info = results[2]

    # Get all the information needed
    account_details = AccountDetails(ACCOUNT_ID, ACCOUNT_NAME, ALLOCATION)
    # assets = get_portfolio_assets(account_balances, avg_prices)
    assets = get_portfolio_assets(account_balances, predicted_prices)
    portfolio = Portfolio(assets, [account_details])

    # Invest USD in portfolio and get resulting assets
    portfolio.invest_balanced(account_details)
    assets = portfolio.get_assets(account_details)

    # Submit buy orders to Binance
    # await submit_buy_orders(assets, avg_prices, all_symbol_info)
    await submit_buy_orders(assets, predicted_prices, all_symbol_info)

    ## print account summary (optional)
    portfolio.print_categories(account_details)
    portfolio.print_assets(account_details)

    # Close the Binance client
    await client.close_connection()
    
    # End timer and print total
    runtime = perf_counter() - start
    print(f'\nRuntime: {runtime:.4f} seconds')

async def get_open_orders() -> None:
    """! UNDER CONSTRUCTION !
    """
    await configure_client()
    open_orders = await client.get_open_orders()
    print(json.dumps(open_orders, indent=2))
    await client.close_connection()

if __name__ == '__main__':
    asyncio.run(main())
    # asyncio.run(get_open_orders())
