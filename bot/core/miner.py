import json
import time
import asyncio
import dateutil.parser
from base64 import b64decode
from urllib.parse import quote, unquote
from typing import Any, Tuple, Optional, Dict, List

import aiohttp
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from pyrogram import Client
from pyrogram.errors import Unauthorized, UserDeactivated, AuthKeyUnregistered
from pyrogram.raw.functions.messages import RequestWebView

from bot.utils import logger
from bot.exceptions import InvalidSession
from .headers import headers
from bot.config import settings


class Miner:
    def __init__(self, tg_client: Client):
        self.session_name = tg_client.name
        self.tg_client = tg_client

    async def get_tg_web_data(self, proxy: str | None) -> str:
        try:
            if proxy:
                proxy = Proxy.from_str(proxy)
                proxy_dict = dict(
                    scheme=proxy.protocol,
                    hostname=proxy.host,
                    port=proxy.port,
                    username=proxy.login,
                    password=proxy.password
                )
            else:
                proxy_dict = None

            self.tg_client.proxy = proxy_dict

            if not self.tg_client.is_connected:
                try:
                    await self.tg_client.connect()
                except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
                    raise InvalidSession(self.session_name)

            web_view = await self.tg_client.invoke(RequestWebView(
                peer=await self.tg_client.resolve_peer('TimeFarmCryptoBot'),
                bot=await self.tg_client.resolve_peer('TimeFarmCryptoBot'),
                platform='android',
                from_bot_menu=False,
                url='https://tg-tap-miniapp.laborx.io/'
            ))

            auth_url = web_view.url
            tg_web_data = unquote(
                string=unquote(
                    string=auth_url.split('tgWebAppData=', maxsplit=1)[1].split('&tgWebAppVersion', maxsplit=1)[0]))

            res = ""
            qparams = tg_web_data.split("&")
            for param in qparams:
                vals = param.split("=")
                if vals[0] == "user":
                   res += f"{vals[0]}={quote(vals[1])}&"
                else:
                    res += f"{vals[0]}={vals[1]}&"

            if self.tg_client.is_connected:
                await self.tg_client.disconnect()

            return res[:-1]

        except InvalidSession as error:
            raise error

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error during Authorization: {error}")
            await asyncio.sleep(delay=7)

    async def validate_init(self, http_client: aiohttp.ClientSession, tg_web_data: str) -> Dict[str, Any]:
        body = json.dumps({
            'initData': tg_web_data,
            'platform': 'android'
        })

        try:
            async with http_client.request(
                    method="POST",
                    url="https://tg-bot-tap.laborx.io/api/v1/auth/validate-init/v2",
                    data=body,
            ) as response:
                response_json = await response.json()
                return response_json
        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error while getting account status: {error}")
            await asyncio.sleep(delay=7)

    async def link(self, http_client: aiohttp.ClientSession) -> Dict[str, Any]:
        try:
            async with http_client.request(
                    method="GET",
                    url="https://tg-bot-tap.laborx.io/api/v1/referral/link",
            ) as response:
                response_json = await response.json()

            return response_json
        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error while getting link: {error}")
            await asyncio.sleep(delay=7)

    async def info(self, http_client: aiohttp.ClientSession) -> Dict[str, Any]:
        try:
            async with http_client.request(
                    method="GET",
                    url="https://tg-bot-tap.laborx.io/api/v1/farming/info",
            ) as response:
                response_json = await response.json()

            return response_json
        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error while getting info: {error}")
            await asyncio.sleep(delay=7)

    async def claim(self, http_client: aiohttp.ClientSession) -> Dict[str, Any]:
        try:
            response = await http_client.post(
                url="https://tg-bot-tap.laborx.io/api/v1/farming/finish",
                json={}
            )
            response.raise_for_status()
            response_json = await response.json()

            return response_json
        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error while claiming: {error}")
            await asyncio.sleep(delay=7)

    async def start(self, http_client: aiohttp.ClientSession) -> Dict[str, Any]:
        try:
            response = await http_client.post(
                url="https://tg-bot-tap.laborx.io/api/v1/farming/start",
                json={}
            )
            response.raise_for_status()

            response_json = await response.json()

            return response_json
        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error while claiming: {error}")
            await asyncio.sleep(delay=7)

    async def upgrade(self, http_client: aiohttp.ClientSession) -> Dict[str, Any]:
        try:
            response = await http_client.post(
                url="https://tg-bot-tap.laborx.io/api/v1/me/level/upgrade",
                json={}
            )
            response.raise_for_status()

            response_json = await response.json()

            return response_json
        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error while upgrading: {error}")
            await asyncio.sleep(delay=7)

    def is_claim_possible(self, info: Dict[str, Any]) -> bool:
        if not info:
            return False

        last_claim_timestamp = dateutil.parser.parse(info['activeFarmingStartedAt']).timestamp()
        current_time = time.time()
        diff = current_time - last_claim_timestamp
        if diff >= settings.DEFAULT_SLEEP:
            return True
        return False

    def is_upgrade_possible(self, info: Dict[str, Any], balance: int) -> bool:
        if not info:
            return False

        current_level = info['info']['level']
        levels = info['levelDescriptions']
        if not levels:
            return False

        upgr = None
        for level in levels:
            level_level = int(level['level'])
            if level_level == current_level + 1:
                upgr = level
                break

        if not upgr:
            return False

        # current_balance = info['balanceInfo']['balance']
        upgrade_price = upgr['price']
        if balance < upgrade_price:
            return False

        return True

    def get_expire_from_token(self, token: str) -> int:
        parts = token.split(".")

        base64_message = parts[1]
        if base64_message[-2:] != "==":
            base64_message += "=="

        base64_bytes = base64_message.encode('ascii')
        message_bytes = b64decode(base64_bytes)
        message = message_bytes.decode('ascii')

        payload = json.loads(message)
        return payload['exp']

    def get_sleep_time(self, info: Dict[str, Any]) -> int:
        farming_start_timestamp = dateutil.parser.parse(info['activeFarmingStartedAt']).timestamp()
        next_claim_timestamp = farming_start_timestamp + int(info['farmingDurationInSec'])

        diff = next_claim_timestamp - time.time()
        if diff < 0:
            return settings.DEFAULT_SLEEP
        return int(diff)

    async def check_proxy(self, http_client: aiohttp.ClientSession, proxy: Proxy) -> None:
        try:
            response = await http_client.get(url='https://httpbin.org/ip', timeout=aiohttp.ClientTimeout(5))
            ip = (await response.json()).get('origin')
            logger.info(f"{self.session_name} | Proxy IP: {ip}")
        except Exception as error:
            logger.error(f"{self.session_name} | Proxy: {proxy} | Error: {error}")

    async def run(self, proxy: str | None) -> None:
        expire_time = 0
        access_token = None
        sleep_time = settings.DEFAULT_SLEEP
        proxy_conn = ProxyConnector().from_url(proxy) if proxy else None

        async with (aiohttp.ClientSession(headers=headers, connector=proxy_conn) as http_client):
            if proxy:
                await self.check_proxy(http_client=http_client, proxy=proxy)

            while True:
                try:
                    if not access_token or (expire_time != 0 and time.time() >= expire_time):
                        tg_web_data = await self.get_tg_web_data(proxy=proxy)
                        account_info = await self.validate_init(http_client=http_client, tg_web_data=tg_web_data)
                        access_token = account_info['token']
                        expire_time = self.get_expire_from_token(access_token)

                        http_client.headers["Authorization"] = f"Bearer {access_token}"
                        headers["Authorization"] = f"Bearer {access_token}"

                    if account_info:
                        balance = int(account_info['balanceInfo']['balance'])
                        logger.info(f"{self.session_name} | Balance is <c>{balance}</c>")

                        # simulating web client behavior
                        info = await self.info(http_client=http_client)
                        await self.link(http_client=http_client)

                        if self.is_claim_possible(info=info):
                            claim_info = await self.claim(http_client=http_client)
                            if claim_info:
                                balance = claim_info['balance']
                                logger.success(f"{self.session_name} | Claimed successfully, new balance is <c>{balance}</c>")
                                await self.info(http_client=http_client)

                                start_info = await self.start(http_client=http_client)
                                await self.info(http_client=http_client)
                                sleep_time = self.get_sleep_time(info=start_info)
                        else:
                            sleep_time = self.get_sleep_time(info=info)

                        if self.is_upgrade_possible(account_info, balance):
                            upgrade_info = await self.upgrade(http_client=http_client)
                            if upgrade_info:
                                balance = upgrade_info['balance']
                                level = upgrade_info['level']
                                logger.success(f"{self.session_name} | Upgraded successfully to level {level}, new balance is <c>{balance}</c>")

                                await self.info(http_client=http_client)

                except InvalidSession as error:
                    raise error

                except Exception as error:
                    logger.error(f"{self.session_name} | Unknown error: {error}")
                    await asyncio.sleep(delay=7)

                else:
                    logger.info(f"{self.session_name} | Sleeping for the next claim {sleep_time}s")
                    await asyncio.sleep(delay=sleep_time)


async def run_miner(tg_client: Client, proxy: str | None):
    try:
        await Miner(tg_client=tg_client).run(proxy=proxy)
    except InvalidSession:
        logger.error(f"{tg_client.name} | Invalid Session")