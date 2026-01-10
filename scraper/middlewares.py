import time
from typing import Optional
import scrapy
from scrapy.http import Request, Response


class RespectRetryAfterMiddleware:
    def process_response(self, request: Request, response: Response, spider: scrapy.Spider) -> Response:
        if response.status != 503:
            return response
        retry_after = response.headers.get(b"Retry-After")
        if not retry_after:
            return response
        wait_seconds = self._parse_retry_after(retry_after)
        if wait_seconds and wait_seconds > 0:
            spider.logger.info(
                "retry-after header detected: sleeping for %s seconds",
                wait_seconds
            )
            time.sleep(wait_seconds)
        return response

    @staticmethod
    def _parse_retry_after(header_value: bytes) -> Optional[int]:
        try:
            return int(header_value.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            try:
                return int(float(header_value.decode("utf-8")))
            except (ValueError, UnicodeDecodeError):
                return None