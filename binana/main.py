import time
from dotenv import load_dotenv
from os import environ
from time import sleep
from binance.client import Client
from portfolio_manager.objects.asset import Asset
from portfolio_manager.objects.allocation import Allocation
from portfolio_manager.objects.allocation_category import AllocationCategory
from portfolio_manager.objects.account_details import AccountDetails
from portfolio_manager.objects.portfolio import Portfolio

account_id = 'binance'
account_name = 'Binance.US'
account = None
client = None

allocation = (Allocation()
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

def configureClient():
    global client
    load_dotenv()
    client = Client(environ.get('binana_api'), environ.get('binana_secret'), tld='us', testnet=False)

def balance():
    # configure the client
    configureClient()
    # get account details
    account_details = AccountDetails(account_id, account_name, allocation)
    # get assets
    parsed_assets = getAssetList()
    # create portfolio and balance
    portfolio = Portfolio(parsed_assets, [account_details])
    portfolio.invest_balanced(account_details)
    # print results
    portfolio.print_categories(account_details)
    portfolio.print_assets(account_details)

def getAveragePrice(asset_symbol):
    if asset_symbol == 'USD':
        return 1.0
    market_symbol = f'{asset_symbol}USD'
    order_book_bids = client.get_order_book(symbol=market_symbol, limit=15)['bids']
    return sum([float(bid[0]) for bid in order_book_bids]) / len(order_book_bids)

def getAssetList():
    account = client.get_account()

    asset_list = []
    for listing in account['balances']:
        total = float(listing['free']) + float(listing['locked'])
        symbol = listing['asset']

        if total > 0 or symbol == 'USD':
            avg_price = getAveragePrice(symbol)
            asset = Asset()
            asset.account_id = account_id
            asset.symbol = symbol
            asset.quantity = total
            asset.initial_balance = avg_price * total * 100
            asset_list.append(asset)

    return asset_list

if __name__ == '__main__':
    start = time.perf_counter()
    balance()
    runtime = time.perf_counter() - start
    print(f'\nRuntime: {runtime}')
