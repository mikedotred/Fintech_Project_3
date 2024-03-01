#importing dependencies

from bfxapi import Client #bitfinex client "python3 -m pip install --pre bitfinex-api-py"
import matplotlib.pyplot as plt
import pandas as pd
import time
import requests
import json
import os
import glob
import sys
from MCForecastTools import MCSimulation
from pypfopt.efficient_frontier import EfficientFrontier
from pypfopt import risk_models, expected_returns, objective_functions
from pypfopt.discrete_allocation import DiscreteAllocation, get_latest_prices
from pypfopt.expected_returns import mean_historical_return
from pypfopt.risk_models import CovarianceShrinkage


class Crypto_Screener:
    """
    
    A Python class for pulling all available crypto denominated in USD 
    and running Monte Carlo simulations on each and creating a portfolio
    with the maximum Sharpe ratio.
    
    
    Attributes
    ----------
    lookback_days: int
        number of days for data to be pulled for all tickers denominated in USD
    forced_tickers: list(str)
        tickers that must be in the portfolio
    sim_years: int
        number of years for simulation to predict
    portfolio_size: int
        number of stocks to include in portfolio (inclusive of forced)
    """

    

    def __init__(self, lookback_days=365, forced_tickers="",
                 sim_years=5, portfolio_size=5, df_ticker=pd.DataFrame()):
        """
        Constructs all the necessary files and attributes for the Crypto_Screener object.
        """

        # Set class attributes
        self.lookback_days = lookback_days
        self.forced_tickers = forced_tickers
        self.sim_years = sim_years
        self.portfolio_size = portfolio_size
        self.df_ticker=df_ticker
        self.keepers=[]



    def pull_crypto_data(self,lookback_days):
        """
        1 - Pulls a list of all crypto tickers
        2 - Filters out only USD-denominated tickers and removes "TEST" tickers
        
        """
        # Using the REST API to pull the list of crypto

        # url for REST API - list of crypto
        url = "https://api-pub.bitfinex.com/v2/conf/pub:list:pair:exchange"

        # preparing for json
        headers = {"accept": "application/json"}

        # pulling tickers
        response = requests.get(url, headers=headers)

        #putting tickers in a list
        full_ticker_list=json.loads(response.text)[0]

        # MUST add a "t" to each ticker to get the traded, not funded
        full_ticker_list = ["t" + each for each in full_ticker_list]

        # Create client for bitfinex public APIs
        bfx = Client()
        path = '.\\coin_csvs\\'

        for each in full_ticker_list:
            time.sleep(4) #give the API a little breathing space to avoid throttling
            crypto_symbol=each 
            # print(crypto_symbol)
            
            # only including cryto denominated in USD
            if "USD" in crypto_symbol:
                # putting the OHCV data in the candles DataFrame
                candles = pd.DataFrame(bfx.rest.public.get_candles_hist(symbol=crypto_symbol,tf='1D',limit=self.lookback_days))
                # showing progress with symbols and indicating how many days in each
                print(crypto_symbol,candles.size)
                # if there's a problem with the API call, candle size is 0
                if candles.size>0:
                    # data is provided in unix epoch, must convert to datetime
                    candles['date']=pd.to_datetime(candles['mts'],unit='ms')
                    # organize DataFrame by date
                    candles=candles.set_index('date')
                    # sort the DataFrame by date
                    candles=candles.sort_index(axis=1,ascending=True)
                    # export DataFrame to a csv for batch processing by later function
                    candles.to_csv(path+crypto_symbol.replace(':','')+'.csv')

    def import_crypto_data(self):
        """
        1 - Imports CSVs produced by pull_crypto_data()
        2 - Builds a MultiIndex DataFrame containing all the ticker data
        
        """
        # set the path to the coin csvs
        path = '.\\coin_csvs\\'
        all_files = glob.glob(path + "/*.csv")
        # initialize the lists
        lst = []
        tickers=[]
        for filename in all_files:
            if filename.replace(path,"").find('t') == 0:
                df = pd.read_csv(filename, index_col='date')
                lst.append(df)
                temp=filename.replace(path,"")
                temp=temp.removeprefix('t')
                temp=temp.removesuffix('.csv')
                tickers.append(temp)
            
        self.df_ticker = pd.concat(lst, axis=1, keys=tickers)
        self.df_ticker.sort_index(ascending=True,inplace=True)
        print("DataFrame size: ",self.df_ticker.shape)

    def run_crypto_sims(self,sim_years,num_sims):
        """
        1 - Runs a simulation for each ticker based on the # of years and # of simulations input
        2 - Builds a DataFrame the mean and median for each ticker's simulation
        
        """
        returns={}
        for each in self.df_ticker.columns.levels[0]:
            ticker_return=((self.df_ticker[each]['close'].pct_change()+1).cumprod()-1)[-1]
            returns[each]=ticker_return
        good_coins=[]
        for each in returns:
            
            if returns[each] > 1:
                good_coins.append(each)
        print(good_coins)

        # I don't know why it won't remove all the items containing "TEST" in only one run
        for each in good_coins:
            if "TEST" in each:
                good_coins.remove(each)
        for each in good_coins:
            if "TEST" in each:
                good_coins.remove(each)
        for each in good_coins:
            if "TEST" in each:
                good_coins.remove(each)
        for each in good_coins:
            if "TEST" in each:
                good_coins.remove(each)
        print("Number of coins with positive return: ",len(good_coins))
        print(good_coins)
        self.df_ticker[good_coins].to_csv('good_coins.csv')

        #create DataFrame for capturing ticker MC simulation statistics
        final_mean_median=pd.DataFrame(columns=['ticker','mean','median'])
        final_mean_median.set_index('ticker',inplace=True)

        # running a simulation for each in good coins
        for each in good_coins:
            print(each)
            ticker_data=self.df_ticker.loc[:, ([each], ['open','high','close','volume'])]

            # Configure a Monte Carlo simulation to forecast X years daily returns
            print(f"Starting Monte Carlo simulations for {each}.")
            MC_ticker = MCSimulation(
                portfolio_data = ticker_data,
                num_simulation = num_sims,
                num_trading_days = 365*sim_years # changed from 252 as crypto trades 24/7
            )

            MC_ticker.calc_cumulative_return()
            # Compute summary statistics from the simulated daily returns
            simulated_returns_data = {
                "mean": list(MC_ticker.simulated_return.mean(axis=1)),
                "median": list(MC_ticker.simulated_return.median(axis=1)),
                "min": list(MC_ticker.simulated_return.min(axis=1)),
                "max": list(MC_ticker.simulated_return.max(axis=1))
            }

            # Store endpoint mean and median in a dataframe for later screening
            final_mean_median.loc[each]=[simulated_returns_data['mean'][-1],simulated_returns_data['median'][-1]]
            
            # Create a DataFrame with the summary statistics
            df_simulated_returns = pd.DataFrame(simulated_returns_data)

            # Display sample data
            df_simulated_returns.head()

            # Plot simulation outcomes
            line_plot = MC_ticker.plot_simulation()

            # Save the plot for future usage
            line_plot.get_figure().savefig(".\\monte_carlo_plots\\"+each+"_ten_year_sim_plot.png", bbox_inches="tight")

            # Plot Return Behaviors
            mean_median=df_simulated_returns[['mean', 'median']].plot(title="Simulated Cumulative Return Behavior of "+each+" Over the Next Ten Years")

            #Save the plot
            mean_median.get_figure().savefig(".\\mean_median_plots\\"+each+"_mean_median_sim_plot.png", bbox_inches="tight")
        
        # 
        final_mean_median['mean_div_median']=final_mean_median['mean']/final_mean_median['median']
        final_mean_median=final_mean_median.sort_values(by='mean_div_median')

        #
        
        self.keepers = list(final_mean_median[(final_mean_median['mean_div_median']<50)].index)[:self.portfolio_size]
        for each in self.forced_tickers:
            self.keepers.append(each)
        
        with open('keepers.txt', 'w') as fp:
            for item in self.keepers:
                fp.write(f"{item}\n")

        print("Number of crypto kept: ",len(self.keepers))

    def create_portfolio(self,amount_to_invest):
        """
        1 - Utilized the keepers ticker list and the original MultiIndex ticker DataFrame to analyze and calculate a max Sharpe ratio portfolio
        2 - Outputs the correct number of each coin to purchase
        
        """

        with open('keepers.txt', 'r') as filehandle:
            self.keepers = [line.strip() for line in filehandle]

        df = self.df_ticker.loc[:, (self.keepers, ['close'])]
        print(self.keepers)
        df.columns=df.columns.droplevel(1)
        # Utilizing the PyPortfolioOpt module
        #https://pyportfolioopt.readthedocs.io/en/latest/UserGuide.html

        #mean historical return
        mu = mean_historical_return(df)
        #estimated covariance matrix
        S = CovarianceShrinkage(df).ledoit_wolf()

        # Calculates the efficient frontier of the basket of coins
        ef = EfficientFrontier(mu, S)
        ef.add_objective(objective_functions.L2_reg, gamma=0.1)
        # Calculates a the portfolio of the coins with the highest Sharpe ratio
        w = ef.max_sharpe()

        # Pulling last price to calculate number to purchase
        latest_prices = get_latest_prices(df)

        # Creates a DiscreteAllocation instance
        da = DiscreteAllocation(w, latest_prices, total_portfolio_value=amount_to_invest)
        # Calculates allocation and dollars leftover
        allocation, leftover = da.lp_portfolio()

        # Shares results
        print("Here are the number of each coin to purchase:",allocation)
        print("Here are your leftover dollars:",leftover.round(2))
        print("---------------------------------------")
        print("Predicted Portfolio performance:")
        ef.portfolio_performance(verbose=True)
        
        dollars_per_coin={}
        for each in allocation:
            dollars_per_coin[each]=allocation[each]*latest_prices[each]
        print("Here are the number of dollars spent on each coin: ")
        print(dollars_per_coin)
        print('')

        weights_dict=dict(w)

        # Data to plot
        labels = []
        sizes = []

        for x, y in weights_dict.items():
            if y > 0:
                labels.append(x)
                sizes.append(y)

        # Plot
        plt.xticks(rotation=45)
        plt.xlabel('Coin')
        plt.ylabel('Weighting')
        plt.bar(x=labels,height=sizes,)

                