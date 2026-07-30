import re
import uuid
from dataclasses import asdict, dataclass
from typing import List, Optional, Union

import requests
from PIL import Image

from uniparser_tools.api.transport import (
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_SYNC_REQUEST_TIMEOUT,
    RequestTimeout,
    UniParserHTTPTransport,
)
from uniparser_tools.common.constant import (
    FormatFlag,
    IntEnum,
    Language,
    OrderingMethod,
    ParseMode,
    ParseModeTextual,
    StatusFlag,
)
from uniparser_tools.utils.image import dump_image_base64_str


def int_enum_factory(items):
    return {k: int(v) if isinstance(v, IntEnum) else v for k, v in items}


@dataclass
class TriggerFileData:
    token: str
    lang: Language
    sync: bool
    textual: Union[ParseModeTextual, bool]
    table: Union[ParseMode, bool]
    molecule: Union[ParseMode, bool]
    chart: Union[ParseMode, bool]
    figure: Union[ParseMode, bool]
    expression: Union[ParseMode, bool]
    equation: Union[ParseMode, bool]
    pages: List[int] = None
    ordering_method: OrderingMethod = OrderingMethod.XYCutExp
    callback_url: str = None
    callback_secret: str = None


@dataclass
class TriggerURLData:
    url: str
    token: str
    lang: Language
    sync: bool
    textual: Union[ParseModeTextual, bool]
    table: Union[ParseMode, bool]
    molecule: Union[ParseMode, bool]
    chart: Union[ParseMode, bool]
    figure: Union[ParseMode, bool]
    expression: Union[ParseMode, bool]
    equation: Union[ParseMode, bool]
    pages: List[int] = None
    ordering_method: OrderingMethod = OrderingMethod.XYCutExp
    proxy: str = None
    callback_url: str = None
    callback_secret: str = None


@dataclass
class GetResultData:
    token: str
    content: bool
    objects: bool
    pages_dict: bool
    pages_tree: bool
    molecule_source: bool


@dataclass
class GetFormattedData:
    token: str
    content: bool
    objects: bool
    pages_dict: bool
    pages_tree: bool
    molecule_source: bool
    textual: FormatFlag
    table: FormatFlag
    molecule: FormatFlag
    chart: FormatFlag
    figure: FormatFlag
    expression: FormatFlag
    equation: FormatFlag
    marginalia: bool


class UniParserClient:
    def __init__(
        self,
        host: str,
        api_key: str,
        *,
        request_timeout: RequestTimeout = DEFAULT_REQUEST_TIMEOUT,
        sync_request_timeout: RequestTimeout = DEFAULT_SYNC_REQUEST_TIMEOUT,
        session: Optional[requests.Session] = None,
    ):
        self._transport = UniParserHTTPTransport(
            host,
            api_key,
            request_timeout=request_timeout,
            session=session,
        )
        self.api_key = api_key
        self.user = uuid.uuid5(uuid.NAMESPACE_DNS, self.api_key)
        self.host = self._transport.host
        self.request_timeout = request_timeout
        self.sync_request_timeout = sync_request_timeout

    def close(self):
        self._transport.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _trigger_http_timeout(self, sync: bool):
        return self.sync_request_timeout if sync else self.request_timeout

    @property
    def trigger_file_endpoint(self):
        return f"{self.host}/trigger-file-async"

    @property
    def trigger_url_endpoint(self):
        return f"{self.host}/trigger-url-async"

    @property
    def trigger_snip_endpoint(self):
        return f"{self.host}/trigger-snip-async"

    @property
    def get_result_endpoint(self):
        return f"{self.host}/get-result"

    @property
    def get_formatted_endpoint(self):
        return f"{self.host}/get-formatted"

    def to_token(self, task_id: str):
        token = uuid.uuid5(self.user, task_id).hex
        return token

    def validate_token(self, token: str):
        assert re.match(r"^[-\._?=&a-zA-Z0-9]{1,128}$", token), f"token: {token} contains illegal characters"

    def health(self):
        return self._transport.request("GET", "/health", error_message="health check failed")

    def version(self):
        return self._transport.request("GET", "/version", error_message="version request failed")

    def trigger_file(
        self,
        file_path: str,
        token: str = None,
        lang: Language = Language.Unknown,
        sync: bool = True,
        textual: Union[ParseModeTextual, bool] = ParseModeTextual.DigitalExported,
        table: Union[ParseMode, bool] = ParseMode.Disable,
        molecule: Union[ParseMode, bool] = ParseMode.Disable,
        chart: Union[ParseMode, bool] = ParseMode.Disable,
        figure: Union[ParseMode, bool] = ParseMode.Disable,
        expression: Union[ParseMode, bool] = ParseMode.Disable,
        equation: Union[ParseMode, bool] = ParseMode.Disable,
        pages: List[int] = None,
        ordering_method: OrderingMethod = OrderingMethod.GapTree,
        callback_url: str = None,
        callback_secret: str = None,
        **kwargs,
    ):
        """
        sync: True=同步解析，该请求会在解析完成后才返回; False=异步解析，该请求会立即返回，解析结果需要通过GetResult接口获取
        callback_url: 异步解析完成后的回调地址
        callback_secret: 回调验证密钥
        """
        if not token:
            token = self.to_token(file_path)
        self.validate_token(token)
        trigger_data = TriggerFileData(
            token=token,
            lang=lang,
            sync=sync,
            textual=textual,
            table=table,
            molecule=molecule,
            chart=chart,
            figure=figure,
            expression=expression,
            equation=equation,
            pages=pages,
            ordering_method=ordering_method,
            callback_url=callback_url,
            callback_secret=callback_secret,
        )

        try:
            data = asdict(trigger_data, dict_factory=int_enum_factory)
            with open(file_path, "rb") as file_obj:
                return self._transport.request(
                    "POST",
                    "/trigger-file-async",
                    files={"file": file_obj},
                    data=data,
                    timeout=self._trigger_http_timeout(sync),
                    error_message="trigger file failed",
                    token=token,
                )
        except OSError as exc:
            return {
                "status": StatusFlag.Error,
                "token": token,
                "message": "trigger file failed",
                "description": str(exc),
                "error_type": type(exc).__name__,
            }

    def trigger_snip(
        self,
        snip_path: str,
        token: str = None,
        lang: Language = Language.Unknown,
        sync: bool = True,
        textual: Union[ParseModeTextual, bool] = ParseModeTextual.DigitalExported,
        table: Union[ParseMode, bool] = ParseMode.Disable,
        molecule: Union[ParseMode, bool] = ParseMode.Disable,
        chart: Union[ParseMode, bool] = ParseMode.Disable,
        figure: Union[ParseMode, bool] = ParseMode.Disable,
        expression: Union[ParseMode, bool] = ParseMode.Disable,
        equation: Union[ParseMode, bool] = ParseMode.Disable,
        pages: List[int] = None,
        ordering_method: OrderingMethod = OrderingMethod.GapTree,
        callback_url: str = None,
        callback_secret: str = None,
        **kwargs,
    ):
        if not token:
            token = self.to_token(snip_path)
        self.validate_token(token)
        trigger_data = TriggerFileData(
            token=token,
            lang=lang,
            sync=sync,
            textual=textual,
            table=table,
            molecule=molecule,
            chart=chart,
            figure=figure,
            expression=expression,
            equation=equation,
            pages=pages,
            ordering_method=ordering_method,
            callback_url=callback_url,
            callback_secret=callback_secret,
        )

        try:
            with Image.open(snip_path) as source_image:
                img = dump_image_base64_str(source_image.convert("RGB"))
            data = {"img": img, **asdict(trigger_data, dict_factory=int_enum_factory)}
            return self._transport.request(
                "POST",
                "/trigger-snip-async",
                data=data,
                timeout=self._trigger_http_timeout(sync),
                error_message="trigger snip failed",
                token=token,
            )
        except (OSError, ValueError) as exc:
            return {
                "status": StatusFlag.Error,
                "token": token,
                "message": "trigger snip failed",
                "description": str(exc),
                "error_type": type(exc).__name__,
            }

    def trigger_url(
        self,
        pdf_url: str,
        token: str = None,
        lang: Language = Language.Unknown,
        sync: bool = True,
        textual: Union[ParseModeTextual, bool] = ParseModeTextual.DigitalExported,
        table: Union[ParseMode, bool] = ParseMode.Disable,
        molecule: Union[ParseMode, bool] = ParseMode.Disable,
        chart: Union[ParseMode, bool] = ParseMode.Disable,
        figure: Union[ParseMode, bool] = ParseMode.Disable,
        expression: Union[ParseMode, bool] = ParseMode.Disable,
        equation: Union[ParseMode, bool] = ParseMode.Disable,
        pages: List[int] = None,
        ordering_method: OrderingMethod = OrderingMethod.GapTree,
        proxy: str = None,
        callback_url: str = None,
        callback_secret: str = None,
        **kwargs,
    ):
        if not token:
            token = self.to_token(pdf_url)
        self.validate_token(token)
        trigger_data = TriggerURLData(
            url=pdf_url,
            token=token,
            lang=lang,
            sync=sync,
            textual=textual,
            table=table,
            molecule=molecule,
            chart=chart,
            figure=figure,
            expression=expression,
            equation=equation,
            pages=pages,
            ordering_method=ordering_method,
            proxy=proxy,
            callback_url=callback_url,
            callback_secret=callback_secret,
        )
        data = asdict(trigger_data, dict_factory=int_enum_factory)
        return self._transport.request(
            "POST",
            "/trigger-url-async",
            json=data,
            timeout=self._trigger_http_timeout(sync),
            error_message="trigger url failed",
            token=token,
        )

    def get_result(
        self,
        token: str,
        content: bool = False,
        objects: bool = False,
        pages_dict: bool = False,
        pages_tree: bool = False,
        molecule_source: bool = False,
    ):
        data = GetResultData(
            token=token,
            content=content,
            objects=objects,
            pages_dict=pages_dict,
            pages_tree=pages_tree,
            molecule_source=molecule_source,
        )
        payload = asdict(data, dict_factory=int_enum_factory)
        return self._transport.request(
            "POST",
            "/get-result",
            json=payload,
            error_message="get result failed",
            token=token,
        )

    def get_formatted(
        self,
        token: str,
        content: bool = False,
        objects: bool = False,
        pages_dict: bool = False,
        pages_tree: bool = False,
        molecule_source: bool = False,
        textual: FormatFlag = FormatFlag.Markdown,
        table: FormatFlag = FormatFlag.Markdown,
        molecule: FormatFlag = FormatFlag.Markdown,
        chart: FormatFlag = FormatFlag.Markdown,
        figure: FormatFlag = FormatFlag.Markdown,
        expression: FormatFlag = FormatFlag.Markdown,
        equation: FormatFlag = FormatFlag.Markdown,
        marginalia: bool = False,
    ):
        data = GetFormattedData(
            token=token,
            content=content,
            objects=objects,
            pages_dict=pages_dict,
            pages_tree=pages_tree,
            molecule_source=molecule_source,
            textual=textual,
            table=table,
            molecule=molecule,
            chart=chart,
            figure=figure,
            expression=expression,
            equation=equation,
            marginalia=marginalia,
        )
        payload = asdict(data, dict_factory=int_enum_factory)
        return self._transport.request(
            "POST",
            "/get-formatted",
            json=payload,
            error_message="get formatted failed",
            token=token,
        )
