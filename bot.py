import os
import logging
import re
import requests
import tweepy
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.ext import CallbackContext
from dotenv import load_dotenv
import praw
from datetime import datetime
# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Twitter API client
twitter_client = tweepy.Client(
    consumer_key=os.getenv("TWITTER_API_KEY"),
    consumer_secret=os.getenv("TWITTER_API_KEY_SECRET"),
    access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
    access_token_secret=os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
)

# Initialize Reddit API client
reddit_client = praw.Reddit(client_id=os.getenv("REDDIT_CLIENT_ID"),
                            client_secret=os.getenv("REDDIT_SECRET"),
                            user_agent=os.getenv("REDDIT_USER_AGENT"))

# Dexscreener Functions
def detect_blockchain(token_address: str) -> str:
    """Detect the blockchain based on the token address format."""
    if re.match(r"^0x[a-fA-F0-9]{40}$", token_address):
        return "Ethereum"
    elif re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", token_address):
        return "Solana"
    elif re.match(r"^[a-zA-Z0-9]{42}$", token_address):
        return "Binance"
    elif re.match(r"^0x[a-fA-F0-9]{40}$", token_address):  # Polygon addresses are similar to Ethereum
        return "Polygon"
    else:
        return "Unknown"

def fetch_dexscreener_data(token_address: str) -> list:
    """Fetch token details from the Dexscreener API."""
    url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data.get("pairs", [])
    except Exception as e:
        logger.error(f"Error fetching data from Dexscreener: {e}")
        return []

def get_preferred_dex(pairs: list) -> dict:
    """Select the preferred DEX based on liquidity or other criteria."""
    if not pairs:
        return {}
    sorted_pairs = sorted(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0), reverse=True)
    return sorted_pairs[0] if sorted_pairs else {}

def analyze_rug_pull_risk(preferred_pair: dict) -> str:
    """Analyze rug pull risk based on liquidity, price trend, market cap, FDV, transaction volume, and other factors."""
    liquidity = preferred_pair.get("liquidity", {}).get("usd", 0)
    price_change_percentage = preferred_pair.get("priceChange", {}).get("percent", preferred_pair.get("priceChange", {}).get("h24", 0))
    market_cap = preferred_pair.get("marketCap", 0)
    fdv = preferred_pair.get("fdv", 0)  # Fully Diluted Valuation

    # **Key Factor 1: Liquidity**
    liquidity_level = "Low"
    if liquidity > 25000:
        liquidity_level = "High"
    elif liquidity >= 10000:
        liquidity_level = "Medium"

    # **Key Factor 2: Market Cap**
    market_cap_level = "Low"
    if market_cap > 250000:
        market_cap_level = "High"
    elif market_cap >= 100000:
        market_cap_level = "Medium"

    # **Key Factor 3: 24H Price Change**
    price_change_level = "Stable"
    if price_change_percentage > 500:
        price_change_level = "Volatile"
    elif price_change_percentage <= 0:
        price_change_level = "Negative"

    # **Key Factor 4: FDV (Fully Diluted Valuation) vs Market Cap**
    fdv_vs_market_cap = "Balanced"
    if fdv < market_cap:
        fdv_vs_market_cap = "FDV Lower Than Market Cap"
    elif fdv > market_cap:
        fdv_vs_market_cap = "FDV Higher Than Market Cap"

    # **Risk Calculation**

    # **Low Risk** - Healthy liquidity, solid market cap, and stable price
    if liquidity > 25000 and market_cap > 250000 and price_change_percentage <= 50:
        return (f"✅ **Low Risk**: Based on the key factors below, this token has strong liquidity, a healthy market cap, and a stable price change, "
                "suggesting stability and minimal risk of a rug pull. Monitor the price and transaction volume. 🟢\n\n"
                f"**Key Factors:**\nLiquidity: {liquidity} USD ({liquidity_level}) - Liquidity is the available amount of capital that can be easily traded or moved in/out of the market. High liquidity reduces the chance of sudden price manipulation.\n"
                f"Market Cap: {market_cap} USD ({market_cap_level}) - A high market cap typically signifies a token with solid backing and less vulnerability to drastic fluctuations.\n"
                f"24H Price Change: {price_change_percentage}% ({price_change_level}) - Stable price changes indicate lower volatility, which is generally a sign of stability.\n"
                f"FDV vs Market Cap: {fdv_vs_market_cap} - If FDV is significantly higher than market cap, it could indicate a potentially overvalued token.\n")

    # **Moderate Risk** - Decent liquidity, but volatility or low market cap
    if liquidity >= 10000 and liquidity <= 20000 and (price_change_percentage > 50 or market_cap < 100000):
        return (f"⚠️ **Moderate Risk**: Liquidity is decent, but there are concerns with the price change or market cap. "
                "While not in immediate danger, signs point to potential instability. Monitor closely. 🟡\n\n"
                f"**Key Factors:**\nLiquidity: {liquidity} USD ({liquidity_level}) - Medium liquidity means there's some flexibility, but not enough to avoid larger market manipulations.\n"
                f"Market Cap: {market_cap} USD ({market_cap_level}) - A lower market cap makes the token more susceptible to manipulation and higher volatility.\n"
                f"24H Price Change: {price_change_percentage}% ({price_change_level}) - A significant price change can indicate speculation or manipulation in the market.\n"
                f"FDV vs Market Cap: {fdv_vs_market_cap} - If FDV is lower than market cap, the market could be undervaluing the token, but it could also signify a false sense of stability.\n")

    # **High Risk** - Low liquidity or price volatility
    if liquidity < 10000 or price_change_percentage <= 0:
        return (f"⚠️ **High Risk**: This token has low liquidity or negative price movement, which increases the likelihood of a rug pull. "
                "A lack of liquidity can make the price more vulnerable to manipulation. 🚨\n\n"
                f"**Key Factors:**\nLiquidity: {liquidity} USD ({liquidity_level}) - Low liquidity means the token is more easily manipulated and price spikes can occur more frequently.\n"
                f"Market Cap: {market_cap} USD ({market_cap_level}) - A low market cap typically reflects a token with fewer investors and higher risk of price manipulation.\n"
                f"24H Price Change: {price_change_percentage}% ({price_change_level}) - A negative price change can be an indication of declining interest or manipulation.\n"
                f"FDV vs Market Cap: {fdv_vs_market_cap} - If FDV is significantly higher than market cap, this imbalance could be a red flag, indicating potential manipulation.\n")

    # **Critical Risk** - Extremely low liquidity, FDV lower than market cap, or significant centralization
    if liquidity < 5000 or fdv < market_cap:
        return (f"🚨 **Critical Risk**: This token has dangerously low liquidity or FDV that is lower than its market cap, suggesting high risk. "
                "The low liquidity makes it easy for malicious actors to manipulate the price. Avoid investing if you value your funds. 🔴\n\n"
                f"**Key Factors:**\nLiquidity: {liquidity} USD ({liquidity_level}) - Extremely low liquidity is a huge risk for manipulation, making it easy for bad actors to control the price.\n"
                f"Market Cap: {market_cap} USD ({market_cap_level}) - A low market cap means fewer resources to keep the price stable, which increases risk.\n"
                f"24H Price Change: {price_change_percentage}% ({price_change_level}) - Price instability makes the token more vulnerable to sudden drops.\n"
                f"FDV vs Market Cap: {fdv_vs_market_cap} - If FDV is lower than market cap, it may suggest an overinflated value that is unsustainable.\n")

    # **Extreme Risk** - Massive price changes or extreme centralization
    if price_change_percentage > 1000 or fdv > market_cap * 2:
        return (f"🔥 **Extreme Risk**: This token has shown a massive price change, or there is extreme centralization. "
                "This can indicate manipulative schemes and pump-and-dump behavior. Proceed with extreme caution! 🚩\n\n"
                f"**Key Factors:**\nLiquidity: {liquidity} USD ({liquidity_level}) - High liquidity is good, but massive volatility or centralization suggests a high risk of market manipulation.\n"
                f"Market Cap: {market_cap} USD ({market_cap_level}) - The market cap is high, but extreme volatility or centralization can create a false sense of security.\n"
                f"24H Price Change: {price_change_percentage}% ({price_change_level}) - A large price change within 24 hours is often associated with pump-and-dump schemes.\n"
                f"FDV vs Market Cap: {fdv_vs_market_cap} - If FDV is much higher than market cap, the token could be highly inflated and could crash once the market stabilizes.\n")

    # **Final Risk Level**: Token with moderate concerns
    return (f"✅ **Low to Moderate Risk**: The token has decent liquidity and market cap, but there are concerns such as price volatility or social media mentions. "
            "Monitor closely for any sudden changes. 🟢\n\n"
            f"**Key Factors:**\nLiquidity: {liquidity} USD ({liquidity_level}) - Decent liquidity means there’s enough trading volume to prevent sudden price swings, but still monitor for sudden changes.\n"
            f"Market Cap: {market_cap} USD ({market_cap_level}) - A reasonable market cap is a good sign, but it can still be vulnerable if price volatility or external factors come into play.\n"
            f"24H Price Change: {price_change_percentage}% ({price_change_level}) - Price volatility could indicate potential price manipulation or speculative trading.\n"
            f"FDV vs Market Cap: {fdv_vs_market_cap} - A balanced FDV vs market cap ratio indicates the market is valuing the token appropriately, but monitor for any shifts in the future.\n")


def fetch_social_media_mentions(token_address: str) -> str:
    """Fetch mentions of the token on social media platforms and return counts."""
    mentions_count = {"Twitter": 0, "Reddit": 0}

    # Fetch Twitter mentions 🐦
    try:
        query = f"{token_address}"
        tweets = twitter_client.search_recent_tweets(query=query, max_results=5)
        mentions_count["Twitter"] = len(tweets.data) if tweets.data else 0
    except Exception as e:
        logger.error(f"Error fetching Twitter mentions: {e}")

    # Fetch Reddit mentions 💬
    try:
        for post in reddit_client.subreddit("all").search(token_address, limit=5):
            mentions_count["Reddit"] += 1
    except Exception as e:
        logger.error(f"Error fetching Reddit mentions: {e}")

    # Return the counts in a formatted string 📊
    return (f"Twitter Mentions: {mentions_count['Twitter']} 🐦\n"
            f"Reddit Mentions: {mentions_count['Reddit']} 💬")


import requests
import logging

logger = logging.getLogger(__name__)

def fetch_boosted_tokens():
    url = "https://api.dexscreener.com/token-boosts/latest/v1"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        # Log the raw response for debugging
        logger.debug(f"Raw API Response: {data}")

        # Ensure the response structure is correct
        if isinstance(data, list):
            boosted_tokens = []
            for token in data[:10]:  # Limit to 10 tokens
                token_link = token.get("url", "Not available")  # Use URL instead of tokenAddress
                liquidity = token.get("totalAmount", "Not available")

                if token_link and liquidity:
                    # Add token info to the list, with clickable token link and liquidity
                    boosted_tokens.append({
                        "tokenLink": f"<a href='{token_link}'>{token_link}</a>",  # Clickable token link
                        "liquidity": liquidity
                    })
            return boosted_tokens
        else:
            logger.error(f"Unexpected response format: Expected list, got {type(data)}")
            return []

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching boosted tokens: {e}")
        return []



# Telegram Bot Command Handlers
async def start(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    logger.info(f"User {user.first_name} started the conversation.")
    await update.message.reply_text(
        "Welcome to the Token Safety Bot! Choose an option from the menu below:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001F50D Analyze Token", callback_data='analyze_token')],
            [InlineKeyboardButton("\U0001F6E1 Rug Pull Scanner", callback_data='rug_pull_scan')],
           # [InlineKeyboardButton("\U0001F4C8 Top Boosted Tokens", callback_data='top_tokens')],
            [InlineKeyboardButton("\U0001F6AA Exit", callback_data='exit')]
        ])
    )

# Handler for the "Analyze Token" option
async def analyze_token(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query
    await query.edit_message_text("Please provide the token address:")

    # Store that the user is analyzing a token
    context.user_data["selected_option"] = "analyze_token"

# Handler for the "Rug Pull Scanner" option
async def rug_pull_scan(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query
    await query.edit_message_text("Please provide the token address for Rug Pull Risk check:")

    # Store that the user is checking for rug pull
    context.user_data["selected_option"] = "rug_pull_scan"

# Handler for the "Random Tokens" option
async def top_tokens(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query
    
    top_tokens = fetch_boosted_tokens()
    if not top_tokens:
        await query.edit_message_text("No top tokens available at the moment.")
        return

    message = "Here are the Top Boosted Tokens based on liquidity:\n\n"
    for i, token in enumerate(top_tokens, 1):
        token_address = token.get("address")
        message += f"{i}. Token Address: {token_address}\n"
    
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup([ 
        [InlineKeyboardButton("Go Back to Main Menu", callback_data='go_back_to_menu')]
    ]))

# Handler for the "Full Token Analysis" button press
async def full_token_analysis(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query
    await query.edit_message_text("🔍 Fetching Full Token Analysis...")

    # Get the previously entered token address from the context
    token_address = context.user_data.get("token_address")

    if not token_address:
        await query.edit_message_text("❌ No token address found. Please enter a valid token address first.")
        return

    # Fetch Dexscreener data
    dex_pairs = fetch_dexscreener_data(token_address)

    if not dex_pairs:
        await query.edit_message_text("⚠️ No valid data found for the given token address.")
        return

    # Get the preferred DEX pair
    preferred_pair = get_preferred_dex(dex_pairs)

    if not preferred_pair:
        await query.edit_message_text("❌ No preferred DEX found for the token.")
        return

    # Fetch token details
    token_details = {
        "dexscreener": {
            "DEX": preferred_pair.get("dexId", "N/A"),
            "Price": preferred_pair.get("priceUsd", "Not Available"),
            "Liquidity": preferred_pair.get("liquidity", {}).get("usd", "Not Available"),
            "Market Cap": preferred_pair.get("marketCap", "Not Available"),
            "FDV": preferred_pair.get("fdv", "Not Available"),
            "24H Price Change": f"{preferred_pair.get('priceChange', {}).get('h24', 'Not Available')}%" if isinstance(preferred_pair.get('priceChange', {}).get('h24'), (int, float)) else "Not Available",
            "URL": preferred_pair.get("url", "N/A")
        },
        "rug_pull_risk": analyze_rug_pull_risk(preferred_pair),
        "social_media_mentions": fetch_social_media_mentions(token_address)
    }

    # Combine everything into a single message formatted like your example
    message = f"""
Token Address: {token_address} 🏷️

Dexscreener Data 📊:
- DEX: {token_details["dexscreener"]["DEX"]} 🔑
- Price: {token_details["dexscreener"]["Price"]} USD 💵
- Liquidity: {token_details["dexscreener"]["Liquidity"]} USD 💧
- Market Cap: {token_details["dexscreener"]["Market Cap"]} USD 💼
- FDV: {token_details["dexscreener"]["FDV"]} USD 📈
- 24H Price Change: {token_details["dexscreener"]["24H Price Change"]} 🔄
Rug Pull Risk: {token_details["rug_pull_risk"]} ⚠️

Social Media Mentions 📱:
{token_details["social_media_mentions"]} 💬
    """

    # Send the combined message with options to exit or search again
    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup([ 
            [InlineKeyboardButton("Rug Pull Check 🔎", callback_data='rug_pull_scan')],
            [InlineKeyboardButton("Go Back to Main Menu 🏠", callback_data='go_back_to_menu')]
        ])
    )

# Message handler for entering the token address after choosing the option
async def handle_token_address(update: Update, context: CallbackContext) -> None:
    token_address = update.message.text.strip()

    # Validate token address format
    if not re.match(r"^0x[a-fA-F0-9]{40}$|^[1-9A-HJ-NP-Za-km-z]{32,44}$", token_address):
        await update.message.reply_text(
            "❌ Invalid address format. Please provide a valid wallet address or token name.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Start Over 🔄", callback_data='start')]]))
        return

    # Store the token address in context
    context.user_data["token_address"] = token_address

    # Check which option the user selected
    if context.user_data.get("selected_option") == "analyze_token":
        await update.message.reply_text(f"🔍 Analyzing token address: {token_address}")

        # Fetch Dexscreener data
        dex_pairs = fetch_dexscreener_data(token_address)
        preferred_pair = get_preferred_dex(dex_pairs)

        # Fetch token details
        token_details = {
            "dexscreener": {
                "DEX": preferred_pair.get("dexId", "N/A"),
                "Price": preferred_pair.get("priceUsd", "Not Available"),
                "Liquidity": preferred_pair.get("liquidity", {}).get("usd", "Not Available"),
                "Market Cap": preferred_pair.get("marketCap", "Not Available"),
                "FDV": preferred_pair.get("fdv", "Not Available"),
                "24H Price Change": f"{preferred_pair.get('priceChange', {}).get('h24', 'Not Available')}%" if isinstance(preferred_pair.get('priceChange', {}).get('h24'), (int, float)) else "Not Available",
                "URL": preferred_pair.get("url", "N/A")
            },
            "rug_pull_risk": analyze_rug_pull_risk(preferred_pair),
            "social_media_mentions": fetch_social_media_mentions(token_address)
        }

        # Combine everything into a single message
        message = f"""
Token Address: {token_address} 🏷️

Dexscreener Data 📊:
- DEX: {token_details["dexscreener"]["DEX"]} 🔑
- Price: {token_details["dexscreener"]["Price"]} USD 💵
- Liquidity: {token_details["dexscreener"]["Liquidity"]} USD 💧
- Market Cap: {token_details["dexscreener"]["Market Cap"]} USD 💼
- FDV: {token_details["dexscreener"]["FDV"]} USD 📈
- 24H Price Change: {token_details["dexscreener"]["24H Price Change"]} 🔄
- URL: {token_details["dexscreener"]["URL"]} 🌐

Rug Pull Risk ⚠️: {token_details["rug_pull_risk"]}

Social Media Mentions 📱:
{token_details["social_media_mentions"]} 💬
        """

        # Send the combined message with options to exit or search again
        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup([ 
                [InlineKeyboardButton("Rug Pull Check 🔎", callback_data='rug_pull_scan')],
                [InlineKeyboardButton("Go Back to Main Menu 🏠", callback_data='go_back_to_menu')]
            ])
        )

# Message handler for entering the token address after choosing the option
async def handle_token_address(update: Update, context: CallbackContext) -> None:
    token_address = update.message.text.strip()

    # Validate token address format
    if not re.match(r"^0x[a-fA-F0-9]{40}$|^[1-9A-HJ-NP-Za-km-z]{32,44}$", token_address):
        await update.message.reply_text(
            "Invalid address format. Please provide a valid wallet address or token name.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Start Over", callback_data='start')]]))
        return

    # Store the token address in context
    context.user_data["token_address"] = token_address

    # Check which option the user selected
    if context.user_data.get("selected_option") == "analyze_token":
        await update.message.reply_text(f"Analyzing token address: {token_address}")

        # Fetch Dexscreener data
        dex_pairs = fetch_dexscreener_data(token_address)
        preferred_pair = get_preferred_dex(dex_pairs)

        # Fetch token details
        token_details = {
           "dexscreener": {
                "DEX": preferred_pair.get("dexId", "N/A"),
                "Price": preferred_pair.get("priceUsd", "Not Available"),
                "Liquidity": preferred_pair.get("liquidity", {}).get("usd", "Not Available"),
                "Market Cap": preferred_pair.get("marketCap", "Not Available"),
                "FDV": preferred_pair.get("fdv", "Not Available"),
                # 24H Price Change: Handle as percentage (remove USD)
                "24H Price Change": f"{preferred_pair.get('priceChange', {}).get('h24', 'Not Available')}%" if isinstance(preferred_pair.get('priceChange', {}).get('h24'), (int, float)) else "Not Available",
                # Remove Volume and fix the Currently Count of Buyers
                "URL": preferred_pair.get("url", "N/A")
            },
            "rug_pull_risk": analyze_rug_pull_risk(preferred_pair),
            "social_media_mentions": fetch_social_media_mentions(token_address)
        }

        # Combine everything into a single message
        message = f"""
Token Address: {token_address} 🏷️

Dexscreener Data 📊:
- DEX: {token_details["dexscreener"]["DEX"]} 🔑
- Price: {token_details["dexscreener"]["Price"]} USD 💵
- Liquidity: {token_details["dexscreener"]["Liquidity"]} USD 💧
- Market Cap: {token_details["dexscreener"]["Market Cap"]} USD 💼
- FDV: {token_details["dexscreener"]["FDV"]} USD 📈
- 24H Price Change: {token_details["dexscreener"]["24H Price Change"]} 🔄
- URL: {token_details["dexscreener"]["URL"]} 🌐

Rug Pull Risk: {token_details["rug_pull_risk"]}

Social Media Mentions:
{token_details["social_media_mentions"]}
        """

        # Send the combined message with options to exit or search again
        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup([ 
                [InlineKeyboardButton("Rug Pull Check", callback_data='rug_pull_scan')],
                [InlineKeyboardButton("Go Back to Main Menu", callback_data='go_back_to_menu')]
            ])
        )

    elif context.user_data.get("selected_option") == "rug_pull_scan":
        await update.message.reply_text(f"Checking Rug Pull Risk for token address: {token_address}")
        
        # Fetch Dexscreener data
        dex_pairs = fetch_dexscreener_data(token_address)
        preferred_pair = get_preferred_dex(dex_pairs)

        # Analyze the Rug Pull Risk
        rug_pull_risk = analyze_rug_pull_risk(preferred_pair)

        # Send rug pull details to the user
        message = f"""
Token Address: {token_address}

Rug Pull Risk: {rug_pull_risk}

Dexscreener Data:
- DEX: {preferred_pair.get("dexId", "N/A")}
- Price: {preferred_pair.get("priceUsd", "Not Available")}
- Liquidity: {preferred_pair.get("liquidity", {}).get("usd", "Not Available")}
- Market Cap: {preferred_pair.get("marketCap", "Not Available")}

Social Media Mentions:
{fetch_social_media_mentions(token_address)}
        """

        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup([ 
                [InlineKeyboardButton("Full Token Analysis", callback_data='full_analysis')],
                [InlineKeyboardButton("Go Back to Main Menu", callback_data='go_back_to_menu')]
            ])
        )

# Go back to main menu
async def go_back_to_menu(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query
    await query.edit_message_text(
        "Welcome back! Choose an option from the menu below:",
        reply_markup=InlineKeyboardMarkup([ 
            [InlineKeyboardButton("\U0001F50D Analyze Token", callback_data='analyze_token')],
            [InlineKeyboardButton("\U0001F6E1 Rug Pull Scanner", callback_data='rug_pull_scan')],
           # [InlineKeyboardButton("\U0001F4C8 Top Boosted Tokens", callback_data='top_tokens')],
            [InlineKeyboardButton("\U0001F6AA Exit", callback_data='exit')]
        ])
    )

# Main function to start the bot
def main():
    """Start the bot."""
    application = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(analyze_token, pattern="^analyze_token$"))
    application.add_handler(CallbackQueryHandler(rug_pull_scan, pattern="^rug_pull_scan$"))
    application.add_handler(CallbackQueryHandler(top_tokens, pattern="^top_tokens$"))
    application.add_handler(CallbackQueryHandler(full_token_analysis, pattern="^full_analysis$"))
    application.add_handler(CallbackQueryHandler(go_back_to_menu, pattern="^go_back_to_menu$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_token_address))

    application.run_polling()

if __name__ == "__main__":
    main()
