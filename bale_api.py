import aiohttp
import logging
from typing import Optional, Dict, Any, List, Union
from config import BALE_BASE_URL

logger = logging.getLogger("BaleAPI")

class BaleBotClient:
    def __init__(self, base_url: str = BALE_BASE_URL):
        self.base_url = base_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=50, keepalive_timeout=60)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _post(self, method: str, data: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        session = await self.get_session()
        url = f"{self.base_url}/{method}"
        try:
            if files:
                form = aiohttp.FormData()
                if data:
                    for k, v in data.items():
                        if v is not None:
                            form.add_field(k, str(v))
                for k, v in files.items():
                    form.add_field(k, v)
                async with session.post(url, data=form) as resp:
                    return await resp.json()
            else:
                async with session.post(url, json=data or {}) as resp:
                    return await resp.json()
        except Exception as e:
            logger.error(f"Error calling {method}: {e}")
            return {"ok": False, "error": str(e)}

    async def get_me(self) -> Dict[str, Any]:
        session = await self.get_session()
        async with session.get(f"{self.base_url}/getMe") as resp:
            return await resp.json()

    async def send_message(
        self,
        chat_id: Union[int, str],
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: Optional[str] = "HTML"
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        res = await self._post("sendMessage", payload)
        if not res.get("ok") and parse_mode:
            logger.warning(f"sendMessage failed with parse_mode={parse_mode}: {res}; retrying plain text")
            payload.pop("parse_mode", None)
            res = await self._post("sendMessage", payload)
        return res

    async def edit_message_text(
        self,
        chat_id: Union[int, str],
        message_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: Optional[str] = "HTML"
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        res = await self._post("editMessageText", payload)
        if not res.get("ok"):
            desc = str(res.get("description") or "").lower()
            if parse_mode and ("parse" in desc or "entity" in desc or "html" in desc or "tag" in desc):
                logger.warning(f"editMessageText HTML parse error: {res}; retrying plain text")
                payload.pop("parse_mode", None)
                res = await self._post("editMessageText", payload)
        return res

    async def send_photo(
        self,
        chat_id: Union[int, str],
        photo_bytes: bytes,
        caption: Optional[str] = None,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        data = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption
        if reply_markup:
            import json
            data["reply_markup"] = json.dumps(reply_markup)
        files = {"photo": photo_bytes}
        return await self._post("sendPhoto", data=data, files=files)

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False
    ) -> Dict[str, Any]:
        payload = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text:
            payload["text"] = text
        return await self._post("answerCallbackQuery", payload)

    async def get_updates(self, offset: Optional[int] = None, timeout: int = 25) -> Dict[str, Any]:
        session = await self.get_session()
        params = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        try:
            async with session.get(f"{self.base_url}/getUpdates", params=params) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"Error fetching updates: {e}")
            return {"ok": False, "result": []}
